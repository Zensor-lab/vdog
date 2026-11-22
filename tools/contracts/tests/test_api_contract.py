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
from tools.contracts.schema_docs import resolve_refs

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
    "device/valid/clip-file-response-412-multi-range": (),
    "device/invalid/clip-file-response-206-multi-range": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-response-206-hyphenless": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-response-206-reversed": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-request-hyphenless": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-request-multi-range": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/invalid/clip-file-request-reversed": ("RANGE_MULTI_NOT_ALLOWED",),
    "device/valid/clip-file-request-with-lease": (),
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
    # Round 4: the nine findings' own vectors.
    "device/invalid/pair-request-missing-body": ("API_SCHEMA",),
    "device/invalid/pair-response-201-missing-body": ("API_SCHEMA",),
    "device/invalid/pair-response-201-no-store": ("HEADER_INVALID",),
    "device/valid/pair-response-403-forbidden": (),
    "device/invalid/preview-response-200-json-content-type": ("HEADER_INVALID",),
    "device/valid/preview-response-200-no-store": (),
    "backend/invalid/job-response-200-progress-nan": ("API_SCHEMA",),
    "backend/invalid/upload-head-response-410-with-body": ("FIXTURE_INDEX_INVALID",),
    "backend/valid/clips-page-response-200-full-page": (),
    "backend/valid/patch_upload_file-response-410-expired": (),
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
    """Each coverage vector refuses the way its own method and status have to.

    A refusal with content arrives in the shared envelope, with a code that status is
    allowed to carry. A HEAD has no content to carry it in (RFC 9110 §9.3.2), so its
    vector ships neither a body nor an index-level code: asserting an envelope there
    would pin the very defect this round removed from the document and the corpus.
    """
    seen = 0
    status_only = 0
    for entry in index:
        if entry["category"] != "error" or entry["expected"] != "valid":
            continue
        seen += 1
        operation = ALL_OPERATIONS[entry["operation"]]
        if operation.is_head:
            status_only += 1
            assert not entry["files"], f"{entry['id']} gives a HEAD a body"
            assert entry["api_error_code"] is None, entry["id"]
            assert entry["status"] in operation.error_codes, entry["id"]
            continue
        assert entry["api_error_code"] in operation.allowed_codes_for(entry["status"]), entry["id"]
        error = _body(entry)["error"]
        assert {"code", "message", "retryable", "request_id"} <= set(error), entry["id"]
        assert error["code"] == entry["api_error_code"], entry["id"]
    assert seen > 100, seen
    head_refusals = sum(
        len(operation.error_codes)
        for operation in ALL_OPERATIONS.values()
        if operation.is_head
    )
    assert status_only == head_refusals, (status_only, head_refusals)


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


def _header_codes(
    name: str,
    value: str,
    status: int | None,
    extra: dict[str, str] | None = None,
    direction: str = "response",
) -> set[str]:
    """One header rule's verdict on one value, away from any committed vector."""
    from tools.contracts.api_validate import HEADER_RULES, _HeaderContext

    headers = {name: value}
    headers.update(extra or {})
    context = _HeaderContext(
        location="unit:range",
        operation=ALL_OPERATIONS["device.get_clip_file"],
        direction=direction,
        status=status,
        headers=headers,
    )
    return {violation.code for violation in HEADER_RULES[name.lower()](context, name, value)}


#: The statuses the contract defines for `device.get_clip_file` that neither grant nor
#: refuse bytes: the 400 request-level malformation plus the §4 gates (authentication,
#: existence, lease, eviction, the `If-Match` precondition), all of which RFC 9110
#: §13.2.2 and §14.4 evaluate before a range is parsed or served. A response at one of
#: them says nothing about the specifier, so every range form must be silent at every
#: one of them. 200, 206 and 416 are the only statuses excluded here, because those are
#: exactly the ones that speak about the range.
GATE_STATUSES: tuple[int, ...] = (400, 401, 404, 409, 410, 412)

#: Range spellings the contract does not support at all: multipart, suffix, a
#: missing hyphen, and something that is not a byte-range specifier to begin with.
UNSUPPORTED_FORMS: tuple[str, ...] = ("bytes=0-99,200-299", "bytes=-500", "bytes=10", "nonsense")

_GRANTING = (200, 206)


