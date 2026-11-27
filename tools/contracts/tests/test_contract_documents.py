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
    UNAUTHENTICATED_OPERATIONS,
    check_headers_contract,
    check_manifest_component,
    check_openapi,
    check_ota_deferral,
    check_shared_error_envelope,
    load_media_schemas,
)
from tools.contracts.schema_docs import (
    load_json,
    load_yaml,
    resolve_reference,
    resolve_refs,
    schema_error_report,
)
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
    # semantics: the Reference-Object full read (resolve_reference, via
    # _resolve) strips the non-`$ref` siblings and follows the pointer, so the
    # chain may not stop there and charge the operation for a member the
    # target does not publish.
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

    # `$ref`-with-siblings hop: the Reference-Object full read (resolve_reference,
    # via _resolve) drops the decorators and follows the pointer, so the
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


# --- Round 17: the effective-security gate and the two $ref resolution semantics --


def _security_findings(document: dict, contract: str) -> list:
    return [
        violation
        for violation in check_openapi(contract, document)
        if violation.code == E.SPEC_SECURITY_MISSING
    ]


def _protected_locations(contract: str) -> set[str]:
    return {
        f"{operation.method} {operation.path}"
        for operation in ALL_OPERATIONS.values()
        if operation.contract == contract
        and operation.key not in UNAUTHENTICATED_OPERATIONS
    }


def test_anonymous_security_alternatives_are_refused_on_protected_operations(device: dict) -> None:
    """Security requirements are ALTERNATIVES — one branch may not authenticate nobody.

    The old gate asked ``any("bearerAuth" in entry for entry in security)``, so
    ``[{}, {bearerAuth: []}]`` passed on a protected operation even though the
    ``{}`` alternative lets it run anonymous (OpenAPI 3.1 security-requirement
    semantics), contradicting interfaces.md §2. The effective list must be
    non-empty and *every* alternative must name bearerAuth; each failure earns
    its one ``SPEC_SECURITY_MISSING`` at ``{method} {path}``, with a message
    naming the reason.
    """
    assert not check_openapi("device", device)

    for label, mutate in (
        ("anonymous alternative", {"security": [{}, {"bearerAuth": []}]}),
        ("single anonymous alternative", {"security": [{}]}),
        ("foreign-only alternative", {"security": [{"apiKey": []}]}),
        ("non-object alternative", {"security": ["bearerAuth"]}),
        ("empty effective list", {"security": []}),
    ):
        weakened = copy.deepcopy(device)
        weakened["paths"]["/status"]["get"].update(mutate)
        found = _security_findings(weakened, "device")
        assert [violation.location for violation in found] == ["GET /status"], (
            label,
            [violation.render() for violation in found],
        )
    # The document-level fallback is read under the same rules: no document
    # default and an operation that declares nothing authenticates nobody.
    weakened = copy.deepcopy(device)
    del weakened["security"]
    found = _security_findings(weakened, "device")
    assert {violation.location for violation in found} == _protected_locations("device"), [
        violation.render() for violation in found
    ]
    anonymous = [
        violation for violation in found if violation.location == "GET /status"
    ]
    assert anonymous and "bearerAuth" not in anonymous[0].detail, anonymous
    # A named scheme is a promise, not a definition: an anonymous alternative
    # names the reason, and the message must say which failure it reports.
    weakened = copy.deepcopy(device)
    weakened["paths"]["/status"]["get"]["security"] = [{}, {"bearerAuth": []}]
    found = [
        violation
        for violation in _security_findings(weakened, "device")
        if violation.location == "GET /status"
    ]
    assert len(found) == 1, [violation.render() for violation in found]
    assert "bearerAuth" in found[0].detail and "alternative" in found[0].detail.lower(), (
        found[0].render()
    )


def test_protected_operations_require_an_http_bearer_scheme(device: dict, backend: dict) -> None:
    """``bearerAuth`` must exist as ``{type: http, scheme: bearer}`` — or it is missing.

    Nothing used to inspect ``components.securitySchemes``: deleting the scheme
    or replacing it with a query-token ``apiKey`` kept every protected operation
    green while documenting no authentication mechanism at all. The scheme check
    runs per protected operation, and the exemptions keep their exemption
    exactly — pairing and the two health probes never carry the finding.
    """
    assert not check_openapi("device", device)
    assert not check_openapi("backend", backend)

    for label, mutate in (
        ("undefined scheme", lambda d: d["components"]["securitySchemes"].pop("bearerAuth")),
        (
            "apiKey scheme",
            lambda d: d["components"]["securitySchemes"].update(
                bearerAuth={"type": "apiKey", "in": "query", "name": "token"}
            ),
        ),
        (
            "non-http type",
            lambda d: d["components"]["securitySchemes"].update(
                bearerAuth={"type": "oauth2", "flows": {}}
            ),
        ),
        (
            "wrong scheme value",
            lambda d: d["components"]["securitySchemes"]["bearerAuth"].update(scheme="basic"),
        ),
        (
            "non-string scheme value",
            lambda d: d["components"]["securitySchemes"]["bearerAuth"].update(scheme=1),
        ),
    ):
        weakened = copy.deepcopy(device)
        mutate(weakened)
        found = _security_findings(weakened, "device")
        assert {violation.location for violation in found} == _protected_locations("device"), (
            label,
            [violation.render() for violation in found],
        )
        assert len(found) == len({violation.location for violation in found}), label
        named = next(
            violation for violation in found if violation.location == "GET /status"
        )
        assert "securitySchemes" in named.detail and "bearerAuth" in named.detail, (
            label,
            named.render(),
        )

    # The exemptions are untouched by the scheme half as well: with the scheme
    # gone, the backend still refuses nothing on the two health probes.
    weakened = copy.deepcopy(backend)
    weakened["components"]["securitySchemes"].pop("bearerAuth")
    found = _security_findings(weakened, "backend")
    assert {violation.location for violation in found} == _protected_locations("backend"), [
        violation.render() for violation in found
    ]
    assert {
        "POST /pair",
        "GET /health/live",
        "GET /health/ready",
    }.isdisjoint({violation.location for violation in found}), [
        violation.render() for violation in found
    ]

    # A scheme name the document spells in capitals is the same scheme: OpenAPI
    # treats scheme values case-insensitively, so the gate must not.
    strengthened = copy.deepcopy(device)
    strengthened["components"]["securitySchemes"]["bearerAuth"]["scheme"] = "BEARER"
    assert not _security_findings(strengthened, "device")


def test_a_ref_sibling_assertion_binds_through_schema_resolution(device: dict) -> None:
    """JSON Schema 2020-12 §8.2.3.1: siblings of a ``$ref`` are assertions too.

    ``resolve_refs`` returned the referenced target and dropped every sibling,
    so the review's ``maxLength: 1`` beside the ``setup_secret`` pointer in
    ``PairRequest`` was enforced by a standard Draft 2020-12 validator and
    silently ignored by the published-schema path — body validation and the
    corpus kept certifying the violating 43-character secret. Siblings now
    merge over the resolved target, agreeing with the standard validator on
    the same document.
    """
    from jsonschema import Draft202012Validator, RefResolver

    instance = {"v": 1, "setup_secret": "A" * 43, "client_name": "long-client"}
    untouched = resolve_refs(
        device["components"]["schemas"]["PairRequest"], root=device
    )
    assert not schema_error_report(untouched, instance), (
        "the committed PairRequest accepts this secret today"
    )

    weakened = copy.deepcopy(device)
    weakened["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"][
        "maxLength"
    ] = 1
    reference = Draft202012Validator(
        weakened["components"]["schemas"]["PairRequest"],
        resolver=RefResolver.from_schema(weakened),
    )
    standard = [error.message for error in reference.iter_errors(instance)]
    assert standard, "a standard validator must refuse the 43-character secret"

    resolved = resolve_refs(
        weakened["components"]["schemas"]["PairRequest"], root=weakened
    )
    report = schema_error_report(resolved, instance)
    assert any(keyword == "maxLength" for _property, keyword, _message in report), report


def test_a_ref_sibling_conjoins_instead_of_overwriting_its_target_keyword(device: dict) -> None:
    """Conjunction means *exact* conjunction: a sibling replaces no target keyword.

    The round-17 read merged ``{**target, **siblings}``, so a sibling spelled
    with the same keyword as the target — ``description`` here — silently won,
    and any assertion the sibling dropped left the referenced schema unbound.
    JSON Schema 2020-12 §8.2.3.1 evaluates both sides, so the resolution is
    now the exact conjunction ``{"allOf": [target, siblings]}``: the sibling's
    annotation rides along and every target assertion keeps binding.
    """
    weakened = copy.deepcopy(device)
    node = weakened["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"]
    node["description"] = "sibling rides along"
    resolved = resolve_refs(node, root=weakened)
    plain = resolve_refs({"$ref": "#/components/schemas/SetupSecret"}, root=weakened)
    assert plain["description"] != "sibling rides along", "SetupSecret lost its own description"
    assert resolved == {"allOf": [plain, {"description": "sibling rides along"}]}
    # The target's own assertions still bind through the conjunction: the
    # length pair and pattern the merge would have overwritten or dropped
    # still judge every instance (the resolution is the property schema).
    assert not schema_error_report(resolved, "A" * 43)
    assert schema_error_report(resolved, "A" * 42), (
        "SetupSecret's own length bound stopped binding through the conjunction"
    )


