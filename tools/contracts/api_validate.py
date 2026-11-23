"""Validation of committed API vectors against the OpenAPI documents.

A fixture is the exact wire body plus, when the vector needs one, the exact header
map. This module validates both against the published contract *and* against the
spec-derived operation table in :mod:`tools.contracts.api_model`, so a contract file
that quietly dropped a documented status or a stable error code cannot pass.

The byte-range rules follow one decision table, written out above :func:`_rule_range`.
What the contract *supports* (interfaces.md §4) and what is *satisfiable* for this
file (RFC 9110 §14.4) are different questions, and a response only speaks about the
range when its status is about the range: the §4 gates — authentication, existence,
lease, the ``If-Match`` precondition — come first (RFC 9110 §13.2.2), so 200, 206 and
416 are the only statuses that can grant or refuse bytes. That precedence is a
property of answers. A request is judged on its specifier alone, because nothing has
been evaluated ahead of it to excuse a form §4 does not support.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from . import errors as E
from .api_model import ALL_OPERATIONS, Operation
from .bounds import (
    API_VERSION,
    CLIP_FILE_NAMES,
    MAX_CHUNK_BYTES,
    MAX_CONTROL_BODY_BYTES,
    MAX_CURSOR_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_PAGE_LIMIT,
    MAX_PAYLOAD_BYTES,
    MIN_CHUNK_BYTES,
    UINT53_MAX,
)
from .errors import Violation
from .schema_docs import resolve_refs, schema_error_report

_UUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_QUOTED_SHA = re.compile(r'\A"[0-9a-f]{64}"\Z')
# The hyphen is mandatory: `bytes=10` is not a range this contract supports, and
# neither is a multipart, suffix or otherwise unrecognised byte-range specifier.
_SINGLE_RANGE = re.compile(r"\Abytes=([0-9]+)-([0-9]*)\Z")
_CONTENT_RANGE = re.compile(r"\Abytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")
# The unsatisfiable-range answer of RFC 9110 §14.4: a refusal may name the file's
# total size without granting anything.
_STAR_CONTENT_RANGE = re.compile(r"\Abytes \*/([0-9]+)\Z")
_UPLOAD_CHECKSUM = re.compile(r"\Asha256 [0-9a-f]{64}\Z")
_ERROR_CODE = re.compile(r"\A[A-Z][A-Z0-9_]{0,63}\Z")
_BASE64URL = re.compile(r"\A[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True)
class _HeaderContext:
    """What a header rule needs to know beyond the header value itself."""

    location: str
    operation: Operation
    direction: str
    status: int | None
    headers: Mapping[str, str]


#: Operations whose JSON body carries a base64url binding that JSON Schema cannot bound.
_MANIFEST_BOUND_OPERATIONS: frozenset[str] = frozenset({"backend.create_upload"})


def validate_api_fixture(
    root: Path,
    entry: Mapping[str, Any],
    specs: Mapping[str, Mapping[str, Any]],
    media_schemas: Mapping[str, Mapping[str, Any]],
) -> list[Violation]:
    """Validate one committed API vector; ``specs`` holds the two parsed documents."""
    operation = ALL_OPERATIONS.get(str(entry.get("operation")))
    if operation is None:
        return [
            Violation(
                E.API_OPERATION_UNKNOWN,
                str(entry.get("id")),
                f"no documented operation {entry.get('operation')!r}",
            )
        ]
    violations: list[Violation] = []
    if entry.get("contract") != f"{operation.contract}-v1":
        violations.append(
            Violation(
                E.API_DIRECTION_MISMATCH,
                str(entry["id"]),
                f"index says {entry.get('contract')!r} but {operation.key} is {operation.contract}",
            )
        )
    document = specs.get(operation.contract)
    if document is None:
        # The other document loaded; report the gap and keep checking the vector
        # against the operation table rather than aborting the whole run.
        violations.append(
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"{operation.contract}-v1",
                "no OpenAPI document of that contract was loaded, so the vector cannot be "
                "checked against its documented operation",
            )
        )
        document = {}
    path_item = document.get("paths", {}).get(operation.path, {})
    item = path_item.get(operation.method.lower(), {}) if isinstance(path_item, Mapping) else {}
    if item.get("operationId") != operation.operation_id:
        violations.append(
            Violation(
                E.API_OPERATION_UNKNOWN,
                f"{operation.method} {operation.path}",
                f"operationId {item.get('operationId')!r} is not {operation.operation_id!r}",
            )
        )

    status = entry.get("status")
    direction = str(entry.get("direction"))
    if direction not in {"request", "response"}:
        violations.append(Violation(E.API_DIRECTION_MISMATCH, str(entry["id"]), direction))
    if direction == "response":
        if status is None:
            violations.append(Violation(E.API_STATUS_UNDOCUMENTED, str(entry["id"]), "no status"))
        elif status not in operation.documented_statuses:
            violations.append(
                Violation(
                    E.API_STATUS_UNDOCUMENTED,
                    f"{operation.key} {status}",
                    "the spec assigns this operation neither that success nor that rejection",
                )
            )
        expected_schema = operation.response_schemas.get(status) if status is not None else None
    else:
        expected_schema = operation.request_schema
    if entry.get("schema") != expected_schema:
        violations.append(
            Violation(
                E.FIXTURE_INDEX_INVALID,
                str(entry["id"]),
                f"index schema {entry.get('schema')!r} but the contract binds {expected_schema!r}",
            )
        )

    body_bytes, file_violations = _load_body(root, entry)
    violations.extend(file_violations)
    headers, header_violations = _load_headers(root, entry)
    violations.extend(header_violations)
    if file_violations or header_violations:
        # The index names a wire file that is absent or unreadable, so its bytes cannot
        # be decoded — but that is no licence to skip the wire rules that do not need
        # the bytes: the required-header walk below still runs, against the empty map
        # this vector effectively presents.
        body_bytes = None
    body: dict[str, Any] | None = None

    presence = _body_presence(operation, entry, direction, status)
    if presence:
        # A body that is not supposed to exist is not decoded, and a body that is
        # supposed to exist is not substituted by an empty walk: either way the
        # contents rules have nothing legitimate to judge.
        violations.extend(presence)
        body_bytes = None
    if body_bytes is not None:
        if direction == "request":
            # Only a request meets a published body ceiling here: the request is what
            # the receiving side has to buffer, and the upload-init exception (32 KiB)
            # belongs to that direction. A response is bounded by what the contract
            # publishes about it — the manifest-binding rules and the Content-Length
            # header rule — not by a request limit applied backwards to it.
            bound = operation.body_bound_bytes or MAX_CONTROL_BODY_BYTES
            if len(body_bytes) > bound:
                violations.append(
                    Violation(
                        E.API_BODY_TOO_LARGE,
                        str(entry["id"]),
                        f"{len(body_bytes)} bytes exceeds the {bound}-byte request limit",
                    )
                )
                # Refuse an over-limit body before decoding any further of it.
                return violations
        try:
            parsed = json.loads(body_bytes.decode("utf-8"), parse_constant=_reject_nonfinite)
        except ValueError as error:
            # One path for every way a body fails to be JSON: the decoder's
            # ``JSONDecodeError``, the strict UTF-8 read's ``UnicodeDecodeError`` and
            # ``_reject_nonfinite``'s refusal of ``NaN``/``Infinity`` — all three mean
            # these bytes are not a JSON body, and none of them can be schema-checked.
            violations.append(
                Violation(E.API_SCHEMA, str(entry["id"]), f"body is not JSON: {error}")
            )
            return violations
        if not isinstance(parsed, dict):
            violations.append(
                Violation(E.API_SCHEMA, str(entry["id"]), "top level is not a JSON object")
            )
            return violations
        body = parsed

        if "v" not in body:
            violations.append(
                Violation(
                    E.API_VERSION_MISSING,
                    str(entry["id"]),
                    f"every request and response object carries top-level v: {API_VERSION}",
                )
            )
            return violations
        if body.get("v") != API_VERSION:
            violations.append(
                Violation(
                    E.API_VERSION_UNSUPPORTED,
                    str(entry["id"]),
                    f"v {body.get('v')!r}; unknown major versions fail",
                )
            )
            return violations

        if direction == "response" and isinstance(status, int) and status >= 400:
            violations.extend(_validate_error_vector(operation, entry, document, body, status))
        elif expected_schema is not None:
            violations.extend(_validate_against_component(document, expected_schema, body, entry))
        elif direction == "response" and status in operation.response_schemas:
            pass  # documented as a non-JSON body (binary or multipart): headers carry the rules
        elif direction == "request":
            violations.append(
                Violation(
                    E.FIXTURE_INDEX_INVALID,
                    str(entry["id"]),
                    "a JSON request body needs a request schema in the operation table",
                )
            )

    if body is not None and operation.key in _MANIFEST_BOUND_OPERATIONS and direction == "request":
        manifest_schema = media_schemas.get("manifest")
        if manifest_schema is None:
            # The dedicated base64url/manifest rules need the media schema. Without it
            # this vector cannot be cleared at all, so the gap is a finding rather than a
            # silently skipped check: a vector nobody checked may not print PASS.
            violations.append(
                Violation(
                    E.SCHEMA_DOCUMENT_INVALID,
                    str(entry["id"]),
                    "no usable media manifest schema was loaded, so the binding is unchecked",
                )
            )
        else:
            binding = validate_manifest_binding(entry, body, manifest_schema)
            if binding:
                # The dedicated base64url/manifest rules own this property: reporting the
                # component ``pattern`` failure as well would only duplicate the code.
                violations[:] = [
                    violation
                    for violation in violations
                    if "manifest_base64url" not in violation.location
                ]
            violations.extend(binding)

    context = _HeaderContext(
        location=str(entry["id"]),
        operation=operation,
        direction=direction,
        status=status if isinstance(status, int) else None,
        # A vector that ships no sidecar still owes every header the contract marks
        # required for this operation and status: absence is a finding, not a pass, so
        # the required-name walk runs against an empty map rather than being skipped.
        headers=headers or {},
    )
    for name in _required_headers(operation, direction, status):
        if _lookup_header(context.headers, name) is None:
            violations.append(
                Violation(
                    E.HEADER_MISSING,
                    f"{context.location}: {name}",
                    f"{operation.key} requires this header",
                )
            )
    if headers is not None:
        for name, value in headers.items():
            rule = HEADER_RULES.get(name.lower())
            if rule is None:
                violations.append(
                    Violation(
                        E.HEADER_INVALID,
                        f"{context.location}: {name}",
                        "no documented header of this name exists for these contracts",
                    )
                )
                continue
            violations.extend(rule(context, name, value))

    if (
        not operation.required_request_headers
        and direction == "request"
        and body is None
        and headers is None
        and not file_violations
        and not header_violations
    ):
        # Only a vector that really declares nothing is empty: a named-but-absent file
        # has already been reported as FIXTURE_FILE_MISSING above.
        violations.append(
            Violation(E.FIXTURE_INDEX_INVALID, str(entry["id"]), "vector carries neither body nor headers")
        )
    return violations


def _reject_nonfinite(name: str) -> float:
    """Refuse the three JavaScript literals Python's decoder accepts by default.

    ``NaN``, ``Infinity`` and ``-Infinity`` are not JSON (RFC 8259 §6 forbids them and
    a conforming parser has to refuse them), so a committed vector carrying one would
    be bytes this contract's readers cannot parse. Turning the token into a parse
    failure routes it into the one path that reports undecodable bodies, which is
    where a non-JSON wire value belongs.
    """
    raise ValueError(f"{name} is not a JSON notation (RFC 8259 §6)")


def _body_presence(
    operation: Operation,
    entry: Mapping[str, Any],
    direction: str,
    status: Any,
) -> list[Violation]:
    """Whether this vector may carry a body at all, judged before its contents.

    interfaces.md §1 binds a body to every request whose schema the contract names, to
    every documented success that answers with a record, and to every rejection, which
    answers with the shared error envelope. RFC 9110 §9.3.2 and §15.3.3 take the body
    away from a HEAD answer and from a 204, so those two are exempt both ways round.
    Checking presence before contents is what stops a vector that ships nothing from
    printing a clean PASS on the strength of the checks it never reached.

    Presence is a fact about the index, not about what could be read: it asks which
    files :file:`fixtures.json` names. Reading is a separate question with its own code
    (``FIXTURE_FILE_MISSING``), and conflating the two would let an unreadable header
    sidecar report a body that is sitting there as missing.
    """
    named = [
        str(name) for name in entry.get("files", []) if not str(name).endswith(".headers.json")
    ]
    if direction == "response" and (operation.is_head or status == 204):
        if not named:
            return []
        reason = (
            f"a {status} answer carries no body (RFC 9110 §15.3.3)"
            if status == 204
            else "a HEAD answer carries no content (RFC 9110 §9.3.2)"
        )
        return [
            Violation(
                E.FIXTURE_INDEX_INVALID,
                str(entry["id"]),
                f"{operation.key} {reason}, but the index ships {', '.join(named)}",
            )
        ]
    if named:
        return []
    required = _required_body_reason(operation, direction, status)
    if required is None:
        return []
    return [Violation(E.API_SCHEMA, str(entry["id"]), required)]


def _required_body_reason(
    operation: Operation, direction: str, status: Any
) -> str | None:
    """Why this vector has to ship a body, or ``None`` when it may stay empty.

    A documented non-JSON body (the preview stream, the two downloads) is deliberately
    absent from this list: those vectors carry headers and status, and the bytes are
    outside what this gate can judge.
    """
    if direction == "request":
        if operation.request_schema is not None:
            return (
                f"{operation.key} requires a {operation.request_schema} request body; "
                "the index names no body file"
            )
        return None
    if not isinstance(status, int):
        return None
    if status in operation.response_schemas:
        if operation.response_schemas[status] is None:
            return None
        return (
            f"{operation.key} {status} requires a {operation.response_schemas[status]} "
            "response body; the index names no body file"
        )
    if status in operation.error_codes:
        return (
            f"{operation.key} {status} answers with the shared error envelope; the index "
            "names no body file"
        )
    return None


def _load_body(root: Path, entry: Mapping[str, Any]) -> tuple[bytes | None, list[Violation]]:
    """Read the fixture's exact wire body, reporting a broken index instead of raising.

    A corpus whose file is missing is exactly what this gate exists to catch, so it
    has to be a finding with a code, not an internal error that aborts the run.
    """
    for name in entry.get("files", []):
        text = str(name)
        if text.endswith(".headers.json"):
            continue
        path = root / text
        if not path.is_file():
            return None, [
                Violation(E.FIXTURE_FILE_MISSING, text, "indexed by fixtures.json but absent")
            ]
        try:
            return path.read_bytes(), []
        except OSError as error:
            return None, [Violation(E.FIXTURE_FILE_MISSING, text, str(error))]
    return None, []


def _load_headers(root: Path, entry: Mapping[str, Any]) -> tuple[dict[str, str] | None, list[Violation]]:
    """Read the fixture's header map, if it has one."""
    for name in entry.get("files", []):
        text = str(name)
        if not text.endswith(".headers.json"):
            continue
        path = root / text
        if not path.is_file():
            return None, [
                Violation(E.FIXTURE_FILE_MISSING, text, "indexed by fixtures.json but absent")
            ]
        try:
            document = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return None, [Violation(E.API_SCHEMA, text, f"header vector is not JSON: {error}")]
        if not isinstance(document, dict):
            return None, [
                Violation(E.API_SCHEMA, text, "header vector must be a JSON object of name/value")
            ]
        return {str(key): str(value) for key, value in document.items()}, []
    return None, []