def _range_table() -> list[tuple[str, int | None, dict[str, str], set[str], str, str]]:
    """``(value, status, extra, codes, id, direction)`` for the whole decision table.

    Built rather than listed so each rejected-form branch is exercised against every
    status the contract defines and every spelling is exercised as a request too: a
    branch that is quiet about a §4 gate by accident, and one that is quiet by design,
    have to look different here, and a request row that silently skipped a spelling
    would leave that form unjudged on the side of the wire that has no status at all.
    """
    cases: list[tuple[str, int | None, dict[str, str], set[str], str, str]] = []
    for form in UNSUPPORTED_FORMS:
        tag = {
            "bytes=0-99,200-299": "multipart",
            "bytes=-500": "suffix",
            "bytes=10": "hyphenless",
            "nonsense": "junk",
        }[form]
        # 416 is the required refusal; 200/206 grant bytes the contract never supports.
        cases.append((form, 416, {}, set(), f"{tag}-416", "response"))
        for status in _GRANTING:
            extra = GRANTED_206 if status == 206 else {"Content-Length": "1000"}
            cases.append(
                (
                    form,
                    status,
                    extra,
                    {E.RANGE_MULTI_NOT_ALLOWED},
                    f"{tag}-{status}-grants",
                    "response",
                )
            )
        for status in GATE_STATUSES:
            cases.append((form, status, {}, set(), f"{tag}-{status}-gate", "response"))
        # A request has no status to be quiet about, so every unsupported spelling is
        # the violation, with no gate and no granting status to vary against.
        cases.append(
            (form, None, {}, {E.RANGE_MULTI_NOT_ALLOWED}, f"{tag}-request", "request")
        )
    # Supported syntax whose endpoints contradict each other.
    cases.append(("bytes=200-100", 416, {}, set(), "reversed-416", "response"))
    for status in _GRANTING:
        extra = GRANTED_206 if status == 206 else {"Content-Length": "1000"}
        cases.append(
            (
                "bytes=200-100",
                status,
                extra,
                {E.RANGE_MULTI_NOT_ALLOWED},
                f"reversed-{status}-grants",
                "response",
            )
        )
    for status in GATE_STATUSES:
        cases.append(("bytes=200-100", status, {}, set(), f"reversed-{status}-gate", "response"))
    cases.append(
        (
            "bytes=200-100",
            None,
            {},
            {E.RANGE_MULTI_NOT_ALLOWED},
            "reversed-request",
            "request",
        )
    )
    # Supported, correctly ordered: a claimed 416 has to prove itself.
    cases += [
        (
            "bytes=999999999-",
            416,
            {"Content-Range": "bytes */1000"},
            set(),
            "beyond-eof-416",
            "response",
        ),
        (
            "bytes=1000-1999",
            416,
            {"Content-Range": "bytes */1000"},
            set(),
            "start-at-total-416",
            "response",
        ),
        (
            "bytes=999-",
            416,
            {"Content-Range": "bytes */1000"},
            {E.RANGE_MULTI_NOT_ALLOWED},
            "star-proves-satisfiable-416",
            "response",
        ),
        (
            "bytes=0-99",
            416,
            {},
            {E.RANGE_MULTI_NOT_ALLOWED},
            "granted-range-416-no-proof",
            "response",
        ),
        (
            "bytes=0-99",
            416,
            {"Content-Range": "bytes 0-99/1000"},
            {E.RANGE_MULTI_NOT_ALLOWED},
            "granted-range-416-granted-form",
            "response",
        ),
        ("bytes=0-99", 206, GRANTED_206, set(), "granted-range-206", "response"),
        ("bytes=999-", 206, GRANTED_206, set(), "open-ended-206", "response"),
        # A supported, ordered specifier is silent at 200 as well as at 206: the rule
        # under test judges whether a response *misuses* the range form, and an
        # ordered one is not a misuse at either granting status. Pinned at 200 too so
        # that status cannot be special-cased into the flagged set unnoticed; whether a
        # 200 full body is the right answer to a supported range is a separate §4
        # question this rule does not own (and no committed vector asserts one).
        (
            "bytes=0-99",
            200,
            {"Content-Length": "1000"},
            set(),
            "granted-range-200-full-body",
            "response",
        ),
        (
            "bytes=999-",
            200,
            {"Content-Length": "1000"},
            set(),
            "open-ended-200-full-body",
            "response",
        ),
        # A correctly ordered request is silent too, and that silence is a different
        # claim from the response rows above: satisfiability needs the file's length,
        # which a request does not have, so the only way to fail here is to flag a
        # form §4 does support. `bytes=0-1023` is the committed valid vector's spelling.
        ("bytes=0-99", None, {}, set(), "ordered-request", "request"),
        ("bytes=999-", None, {}, set(), "open-ended-request", "request"),
        ("bytes=0-1023", None, {}, set(), "baseline-request", "request"),
        # `bytes=20-100` orders correctly numerically and wrongly as text, since "100"
        # sorts before "20". Every other reversed cell (`bytes=200-100`) flags under
        # either reading, so without these three nothing in the suite would notice the
        # comparison being changed from `int(end) < start` to `end < start`: the two
        # granting statuses and the request all go silent on a correctly ordered range.
        (
            "bytes=20-100",
            206,
            GRANTED_206,
            set(),
            "wider-end-206-ordered",
            "response",
        ),
        (
            "bytes=20-100",
            200,
            {"Content-Length": "1000"},
            set(),
            "wider-end-200-ordered",
            "response",
        ),
        ("bytes=20-100", None, {}, set(), "wider-end-request", "request"),
    ]
    return cases


