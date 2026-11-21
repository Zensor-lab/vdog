"""API contract invariants over the committed corpus (AC-04, AC-05, AC-06).

``AC_VECTORS`` is the hand-authored coverage table: each entry names the fixture
that must exist and the primary validator code it must produce. It is deliberately
independent of ``fixtures.json`` so a corpus that quietly drops a required vector or
relabels a code fails here rather than agreeing with itself.
"""

from __future__ import annotations

import json
import re

import pytest

from tools.contracts import errors as E
from tools.contracts.api_model import (
    ALL_OPERATIONS,
    ALLOWED_ERROR_CODES,
    ILLUSTRATIVE_CODES,
    SPEC_ERROR_CODES,
)
from tools.contracts.api_validate import validate_api_fixture
from tools.contracts.bounds import MAX_CURSOR_CHARS, MAX_PAGE_LIMIT
from tools.contracts.openapi_check import load_media_schemas

from conftest import FIXTURES, REPO_ROOT

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture(scope="module")
def index() -> list[dict]:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    return [entry for entry in document["fixtures"] if entry["kind"] == "api"]


@pytest.fixture(scope="module")
def by_id(index: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in index}


@pytest.fixture(scope="module")
def specs() -> dict:
    import yaml

    return {
        "device": yaml.safe_load(
            (REPO_ROOT / "contracts" / "device-v1.yaml").read_text(encoding="utf-8")
        ),
        "backend": yaml.safe_load(
            (REPO_ROOT / "contracts" / "backend-v1.yaml").read_text(encoding="utf-8")
        ),
    }


