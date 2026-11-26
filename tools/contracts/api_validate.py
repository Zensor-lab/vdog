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
import decimal
import hashlib
import json
import re
from dataclasses import dataclass, field
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
from .media_validate import MANIFEST_WIRE_SUPPRESSED, validate_manifest_fields
from .schema_docs import is_json_integer, resolve_refs, schema_error_report

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
# The bearer challenge RFC 9110 §15.5.2 requires on a 401, anchored with \A/\Z rather
# than ^/$: a scheme name with the terminator left in the buffer is not a challenge.
_WWW_AUTHENTICATE = re.compile(r'\ABearer( realm="[^"]{1,100}")?\Z')


@dataclass(frozen=True)
class _HeaderContext:
    """What a header rule needs to know beyond the header value itself."""

    location: str
    operation: Operation
    direction: str
    status: int | None
    headers: Mapping[str, str]
    #: The request that produced a response vector, when the vector ships one. A granted
    #: range means nothing without the specifier it answers, so ``_rule_content_range``
    #: reads the request's ``Range`` here; a vector without the sidecar keeps every
    #: existing behaviour, because an absent request is silence, not a pass.
    request_headers: Mapping[str, str] = field(default_factory=dict)


#: Operations whose JSON body carries a base64url binding that JSON Schema cannot bound.
_MANIFEST_BOUND_OPERATIONS: frozenset[str] = frozenset({"backend.create_upload"})

#: Operations whose 200 body *is* a completion manifest, so the media contract's own
#: field rules apply to it and not only the OpenAPI mirror it validates against.
_MANIFEST_RESPONSE_OPERATIONS: frozenset[str] = frozenset({"device.get_clip_manifest"})

#: Operations whose 200 body records a crop taken out of a clip this corpus also ships,
#: so the rectangle can be measured against the source it claims to come from.
_CROP_BOUND_OPERATIONS: frozenset[str] = frozenset({"backend.get_derivative"})

#: Operations whose 200 body carries a completion manifest as a *member* — today the
#: backend's ``StoredClip`` — so the media contract's own field rules apply to that
#: nested record too. ``device.get_clip_manifest`` (the body *is* the manifest) rides
#: :data:`_MANIFEST_RESPONSE_OPERATIONS` above; this table is for the transport where
#: the manifest travels inside a larger record, which the OpenAPI mirror alone leaves
#: free to contradict its own envelope.
_STORED_CLIP_MANIFEST_OPERATIONS: frozenset[str] = frozenset({"backend.get_clip"})


#: Operations whose request body is the raw bytes the contract publishes for them —
#: today only the chunk of an upload ``PATCH``, which ``backend-v1.yaml`` documents as
#: ``application/octet-stream`` of 1-1,048,576 bytes. Their body is never JSON-decoded:
#: there is no ``v`` to read, no component schema to bind, and the request ceiling that
#: guards control bodies would refuse a conforming chunk nobody sent text. What the
#: chunk owes is judged as bytes by :func:`validate_upload_chunk_body`.
_BINARY_REQUEST_OPERATIONS: frozenset[str] = frozenset({"backend.patch_upload_file"})