def test_boolean_and_scalar_ref_targets_conjoin_the_obvious_way() -> None:
    """A boolean target conjoins; a scalar one cannot conjoin at all.

    ``true`` leaves the siblings as the whole satisfiable assertion, ``false``
    makes the node unsatisfiable (an unsatisfiable conjunct dominates), and a
    non-schema target with siblings is refused by name — a schema object
    cannot conjoin assertions with ``"hello"``. A scalar target without
    siblings keeps today's wholesale return.
    """
    document = {"$defs": {"allow": True, "deny": False, "word": "hello"}}
    assert resolve_refs({"$ref": "#/$defs/allow", "maxLength": 7}, root=document) == {
        "maxLength": 7
    }
    assert resolve_refs({"$ref": "#/$defs/allow"}, root=document) == {}
    assert resolve_refs({"$ref": "#/$defs/deny", "maxLength": 7}, root=document) is False
    assert resolve_refs({"$ref": "#/$defs/deny"}, root=document) is False
    assert resolve_refs({"$ref": "#/$defs/word"}, root=document) == "hello"
    with pytest.raises(ValueError, match=re.escape("#/$defs/word")):
        resolve_refs({"$ref": "#/$defs/word", "maxLength": 7}, root=document)
    # A sibling that re-references the node's own target is *not* recursion
    # (round-18 F4): sibling subtrees resolve with a fresh copy of the stack as
    # it stood before the node's own pointer was pushed, so this repeated
    # assertion of one finite target resolves the way a standard validator
    # accepts it. Genuine recursion — a target expansion reaching an
    # enclosing in-flight pointer — is still refused by name.
    assert resolve_refs(
        {"$ref": "#/$defs/allow", "patternProperties": {"x": {"$ref": "#/$defs/allow"}}},
        root=document,
    ) == {"patternProperties": {"x": {}}}
    cyclic = {
        "$defs": {
            "loop": {"type": "object", "properties": {"next": {"$ref": "#/$defs/loop"}}}
        }
    }
    with pytest.raises(ValueError, match=re.escape("recursive $ref '#/$defs/loop'")):
        resolve_refs({"$ref": "#/$defs/loop"}, root=cyclic)


def test_stripped_reference_decoration_is_inert_while_followed_pointers_fail_closed(
    backend: dict,
) -> None:
    """Round 18 F2, correcting the round-17 note: decoration is inert, hops fail closed.

    Round 17 pinned that a dangling ``$ref`` hiding inside a header node's
    *decoration* sibling earned ``SPEC_COMPONENT_DRIFT`` — the deep schema-mode
    walk followed it. OpenAPI 3.1 Reference Object semantics say that sibling
    is never read at all: the reference-mode read strips every non-``$ref``
    member at every hop, so a pointer inside stripped decoration is inert —
    nothing names it and nothing crashes. What the walk does follow still
    fails closed: a pointer a hop reaches (a Header Object's own ``schema``
    member here) is resolved, and one the document cannot follow still earns
    its ``SPEC_COMPONENT_DRIFT`` at the response, never an exit-2 crash.
    """
    assert not check_openapi("backend", backend)

    # The very mutation round 17 pinned as drift: the dangling pointer sits in
    # a stripped sibling of a Reference Object, so it is never followed, never
    # named, and the rest of the document certifies honestly.
    weakened = copy.deepcopy(backend)
    weakened["components"]["headers"]["SiblingProbeMap"] = {
        "X-Probe": {
            "$ref": "#/components/headers/ETagSha256",
            "x-decoration": {"$ref": "#/components/headers/NoSuchHeader"},
        }
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]["headers"] = {
        "$ref": "#/components/headers/SiblingProbeMap"
    }
    report = check_openapi("backend", weakened)
    assert not [violation for violation in report if "NoSuchHeader" in violation.render()], [
        violation.render() for violation in report
    ]
    assert not report, [violation.render() for violation in report]

    # The pointer this hop *does* follow — the Header Object's ``schema``
    # member — is still walked: a dangling target there is the document
    # defect it always was, named at the response in the guarded wording.
    weakened = copy.deepcopy(backend)
    weakened["components"]["headers"]["ProbeSchemaHop"] = {
        "description": "a header whose schema pointer dangles",
        "schema": {"$ref": "#/components/headers/NoSuchHeader"},
    }
    weakened["components"]["headers"]["SiblingProbeMap"] = {
        "X-Probe": {"$ref": "#/components/headers/ProbeSchemaHop"}
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]["headers"] = {
        "$ref": "#/components/headers/SiblingProbeMap"
    }
    report = check_openapi("backend", weakened)
    drift = [
        violation
        for violation in report
        if violation.code == E.SPEC_COMPONENT_DRIFT
        and violation.location == "backend-v1 GET /clips/{clip_id} responses/200"
    ]
    assert drift and all("NoSuchHeader" in violation.detail for violation in drift), [
        violation.render() for violation in report
    ]


def test_a_reference_object_sibling_does_not_reach_the_resolved_target() -> None:
    """OpenAPI 3.1 Reference Objects do not augment the target — strip, then follow.

    The response/header/parameter positions are Reference Object territory, not
    Schema Object territory: members other than ``$ref`` riding beside a
    reference are decorations that must not change a gate decision, unlike
    JSON Schema siblings which are assertions. ``resolve_reference`` is that
    read: every non-``$ref`` sibling is stripped before the pointer is
    followed. A node without ``$ref`` is walked by the same
    :func:`resolve_refs` read, nested references inlined.
    """
    document = {"components": {"responses": {"Ok": {"description": "target words"}}}}
    resolved = resolve_reference(
        {"$ref": "#/components/responses/Ok", "required": True, "x-decoration": 1},
        root=document,
    )
    assert resolved == {"description": "target words"}
    assert resolve_reference({"description": "plain"}, root=document) == {
        "description": "plain"
    }