@pytest.fixture(scope="module")
def media_schemas() -> dict:
    loaded, violations = load_media_schemas(REPO_ROOT / "contracts" / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    return loaded


def _body(entry: dict) -> dict:
    """Parse the vector's wire body, ignoring its header sidecar."""
    for name in entry["files"]:
        if not name.endswith(".headers.json"):
            return json.loads((FIXTURES / name).read_bytes().decode("utf-8"))
    raise AssertionError(f"{entry['id']} has no body file")


def _headers(entry: dict) -> dict:
    for name in entry["files"]:
        if name.endswith(".headers.json"):
            return json.loads((FIXTURES / name).read_bytes().decode("utf-8"))
    raise AssertionError(f"{entry['id']} has no header sidecar")


def _observed(entry: dict, specs: dict, media_schemas: dict) -> set[str]:
    return {
        violation.code
        for violation in validate_api_fixture(FIXTURES, entry, specs, media_schemas)
    }


# --- AC-04 / AC-05 coverage table -------------------------------------------

AC_VECTORS: dict[str, tuple[str, ...]] = {
    # AC-04 device: pairing, tokens, capabilities
    "device/valid/pair-request": (),
    "device/valid/pair-response-201": (),
    "device/valid/pair-response-409-already-owned": (),
    "device/valid/pair-response-400-bad-secret": (),
    "device/invalid/pair-request-padded-secret": ("API_SCHEMA",),
    "device/invalid/pair-request-missing-version": ("API_VERSION_MISSING",),
    "device/invalid/pair-response-unsupported-version": ("API_VERSION_UNSUPPORTED",),
    "device/valid/tokens-revoke-request": (),
    "device/valid/tokens-revoke-response-200": (),
    "device/invalid/tokens-revoke-request-missing-token": ("API_SCHEMA_MISSING_FIELD",),
    "device/valid/capabilities-response-200": (),
    "device/invalid/capabilities-response-missing-limits": ("API_SCHEMA_MISSING_FIELD",),
    # AC-04 device: status, settings, time
    "device/valid/status-response-200-recording": (),
    "device/valid/status-response-200-unmounted": (),
    "device/invalid/status-response-200-bad-state": ("API_SCHEMA",),
    "device/valid/settings-response-200": (),
    "device/valid/settings-put-response-409-revision-conflict": (),
    "device/valid/settings-put-response-400-unsupported-profile": (),
    "device/invalid/settings-put-request-unknown-field": ("API_SCHEMA",),
    "device/valid/time-request-valid": (),
    "device/invalid/time-request-missing-milliseconds": ("API_SCHEMA",),
    "device/invalid/time-request-local-offset": ("API_SCHEMA",),
    "device/invalid/time-request-negative-uncertainty": ("API_SCHEMA",),
    # AC-04 device: clips page, leases, files, events, envelope
    "device/valid/clips-page-response-200": (),
    "device/invalid/clips-page-request-cursor-too-long": ("CURSOR_TOO_LONG",),
    "device/invalid/clips-page-request-limit-too-large": ("PAGE_LIMIT_INVALID",),
    "device/valid/clips-page-response-409-cursor-expired": (),
    "device/valid/lease-create-response-201": (),
    "device/valid/lease-create-response-409-lease-limit": (),
    "device/valid/lease-renew-response-200": (),
    "device/valid/lease-renew-response-409-storage-pressure": (),
    "device/valid/lease-renew-response-409-lease-expired": (),
    "device/valid/lease-delete-204": (),
    "device/valid/clip-file-response-206": (),
    "device/valid/clip-file-response-412-content-changed": (),
    "device/valid/clip-file-response-416-multi-range": (),
    "device/valid/clip-file-response-416-hyphenless": (),
    "device/valid/clip-file-response-416-beyond-eof": (),
    "device/valid/clip-file-response-416-reversed": (),
    "device/invalid/clip-file-response-206-hyphenless": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-response-206-reversed": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/valid/clip-file-response-409-lease-expired": (),
    "device/valid/clip-file-response-410-clip-gone": (),
    "device/invalid/clip-file-response-206-bad-etag_invalid": ("ETAG_INVALID",),
    "device/invalid/clip-file-response-206-bad-content_range_invalid": ("CONTENT_RANGE_INVALID",),
    "device/invalid/clip-file-response-206-bad-accept_ranges_invalid": ("ACCEPT_RANGES_INVALID",),
    "device/invalid/clip-file-response-206-bad-content_length_mismatch": (
        "CONTENT_LENGTH_MISMATCH",
    ),
    "device/invalid/clip-file-response-416-without-multi-range": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-response-missing-required-headers": ("HEADER_MISSING",),
    "device/valid/event-create-request": (),
    "device/invalid/event-create-request-too-many-clips": ("API_SCHEMA",),
    "device/valid/event-create-response-409-protection-quota": (),
    "device/valid/event-create-response-409-idempotency-collision": (),
    "device/valid/error-envelope-storage-full": (),
    "device/invalid/error-envelope-missing-fields": ("ERROR_ENVELOPE_INVALID",),
    "device/invalid/error-envelope-lowercase-code": ("ERROR_ENVELOPE_INVALID",),
    "device/valid/preview-response-200": (),
    "device/invalid/preview-response-200-wrong-content-type": ("HEADER_INVALID",),
    "device/valid/clip-manifest-response-200": (),
    "device/invalid/clip-manifest-response-200-bad-frame-count": ("API_SCHEMA",),
    "device/invalid/clip-manifest-response-200-bad-clock-date": ("API_SCHEMA",),
    "device/invalid/clips-page-response-200-bad-start-utc": ("API_SCHEMA",),
    "device/valid/ota-stage-response-202": (),
    # AC-05 backend: identity, uploads, patch, commit, jobs, derivatives, health
    "backend/valid/tokens-create-request": (),
    "backend/valid/tokens-create-response-201": (),
    "backend/invalid/tokens-create-request-bad-scope": ("API_SCHEMA",),
    "backend/valid/device-register-request": (),
    "backend/valid/device-register-response-201": (),
    "backend/invalid/device-register-request-bad-device-id": ("API_SCHEMA",),
    "backend/valid/upload-create-request": (),
    "backend/valid/upload-create-response-413-encoded-too-large": (),
    "backend/valid/upload-create-response-422-decoded-too-large": (),
    "backend/valid/upload-create-response-409-idempotency-mismatch": (),
    "backend/invalid/upload-create-request-encoded-too-large": ("API_BODY_TOO_LARGE",),
    "backend/invalid/upload-create-request-decoded-too-large": ("MANIFEST_DECODED_TOO_LARGE",),
    "backend/invalid/upload-create-request-bad-alphabet": ("BASE64URL_ALPHABET_INVALID",),
    "backend/invalid/upload-create-request-not-json": ("MANIFEST_JSON_INVALID_DECODED",),
    "backend/invalid/upload-create-request-invalid-manifest": ("MANIFEST_DECODED_SCHEMA",),
    "backend/invalid/upload-create-request-missing-idempotency-key": ("HEADER_MISSING",),
    "backend/valid/upload-patch-request-valid": (),
    "backend/valid/upload-patch-response-204": (),
    "backend/valid/upload-patch-response-409-wrong-offset": (),
    "backend/valid/upload-patch-response-422-bad-hash": (),
    "backend/valid/upload-patch-response-413-oversized": (),
    "backend/invalid/upload-patch-request-empty-body": ("CHUNK_SIZE_INVALID",),
    "backend/invalid/upload-patch-request-oversized-body": ("CHUNK_SIZE_INVALID",),
    "backend/invalid/upload-patch-request-disallowed-name": ("FILE_NAME_NOT_ALLOWED",),
    "backend/invalid/upload-patch-request-bad-checksum": ("UPLOAD_CHECKSUM_SYNTAX",),
    "backend/invalid/upload-patch-request-negative-offset": ("UPLOAD_OFFSET_INVALID",),
    "backend/valid/upload-commit-response-201-stored": (),
    "backend/valid/upload-commit-response-201-repeat": (),
    "backend/valid/upload-commit-response-422-integrity": (),
    "backend/valid/upload-commit-response-409-clip-id-collision": (),
    "backend/valid/upload-head-response-200": (),
    "backend/invalid/upload-head-response-missing-offset": ("HEADER_MISSING",),
    "backend/invalid/upload-head-response-bad-length": ("UPLOAD_LENGTH_INVALID",),
    "backend/valid/upload-get-response-410-expired": (),
    "backend/valid/job-create-request": (),
    "backend/invalid/job-create-request-bad-type": ("API_SCHEMA",),
    "backend/valid/job-response-200-running": (),
    "backend/invalid/job-response-200-bad-state": ("API_SCHEMA",),
    "backend/invalid/job-response-200-progress-out-of-range": ("API_SCHEMA",),
    "backend/valid/derivative-response-200": (),
    "backend/invalid/derivative-response-200-bad-hash": ("API_SCHEMA",),
    "backend/valid/derivative-file-response-206": (),
    "backend/valid/health-live-response-200": (),
    "backend/valid/health-ready-response-503": (),
    "backend/valid/clip-delete-response-409-clip-protected": (),
    "backend/valid/clip-file-response-410-clip-gone": (),
}


@pytest.mark.parametrize("fixture_id", sorted(AC_VECTORS))
def test_ac_vector_exists_and_behaves_as_declared(
    fixture_id: str, index: list[dict], by_id: dict, specs: dict, media_schemas: dict
) -> None:
    """Every AC-named vector ships, and its observed codes match its declaration."""
    entry = by_id.get(fixture_id)
    assert entry is not None, f"{fixture_id} is required by AC-04/AC-05 but is not in the corpus"
    observed = _observed(entry, specs, media_schemas)
    if entry["expected"] == "valid":
        assert observed == set(), (fixture_id, sorted(observed))
    else:
        primary = set(AC_VECTORS[fixture_id])
        assert primary, f"{fixture_id} is declared invalid but the table names no primary code"
        assert primary <= observed, (fixture_id, sorted(observed))
        assert observed == set(entry["expected_error_codes"]), (
            fixture_id,
            sorted(observed),
            entry["expected_error_codes"],
        )


def test_every_documented_operation_has_a_vector(index: list[dict]) -> None:
    covered = {entry["operation"] for entry in index}
    assert covered == set(ALL_OPERATIONS), sorted(set(ALL_OPERATIONS) ^ covered)


def test_every_required_response_header_can_be_represented() -> None:
    """A refusal with required headers has to be generatable, not just documented.

    The completion pass emits a header sidecar only when it can name an exact value, so
    every header the operation table demands on a response must have one.
    """
    from tools.contracts.fixture_spec import _COMPLETION_HEADER_VALUE, _completion_headers

    demanded = {
        name
        for operation in ALL_OPERATIONS.values()
        for names in operation.required_response_headers.values()
        for name in names
    }
    assert demanded <= set(_COMPLETION_HEADER_VALUE), sorted(demanded - set(_COMPLETION_HEADER_VALUE))
    # the helper is reachable for the statuses that need it and silent otherwise
    patched = ALL_OPERATIONS["backend.patch_upload_file"]
    assert _completion_headers(patched, 409) == {"Upload-Offset": "1024"}
    assert _completion_headers(ALL_OPERATIONS["device.pair"], 429) is None


def _completion_header_table() -> dict[str, str]:
    from tools.contracts.fixture_spec import _COMPLETION_HEADER_VALUE

    return dict(_COMPLETION_HEADER_VALUE)


def test_the_three_header_vector_names_all_three_headers(by_id: dict, specs: dict) -> None:
    """A vector that declares three absent headers has to be missing three, by name.

    ``expected_error_codes`` is a set to the comparison in :mod:`tools.contracts.validate`,
    so the promise that this vector exercises three distinct required headers lives in
    the finding *locations*, which is what this pins.
    """
    from tools.contracts.api_validate import validate_api_fixture

    entry = by_id["device/invalid/clip-file-response-missing-required-headers"]
    assert entry["expected_error_codes"].count(E.HEADER_MISSING) == 3
    violations = validate_api_fixture(FIXTURES, entry, specs, {})
    named = {
        violation.location.rsplit(": ", 1)[-1]
        for violation in violations
        if violation.code == E.HEADER_MISSING
    }
    assert named == {"Accept-Ranges", "Content-Range", "ETag"}, sorted(named)


@pytest.mark.parametrize(("name", "value"), sorted(_completion_header_table().items()))
def test_a_completion_header_value_is_conformant(name: str, value: str) -> None:
    """The generator's canned refusal headers have to satisfy the rules they claim to.

    ``_completion_headers`` is only reachable when a document demands a header, so its
    values would otherwise never be checked; running them through the same
    :data:`HEADER_RULES` a committed vector goes through makes them a pinned fact.
    """
    from tools.contracts.api_validate import HEADER_RULES, _HeaderContext

    operation = ALL_OPERATIONS["backend.patch_upload_file"]
    rule = HEADER_RULES.get(name.lower())
    assert rule is not None, f"{name} has no documented rule"
    context = _HeaderContext(
        location=f"completion:{operation.key}",
        operation=operation,
        direction="response",
        status=409,
        headers={name: value},
    )
    violations = rule(context, name, value)
    assert not violations, [violation.render() for violation in violations]


def test_the_completion_range_and_length_pair_agree() -> None:
    """``Content-Range`` is cross-checked against ``Content-Length``, so the pair is pinned.

    Checked one header at a time, the range rule always sees no declared length; the
    two canned values only mean something together.
    """
    from tools.contracts.api_validate import HEADER_RULES, _HeaderContext

    operation = ALL_OPERATIONS["backend.get_clip_file"]
    table = _completion_header_table()
    headers = {"Content-Range": table["Content-Range"], "Content-Length": table["Content-Length"]}
    context = _HeaderContext(
        location="completion:pair",
        operation=operation,
        direction="response",
        status=206,
        headers=headers,
    )
    violations: list = []
    for name, value in headers.items():
        violations.extend(HEADER_RULES[name.lower()](context, name, value))
    assert not violations, [violation.render() for violation in violations]


def test_every_success_status_has_a_vector(index: list[dict]) -> None:
    """Every documented 2xx of every operation is exercised by a response vector."""
    for key, operation in ALL_OPERATIONS.items():
        statuses = {
            entry["status"]
            for entry in index
            if entry["operation"] == key and entry["expected"] == "valid"
        }
        missing = set(operation.success_statuses) - statuses
        assert not missing, (key, sorted(missing))


def test_every_documented_error_status_has_a_vector(index: list[dict]) -> None:
    """A documented refusal with no committed example is an untested promise."""
    for key, operation in ALL_OPERATIONS.items():
        statuses = {
            entry["status"]
            for entry in index
            if entry["operation"] == key
            and entry["direction"] == "response"
            and entry["status"] in operation.error_codes
        }
        missing = set(operation.error_codes) - statuses
        assert not missing, (key, sorted(missing))


def test_every_documented_status_is_exercised_in_both_notations(index: list[dict]) -> None:
    """The YAML response list and the vector set describe the same contract."""
    for key, operation in ALL_OPERATIONS.items():
        statuses = {
            entry["status"]
            for entry in index
            if entry["operation"] == key and entry["direction"] == "response"
        }
        assert set(operation.documented_statuses) <= statuses, (
            key,
            sorted(set(operation.documented_statuses) - statuses),
        )


def test_every_required_error_header_has_a_committed_value() -> None:
    """No documented refusal can ship without a header the contract itself demands."""
    from tools.contracts.fixture_spec import _COMPLETION_HEADER_VALUE

    missing = {
        f"{key} {status}: {name}"
        for key, operation in ALL_OPERATIONS.items()
        for status in operation.error_codes
        for name in operation.required_response_headers.get(status, ())
        if name not in _COMPLETION_HEADER_VALUE
    }
    assert not missing, sorted(missing)


def test_coverage_refusals_use_the_shared_envelope(index: list[dict]) -> None:
    """Each coverage vector refuses with a code that status is allowed to carry."""
    seen = 0
    for entry in index:
        if entry["category"] != "error" or entry["expected"] != "valid":
            continue
        seen += 1
        operation = ALL_OPERATIONS[entry["operation"]]
        assert entry["api_error_code"] in operation.allowed_codes_for(entry["status"]), entry["id"]
        error = _body(entry)["error"]
        assert {"code", "message", "retryable", "request_id"} <= set(error), entry["id"]
        assert error["code"] == entry["api_error_code"], entry["id"]
    assert seen > 100, seen


def test_every_spec_named_error_code_is_demonstrated(index: list[dict]) -> None:
    demonstrated = {
        entry["api_error_code"] for entry in index if entry["api_error_code"] is not None
    }
    assert SPEC_ERROR_CODES <= demonstrated, sorted(SPEC_ERROR_CODES - demonstrated)


def test_error_codes_are_all_documented_names(index: list[dict]) -> None:
    used = {
        entry["api_error_code"]
        for entry in index
        # The vectors that demonstrate an undocumented code name one on purpose.
        if entry["api_error_code"] is not None
        and E.ERROR_CODE_UNDOCUMENTED not in entry["expected_error_codes"]
    }
    assert used <= ALLOWED_ERROR_CODES, sorted(used - ALLOWED_ERROR_CODES)
    # The spec's own names and the isolated illustrative names stay distinguishable.
    assert used & SPEC_ERROR_CODES
    assert used & ILLUSTRATIVE_CODES


def test_error_vectors_use_the_shared_envelope_shape(by_id: dict) -> None:
    for entry in by_id.values():
        if entry["api_error_code"] is None:
            continue
        body = _body(entry)
        assert body["v"] == 1
        error = body["error"]
        assert set(error) == {"code", "message", "retryable", "request_id"}
        assert re.match(r"^[A-Z][A-Z0-9_]{0,63}$", error["code"])
        assert isinstance(error["retryable"], bool)
        assert error["message"].strip() == error["message"]


def test_request_bodies_carry_no_unknown_write_fields(by_id: dict, specs: dict) -> None:
    """Write objects are strict, so a stray field must never appear in a valid vector.

    The check is the contract's own: every valid request body is re-validated against
    the ``components/schemas`` entry the operation binds, and must produce no finding.
    """
    from tools.contracts.api_validate import _validate_against_component

    seen = 0
    for entry in by_id.values():
        if entry["direction"] != "request" or entry["expected"] != "valid":
            continue
        if entry["schema"] is None:
            continue
        seen += 1
        document = specs[entry["contract"].removesuffix("-v1")]
        violations = _validate_against_component(document, entry["schema"], _body(entry), entry)
        assert not violations, (entry["id"], [v.render() for v in violations])
    assert seen >= 12, seen  # every documented write body is checked


def test_pagination_bounds_are_respected_by_valid_vectors(by_id: dict) -> None:
    for entry in by_id.values():
        if entry["category"] != "pagination" or entry["expected"] != "valid":
            continue
        if any(name.endswith(".headers.json") for name in entry["files"]):
            headers = _headers(entry)
            if "cursor" in headers:
                assert len(headers["cursor"]) <= MAX_CURSOR_CHARS, entry["id"]
            if "limit" in headers:
                assert 1 <= int(headers["limit"]) <= MAX_PAGE_LIMIT, entry["id"]


def test_idempotency_keys_are_canonical_uuids(by_id: dict) -> None:
    seen = 0
    for entry in by_id.values():
        if any(name.endswith(".headers.json") for name in entry["files"]):
            headers = _headers(entry)
            if "Idempotency-Key" in headers:
                seen += 1
                assert UUID.match(headers["Idempotency-Key"]), (entry["id"], headers)
    assert seen >= 3


def test_upload_binding_quotes_the_committed_manifest(by_id: dict) -> None:
    """AC-05: the valid upload-init vector binds the real committed manifest.json."""
    import base64

    entry = by_id["backend/valid/upload-create-request"]
    body = _body(entry)
    encoded = body["manifest_base64url"]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", encoded)
    decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_")
    committed = (FIXTURES / "media/valid/baseline/manifest.json").read_bytes()
    assert json.loads(decoded) == json.loads(committed)


def test_manifest_quoting_vectors_cover_each_failure_mode(by_id: dict) -> None:
    """The five distinct base64url/manifest defects are five separate vectors."""
    ids = {
        "backend/invalid/upload-create-request-bad-alphabet",
        "backend/invalid/upload-create-request-encoded-too-large",
        "backend/invalid/upload-create-request-decoded-too-large",
        "backend/invalid/upload-create-request-not-json",
        "backend/invalid/upload-create-request-invalid-manifest",
    }
    assert ids <= set(by_id)
    codes = {by_id[fixture_id]["expected_error_codes"][0] for fixture_id in ids}
    assert len(codes) == len(ids), "each quoting defect needs its own code"


def test_header_only_vectors_keep_their_sidecar(by_id: dict) -> None:
    for entry in by_id.values():
        if entry["files"] and all(name.endswith(".headers.json") for name in entry["files"]):
            assert len(entry["files"]) == 1, entry["id"]


def test_api_bodies_carry_the_version_field(by_id: dict) -> None:
    """Every body is exactly what a client would put on the wire, version included."""
    for entry in by_id.values():
        if not any(name.endswith(".json") and not name.endswith(".headers.json")
                   for name in entry["files"]):
            continue
        if {E.API_VERSION_MISSING, E.API_VERSION_UNSUPPORTED} & set(
            entry["expected_error_codes"]
        ):
            continue  # these vectors exist to omit or falsify the field
        document = _body(entry)
        assert document["v"] == 1, entry["id"]


def test_every_device_state_is_exercised(specs: dict, by_id: dict) -> None:
    """interfaces.md lists eight device states; a state nobody sends is untested."""
    documented = set(specs["device"]["components"]["schemas"]["DeviceState"]["enum"])
    seen: set[str] = set()
    for entry in by_id.values():
        if entry.get("operation") != "device.get_status" or entry["expected"] != "valid":
            continue
        for name in entry["files"]:
            if name.endswith(".headers.json"):
                continue
            document = json.loads((FIXTURES / name).read_bytes().decode("utf-8"))
            if isinstance(document, dict) and isinstance(document.get("state"), str):
                seen.add(document["state"])
    assert seen == documented, (sorted(documented - seen), sorted(seen - documented))


def test_invalid_api_vectors_never_pass_silently(index: list[dict], specs: dict, media_schemas: dict) -> None:
    for entry in index:
        if entry["expected"] != "invalid":
            continue
        assert _observed(entry, specs, media_schemas), f"{entry['id']} passed but must not"


# --- Round 2: the Range decision table (interfaces.md §4, RFC 9110) ----------

GRANTED_206 = {"Content-Range": "bytes 0-99/1000", "Content-Length": "100"}


def _header_codes(name: str, value: str, status: int, extra: dict[str, str] | None = None) -> set[str]:
    """One header rule's verdict on one value, away from any committed vector."""
    from tools.contracts.api_validate import HEADER_RULES, _HeaderContext

    headers = {name: value}
    headers.update(extra or {})
    context = _HeaderContext(
        location="unit:range",
        operation=ALL_OPERATIONS["device.get_clip_file"],
        direction="response",
        status=status,
        headers=headers,
    )
    return {violation.code for violation in HEADER_RULES[name.lower()](context, name, value)}


@pytest.mark.parametrize(
    ("value", "status", "extra", "codes"),
    [
        # Unsupported syntax: the contract rejects it, so 416 is required, not optional.
        ("bytes=0-99,200-299", 416, {}, set()),
        ("bytes=-500", 416, {}, set()),
        ("bytes=10", 416, {}, set()),
        ("bytes=0-99,200-299", 206, GRANTED_206, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=-500", 200, {"Content-Length": "1000"}, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=10", 206, GRANTED_206, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("nonsense", 200, {"Content-Length": "1000"}, {E.RANGE_MULTI_NOT_ALLOWED}),
        # Supported syntax, unsatisfiable endpoint ordering: 416 answers it.
        ("bytes=200-100", 416, {}, set()),
        ("bytes=200-100", 206, GRANTED_206, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=200-100", 200, {"Content-Length": "1000"}, {E.RANGE_MULTI_NOT_ALLOWED}),
        # Supported syntax, correctly ordered: a 416 needs proof from Content-Range.
        ("bytes=999999999-", 416, {"Content-Range": "bytes */1000"}, set()),
        ("bytes=1000-1999", 416, {"Content-Range": "bytes */1000"}, set()),
        ("bytes=999-", 416, {"Content-Range": "bytes */1000"}, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=0-99", 416, {}, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=0-99", 416, {"Content-Range": "bytes 0-99/1000"}, {E.RANGE_MULTI_NOT_ALLOWED}),
        ("bytes=0-99", 206, GRANTED_206, set()),
        ("bytes=999-", 206, GRANTED_206, set()),
    ],
    ids=[
        "multipart-416",
        "suffix-416",
        "hyphenless-416",
        "multipart-206",
        "suffix-200",
        "hyphenless-206",
        "junk-200",
        "reversed-416",
        "reversed-206",
        "reversed-200",
        "beyond-eof-416",
        "start-at-total-416",
        "star-proves-satisfiable-416",
        "granted-range-416-no-proof",
        "granted-range-416-granted-form",
        "granted-range-206",
        "open-ended-206",
    ],
)
def test_the_range_rule_follows_the_decision_table(
    value: str, status: int, extra: dict[str, str], codes: set[str]
) -> None:
    """What the contract *rejects* and what is merely *unsatisfiable* differ (AC-06)."""
    assert _header_codes("Range", value, status, extra) == codes, (value, status, extra)


@pytest.mark.parametrize(
    ("value", "status", "extra", "codes"),
    [
        ("bytes */1000", 416, {}, set()),
        ("bytes */1000", 206, GRANTED_206, {E.CONTENT_RANGE_INVALID}),
        ("bytes */1000", 200, {"Content-Length": "1000"}, {E.CONTENT_RANGE_INVALID}),
        ("bytes */0", 416, {}, {E.CONTENT_RANGE_INVALID}),
        ("bytes 0-99/1000", 416, {}, {E.CONTENT_RANGE_INVALID}),
        ("bytes 0-99/1000", 206, GRANTED_206, set()),
        ("bytes 0-99/1000", 206, {"Content-Length": "99"}, {E.CONTENT_LENGTH_MISMATCH}),
        ("bytes 99-0/1000", 206, {"Content-Length": "100"}, {E.CONTENT_RANGE_INVALID}),
        ("bytes 0-99/50", 206, {"Content-Length": "100"}, {E.CONTENT_RANGE_INVALID}),
        ("bytes */", 416, {}, {E.CONTENT_RANGE_INVALID}),
    ],
    ids=[
        "star-416",
        "star-206",
        "star-200",
        "star-zero-total-416",
        "granted-on-416",
        "granted-206",
        "granted-length-disagrees",
        "descending-206",
        "past-total-206",
        "star-without-total",
    ],
)
def test_the_content_range_rule_grants_only_on_a_success(
    value: str, status: int, extra: dict[str, str], codes: set[str]
) -> None:
    """``bytes */<total>`` promises nothing, so only a 416 may carry it (and total ≥ 1)."""
    assert _header_codes("Content-Range", value, status, extra) == codes, (value, status, extra)
