"""The contract documents themselves (decision 1, AC-07, AC-08).

Two OpenAPI files and three JSON Schemas are the published contract. These tests
prove the documents are structurally what the specs say, that the validator really
notices when they weaken, and that the deferred OTA envelope stays deferred.
"""

from __future__ import annotations

import ast
import copy
import pathlib
import json
import re
import shutil
from typing import Final
from pathlib import Path

import pytest

from tools.contracts import bounds as bounds_module
from tools.contracts import errors as E
from tools.contracts.api_model import ALL_OPERATIONS
from tools.contracts.openapi_check import (
    check_headers_contract,
    check_manifest_component,
    check_openapi,
    check_ota_deferral,
    check_shared_error_envelope,
    load_media_schemas,
)
from tools.contracts.schema_docs import load_json, load_yaml, resolve_refs, schema_error_report
from tools.contracts.validate import validate_contracts

from conftest import CORPUS_MUTATIONS, REPO_ROOT

CONTRACTS = REPO_ROOT / "contracts"

#: Device routes interfaces.md §2-§6 assigns.
DEVICE_PATHS = (
    "/pair",
    "/tokens/revoke",
    "/capabilities",
    "/status",
    "/settings",
    "/time",
    "/preview",
    "/clips",
    "/clips/{clip_id}/manifest",
    "/clips/{clip_id}/leases",
    "/leases/{lease_id}",
    "/clips/{clip_id}/files/{name}",
    "/ota",
    "/events",
    "/events/{event_id}",
)

#: Backend routes interfaces.md §7-§9 assigns.
BACKEND_PATHS = (
    "/tokens",
    "/tokens/{id}",
    "/devices",
    "/clips",
    "/clips/{clip_id}",
    "/clips/{clip_id}/files/{name}",
    "/uploads",
    "/uploads/{id}",
    "/uploads/{id}/files/{name}",
    "/uploads/{id}/commit",
    "/events",
    "/events/{id}",
    "/jobs",
    "/jobs/{id}",
    "/derivatives/{id}",
    "/derivatives/{id}/file",
    "/health/live",
    "/health/ready",
)


@pytest.fixture(scope="module")
def device() -> dict:
    return load_yaml(CONTRACTS / "device-v1.yaml")


@pytest.fixture(scope="module")
def backend() -> dict:
    return load_yaml(CONTRACTS / "backend-v1.yaml")


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    """A disposable copy of the contracts tree, for mutation experiments."""
    target = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, target)
    return target


def test_media_schemas_load_and_pass_their_meta_schema() -> None:
    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    assert set(schemas) == {"frame", "manifest", "active"}


def test_a_broken_media_schema_is_reported(tmp_path: Path) -> None:
    media_dir = tmp_path / "contracts" / "media-v1"
    media_dir.mkdir(parents=True)
    shutil.copy(CONTRACTS / "media-v1" / "manifest.schema.json", media_dir)
    shutil.copy(CONTRACTS / "media-v1" / "active-record.schema.json", media_dir)
    (media_dir / "frame-record.schema.json").write_text("{ not json", encoding="utf-8")

    _schemas, violations = load_media_schemas(media_dir)
    assert {violation.code for violation in violations} == {E.SCHEMA_DOCUMENT_INVALID}


def test_device_document_declares_every_documented_route(device: dict) -> None:
    assert device["openapi"] == "3.1.0"
    assert device["servers"][0]["url"] == "https://vdog.local/api/v1"
    for path in DEVICE_PATHS:
        assert path in device["paths"], path
    assert not check_openapi("device", device)
    assert not check_headers_contract(device, "device")


def test_backend_document_declares_every_documented_route(backend: dict) -> None:
    assert backend["openapi"] == "3.1.0"
    assert backend["servers"][0]["url"] == "https://backend.local/api/v1"
    for path in BACKEND_PATHS:
        assert path in backend["paths"], path
    assert not check_openapi("backend", backend)
    assert not check_headers_contract(backend, "backend")


def test_every_operation_in_the_table_is_in_the_yaml(device: dict, backend: dict) -> None:
    documents = {"device": device, "backend": backend}
    for key, operation in ALL_OPERATIONS.items():
        item = documents[operation.contract]["paths"][operation.path][operation.method.lower()]
        assert item["operationId"] == operation.operation_id, key


def test_dropping_a_documented_response_is_detected(device: dict) -> None:
    weakened = copy.deepcopy(device)
    del weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["416"]
    codes = {violation.code for violation in check_openapi("device", weakened)}
    assert E.SPEC_STATUS_MISSING in codes


def test_adding_an_undocumented_response_is_detected(device: dict) -> None:
    weakened = copy.deepcopy(device)
    weakened["paths"]["/status"]["get"]["responses"]["418"] = {"description": "teapot"}
    codes = {violation.code for violation in check_openapi("device", weakened)}
    assert E.SPEC_STATUS_UNDOCUMENTED in codes


def test_dropping_bearer_security_is_detected(device: dict) -> None:
    weakened = copy.deepcopy(device)
    weakened["paths"]["/status"]["get"]["security"] = []
    codes = {violation.code for violation in check_openapi("device", weakened)}
    assert E.SPEC_SECURITY_MISSING in codes


def test_optional_chunk_body_is_detected(backend: dict) -> None:
    """A binary chunk body the document marks optional is a defect, not a free choice.

    The PATCH has no named JSON schema, so the ``$ref`` binding check never runs for it
    and ``requestBody.required`` is the only member that says the bytes are mandatory.
    An optional body documents an append of no bytes at all, and a client generated from
    it would send exactly that.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"]["required"] = False
    found = check_openapi("backend", weakened)
    assert E.SPEC_STRUCTURE_MISSING in {violation.code for violation in found}
    named = [violation for violation in found if E.SPEC_STRUCTURE_MISSING == violation.code]
    assert any(
        "PATCH /uploads/{id}/files/{name}" in violation.location
        and violation.location.endswith("requestBody")
        for violation in named
    ), named
    # OpenAPI's default for an absent ``required`` is false, so the omitted spelling names
    # the same unrequired body a generated client would honour.
    omitted = copy.deepcopy(backend)
    del omitted["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"]["required"]
    assert E.SPEC_STRUCTURE_MISSING in {violation.code for violation in check_openapi("backend", omitted)}


def test_optional_upload_checksum_is_detected(backend: dict) -> None:
    """A declared-but-optional required header is refused, and unlike an absent one.

    Matching name and location alone accepted this: an optional ``Upload-Checksum`` is a
    chunk nobody hashed, and the two failures need different words because only one of
    them is a document that stopped declaring the header at all.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["parameters"]["UploadChecksum"]["required"] = False
    found = check_openapi("backend", weakened)
    named = [violation for violation in found if E.SPEC_STRUCTURE_MISSING == violation.code]
    checksum = [violation for violation in named if "parameters/Upload-Checksum" in violation.location]
    assert checksum, named
    assert any("optional" in violation.detail for violation in checksum), checksum
    # The other half of the distinction: dropping the declaration entirely reports the
    # absence, and never the "declared but optional" wording.
    absent = copy.deepcopy(backend)
    patch = absent["paths"]["/uploads/{id}/files/{name}"]["patch"]
    patch["parameters"] = [
        parameter
        for parameter in patch["parameters"]
        if parameter.get("$ref") != "#/components/parameters/UploadChecksum"
    ]
    absent_found = [
        violation
        for violation in check_openapi("backend", absent)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "parameters/Upload-Checksum" in violation.location
    ]
    assert absent_found, named
    assert all("optional" not in violation.detail for violation in absent_found), absent_found


def test_an_unreadable_parameter_declaration_is_a_finding_not_a_crash(backend: dict) -> None:
    """A required header whose `$ref` goes nowhere is refused, not raised.

    The PATCH declares each of its three headers as a `$ref` to a shared component, so a
    document whose component is missing used to reach the CLI as exit 2 "validator internal
    error" — the one outcome that leaves the missing header unreported, which is the whole
    thing this check exists to say.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    del weakened["components"]["parameters"]["UploadChecksum"]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "parameters/Upload-Checksum" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    # An unreadable declaration is the absent case, never the "declared but optional" one.
    assert all("optional" not in violation.detail for violation in found), found


def test_an_unreadable_request_body_pointer_is_a_finding_not_a_crash(backend: dict) -> None:
    """A `requestBody` whose pointer misfires is refused too, whatever the way it fails.

    ``resolve_refs`` raises for a missing member, a list index out of range, a scalar it is
    asked to subscript and a pointer that is not a local one; the body check also has to
    survive a pointer that lands on a value that is not an object. All five are documents
    with a defect, and each has to come back as the finding the body checks already know
    how to write rather than as the CLI's exit 2 "validator internal error".
    """
    assert not check_openapi("backend", backend)
    for broken in (
        {"$ref": "#/components/requestBodies/Absent"},
        {"$ref": "#/paths/~1uploads~1{id}~1files~1{name}/patch/tags/9"},
        {"$ref": "#/components/parameters/UploadChecksum/schema/type"},
        {"$ref": "#/components/parameters/UploadChecksum/schema/type/deeper"},
        {"$ref": "https://example.invalid/body"},
    ):
        weakened = copy.deepcopy(backend)
        weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"] = broken
        found = [
            violation
            for violation in check_openapi("backend", weakened)
            if E.SPEC_STRUCTURE_MISSING == violation.code
            and "PATCH /uploads/{id}/files/{name} requestBody" in violation.location
        ]
        assert found, broken


def test_a_stored_detail_may_still_omit_its_expiry(backend: dict) -> None:
    """The deadline is required while receiving and remains optional afterwards.

    The corpus pins the refusal half; nothing pinned that a `stored` answer may still arrive
    without the member, so hoisting `expires_at` into the schema's own `required` — which
    would refuse every stored and expired detail — would have reddened nothing.
    """
    schema = resolve_refs(backend["components"]["schemas"]["UploadDetail"], root=backend)
    detail = {
        "v": 1,
        "upload_id": "upl_0000000000000000000000000000001",
        "state": "stored",
        "offsets": {"video.mjpg": 512, "frames.jsonl": 0},
    }
    assert not schema_error_report(schema, detail)
    assert not schema_error_report(schema, {**detail, "expires_at": None})
    receiving = {**detail, "state": "receiving"}
    assert schema_error_report(schema, receiving), "a receiving detail without an expiry must be refused"


def test_a_response_that_points_at_nothing_is_a_finding_not_a_crash(backend: dict) -> None:
    """Every 401 is a `$ref` to the shared component, so deleting it must be reported.

    Following a pointer into a member the document does not define raises, and an internal
    error escaping the CLI would leave the absence itself unreported — the one thing this
    check exists to say.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    del weakened["components"]["responses"]["Unauthorized"]
    found = check_openapi("backend", weakened)
    assert E.SPEC_COMPONENT_DRIFT in {violation.code for violation in found}
    named = [violation for violation in found if E.SPEC_COMPONENT_DRIFT == violation.code]
    assert any("responses/401" in violation.location for violation in named), named


def test_a_response_that_is_not_an_object_is_a_finding_not_a_crash(device: dict) -> None:
    weakened = copy.deepcopy(device)
    weakened["paths"]["/status"]["get"]["responses"]["200"] = "not a response"
    found = check_openapi("device", weakened)
    assert E.SPEC_COMPONENT_DRIFT in {violation.code for violation in found}


# --- Round 11: the expired 200, the optional required headers, the parameter gate ---


def test_expired_detail_is_refused_from_the_200_schema(backend: dict) -> None:
    """A 200 detail names a live or committed session; `expired` belongs to the 410.

    The shared `UploadState` still spells all three states — `expired` is the name the
    documented refusal carries (interfaces.md §8 step 5, corpus
    `upload-get-response-410-expired`) — but the success schema of `GET /uploads/{id}`
    narrows it: a session the spec only ever answers with a 410 may not be described
    by a 200. The corpus ships the refusal as `backend/invalid/upload-get-response-200-expired`;
    the two permissive halves below (receiving with its deadline, stored with or
    without one) guard the narrowing against over-tightening into refusing the very
    answers the spec requires.
    """
    schema = resolve_refs(backend["components"]["schemas"]["UploadDetail"], root=backend)
    receiving = {
        "v": 1,
        "upload_id": "upl_0000000000000000000000000000001",
        "state": "receiving",
        "offsets": {"video.mjpg": 512, "frames.jsonl": 0},
        "expires_at": "2026-03-05T12:00:00.000Z",
    }
    assert not schema_error_report(schema, receiving)
    stored = {**receiving, "state": "stored"}
    assert not schema_error_report(schema, stored)
    assert not schema_error_report(
        schema, {key: value for key, value in stored.items() if key != "expires_at"}
    )
    report = schema_error_report(schema, {**receiving, "state": "expired"})
    assert report, "an expired detail must be refused by the 200 schema"
    assert any(
        keyword == "enum" and "expired" in message for _property, keyword, message in report
    ), report