def test_a_decorated_reference_does_not_promise_content_the_target_withholds(
    backend: dict,
) -> None:
    """The round-16 full-read/shallow-read agreement, restated for the split.

    The HEAD/204 no-body gate asks the *full* read what the response carries
    while the table loops read the guarded shallow hop. Both must resolve a
    Reference-Object position the same way: through ``resolve_reference``,
    which drops non-``$ref`` siblings. A ``content`` member decorating a
    ``$ref`` beside the HEAD 200 is decoration the reference does not merge —
    the target still promises no body, and the document must certify clean
    exactly as the undecorated ``$ref`` does (the two round-16 agreement tests
    at the top of this module pin the undecorated and ``$ref``-with-siblings
    alias hops).
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    head200 = weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["200"]
    weakened["components"]["responses"]["HeadUpload200"] = copy.deepcopy(head200)
    weakened["paths"]["/uploads/{id}/files/{name}"]["head"]["responses"]["200"] = {
        "$ref": "#/components/responses/HeadUpload200",
        "content": {"application/json": {}},
    }
    found = check_openapi("backend", weakened)
    assert not [
        violation
        for violation in found
        if "promises a body the method or status forbids" in violation.detail
    ], [violation.render() for violation in found]


# --- Round 18: sibling conjunction, Reference Object hops, scheme refs, cycle
# --- policy, and the guarded OTA body -----------------------------------------


def test_ref_sibling_assertions_agree_with_a_standard_validator(device: dict) -> None:
    """F1: siblings of a ``$ref`` conjoin with the target, keyword for keyword.

    The round-17 merge handed every keyword the sibling spelled to the sibling,
    so an overlapping ``pattern``, ``required``, ``properties`` or ``minimum``
    silently dropped the referenced assertion. JSON Schema 2020-12 §8.2.3.1
    evaluates both, and this asks the same node and instance of a Draft
    2020-12 validator with a real ref resolver and of
    ``schema_error_report(resolve_refs(...))``, pinning that they agree —
    including the review's ``+``-string case and a weakening attempt whose
    sibling pattern is strictly broader than the target's.
    """
    from jsonschema import Draft202012Validator, RefResolver

    document = {
        "$defs": {
            "Secret": {"type": "string", "pattern": "^[a-z]{3}$"},
            "Count": {"type": "integer", "minimum": 5, "maximum": 10},
            "Box": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            },
        }
    }
    cases = (
        # label, node, instance, expected_rejected_by_both
        (
            "sibling pattern overlapping the target, outside the target",
            {"$ref": "#/$defs/Secret", "pattern": "^[a-z+]{3}$"},
            "+++",
            True,
        ),
        (
            "sibling pattern overlapping the target, inside the intersection",
            {"$ref": "#/$defs/Secret", "pattern": "^[a-z+]{3}$"},
            "abc",
            False,
        ),
        (
            "attempted weakening: a strictly broader sibling still rejects",
            {"$ref": "#/$defs/Secret", "pattern": "^.{3}$"},
            "+++",
            True,
        ),
        (
            "sibling minimum cannot lower the target floor",
            {"$ref": "#/$defs/Count", "minimum": 0},
            3,
            True,
        ),
        (
            "sibling minimum, instance inside both floors",
            {"$ref": "#/$defs/Count", "minimum": 0},
            7,
            False,
        ),
        (
            "sibling required cannot drop the target's required member",
            {"$ref": "#/$defs/Box", "required": ["b"]},
            {"b": "y"},
            True,
        ),
        (
            "sibling required keeps both lists binding",
            {"$ref": "#/$defs/Box", "required": ["b"]},
            {"a": "x", "b": "y"},
            False,
        ),
        (
            "sibling properties cannot drop a target property constraint",
            {"$ref": "#/$defs/Box", "properties": {"a": {"type": "string"}}},
            {"a": "x", "b": 42},
            True,
        ),
        (
            "disjoint sibling key conjoins beside the target",
            {"$ref": "#/$defs/Secret", "description": "rides along"},
            "abc",
            False,
        ),
    )
    for label, node, instance, rejected in cases:
        standard = Draft202012Validator(node, resolver=RefResolver.from_schema(document))
        standard_errors = list(standard.iter_errors(instance))
        resolved_errors = schema_error_report(resolve_refs(node, root=document), instance)
        assert bool(standard_errors) is rejected, (label, [e.message for e in standard_errors])
        assert bool(resolved_errors) is rejected, (
            label,
            resolved_errors,
            [e.message for e in standard_errors],
        )

    # The review's mutation on the real document: a broader sibling pattern on
    # the pair-request secret cannot admit the ``+`` string the referenced
    # ``SetupSecret`` pattern prohibits, and the valid secret still passes.
    weakened = copy.deepcopy(device)
    weakened["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"][
        "pattern"
    ] = r"^[A-Za-z0-9_+\-]{43}$"
    raw = weakened["components"]["schemas"]["PairRequest"]
    for secret, rejected in (("+" * 43, True), ("A" * 43, False)):
        instance = {"v": 1, "setup_secret": secret, "client_name": "review"}
        standard = Draft202012Validator(raw, resolver=RefResolver.from_schema(weakened))
        standard_errors = list(standard.iter_errors(instance))
        report = schema_error_report(resolve_refs(raw, root=weakened), instance)
        assert bool(standard_errors) is rejected, secret
        assert bool(report) is rejected, (secret, report)
        if rejected:
            assert any(
                keyword == "pattern" and "^[A-Za-z0-9_-]{43}$" in message
                for _property, keyword, message in report
            ), report


def test_a_two_hop_header_alias_cannot_weaken_a_required_response_header(
    backend: dict, tmp_path: Path
) -> None:
    """F2: a Reference Object carries only ``$ref`` at every hop of the chain.

    The review's mutation: an optional copy of ``UploadOffset`` behind an alias
    that declares ``required: true`` beside its own ``$ref``. Round 17 merged
    that alias sibling into the target, so the gate certified a 204 whose
    ``Upload-Offset`` had been demoted to a suggestion. OpenAPI 3.1 Reference
    Object semantics strip it at the alias hop — the effective Header Object
    is the optional copy, and the required-ness gate says so through the
    complete validator, not only the operation scan.
    """
    import yaml

    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    target = copy.deepcopy(weakened["components"]["headers"]["UploadOffset"])
    target["required"] = False
    weakened["components"]["headers"]["ReviewOptionalOffset"] = target
    weakened["components"]["headers"]["ReviewOffsetAlias"] = {
        "$ref": "#/components/headers/ReviewOptionalOffset",
        "required": True,
    }
    weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["responses"]["204"]["headers"][
        "Upload-Offset"
    ] = {"$ref": "#/components/headers/ReviewOffsetAlias"}
    found = [
        violation
        for violation in check_openapi("backend", weakened)
        if violation.code == E.SPEC_STRUCTURE_MISSING
        and violation.location
        == "backend-v1 PATCH /uploads/{id}/files/{name} responses/204 headers/Upload-Offset"
    ]
    assert found and all("declares it optional" in violation.detail for violation in found), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]

    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "backend-v1.yaml").write_text(yaml.safe_dump(weakened, sort_keys=False), encoding="utf-8")
    report = validate_contracts(tmp_path)
    assert not report.passed, "the complete validator must refuse the weakened header"
    assert any(
        violation.code == E.SPEC_STRUCTURE_MISSING
        and "declares it optional" in violation.detail
        for violation in report.violations
    ), [violation.render() for violation in report.violations]


def test_a_parameter_alias_sibling_cannot_make_a_required_parameter_optional(
    backend: dict,
) -> None:
    """F2 at the parameter position: the sibling beside a hop is decoration.

    ``Upload-Checksum`` is already a ``$ref`` component; pointing the operation
    two hops away at a decoy that declares ``required: false`` beside its own
    ``$ref`` is the same weakening the header probe ran at the parameter
    position. Reference Object semantics strip the decoy's sibling, so the
    required-request-header gate still reads the component's own
    ``required: true`` and says nothing.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    real = copy.deepcopy(weakened["components"]["parameters"]["UploadChecksum"])
    assert real.get("required") is True, "the pinned sibling is a real weakening attempt"
    weakened["components"]["parameters"]["ChecksumReal"] = real
    weakened["components"]["parameters"]["ChecksumDecoy"] = {
        "$ref": "#/components/parameters/ChecksumReal",
        "required": False,
    }
    parameters = weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["parameters"]
    parameters[
        parameters.index({"$ref": "#/components/parameters/UploadChecksum"})
    ] = {"$ref": "#/components/parameters/ChecksumDecoy"}
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_nested_references_through_a_shared_response_component_still_resolve(
    backend: dict,
) -> None:
    """F2: the reference-mode walk follows every nested hop it reaches.

    The 204 moved into ``components.responses`` keeps its header ``$ref``, and
    that header now rides one more alias hop before its Header Object with its
    ``schema`` member. Resolution still reaches the target through response →
    header → alias → object, so the required ``Upload-Offset`` is read as the
    component declares it and the shared answer certifies clean.
    """
    assert not check_openapi("backend", backend)
    weakened = copy.deepcopy(backend)
    offset204 = copy.deepcopy(
        weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["responses"]["204"]
    )
    weakened["components"]["responses"]["Offset204"] = offset204
    weakened["components"]["headers"]["UploadOffsetAlias"] = {
        "$ref": "#/components/headers/UploadOffset"
    }
    offset204["headers"]["Upload-Offset"] = {"$ref": "#/components/headers/UploadOffsetAlias"}
    weakened["paths"]["/uploads/{id}/files/{name}"]["patch"]["responses"]["204"] = {
        "$ref": "#/components/responses/Offset204"
    }
    assert not check_openapi("backend", weakened), [
        violation.render() for violation in check_openapi("backend", weakened)
    ]


def test_reference_object_decoration_is_stripped_at_every_hop() -> None:
    """F2: ``summary``/``description`` (and anything else) never reach the target.

    A Reference Object decorates, it does not augment — and the strip is a hop
    rule, not a first-node rule: the decoration carried by an intermediate
    alias (here a contradicting ``required`` and a ``summary``) is gone before
    the next hop is read, exactly as the outer node's own ``description`` is.
    The target's own members, including its ``schema``, survive untouched.
    """
    document = {
        "components": {
            "headers": {
                "Real": {
                    "description": "real words",
                    "required": True,
                    "schema": {"type": "integer", "minimum": 3},
                },
                "Mid": {
                    "$ref": "#/components/headers/Real",
                    "required": False,
                    "summary": "decoration",
                },
            }
        }
    }
    resolved = resolve_reference(
        {
            "$ref": "#/components/headers/Mid",
            "description": "outer",
            "required": False,
            "x-decoration": 1,
        },
        root=document,
    )
    assert resolved == {
        "description": "real words",
        "required": True,
        "schema": {"type": "integer", "minimum": 3},
    }


def test_security_scheme_reference_objects_are_resolved_before_the_bearer_check(
    device: dict,
) -> None:
    """F3: ``components.securitySchemes`` entries may be Reference Objects.

    The authentication gate used to read ``bearerAuth`` inline, so moving the
    unchanged HTTP bearer definition to a shared component and referencing it —
    legal OpenAPI — charged every protected operation a ``SPEC_SECURITY_MISSING``
    for a scheme the document does define. The name is now followed the
    Reference-Object way (direct hop and chained hops), and the failures a
    pointer can make answer with the named strings the gate already used,
    never an exception: a dangling target and a cycle both say ``is not
    defined``, and a wrong-scheme target keeps the not-an-HTTP-bearer wording.
    """
    assert not check_openapi("device", device)
    bearer = device["components"]["securitySchemes"]["bearerAuth"]

    direct = copy.deepcopy(device)
    direct["components"]["securitySchemes"]["ReviewBearer"] = copy.deepcopy(bearer)
    direct["components"]["securitySchemes"]["bearerAuth"] = {
        "$ref": "#/components/securitySchemes/ReviewBearer"
    }
    assert not _security_findings(direct, "device")
    assert not check_openapi("device", direct), [
        violation.render() for violation in check_openapi("device", direct)
    ]

    chained = copy.deepcopy(direct)
    chained["components"]["securitySchemes"]["ReviewBase"] = copy.deepcopy(bearer)
    chained["components"]["securitySchemes"]["ReviewBearer"] = {
        "$ref": "#/components/securitySchemes/ReviewBase"
    }
    assert not _security_findings(chained, "device")

    dangling = copy.deepcopy(device)
    dangling["components"]["securitySchemes"]["bearerAuth"] = {
        "$ref": "#/components/securitySchemes/Gone"
    }
    found = _security_findings(dangling, "device")
    assert {violation.location for violation in found} == _protected_locations("device"), [
        violation.render() for violation in found
    ]
    named = next(violation for violation in found if violation.location == "GET /status")
    assert "securitySchemes" in named.detail and "not defined" in named.detail, named.render()

    cycle = copy.deepcopy(device)
    cycle["components"]["securitySchemes"]["bearerAuth"] = {
        "$ref": "#/components/securitySchemes/Loop"
    }
    cycle["components"]["securitySchemes"]["Loop"] = {
        "$ref": "#/components/securitySchemes/bearerAuth"
    }
    found = _security_findings(cycle, "device")
    assert {violation.location for violation in found} == _protected_locations("device"), [
        violation.render() for violation in found
    ]
    # The cycle says exactly what a missing member says — the same named string,
    # not just findings at the same locations (the pre-gate code also produced
    # findings here, with the wrong wording).
    named = next(violation for violation in found if violation.location == "GET /status")
    assert "securitySchemes" in named.detail and "not defined" in named.detail, named.render()

    wrong = copy.deepcopy(device)
    wrong["components"]["securitySchemes"]["ApiKeyBearer"] = {
        "type": "apiKey",
        "in": "query",
        "name": "token",
    }
    wrong["components"]["securitySchemes"]["bearerAuth"] = {
        "$ref": "#/components/securitySchemes/ApiKeyBearer"
    }
    found = _security_findings(wrong, "device")
    assert found and all(
        "not an HTTP bearer scheme" in violation.detail for violation in found
    ), [violation.render() for violation in found]


