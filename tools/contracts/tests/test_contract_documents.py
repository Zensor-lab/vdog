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
from tools.contracts.schema_docs import load_json, load_yaml
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