def test_optional_required_response_header_is_detected(backend: dict) -> None:
    """A response header the spec requires may not be declared optional.

    The loop compared header *names*, so flipping the mandatory `Upload-Offset`
    component to `required: false` — OpenAPI's Header Object default — left the gate at
    zero findings while a generated client learned that the offset answer may omit its
    offset. Every promise of the operation table has to survive the flip: the HEAD 200
    carries both offset components and the PATCH carries `Upload-Offset` on its 204 and
    its offset-conflict 409.
    """
    assert not check_openapi("backend", backend)
    expected = {
        "UploadOffset": (
            "backend-v1 HEAD /uploads/{id}/files/{name} responses/200 headers/Upload-Offset",
            "backend-v1 PATCH /uploads/{id}/files/{name} responses/204 headers/Upload-Offset",
            "backend-v1 PATCH /uploads/{id}/files/{name} responses/409 headers/Upload-Offset",
        ),
        "UploadLength": (
            "backend-v1 HEAD /uploads/{id}/files/{name} responses/200 headers/Upload-Length",
        ),
    }
    for component, subjects in expected.items():
        for mutate, spelling in (
            (False, "optional"),
            (None, "omitted (OpenAPI defaults a header to optional)"),
        ):
            weakened = copy.deepcopy(backend)
            if mutate is None:
                del weakened["components"]["headers"][component]["required"]
            else:
                weakened["components"]["headers"][component]["required"] = mutate
            found = [
                violation
                for violation in check_openapi("backend", weakened)
                if E.SPEC_STRUCTURE_MISSING == violation.code
            ]
            for subject in subjects:
                named = [violation for violation in found if violation.location.endswith(subject)]
                assert named, (component, spelling, subject, [v.render() for v in found])
                assert all("optional" in violation.detail for violation in named), named


def test_optional_bearer_challenge_is_detected(backend: dict) -> None:
    """The review's own probe: an optional `WwwAuthenticate` is refused on every 401.

    A 401 that does not say how to authenticate is not a challenge (RFC 9110 §15.5.2),
    and the table demands the header on every documented 401 — the name-only comparison
    accepted the component flipped to `required: false` on all of them at once.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["headers"]["WwwAuthenticate"]["required"] = False
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
    ]
    assert found, "an optional challenge must be refused"
    assert all(
        violation.location.endswith("responses/401 headers/WWW-Authenticate")
        for violation in found
    ), [violation.render() for violation in found]
    assert any("HEAD /uploads/{id}/files/{name}" in violation.location for violation in found), (
        "the bodyless HEAD refusal declares the challenge inline and must be refused too",
        [violation.render() for violation in found],
    )


def test_an_unreadable_required_response_header_is_a_finding_not_a_crash(backend: dict) -> None:
    """A required header whose component vanished is refused, not raised.

    The HEAD 200 declares both offset headers as `$ref`s to shared components; a
    document missing one used to reach the CLI as exit 2 "validator internal error",
    leaving the header this check exists to demand unreported.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    del weakened["components"]["headers"]["UploadLength"]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location.endswith(
            "HEAD /uploads/{id}/files/{name} responses/200 headers/Upload-Length"
        )
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    # An unreadable declaration is never reported as the "declared but optional" defect.
    assert all("optional" not in violation.detail for violation in found), found


def test_optional_device_response_headers_are_detected(device: dict) -> None:
    """The device file download loses its name just as quietly — every status pays.

    interfaces.md §4 assigns `Accept-Ranges`, `ETag`, `Content-Length` to the 200 and
    those plus `Content-Range` to the 206; the shared 416 carries only its optional
    unsatisfied `Content-Range` — a separate component — so nothing outside the two
    range answers depends on these components.
    """
    assert not check_openapi("device", device)
    expectations = {
        "AcceptRanges": ("Accept-Ranges", ("200", "206")),
        "ETagSha256": ("ETag", ("200", "206")),
        "ContentLength": ("Content-Length", ("200", "206")),
        "ContentRange": ("Content-Range", ("206",)),
    }
    for component, (header, statuses) in expectations.items():
        weakened = copy.deepcopy(device)
        weakened["components"]["headers"][component]["required"] = False
        found = [
            violation
            for violation in check_openapi("device", weakened)
            if E.SPEC_STRUCTURE_MISSING == violation.code
        ]
        for status in statuses:
            subject = (
                f"device-v1 GET /clips/{{clip_id}}/files/{{name}} "
                f"responses/{status} headers/{header}"
            )
            named = [violation for violation in found if violation.location.endswith(subject)]
            assert named, (component, subject, [violation.render() for violation in found])
            assert all("optional" in violation.detail for violation in named), named
        if component == "ContentRange":
            # The 416's optional `Content-Range` rides `ContentRangeUnsatisfied`, a
            # component apart from the granted one: flipping the granted half's
            # required flag may not reach the refusal, which proves the two spellings
            # are modelled apart.
            assert all("416" not in violation.location for violation in found), found


def test_granted_and_unsatisfied_content_range_are_modelled_apart(
    device: dict, backend: dict
) -> None:
    """A granted window and an unsatisfied refusal are different fields (RFC 9110 §14.4).

    The 206 answers `bytes <first>-<last>/<total>` and nothing else — the `*/` form
    promises no bytes and belongs to the refusal alone. The shared 416 may answer
    `bytes */<total>` to report the current representation's length and may omit the
    header entirely, so its declaration carries no `required` flag. Each spelling is
    its own component, and the documents stay silent under the full gate either way.
    """
    from tools.contracts.schema_docs import DRAFT202012_VALIDATOR

    download_routes = {
        "device": [("/clips/{clip_id}/files/{name}", "get")],
        "backend": [("/clips/{clip_id}/files/{name}", "get"), ("/derivatives/{id}/file", "get")],
    }
    for contract, document in (("device", device), ("backend", backend)):
        assert not check_openapi(contract, document)
        for path, method in download_routes[contract]:
            operation = document["paths"][path][method]
            granted = resolve_refs(
                operation["responses"]["206"]["headers"]["Content-Range"], root=document
            )
            assert granted["required"] is True, (contract, path, method)
            assert DRAFT202012_VALIDATOR(granted["schema"]).is_valid("bytes 0-1023/1712")
            assert not DRAFT202012_VALIDATOR(granted["schema"]).is_valid("bytes */1712")
            refusal = resolve_refs(operation["responses"]["416"], root=document)
            unsatisfied = refusal["headers"]["Content-Range"]
            assert "required" not in unsatisfied, (
                "the 416 may refuse without the header, so it must stay at OpenAPI's "
                "optional default",
                unsatisfied,
            )
            assert DRAFT202012_VALIDATOR(unsatisfied["schema"]).is_valid("bytes */1712")
            assert not DRAFT202012_VALIDATOR(unsatisfied["schema"]).is_valid("bytes 0-1023/1712")


def test_documented_optional_response_header_stays_optional(device: dict) -> None:
    """The preview `Cache-Control` is documented-optional and the gate says nothing.

    The checker enforces required-ness only where the operation table demands presence;
    a header the contract merely documents stays a permitted answer, so neither the
    shipped spelling (no flag) nor its opposite may raise a finding.
    """
    assert not check_openapi("device", device)
    flagged = copy.deepcopy(device)
    flagged["components"]["headers"]["CacheControlNoStore"]["required"] = True
    assert not check_openapi("device", flagged)


def test_dropping_a_spec_pinned_query_parameter_is_detected(backend: dict) -> None:
    """A clip route may not silently lose the `device_id` that disambiguates its id.

    interfaces.md §9 scopes every clip-keyed backend route by `device_id`; the gate
    walked only `required_request_headers`, so deleting the `DeviceIdQuery` entry from
    `GET /clips/{clip_id}` passed with zero findings and a generated client lost the
    disambiguator.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    get = weakened["paths"]["/clips/{clip_id}"]["get"]
    get["parameters"] = [
        parameter
        for parameter in get["parameters"]
        if parameter.get("$ref") != "#/components/parameters/DeviceIdQuery"
    ]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/device_id" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    # Absent is its own defect, never the "declared but optional" wording.
    assert all("optional" not in violation.detail for violation in found), found


def test_optional_device_id_query_is_detected(backend: dict) -> None:
    """Declared-but-optional is refused on every route the spec scopes by `device_id`."""
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["parameters"]["DeviceIdQuery"]["required"] = False
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith("parameters/device_id")
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert all("optional" in violation.detail for violation in found), found
    # The three clip-scoped routes of interfaces.md §9 all name it.
    assert len({violation.location.split(" parameters/")[0] for violation in found}) == 3, found


def test_a_dangling_parameter_ref_is_a_drift_finding_not_a_crash(backend: dict) -> None:
    """A parameter `$ref` going nowhere is the document's defect, not exit 2.

    The review pointed the clip-file route's `Range` at
    `#/components/parameters/RangeMissing` and the gate certified the document: the
    OpenAPI documents were never scanned for reference integrity at all.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    parameters = weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["parameters"]
    parameters[:] = [
        {"$ref": "#/components/parameters/RangeMissing"}
        if parameter.get("$ref") == "#/components/parameters/Range"
        else parameter
        for parameter in parameters
    ]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location == "backend-v1 GET /clips/{clip_id}/files/{name} parameters"
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert any("RangeMissing" in violation.detail for violation in found), found


def test_duplicate_parameter_declaration_is_detected(backend: dict) -> None:
    """One name per location is an Operation Object rule, not a suggestion.

    The review appended a second, required integer `device_id` query to
    `GET /clips/{clip_id}` and a lowercase `idempotency-key` twin to the upload
    initialisation's required `Idempotency-Key` header, and the gate certified both
    documents: `_required_request_parameter` asks whether *every* match is required,
    so a twin passes whenever both members happen to be. The duplicate read comes
    from the parameter list itself, before any required interpretation, and a header
    twin colliding under HTTP's case-insensitive names is found just the same.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["parameters"].append(
        {"name": "device_id", "in": "query", "required": True, "schema": {"type": "integer"}}
    )
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith("parameters/device_id")
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert all("duplicate" in violation.detail for violation in found), found
    # Required twins are refused by the list itself, never the "declared but
    # optional" wording the required-ness walk reserves for optional members.
    assert all("optional" not in violation.detail for violation in found), found

    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads"]["post"]["parameters"].append(
        {"name": "idempotency-key", "in": "header", "required": True, "schema": {"type": "string"}}
    )
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith("parameters/idempotency-key")
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert all("duplicate" in violation.detail for violation in found), found


def test_duplicate_response_header_is_detected(backend: dict) -> None:
    """A response may not declare one header twice under two spellings.

    Header names are case-insensitive (RFC 9110 §5.1), so a lowercase
    `upload-offset` beside the required `Upload-Offset` `$ref` on the upload HEAD's
    200 is one header declared twice — and `_resolved_header` reads only the first
    spelling, so the second member was never read at all. The refusal comes from the
    header map itself, raised while the shared component still carries its
    `required: true` flag.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    headers = weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["200"]["headers"]
    headers["upload-offset"] = {"schema": {"type": "string"}}
    assert weakened["components"]["headers"]["UploadOffset"]["required"] is True
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith(
            "HEAD /uploads/{id}/files/{name} responses/200 headers/Upload-Offset"
        )
    ]
    assert len(found) == 1, [violation.render() for violation in found]
    assert "upload-offset" in found[0].detail and "Upload-Offset" in found[0].detail, found[0]