def _required_headers(
    operation: Operation, direction: str, status: Any
) -> tuple[str, ...]:
    if direction == "request":
        return operation.required_request_headers
    if isinstance(status, int):
        return operation.required_response_headers.get(status, ())
    return ()


def _lookup_header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _validate_against_component(
    document: Mapping[str, Any],
    schema_name: str,
    instance: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> list[Violation]:
    """Validate a body against one ``components/schemas`` entry."""
    components = document.get("components", {}).get("schemas", {})
    if schema_name not in components:
        return [
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"components/schemas/{schema_name}",
                "the contract does not define the schema the index binds",
            )
        ]
    schema = resolve_refs(components[schema_name], root=document)
    found: list[Violation] = []
    for property_name, keyword, message in schema_error_report(schema, instance):
        code = E.API_SCHEMA_MISSING_FIELD if keyword == "required" else E.API_SCHEMA
        location = f"{entry['id']}{f' at {property_name}' if property_name else ''}"
        found.append(Violation(code, location, message))
    return found


def _validate_error_vector(
    operation: Operation,
    entry: Mapping[str, Any],
    document: Mapping[str, Any],
    body: Mapping[str, Any],
    status: int,
) -> list[Violation]:
    """An error response must be the shared envelope with a code the spec assigns."""
    components = document.get("components", {}).get("schemas", {})
    if "Error" not in components:
        return [
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                "components/schemas/Error",
                "the contract has no reusable error envelope",
            )
        ]
    schema = resolve_refs(components["Error"], root=document)
    found: list[Violation] = []
    for property_name, keyword, message in schema_error_report(schema, body):
        found.append(
            Violation(
                E.ERROR_ENVELOPE_INVALID,
                f"{entry['id']}{f' at {property_name}' if property_name else ''}",
                f"{keyword}: {message}",
            )
        )
    error = body.get("error")
    if not isinstance(error, Mapping):
        found.append(
            Violation(E.ERROR_ENVELOPE_INVALID, f"{entry['id']}.error", "missing object")
        )
        return found
    code = error.get("code")
    if not isinstance(code, str) or _ERROR_CODE.match(code) is None:
        found.append(
            Violation(
                E.ERROR_ENVELOPE_INVALID,
                f"{entry['id']}.error.code",
                f"{code!r} is not an upper-snake-case stable code",
            )
        )
    else:
        allowed = operation.allowed_codes_for(status)
        if code not in allowed:
            found.append(
                Violation(
                    E.ERROR_CODE_UNDOCUMENTED,
                    f"{entry['id']}.error.code",
                    f"{code} is not documented for {operation.key} {status}; documented: "
                    f"{', '.join(sorted(set(operation.error_codes.get(status, ()))) ) or 'none'}",
                )
            )
    declared = entry.get("api_error_code")
    expected_codes = {str(value) for value in entry.get("expected_error_codes", [])}
    if declared is not None and declared != code:
        found.append(
            Violation(
                E.FIXTURE_INDEX_INVALID,
                f"{entry['id']}",
                f"index declares api_error_code {declared!r} but the body says {code!r}",
            )
        )
    if declared is None and E.ERROR_CODE_UNDOCUMENTED in expected_codes:
        # The whole point of such a vector is the code it demonstrates, so the
        # index has to name it; vectors defective in some other way may omit it.
        found.append(
            Violation(
                E.FIXTURE_INDEX_INVALID,
                f"{entry['id']}",
                "a vector demonstrating an undocumented code must record api_error_code",
            )
        )
    return found