def test_independent_sibling_references_are_not_a_cycle(device: dict, tmp_path: Path) -> None:
    """F4: two assertions of one finite target are reuse, not recursion.

    ``resolve_refs`` used to keep the node's own ``$ref`` on the cycle stack
    while resolving siblings, so ``{"$ref": A, "allOf": [{"$ref": A}]}`` — two
    independent assertions of the same non-recursive schema, which standard
    validators accept — aborted the CLI as ``ValueError: recursive $ref``.
    Sibling subtrees now see the stack as it stood before the node's own
    pointer was pushed; diamond-shaped reuse of one target stays fine, and
    genuine recursion — a target expansion reaching an enclosing in-flight
    pointer — is still refused by name.
    """
    root = {"$defs": {"T": {"type": "integer"}}}
    assert resolve_refs({"$ref": "#/$defs/T", "allOf": [{"$ref": "#/$defs/T"}]}, root=root) == {
        "allOf": [{"type": "integer"}, {"allOf": [{"type": "integer"}]}]
    }
    assert resolve_refs({"allOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/T"}]}, root=root) == {
        "allOf": [{"type": "integer"}, {"type": "integer"}]
    }
    cyclic = {
        "$defs": {
            "A": {"allOf": [{"$ref": "#/$defs/B"}]},
            "B": {"$ref": "#/$defs/A"},
        }
    }
    with pytest.raises(ValueError, match=re.escape("recursive $ref '#/$defs/A'")):
        resolve_refs({"$ref": "#/$defs/A"}, root=cyclic)

    # The review's document-level case: a second, independent ``SetupSecret``
    # assertion beside the pair-request pointer resolves, still binds both
    # assertions, and certifies the whole corpus clean.
    import yaml

    strengthened = copy.deepcopy(device)
    strengthened["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"][
        "allOf"
    ] = [{"$ref": "#/components/schemas/SetupSecret"}]
    assert not check_openapi("device", strengthened)
    resolved = resolve_refs(
        strengthened["components"]["schemas"]["PairRequest"], root=strengthened
    )
    assert not schema_error_report(
        resolved, {"v": 1, "setup_secret": "A" * 43, "client_name": "review"}
    )
    assert schema_error_report(
        resolved, {"v": 1, "setup_secret": "+" * 43, "client_name": "review"}
    ), "both independent assertions of SetupSecret must still bind"
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "device-v1.yaml").write_text(
        yaml.safe_dump(strengthened, sort_keys=False), encoding="utf-8"
    )
    report = validate_contracts(tmp_path)
    assert report.passed and not report.violations, [
        violation.render() for violation in report.violations
    ]