def test_dropping_a_path_parameter_is_detected(backend: dict) -> None:
    """Every `{placeholder}` must keep its required path parameter.

    The document key already proves the route is named `/clips/{clip_id}`; without
    this rule a document could drop the `ClipIdPath` entry and the gate would call the
    route complete while a generated client could not fill in the id.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    get = weakened["paths"]["/clips/{clip_id}"]["get"]
    get["parameters"] = [
        parameter
        for parameter in get["parameters"]
        if parameter.get("$ref") != "#/components/parameters/ClipIdPath"
    ]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/clip_id" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]


def test_an_inline_parameter_without_a_name_is_a_finding(backend: dict) -> None:
    """A parameter entry that is not a usable parameter object is refused, either spelling."""
    assert not check_openapi("backend", backend)
    for broken in ({"in": "query"}, "not a parameter"):
        weakened = copy.deepcopy(backend)
        weakened["paths"]["/clips/{clip_id}"]["get"]["parameters"].append(broken)
        found = [
            violation
            for violation in check_openapi("backend", weakened)
            if E.SPEC_STRUCTURE_MISSING == violation.code
            and violation.location == "backend-v1 GET /clips/{clip_id} parameters"
        ]
        assert found, (broken, [violation.render() for violation in check_openapi("backend", weakened)])


def test_a_null_parameters_member_is_a_finding_not_a_crash(backend: dict) -> None:
    """A `parameters` member that is not a list is named, never raised as exit 2.

    The integrity loop now reads every operation's parameters, so a document that
    spells the member as `null` used to reach the CLI as "validator internal error" —
    the module's own design rule says a malformed member is a finding first.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["parameters"] = None
    found = check_openapi("backend", weakened)
    named = [
        violation
        for violation in found
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == "backend-v1 GET /clips/{clip_id} parameters"
        and "not a list" in violation.detail
    ]
    assert named, [violation.render() for violation in found]
    # The member declares nothing, so the required inputs it hid read as missing too.
    assert any(
        E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/device_id" in violation.location
        for violation in found
    ), [violation.render() for violation in found]


def test_a_null_response_headers_member_is_a_finding_not_a_crash(device: dict) -> None:
    """A documented-optional response's `headers: null` is refused, not raised."""
    assert not check_openapi("device", device)
    weakened = copy.deepcopy(device)
    weakened["paths"]["/preview"]["get"]["responses"]["200"]["headers"] = None
    found = [
        violation
        for violation in check_openapi("device", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith("responses/200 headers/Cache-Control")
    ]
    assert found, [violation.render() for violation in check_openapi("device", weakened)]


def test_an_optional_twin_of_a_required_parameter_is_detected(backend: dict) -> None:
    """A second, optional declaration may not hide behind the required first one.

    OpenAPI requires names to be unique per location, and the gate enforces no such
    uniqueness; the old first-match rule returned ``ok`` on the required entry and
    certified the optional twin a generated client may still drop. Every match has to
    carry `required: true`.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["parameters"].append(
        {"name": "device_id", "in": "query", "required": False, "schema": {"type": "string"}}
    )
    # The list gate refuses this twin as a duplicate declaration whatever its
    # ``required`` flag says (pinned by test_duplicate_parameter_declaration_is_detected);
    # the finding *here* is the required-ness walk's own, which still has to name the
    # optional twin even with the duplicate finding beside it.
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/device_id" in violation.location
        and "duplicate declaration" not in violation.detail
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert all("optional" in violation.detail for violation in found), found


# --- Round 13: the unreadable response and header nodes, the 204 length, the folding header ---


def test_a_dangling_error_response_ref_is_reported_where_it_sits(backend: dict) -> None:
    """An error status the operation table never speaks for still has to be read.

    The three table loops resolve only the statuses they name, so
    `GET /clips/{clip_id}`'s 404 — no named schema, no promised header — was read
    by nothing: repointing its `$ref` at a component the document never defined
    produced zero findings from the checker and the full gate alike. The
    all-response scan reads every response the operation carries and names the
    unreadable one at the status where it sits; deleting the shared component
    every 404 points at names each of those operations in turn.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "$ref": "#/components/responses/NoSuchResponse"
    }
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location.endswith("GET /clips/{clip_id} responses/404")
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert any("NoSuchResponse" in violation.detail for violation in found), found
    # The same refusal for pointers the full read refuses outright: only local
    # `#/...` references are walkable, and the shallow hop mirrors that guard,
    # so a dropped-slash typo cannot quietly resolve at one depth and vanish.
    for typo in ("#components/responses/NotFound", "components/responses/NotFound"):
        weakened = copy.deepcopy(backend)
        weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {"$ref": typo}
        found = [
            violation
            for violation in check_openapi("backend", weakened)
            if E.SPEC_COMPONENT_DRIFT == violation.code
            and violation.location.endswith("GET /clips/{clip_id} responses/404")
        ]
        assert found, (typo, [v.render() for v in check_openapi("backend", weakened)])
    # One dangling component is one finding per operation+status: no exact repeat.
    all_found = check_openapi("backend", weakened)
    identities = [(violation.code, violation.location, violation.detail) for violation in all_found]
    assert len(identities) == len(set(identities)), [violation.render() for violation in all_found]

    # The same refusal when the shared component itself vanishes: every backend
    # route whose 404 pointed at `NotFound` is named at its own status.
    referring = sorted(
        f"{operation.method} {operation.path}"
        for operation in ALL_OPERATIONS.values()
        if operation.key.startswith("backend.")
        and (
            backend["paths"].get(operation.path, {})
            .get(operation.method.lower(), {})
            .get("responses", {})
            .get("404")
            == {"$ref": "#/components/responses/NotFound"}
        )
    )
    assert referring, "the document must still answer 404 from the shared component"
    weakened = copy.deepcopy(backend)
    del weakened["components"]["responses"]["NotFound"]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location.endswith("responses/404")
        and "NotFound" in violation.detail
    ]
    for subject in referring:
        assert any(subject in violation.location for violation in found), (subject, found)


def test_an_unreadable_optional_response_header_ref_is_a_drift_finding(
    device: dict, backend: dict
) -> None:
    """A header the table never lists is still a declared node that must resolve.

    The required-ness loop resolves only the headers the operation table lists and
    the documented loop compares *names* alone, so the shared 416's optional
    `Content-Range` — one component shared by the device file download and both
    backend download routes, listed nowhere in the table — was never read:
    dangling its `$ref` earned the documents nothing. The all-response scan reads
    every declared header node and names the unreadable one at the member itself.
    """
    assert not check_openapi("device", device)
    assert not check_openapi("backend", backend)
    subjects = {
        "device": ("GET /clips/{clip_id}/files/{name}",),
        "backend": ("GET /clips/{clip_id}/files/{name}", "GET /derivatives/{id}/file"),
    }
    for contract, routes in subjects.items():
        document = device if contract == "device" else backend
        weakened = copy.deepcopy(document)
        weakened["components"]["responses"]["RangeNotSatisfiable"]["headers"]["Content-Range"] = {
            "$ref": "#/components/headers/ContentRangeAbsent"
        }
        found = check_openapi(contract, weakened)
        named = [
            violation
            for violation in found
            if E.SPEC_COMPONENT_DRIFT == violation.code
            and "responses/416 headers/Content-Range" in violation.location
            and "ContentRangeAbsent" in violation.detail
        ]
        assert len(named) == len(routes), (contract, [v.render() for v in found])
        for route in routes:
            assert any(route in violation.location for violation in named), (contract, route, named)
        # Nothing else speaks: the shared component was the only defect.
        assert len(found) == len(routes), [violation.render() for violation in found]


def test_content_length_declared_on_a_204_is_refused(
    device: dict, backend: dict
) -> None:
    """A 204 answers without a payload, so its document may not promise a length.

    The no-body loop refused `content` on a 204 but read nothing of the header
    map: declaring `Content-Length` on the upload commit's 204 — the same field
    `api_validate._rule_content_length` refuses on the wire (RFC 9110 §8.6) — was
    certified, teaching a generated client to expect bytes the status can never
    carry. The refusal is the status's own: a HEAD answer legitimately reports the
    length its GET would have sent, and every committed 200/206 declaration of
    `Content-Length` stays silent.
    """
    assert not check_openapi("backend", backend)
    for spelling in ("Content-Length", "content-length"):
        weakened = copy.deepcopy(backend)
        weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["responses"]["204"]["headers"][
            spelling
        ] = {"description": "x", "schema": {"type": "integer"}}
        found = check_openapi("backend", weakened)
        assert len(found) == 1, [violation.render() for violation in found]
        violation = found[0]
        assert E.SPEC_STRUCTURE_MISSING == violation.code, violation
        assert violation.location.endswith(
            "PATCH /uploads/{id}/files/{name} responses/204 headers/Content-Length"
        ) or violation.location.endswith(
            "PATCH /uploads/{id}/files/{name} responses/204 headers/content-length"
        ), violation
        assert "8.6" in violation.detail and "payload" in violation.detail, violation
    # Controls: the 204 is the only refusal. A HEAD answer may declare the length
    # its GET would have sent, and the committed range answers already do.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["200"]["headers"][
        "Content-Length"
    ] = {"description": "x", "schema": {"type": "integer"}}
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if "content-length" in violation.location.lower()
    ]
    assert not found, [violation.render() for violation in found]
    # The device 200/206 and the backend 200/206 declare `Content-Length` today,
    # and the rule keeps them silent — the control is only real because those
    # declarations exist, so pin that too.
    assert not check_openapi("device", device)
    assert "Content-Length" in device["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]["headers"]
    assert "Content-Length" in device["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["200"]["headers"]
    assert "Content-Length" in backend["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["200"]["headers"]
    assert "Content-Length" in backend["paths"]["/derivatives/{id}/file"]["get"]["responses"]["200"]["headers"]


def test_a_required_request_header_name_folds_case(backend: dict) -> None:
    """Required request headers match the way HTTP matches field names.

    `_required_request_parameter` compared `name` verbatim for every location, so
    respelling `UploadChecksum`'s name as `upload-checksum` — the same field per
    RFC 9110 §5.1, `required: true` intact — made the checker demand a header the
    document *does* require, while the round-12 duplicate-identity gate and the
    wire validator already folded. Path and query names are URI elements, not
    field names: the `Clip_Id` and `DEVICE_ID` renames below stay missing.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["parameters"]["UploadChecksum"]["name"] = "upload-checksum"
    assert weakened["components"]["parameters"]["UploadChecksum"]["required"] is True
    found = check_openapi("backend", weakened)
    assert not found, [violation.render() for violation in found]

    weakened = copy.deepcopy(backend)
    weakened["components"]["parameters"]["ClipIdPath"]["name"] = "Clip_Id"
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/clip_id" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert any(violation.detail.startswith("the spec requires this path parameter") for violation in found)

    weakened = copy.deepcopy(backend)
    weakened["components"]["parameters"]["DeviceIdQuery"]["name"] = "DEVICE_ID"
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "GET /clips/{clip_id} parameters/device_id" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert any(
        violation.detail.startswith("the spec requires this query parameter") for violation in found
    )


def test_malformed_response_member_shapes_are_read_or_named(backend: dict) -> None:
    """The all-response scan never leaves a node unread *and* unnamed.

    Three shapes outside valid OpenAPI pin the scan's fail-closed boundary: a
    two-hop `$ref` chain whose far member dangles is named at the response the
    operation carries (the hop cannot see the broken header, and silence at both
    depths is the defect this round died on); a ``headers`` member that is not a
    name map but hides a dangling `$ref` inside is likewise named at the
    response; and a ``headers`` member that is itself one `$ref` node earns no
    spurious name-keyed finding, because it declares no names — the table loops
    read that same shape through the full resolution.
    """
    assert not check_openapi("backend", backend)
    # (a) Two-hop chain, clean then dangling: the chain alone certifies, and
    # breaking the far header names the response the operation actually carries.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["ChainRef"] = {
        "$ref": "#/components/responses/RangeNotSatisfiable"
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "$ref": "#/components/responses/ChainRef"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]
    weakened["components"]["responses"]["RangeNotSatisfiable"]["headers"]["Content-Range"] = {
        "$ref": "#/components/headers/ContentRangeAbsent"
    }
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and "GET /clips/{clip_id} responses/404" in violation.location
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]

    # (b) A non-map headers member hiding a dangling ref is named at the response.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "description": "gone",
        "headers": [{"$ref": "#/components/headers/AbsentOne"}],
    }
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and "GET /clips/{clip_id} responses/404" in violation.location
        and "AbsentOne" in violation.detail
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]

    # (c) A `$ref` headers member declares no names: no name-keyed finding, and
    # the full read reads it just as the table loops do. The Error body it
    # carries is the round-15 envelope gate's demand for this documented status;
    # the pin here is the `$ref` member's silence, not a bodyless 404.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "description": "gone",
        "headers": {"$ref": "#/components/headers/ContentLength"},
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


# --- Round 14: the guarded media-type read, the declared header map, the parse-time key ---


def test_a_dangling_download_206_ref_is_named_not_raised(backend: dict) -> None:
    """Round 14 finding 1: the media-type loop is a guarded response read.

    The download operation's table entry promises `application/octet-stream` on
    the 206, so the media-type comparison used to follow that status' pointer
    unguarded: repointing the committed inline 206 at a component the document
    never defined raised ``KeyError`` past the report, and the CLI called the
    whole run a "validator internal error" with exit 2. The all-response scan
    already names the unreadable node at the status where it sits; the loop has
    to reuse that guarded resolution and skip the comparison once it failed —
    and the report may not state the surviving finding twice.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"] = {
        "$ref": "#/components/responses/NoSuchPartial"
    }
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location.endswith("GET /clips/{clip_id}/files/{name} responses/206")
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]
    assert any("NoSuchPartial" in violation.detail for violation in found), found
    triples = [
        (violation.code, violation.location, violation.detail)
        for violation in check_openapi("backend", weakened)
    ]
    assert len(triples) == len(set(triples)), "one finding may not be stated twice"


def _shared_404_operations(document: dict) -> list[str]:
    """Every ``METHOD /path`` whose document node points at the shared NotFound."""
    operations: list[str] = []
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            node = responses.get("404")
            if isinstance(node, dict) and node.get("$ref") == "#/components/responses/NotFound":
                operations.append(f"{method.upper()} {path}")
    return operations


def test_a_declared_response_headers_member_must_be_a_map(backend: dict) -> None:
    """Round 14 finding 2: a declared ``headers`` member is shape-checked always.

    The shared backend 404 declares no mandatory header, so the required-ness
    and documented loops never read its header map, and the all-response scan —
    which alone reads every response — silently accepted a member that is not a
    map at all: a `headers: []` on `components.responses.NotFound` produced
    zero findings from the checker and the full gate alike. OpenAPI's Response
    Object defines ``headers`` as a Map, so the scan refuses any other declared
    shape at the response, naming the actual type, on every operation carrying
    the status. Two round-13 pins survive the refusal untouched: a `$ref`
    Mapping member declares no names and stays silent when it resolves, and a
    dangling ref hiding inside a list keeps its own component drift.
    """
    assert not check_openapi("backend", backend)
    for malformed, spelling in (([], "list"), (5, "int")):
        weakened = copy.deepcopy(backend)
        weakened["components"]["responses"]["NotFound"]["headers"] = malformed
        report = check_openapi("backend", weakened)
        violations = [
            violation
            for violation in report
            if E.SPEC_STRUCTURE_MISSING == violation.code
            and violation.location.endswith(" responses/404 headers")
        ]
        assert violations, [violation.render() for violation in report]
        assert all(spelling in violation.detail for violation in violations), violations
        located = {violation.location for violation in violations}
        expected = {
            f"backend-v1 {operation} responses/404 headers"
            for operation in _shared_404_operations(backend)
        }
        assert expected <= located, sorted(expected - located)
        assert "backend-v1 GET /clips/{clip_id} responses/404 headers" in located
        # The refused member is the only 404-headers finding the run reports:
        # the shape refusal names the member, and nothing else starts reading
        # a map the document never declared as one.
        assert located == expected, sorted(located ^ expected)

    # Pin (round 13): a `$ref` headers member is a Mapping that declares no
    # names — resolvable, it stays totally silent, exactly as before the
    # shape check existed.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["headers"] = {
        "$ref": "#/components/headers/ContentLength"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # Pin (round 13): the non-map member stays refused *and* a dangling ref
    # inside it keeps its own drift at the response, never swallowed by the
    # shape finding beside it.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["headers"] = [
        {"$ref": "#/components/headers/AbsentOne"}
    ]
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location.endswith("GET /clips/{clip_id} responses/404")
        and "AbsentOne" in violation.detail
    ]
    assert found, [violation.render() for violation in check_openapi("backend", weakened)]