# --- Header rules --------------------------------------------------------------

Rule = Callable[[_HeaderContext, str, str], list[Violation]]


def _rule_accept_ranges(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if value != "bytes":
        return [
            Violation(
                E.ACCEPT_RANGES_INVALID,
                f"{context.location}: {name}",
                f"{value!r}; immutable clip files always advertise bytes",
            )
        ]
    return []


def _rule_etag(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if _QUOTED_SHA.match(value) is None:
        return [
            Violation(
                E.ETAG_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not the quoted SHA-256 of the whole file",
            )
        ]
    return []


def _rule_if_match(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    return _rule_etag(context, name, value)


def _rule_content_length(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    location = f"{context.location}: {name}"
    number = _as_int(value)
    if number is None or number < 0:
        return [Violation(E.CONTENT_LENGTH_MISMATCH, location, f"{value!r} is not a byte count")]
    if context.operation.key == "backend.patch_upload_file" and context.direction == "request":
        if not MIN_CHUNK_BYTES <= number <= MAX_CHUNK_BYTES:
            return [
                Violation(
                    E.CHUNK_SIZE_INVALID,
                    location,
                    f"{number} is outside the {MIN_CHUNK_BYTES}-{MAX_CHUNK_BYTES} byte chunk range",
                )
            ]
    return []


def _rule_content_range(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    location = f"{context.location}: {name}"
    star = _STAR_CONTENT_RANGE.match(value)
    if star is not None:
        # ``bytes */<total>`` promises no bytes, so it belongs to the refusal alone.
        # A total of zero would describe a file this contract never stores. Only a
        # response that grants bytes is wrong to carry it: a refusal for a
        # higher-priority reason may echo the header it was given, exactly as a 416
        # does, and calling that a contract violation would fail a device the spec
        # requires to answer 412, 401, 404, 409 or 410 instead.
        if context.status in (200, 206):
            return [
                Violation(
                    E.CONTENT_RANGE_INVALID,
                    location,
                    f"{value!r} is the unsatisfiable-range form, which only a 416 may carry",
                )
            ]
        if context.status == 416 and int(star.group(1)) < 1:
            return [
                Violation(
                    E.CONTENT_RANGE_INVALID,
                    location,
                    f"{value!r} declares a file of no bytes",
                )
            ]
        return []
    match = _CONTENT_RANGE.match(value)
    if match is None:
        return [
            Violation(
                E.CONTENT_RANGE_INVALID,
                location,
                f"{value!r} is not `bytes <first>-<last>/<total>`",
            )
        ]
    if context.status == 416:
        return [
            Violation(
                E.CONTENT_RANGE_INVALID,
                location,
                f"{value!r} grants a range, which a 416 may not; the refusal states `bytes */<total>`",
            )
        ]
    first, last, total = (int(match.group(index)) for index in (1, 2, 3))
    if not first <= last < total:
        return [
            Violation(
                E.CONTENT_RANGE_INVALID,
                location,
                f"{value!r} is not an in-bounds ascending range of {total} bytes",
            )
        ]
    declared = _lookup_header(context.headers, "Content-Length")
    if declared is not None:
        number = _as_int(declared)
        if number != last - first + 1:
            return [
                Violation(
                    E.CONTENT_LENGTH_MISMATCH,
                    location,
                    f"Content-Length {declared} does not match the granted range of {last - first + 1} bytes",
                )
            ]
    return []


#: The Range decision table, in the words the validator applies (interfaces.md §4 for
#: what the contract allows, RFC 9110 §13.2.2, §14.4 and §15.5.17 for what a refusal
#: means). The two questions are separate: what the contract *supports* at all, and
#: what is *satisfiable* for this file. The table has one row per direction, and they
#: are read differently on purpose: the precedence below belongs to answers only, and
#: is no licence for a request to use a form the contract never supports.
#:
#: A response is only a range statement when it is about the range. The gates ahead of
#: it — 400 request-level malformation, 401 authentication, 404 unknown clip, 409
#: expired lease, 410 evicted clip and the 412 `If-Match` precondition of a resume —
#: are all evaluated before a range is parsed or served (RFC 9110 §13.2.2, §14.4), so
#: such a refusal says nothing about the specifier and may echo whatever `Range` it
#: was given. Only three statuses speak about the range at all: 200 and 206 grant
#: bytes, and 416 refuses them. Every row below therefore reads: 416 clean, 200/206
#: flagged, anything else silent.
#:
#: * **Unsupported syntax** — anything the anchored ``_SINGLE_RANGE`` refuses
#:   (multipart, suffix, ``bytes=10``, junk). Granting bytes for a form the contract
#:   never supports is the violation, so 200/206 is ``RANGE_MULTI_NOT_ALLOWED`` and
#:   the required answer is 416. This is the contract being stricter than RFC 9110,
#:   which would let a server ignore an unparseable `Range` and answer 200 in full:
#:   §4's "Support single ... only" and "Multipart/suffix ranges are rejected with
#:   416" make the refusal mandatory instead, and that strictness applies to the
#:   answer about the range, not to a 401 or 412 that never reached range handling.
#: * **Supported syntax, unsatisfiable ordering** (``end < start``). A well-formed
#:   request that can never be served, so 416 is the natural answer and granting it
#:   (200/206) is ``RANGE_MULTI_NOT_ALLOWED``: serving bytes a client did not ask for
#:   is worse than refusing.
#: * **Supported syntax, correctly ordered** (``bytes=start-end`` or ``bytes=start-``)
#:   *and the response claims 416*. A refusal of a range that looks serveable is
#:   honest only when it *proves* the range is past the end of this file:
#:   ``Content-Range: bytes */<total>`` with ``start >= total``. Without that header,
#:   or with a start inside the file, the claim is unfounded and is
#:   ``RANGE_MULTI_NOT_ALLOWED``. This row is keyed on the 416, because it is about a
#:   device *claiming* a refusal it cannot support.
#: * **A request's own specifier** (``direction == "request"``), which has no status to
#:   be silent about. The precedence above describes how a server *replies*; a request
#:   is not an answer to anything, so nothing has been evaluated ahead of it and no
#:   precondition can explain its spelling. §4 supports "single ``Range:
#:   bytes=start-end`` or ``bytes=start-`` only", so multipart, suffix, ``bytes=10``
#:   and junk, and an ordering that can never be served (``end < start``), are outside
#:   the contract as requests whatever the device eventually answers, and each is
#:   ``RANGE_MULTI_NOT_ALLOWED``. A correctly ordered request is silent: satisfiability
#:   needs this file's length, which a request does not have.


def _rule_range(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    location = f"{context.location}: {name}"
    match = _SINGLE_RANGE.match(value)
    if context.direction == "request":
        # The table's request row. A request has no status, and the precedence that
        # keeps a gated response silent describes how a server replies; nothing was
        # evaluated ahead of a request, so its specifier is judged on its own.
        if match is None:
            return [
                Violation(
                    E.RANGE_MULTI_NOT_ALLOWED,
                    location,
                    f"{value!r} is not a single bytes=start-end or bytes=start- range, "
                    f"the only two forms the contract makes a request",
                )
            ]
        start = int(match.group(1))
        end = match.group(2)
        if end and int(end) < start:
            return [
                Violation(
                    E.RANGE_MULTI_NOT_ALLOWED,
                    location,
                    f"{value!r} asks for bytes beyond their own end, which no request may ask for",
                )
            ]
        return []
    if match is None:
        # Unsupported syntax: only a response that grants bytes is wrong. A 416 is
        # the required refusal, and a §4 gate that never reached range processing is
        # no statement about the specifier at all (see the table above).
        if context.status in (200, 206):
            return [
                Violation(
                    E.RANGE_MULTI_NOT_ALLOWED,
                    location,
                    f"{value!r} is not a single bytes=start-end or bytes=start- range",
                )
            ]
        return []
    start = int(match.group(1))
    end = match.group(2)
    if end and int(end) < start:
        # The table's second row: only a response that grants bytes is wrong, since a
        # 416 is the natural answer to the ordering and a §4 gate never reached it.
        if context.status in (200, 206):
            return [
                Violation(
                    E.RANGE_MULTI_NOT_ALLOWED,
                    location,
                    f"{value!r} asks for bytes beyond their own end, which only a 416 may answer",
                )
            ]
        return []
    if context.status == 416:
        proven_beyond_end = False
        declared = _lookup_header(context.headers, "Content-Range")
        if declared is not None:
            total = _STAR_CONTENT_RANGE.match(declared)
            proven_beyond_end = total is not None and start >= int(total.group(1))
        if proven_beyond_end:
            return []
        return [
            Violation(
                E.RANGE_MULTI_NOT_ALLOWED,
                location,
                f"416 is only the answer to a range the contract rejects or one its "
                f"Content-Range proves starts past the end, and {value!r} is neither",
            )
        ]
    return []


def _rule_upload_offset(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    number = _as_int(value)
    if number is None or number < 0 or number > UINT53_MAX:
        return [
            Violation(
                E.UPLOAD_OFFSET_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not a nonnegative committed offset",
            )
        ]
    return []


def _rule_upload_length(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    number = _as_int(value)
    if number is None or not 1 <= number <= MAX_PAYLOAD_BYTES:
        return [
            Violation(
                E.UPLOAD_LENGTH_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not a declared length of 1..{MAX_PAYLOAD_BYTES} bytes",
            )
        ]
    return []


def _rule_upload_checksum(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if _UPLOAD_CHECKSUM.match(value) is None:
        return [
            Violation(
                E.UPLOAD_CHECKSUM_SYNTAX,
                f"{context.location}: {name}",
                f"{value!r} is not `sha256 <64 lowercase hex>`",
            )
        ]
    return []


def _rule_lease(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if not 1 <= len(value) <= 64:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                "a lease id is 1-64 characters",
            )
        ]
    return []


def _rule_idempotency_key(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if _UUID.match(value) is None:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not a canonical UUID",
            )
        ]
    return []


def _rule_cursor(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if len(value) > MAX_CURSOR_CHARS:
        return [
            Violation(
                E.CURSOR_TOO_LONG,
                f"{context.location}: {name}",
                f"{len(value)} characters exceeds the {MAX_CURSOR_CHARS}-character cursor bound",
            )
        ]
    return []


def _rule_limit(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    number = _as_int(value)
    if number is None or not 1 <= number <= MAX_PAGE_LIMIT:
        return [
            Violation(
                E.PAGE_LIMIT_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is outside 1..{MAX_PAGE_LIMIT}",
            )
        ]
    return []


def _rule_upload_name(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if value not in CLIP_FILE_NAMES:
        return [
            Violation(
                E.FILE_NAME_NOT_ALLOWED,
                f"{context.location}: {name}",
                f"{value!r} is not one of {', '.join(CLIP_FILE_NAMES)}",
            )
        ]
    return []


#: The media types the two contracts ever put on a JSON/multipart/binary hop, as
#: published by the two documents. The per-operation table in
#: :mod:`tools.contracts.api_model` decides what one operation may carry; this set is
#: only the shared vocabulary that message and the OpenAPI tie-out quote.
DOCUMENTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/json",
        "multipart/x-mixed-replace; boundary=frame",
        "application/octet-stream",
    }
)


def _rule_content_type(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    # Judged against the selected operation, not against the corpus-wide vocabulary:
    # ``application/json`` is documented, which is exactly why an operation that never
    # promises a JSON body has to be refused here rather than waved through.
    allowed = context.operation.content_types_for(context.direction, context.status)
    if value not in allowed:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not a media type {context.operation.key} documents for this "
                f"{'request' if context.direction == 'request' else f'answer at {context.status}'} "
                f"({', '.join(sorted(allowed)) or 'no body, so no media type'})",
            )
        ]
    return []


def _rule_cache_control(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    """``Cache-Control`` where the contract documents it, and nowhere else.

    Only the live preview documents it — ``components/headers/CacheControlNoStore`` in
    device-v1.yaml, a ``const`` of ``no-store`` — and it documents it without marking it
    required, so a preview answer may carry it and no other operation may carry it at
    all: a directive is a claim about how a response may be stored, and no document
    makes that claim for anything else.
    """
    documented = {
        header.lower()
        for header in context.operation.documented_response_headers.get(
            context.status or -1, ()
        )
    }
    if name.lower() not in documented:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{context.operation.key} documents no Cache-Control at "
                f"{context.status}; only the live preview answers with one",
            )
        ]
    if value != "no-store":
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not the documented directive `no-store`: live preview parts "
                "are never cached",
            )
        ]
    return []


def _rule_retry_after(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    number = _as_int(value)
    if number is None or number < 0:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not a nonnegative delay in seconds",
            )
        ]
    return []


HEADER_RULES: Mapping[str, Rule] = {
    "accept-ranges": _rule_accept_ranges,
    "etag": _rule_etag,
    "if-match": _rule_if_match,
    "content-length": _rule_content_length,
    "content-range": _rule_content_range,
    "range": _rule_range,
    "upload-offset": _rule_upload_offset,
    "upload-length": _rule_upload_length,
    "upload-checksum": _rule_upload_checksum,
    "x-clip-lease": _rule_lease,
    "idempotency-key": _rule_idempotency_key,
    "cursor": _rule_cursor,
    "limit": _rule_limit,
    "x-upload-name": _rule_upload_name,
    "retry-after": _rule_retry_after,
    "content-type": _rule_content_type,
    "cache-control": _rule_cache_control,
}


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def validate_manifest_binding(entry: Mapping[str, Any], body: Mapping[str, Any], media_schema: Mapping[str, Any]) -> list[Violation]:
    """Check the base64url manifest binding of an upload-initialization vector.

    The contract cannot express these rules in JSON Schema, so they live here: the
    alphabet is unpadded base64url, the decoded length respects the 16,384-byte
    manifest bound and the decoded bytes are the exact manifest JSON.
    """
    encoded = body.get("manifest_base64url")
    location = str(entry["id"])
    if not isinstance(encoded, str):
        return []
    if _BASE64URL.match(encoded) is None:
        return [
            Violation(
                E.BASE64URL_ALPHABET_INVALID,
                f"{location}: manifest_base64url",
                "only the unpadded base64url alphabet is accepted",
            )
        ]
    if len(encoded) % 4 == 1:
        return [
            Violation(
                E.BASE64URL_LENGTH_INVALID,
                f"{location}: manifest_base64url",
                "length is not a possible base64 length",
            )
        ]
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except Exception as error:  # noqa: BLE001 - any decoding failure is one contract code
        return [
            Violation(
                E.BASE64URL_ALPHABET_INVALID,
                f"{location}: manifest_base64url",
                f"does not decode: {error}",
            )
        ]
    if len(decoded) > MAX_MANIFEST_BYTES:
        return [
            Violation(
                E.MANIFEST_DECODED_TOO_LARGE,
                f"{location}: manifest_base64url",
                f"decoded to {len(decoded)} bytes, above the {MAX_MANIFEST_BYTES}-byte manifest bound",
            )
        ]
    try:
        manifest = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [
            Violation(
                E.MANIFEST_JSON_INVALID_DECODED,
                f"{location}: manifest_base64url",
                f"decoded bytes are not JSON: {str(error).replace(chr(10), ' ')}",
            )
        ]
    found: list[Violation] = []
    for property_name, keyword, message in schema_error_report(media_schema, manifest):
        found.append(
            Violation(
                E.MANIFEST_DECODED_SCHEMA,
                f"{location}: manifest_base64url{f' at {property_name}' if property_name else ''}",
                f"{keyword}: {message}",
            )
        )
    return found