def test_ota_deferral_reads_a_shared_body_like_its_inline_twin_and_refuses_malformed_shapes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """F5: one guarded, Reference-Object-aware reader for the OTA requestBody.

    ``check_ota_deferral`` used to ``.get`` the raw ``requestBody`` and
    ``set(content)``: a body legally moved into ``components.requestBodies``
    was charged ``OTA_DEFERRAL_MISSING`` although the operation checker read
    the same reference fine, and a null ``content`` reached the CLI as an
    exit-2 ``TypeError``. The body now goes through the guarded resolution the
    operation checker uses — inline and reused answer identically through the
    complete validator — while malformed body, content and media-entry shapes
    stay named document findings that fail the CLI at exit 1.
    """
    import yaml

    from tools.contracts import cli

    document = load_yaml(CONTRACTS / "device-v1.yaml")
    assert not check_ota_deferral(document, CONTRACTS)

    reused = copy.deepcopy(document)
    reused["components"].setdefault("requestBodies", {})["ReviewOtaBody"] = copy.deepcopy(
        reused["paths"]["/ota"]["post"]["requestBody"]
    )
    reused["paths"]["/ota"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/ReviewOtaBody"
    }
    assert not check_ota_deferral(reused, CONTRACTS), "a reused body is the inline body"
    scratch = tmp_path / "reused"
    scratch.mkdir(parents=True)
    shutil.copytree(CONTRACTS, scratch / "contracts")
    (scratch / "contracts" / "device-v1.yaml").write_text(
        yaml.safe_dump(reused, sort_keys=False), encoding="utf-8"
    )
    report = validate_contracts(scratch)
    assert (report.fixture_total, len(report.violations), report.passed) == (441, 0, True), [
        violation.render() for violation in report.violations
    ]

    for label, mutate, code, location, detail in (
        (
            "null-content",
            lambda d: d["paths"]["/ota"]["post"]["requestBody"].__setitem__("content", None),
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody content",
            "is NoneType, not a media-type map",
        ),
        (
            "null-body",
            lambda d: d["paths"]["/ota"]["post"].__setitem__("requestBody", None),
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody",
            "must be exactly one application/octet-stream content entry",
        ),
        (
            "null-entry",
            lambda d: d["paths"]["/ota"]["post"]["requestBody"]["content"].__setitem__(
                "application/octet-stream", None
            ),
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody content",
            "media type 'application/octet-stream' is NoneType, not a media-type object",
        ),
    ):
        mutated = copy.deepcopy(document)
        mutate(mutated)
        found = check_ota_deferral(mutated, CONTRACTS)
        assert [(v.code, v.location, v.detail) for v in found] == [(code, location, detail)], (
            label,
            [v.render() for v in found],
        )
        broken = tmp_path / label
        broken.mkdir(parents=True)
        shutil.copytree(CONTRACTS, broken / "contracts")
        (broken / "contracts" / "device-v1.yaml").write_text(
            yaml.safe_dump(mutated, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.chdir(broken)
        assert cli.main([]) == 1, label  # never 2: no internal error, only a failing check
        captured = capsys.readouterr()
        assert "validator internal error" not in captured.err, (label, captured.err)
        assert "Traceback" not in captured.err, (label, captured.err)

    # A dangling body reference is the named component drift the response
    # readers already use, not a false content complaint and not a crash.
    dangling = copy.deepcopy(document)
    dangling["paths"]["/ota"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/Gone"
    }
    found = check_ota_deferral(dangling, CONTRACTS)
    assert [(v.code, v.location) for v in found] == [
        (E.SPEC_COMPONENT_DRIFT, "POST /ota requestBody")
    ], [v.render() for v in found]
    # The guarded wording names the first member the document does not define
    # — the same convention the response and header readers keep.
    assert "requestBodies" in found[0].detail and "does not define" in found[0].detail, (
        found[0].render()
    )


def test_a_referenced_body_cannot_smuggle_a_request_schema_past_the_deferral_gate(
    device: dict,
) -> None:
    """Review finding 1 (round-18 review): the ref-presence question reads the
    *un-inlined* body, so reuse cannot launder a deferred envelope back in.

    The full read resolves a ``$ref``'d body wholesale, and the schema-position
    walk resolves the media entry's ``schema`` member with it — so asking
    ``"$ref" in schema`` of the *resolved* body answers "references no schema"
    for exactly the body that does, while the identical inline twin is refused.
    AC-07's deferral must mean the same thing at both spellings: the operation
    checker already asks its binding question of the shallow alias-chained node
    for this reason, and so does this gate.
    """
    smuggled = copy.deepcopy(device)
    smuggled["components"].setdefault("requestBodies", {})["SmuggledOtaBody"] = {
        "required": True,
        "description": (
            "signed envelope; encoding and `contracts/ota-v1.json` deferred to "
            "package 2.10; consumers must not guess"
        ),
        "content": {
            "application/octet-stream": {"schema": {"$ref": "#/components/schemas/Error"}}
        },
    }
    smuggled["paths"]["/ota"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/SmuggledOtaBody"
    }
    found = check_ota_deferral(smuggled, CONTRACTS)
    assert [(v.code, v.location, v.detail) for v in found] == [
        (
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody schema",
            "no request schema may be referenced while the encoding is deferred",
        )
    ], [v.render() for v in found]

    # The inline twin — the same schema member riding on the inline body —
    # answers identically: reuse is neither a laundering route nor a false alarm.
    inline = copy.deepcopy(device)
    inline["paths"]["/ota"]["post"]["requestBody"]["content"]["application/octet-stream"][
        "schema"
    ] = {"$ref": "#/components/schemas/Error"}
    inline_found = check_ota_deferral(inline, CONTRACTS)
    assert [(v.code, v.location, v.detail) for v in inline_found] == [
        (v.code, v.location, v.detail) for v in found
    ], [v.render() for v in inline_found]

    # The same class one level deeper: a `$ref` spelled at the Media Type
    # Object position (not an OpenAPI 3.1 reference position — the repo runs
    # no OpenAPI metaschema over these documents) is still a route for a
    # shared component to bring a referenced schema back into the body, so it
    # is the same deferral refusal.
    entry_ref = copy.deepcopy(device)
    entry_ref["components"]["schemas"]["OtaEntryTarget"] = {
        "schema": {"$ref": "#/components/schemas/Error"}
    }
    entry_ref["components"].setdefault("requestBodies", {})["EntryRefOtaBody"] = {
        "required": True,
        "description": (
            "signed envelope; encoding and `contracts/ota-v1.json` deferred to "
            "package 2.10; consumers must not guess"
        ),
        "content": {
            "application/octet-stream": {
                "$ref": "#/components/schemas/OtaEntryTarget"
            }
        },
    }
    entry_ref["paths"]["/ota"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/EntryRefOtaBody"
    }
    found_entry = check_ota_deferral(entry_ref, CONTRACTS)
    assert [(v.code, v.location, v.detail) for v in found_entry] == [
        (
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody schema",
            "no request schema may be referenced while the encoding is deferred",
        )
    ], [v.render() for v in found_entry]

    # Its inline twin, so the entry-position rule is pinned on both spellings
    # like the two directions above: here the un-inlined node *is* the body.
    inline_entry = copy.deepcopy(device)
    inline_entry["components"]["schemas"]["OtaEntryTarget"] = {
        "schema": {"$ref": "#/components/schemas/Error"}
    }
    inline_entry["paths"]["/ota"]["post"]["requestBody"]["content"][
        "application/octet-stream"
    ] = {"$ref": "#/components/schemas/OtaEntryTarget"}
    found_inline_entry = check_ota_deferral(inline_entry, CONTRACTS)
    assert [(v.code, v.location, v.detail) for v in found_inline_entry] == [
        (v.code, v.location, v.detail) for v in found_entry
    ], [v.render() for v in found_inline_entry]

    # And the legal "declares nothing" spelling — an empty Media Type Object —
    # stays clean, so the entry-position rule reports no reference where the
    # document spells none.
    empty_entry = copy.deepcopy(device)
    empty_entry["paths"]["/ota"]["post"]["requestBody"]["content"][
        "application/octet-stream"
    ] = {}
    assert not check_ota_deferral(empty_entry, CONTRACTS)

    # And the honest shapes still certify clean both ways (the shared component
    # the probe moves verbatim; a non-mapping `schema` references nothing).
    clean = copy.deepcopy(device)
    clean["components"].setdefault("requestBodies", {})["ReviewOtaBody"] = copy.deepcopy(
        clean["paths"]["/ota"]["post"]["requestBody"]
    )
    clean["paths"]["/ota"]["post"]["requestBody"] = {
        "$ref": "#/components/requestBodies/ReviewOtaBody"
    }
    assert not check_ota_deferral(clean, CONTRACTS)
    scalar_schema = copy.deepcopy(device)
    scalar_schema["paths"]["/ota"]["post"]["requestBody"]["content"]["application/octet-stream"][
        "schema"
    ] = "not-a-schema"
    assert not check_ota_deferral(scalar_schema, CONTRACTS)


# --- Round 19: annotation-scope validation, aliased-header scan, ----------------
# --- components guards, and the composed OTA schema reference --------------------


def _report_triples(
    report: list[tuple[str, str, str]],
) -> set[tuple[str, str, str]]:
    return {(property_name, keyword, message) for property_name, keyword, message in report}


def _standard_triples(validator, instance) -> set[tuple[str, str, str]]:
    triples: set[tuple[str, str, str]] = set()
    for error in validator.iter_errors(instance):
        property_name = ""
        for part in reversed(list(error.absolute_path)):
            if isinstance(part, str):
                property_name = part
                break
        message = error.message.replace("\n", " ")
        if len(message) > 200:
            message = message[:197] + "..."
        triples.add((property_name, str(error.validator or ""), message))
    return triples


def test_a_ref_sibling_unevaluated_properties_agrees_with_the_standard_validator(
    device: dict, tmp_path: Path
) -> None:
    """F1: instance validation must keep ``$ref`` siblings in schema scope.

    The round-18 ``{"allOf": [target, siblings]}`` pre-expansion splits the
    ``$ref`` node into two independently validated branches, and
    ``unevaluatedProperties`` (JSON Schema 2020-12 §11.3) only observes the
    annotations of applicators in its own scope — so the review's strict
    ``PairRequest`` = ``{"$ref": …, "unevaluatedProperties": false}`` over a
    copy of itself reported every legitimate field as unevaluated. The report
    now judges the raw node against the whole document through an offline
    local-reference registry, and this pins it against a standard Draft
    2020-12 validator on the actual contract: the valid pair request reports
    zero errors and the corpus certifies the edited document 441/0, while the
    extra property earns exactly the errors — and only the errors — the
    standard validator names.
    """
    import yaml

    from jsonschema import Draft202012Validator

    assert not check_openapi("device", device)

    weakened = copy.deepcopy(device)
    weakened["components"]["schemas"]["ReviewPairBase"] = copy.deepcopy(
        weakened["components"]["schemas"]["PairRequest"]
    )
    weakened["components"]["schemas"]["PairRequest"] = {
        "$ref": "#/components/schemas/ReviewPairBase",
        "unevaluatedProperties": False,
    }
    raw = weakened["components"]["schemas"]["PairRequest"]
    valid = {"v": 1, "setup_secret": "A" * 43, "client_name": "review"}
    oracle = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/components/schemas/PairRequest",
        "components": weakened["components"],
    }

    # The valid pair request: zero errors from the standard validator over the
    # complete local root, and zero from the report on the raw node.
    assert not list(Draft202012Validator(oracle).iter_errors(valid)), (
        "the standard validator itself must accept the valid pair request"
    )
    assert not schema_error_report(raw, valid, root=weakened), (
        "a $ref target that already evaluates every field must leave a sibling "
        "unevaluatedProperties nothing to refuse"
    )

    # The extra property: the report agrees with the standard validator on the
    # exact (property, keyword, message) triples — including the one
    # unevaluatedProperties error the pre-expansion fabricated for every
    # legitimate field instead.
    extra = {**valid, "surprise": True}
    standard = _standard_triples(Draft202012Validator(oracle), extra)
    assert sum(keyword == "unevaluatedProperties" for _p, keyword, _m in standard) == 1, standard
    report = schema_error_report(raw, extra, root=weakened)
    assert _report_triples(report) == standard, (report, sorted(standard))

    # The complete corpus certifies that edited document, every fixture.
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "device-v1.yaml").write_text(
        yaml.safe_dump(weakened, sort_keys=False), encoding="utf-8"
    )
    result = validate_contracts(tmp_path)
    assert result.fixture_total == 441 and result.passed, [
        violation.render() for violation in result.violations
    ]

    # The real API path keeps the referenced target's verdict (the round-18
    # ``+``-secret pin, restated for the raw rooted read that replaced the
    # pre-expansion at this call site): a strictly broader sibling pattern
    # beside the ``setup_secret`` pointer cannot admit the ``+`` string the
    # referenced ``SetupSecret`` prohibits, and the valid secret still passes.
    from tools.contracts.api_validate import _validate_against_component

    api_doc = copy.deepcopy(device)
    api_doc["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"][
        "pattern"
    ] = r"^[A-Za-z0-9_+\-]{43}$"
    entry = {"id": "device/review-plus-secret"}
    violations = _validate_against_component(
        api_doc, "PairRequest", {"v": 1, "setup_secret": "+" * 43, "client_name": "review"}, entry
    )
    assert any(
        violation.code == E.API_SCHEMA
        and "^[A-Za-z0-9_-]{43}$" in violation.detail
        for violation in violations
    ), [violation.render() for violation in violations]
    assert not _validate_against_component(api_doc, "PairRequest", valid, entry)


def test_a_ref_sibling_unevaluated_items_agrees_with_the_standard_validator() -> None:
    """F1's §11.3 twin: ``unevaluatedItems`` shares the annotation-scope rule.

    The same scoping dependency that broke ``unevaluatedProperties`` also
    breaks ``unevaluatedItems``: a sibling of a ``$ref`` may only see the
    ``prefixItems`` annotations the target produces in the target's own
    scope. A target declaring ``prefixItems`` with a sibling
    ``unevaluatedItems: false`` must accept the prefix-length array and
    refuse the additional item — exactly as the standard validator does.
    """
    from jsonschema import Draft202012Validator

    document = {"$defs": {"Tuple": {"type": "array", "prefixItems": [{"type": "integer"}]}}}
    node = {"$ref": "#/$defs/Tuple", "unevaluatedItems": False}
    oracle = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/$defs/Tuple",
        "unevaluatedItems": False,
        "$defs": document["$defs"],
    }

    assert not list(Draft202012Validator(oracle).iter_errors([1]))
    assert not schema_error_report(node, [1], root=document), (
        "a $ref target's prefixItems annotation must bind a sibling unevaluatedItems"
    )

    standard = _standard_triples(Draft202012Validator(oracle), [1, "x"])
    assert [keyword for _p, keyword, _m in standard] == ["unevaluatedItems"], standard
    report = schema_error_report(node, [1, "x"], root=document)
    assert _report_triples(report) == standard, (report, sorted(standard))


def test_a_decorated_response_alias_cannot_hide_target_duplicate_headers(
    backend: dict, tmp_path: Path
) -> None:
    """F2: the all-response scan reads the *effective target's* header map.

    The scan took the header name map from ``_shallow_reference``'s one-hop
    node even when that node was itself a Reference Object, so a ``headers``
    member beside the alias's ``$ref`` — inert decoration the reference does
    not merge — displaced the target's real map: ``ETag`` beside ``etag``
    inside a shared ``components/responses`` member earned its duplicate
    finding when referenced directly but hid behind an alias carrying
    ``headers: {}``. The scan now ignores the decoration and reads the
    target's map, so the duplicate is refused whatever route the document
    takes to it, and the complete validator fails the corpus on it.
    """
    import yaml

    assert not check_openapi("backend", backend)

    weakened = copy.deepcopy(backend)
    real = copy.deepcopy(weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"])
    real["headers"] = {
        "ETag": {"$ref": "#/components/headers/ETagSha256"},
        "etag": {"$ref": "#/components/headers/ETagSha256"},
    }
    weakened["components"]["responses"]["ReviewClip200"] = real

    def duplicates(found: list) -> list:
        return [
            violation
            for violation in found
            if violation.code == E.SPEC_STRUCTURE_MISSING and "declared twice" in violation.detail
        ]

    # The direct-reference control, unchanged: the target's own duplicate
    # spelling earns its one finding.
    direct = copy.deepcopy(weakened)
    direct["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ReviewClip200"
    }
    direct_found = check_openapi("backend", direct)
    assert len(duplicates(direct_found)) == 1, [v.render() for v in direct_found]

    # The decorated alias: an inert ``headers: {}`` beside the reference must
    # not stand in for the target's map — the duplicate still earns exactly
    # one finding, and it is the only thing this document breaks.
    weakened["components"]["responses"]["ReviewClipAlias"] = {
        "$ref": "#/components/responses/ReviewClip200",
        "headers": {},
    }
    weakened["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ReviewClipAlias"
    }
    found = check_openapi("backend", weakened)
    assert len(duplicates(found)) == 1, [violation.render() for violation in found]
    assert len(found) == 1, [violation.render() for violation in found]

    # And the corpus run on that edited document FAILS.
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "backend-v1.yaml").write_text(
        yaml.safe_dump(weakened, sort_keys=False), encoding="utf-8"
    )
    result = validate_contracts(tmp_path)
    assert not result.passed, "the complete validator must refuse the hidden duplicate"
    assert any(
        violation.code == E.SPEC_STRUCTURE_MISSING and "declared twice" in violation.detail
        for violation in result.violations
    ), [violation.render() for violation in result.violations]