def test_a_broken_header_ref_does_not_swallow_the_media_type_mismatch(backend: dict) -> None:
    """Round 14 rework: one broken pointer never silences a coexisting finding.

    The media-type comparison reads only the ``content`` *keys*, and a media
    type name carries no reference — yet the round-14 guarded read reached for
    the full resolution, so a response whose own pointer resolves fine while a
    *header* component inside it vanished lost its ``publishes …, the operation
    table carries …`` diagnostic beside the component drift it coexists with.
    The loop therefore reads through the response's own pointer hop only. Both
    shapes — an inline table-listed status and one pointing at a shared
    component — have to earn the drift naming the dangling header *and* the
    content mismatch, at every status the operation table carries types for.
    """
    assert not check_openapi("backend", backend)
    where = "backend-v1 GET /clips/{clip_id}/files/{name} responses/206"
    binary = {"schema": {"type": "string", "format": "binary"}}

    # (a) Inline table-listed status: dangling header ref inside the map, and
    # the published media type flipped away from the operation table's.
    weakened = copy.deepcopy(backend)
    download = weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]
    download["headers"] = [{"$ref": "#/components/headers/AbsentOne"}]
    download["content"] = {"text/plain": binary}
    report = check_openapi("backend", weakened)
    drift = [
        violation
        for violation in report
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location == where
        and "AbsentOne" in violation.detail
    ]
    mismatch = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == f"{where} content"
        and "text/plain" in violation.detail
        and "application/octet-stream" in violation.detail
    ]
    assert drift, [violation.render() for violation in report]
    assert mismatch, [violation.render() for violation in report]

    # (b) The same status pointing at a shared component: the component's own
    # pointer resolves, only a header inside it dangles — the full read fails
    # and the media comparison must run anyway off the one-hop node.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["Partial206"] = {
        "description": "Requested single byte range.",
        "headers": [{"$ref": "#/components/headers/AbsentOne"}],
        "content": {"text/plain": binary},
    }
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"] = {
        "$ref": "#/components/responses/Partial206"
    }
    report = check_openapi("backend", weakened)
    drift = [
        violation
        for violation in report
        if E.SPEC_COMPONENT_DRIFT == violation.code
        and violation.location == where
        and "AbsentOne" in violation.detail
    ]
    mismatch = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == f"{where} content"
        and "text/plain" in violation.detail
        and "application/octet-stream" in violation.detail
    ]
    assert drift, [violation.render() for violation in report]
    assert mismatch, [violation.render() for violation in report]


# --- Round 15: the shared-envelope binding gate, declared-header shape, scalar content ---


def test_an_unbound_error_status_must_publish_the_shared_error_envelope(
    backend: dict, device: dict
) -> None:
    """Round 15 P3-1: the document answers unbound errors like the fixtures do.

    ``api_validate`` selects ``operation.response_schemas.get(status) or "Error"``
    (api_validate.py:631): a documented refusal the table does not bind its own
    schema to is checked against the shared ``Error`` envelope. The document
    checker's binding loop walked only the table's bound statuses, so the
    review's two mutations — ``GET /clips/{clip_id}``' 404 reduced to a
    description, or 404 publishing the operation's own ``StoredClip`` —
    certified with zero findings. Every documented error status the table does
    not bind now has to publish exactly ``#/components/schemas/Error``. The
    status the table does bind (the settings 409 with its dedicated schema)
    keeps the binding loop's comparison, unbound-and-bodyless HEAD refusals
    stay the method's own answer, and no committed operation trips the gate.
    """
    assert not check_openapi("backend", backend)
    assert not check_openapi("device", device)

    # (a) The review's mutation (a): a bodyless 404 is a document that no
    # longer answers the status the contract says it answers.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "description": "Resource was never known."
    }
    report = check_openapi("backend", weakened)
    found = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == "backend-v1 GET /clips/{clip_id} responses/404"
    ]
    assert found, [violation.render() for violation in report]
    assert any(
        "Error envelope" in violation.detail and "no response body" in violation.detail
        for violation in found
    ), found

    # (b) The review's mutation (b): a 404 publishing the 200's schema binds a
    # body the contract never assigned that status.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "description": "Resource was never known.",
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/StoredClip"}}
        },
    }
    report = check_openapi("backend", weakened)
    found = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == "backend-v1 GET /clips/{clip_id} responses/404"
    ]
    assert found, [violation.render() for violation in report]
    assert any(
        "StoredClip" in violation.detail and "instead of Error" in violation.detail
        for violation in found
    ), found

    # (c) The whole shared component answers with a foreign schema: every
    # operation carrying the status names it, one statement per operation.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/StoredClip"}
    report = check_openapi("backend", weakened)
    located = {
        violation.location
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and "instead of Error" in violation.detail
        and violation.location.endswith(" responses/404")
    }
    expected = {
        f"backend-v1 {operation} responses/404"
        for operation in _shared_404_operations(backend)
    }
    assert expected <= located, sorted(expected - located)

    # (d) The dedicated-schema comparison is untouched: the settings 409 is
    # bound in the table, so flipping its body to the shared envelope earns
    # the binding loop's verdict for *that* schema, not this loop's Error rule.
    weakened = copy.deepcopy(device)
    weakened["paths"]["/settings"]["put"]["responses"]["409"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/Error"}
    report = check_openapi("device", weakened)
    found = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith("PUT /settings responses/409")
    ]
    assert found, [violation.render() for violation in report]
    assert any(
        "instead of SettingsRevisionConflictResponse" in violation.detail
        for violation in found
    ), found


def test_a_bodyless_head_refusal_is_the_method_s_own_answer(backend: dict) -> None:
    """Round 15: the envelope gate keeps a HEAD refusal bodyless-legal.

    ``content_types_for`` answers a HEAD refusal with "no content" (RFC 9110
    §9.3.2), and the committed ``headUploadFile`` refusals are exactly that:
    status and headers alone. The new gate may not demand a body the method
    forbids — but a HEAD that *does* publish one still earns the round-13
    no-body loop's refusal, and binding the wrong schema names both defects.
    """
    assert not check_openapi("backend", backend)
    head = backend["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]
    for status in ("401", "404", "410"):
        assert "content" not in head[status], status

    # A bodyless refusal stays fully silent (the document pin above proves it
    # for all three); adding the shared envelope earns exactly the pre-existing
    # HEAD refusal — the binding question itself answers "Error", correctly.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["404"]["content"] = {
        "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
    }
    report = check_openapi("backend", weakened)
    found = [
        violation
        for violation in report
        if violation.location.endswith("HEAD /uploads/{id}/files/{name} responses/404 content")
    ]
    assert len(found) == 1, [violation.render() for violation in report]
    assert E.SPEC_STRUCTURE_MISSING == found[0].code
    assert "forbids" in found[0].detail

    # Binding the 200's schema on that same body earns both statements: the
    # no-body loop's and this gate's `binds … instead of Error`.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["404"]["content"] = {
        "application/json": {"schema": {"$ref": "#/components/schemas/StoredClip"}}
    }
    report = check_openapi("backend", weakened)
    assert any(
        "binds '#/components/schemas/StoredClip' instead of Error" in violation.detail
        and violation.location.endswith("HEAD /uploads/{id}/files/{name} responses/404")
        for violation in report
    ), [violation.render() for violation in report]
    assert any(
        "forbids" in violation.detail
        and violation.location.endswith("responses/404 content")
        for violation in report
    ), [violation.render() for violation in report]