def validate_api_fixture(
    root: Path,
    entry: Mapping[str, Any],
    specs: Mapping[str, Mapping[str, Any]],
    media_schemas: Mapping[str, Mapping[str, Any]],
    clip_dimensions: Mapping[tuple[str, str], tuple[int, int]] | None = None,
) -> list[Violation]:
    """Validate one committed API vector; ``specs`` holds the two parsed documents.

    ``clip_dimensions`` maps a committed clip's ``(device_id, clip_id)`` pair to the
    source size its own manifest records, which is the only way a derivative vector's
    ``crop`` can be measured against the file it claims to have been cut from — and the
    pair is the key because ``clip_id`` is scoped by ``device_id`` in backend requests.
    Its absence is silence, never a pass: a clip this corpus does not ship has no size
    this validator may invent.
    """
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
    request_headers, request_header_violations = _load_request_headers(root, entry)
    violations.extend(request_header_violations)
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
    binary_request = direction == "request" and operation.key in _BINARY_REQUEST_OPERATIONS
    if body_bytes is not None and not binary_request:
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
            # ``parse_float=decimal.Decimal`` keeps the notation a body has to survive
            # on: the media walk parses its index that way (see
            # :func:`tools.contracts.media_validate._walk_index`), and a manifest
            # response or upload binding carries the very integers that decision judges.
            # The default float conversion turns ``266667.000000000001`` into exactly
            # ``266667.0`` — an integral float the ``type: integer`` keyword and every
            # dedicated bound below would then read as the integer it is not.
            parsed = json.loads(
                body_bytes.decode("utf-8"),
                parse_float=decimal.Decimal,
                parse_constant=_reject_nonfinite,
            )
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

    if (
        body is not None
        and direction == "response"
        and status == 200
        and operation.key in _MANIFEST_RESPONSE_OPERATIONS
    ):
        violations.extend(validate_manifest_response(entry, body, body_bytes, media_schemas))

    if (
        body is not None
        and direction == "response"
        and status == 200
        and operation.key in _CROP_BOUND_OPERATIONS
    ):
        violations.extend(validate_derivative_crop(entry, body, clip_dimensions or {}))

    if (
        body is not None
        and direction == "response"
        and status == 200
        and operation.key in _STORED_CLIP_MANIFEST_OPERATIONS
        and isinstance(body.get("manifest"), Mapping)
    ):
        violations.extend(validate_stored_clip_manifest(entry, body))

    context = _HeaderContext(
        location=str(entry["id"]),
        operation=operation,
        direction=direction,
        status=status if isinstance(status, int) else None,
        # A vector that ships no sidecar still owes every header the contract marks
        # required for this operation and status: absence is a finding, not a pass, so
        # the required-name walk runs against an empty map rather than being skipped.
        headers=headers or {},
        request_headers=request_headers or {},
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

    if direction == "response" and request_headers is not None:
        # The request this answer claims to answer is itself a request: the required-
        # header walk and the header rules judge it too, and the range/precondition
        # pairing below reads it as the only statement of what was actually asked. A
        # sidecar that is present but empty is still the request this vector claims
        # it answered — §4 makes the lease, the specifier and the precondition facts
        # about the pair whatever the request happened to omit — so only an absent
        # sidecar keeps silence.
        violations.extend(
            _evaluate_request_sidecar(entry, operation, status, context.headers, request_headers)
        )

    if binary_request:
        # Judged after the header walk, in the direction the contract documents this
        # body: the size defect is the finding and nothing else, exactly as an
        # over-limit manifest is a size defect before its fields are put on trial.
        violations.extend(validate_upload_chunk_body(entry, context.headers, body_bytes))

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
    """Read the fixture's own header map — the one this vector itself puts on the wire."""
    return _load_header_map(root, entry, ".headers.json", exclude=".request.headers.json")


def _load_request_headers(
    root: Path, entry: Mapping[str, Any]
) -> tuple[dict[str, str] | None, list[Violation]]:
    """Read the request sidecar of a response vector, when it declares one.

    A 206 is only checkable against the ``Range`` it answers, and a committed response
    fixture has to carry that request for the pairing to be reviewable at all.
    """
    return _load_header_map(root, entry, ".request.headers.json")


def _load_header_map(
    root: Path,
    entry: Mapping[str, Any],
    suffix: str,
    exclude: str | None = None,
) -> tuple[dict[str, str] | None, list[Violation]]:
    """Read one JSON object of header name/value out of the fixture's file set."""
    for name in entry.get("files", []):
        text = str(name)
        if not text.endswith(suffix) or (exclude is not None and text.endswith(exclude)):
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
    """An error response must be the shared envelope with a code the spec assigns.

    One rejection says more than the envelope: the operation table binds a schema to a
    status of 400 or above when the contract gives that refusal its own body, and the
    body is then checked against that schema. The reported code follows the schema the
    finding came from, so a missing member of a documented response body is
    ``API_SCHEMA`` — the code every other documented response reports — rather than a
    complaint about an envelope this status no longer uses.
    """
    components = document.get("components", {}).get("schemas", {})
    schema_name = operation.response_schemas.get(status) or "Error"
    if schema_name not in components:
        return [
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"components/schemas/{schema_name}",
                f"the contract has no {schema_name} schema for {operation.key} {status}",
            )
        ]
    schema_code = E.ERROR_ENVELOPE_INVALID if schema_name == "Error" else E.API_SCHEMA
    schema = resolve_refs(components[schema_name], root=document)
    found: list[Violation] = []
    for property_name, keyword, message in schema_error_report(schema, body):
        found.append(
            Violation(
                schema_code,
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
    if context.direction == "response" and context.status == 204:
        # RFC 9110 §8.6 forbids the field itself on a 204, whatever its value: the
        # separate body-presence check only proves no bytes are present, so the
        # header is refused here before ``_as_int`` ever reads it. A 204 answer
        # that names a length — even a correct-looking ``0`` — teaches clients to
        # expect a body the status can never carry.
        return [
            Violation(
                E.CONTENT_LENGTH_MISMATCH,
                location,
                "a 204 answer may not carry the header at all (RFC 9110 §8.6), "
                f"whatever its value ({value!r})",
            )
        ]
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
    mismatch = _requested_span_mismatch(context, first, last, total)
    if mismatch is not None:
        return [Violation(E.CONTENT_RANGE_INVALID, location, f"{value!r}: {mismatch}")]
    return []


def _requested_span_mismatch(
    context: _HeaderContext, first: int, last: int, total: int
) -> str | None:
    """Why this granted interval is not the one the request asked for, or ``None``.

    Syntax, bounds and ``Content-Length`` agreement say that a ``Content-Range`` is a
    well-formed statement about a file; none of them says it is a statement about the
    range the client asked for. A 206 of ``bytes 0-99/1000`` for ``Range: bytes=999-``
    is internally consistent and hands over the wrong hundred bytes, which is the
    failure this returns.

    Silence is deliberate wherever the answer cannot be judged: a status that is not a
    grant (a 401, 404, 412 or 416 never reached range serving, and may echo the
    specifier it was given), no request context at all, and a specifier this contract
    never supports (its own row in the table above already owns that defect).

    The request is read from the sidecar first and then from the vector's own header
    map, because a committed response vector has always been able to name the `Range` it
    answers beside the answer itself: the sidecar is the precise form and the echo is the
    historical one, and both are the request this answer claims to be serving.
    """
    if context.direction != "response" or context.status not in (200, 206):
        return None
    specifier = _lookup_header(context.request_headers, "Range") or _lookup_header(
        context.headers, "Range"
    )
    if specifier is None:
        return None
    requested = _SINGLE_RANGE.match(specifier)
    if requested is None:
        return None
    start = int(requested.group(1))
    end = _as_int(requested.group(2)) if requested.group(2) else None
    if end is not None and end < start:
        # Bytes past their own end: `_rule_range` owns that specifier, including the
        # 206-instead-of-416 misuse, and comparing a grant against a request that asks
        # for an impossible interval would report the same act twice under two codes.
        # A start at or beyond the end is deliberately *not* silenced here — a 206 for
        # it is a grant of something nobody asked for, and nothing else reports it.
        return None
    expected_last = total - 1 if end is None else min(end, total - 1)
    if first == start and last == expected_last:
        return None
    wanted = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
    return (
        f"the request asked for {wanted!r}, which grants bytes {start}-{expected_last}/{total}, "
        f"not {first}-{last}/{total}"
    )


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
#: * **The request a response answers** (its ``.request.headers.json`` sidecar) is read
#:   by these same two rows and by nothing else: :func:`_evaluate_request_sidecar`
#:   hands the sidecar to the request row whatever the answer turned out to be, because
#:   a gate is a fact about the answer. The one exemption is the 416, whose subject *is*
#:   this specifier — refusing a form §4 refuses is the contract working, so the refused
#:   form may not be named a second defect there. Only the forms a 416 may honestly
#:   refuse are excused: an ordered specifier its own ``bytes */<total>`` shows the file
#:   holds is refused as a sidecar defect (see ``_evaluate_request_sidecar``), and an
#:   answer that states no total is left to this rule alone — the deliberate asymmetry
#:   is that a 416 owes a ``Content-Range`` this contract does not require, so the
#:   sidecar path has nothing to check the specifier against.


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
    # A HEAD answers with both headers and the pair has to agree: bytes committed past
    # the declared total describe a file the upload never declared, which is exactly the
    # state a client must not be able to resume from. Equality is a completed upload.
    declared = _lookup_header(context.headers, "Upload-Length")
    if declared is not None:
        length = _as_int(declared)
        if length is not None and number > length:
            return [
                Violation(
                    E.UPLOAD_OFFSET_INVALID,
                    f"{context.location}: {name}",
                    f"offset {number} is past the declared length {length}",
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


def _rule_www_authenticate(context: _HeaderContext, name: str, value: str) -> list[Violation]:
    if _WWW_AUTHENTICATE.match(value) is None:
        return [
            Violation(
                E.HEADER_INVALID,
                f"{context.location}: {name}",
                f"{value!r} is not `Bearer` or `Bearer realm=\"<realm>\"` (RFC 9110 §15.5.2)",
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
    "www-authenticate": _rule_www_authenticate,
    "x-clip-lease": _rule_lease,
    "idempotency-key": _rule_idempotency_key,
    "cursor": _rule_cursor,
    "limit": _rule_limit,
    "x-upload-name": _rule_upload_name,
    "retry-after": _rule_retry_after,
    "content-type": _rule_content_type,
    "cache-control": _rule_cache_control,
}


def _evaluate_request_sidecar(
    entry: Mapping[str, Any],
    operation: Operation,
    status: Any,
    response_headers: Mapping[str, str],
    request_headers: Mapping[str, str],
) -> list[Violation]:
    """Judge a response vector's request sidecar as the request it claims to be.

    A response sidecar used to be read for one thing: the specifier
    :func:`_requested_span_mismatch` compares a grant against. That left the sidecar a
    free pass — a ``206`` could answer a suffix range, a ``200`` could answer any
    ``Range`` at all, and a resume could carry an ``If-Match`` that is not the ``ETag``
    it ships beside, because nothing on the request side of the pairing was ever walked
    (interfaces.md §4, RFC 9110 §13.2.2: the preconditions and the range rules are
    properties of the *pair*, and a vector that carries its request is asserting that
    pair). The judgment here is exactly the judgment any request of this operation
    meets — the required-request-header walk plus every :data:`HEADER_RULES` entry in
    the request direction, including the unknown-name refusal and the request row of the
    ``Range`` decision table — with two precedence rules so the validator never demands
    the refusal of the very defect:

    * the sidecar's ``Range`` *specifier* findings are silenced when ``status == 416``,
      the one answer whose subject is that specifier: refusing a suffix or multipart
      request with 416 is the contract working, and a second code for the same form would
      fail the device §4 requires. Every other status — the 401/404/409/410/412 gates
      included — is silent about the range only *as an answer*; the request itself is
      still a request, and a form §4 never supports is outside the contract whatever the
      device eventually replies;
    * the ``Range``-against-the-answer pairing (a full 200 to a supported specifier, and
      ``IF_MATCH_ETAG_DISAGREE``) belongs to a grant (200/206): 412 is the *required*
      answer to a mismatched precondition, and a gated refusal is not a grant of anything.

    Syntax rules (``If-Match``, the lease id, unknown names) are never excused: they
    judge what the request itself says, whatever the answer turned out to be. A vector
    without a sidecar keeps every existing behaviour, because an absent request is
    silence, not a pass — while a sidecar that is *present but empty* is still the
    request this vector claims to have answered, and owes every header §4 requires of
    one. Three pairing rules complete the answer's side of the pair: a ``416`` may refuse
    only a specifier its own ``Content-Range: bytes */<total>`` proves the file cannot
    serve and that some request actually sent, a ``206`` grants bytes only for a
    specifier some request actually sent — §4's "No Range returns 200" reads both ways —
    and an upload ``204`` acknowledges a chunk only by the offset that chunk's append
    actually advanced to (§8 step 2).
    """
    location = f"{entry['id']}: request sidecar"
    request_context = _HeaderContext(
        location=location,
        operation=operation,
        direction="request",
        status=None,
        headers=dict(request_headers),
    )
    found: list[Violation] = []
    for name in operation.required_request_headers:
        if _lookup_header(request_headers, name) is None:
            found.append(
                Violation(
                    E.HEADER_MISSING,
                    f"{location}: {name}",
                    f"{operation.key} requires this header on the request it answers",
                )
            )
    grants = isinstance(status, int) and status in (200, 206)
    # A refusal *about* the range is the one answer whose own subject the specifier is:
    # at a 416 the request's form is what the device is refusing, so judging it again as a
    # violation would flag the vector for the defect the 416 exists to name (§4, RFC 9110
    # §15.5.17). Every other status, including the 401/404/409/410/412 gates, is silent
    # about the range *as an answer* — and a request is judged on its own, exactly as the
    # request row of the decision table above says, so a gated answer does not excuse a
    # specifier no request of this contract may send. The 416's excuse reaches only the
    # forms it legitimately refuses — those the anchored ``_SINGLE_RANGE`` will not parse
    # at all, and a supported spelling whose ordering no file can satisfy — never a
    # well-formed ordered request, whose refusal the satisfiability rule below judges.
    refuses_the_range = isinstance(status, int) and status == 416
    specifier = _lookup_header(request_headers, "Range")
    excused_at_416 = False
    ordered_specifier: tuple[int, int | None] | None = None
    if refuses_the_range and specifier is not None:
        parsed = _SINGLE_RANGE.match(specifier)
        if parsed is None:
            excused_at_416 = True  # multipart, suffix, hyphenless, junk: the 416 refuses it
        else:
            start = int(parsed.group(1))
            end = _as_int(parsed.group(2)) if parsed.group(2) else None
            if end is not None and end < start:
                excused_at_416 = True  # bytes past their own end: the request row's form
            else:
                ordered_specifier = (start, end)
    for name, value in request_headers.items():
        if name.lower() == "range" and refuses_the_range and excused_at_416:
            continue  # the 416 is the answer about this very refused form
        rule = HEADER_RULES.get(name.lower())
        if rule is None:
            found.append(
                Violation(
                    E.HEADER_INVALID,
                    f"{location}: {name}",
                    "no documented header of this name exists for these contracts",
                )
            )
            continue
        found.extend(rule(request_context, name, value))
    if specifier is not None and status == 200:
        match = _SINGLE_RANGE.match(specifier)
        start = int(match.group(1)) if match is not None else 0
        end = _as_int(match.group(2)) if match is not None and match.group(2) else None
        # An unsupported form, and an interval that asks for bytes beyond their own end,
        # are the request row's findings already; comparing a full 200 against a request
        # no device can serve would name the same act twice.
        if match is not None and not (end is not None and end < start):
            found.append(
                Violation(
                    E.RANGE_MULTI_NOT_ALLOWED,
                    f"{location}: Range",
                    f"{specifier!r} is a range request, and §4's \"No Range returns 200\" "
                    f"reads both ways: the answer is 206 or a gated refusal, never the "
                    f"whole file, so a full 200 to {start}-"
                    f"{end if end is not None else ''} is the wrong grant",
                )
            )
    if ordered_specifier is not None:
        # RFC 9110 §15.5.17: the 416 refuses a range the file cannot satisfy. Its
        # ``Content-Range: bytes */<total>`` names the file's size, so a refusal of a
        # supported, ordered specifier that *fits* inside that total is a refusal the
        # answer's own proof contradicts — bytes the file holds, refused as though it
        # did not hold them. A specified end past the representation's end is clamped
        # to it (§14.1.2), not made unsatisfiable: whatever ``end`` says, a start the
        # file holds names a window the 206 path already grants as
        # ``start..file_bytes-1``, so the 416's own total proves this refusal wrong.
        # Without a `*/<total>` there is nothing to check against, and the header's own
        # rules own its absence or shape.
        start, end = ordered_specifier
        declared = _lookup_header(response_headers, "Content-Range")
        total = _STAR_CONTENT_RANGE.match(declared) if declared is not None else None
        if total is not None:
            file_bytes = int(total.group(1))
            if start < file_bytes:
                found.append(
                    Violation(
                        E.CONTENT_RANGE_INVALID,
                        f"{location}: Range",
                        f"{specifier!r} starts at a byte the {file_bytes}-byte file holds, and "
                        f"RFC 9110 §14.1.2 clamps any end past it: a 416 refuses only a range "
                        f"its bytes */{file_bytes} proves unsatisfiable, and this specifier's "
                        f"start is inside it",
                    )
                )
    if isinstance(status, int) and status in (206, 416) and specifier is None:
        # A 206 is a grant of a window and a 416 is a refusal of one: both answers are
        # about bytes some request has to have asked for. This function runs only when a
        # sidecar is present, and the sidecar is then the *only* statement of the
        # question — an echo of `Range` in the answer's own header map is the historical
        # spelling for vectors that carry no sidecar at all, and it can never conjure the
        # request the sidecar itself omits. A grant beside a request that names no range
        # grants bytes no range request justified; a refusal beside one refuses a range no
        # request asked for, and §4's "No Range returns 200" reads both ways (RFC 9110
        # §15.5.17 refuses *a range*; a whole-file request ends in 200, never 416).
        found.append(
            Violation(
                E.CONTENT_RANGE_INVALID,
                f"{location}: Range",
                f"this {status} is an answer about a byte window, but neither the request "
                f"it answers nor the answer itself names a Range; §4's \"No Range returns "
                f"200\" reads both ways: a 206 grants bytes no range request justified, "
                f"and a 416 refuses a range no request asked for",
            )
        )
    if (
        isinstance(status, int)
        and status == 204
        and operation.key == "backend.patch_upload_file"
    ):
        # interfaces.md §8 step 2: the 204 after an appended chunk carries the *new*
        # authoritative Upload-Offset — an accepted chunk of ``Content-Length`` bytes at
        # request offset N commits through N + length, so with the request sidecar
        # present and its arithmetic headers readable, the answer's offset has exactly
        # one legal value. A 204 still naming the request's own offset acknowledged bytes
        # it never committed, and a client resuming from it resends them. The check stays
        # silent wherever another rule owns the pair's defect first: an absent sidecar
        # header is the required-header walk's, a malformed one is _rule_upload_offset /
        # _rule_content_length / _rule_upload_checksum's, and an absent or malformed
        # response offset is HEADER_MISSING / UPLOAD_OFFSET_INVALID's. A 409 pair is a
        # different answer: there the response offset is the server's authoritative
        # committed offset and legitimately not request + chunk.
        request_offset = _lookup_header(request_headers, "Upload-Offset")
        chunk_length = _lookup_header(request_headers, "Content-Length")
        request_checksum = _lookup_header(request_headers, "Upload-Checksum")
        answer_offset = _lookup_header(response_headers, "Upload-Offset")
        if (
            request_offset is not None
            and chunk_length is not None
            and request_checksum is not None
            and answer_offset is not None
            and not _rule_upload_offset(request_context, "Upload-Offset", request_offset)
            and not _rule_content_length(request_context, "Content-Length", chunk_length)
            and not _rule_upload_checksum(request_context, "Upload-Checksum", request_checksum)
        ):
            start = _as_int(request_offset)
            length = _as_int(chunk_length)
            committed = _as_int(answer_offset)
            if committed is not None and 0 <= committed <= UINT53_MAX and committed != start + length:
                found.append(
                    Violation(
                        E.UPLOAD_OFFSET_STALE,
                        f"{location}: Upload-Offset",
                        f"this 204 acknowledges the chunk but names offset {committed}, "
                        f"not {start} + {length} = {start + length}: the accepted "
                        f"{length}-byte append at offset {start} ends where the answer "
                        f"does not say it ends (interfaces.md §8 step 2), and a client "
                        f"resuming from this acknowledgement resends committed bytes",
                    )
                )
    if_match = _lookup_header(request_headers, "If-Match")
    if if_match is not None and grants:
        etag = _lookup_header(response_headers, "ETag")
        if etag is None or etag != if_match:
            found.append(
                Violation(
                    E.IF_MATCH_ETAG_DISAGREE,
                    f"{location}: If-Match",
                    f"{if_match!r} is not the {etag!r} this answer ships; a resume "
                    f"requires the original ETag, and the required answer to a mismatch "
                    f"is 412 CONTENT_CHANGED",
                )
            )
    return found


# RFC 9110 §8.6: an HTTP integer field value is 1*DIGIT — ASCII digits, no sign,
# no separators, no whitespace, no lookalike codepoints. Bare ``int()`` accepted
# "+512", "51_2", fullwidth digits and " 512" alike, so the gate below refused
# none of them; this anchor is what every caller of ``_as_int`` shares.
_HTTP_INTEGER = re.compile(r"\A[0-9]+\Z")


def _as_int(value: str) -> int | None:
    if not isinstance(value, str) or _HTTP_INTEGER.fullmatch(value) is None:
        return None
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
        # The exact-number rule again (see :func:`_load_body`): this decoded manifest
        # is the same document the card carries, and an upload must not be able to
        # bind a manifest whose duration rounds into a legal integer only on the way
        # through a binary float.
        manifest = json.loads(decoded.decode("utf-8"), parse_float=decimal.Decimal)
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
        if (property_name, keyword) in MANIFEST_WIRE_SUPPRESSED:
            # The mirror states the shape; the rules below name this defect themselves, and
            # a second code for one defect would make the vector's declared set a matter of
            # luck rather than a contract. The set is the narrow one: a bound this path does
            # not check has to stay reported by the keyword that does.
            continue
        found.append(
            Violation(
                E.MANIFEST_DECODED_SCHEMA,
                f"{location}: manifest_base64url{f' at {property_name}' if property_name else ''}",
                f"{keyword}: {message}",
            )
        )
    # The mirror says what a manifest looks like; these are the rules a manifest has to
    # obey, and a manifest that breaks them over the wire is the same defect as one that
    # breaks them on the card. Without this call an upload could bind a manifest naming
    # a clip whose boot prefix contradicts its own boot_id, or a clock that is both
    # unknown and timestamped, and the media validator would never be told.
    if isinstance(manifest, dict):
        found.extend(
            validate_manifest_fields(manifest, location_prefix=f"{location}: manifest_base64url")
        )
    return found


def validate_manifest_response(
    entry: Mapping[str, Any],
    body: Mapping[str, Any],
    body_bytes: bytes | None,
    media_schemas: Mapping[str, Mapping[str, Any]],
) -> list[Violation]:
    """Check a ``GET /clips/{clip_id}/manifest`` answer with the media contract's own rules.

    The 200 validates against the contract's ``Manifest`` mirror, which states the shape
    and nothing more; the field rules — the boot prefix, the close reason, the null-ness
    of an unknown clock — live in :mod:`tools.contracts.media_validate`, and a client that
    trusts this answer trusts exactly those facts.

    The 16,384-byte bound is measured on the bytes as committed, before those field rules
    run: a document over the bound is the size defect and nothing else, and reporting a
    dozen field members of a manifest that should never have been parsed would bury the one
    finding about it. (The bytes were of course already read to be decoded at all — this
    gate orders the findings, it does not save the read.)
    """
    location = str(entry["id"])
    if body_bytes is None:
        return [
            Violation(
                E.FIXTURE_FILE_MISSING,
                location,
                "a manifest response has no committed bytes to measure against the bound",
            )
        ]
    if len(body_bytes) > MAX_MANIFEST_BYTES:
        return [
            Violation(
                E.MANIFEST_DECODED_TOO_LARGE,
                location,
                f"{len(body_bytes)} bytes exceeds the {MAX_MANIFEST_BYTES}-byte manifest bound",
            )
        ]
    if "manifest" not in media_schemas:
        # No usable media schema means rules nobody was able to run, which is a finding
        # about the run rather than a pass for the vector.
        return [
            Violation(
                E.SCHEMA_DOCUMENT_INVALID,
                location,
                "no usable media manifest schema was loaded, so the manifest is unchecked",
            )
        ]
    return validate_manifest_fields(body, location_prefix=f"{location}: manifest")


def validate_stored_clip_manifest(
    entry: Mapping[str, Any], body: Mapping[str, Any]
) -> list[Violation]:
    """A ``StoredClip`` may not carry a manifest that contradicts the record around it.

    ``GET /clips/{clip_id}`` hands a client the clip's completion manifest as a member,
    and until now only the OpenAPI mirror judged it: a nested record was free to name a
    boot prefix that disagrees with its own ``boot_id``, a clock that is both unknown
    and timestamped, or a device the enclosing record does not belong to. The mirror
    states the shape and nothing more, so the media contract's own field rules run here
    too — the same six rules the card and the manifest route are judged by — and the
    identity the envelope and its manifest share has to be stated once, not twice with
    two answers. A disagreement of ``device_id`` or ``clip_id`` is a fact no schema
    keyword can state about a member of a different document (the same precedent as
    :func:`validate_derivative_crop`), so each is one ``API_SCHEMA``; an absent member
    stays the schema's own finding.
    """
    location = str(entry["id"])
    manifest = body.get("manifest")
    if not isinstance(manifest, Mapping):
        return []  # the mirror reports a record without its manifest
    found = validate_manifest_fields(manifest, location_prefix=f"{location}: manifest")
    for member in ("device_id", "clip_id"):
        outer, inner = body.get(member), manifest.get(member)
        if isinstance(outer, str) and isinstance(inner, str) and outer != inner:
            found.append(
                Violation(
                    E.API_SCHEMA,
                    f"{location}: manifest.{member}",
                    f"the stored {member} is {outer!r} but its own manifest says "
                    f"{inner!r}; one record cannot name two {member}s",
                )
            )
    return found


def validate_upload_chunk_body(
    entry: Mapping[str, Any],
    headers: Mapping[str, str],
    body_bytes: bytes | None,
) -> list[Violation]:
    """The chunk of an upload ``PATCH`` is judged as bytes, never as JSON.

    ``backend-v1.yaml`` documents this request body as ``application/octet-stream`` of
    1-1,048,576 bytes, so the bytes are the wire form: this rule reads them as what
    they are and compares them against exactly the facts the headers declare. The
    ordering is a precedence, matching the over-limit-record gate in
    :mod:`tools.contracts.media_validate`: a size defect is *the* finding about the
    body, and nothing else speaks until it is cleared.

    * no chunk committed while ``Content-Length`` still declares an in-range chunk size
      means 0 bytes are present for it — below the 1-byte floor, ``CHUNK_SIZE_INVALID``
      alone (a declared 0 or an over-limit declaration is already the header rule's
      single ``CHUNK_SIZE_INVALID``, and a named-but-unreadable file its own
      ``FIXTURE_FILE_MISSING``);
    * committed bytes outside ``1..MAX_CHUNK_BYTES`` are ``CHUNK_SIZE_INVALID`` alone —
      and when ``Content-Length`` declares an equally impossible size, the header rule
      says it once and this rule keeps silent, so one oversized chunk is one finding;
    * ``Content-Length``, when it declares an in-range chunk size, disagreeing with the
      committed length is ``CONTENT_LENGTH_MISMATCH``; a declaration outside the chunk
      range is the header rule's ``CHUNK_SIZE_INVALID`` alone, whichever side of the pair
      the bad number was written on;
    * a well-formed ``Upload-Checksum`` that is not ``sha256`` of these bytes is
      ``CHUNK_HASH_MISMATCH`` — the 422 ``INTEGRITY_FAILURE`` refusal this contract
      owes the client. A malformed checksum is left to ``UPLOAD_CHECKSUM_SYNTAX`` and
      an absent one to the required-header walk: each defect is named by the one rule
      that measures it.
    """
    location = str(entry["id"])
    declared_raw = _lookup_header(headers, "Content-Length")
    declared = _as_int(declared_raw) if declared_raw is not None else None
    if body_bytes is None:
        named = any(
            not str(name).endswith(".headers.json") for name in entry.get("files", [])
        )
        if named:
            return []  # the file was named and could not be read: that is the finding
        if declared is not None and MIN_CHUNK_BYTES <= declared <= MAX_CHUNK_BYTES:
            return [
                Violation(
                    E.CHUNK_SIZE_INVALID,
                    f"{location}: body",
                    f"the index names no chunk file, so 0 bytes are present for the "
                    f"declared {declared}-byte chunk, and no chunk is smaller than "
                    f"{MIN_CHUNK_BYTES} byte",
                )
            ]
        return []
    declared_out_of_range = declared is not None and not (
        MIN_CHUNK_BYTES <= declared <= MAX_CHUNK_BYTES
    )
    if not MIN_CHUNK_BYTES <= len(body_bytes) <= MAX_CHUNK_BYTES:
        if declared_out_of_range:
            return []  # both sides name the same oversized chunk: the header says it once
        return [
            Violation(
                E.CHUNK_SIZE_INVALID,
                f"{location}: body",
                f"{len(body_bytes)} committed bytes are outside the "
                f"{MIN_CHUNK_BYTES}-{MAX_CHUNK_BYTES} byte chunk range",
            )
        ]
    if declared_out_of_range:
        return []  # a declaration outside the chunk range is the header rule's one finding
    if declared is not None and declared != len(body_bytes):
        return [
            Violation(
                E.CONTENT_LENGTH_MISMATCH,
                f"{location}: body",
                f"Content-Length declares {declared} bytes, the committed chunk is "
                f"{len(body_bytes)}",
            )
        ]
    checksum = _lookup_header(headers, "Upload-Checksum")
    if checksum is not None and _UPLOAD_CHECKSUM.match(checksum) is not None:
        digest = hashlib.sha256(body_bytes).hexdigest()
        if digest != checksum[len("sha256 "):]:
            return [
                Violation(
                    E.CHUNK_HASH_MISMATCH,
                    f"{location}: Upload-Checksum",
                    f"declares {checksum!r} but these {len(body_bytes)} bytes hash to "
                    f"sha256 {digest}; the answer to a chunk that does not match its "
                    f"checksum is 422 INTEGRITY_FAILURE",
                )
            ]
    return []


def validate_derivative_crop(
    entry: Mapping[str, Any],
    body: Mapping[str, Any],
    clip_dimensions: Mapping[tuple[str, str], tuple[int, int]],
) -> list[Violation]:
    """A recorded crop has to lie inside the source the record names.

    ``CropRegion`` states a rectangle and the two bounds JSON Schema can state for it;
    that a crop is measured *in the source's pixels* is a statement about a pair of
    documents, since the encoder's window onto a 64×64 baseline cannot start at y=120. The
    source size comes from the committed manifest of the very clip this record cites —
    and the citation is the ``(device_id, clip_id)`` pair, because ``clip_id`` is scoped
    by ``device_id`` in backend requests: one id may name two differently-sized segments
    on two devices, and measuring either record's crop against the other's pixels would
    certify an encode of impossible geometry. A clip pair nobody shipped is silence:
    this validator has no size for it and must not conjure one.
    """
    device_id = body.get("device_id")
    clip_id = body.get("clip_id")
    crop = body.get("crop")
    if (
        not isinstance(device_id, str)
        or not isinstance(clip_id, str)
        or not isinstance(crop, Mapping)
    ):
        return []  # the bound schema reports a record without a device, an id or a crop
    size = clip_dimensions.get((device_id, clip_id))
    if size is None:
        return []
    width, height = size
    found: list[Violation] = []
    for axis, extent_key, limit in (("x", "width", width), ("y", "height", height)):
        offset, extent = crop.get(axis), crop.get(extent_key)
        # The same predicate the ``type: integer`` keyword of ``CropRegion`` judges with
        # (:func:`tools.contracts.schema_docs.is_json_integer`), not a narrower one:
        # ``120``, ``120.0`` and ``1.2e2`` are the same integer to the schema, so a crop
        # that slips past the bounds check on its spelling is a crop the schema called
        # an integer and this check pretended not to see. The ``int()`` below is safe
        # precisely because the predicate accepted the notation.
        if not is_json_integer(None, offset) or not is_json_integer(None, extent):
            continue  # a rectangle the schema cannot read is the schema's to report
        offset, extent = int(offset), int(extent)
        if offset + extent > limit:
            found.append(
                Violation(
                    E.API_SCHEMA,
                    f"{entry['id']}: derivative.crop.{axis}",
                    f"crop {axis}={offset} with {extent_key}={extent} reaches "
                    f"{offset + extent}, past the {limit}-pixel edge of source "
                    f"{device_id}/{clip_id}",
                )
            )
    return found