def test_a_decorated_response_alias_neither_fabricates_nor_silences_header_findings(
    backend: dict,
) -> None:
    """F2's opposite direction, plus the per-attribution floor behind an alias.

    A dangling ``$ref`` inside the ignored ``headers`` decoration is inert —
    no effective read ever follows it, and the scan must not inspect it as a
    real header (round 18 charged a false ``SPEC_COMPONENT_DRIFT`` for
    exactly that). An unreadable *target* header map, by contrast, is a real
    defect: with the alias's ``headers: {}`` out of the way the scan has no
    readable shallow map to lean on, so the response-level drift names the
    failing member — an inert decoration must not talk the scan into a
    silent pass.
    """
    assert not check_openapi("backend", backend)

    # The ignored decoration is never inspected: zero findings.
    ignored = copy.deepcopy(backend)
    ignored["components"]["responses"]["ReviewClip200"] = copy.deepcopy(
        ignored["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"]
    )
    ignored["components"]["responses"]["ReviewClipAlias"] = {
        "$ref": "#/components/responses/ReviewClip200",
        "headers": {"X-Ignored": {"$ref": "#/components/headers/ReviewMissingHeader"}},
    }
    ignored["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ReviewClipAlias"
    }
    assert not check_openapi("backend", ignored), [
        violation.render() for violation in check_openapi("backend", ignored)
    ]

    # The target's own unreadable header map still fails closed: the alias's
    # ``headers: {}`` cannot hide it and cannot become the finding's subject.
    broken = copy.deepcopy(backend)
    target = copy.deepcopy(broken["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"])
    target["headers"] = {"ETag": {"$ref": "#/components/headers/ReviewMissingHeader"}}
    broken["components"]["responses"]["ReviewClip200"] = target
    broken["components"]["responses"]["ReviewClipAlias"] = {
        "$ref": "#/components/responses/ReviewClip200",
        "headers": {},
    }
    broken["paths"]["/clips/{clip_id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/ReviewClipAlias"
    }
    found = check_openapi("backend", broken)
    drift = [
        violation
        for violation in found
        if violation.code == E.SPEC_COMPONENT_DRIFT
        and violation.location == "backend-v1 GET /clips/{clip_id} responses/200"
        and "ReviewMissingHeader" in violation.detail
    ]
    assert drift, [violation.render() for violation in found]


def test_the_ota_deferral_gate_refuses_a_schema_reference_under_any_applicator(
    device: dict, tmp_path: Path
) -> None:
    """F4 (queued R3-N2): a schema ref under a standard applicator is still a ref.

    The gate tested only whether ``$ref`` was a *direct* member of the
    octet-stream Media Type Object or of its ``schema``, so
    ``schema: {"allOf": [{"$ref": …}]}`` — legal OpenAPI schema content and
    still a request-schema reference — slipped through clean while the
    identical direct reference was refused. The deferral is enforced
    fail-closed now: any Mapping member of the un-inlined entry's subtree
    that carries a ``$ref`` earns the one refusal, and the non-mapping
    guard (the ``in``-over-scalar crash) is kept.
    """
    import yaml

    committed = check_ota_deferral(device, CONTRACTS)
    assert not committed, [violation.render() for violation in committed]

    expected = [
        (
            E.OTA_DEFERRAL_MISSING,
            "POST /ota requestBody schema",
            "no request schema may be referenced while the encoding is deferred",
        )
    ]

    # The walk answers the verdict for every *sequence* spelling, not just
    # the lists YAML produces: a programmatically built document smuggling the
    # reference inside a tuple is the same refusal (the reviewer's plan-text
    # note), and a scalar whose text merely contains ``$ref`` references
    # nothing — strings are sequences of characters, and the walk excludes
    # them so a scalar never membership-tests into a false refusal.
    tupled = copy.deepcopy(device)
    tupled["paths"]["/ota"]["post"]["requestBody"]["content"][
        "application/octet-stream"
    ]["schema"] = {"allOf": ({"$ref": "#/components/schemas/VersionedRequest"},)}
    found = check_ota_deferral(tupled, CONTRACTS)
    assert [(v.code, v.location, v.detail) for v in found] == expected

    scalar = copy.deepcopy(device)
    scalar["paths"]["/ota"]["post"]["requestBody"]["content"][
        "application/octet-stream"
    ]["schema"] = "all $ref strings here reference nothing"
    assert not check_ota_deferral(scalar, CONTRACTS)
    forms = {
        "direct": {"$ref": "#/components/schemas/VersionedRequest"},
        "allOf": {"allOf": [{"$ref": "#/components/schemas/VersionedRequest"}]},
        "deep": {"anyOf": [{"items": {"$ref": "#/components/schemas/VersionedRequest"}}]},
    }
    composed = None
    for label, schema in forms.items():
        weakened = copy.deepcopy(device)
        weakened["paths"]["/ota"]["post"]["requestBody"]["content"][
            "application/octet-stream"
        ]["schema"] = schema
        found = check_ota_deferral(weakened, CONTRACTS)
        assert [(v.code, v.location, v.detail) for v in found] == expected, (
            label,
            [v.render() for v in found],
        )
        if label == "allOf":
            composed = weakened

    # The complete corpus run on the composed-ref document reports the
    # finding — it does not PASS — and the committed corpus stays 441/0/PASS.
    broken = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, broken)
    (broken / "device-v1.yaml").write_text(
        yaml.safe_dump(composed, sort_keys=False), encoding="utf-8"
    )
    result = validate_contracts(tmp_path)
    assert not result.passed, "the composed schema ref must fail the corpus run"
    assert any(
        violation.code == E.OTA_DEFERRAL_MISSING
        and "no request schema may be referenced" in violation.detail
        for violation in result.violations
    ), [violation.render() for violation in result.violations]
    baseline = validate_contracts(REPO_ROOT)
    assert baseline.fixture_total == 441 and not baseline.violations and baseline.passed


#: The one dialect a contract component may legally spell on its own: OpenAPI
#: 3.1 schemas are 2020-12, and the round-20 finding is exactly what a
#: component declaring that dialect must not do to the instance validator.
_2020_12_DIALECT: Final[str] = "https://json-schema.org/draft/2020-12/schema"


def test_a_declared_2020_12_dialect_keeps_the_exact_number_validator_through_evolution(
    backend: dict,
) -> None:
    """F1 (round 20): ``$ref`` onto a dialect-spelling target keeps the Decimal branch.

    Reference following evolves the validator onto the class
    ``validator_for`` reads from the target's own ``$schema``, and at
    225e3ba a target spelling the supported 2020-12 dialect evolved onto the
    built-in :class:`~jsonschema.Draft202012Validator` mid-validation — the
    exact-number integer branch went with the class, and a
    ``parse_float=decimal.Decimal`` body lost its ``type: integer`` verdict
    for writing ``0.0``. The class-level ``evolve`` override now keeps the
    custom class whenever the library's selection is the built-in 2020-12
    one, and this pins the evolved instance: same class, same Decimal
    verdict, and the library's own state copy — schema, resolver, registry,
    format checker — carried over intact.
    """
    from decimal import Decimal

    from tools.contracts.schema_docs import DRAFT202012_VALIDATOR, _rooted_validator

    annotated = copy.deepcopy(backend)
    target = annotated["components"]["schemas"]["DerivativeRecord"]
    target["$schema"] = _2020_12_DIALECT
    validator = _rooted_validator(target, annotated)
    assert validator.TYPE_CHECKER.is_type(Decimal("1.0"), "integer")

    evolved = validator.evolve(schema=target)
    assert isinstance(evolved, DRAFT202012_VALIDATOR), type(evolved).__name__
    assert evolved.TYPE_CHECKER.is_type(Decimal("1.0"), "integer")
    assert evolved.schema == target
    assert evolved.format_checker is validator.format_checker
    assert evolved._registry is validator._registry
    assert evolved._resolver is validator._resolver