def test_an_explicit_null_headers_member_is_named_like_a_malformed_one(
    backend: dict,
) -> None:
    """Round 15 P3-2: key presence, not truthiness, asks the shape question.

    The shared ``NotFound`` declares no mandatory header, so no presence loop
    ever read its header map, and the all-response scan's shape refusal ran
    only under ``if declared_headers is not None:`` — an explicit
    ``headers: null`` read as an omission and certified with zero findings.
    OpenAPI defines ``headers`` as a Map whatever the status carries, so a
    declared member of any other shape earns the named refusal on every
    operation carrying the status; omission and the empty map stay valid.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["headers"] = None
    report = check_openapi("backend", weakened)
    located = {
        violation.location
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location.endswith(" responses/404 headers")
    }
    expected = {
        f"backend-v1 {operation} responses/404 headers"
        for operation in _shared_404_operations(backend)
    }
    assert expected <= located, sorted(expected - located)
    assert located == expected, sorted(located ^ expected)
    assert all(
        "is NoneType, not a map of declared header names" in violation.detail
        for violation in report
        if violation.location in located
    ), [violation.render() for violation in report]

    # Omission (the committed document) and the empty map are both valid: the
    # Map may simply name no header.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["headers"] = {}
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_an_alias_component_cannot_hide_a_malformed_headers_member(
    backend: dict,
) -> None:
    """Round 15 item 3: the two-hop branch owes the member the shape verdict.

    A response component that is a pure ``$ref`` to another response leaves the
    all-response scan's shallow node without the member, and the two-hop branch
    read only the name map from the full resolution — a target declaring
    ``headers: null`` (round 14's recorded escape) was certified. The branch
    now judges presence on the full-resolved response too.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["AliasHop"] = {
        "$ref": "#/components/responses/NullHeaderTarget"
    }
    weakened["components"]["responses"]["NullHeaderTarget"] = {
        "description": "Resource was never known.",
        "headers": None,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
        },
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "$ref": "#/components/responses/AliasHop"
    }
    report = check_openapi("backend", weakened)
    found = [
        violation
        for violation in report
        if E.SPEC_STRUCTURE_MISSING == violation.code
        and violation.location == "backend-v1 GET /clips/{clip_id} responses/404 headers"
    ]
    assert found, [violation.render() for violation in report]
    assert "is NoneType, not a map of declared header names" in found[0].detail


def test_a_pure_ref_alias_component_still_publishes_the_table_media_types(
    backend: dict,
) -> None:
    """Round 15 item 3: the media-type loop follows pure-`$ref` alias chains.

    A table-listed status pointed at a component that is nothing but a
    ``$ref`` stopped the loop's one hop at the alias — which carries no
    ``content`` member — and the operation was charged a ``publishes []``
    mismatch against types the document does publish behind the alias. Each
    hop past the first is guarded the same way, so a chain that cannot be
    followed stays the all-response scan's drift alone.
    """
    assert not check_openapi("backend", backend)
    where = "backend-v1 GET /clips/{clip_id}/files/{name} responses/206"
    weakened = copy.deepcopy(backend)
    download = weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]
    weakened["components"]["responses"]["Partial206Real"] = copy.deepcopy(download)
    weakened["components"]["responses"]["Partial206Alias"] = {
        "$ref": "#/components/responses/Partial206Real"
    }
    weakened["components"]["responses"]["Partial206Outer"] = {
        "$ref": "#/components/responses/Partial206Alias"
    }
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"] = {
        "$ref": "#/components/responses/Partial206Outer"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # A chain whose far end dangles: named once by the scan, and the media
    # comparison skips rather than stack a mismatch beside the drift.
    weakened["components"]["responses"]["Partial206Real"] = {
        "$ref": "#/components/responses/NoSuchPartial"
    }
    report = check_openapi("backend", weakened)
    drift = [
        violation
        for violation in report
        if E.SPEC_COMPONENT_DRIFT == violation.code and violation.location == where
    ]
    assert drift and any("NoSuchPartial" in violation.detail for violation in drift), [
        violation.render() for violation in report
    ]
    assert not [
        violation
        for violation in report
        if "the operation table carries" in violation.detail
        and violation.location == f"{where} content"
    ], [violation.render() for violation in report]

    # `$ref`-with-siblings is the same alias to this checker's own resolution
    # semantics: resolve_refs (the full read the readability gate ran) replaces
    # the node wholesale whatever decorators ride along, so the chain may not
    # stop there and charge the operation for a member the target does publish.
    weakened = copy.deepcopy(backend)
    download = weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]
    weakened["components"]["responses"]["Partial206Real"] = copy.deepcopy(download)
    weakened["components"]["responses"]["Partial206Sibling"] = {
        "$ref": "#/components/responses/Partial206Real",
        "description": "decorated alias hop",
    }
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"] = {
        "$ref": "#/components/responses/Partial206Sibling",
        "summary": "decorated operation node",
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # The envelope loop reads through the same chain: a decorated alias in
    # front of the shared NotFound still answers with the Error envelope.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFoundSibling"] = {
        "$ref": "#/components/responses/NotFound",
        "description": "decorated alias hop",
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["404"] = {
        "$ref": "#/components/responses/NotFoundSibling"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_a_scalar_content_member_is_named_once_and_never_crashes(backend: dict) -> None:
    """Round 15 item 4: a declared `content` that is not a map earns a finding.

    ``set(response.get("content", {}))`` in the media-type loop and the
    ``"application/json" in content`` test behind ``_json_schema_ref`` both
    raise over a scalar member — a ``TypeError`` the CLI reported as exit 2
    "validator internal error" for a merely malformed document. Every such
    read now yields ``is {type}, not a media-type map`` at the member, named
    by one owner per status: the binding loop and the media-type loop name
    the same triple for a listed download status and the dedup keeps one, and
    the request-body reads answer the same way.
    """
    assert not check_openapi("backend", backend)

    # (a) The table-listed download 206: two loops read the member, the report
    # states the refusal exactly once, and no media-type mismatch piles on.
    where = "backend-v1 GET /clips/{clip_id}/files/{name} responses/206 content"
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]["content"] = 5
    report = check_openapi("backend", weakened)
    shape = [violation for violation in report if violation.location == where]
    assert len(shape) == 1, [violation.render() for violation in report]
    assert E.SPEC_STRUCTURE_MISSING == shape[0].code
    assert shape[0].detail == "is int, not a media-type map"
    assert not [
        violation
        for violation in report
        if "the operation table carries" in violation.detail
    ], [violation.render() for violation in report]

    # (b) An unbound error status: the envelope loop owns the member there.
    weakened = copy.deepcopy(backend)
    weakened["components"]["responses"]["NotFound"]["content"] = "gone"
    report = check_openapi("backend", weakened)
    shape = [
        violation
        for violation in report
        if violation.location.endswith(" responses/404 content")
    ]
    assert shape, [violation.render() for violation in report]
    assert {violation.location for violation in shape} == {
        f"backend-v1 {operation} responses/404 content"
        for operation in _shared_404_operations(backend)
    }
    assert all(violation.detail == "is str, not a media-type map" for violation in shape)

    # (c) The bound requestBody: the shape refusal replaces the crash and the
    # misleading `binds None` — nothing was ever read from the member.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads"]["post"]["requestBody"]["content"] = 5
    report = check_openapi("backend", weakened)
    shape = [
        violation
        for violation in report
        if violation.location == "backend-v1 POST /uploads requestBody content"
    ]
    assert len(shape) == 1, [violation.render() for violation in report]
    assert shape[0].detail == "is int, not a media-type map"
    assert not [
        violation for violation in report if "instead of CreateUploadRequest" in violation.detail
    ], [violation.render() for violation in report]

    # (d) A malformed `content` still declares a body: the requestBody's own
    # `required` question is independent of the member's shape, so a scalar
    # content on the raw-chunk PATCH earns both statements — the shape refusal
    # at the member and `not required` at the body.
    weakened = copy.deepcopy(backend)
    patch_body = weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"]
    patch_body["content"] = 5
    patch_body["required"] = False
    report = check_openapi("backend", weakened)
    where = "backend-v1 PATCH /uploads/{id}/files/{name}"
    shape = [
        violation
        for violation in report
        if violation.location == f"{where} requestBody content"
    ]
    assert len(shape) == 1 and shape[0].detail == "is int, not a media-type map", [
        violation.render() for violation in report
    ]
    required = [
        violation
        for violation in report
        if violation.location == f"{where} requestBody" and violation.detail == "not required"
    ]
    assert required, [violation.render() for violation in report]


def test_a_null_media_type_entry_in_a_response_is_named_once(device: dict, backend: dict) -> None:
    """Round 16 item 1: a media-type entry that is not an object earns a finding.

    Every read behind ``_media_type_map`` consults the media-type *keys*, so a
    binary entry replaced with ``null`` — the review's device download 206 —
    was invisible, and the document certified a member that is no kind of
    Media Type Object. The helper now refuses the first non-Mapping entry in
    document order; for a table-listed status the binding loop and the
    media-type loop name the identical triple and the dedup keeps exactly one
    statement, with no ``the operation table carries`` mismatch piling on. The
    backend download mirror shares the probe.
    """
    assert not check_openapi("device", device)
    assert not check_openapi("backend", backend)
    for contract, document in (("device", device), ("backend", backend)):
        weakened = copy.deepcopy(document)
        weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]["content"][
            "application/octet-stream"
        ] = None
        report = check_openapi(contract, weakened)
        where = (
            f"{contract}-v1 GET /clips/{{clip_id}}/files/{{name}} responses/206 content"
        )
        shape = [violation for violation in report if violation.location == where]
        assert len(shape) == 1, [violation.render() for violation in report]
        assert E.SPEC_STRUCTURE_MISSING == shape[0].code
        assert shape[0].detail == (
            "media type 'application/octet-stream' is NoneType, not a media-type object"
        )
        assert not [
            violation
            for violation in report
            if "the operation table carries" in violation.detail
        ], [violation.render() for violation in report]


def test_a_scalar_media_type_entry_in_a_request_body_is_named_once(backend: dict) -> None:
    """Round 16 item 1, request side: the entry refusal reaches both body kinds.

    The review's backend PATCH chunk — ``application/octet-stream`` replaced
    with ``5`` — was certified as silently as the response escape, because no
    read ever touched the entry's value. The member is now named once per
    body: the raw-chunk PATCH keeps its independent ``not required`` statement
    when the body also declares itself optional (round-15 case (d) at entry
    level), and the bound JSON body's shape refusal replaces the misleading
    ``binds None instead of …`` (round-15 case (c) at entry level).
    """
    assert not check_openapi("backend", backend)

    # (a) The raw-chunk PATCH: the member finding, plus the body's own
    # `required` verdict — the requestBody owns that question whatever shape
    # the member carries.
    where = "backend-v1 PATCH /uploads/{id}/files/{name}"
    weakened = copy.deepcopy(backend)
    patch_body = weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"]
    patch_body["content"]["application/octet-stream"] = 5
    patch_body["required"] = False
    report = check_openapi("backend", weakened)
    shape = [
        violation
        for violation in report
        if violation.location == f"{where} requestBody content"
    ]
    assert len(shape) == 1, [violation.render() for violation in report]
    assert E.SPEC_STRUCTURE_MISSING == shape[0].code
    assert shape[0].detail == (
        "media type 'application/octet-stream' is int, not a media-type object"
    )
    required = [
        violation
        for violation in report
        if violation.location == f"{where} requestBody" and violation.detail == "not required"
    ]
    assert required, [violation.render() for violation in report]

    # (b) The bound JSON body: the member is named once, and no `binds None`
    # — nor any other binding statement — piles on beside a refusal that
    # never let a read reach the schema. `required` stays true, so it stays
    # silent.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads"]["post"]["requestBody"]["content"]["application/json"] = 5
    report = check_openapi("backend", weakened)
    shape = [
        violation
        for violation in report
        if violation.location == "backend-v1 POST /uploads requestBody content"
    ]
    assert len(shape) == 1, [violation.render() for violation in report]
    assert shape[0].detail == "media type 'application/json' is int, not a media-type object"
    assert not [
        violation for violation in report if "instead of CreateUploadRequest" in violation.detail
    ], [violation.render() for violation in report]
    assert not [
        violation
        for violation in report
        if violation.location == "backend-v1 POST /uploads requestBody"
    ], [violation.render() for violation in report]