_RANGE_CASES = _range_table()


@pytest.mark.parametrize(
    ("value", "status", "extra", "codes", "direction"),
    [
        (value, status, extra, codes, direction)
        for value, status, extra, codes, _id, direction in _RANGE_CASES
    ],
    ids=[case_id for *_rest, case_id, _direction in _RANGE_CASES],
)
def test_the_range_rule_follows_the_decision_table(
    value: str, status: int | None, extra: dict[str, str], codes: set[str], direction: str
) -> None:
    """What the contract *supports* and what is merely *satisfiable* differ (AC-06).

    A response speaks about the range only when it is 200, 206 or 416; a §4 gate that
    never reached range handling may echo whatever `Range` it was given. A request is
    judged on its specifier alone, since nothing was evaluated ahead of it.
    """
    assert (
        _header_codes("Range", value, status, extra, direction) == codes
    ), (direction, value, status, extra)


@pytest.mark.parametrize(
    ("value", "status", "extra", "codes"),
    [
        ("bytes */1000", 416, {}, set()),
        ("bytes */1000", 206, GRANTED_206, {E.CONTENT_RANGE_INVALID}),
        ("bytes */1000", 200, {"Content-Length": "1000"}, {E.CONTENT_RANGE_INVALID}),
        # A §4 gate may echo the header, exactly as a 416 does.
        *[
            ("bytes */1000", status, {}, set())
            for status in GATE_STATUSES
        ],
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
        *[f"star-{status}-gate" for status in GATE_STATUSES],
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


# --- Round 4: body presence, the request-only ceiling, strict wire JSON, and the
#     media types and headers one operation actually documents -------------------


def _vector(
    tmp_path,
    *,
    operation: str,
    direction: str,
    status: int | None = None,
    schema: str | None = None,
    body: dict | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
):
    """An ad-hoc API vector in ``tmp_path``, indexed exactly as ``fixtures.json`` does.

    A defect about whether a body exists at all cannot ride along as a second copy of a
    committed vector, so these vectors are built where they are judged. The entry carries
    the same fields the generator writes, so nothing here is validated more leniently
    than a committed vector is.
    """
    from tools.contracts.media_model import dump_json

    key = ALL_OPERATIONS[operation]
    vector_id = f"{key.contract}/valid/adhoc-{operation}-{direction}-{status}"
    (tmp_path / vector_id).parent.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if raw_body is not None:
        (tmp_path / f"{vector_id}.json").write_bytes(raw_body)
        files.append(f"{vector_id}.json")
    elif body is not None:
        (tmp_path / f"{vector_id}.json").write_bytes(dump_json(body))
        files.append(f"{vector_id}.json")
    if headers is not None:
        (tmp_path / f"{vector_id}.headers.json").write_bytes(
            dump_json({name: headers[name] for name in sorted(headers)})
        )
        files.append(f"{vector_id}.headers.json")
    entry = {
        "id": vector_id,
        "kind": "api",
        "contract": f"{key.contract}-v1",
        "category": "round-4",
        "expected": "valid",
        "expected_error_codes": [],
        "files": sorted(files),
        "invariant": "AC-06 wire rule exercised in a temporary directory",
        "operation": operation,
        "operation_id": key.operation_id,
        "method": key.method,
        "path": key.path,
        "direction": direction,
        "status": status,
        "schema": schema,
        "api_error_code": None,
    }
    return tmp_path, entry


def _codes(tmp_path, entry: dict, specs: dict, media_schemas: dict) -> set[str]:
    return {
        violation.code
        for violation in validate_api_fixture(tmp_path, entry, specs, media_schemas)
    }


@pytest.mark.parametrize(
    ("operation", "direction", "status", "schema"),
    [
        ("device.pair", "request", None, "PairRequest"),
        ("device.pair", "response", 201, "PairResponse"),
        ("device.pair", "response", 400, None),
        ("backend.get_job", "response", 200, "JobRecord"),
    ],
    ids=["pair-request", "pair-201", "pair-400-envelope", "job-200-record"],
)
def test_a_vector_missing_a_body_the_contract_requires_is_refused(
    tmp_path, specs, media_schemas, operation, direction, status, schema
) -> None:
    """Presence is checked before contents: an absent body is a finding, not a pass.

    Each case names a body interfaces.md §1 binds — a request schema, a documented
    record, the shared error envelope — and ships headers only, which is the shape that
    used to walk away clean because every rule that could object was waiting for bytes.
    """
    entry = _vector(
        tmp_path,
        operation=operation,
        direction=direction,
        status=status,
        schema=schema,
        headers={"Content-Type": "application/json"},
    )
    assert _codes(*entry, specs, media_schemas) == {E.API_SCHEMA}


@pytest.mark.parametrize(
    ("operation", "status", "headers"),
    [
        ("backend.head_upload_file", 410, None),
        ("backend.head_upload_file", 200, {"Upload-Offset": "0", "Upload-Length": "4096"}),
        ("backend.patch_upload_file", 204, {"Upload-Offset": "1024"}),
    ],
    ids=["head-410", "head-200", "patch-204"],
)
def test_a_body_where_the_contract_allows_none_is_an_index_defect(
    tmp_path, specs, media_schemas, operation, status, headers
) -> None:
    """RFC 9110 §9.3.2 and §15.3.3 leave a HEAD and a 204 without content.

    The defect is the index naming a body file at all, so it reports the index code and
    the body is never read: an envelope under a HEAD is not a malformed envelope, it is
    bytes that should not exist.
    """
    entry = _vector(
        tmp_path,
        operation=operation,
        direction="response",
        status=status,
        body={"v": 1, "error": {"code": "EXPIRED", "message": "gone", "retryable": False, "request_id": "req-1"}},
        headers=headers,
    )
    assert _codes(*entry, specs, media_schemas) == {E.FIXTURE_INDEX_INVALID}


@pytest.mark.parametrize(
    ("operation", "status", "headers"),
    [
        ("device.get_preview", 200, {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}),
        (
            "backend.get_clip_file",
            200,
            {"Accept-Ranges": "bytes", "ETag": '"' + "0" * 64 + '"', "Content-Length": "434"},
        ),
    ],
    ids=["preview-stream", "binary-download"],
)
def test_the_presence_check_leaves_the_documented_non_json_bodies_alone(
    tmp_path, specs, media_schemas, operation, status, headers
) -> None:
    """A body the contract publishes as bytes or a stream stays a headers-only vector."""
    entry = _vector(
        tmp_path, operation=operation, direction="response", status=status, headers=headers
    )
    assert _codes(*entry, specs, media_schemas) == set()


def test_the_body_ceiling_governs_requests_and_leaves_responses_alone(
    tmp_path, specs, media_schemas, by_id
) -> None:
    """R4: the published control bound is a bound on what a client sends.

    Both halves are needed. A request past 16 KiB still has to be refused, or the gate
    would have been deleted rather than scoped; a full catalog page past 16 KiB has to
    pass, or the request bound was being applied to answers it never governed.
    """
    from tools.contracts.bounds import MAX_CONTROL_BODY_BYTES

    oversized = _vector(
        tmp_path,
        operation="device.pair",
        direction="request",
        schema="PairRequest",
        body={"v": 1, "setup_secret": "A" * 86, "client_name": "n" * (MAX_CONTROL_BODY_BYTES * 2)},
    )
    assert _codes(*oversized, specs, media_schemas) == {E.API_BODY_TOO_LARGE}

    page = by_id["backend/valid/clips-page-response-200-full-page"]
    body = json.dumps(_body(page), separators=(",", ":")).encode("utf-8")
    assert len(body) > MAX_CONTROL_BODY_BYTES, len(body)
    assert page["expected"] == "valid"
    assert _observed(page, specs, media_schemas) == set()


def test_a_body_using_a_non_json_literal_is_refused_before_the_schema(
    tmp_path, specs, media_schemas, by_id
) -> None:
    """RFC 8259 §6 admits no NaN, so a body carrying one is not JSON at all.

    Python's decoder accepts the literal by default, which is how such a vector could
    once have been generated *and* validated; the strict hook makes both halves refuse.
    """
    entry = _vector(
        tmp_path,
        operation="backend.get_job",
        direction="response",
        status=200,
        schema="JobRecord",
        raw_body=b'{"v":1,"job_id":"job-1","state":"running","progress":NaN,'
        b'"error_code":null,"derivative_id":null}\n',
    )
    assert _codes(*entry, specs, media_schemas) == {E.API_SCHEMA}

    committed = by_id["backend/invalid/job-response-200-progress-nan"]
    shipped = (FIXTURES / committed["files"][0]).read_bytes()
    assert b'"progress":NaN' in shipped, shipped
    assert _observed(committed, specs, media_schemas) == {E.API_SCHEMA}


def test_no_conforming_body_carries_a_non_json_literal() -> None:
    """The generator cannot produce one, so only a deliberate defect may carry one.

    ``dump_json`` refusing the value is the writer's contract; this is the corpus half of
    the same statement, read with the validator's own hook: every committed wire file
    either parses as strict JSON or is the vector whose declared defect is that it does
    not. A second offender would be a defect nobody declared.
    """
    from tools.contracts.api_validate import _reject_nonfinite
    from tools.contracts.media_model import dump_json

    with pytest.raises(ValueError):
        dump_json({"v": 1, "progress": float("nan")})

    offenders = []
    for entry in _all_api_entries():
        for name in entry["files"]:
            if name.endswith(".headers.json"):
                continue
            data = (FIXTURES / name).read_bytes()
            try:
                json.loads(data.decode("utf-8"), parse_constant=_reject_nonfinite)
            except ValueError:
                offenders.append((name, entry["expected"], entry["expected_error_codes"]))
    assert offenders == [
        (
            "backend/invalid/job-response-200-progress-nan.json",
            "invalid",
            ["API_SCHEMA"],
        )
    ], offenders


def _all_api_entries() -> list[dict]:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    return [entry for entry in document["fixtures"] if entry["kind"] == "api"]


def test_the_preview_media_type_is_the_stream_the_document_publishes(
    specs: dict, by_id: dict, media_schemas: dict
) -> None:
    """R6: the one non-JSON body this contract publishes says the same thing everywhere.

    The operation table decides what the validator accepts, the YAML is what a client is
    generated from, and the vector is what a reviewer can read off the wire. If the
    published media type drifts in any of the three, a consumer is coded against a stream
    no conforming device sends, and the corpus still passes.
    """
    from tools.contracts.api_model import PREVIEW_CONTENT_TYPE

    preview = ALL_OPERATIONS["device.get_preview"]
    assert PREVIEW_CONTENT_TYPE == "multipart/x-mixed-replace; boundary=frame"
    assert preview.content_types_for("response", 200) == frozenset({PREVIEW_CONTENT_TYPE})
    published = specs["device"]["paths"][preview.path]["get"]["responses"]["200"]
    assert set(published["content"]) == {PREVIEW_CONTENT_TYPE}, sorted(published["content"])
    assert set(published["headers"]) == {"Cache-Control"}, sorted(published["headers"])

    stream = by_id["device/valid/preview-response-200-no-store"]
    assert _headers(stream)["Content-Type"] == PREVIEW_CONTENT_TYPE
    assert _observed(stream, specs, media_schemas) == set()
    # The vector that answers the stream with a JSON document is the regression this
    # tie-out exists to keep refused.
    impostor = by_id["device/invalid/preview-response-200-json-content-type"]
    assert _headers(impostor)["Content-Type"] == "application/json"
    assert _observed(impostor, specs, media_schemas) == {E.HEADER_INVALID}


def _rule_codes(operation: str, direction: str, status: int | None, name: str, value: str):
    """One header value through the one rule a committed vector would send it through."""
    from tools.contracts.api_validate import HEADER_RULES, _HeaderContext

    rule = HEADER_RULES.get(name.lower())
    assert rule is not None, f"{name} has no documented rule"
    context = _HeaderContext(
        location=f"round-4:{operation}",
        operation=ALL_OPERATIONS[operation],
        direction=direction,
        status=status,
        headers={name: value},
    )
    return {violation.code for violation in rule(context, name, value)}


@pytest.mark.parametrize(
    ("operation", "direction", "status", "value", "codes"),
    [
        ("device.get_preview", "response", 200, "multipart/x-mixed-replace; boundary=frame", set()),
        ("device.get_preview", "response", 200, "application/json", {E.HEADER_INVALID}),
        ("device.get_preview", "response", 200, "text/plain", {E.HEADER_INVALID}),
        ("device.pair", "response", 201, "application/json", set()),
        ("device.pair", "response", 201, "multipart/x-mixed-replace; boundary=frame", {E.HEADER_INVALID}),
        ("device.pair", "response", 201, "application/octet-stream", {E.HEADER_INVALID}),
        ("device.get_clip_file", "response", 200, "application/octet-stream", set()),
        ("device.get_clip_file", "response", 206, "application/json", {E.HEADER_INVALID}),
        ("backend.head_upload_file", "response", 200, "application/octet-stream", {E.HEADER_INVALID}),
        ("backend.head_upload_file", "response", 410, "application/json", {E.HEADER_INVALID}),
        ("backend.patch_upload_file", "request", None, "application/octet-stream", set()),
        ("backend.patch_upload_file", "request", None, "application/json", {E.HEADER_INVALID}),
        ("device.post_ota", "request", None, "application/octet-stream", set()),
        ("device.pair", "request", None, "application/json", set()),
    ],
    ids=[
        "preview-its-own-stream",
        "preview-answering-json",
        "preview-answering-text",
        "pair-json-record",
        "pair-with-a-stream",
        "pair-with-raw-bytes",
        "download-octet-stream",
        "download-as-json",
        "head-claiming-bytes",
        "head-claiming-json",
        "chunk-octet-stream",
        "chunk-as-json",
        "ota-image-octet-stream",
        "pair-request-json",
    ],
)
def test_a_media_type_is_judged_against_the_operation_that_sends_it(
    operation: str, direction: str, status: int | None, value: str, codes: set[str]
) -> None:
    """A media type is only conforming *for* the operation that publishes it.

    ``application/json`` is documented by these contracts, which is exactly the hole: the
    old corpus-wide vocabulary accepted it wherever it appeared, so a preview that
    answered one JSON document and a HEAD that claimed a body both passed.
    """
    assert _rule_codes(operation, direction, status, "Content-Type", value) == codes


@pytest.mark.parametrize(
    ("operation", "direction", "status", "value", "codes"),
    [
        ("device.get_preview", "response", 200, "no-store", set()),
        ("device.get_preview", "response", 200, "max-age=60", {E.HEADER_INVALID}),
        ("device.pair", "response", 201, "no-store", {E.HEADER_INVALID}),
        ("device.get_clip_file", "response", 200, "no-store", {E.HEADER_INVALID}),
        ("device.pair", "request", None, "no-store", {E.HEADER_INVALID}),
    ],
    ids=[
        "preview-no-store",
        "preview-caching-a-stream",
        "token-response-with-a-directive",
        "download-with-a-directive",
        "request-with-a-directive",
    ],
)
def test_cache_control_is_accepted_only_where_the_contract_documents_it(
    operation: str, direction: str, status: int | None, value: str, codes: set[str]
) -> None:
    """Only the live preview documents ``Cache-Control``, and only as ``no-store``.

    device-v1.yaml publishes ``components/headers/CacheControlNoStore`` on the preview 200
    without marking it required, so the directive is allowed there and is a claim no other
    operation is entitled to make.
    """
    assert _rule_codes(operation, direction, status, "Cache-Control", value) == codes


def test_the_shared_media_type_vocabulary_is_exactly_what_some_operation_publishes() -> None:
    """No media type may survive in the shared vocabulary that no operation documents.

    The per-operation table decides acceptance; the shared set is the cross-contract
    vocabulary a message quotes. A stale entry there would be a media type the tests
    claim exists and no vector or document can name.
    """
    from tools.contracts.api_validate import DOCUMENTED_CONTENT_TYPES

    published: set[str] = set()
    for operation in ALL_OPERATIONS.values():
        published |= operation.content_types_for("request", None)
        for status in operation.documented_statuses:
            published |= operation.content_types_for("response", status)
    assert published == set(DOCUMENTED_CONTENT_TYPES), (
        sorted(published ^ set(DOCUMENTED_CONTENT_TYPES)),
    )


def test_the_document_promises_no_content_where_the_method_forbids_it(
    specs: dict, index: list[dict]
) -> None:
    """R9: the HEAD operation answers with status and headers, in both notations.

    The YAML used to point its three refusals at the shared JSON error components, and the
    corpus shipped three bodies nobody would send; either half regrowing content is a
    contract that teaches a client to read bytes that never arrive.
    """
    head = ALL_OPERATIONS["backend.head_upload_file"]
    responses = specs["backend"]["paths"][head.path]["head"]["responses"]
    for status, response in responses.items():
        # A response may promise a body through a component reference, so the promise is
        # judged on what a generated client would actually see, not on the key that
        # carries it: `{"$ref": "#/components/responses/Unauthorized"}` names a JSON body
        # and is refused here exactly as an inline `content:` block would be.
        published = resolve_refs(response, root=specs["backend"])
        assert not published.get("content"), (status, sorted(published.get("content", {})))
    vectors = [entry for entry in index if entry["operation"] == "backend.head_upload_file"]
    assert vectors, "the HEAD operation has no vector at all"
    for entry in vectors:
        if entry["expected"] == "valid":
            assert not [
                name for name in entry["files"] if not name.endswith(".headers.json")
            ], entry["id"]
    # Exactly one HEAD vector is allowed to name a body file: the one whose declared
    # defect is shipping it, and that is the only code it may declare.
    with_bodies = [
        entry
        for entry in vectors
        if any(not name.endswith(".headers.json") for name in entry["files"])
    ]
    assert [entry["id"] for entry in with_bodies] == [
        "backend/invalid/upload-head-response-410-with-body"
    ]
    assert with_bodies[0]["expected_error_codes"] == ["FIXTURE_INDEX_INVALID"]


def test_the_two_new_refusals_are_documented_and_demonstrated(
    specs: dict, by_id: dict, media_schemas: dict
) -> None:
    """R8: the pairing window and the expired upload are refusals, not prose.

    Each half has to hold in all three notations at once: the operation table that drives
    validation, the OpenAPI response a client is generated from, and a committed golden
    vector that shows the shared envelope arriving with the code the spec names.
    """
    pair = ALL_OPERATIONS["device.pair"]
    assert pair.error_codes.get(403) == ("FORBIDDEN",), pair.error_codes
    pair_response = specs["device"]["paths"]["/pair"]["post"]["responses"]["403"]
    assert pair_response["$ref"] == "#/components/responses/Forbidden"
    forbidden = by_id["device/valid/pair-response-403-forbidden"]
    assert forbidden["expected"] == "valid"
    assert forbidden["api_error_code"] == "FORBIDDEN"
    assert _observed(forbidden, specs, media_schemas) == set()

    patch = ALL_OPERATIONS["backend.patch_upload_file"]
    assert patch.error_codes.get(410) == ("EXPIRED",), patch.error_codes
    gone = specs["backend"]["paths"]["/uploads/{id}/files/{name}"]["patch"]["responses"]["410"]
    assert gone["$ref"] == "#/components/responses/Gone"
    expired = by_id["backend/valid/patch_upload_file-response-410-expired"]
    assert expired["expected"] == "valid"
    assert expired["api_error_code"] == "EXPIRED"
    assert _observed(expired, specs, media_schemas) == set()