def test_a_dialect_declaration_on_the_referenced_component_certifies_the_integral_float_vector(
    device: dict, backend: dict
) -> None:
    """F1 (round 20) on the API path: the published integral-float vector stays valid.

    The committed ``derivative-response-200-crop-integral-float-notation``
    vector is the contract's own proof that ``0.0``/``64.0`` notation is an
    integer window, and the review showed that annotating
    ``components/schemas/DerivativeRecord`` — the schema that vector is
    judged against through ``$ref`` — with the supported dialect made the
    gate report four ``Decimal(…) is not of type 'integer'`` ``API_SCHEMA``
    findings plus ``FIXTURE_EXPECTED_PASS`` on it. Zero findings, annotated
    or not: the dialect declaration may not move the verdict of a valid
    vector.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    index = json.loads(
        (CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8")
    )["fixtures"]
    entry = next(
        item for item in index
        if item["id"] == "backend/valid/derivative-response-200-crop-integral-float-notation"
    )
    body = json.loads(
        (CONTRACTS / "fixtures" / entry["files"][0]).read_bytes().decode("utf-8")
    )
    assert body["crop"] == {"x": 0.0, "y": 0.0, "width": 64.0, "height": 64.0}, (
        "the committed vector must still carry its window in float notation, "
        "or this test pins nothing"
    )
    # Equality cannot tell 0 from 0.0 (round 21 F4): a regeneration that wrote
    # the window with integer literals would satisfy the assertion above while
    # nothing on the path parsed decimal notation any more. Every member must
    # decode as a float under this test's plain loader.
    assert all(type(value) is float for value in body["crop"].values()), (
        "the committed vector must carry its window in decimal notation, "
        f"not integer literals: {body['crop']!r}"
    )
    # And the pin discriminates: the same window written with integer literals
    # decodes to ``int`` members, which the assertion above refuses.
    integer_regen = json.loads(
        json.dumps({**body, "crop": {"x": 0, "y": 0, "width": 64, "height": 64}})
    )
    assert not all(type(value) is float for value in integer_regen["crop"].values()), (
        "the type pin must refuse an integer-literal regeneration of the window"
    )

    # The control: the committed, un-annotated document certifies the vector.
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": backend}, schemas
    )
    assert not found, [violation.render() for violation in found]

    # The annotated document must not judge it any differently.
    annotated = copy.deepcopy(backend)
    annotated["components"]["schemas"]["DerivativeRecord"]["$schema"] = _2020_12_DIALECT
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": annotated}, schemas
    )
    assert not found, [violation.render() for violation in found]


def test_the_corpus_certifies_a_backend_annotated_with_the_supported_dialect(
    backend: dict, tmp_path: Path
) -> None:
    """F1 (round 20) end to end: the whole corpus still certifies the annotated document.

    The review's corpus-level reproduction rewrote only
    ``contracts/backend-v1.yaml`` of a temporary copy — adding the supported
    dialect to ``components/schemas/DerivativeRecord``, nothing else — and
    at 225e3ba the complete validator reported ``441 / 5 / False``. The
    same run now answers ``441 / 0 / True``: a legal dialect declaration
    on a referenced component changes no fixture's verdict and nothing else
    either.
    """
    import yaml

    annotated = copy.deepcopy(backend)
    annotated["components"]["schemas"]["DerivativeRecord"]["$schema"] = _2020_12_DIALECT
    corpus = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, corpus)
    (corpus / "backend-v1.yaml").write_text(
        yaml.safe_dump(annotated, sort_keys=False), encoding="utf-8"
    )
    result = validate_contracts(tmp_path)
    assert result.fixture_total == 441 and not result.violations and result.passed, (
        result.fixture_total,
        [violation.render() for violation in result.violations],
        result.passed,
    )


def test_an_unsupported_dialect_still_evolves_onto_the_draft_validator_it_names(
    backend: dict,
) -> None:
    """F1 (round 20) stays narrow: only the built-in 2020-12 selection is remapped.

    The remap answers the one question — "would the library build the
    built-in 2020-12 validator here?" — with "build ours instead". A
    component spelling any other registered dialect still evolves onto the
    validator that dialect names, exactly as the library has always done,
    so the fix is provably scoped to the supported dialect and cannot leak
    into another draft's semantics.
    """
    from jsonschema import Draft7Validator

    from tools.contracts.schema_docs import DRAFT202012_VALIDATOR, _rooted_validator

    annotated = copy.deepcopy(backend)
    target = annotated["components"]["schemas"]["DerivativeRecord"]
    target["$schema"] = "http://json-schema.org/draft-07/schema#"
    evolved = _rooted_validator(target, annotated).evolve(schema=target)
    assert isinstance(evolved, Draft7Validator), type(evolved).__name__
    assert not isinstance(evolved, DRAFT202012_VALIDATOR)


# --- Round 21: the published operation schema, guarded containers ------------


def _derivative_200_index_entry() -> dict:
    """The committed golden answer of ``GET /derivatives/{id}`` (round 21 F1)."""
    document = json.loads((CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8"))
    return next(
        item for item in document["fixtures"]
        if item["id"] == "backend/valid/derivative-response-200"
    )


def test_a_sibling_assertion_beside_the_bound_ref_is_part_of_the_published_contract(
    device: dict, backend: dict
) -> None:
    """F1 (round 21): the operation schema node is judged, not just its ``$ref``.

    The binding loop reads the ``$ref`` text and the fixture validator judged
    the bare component, so ``required: [reviewed_round21_field]`` written
    *beside* the ``$ref`` on the ``GET /derivatives/{id}`` 200 schema was part
    of no one's contract while being part of the published one (JSON Schema
    §8.2.3.1: siblings of ``$ref`` are assertions). The validator now
    evaluates the node the document carries with the document as root, so the
    committed golden answer is refused the member the document demands — and
    the three controls keep the read honest: the unannotated document still
    certifies it, a satisfied sibling still certifies it, and an unreadable
    node (a dangling response hop) keeps the component judgment the checker
    already owns.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    entry = _derivative_200_index_entry()
    assert (
        validate_api_fixture(CONTRACTS / "fixtures", entry, {"device": device, "backend": backend}, schemas)
        == []
    )

    strict = copy.deepcopy(backend)
    node = strict["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert node == {"$ref": "#/components/schemas/DerivativeRecord"}
    node["required"] = ["reviewed_round21_field"]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": strict}, schemas
    )
    assert {violation.code for violation in found} == {E.API_SCHEMA_MISSING_FIELD}, [
        violation.render() for violation in found
    ]
    assert any("reviewed_round21_field" in violation.detail for violation in found), [
        violation.render() for violation in found
    ]

    # A sibling the body satisfies certifies the vector: the node is read as a
    # schema, not refused as an annotation.
    satisfied = copy.deepcopy(backend)
    satisfied["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["required"] = ["derivative_id"]
    assert (
        validate_api_fixture(
            CONTRACTS / "fixtures", entry, {"device": device, "backend": satisfied}, schemas
        )
        == []
    )

    # An unreadable operation node falls back to the component judgment: the
    # all-response scan names the dangling hop as a document finding, and the
    # vector is no worse off for a defect the checker owns.
    dangling = copy.deepcopy(backend)
    dangling["paths"]["/derivatives/{id}"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/NotThere"
    }
    assert (
        validate_api_fixture(
            CONTRACTS / "fixtures", entry, {"device": device, "backend": dangling}, schemas
        )
        == []
    )


def test_a_sibling_assertion_on_the_request_schema_node_is_part_of_the_published_contract(
    device: dict, backend: dict
) -> None:
    """F1 (round 21) on the request side: ``requestBody`` siblings are contract too.

    The same gap sat under ``item["requestBody"]``: a ``required`` written
    beside the chunk of pointers the request body binds was invisible to both
    readers, so the committed ``device/valid/settings-put-request`` would have
    stayed valid under a document that demands a member its body does not
    carry.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    document = json.loads((CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8"))
    entry = next(
        item for item in document["fixtures"] if item["id"] == "device/valid/settings-put-request"
    )
    assert (
        validate_api_fixture(CONTRACTS / "fixtures", entry, {"device": device, "backend": backend}, schemas)
        == []
    )

    strict = copy.deepcopy(device)
    node = strict["paths"]["/settings"]["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert node == {"$ref": "#/components/schemas/PutSettingsRequest"}
    node["required"] = ["reviewed_round21_field"]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": strict, "backend": backend}, schemas
    )
    assert {violation.code for violation in found} == {E.API_SCHEMA_MISSING_FIELD}, [
        violation.render() for violation in found
    ]
    assert any("reviewed_round21_field" in violation.detail for violation in found), [
        violation.render() for violation in found
    ]


def test_a_null_responses_container_is_named_and_read_as_declaring_nothing(
    device: dict, backend: dict
) -> None:
    """F2 (round 21): a non-Mapping ``responses`` is a finding, never exit 2.

    The first documented-status lookup asked ``str(status) not in responses``
    over a declared ``None`` and died as the CLI's exit-2 "validator internal
    error" before a single contract finding printed. The container is now
    named once at ``responses`` and every reader — both status walks, both
    binding loops and the all-response scan — reads it as declaring nothing:
    the statuses the spec assigns report the answers they are missing.
    """
    broken = copy.deepcopy(backend)
    broken["paths"]["/derivatives/{id}"]["get"]["responses"] = None
    found = check_openapi("backend", broken)
    named = [
        violation
        for violation in found
        if violation.code == E.SPEC_STRUCTURE_MISSING
        and violation.location == "backend-v1 GET /derivatives/{id} responses"
        and violation.detail == "responses is NoneType, not a response object"
    ]
    assert named, [violation.render() for violation in found]
    # The read-as-empty consequence: every documented status reports its answer
    # missing, which is what an operation carrying no responses means.
    assert any(
        violation.code == E.SPEC_STATUS_MISSING
        and violation.location == "backend-v1 GET /derivatives/{id} responses/200"
        for violation in found
    ), [violation.render() for violation in found]
    assert not any(
        violation.detail == "responses is NoneType, not a response object"
        for violation in check_openapi("backend", backend)
    )

    # A list is just as unreadable as a null — and it used to die differently
    # (the all-response scan's ``.items()`` over the list).
    broken = copy.deepcopy(device)
    broken["paths"]["/settings"]["put"]["responses"] = []
    found = check_openapi("device", broken)
    assert any(
        violation.code == E.SPEC_STRUCTURE_MISSING
        and violation.location == "device-v1 PUT /settings responses"
        and violation.detail == "responses is list, not a response object"
        for violation in found
    ), [violation.render() for violation in found]


def test_a_malformed_servers_container_is_named_and_never_exits_two(
    device: dict, backend: dict
) -> None:
    """F2 (round 21): ``servers: [null]`` and a bare-string ``servers`` are findings.

    Both shapes reached ``servers[0].get("url")`` (or ``"a".get``) and raised
    past the CLI as exit 2. Each now names its container once — and the
    expected-server finding still speaks for the contract's own URL, the same
    two truthful statements ``servers: null`` already produced.
    """
    for contract, document, expected_url in (
        ("backend", backend, "https://backend.local/api/v1"),
        ("device", device, "https://vdog.local/api/v1"),
    ):
        broken = copy.deepcopy(document)
        broken["servers"] = [None]
        found = check_openapi(contract, broken)
        assert any(
            violation.code == E.SPEC_STRUCTURE_MISSING
            and violation.location == f"{contract}-v1.yaml servers/0"
            and violation.detail == "servers/0 is NoneType, not a server object"
            for violation in found
        ), [violation.render() for violation in found]
        assert any(
            violation.code == E.SPEC_STRUCTURE_MISSING
            and violation.location == f"{contract}-v1.yaml servers"
            and violation.detail == f"expected {expected_url!r}"
            for violation in found
        ), [violation.render() for violation in found]

        broken = copy.deepcopy(document)
        broken["servers"] = expected_url  # a str: today's AttributeError at servers[0]
        found = check_openapi(contract, broken)
        assert any(
            violation.code == E.SPEC_STRUCTURE_MISSING
            and violation.location == f"{contract}-v1.yaml servers"
            and violation.detail == "servers is str, not a server array"
            for violation in found
        ), [violation.render() for violation in found]
        assert any(
            violation.code == E.SPEC_STRUCTURE_MISSING
            and violation.location == f"{contract}-v1.yaml servers"
            and violation.detail == f"expected {expected_url!r}"
            for violation in found
        ), [violation.render() for violation in found]


# --- Round 22: named refs, exact division -------------------------------------


def test_an_unresolvable_operation_schema_reference_is_named_before_the_fallback(
    device: dict, backend: dict
) -> None:
    """F1 (round 22): an unusable published schema is a finding, never a silent fallback.

    Round 21's whole-node readability probe answered "unreadable" for a
    dangling pointer nested in the inline ``GET /derivatives/{id}`` 200 schema
    (a sibling ``allOf`` pointing at a component the document does not carry),
    returned ``None``, and the vector was judged by the bare component with
    nothing naming the defect — while no checker loop reads nested references
    inside an inline response. The resolution question now belongs to the
    rooted report, so the vector earns ``SPEC_COMPONENT_DRIFT`` *and* keeps
    its component verdict. The companion control is the probe's other
    half-bug: a schema whose ``examples`` merely quote a ``$ref`` key is
    valid data, its siblings must still judge — pre-round-22 the probe
    refused that node too and the missing required member passed unseen.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    document = json.loads((CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8"))
    entry = next(
        item for item in document["fixtures"]
        if item["id"] == "backend/valid/derivative-response-200"
    )

    broken = copy.deepcopy(backend)
    node = broken["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    node["required"] = ["reviewed_round22_field"]
    node["allOf"] = [{"$ref": "#/components/schemas/NotThere"}]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": broken}, schemas
    )
    assert [violation.code for violation in found] == [E.SPEC_COMPONENT_DRIFT], [
        violation.render() for violation in found
    ]
    assert found[0].location == f"{entry['id']}: operation schema"
    assert "cannot be followed" in found[0].detail, found[0].render()
    assert "DerivativeRecord" in found[0].detail, found[0].render()

    # ``examples`` data is never a pointer: the node's assertions judge, the
    # missing required member is charged, and no drift is reported.
    quoted = copy.deepcopy(backend)
    node = quoted["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    node["required"] = ["reviewed_round22_field"]
    node["examples"] = [{"$ref": "just some text"}]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": quoted}, schemas
    )
    assert {violation.code for violation in found} == {E.API_SCHEMA_MISSING_FIELD}, [
        violation.render() for violation in found
    ]
    assert any("reviewed_round22_field" in violation.detail for violation in found), [
        violation.render() for violation in found
    ]


def test_a_decimal_body_survives_a_fractional_multiple_of_on_the_operation_schema(
    device: dict, backend: dict
) -> None:
    """F2 (round 22): ``multipleOf`` divides exactly once bodies carry ``Decimal``.

    API bodies parse with ``parse_float=decimal.Decimal`` by design and the
    pinned library's keyword does ``instance / dB`` for a float divisor, so a
    legal ``multipleOf: 0.5`` the vector satisfies — the committed
    integral-float-notation window is ``Decimal(\"64.0\")`` — reached the CLI
    as ``TypeError`` the moment the constraint rode the operation-node path.
    The exact-number validator now divides ``Decimal`` instances through
    ``Fraction`` (the library's own overflow fallback) and hands every other
    instance to the shipped keyword verbatim: the passing multiple certifies,
    the failing non-multiple earns ``API_SCHEMA`` with the library's message.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    document = json.loads((CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8"))
    entry = next(
        item for item in document["fixtures"]
        if item["id"] == "backend/valid/derivative-response-200-crop-integral-float-notation"
    )

    passing = copy.deepcopy(backend)
    passing["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["properties"] = {
        "crop": {"properties": {"width": {"multipleOf": 0.5}}}
    }
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": passing}, schemas
    )
    assert found == [], [violation.render() for violation in found]

    failing = copy.deepcopy(backend)
    failing["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["properties"] = {
        "crop": {"properties": {"width": {"multipleOf": 2.5}}}
    }
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": failing}, schemas
    )
    assert {violation.code for violation in found} == {E.API_SCHEMA}, [
        violation.render() for violation in found
    ]
    assert any(
        "not a multiple of 2.5" in violation.detail for violation in found
    ), [violation.render() for violation in found]


# --- Round 23: the rooted report must name the cycle it recurses on -----------


def test_a_self_referencing_inline_operation_schema_earns_a_named_drift_not_a_crash(
    device: dict, backend: dict
) -> None:
    """F1 (round 23): a same-instance reference cycle is a finding, never exit 2.

    Round 21's ``resolve_refs`` preflight refused cycles before evaluation (its
    schema mode expands a cycle once and raises); round 22 moved the resolution
    question into the rooted report, and the standard library follows a pointer
    that returns to an in-flight schema until Python raises ``RecursionError`` —
    an exception the round-22 catch tuple did not name, so the whole corpus run
    died at exit 2 with no report. The cycle now joins the ``$ref`` family: the
    inline ``GET /derivatives/{id}`` 200 schema whose ``allOf`` points back at
    itself charges ``SPEC_COMPONENT_DRIFT`` on the vector and the body keeps
    its component verdict. The companion control is the *legal* recursion the
    same library accepts — an instance-consuming ``$ref`` descending a
    property — which must still evaluate and charge normally, proving the fix
    names only the non-consuming cycle.
    """
    from tools.contracts.api_validate import validate_api_fixture

    schemas, violations = load_media_schemas(CONTRACTS / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    document = json.loads((CONTRACTS / "fixtures" / "fixtures.json").read_bytes().decode("utf-8"))
    entry = next(
        item for item in document["fixtures"]
        if item["id"] == "backend/valid/derivative-response-200"
    )
    self_pointer = (
        "#/paths/~1derivatives~1%7Bid%7D/get/responses/200"
        "/content/application~1json/schema"
    )

    cyclic = copy.deepcopy(backend)
    node = cyclic["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    node["allOf"] = [{"$ref": self_pointer}]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": cyclic}, schemas
    )
    assert [(violation.code, violation.location) for violation in found] == [
        (E.SPEC_COMPONENT_DRIFT, f"{entry['id']}: operation schema")
    ], [violation.render() for violation in found]
    assert "reference cycle" in found[0].detail, found[0].render()
    assert "DerivativeRecord" in found[0].detail, found[0].render()

    # A component whose sibling $ref returns to itself: the node report cycles
    # (charge at the operation schema) and so does the fallback target (charge
    # at the component) — both named, nothing escapes.
    cyclic_component = copy.deepcopy(backend)
    cyclic_component["components"]["schemas"]["DerivativeRecord"]["allOf"] = [
        {"$ref": "#/components/schemas/DerivativeRecord"}
    ]
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": cyclic_component}, schemas
    )
    assert {(violation.code, violation.location) for violation in found} == {
        (E.SPEC_COMPONENT_DRIFT, f"{entry['id']}: operation schema"),
        (E.SPEC_COMPONENT_DRIFT, f"{entry['id']}: components/schemas/DerivativeRecord"),
    }, [violation.render() for violation in found]

    # The legal shape still judges: recursion that consumes the instance
    # terminates, and the sibling assertion charges like any other.
    consuming = copy.deepcopy(backend)
    node = consuming["paths"]["/derivatives/{id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    node.clear()
    node.update(
        {
            "type": "object",
            "properties": {"child": {"$ref": self_pointer}},
            "required": ["reviewed_round23_field"],
        }
    )
    found = validate_api_fixture(
        CONTRACTS / "fixtures", entry, {"device": device, "backend": consuming}, schemas
    )
    assert {violation.code for violation in found} == {E.API_SCHEMA_MISSING_FIELD}, [
        violation.render() for violation in found
    ]