def test_an_empty_media_type_object_certifies_on_both_sides(device: dict, backend: dict) -> None:
    """Round 16 item 1: `{}` stays the legal spelling for bare content.

    OpenAPI 3.1 makes every Media Type Object member optional, so an entry
    that declares nothing beyond its own media type — the natural spelling for
    a binary body — must pass the new entry gate on both sides: the device
    download's 206 answer and the backend upload chunk's request member alike
    certify with zero findings.
    """
    weakened = copy.deepcopy(device)
    weakened["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]["content"][
        "application/octet-stream"
    ] = {}
    assert not check_openapi("device", weakened), [
        violation.render() for violation in check_openapi("device", weakened)
    ]

    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"]["content"][
        "application/octet-stream"
    ] = {}
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_a_reusable_json_response_component_binds_like_its_inline_equivalent(
    backend: dict,
) -> None:
    """Round 16 item 2: a `$ref`'d success response binds as its inline twin does.

    The full read the table loops ran inlines a shared component wholesale, so
    the schema `$ref` the binding question asks about was gone and an
    operation pointing at ``components.responses`` was charged a false
    ``binds None instead of StoredClip`` (the review's F2a). The media-type
    and binding reads now go through the shallow alias-chained node — the same
    read the envelope loop already used — so the clip-detail 200 moved verbatim
    into a shared component certifies clean, across a pure-`$ref` alias hop and
    a `$ref`-with-siblings hop as well.
    """
    assert not check_openapi("backend", backend)

    def reused(operation_node: dict) -> dict:
        weakened = copy.deepcopy(backend)
        clip200 = weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]
        weakened["components"]["responses"]["ClipDetailOK"] = copy.deepcopy(clip200)
        weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = operation_node
        return weakened

    # Direct reference to the shared component.
    weakened = reused({"$ref": "#/components/responses/ClipDetailOK"})
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # Pure-`$ref` alias hop: the alias carries no ``content`` of its own, so
    # stopping there would read the binding off an empty document.
    weakened = reused({"$ref": "#/components/responses/ClipDetailAlias"})
    weakened["components"]["responses"]["ClipDetailAlias"] = {
        "$ref": "#/components/responses/ClipDetailOK"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # `$ref`-with-siblings hop: resolve_refs (the full read the gate ran)
    # replaces the node wholesale whatever decorators ride along, so the
    # chain may not stop here either.
    weakened = reused({"$ref": "#/components/responses/ClipDetailSibling"})
    weakened["components"]["responses"]["ClipDetailSibling"] = {
        "$ref": "#/components/responses/ClipDetailOK",
        "description": "decorated alias hop",
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_a_reusable_request_body_component_binds_like_its_inline_equivalent(
    backend: dict,
) -> None:
    """Round 16 item 2: a `$ref`'d requestBody binds as its inline twin does.

    The upload-init body moved verbatim into ``components.requestBodies`` was
    charged the review's false ``binds None instead of CreateUploadRequest``
    (F2b) for the same inlining reason as the response side. The binding read
    now goes through the shallow alias-chained node — an un-followable chain
    falls back to the full read, which keeps the honest ``binds None`` — so
    the shared component certifies clean, alias hop included.
    """
    assert not check_openapi("backend", backend)

    def reused(operation_node: dict) -> dict:
        weakened = copy.deepcopy(backend)
        init_body = weakened["paths"]["/uploads"]["post"]["requestBody"]
        weakened["components"].setdefault("requestBodies", {})["CreateUploadBody"] = (
            copy.deepcopy(init_body)
        )
        weakened["paths"]["/uploads"]["post"]["requestBody"] = operation_node
        return weakened

    # Direct reference to the shared component.
    weakened = reused({"$ref": "#/components/requestBodies/CreateUploadBody"})
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    # Pure-`$ref` alias hop in front of the shared body.
    weakened = reused({"$ref": "#/components/requestBodies/CreateUploadBodyAlias"})
    weakened["components"]["requestBodies"]["CreateUploadBodyAlias"] = {
        "$ref": "#/components/requestBodies/CreateUploadBody"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_a_list_indexed_pointer_hop_still_asks_the_binding_question(backend: dict) -> None:
    """Round 16 review finding: the guarded hop mirrors ``_pointer``, lists included.

    ``resolve_refs`` — the full read the readability gate runs — walks a list
    segment by integer (:func:`tools.contracts.schema_docs._pointer`), so the
    shallow hop the binding reads take must follow one too. A
    ``#/paths/~1uploads/post/parameters/0``-style response reference lands on a
    readable node the gate certifies; had the chain refused the list segment
    where the full read did not, the loop's skip would have silently certified
    a status the pre-fix read named ``binds None instead of StoredClip``. A
    bad index is a finding, never an exception: both the out-of-range and the
    non-integer spellings collapse to the drift wording the guarded full read
    uses for an un-followable pointer.
    """
    assert not check_openapi("backend", backend)
    where = "backend-v1 GET /clips/{clip_id} responses/200"

    # A hop through a list lands on a readable node: the binding question is
    # asked of it — `binds None`, the verdict the full read gave before this
    # round, not silence.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/paths/~1uploads/post/parameters/0"
    }
    report = check_openapi("backend", weakened)
    binds = [violation for violation in report if violation.location == where]
    assert len(binds) == 1, [violation.render() for violation in report]
    assert binds[0].detail == "binds None instead of StoredClip"

    # Out-of-range and non-integer indices are un-followable by the full read
    # too, so the binding loop's gate names the drift (the all-response scan
    # emits the identical triple and the dedup keeps one) — findings, and
    # never the exception reaching the CLI as exit 2.
    for segment, reason in (
        ("9", "IndexError('list index out of range')"),
        ("x", 'ValueError("invalid literal for int() with base 10: \'x\'")'),
    ):
        weakened = copy.deepcopy(backend)
        weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
            "$ref": f"#/paths/~1uploads/post/parameters/{segment}"
        }
        report = check_openapi("backend", weakened)
        drift = [
            violation
            for violation in report
            if violation.location == where and violation.code == E.SPEC_COMPONENT_DRIFT
        ]
        assert len(drift) == 1, [violation.render() for violation in report]
        assert drift[0].detail == f"$ref cannot be followed: {reason}"


def test_a_reused_component_binding_the_wrong_schema_still_bites(backend: dict) -> None:
    """Round 16 tests 5: the shallow reads keep the binding check non-vacuous.

    Under the full read every reuse looked alike — ``binds None`` whether the
    component bound the wrong schema, a dangling one, or none. The chained
    reads must name the pointer the document actually carries: the shared
    ``Error`` envelope where ``StoredClip``/``CreateUploadRequest`` is due,
    the dangling schema through the readability gate that refuses the node
    (one drift statement naming the missing member, no ``binds`` piled on),
    and — unchanged from before this round — the collapsed full read for a
    requestBody whose own `$ref` cannot be followed, which keeps its honest
    ``not required`` + ``binds None`` pair.
    """
    assert not check_openapi("backend", backend)

    # (a) A reused 200 binding the Error envelope: the statement names the
    # wrong pointer, where the pre-fix read said only `binds None`.
    weakened = copy.deepcopy(backend)
    clip200 = weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]
    clip200["content"]["application/json"]["schema"]["$ref"] = "#/components/schemas/Error"
    weakened["components"]["responses"]["ClipDetailOK"] = clip200
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ClipDetailOK"
    }
    report = check_openapi("backend", weakened)
    binds = [
        violation
        for violation in report
        if violation.location == "backend-v1 GET /clips/{clip_id} responses/200"
        and "instead of StoredClip" in violation.detail
    ]
    assert len(binds) == 1, [violation.render() for violation in report]
    assert binds[0].detail == "binds '#/components/schemas/Error' instead of StoredClip"
    assert not [
        violation for violation in report if violation.detail == "binds None instead of StoredClip"
    ], [violation.render() for violation in report]

    # (b) A reused request body binding the Error envelope: same bite.
    weakened = copy.deepcopy(backend)
    init_body = weakened["paths"]["/uploads"]["post"]["requestBody"]
    init_body["content"]["application/json"]["schema"]["$ref"] = "#/components/schemas/Error"
    weakened["components"].setdefault("requestBodies", {})["CreateUploadBody"] = init_body
    weakened["paths"]["/uploads"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/CreateUploadBody"
    }
    report = check_openapi("backend", weakened)
    binds = [
        violation
        for violation in report
        if violation.location == "backend-v1 POST /uploads requestBody"
        and "instead of CreateUploadRequest" in violation.detail
    ]
    assert len(binds) == 1, [violation.render() for violation in report]
    assert binds[0].detail == "binds '#/components/schemas/Error' instead of CreateUploadRequest"

    # (c) A reused 200 whose schema `$ref` dangles: the guarded full read
    # refuses the whole node, so the readability gate owns the statement —
    # one drift finding naming the missing component member, and no `binds`
    # claim about a schema nothing was ever read from.
    weakened = copy.deepcopy(backend)
    clip200 = weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]
    clip200["content"]["application/json"]["schema"]["$ref"] = (
        "#/components/schemas/NonexistentSchema"
    )
    weakened["components"]["responses"]["ClipDetailOK"] = clip200
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ClipDetailOK"
    }
    report = check_openapi("backend", weakened)
    drift = [
        violation
        for violation in report
        if violation.location == "backend-v1 GET /clips/{clip_id} responses/200"
    ]
    assert len(drift) == 1, [violation.render() for violation in report]
    assert E.SPEC_COMPONENT_DRIFT == drift[0].code
    assert drift[0].detail == (
        "$ref names 'NonexistentSchema', a component member the document does not define"
    )

    # (d) A dangling requestBody `$ref` has no readability gate to skip to:
    # the collapsed full read keeps exactly the pair this check named before
    # this round — `not required` and `binds None` — no more, no less.
    weakened = copy.deepcopy(backend)
    weakened["paths"]["/uploads"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/MissingBody"
    }
    report = check_openapi("backend", weakened)
    verdicts = {
        violation.detail
        for violation in report
        if violation.location == "backend-v1 POST /uploads requestBody"
    }
    assert verdicts == {"not required", "binds None instead of CreateUploadRequest"}, [
        violation.render() for violation in report
    ]


def test_the_validator_reports_a_null_media_type_entry_as_a_finding(tmp_path: Path) -> None:
    """Round 16 AC-5: the review's F1a escape dies at the CLI as a finding.

    On a scratch copy of the contracts tree, the device download 206 whose
    octet-stream entry is ``null`` must earn the full validator an exit-1
    class contract finding naming the member — not silence (the review's
    escape) and not an exception reaching the CLI as exit 2.
    """
    import yaml

    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    path = broken / "device-v1.yaml"
    document = load_yaml(path)
    document["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"]["206"]["content"][
        "application/octet-stream"
    ] = None
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    report = validate_contracts(tmp_path)
    shape = [
        violation
        for violation in report.contract_violations
        if violation.location
        == "device-v1 GET /clips/{clip_id}/files/{name} responses/206 content"
    ]
    assert len(shape) == 1, [violation.render() for violation in report.contract_violations]
    assert shape[0].detail == (
        "media type 'application/octet-stream' is NoneType, not a media-type object"
    )


def test_load_yaml_refuses_an_explicit_duplicate_mapping_key(tmp_path: Path) -> None:
    """Round 14 finding 3: the duplicate key dies in the loader, not after it.

    ``yaml.safe_load`` keeps only the last of two literal ``Upload-Offset:``
    keys, so a second same-spelling entry vanished before the round-12
    duplicate-spelling gate ever ran and the full validator certified the
    document. The loader now walks the parse tree and refuses the collision
    while both keys still exist on it, which ``validate_contracts`` reports as
    a ``SPEC_PARSE_FAILED`` naming the file — never a crash, and never silence.
    """
    import yaml

    prefix = (
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: duplicate-key probe\n"
        "  version: '1'\n"
        "paths:\n"
        "  /uploads/{id}/files/{name}:\n"
        "    head:\n"
        "      operationId: headUploadFile\n"
        "      responses:\n"
        "        '200':\n"
        "          description: Authoritative offsets.\n"
        "          headers:\n"
    )
    path = tmp_path / "duplicate-offset.yaml"

    path.write_text(
        prefix
        + "            Upload-Offset:\n"
        + "              $ref: '#/components/headers/UploadOffset'\n"
        + "            Upload-Offset:\n"
        + "              $ref: '#/components/headers/UploadOffsetTwin'\n",
        encoding="utf-8",
    )
    with pytest.raises(yaml.YAMLError) as raised:
        load_yaml(path)
    assert "Upload-Offset" in str(raised.value), str(raised.value)

    # The refusal is about duplicate *keys*, not the round-12 gate's
    # case-folded names: the distinct-spelling twin is a legal document that
    # the header-spelling scan, not the parser, refuses.
    path.write_text(
        prefix
        + "            Upload-Offset:\n"
        + "              $ref: '#/components/headers/UploadOffset'\n"
        + "            upload-offset:\n"
        + "              $ref: '#/components/headers/UploadOffsetTwin'\n",
        encoding="utf-8",
    )
    loaded = load_yaml(path)
    declared = loaded["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["200"]["headers"]
    assert set(declared) == {"Upload-Offset", "upload-offset"}

    # A key that could never become a mapping member dies the same
    # ``YAMLError`` way as every other load failure — a ``ConstructorError``
    # naming the node, never a bare ``TypeError`` from dict assignment.
    path.write_text(prefix + "            ? [a, b]\n            : value\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError) as raised:
        load_yaml(path)
    assert "unhashable key" in str(raised.value), str(raised.value)

    # The committed documents contain no duplicate keys: the stricter loader
    # still reads both of them whole.
    for file_name in ("device-v1.yaml", "backend-v1.yaml"):
        document = load_yaml(CONTRACTS / file_name)
        assert isinstance(document, dict) and document, file_name


def test_load_yaml_keeps_the_safe_loader_merge_semantics(tmp_path: Path) -> None:
    """Round 14 rework: the duplicate guard sees explicit keys only.

    A base map merged through ``<<`` that also sits as an explicit key on the
    node is YAML's documented override, not a collision, and PyYAML lets the
    explicit member win in *either* textual order — a guard that consults the
    merged mapping would reject the legal document as a whole-file
    ``SPEC_PARSE_FAILED``. Only two explicit spellings of one key are a
    duplicate, and a ``<<`` that names something other than a mapping is the
    refusal the stock constructor raises, never a silently dropped member.
    """
    import yaml

    path = tmp_path / "merge.yaml"
    base = "base: &base\n  x: merged\n  y: merged\n"

    # The explicit key beats the merged one, before or after the merge key.
    for document_text in (
        base + "target:\n  <<: *base\n  y: explicit\n",
        base + "target:\n  y: explicit\n  <<: *base\n",
    ):
        path.write_text(document_text, encoding="utf-8")
        loaded = load_yaml(path)
        assert loaded["target"] == {"x": "merged", "y": "explicit"}, document_text

    # Two explicit spellings of one key still die, merge present or not.
    path.write_text(
        base + "target:\n  <<: *base\n  y: one\n  y: two\n", encoding="utf-8"
    )
    with pytest.raises(yaml.YAMLError) as raised:
        load_yaml(path)
    assert "found duplicate key 'y'" in str(raised.value), str(raised.value)

    # A merge source that is not a mapping is refused the way
    # ``BaseConstructor.flatten_mapping`` refuses it.
    path.write_text(
        "scalar: &scalar not-a-mapping\ntarget:\n  <<: *scalar\n", encoding="utf-8"
    )
    with pytest.raises(yaml.YAMLError) as raised:
        load_yaml(path)
    assert "expected a mapping for merging" in str(raised.value), str(raised.value)


def test_load_yaml_merges_an_anchored_sequence_of_mappings_like_the_safe_loader(
    tmp_path: Path,
) -> None:
    """Round 15: ``<<`` over an anchored sequence merges — it never drops.

    The merge operand is the anchored ``SequenceNode`` itself. Constructing it
    hits the loader's already-constructed memo — the anchor was registered when
    its own key constructed it shallowly — which hands back the generator-
    backed list *before* its pending generator appends the entries, so the
    merge loop iterated nothing and every merged key silently vanished while
    ``yaml.safe_load`` merged them all. The walk now happens at the node level,
    the way ``BaseConstructor.flatten_mapping`` walks it: each entry has to be
    a mapping, first source wins, the explicit member beats all of them, and a
    non-mapping entry dies the same ``ConstructorError`` family (which the
    validator reports as ``SPEC_PARSE_FAILED``) rather than dropping members.
    """
    import yaml

    path = tmp_path / "merge-seq.yaml"

    # The exact loader probe from the review: a sequence of two single-pair
    # mappings merged under an explicit key.
    text = "s: &s\n  - a: 1\n  - b: 2\nm:\n  <<: *s\n  k: v\n"
    path.write_text(text, encoding="utf-8")
    loaded = load_yaml(path)
    assert loaded["m"] == {"a": 1, "b": 2, "k": "v"}, loaded
    assert loaded == yaml.safe_load(text), loaded

    # First source wins among the sequence's entries and the explicit member
    # still beats them all — the round-14 precedence, unchanged for sequences.
    text = (
        "a: &a\n  k: from-a\n"
        "b: &b\n  k: from-b\n  j: from-b\n"
        "t:\n  <<: [*a, *b]\n  j: explicit\n"
    )
    path.write_text(text, encoding="utf-8")
    loaded = load_yaml(path)
    assert loaded["t"] == {"k": "from-a", "j": "explicit"}, loaded
    assert loaded == yaml.safe_load(text), loaded

    # An anchored sequence merged as a *sequence entry* is not a mapping and
    # dies the stock refusal family — as does any entry that names a scalar or
    # a sequence — a ``YAMLError`` for the validator, never a silently dropped
    # member. Each case refuses identically under ``yaml.safe_load``.
    for text in (
        "s: &s\n  - 1\nm:\n  <<: *s\n",
        "s: &s\n  - [1]\nm:\n  <<: *s\n",
        "a: &a\n  k: 1\ns: &s\n  - k: 77\nm:\n  <<: [*a, *s]\n",
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(yaml.YAMLError) as raised:
            load_yaml(path)
        assert "expected a mapping for merging" in str(raised.value), text
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(text)


def test_the_error_envelope_is_one_reusable_schema(device: dict, backend: dict) -> None:
    assert not check_shared_error_envelope({"device": device, "backend": backend})
    weakened = copy.deepcopy(backend)
    weakened["components"]["schemas"]["ErrorBody"]["required"] = ["code"]
    codes = {
        violation.code
        for violation in check_shared_error_envelope({"device": device, "backend": weakened})
    }
    assert codes == {E.SPEC_COMPONENT_DRIFT}


def test_the_manifest_component_mirrors_the_media_schema(device: dict, backend: dict) -> None:
    manifest = load_json(CONTRACTS / "media-v1" / "manifest.schema.json")
    assert not check_manifest_component({"device": device, "backend": backend}, manifest)

    weakened = copy.deepcopy(device)
    weakened["components"]["schemas"]["ManifestFile"]["properties"]["bytes"]["maximum"] = 1024
    codes = {
        violation.code
        for violation in check_manifest_component({"device": weakened, "backend": backend}, manifest)
    }
    assert codes == {E.SPEC_COMPONENT_DRIFT}


def test_request_objects_reject_unknown_fields_and_no_secret_appears(device: dict) -> None:
    schemas = device["components"]["schemas"]
    for name in ("PutSettingsRequest", "TimeRequest", "DeviceEventRequest", "VersionedRequest"):
        assert schemas[name]["additionalProperties"] is False, name
    read = schemas["NetworkSettingsRead"]
    assert read["additionalProperties"] is False
    # The description may mention a password; the schema must not carry one.
    assert "password" not in read["properties"], "GET /settings must never expose a password"


def test_response_objects_stay_permissive(device: dict) -> None:
    """interfaces.md §1: readers tolerate unknown response fields."""
    schemas = device["components"]["schemas"]
    for name in ("StatusResponse", "CapabilitiesResponse", "ClipsPage"):
        assert schemas[name].get("additionalProperties") is not False, name


def test_token_and_secret_patterns_are_unpadded_base64url(device: dict, backend: dict) -> None:
    pattern = "^[A-Za-z0-9_-]{43}$"
    for document, name in (
        (device, "SetupSecret"),
        (device, "AccessToken"),
        (backend, "TokenSecret"),
    ):
        assert document["components"]["schemas"][name]["pattern"] == pattern, name


def test_manifest_base64url_is_base64url_and_validator_bounds_the_decode(backend: dict) -> None:
    binding = backend["components"]["schemas"]["CreateUploadRequest"]["properties"]
    assert binding["manifest_base64url"]["$ref"] == "#/components/schemas/ManifestBase64Url"
    assert (
        backend["components"]["schemas"]["ManifestBase64Url"]["pattern"] == "^[A-Za-z0-9_-]+$"
    )


def test_chunk_content_length_is_documented_as_one_to_one_mebibyte(backend: dict) -> None:
    parameter = backend["components"]["parameters"]["ChunkContentLength"]
    assert parameter["name"] == "Content-Length"
    assert parameter["in"] == "header"
    assert parameter["required"] is True
    assert parameter["schema"]["minimum"] == 1
    assert parameter["schema"]["maximum"] == 1_048_576


# --- AC-07: the OTA envelope stays deferred ----------------------------------


def test_no_ota_schema_ships() -> None:
    assert not (CONTRACTS / "ota-v1.json").exists()


def test_ota_operation_carries_the_deferral(device: dict) -> None:
    assert not check_ota_deferral(device, CONTRACTS)


def test_a_guessed_ota_schema_is_refused(device: dict, media_dir: Path) -> None:
    (media_dir / "ota-v1.json").write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
        encoding="utf-8",
    )
    codes = {violation.code for violation in check_ota_deferral(device, media_dir)}
    assert codes == {E.OTA_SCHEMA_PRESENT}


def test_removing_the_deferral_note_is_refused(device: dict, media_dir: Path) -> None:
    weakened = copy.deepcopy(device)
    del weakened["paths"]["/ota"]["post"]["x-deferred"]
    codes = {violation.code for violation in check_ota_deferral(weakened, media_dir)}
    assert E.OTA_DEFERRAL_MISSING in codes


def test_a_schema_on_the_deferred_body_is_refused(device: dict, media_dir: Path) -> None:
    weakened = copy.deepcopy(device)
    weakened["paths"]["/ota"]["post"]["requestBody"]["content"]["application/octet-stream"][
        "schema"
    ] = {"$ref": "#/components/schemas/OtaEnvelope"}
    codes = {violation.code for violation in check_ota_deferral(weakened, media_dir)}
    assert E.OTA_DEFERRAL_MISSING in codes


# --- Whole-repo contract checks (AC-08) --------------------------------------


@pytest.mark.parametrize(
    "index,code",
    [(i, code) for i, (group, code, _mutate) in enumerate(CORPUS_MUTATIONS) if group == "documents"],
    ids=[code for group, code, _mutate in CORPUS_MUTATIONS if group == "documents"],
)
def test_a_broken_document_is_named(index: int, code: str, mutation_codes) -> None:
    """A contract document that stopped being parseable or lost its envelope is a finding."""
    assert code in mutation_codes[f"{index}:{code}"], sorted(mutation_codes[f"{index}:{code}"])


def test_a_tree_level_scenario_code_is_never_routine(clean_codes) -> None:
    """Attribution for a document scenario is the whole tree, so it needs a guard.

    A vector scenario must name its code on the damaged vector. A document scenario
    damages the tree as a whole, so its evidence is only sound while the code it claims
    is one the committed tree never emits — which is exactly what this pins.
    """
    tree_level = [code for group, code, _mutate in CORPUS_MUTATIONS if group == "documents"]
    tree_level.append("SPEC_STATUS_NOT_ALLOWED")
    routine = [code for code in tree_level if code in clean_codes]
    assert not routine, sorted(routine)


def test_a_status_outside_the_documented_set_is_refused(mutation_codes) -> None:
    """Decision 7: the documented status set is a ceiling, not a suggestion.

    The scenario puts 418 in *both* the operation table and the YAML, so the two
    notations agree with each other and only the ceiling can catch it.
    """
    codes = mutation_codes[f"{len(CORPUS_MUTATIONS)}:SPEC_STATUS_NOT_ALLOWED"]
    assert E.SPEC_STATUS_NOT_ALLOWED in codes, sorted(codes)


def test_the_documents_and_the_bound_table_agree(device: dict, backend: dict) -> None:
    """bounds.py is the single source of a limit; a YAML keyword may not drift from it.

    The contract states these limits as schema keywords, and the validator enforces
    the ones it can only reach by arithmetic. Both notations have to say the same
    number, or a client coded against the document would be refused by the tooling.
    """
    from tools.contracts import bounds

    device_parameters = device["components"]["parameters"]
    backend_parameters = backend["components"]["parameters"]
    device_schemas = device["components"]["schemas"]
    backend_schemas = backend["components"]["schemas"]

    checks: list[tuple[object, object, str]] = [
        (device_parameters["Cursor"]["schema"]["maxLength"], bounds.MAX_CURSOR_CHARS, "device Cursor"),
        (backend_parameters["Cursor"]["schema"]["maxLength"], bounds.MAX_CURSOR_CHARS, "backend Cursor"),
        (device_parameters["LimitDevice"]["schema"]["maximum"], bounds.MAX_PAGE_LIMIT, "device page limit"),
        (device_parameters["LimitDevice"]["schema"]["default"], bounds.DEVICE_PAGE_DEFAULT, "device page default"),
        (backend_parameters["LimitBackend"]["schema"]["maximum"], bounds.MAX_PAGE_LIMIT, "backend page limit"),
        (backend_parameters["LimitBackend"]["schema"]["default"], bounds.BACKEND_PAGE_DEFAULT, "backend page default"),
        (
            device_schemas["DeviceEventRequest"]["properties"]["clip_ids"]["minItems"],
            bounds.MIN_EVENT_CLIPS,
            "event clip floor",
        ),
        (
            device_schemas["DeviceEventRequest"]["properties"]["clip_ids"]["maxItems"],
            bounds.MAX_EVENT_CLIPS,
            "event clip ceiling",
        ),
        (
            device_schemas["DeviceEventRequest"]["properties"]["label"]["maxLength"],
            bounds.MAX_EVENT_LABEL_CHARS,
            "device event label",
        ),
        (
            backend_schemas["BackendEventRequest"]["properties"]["label"]["maxLength"],
            bounds.MAX_EVENT_LABEL_CHARS,
            "backend event label",
        ),
        (
            backend_parameters["ChunkContentLength"]["schema"]["minimum"],
            bounds.MIN_CHUNK_BYTES,
            "chunk floor",
        ),
        (
            backend_parameters["ChunkContentLength"]["schema"]["maximum"],
            bounds.MAX_CHUNK_BYTES,
            "chunk ceiling",
        ),
        (
            backend_schemas["UploadCreated"]["properties"]["expires_in_s"]["const"],
            bounds.UPLOAD_EXPIRY_S,
            "upload expiry",
        ),
    ]

    # media-format.md §2 puts every JSON integer of these formats inside the range a
    # conforming reader represents exactly. Four documents state that ceiling for the
    # clock estimate and two more for the shared integer component, and the validator
    # enforces the clock one arithmetically: any of them drifting from ``bounds.py`` would
    # let a client accept an estimate the harness refuses.
    media, media_violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not media_violations, [violation.render() for violation in media_violations]
    for name in ("manifest", "active"):
        checks.append(
            (
                media[name]["$defs"]["clock"]["properties"]["uncertainty_ms"]["maximum"],
                bounds.UINT53_MAX,
                f"media-v1 {name} uncertainty ceiling",
            )
        )
    for schemas, contract in ((device_schemas, "device"), (backend_schemas, "backend")):
        checks.append(
            (
                schemas["ManifestClock"]["properties"]["uncertainty_ms"]["maximum"],
                bounds.UINT53_MAX,
                f"{contract}-v1 ManifestClock uncertainty ceiling",
            )
        )
        checks.append(
            (
                schemas["UInt53"]["maximum"],
                bounds.UINT53_MAX,
                f"{contract}-v1 shared integer ceiling",
            )
        )
        # A digest is 64 characters by definition, so each notation that declares the
        # pattern has to carry the pair of length keywords too; the value is pinned beside
        # the pattern in test_media_contract, and what belongs here is that no notation is
        # left accepting a padded digest a sibling refuses.
        assert "minLength" in schemas["Sha256"] and "maxLength" in schemas["Sha256"], contract
    assert "minLength" in media["manifest"]["$defs"]["sha256"], "media-v1 sha256"
    assert "maxLength" in media["manifest"]["$defs"]["sha256"], "media-v1 sha256"

    for observed, expected, name in checks:
        assert observed == expected, f"{name}: document says {observed!r}, bounds.py says {expected!r}"


#: bounds.py names that describe the *fixture shapes* the generator draws rather than a
#: rule the contract enforces, so only the generator side may read them. Listed by hand:
#: a new `FIXTURE_*`-looking limit must be argued for here, not exempted by its name.
GENERATOR_ONLY_BOUNDS: Final[frozenset[str]] = frozenset(
    {
        "FIXTURE_FRAME_WIDTH",
        "FIXTURE_FRAME_HEIGHT",
        "FIXTURE_JPEG_QUALITY",
        "FIXTURE_NOMINAL_FPS",
    }
)


def _loaded_names(path: pathlib.Path) -> set[str]:
    """Every identifier a module *loads*, ignoring imports, strings and comments.

    Text matching would credit a mention in a docstring or an unused import, so the
    guard reads syntax: a bound counts as read only where the code actually uses it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            # An import binds an ``alias``, never a ``Name``, so what is reached here is
            # a real load site: the bound is used, not merely mentioned.
            loaded.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                loaded.add(node.attr)
    return loaded


def test_no_bound_constant_is_left_unread() -> None:
    """A limit in bounds.py that nothing reads is a limit nobody enforces.

    Every constant type counts: a marker byte or a file name drifts just as quietly as
    a maximum does, and an identifier in a comment is not an enforcement site.
    """
    package = pathlib.Path(bounds_module.__file__).parent
    readers: set[str] = set()
    for source in sorted(package.glob("*.py")):
        if source.name != "bounds.py":
            readers |= _loaded_names(source)
    readers |= _loaded_names(pathlib.Path(__file__))
    declared = {
        name
        for name in dir(bounds_module)
        if name.isupper() and not name.startswith("_")
    }
    unenforced = sorted(declared - readers - GENERATOR_ONLY_BOUNDS)
    assert not unenforced, unenforced


def test_whole_corpus_has_no_contract_findings(report) -> None:
    assert not report.contract_violations, [
        violation.render() for violation in report.contract_violations
    ]


def test_a_negative_vector_that_passes_is_a_failure(tmp_path: Path) -> None:
    """AC-10 of the plan: a detector that stopped detecting must fail the run."""
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    index_path = broken / "fixtures" / "fixtures.json"
    document = json.loads(index_path.read_bytes().decode("utf-8"))
    for entry in document["fixtures"]:
        if entry["id"] == "media/invalid/frame-crc-mismatch":
            entry["expected_error_codes"] = [E.FRAME_SEQ_NOT_CONSECUTIVE]
    index_path.write_bytes(json.dumps(document).encode("utf-8"))

    report = validate_contracts(tmp_path)
    result = next(item for item in report.results if item.id == "media/invalid/frame-crc-mismatch")
    codes = {violation.code for violation in result.failures}
    assert codes == {E.FIXTURE_MISSING_CODE, E.FIXTURE_UNEXPECTED_CODE}


def test_a_valid_vector_that_fails_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "fixtures" / "media" / "valid" / "baseline" / "frames.jsonl").write_bytes(
        b'{"v":1,"seq":0,"offset":0,"size":1,"t_us":0,"crc32":"00000000"}\n'
    )
    report = validate_contracts(tmp_path)
    result = next(item for item in report.results if item.id == "media/valid/baseline")
    assert not result.passed
    codes = {violation.code for violation in result.failures}
    assert E.FRAME_CRC_MISMATCH in codes, sorted(codes)
    assert E.FIXTURE_EXPECTED_PASS in codes, sorted(codes)


# --- Round 2: mirrored ceilings, the format checker, invalid keywords --------


def _baseline_manifest() -> dict:
    """The committed baseline manifest, as a mutable document."""
    return json.loads(
        (CONTRACTS / "fixtures" / "media" / "valid" / "baseline" / "manifest.json").read_bytes()
    )


def _manifest_schema(mirror: str, device: dict, backend: dict) -> dict:
    """The manifest schema of one of the three places the manifest is published."""
    from tools.contracts.schema_docs import resolve_refs

    if mirror == "media":
        document = load_json(CONTRACTS / "media-v1" / "manifest.schema.json")
        return resolve_refs(document)
    document = device if mirror == "device" else backend
    return resolve_refs(document["components"]["schemas"]["Manifest"], root=document)


@pytest.mark.parametrize("mirror", ["media", "device", "backend"])
def test_the_index_ceiling_is_mirrored_in_every_manifest_notation(
    mirror: str, device: dict, backend: dict
) -> None:
    """media-format.md §2 bounds frames.jsonl at 1,843,200 bytes in all three documents.

    The OpenAPI mirrors are what a consumer generates a client from, so an index ceiling
    that exists only in ``contracts/media-v1`` would still let a backend accept a
    manifest declaring a three-times-too-large index. The payload entry keeps its own,
    much larger, ceiling in every mirror too.
    """
    from tools.contracts.bounds import MAX_INDEX_BYTES, MAX_PAYLOAD_BYTES
    from tools.contracts.schema_docs import schema_error_report

    schema = _manifest_schema(mirror, device, backend)
    manifest = _baseline_manifest()
    manifest["files"]["video.mjpg"]["bytes"] = MAX_PAYLOAD_BYTES
    manifest["files"]["frames.jsonl"]["bytes"] = MAX_INDEX_BYTES
    assert not schema_error_report(schema, manifest), mirror

    manifest["files"]["frames.jsonl"]["bytes"] = MAX_INDEX_BYTES + 1
    found = [
        (property_name, keyword)
        for property_name, keyword, _ in schema_error_report(schema, manifest)
    ]
    assert found == [("bytes", "maximum")], (mirror, found)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("2026-03-04T11:02:03.250Z", True),
        ("2026-01-01T00:00:00Z", True),
        ("2026-12-31T23:59:59.999999Z", True),
        ("2026-06-01T08:30:00.000+05:30", True),
        ("2026-02-28T23:59:59.000-00:00", True),
        ("2026-03-04t11:02:03.250z", True),
        ("2028-02-29T12:00:00.000Z", True),
        ("2026-02-30T12:00:00.000Z", False),
        ("2025-02-29T00:00:00.000Z", False),
        ("2026-01-01T25:00:00.000Z", False),
        ("2026-01-01T12:61:00.000Z", False),
        ("2026-01-01T12:00:60.000Z", False),
        ("2026-13-01T12:00:00.000Z", False),
        ("2026-01-01T12:00:00.000+24:00", False),
        ("2026-01-01 12:00:00.000Z", False),
        ("2026-01-01T12:00:00.000", False),
        ("not a timestamp", False),
    ],
)
def test_the_format_checker_needs_a_real_instant_not_its_shape(value: str, valid: bool) -> None:
    """``format`` is informational unless somebody checks it, so here it is checked.

    Every documented timestamp in this contract already carries milliseconds and a
    trailing ``Z``; the checker is not there to widen the wire form (a leap second stays
    refused) but to give the pattern a calendar behind it.
    """
    from tools.contracts.schema_docs import is_rfc3339_date_time

    assert is_rfc3339_date_time(value) is valid, value


def test_the_format_checker_owns_only_the_formats_it_registers() -> None:
    """``null`` stays a legal ``date-time`` value and an unknown format stays a note.

    The contract writes ``type: [string, null]`` beside ``format: date-time`` and uses
    ``format: binary`` as a pure annotation, so a checker that judged either would be
    inventing a rule the documents never stated.
    """
    from tools.contracts.schema_docs import schema_error_report

    assert not schema_error_report({"type": ["string", "null"], "format": "date-time"}, None)
    assert not schema_error_report({"type": "string", "format": "binary"}, "anything at all")
    assert [
        (property_name, keyword)
        for property_name, keyword, _ in schema_error_report(
            {"type": "string", "format": "date-time"}, "2026-02-30T12:00:00.000Z"
        )
    ] == [("", "format")]


def test_an_unresolvable_local_ref_is_a_finding_not_a_crash() -> None:
    """A valid schema that cannot be *resolved* is as unusable as an invalid one.

    ``check_schema`` accepts any URI-reference as ``$ref``, so only resolution notices
    a typo'd pointer — and resolution is lazy, so without this the ``KeyError`` arrives
    from inside ``iter_errors`` as a validator internal error.
    """
    from tools.contracts.schema_docs import check_local_refs

    assert not check_local_refs({"$defs": {"a": {"type": "integer"}}, "properties": {"x": {"$ref": "#/$defs/a"}}})
    for broken in (
        {"properties": {"x": {"$ref": "#/$defs/nope"}}},
        {"$defs": {"a": {"$ref": "#/$defs/a"}}, "properties": {"x": {"$ref": "#/$defs/a"}}},
        {"properties": {"x": {"$ref": "https://example.com/other.json"}}},
    ):
        failure = check_local_refs(broken)
        assert failure is not None and "\n" not in failure, broken


def test_an_invalid_keyword_value_is_a_finding_not_a_crash() -> None:
    """A parseable schema whose keyword is nonsense is a failed check, not exit 2.

    ``check_schema`` raises ``SchemaError``, which is not a ``ValidationError``: letting
    it escape turns a bad contract file into "validator internal error".
    """
    from tools.contracts.schema_docs import check_metaschema

    failure = check_metaschema({"type": "object", "properties": {"x": {"maximum": "not-a-number"}}})
    assert failure is not None
    assert failure == failure.strip() and "\n" not in failure, failure
    assert not check_metaschema({"type": "object", "properties": {"x": {"maximum": 3}}})
