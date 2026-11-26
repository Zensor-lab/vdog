"""Structural validation of the contract documents themselves.

The OpenAPI files are the published contract; this module is the independent
checklist derived from ``docs/specs/interfaces.md`` and ``docs/specs/media-format.md``
that keeps them from quietly weakening. It answers questions a schema validator
cannot: is every documented operation present, does each one declare the statuses
the spec assigns, is the error envelope really one reusable schema, is the manifest
component still identical to ``contracts/media-v1/manifest.schema.json``, and is the
OTA envelope still explicitly deferred instead of guessed?
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, Mapping

from . import errors as E
from .api_model import Operation, operation_for
from .bounds import DOCUMENTED_ERROR_STATUSES
from .errors import Violation
from .schema_docs import canonical, check_local_refs, check_metaschema, resolve_refs

#: Operations the spec leaves unauthenticated: pairing happens before a token
#: exists, and the two health probes are documented as "minimal health only".
UNAUTHENTICATED_OPERATIONS: frozenset[str] = frozenset(
    {"device.pair", "backend.get_health_live", "backend.get_health_ready"}
)

_EXPECTED_SERVERS: Mapping[str, str] = {
    "device": "https://vdog.local/api/v1",
    "backend": "https://backend.local/api/v1",
}

_MEDIA_SCHEMA_FILES: Mapping[str, str] = {
    "frame": "frame-record.schema.json",
    "manifest": "manifest.schema.json",
    "active": "active-record.schema.json",
}

#: ``$defs`` that the manifest and the active record must spell identically: the
#: active record "uses the manifest field rules" (media-format.md §5).
_SHARED_DEFS: tuple[str, ...] = ("device_id", "boot_id", "clip_id", "profile", "clock")

_EXPECTED_HEADER_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "AcceptRanges": {"type": "string", "const": "bytes"},
    "ETagSha256": {
        "type": "string",
        "pattern": '^[0-9a-f]{64}$',
        "_quoted": True,
        # The quoted digest is exactly 66 characters, and the length pair is what a
        # validator whose `pattern` is a substring search still has to obey.
        "minLength": 66,
        "maxLength": 66,
    },
    "ContentRange": {"type": "string", "pattern": "^bytes [0-9]+-[0-9]+/[0-9]+$"},
    "ContentRangeUnsatisfied": {"type": "string", "pattern": "^bytes \\*/[0-9]+$"},
    "WwwAuthenticate": {
        "type": "string",
        "pattern": '^Bearer( realm="[^"]{1,100}")?$'
    },
}

OTA_DEFERRAL_PACKAGE: str = "2.10"


def load_media_schemas(media_dir: Path) -> tuple[dict[str, Mapping[str, Any]], list[Violation]]:
    """Parse the three media schemas and assert they are valid 2020-12 documents."""
    from .schema_docs import load_json

    schemas: dict[str, Mapping[str, Any]] = {}
    found: list[Violation] = []
    for name, file_name in _MEDIA_SCHEMA_FILES.items():
        path = media_dir / file_name
        if not path.is_file():
            found.append(Violation(E.SPEC_STRUCTURE_MISSING, str(path), "schema file absent"))
            continue
        try:
            document = load_json(path)
        except (ValueError, UnicodeDecodeError) as error:
            found.append(Violation(E.SCHEMA_DOCUMENT_INVALID, str(path), str(error)))
            continue
        if not isinstance(document, Mapping):
            # A JSON document whose root is not an object — `[]`, `null`, `true`, a
            # number or a string — is not a schema document at all. Some of them
            # survive the metaschema (an array of schemas is a valid 2020-12 schema,
            # and so is a boolean), so the first thing that notices the difference
            # would otherwise be `.get` below or `iter_errors` far later, raising
            # `AttributeError` out of the CLI as exit 2 "validator internal error".
            # Refusing here also keeps the document out of `schemas`, which is what
            # makes the vectors that use it report "no usable schema" honestly.
            found.append(
                Violation(
                    E.SCHEMA_DOCUMENT_INVALID,
                    str(path),
                    f"root is {type(document).__name__}, not a JSON object",
                )
            )
            continue
        failure = check_metaschema(document)
        if failure is None:
            # Valid keywords are not enough: a typo'd local pointer is a valid schema
            # that explodes only when it is used, so it is refused here too.
            failure = check_local_refs(document)
        if failure is not None:
            found.append(Violation(E.SCHEMA_DOCUMENT_INVALID, str(path), failure))
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            found.append(
                Violation(
                    E.SCHEMA_DOCUMENT_INVALID,
                    str(path),
                    f"$schema is {document.get('$schema')!r}, not draft 2020-12",
                )
            )
        if document.get("additionalProperties") is not False:
            found.append(
                Violation(
                    E.SCHEMA_DOCUMENT_INVALID,
                    str(path),
                    "write-side objects must reject unknown fields",
                )
            )
        if failure is not None:
            # A document that is not a schema cannot validate anything: handing it to
            # ``iter_errors`` anyway raises from inside the keyword implementation, so a
            # bad contract file would surface as a CLI exit 2 "validator internal error"
            # rather than the exit 1 finding it is. Every vector of that kind is then
            # reported as having no usable schema, which is the honest verdict.
            continue
        schemas[name] = document
    if {"manifest", "active"} <= set(schemas):
        manifest_defs = schemas["manifest"].get("$defs", {})
        active_defs = schemas["active"].get("$defs", {})
        for shared in _SHARED_DEFS:
            if canonical(manifest_defs.get(shared)) != canonical(active_defs.get(shared)):
                found.append(
                    Violation(
                        E.SPEC_COMPONENT_DRIFT,
                        f"contracts/media-v1/$defs/{shared}",
                        "the manifest and active record must use identical field rules",
                    )
                )
    return schemas, found


def check_openapi(contract: str, document: Mapping[str, Any]) -> list[Violation]:
    """Assert one OpenAPI document still carries every documented operation rule."""
    found: list[Violation] = []
    if document.get("openapi") != "3.1.0":
        found.append(
            Violation(E.SPEC_STRUCTURE_MISSING, f"{contract}-v1.yaml", f"openapi {document.get('openapi')!r} is not 3.1.0")
        )
    servers = document.get("servers", [])
    expected_server = _EXPECTED_SERVERS[contract]
    if not servers or servers[0].get("url") != expected_server:
        found.append(
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"{contract}-v1.yaml servers",
                f"expected {expected_server!r}",
            )
        )
    components = document.get("components", {})
    if "Error" not in components.get("schemas", {}):
        found.append(
            Violation(E.SPEC_STRUCTURE_MISSING, "components/schemas/Error", "reusable envelope missing")
        )
    for operation in operation_for(contract).values():
        found.extend(_check_operation(contract, document, operation))
        found.extend(_check_status_ceiling(contract, operation))
        if operation.key not in UNAUTHENTICATED_OPERATIONS and not _requires_bearer(document, operation):
            found.append(
                Violation(
                    E.SPEC_SECURITY_MISSING,
                    f"{operation.method} {operation.path}",
                    "requires Authorization: Bearer after pinned TLS",
                )
            )
    return found


def _check_status_ceiling(contract: str, operation: Operation) -> list[Violation]:
    """No operation may document a refusal outside the set interfaces.md assigns.

    ``check_openapi`` compares the document against the operation table, so a status
    added to *both* would otherwise agree with itself. This is the ceiling that set
    has to stay inside: the documented 2xx codes of the operation plus
    ``DOCUMENTED_ERROR_STATUSES`` (interfaces.md §1, and 412 which the file-conditional
    section assigns explicitly).
    """
    allowed = set(operation.success_statuses) | set(DOCUMENTED_ERROR_STATUSES)
    found: list[Violation] = []
    for status in operation.documented_statuses:
        if status not in allowed:
            found.append(
                Violation(
                    E.SPEC_STATUS_NOT_ALLOWED,
                    f"{contract}-v1 {operation.key} {status}",
                    "the documented status set is 2xx plus "
                    + ", ".join(str(code) for code in sorted(DOCUMENTED_ERROR_STATUSES)),
                )
            )
    return found


def check_shared_error_envelope(documents: Mapping[str, Mapping[str, Any]]) -> list[Violation]:
    """The device and backend error envelopes must be the same reusable schema."""
    if set(documents) != {"device", "backend"}:
        return [Violation(E.SPEC_STRUCTURE_MISSING, "error envelope", "both contracts are required")]
    rendered = {}
    for contract, document in documents.items():
        schemas = document.get("components", {}).get("schemas", {})
        if "Error" not in schemas:
            return [Violation(E.SPEC_STRUCTURE_MISSING, f"{contract}-v1 Error", "missing")]
        rendered[contract] = canonical(resolve_refs(schemas["Error"], root=document))
    if rendered["device"] != rendered["backend"]:
        return [
            Violation(
                E.SPEC_COMPONENT_DRIFT,
                "components/schemas/Error",
                "device and backend must carry one identical reusable envelope",
            )
        ]
    return []


def check_manifest_component(
    documents: Mapping[str, Mapping[str, Any]], manifest_schema: Mapping[str, Any]
) -> list[Violation]:
    """The in-contract ``Manifest`` must still equal the media contract's schema."""
    found: list[Violation] = []
    # Resolve the media schema's own ``$defs`` first: both sides are compared fully
    # inlined, so "#/$defs/boot_id" and its expansion are the same statement.
    base = {key: value for key, value in manifest_schema.items() if key not in {"$schema", "$id"}}
    reference = canonical(
        {key: value for key, value in resolve_refs(base, root=base).items() if key != "$defs"}
    )
    for contract in ("device", "backend"):
        document = documents.get(contract)
        if document is None:  # pragma: no cover - loader reports a missing file first
            continue
        schemas = document.get("components", {}).get("schemas", {})
        if "Manifest" not in schemas:
            found.append(
                Violation(E.SPEC_STRUCTURE_MISSING, f"{contract}-v1 Manifest", "component missing")
            )
            continue
        rendered = canonical(resolve_refs(schemas["Manifest"], root=document))
        if rendered != reference:
            found.append(
                Violation(
                    E.SPEC_COMPONENT_DRIFT,
                    f"{contract}-v1 components/schemas/Manifest",
                    "disagrees with contracts/media-v1/manifest.schema.json",
                )
            )
    return found


def check_headers_contract(document: Mapping[str, Any], contract: str) -> list[Violation]:
    """Shared header component schemas must keep the shapes the spec states."""
    found: list[Violation] = []
    headers = document.get("components", {}).get("headers", {})
    for name, expected in _EXPECTED_HEADER_SCHEMAS.items():
        if name not in headers:
            found.append(Violation(E.SPEC_STRUCTURE_MISSING, f"{contract}-v1 headers/{name}", "missing"))
            continue
        schema = canonical(headers[name].get("schema", {}))
        want = {key: value for key, value in expected.items() if not key.startswith("_")}
        if expected.get("_quoted"):
            want = {**want, "pattern": '^"[0-9a-f]{64}"$'}
        if schema != want:
            found.append(
                Violation(
                    E.SPEC_COMPONENT_DRIFT,
                    f"{contract}-v1 components/headers/{name}",
                    f"schema {schema} is not {want}",
                )
            )
    return found


def check_ota_deferral(document: Mapping[str, Any], contracts_dir: Path) -> list[Violation]:
    """AC-07: no OTA schema ships, and the operation says the encoding is deferred."""
    found: list[Violation] = []
    if (contracts_dir / "ota-v1.json").exists():
        found.append(
            Violation(
                E.OTA_SCHEMA_PRESENT,
                "contracts/ota-v1.json",
                "the OTA envelope is deferred to package 2.10 and must not be guessed",
            )
        )
    ota = document.get("paths", {}).get("/ota", {}).get("post", {})
    if ota.get("x-deferred") != OTA_DEFERRAL_PACKAGE:
        found.append(
            Violation(
                E.OTA_DEFERRAL_MISSING,
                "POST /ota",
                f"expected x-deferred: {OTA_DEFERRAL_PACKAGE!r}",
            )
        )
    body = ota.get("requestBody", {})
    content = body.get("content", {})
    if set(content) != {"application/octet-stream"}:
        found.append(
            Violation(
                E.OTA_DEFERRAL_MISSING,
                "POST /ota requestBody",
                "must be exactly one application/octet-stream content entry",
            )
        )
    else:
        entry = content["application/octet-stream"]
        description = str(body.get("description", ""))
        if "deferred" not in description or OTA_DEFERRAL_PACKAGE not in description:
            found.append(
                Violation(
                    E.OTA_DEFERRAL_MISSING,
                    "POST /ota requestBody description",
                    "must state that the encoding and contracts/ota-v1.json are deferred to 2.10",
                )
            )
        if "$ref" in entry.get("schema", {}):
            found.append(
                Violation(
                    E.OTA_DEFERRAL_MISSING,
                    "POST /ota requestBody schema",
                    "no request schema may be referenced while the encoding is deferred",
                )
            )
    return found


def _check_operation(
    contract: str, document: Mapping[str, Any], operation: Operation
) -> list[Violation]:
    found: list[Violation] = []
    paths = document.get("paths", {})
    if operation.path not in paths:
        return [Violation(E.SPEC_STRUCTURE_MISSING, f"{contract}-v1 paths{operation.path}", "missing")]
    item = paths[operation.path].get(operation.method.lower())
    if item is None:
        return [
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"{contract}-v1 {operation.method} {operation.path}",
                "missing",
            )
        ]
    where = f"{contract}-v1 {operation.method} {operation.path}"
    if item.get("operationId") != operation.operation_id:
        found.append(
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"{where} operationId",
                f"{item.get('operationId')!r} != {operation.operation_id!r}",
            )
        )

    documented = set(operation.documented_statuses)
    responses = item.get("responses", {})
    for status in sorted(documented):
        if str(status) not in responses:
            found.append(Violation(E.SPEC_STATUS_MISSING, f"{where} responses/{status}", "the spec assigns it"))
    for status_key in responses:
        try:
            status = int(status_key)
        except ValueError:
            found.append(Violation(E.SPEC_STATUS_UNDOCUMENTED, f"{where} responses/{status_key}", "not numeric"))
            continue
        if status not in documented:
            found.append(
                Violation(
                    E.SPEC_STATUS_UNDOCUMENTED,
                    f"{where} responses/{status}",
                    f"outside the documented set {sorted(documented)}",
                )
            )

    for status, schema_name in operation.response_schemas.items():
        response, unreadable = _resolved_response(responses, status, document)
        if unreadable is not None:
            found.append(
                Violation(E.SPEC_COMPONENT_DRIFT, f"{where} responses/{status}", unreadable)
            )
            continue
        content, content_issue = _media_type_map(response)
        if content_issue is not None:
            # A declared ``content`` member that is not a media-type map answers
            # neither "no content" nor "which schema does it bind": name the
            # member. The media-type loop may name the identical triple for a
            # listed status; the dedup pass at the end keeps one statement.
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    content_issue,
                )
            )
            continue
        if schema_name is None:
            if not content:
                found.append(Violation(E.SPEC_STRUCTURE_MISSING, f"{where} responses/{status}", "no content"))
            continue
        ref = _json_schema_ref(response, document)
        if ref != f"#/components/schemas/{schema_name}":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status}",
                    f"binds {ref!r} instead of {schema_name}",
                )
            )
    # The fixture validator selects `operation.response_schemas.get(status) or
    # "Error"` for every documented status ≥400 (api_validate.py:631): a refusal
    # the table does not bind a dedicated schema to answers with the shared
    # ``Error`` envelope, so the document has to publish exactly that body. The
    # binding loop above walks only the statuses the table names, so without
    # this loop an error status could drop its body entirely — or publish the
    # operation's own 200 schema — and the checker would certify it. Statuses
    # the table binds (the settings 409 with its SettingsRevisionConflictResponse
    # among them) keep the comparison above, and this loop speaks only for the
    # rest. The binding read is taken from the shallow alias-chained node on
    # purpose: the full read of a `$ref` response inlines the shared component
    # and its schema `$ref` is gone, so the binding question could no longer be
    # asked of it — the same reference the fixture side would follow.
    for status in operation.error_codes:
        if status < 400 or status in operation.response_schemas:
            continue
        _, unreadable = _resolved_response(responses, status, document)
        if unreadable is not None:
            # The all-response scan below owns that SPEC_COMPONENT_DRIFT.
            continue
        response = _alias_chained_response(responses.get(str(status), {}), document)
        if response is None:
            continue  # likewise: the scan names the hop this chain could not follow
        content, content_issue = _media_type_map(response)
        if content_issue is not None:
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    content_issue,
                )
            )
            continue
        if not content:
            if not operation.is_head:
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status}",
                        "the contract answers this status with the shared Error "
                        "envelope, and the document carries no response body",
                    )
                )
            # A HEAD answer is status and headers alone (RFC 9110 §9.3.2): the
            # bodyless refusal is exactly what the method promises, not a defect.
            continue
        ref = _json_schema_ref(response, document)
        if ref != "#/components/schemas/Error":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status}",
                    f"binds {ref!r} instead of Error",
                )
            )
    # This loop speaks for *every* response the operation carries, not only the
    # ones the table loops name, and it reads every node: an unreadable response
    # is named here — otherwise an error status the binding loop does not bind
    # and the error-envelope loop only skips as unreadable (a 404 with no named
    # schema and no promised header) could point its `$ref` at a component the
    # document does not define and be certified — and
    # so is an unreadable header node, because the required-ness loop below
    # resolves only the headers the table lists and the documented loop compares
    # names alone: the shared 416's optional `Content-Range` was never read.
    # The header map is read from the *shallow* response, with nested `$ref`s left
    # as nodes, so a dangling header component is named at the header where it
    # sits rather than at the response whose full read it breaks. HTTP field
    # names are case-insensitive (RFC 9110 §5.1), so a response that declares
    # `Upload-Offset` beside `upload-offset` declares one header twice — an
    # ambiguous document a generated client may satisfy with either schema. The
    # duplicate has to be refused *before* the required-ness loops below interpret
    # the flags, because `_resolved_header` reads only the first spelling and the
    # second member would otherwise never be read at all.
    for status_key, node in responses.items():
        resolved_response, unreadable = _resolved_response_node(node, document)
        shallow = _shallow_response(node, document)
        if shallow is None and unreadable is None:
            shallow = resolved_response
        if shallow is None:
            found.append(
                Violation(E.SPEC_COMPONENT_DRIFT, f"{where} responses/{status_key}", unreadable)
            )
            continue
        declared_headers = shallow.get("headers")
        # The map is scannable only when it is a map of declared names: a
        # ``$ref`` node is not one (the table loops read that shape through the
        # full response resolution below), and a member that is not a map at all
        # declares no names for the scan to read.
        headers_scannable = isinstance(declared_headers, Mapping) and "$ref" not in declared_headers
        if unreadable is not None:
            # The component the response points at is there but its full read
            # failed somewhere. Name the response unless the failure sat inside
            # a header map the scan below can read, where the per-header read
            # reports the very member that carries the bad `$ref`.
            without_headers = {key: value for key, value in shallow.items() if key != "headers"}
            try:
                resolve_refs(without_headers, root=document)
            except _RESOLUTION_FAILURES:
                headers_scannable = False
            if not headers_scannable:
                found.append(
                    Violation(
                        E.SPEC_COMPONENT_DRIFT, f"{where} responses/{status_key}", unreadable
                    )
                )
        if headers_scannable:
            name_map: Mapping[str, Any] | None = declared_headers
        elif unreadable is None and "headers" not in shallow:
            # A two-hop `$ref` chain landed on an intermediate node that carries
            # no member of its own, so the full resolution holds the header map
            # the hop could not reach — the duplicate-spelling gate keeps its
            # round-12 coverage for this shape. The shape verdict travels with
            # it: an alias may hide a target that declares `headers: null` (or
            # any other non-map), and reading only the shallow node let that
            # member escape the refusal the direct shape gets (round-14's
            # recorded two-hop escape).
            full_headers = resolved_response.get("headers")
            if "headers" in resolved_response and not isinstance(full_headers, Mapping):
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status_key} headers",
                        f"is {type(full_headers).__name__}, not a map of declared header names",
                    )
                )
                name_map = None
            else:
                name_map = full_headers if isinstance(full_headers, Mapping) else None
        else:
            # The member is not a name map the scan can read (a `$ref` node, or
            # not a map at all). If the response declares it at all, judge its
            # shape and, if it still carries references, follow them the
            # guarded way: a failure here is a defect no other reader reaches —
            # the helpers do not deep-resolve an inline response node — so it is
            # named at the response, never left unread and unnamed. Key
            # *presence* is the question, not truthiness: an explicit
            # `headers:` null declares a member OpenAPI defines as a Map, and
            # the status may carry no mandatory header for any presence loop to
            # notice it (the shared 404 was exactly that silence).
            if "headers" in shallow:
                if not isinstance(declared_headers, Mapping):
                    # OpenAPI's Response Object defines `headers` as a Map, so a
                    # declared member of any other shape is a document defect
                    # whatever the status carries — including one with no
                    # mandatory headers, where no presence loop below would ever
                    # notice. Name it the way the non-list `parameters` member is
                    # named, and still follow the references below: a dangling
                    # `$ref` hiding inside the list keeps its own drift finding.
                    found.append(
                        Violation(
                            E.SPEC_STRUCTURE_MISSING,
                            f"{where} responses/{status_key} headers",
                            f"is {type(declared_headers).__name__}, not a map of declared header names",
                        )
                    )
                try:
                    resolve_refs(declared_headers, root=document)
                except KeyError as error:
                    found.append(
                        Violation(
                            E.SPEC_COMPONENT_DRIFT,
                            f"{where} responses/{status_key}",
                            f"$ref names {error}, a component member the document does not define",
                        )
                    )
                except _RESOLUTION_FAILURES as error:
                    found.append(
                        Violation(
                            E.SPEC_COMPONENT_DRIFT,
                            f"{where} responses/{status_key}",
                            f"$ref cannot be followed: {error!r}",
                        )
                    )
            name_map = None
        if name_map is None:
            continue
        for key, header_node in name_map.items():
            _, broken = _read_header_node(header_node, document)
            if broken is not None:
                found.append(
                    Violation(
                        E.SPEC_COMPONENT_DRIFT,
                        f"{where} responses/{status_key} headers/{key}",
                        broken,
                    )
                )
        spellings: dict[str, list[str]] = {}
        for key in name_map:
            spellings.setdefault(str(key).lower(), []).append(str(key))
        for collisions in spellings.values():
            if len(collisions) < 2:
                continue
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status_key} headers/{collisions[0]}",
                    f"declares the header {collisions[0]!r} {len(collisions)} times "
                    f"as {', '.join(collisions)}: field names are case-insensitive, "
                    "so this is one header declared twice",
                )
            )
    for status, names in operation.required_response_headers.items():
        response, unreadable = _resolved_response(responses, status, document)
        if unreadable is not None:
            found.append(
                Violation(E.SPEC_COMPONENT_DRIFT, f"{where} responses/{status}", unreadable)
            )
            continue
        declared = response.get("headers", {})
        if not isinstance(declared, Mapping):
            # A ``headers`` member that is not an object declares no header at all; the
            # presence check below names every promised header as missing, which is the
            # honest verdict and never the crash an ``.items()`` here would raise.
            declared = {}
        header_names = {str(key).lower() for key in declared}
        for name in names:
            if name.lower() not in header_names:
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status} headers/{name}",
                        "the spec requires this header in that response",
                    )
                )
                continue
            # Presence alone was not enough: OpenAPI's Header Object defaults to
            # optional, so a document could promise ``Upload-Offset`` on the 204 and
            # still declare it a suggestion a generated client may drop. The contract
            # *requires* these headers, so the component behind the name has to say so.
            header, broken = _resolved_header(declared, name, document)
            if broken is not None:
                found.append(
                    Violation(
                        E.SPEC_COMPONENT_DRIFT,
                        f"{where} responses/{status} headers/{name}",
                        broken,
                    )
                )
                continue
            if header.get("required") is not True:
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status} headers/{name}",
                        "the spec requires this header in that response, and the "
                        "document declares it optional",
                    )
                )
    for status, names in operation.documented_response_headers.items():
        response, unreadable = _resolved_response(responses, status, document)
        if unreadable is not None:
            found.append(
                Violation(E.SPEC_COMPONENT_DRIFT, f"{where} responses/{status}", unreadable)
            )
            continue
        declared = response.get("headers", {})
        if not isinstance(declared, Mapping):
            # Same guard the required loop above applies: a ``headers`` member that is
            # not an object documents no header, and the presence check below says so
            # as a finding instead of the iteration raising past the CLI as exit 2.
            declared = {}
        header_names = {str(key).lower() for key in declared}
        for name in names:
            if name.lower() not in header_names:
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status} headers/{name}",
                        "the spec documents this header for that response, which is what "
                        "lets a vector carry it without requiring it",
                    )
                )
    # Resolved once for both branches below, so a document that points its requestBody at
    # a shared component is asked the same ``required`` question an inline body is. The
    # binding check is the narrower half: it reads the ``$ref`` the JSON schema carries
    # before inlining, so a JSON body has to stay inline as both documents publish it.
    body = _resolved_request_body(item, document)
    # The media types :mod:`tools.contracts.api_validate` accepts are the ones this
    # document publishes, per operation and status, so the operation table cannot drift
    # into a second source of truth: a media type added to one side and not the other is
    # a finding here rather than a rule that quietly stops matching anything.
    if operation.request_schema is None:
        published_map, body_issue = _media_type_map(body)
        published = set(published_map)
        if body_issue is not None:
            # The shape refusal is this body's one owner; the media-type
            # comparison below can only repeat it against an unreadable member.
            found.append(
                Violation(E.SPEC_STRUCTURE_MISSING, f"{where} requestBody content", body_issue)
            )
            published = set()
        elif published != set(operation.request_content_types):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} requestBody content",
                    f"publishes {sorted(published)}, the operation table carries "
                    f"{sorted(operation.request_content_types)}",
                )
            )
        # A body with no named JSON schema has no ``$ref`` binding to check, so the one
        # thing that pins it to the wire is its own ``required``. The upload chunk is
        # exactly that body: a PATCH whose ``requestBody`` is optional documents an append
        # of no bytes at all, which is how a client generator learns to send one.
        if published and body.get("required") is not True:
            found.append(Violation(E.SPEC_STRUCTURE_MISSING, f"{where} requestBody", "not required"))
    for status, types in operation.response_content_types.items():
        # Read through the response's own pointer hop only: the comparison
        # consults the ``content`` *keys*, and a media type name carries no
        # reference, so a nested pointer the document cannot resolve — a header
        # component that vanished — must not swallow this diagnostic beside the
        # drift it coexists with. A node whose own pointer cannot be followed is
        # named at `{where} responses/{status}` by the all-response scan above,
        # which owns that diagnostic; this loop skips it rather than let the
        # failed pointer raise past the CLI as exit 2 "validator internal
        # error" the way the unguarded `_resolve` here once did. A pure-`$ref`
        # alias component is followed to its target before the keys are read:
        # the alias carries no ``content`` member, and stopping at it would
        # report a mismatch against types the document does publish. A status
        # the table names but the document lacks still compares, as ever: the
        # missing status reads as an empty mapping and earns its mismatch.
        response = _alias_chained_response(responses.get(str(status), {}), document)
        if response is None:
            continue
        content, content_issue = _media_type_map(response)
        if content_issue is not None:
            # A declared ``content`` that is not a media-type map cannot answer
            # the media-type question; the shape refusal is that one owner, and
            # the empty-vs-table mismatch beside it would only repeat it.
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    content_issue,
                )
            )
            continue
        published = set(content)
        if published != set(types):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    f"publishes {sorted(published)}, the operation table carries "
                    f"{sorted(types)}",
                )
            )
    for status_key, response in responses.items():
        # RFC 9110 §9.3.2 and §15.3.3: a HEAD answer is headers and status alone and a
        # 204 describes its result without a body. A document that promises content on
        # one of those teaches a generator to build a client that reads bytes no
        # conforming server ever sends.
        try:
            status: int | str = int(status_key)
        except ValueError:
            # ``default`` is the only non-numeric key either document uses, and on a HEAD
            # operation it still describes a HEAD answer, so it may not promise content
            # either. A 204 operation's ``default`` covers statuses other than the 204,
            # where a body is legitimate, so only the HEAD half is refused here.
            if status_key != "default" or not operation.is_head:
                continue
            status = status_key
        if not (operation.is_head or status == 204):
            continue
        # Guarded: an unreadable response is named by the all-response scan above,
        # and this loop simply cannot read a content or headers member out of it —
        # never the exception reaching the CLI as exit 2 "validator internal error".
        resolved, _ = _resolved_response_node(response, document)
        if isinstance(resolved, Mapping) and resolved.get("content"):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    "promises a body the method or status forbids",
                )
            )
        # RFC 9110 §8.6 and §15.3.2: a 204 describes its result without a payload,
        # so a document promising its length teaches a generated client to expect
        # bytes the status can never carry — the same rule
        # ``api_validate._rule_content_length`` enforces on the wire. A HEAD
        # answer *may* legitimately carry `Content-Length` (it reports the length
        # the GET would have sent), so only the 204 half is refused here; the
        # header key is read from the declared map, so the refusal stands whatever
        # spelling or `$ref` the value carries.
        if status == 204 and isinstance(resolved, Mapping):
            declared = resolved.get("headers")
            if isinstance(declared, Mapping):
                for key in declared:
                    if str(key).lower() == "content-length":
                        found.append(
                            Violation(
                                E.SPEC_STRUCTURE_MISSING,
                                f"{where} responses/{status} headers/{key}",
                                "a 204 describes its result without a payload, so the "
                                "document may not declare its length (RFC 9110 §8.6)",
                            )
                        )

    if operation.request_schema is not None:
        if body.get("required") is not True:
            found.append(Violation(E.SPEC_STRUCTURE_MISSING, f"{where} requestBody", "not required"))
        _, body_issue = _media_type_map(body)
        if body_issue is not None:
            # A `content` member that is not a media-type map carries no
            # readable schema `$ref`: name the member as the one owner instead
            # of letting the read raise past the CLI, or naming the body as if
            # it bound no schema when nothing was ever read from it.
            found.append(
                Violation(E.SPEC_STRUCTURE_MISSING, f"{where} requestBody content", body_issue)
            )
        else:
            ref = _json_schema_ref(body, document)
            if ref != f"#/components/schemas/{operation.request_schema}":
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} requestBody",
                        f"binds {ref!r} instead of {operation.request_schema}",
                    )
                )
    # Every parameter an operation declares has to be a usable parameter object, and
    # every `{placeholder}` the path carries — plus every query parameter the spec
    # pins by name — has to be declared and required. The required-input checks of the
    # rounds before this one walked only the request headers, so a document could drop
    # the `device_id` that disambiguates a clip id (interfaces.md §9), delete a path
    # parameter, or point a `$ref` at a component it never defined, and the gate would
    # certify it: a generated client would silently lose the disambiguator or fail to
    # generate the method at all.
    declared_parameters = item.get("parameters", [])
    if not isinstance(declared_parameters, list):
        # A `parameters` member that is not a list declares nothing answerable: it is
        # named as a defect and read as "nothing declared", the same way the headers
        # guards read a non-object headers member — never as the iteration raising
        # past the CLI as exit 2 "validator internal error".
        found.append(
            Violation(
                E.SPEC_STRUCTURE_MISSING,
                f"{where} parameters",
                f"is {type(declared_parameters).__name__}, not a list of parameter objects",
            )
        )
        declared_parameters = []
    parameter_identities: dict[tuple[str, str], list[str]] = {}
    for entry in declared_parameters:
        is_reference = isinstance(entry, Mapping) and "$ref" in entry
        try:
            resolved = _resolve(entry, document)
        except _RESOLUTION_FAILURES:
            resolved = None
        if (
            isinstance(resolved, Mapping)
            and isinstance(resolved.get("name"), str)
            and isinstance(resolved.get("in"), str)
        ):
            # OpenAPI's Operation Object requires parameter names to be unique per
            # location, so the first member of an identity is the declaration and
            # every additional member is a document the gate may not certify.
            # Header field names match case-insensitively (RFC 9110 §5.1) while
            # path and query names are exact, so the identity lowercases only for
            # `header` and reads `name` verbatim everywhere else.
            location_kind = resolved["in"].lower()
            declared_name = resolved["name"]
            identity_name = declared_name.lower() if location_kind == "header" else declared_name
            parameter_identities.setdefault((location_kind, identity_name), []).append(declared_name)
            continue
        if is_reference:
            found.append(
                Violation(
                    E.SPEC_COMPONENT_DRIFT,
                    f"{where} parameters",
                    f"$ref {entry.get('$ref')!r} names no parameter object the document defines",
                )
            )
        else:
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters",
                    "an inline parameter carries no string name and in",
                )
            )
    for (identity_location, identity_name), declared_names in parameter_identities.items():
        if len(declared_names) < 2:
            continue
        # Read from the list before any required interpretation: every additional
        # member of one identity is refused whatever its ``required`` flag says,
        # because a twin a generated client may read instead of the declaration is
        # a defect whether or not both members happen to be required today.
        for duplicate_name in declared_names[1:]:
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters/{duplicate_name}",
                    f"duplicate declaration: {len(declared_names)} parameters share the "
                    f"identity in={identity_location} name={identity_name}, and the "
                    "Operation Object permits one declaration per name and location",
                )
            )
    for placeholder in re.findall(r"\{([^}/]+)\}", operation.path):
        declared = _required_request_parameter(item, document, placeholder, "path")
        if declared != "ok":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters/{placeholder}",
                    "the spec requires this path parameter"
                    if declared == "missing"
                    else "the spec requires this path parameter, and the document declares it optional",
                )
            )
    for name in operation.required_query_parameters:
        declared = _required_request_parameter(item, document, name, "query")
        if declared != "ok":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters/{name}",
                    "the spec requires this query parameter"
                    if declared == "missing"
                    else "the spec requires this query parameter, and the document declares it optional",
                )
            )
    for name in operation.required_request_headers:
        declared = _required_request_parameter(item, document, name, "header")
        if declared != "ok":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters/{name}",
                    "the spec requires this request header"
                    if declared == "missing"
                    else "the spec requires this request header, and the document declares it optional",
                )
            )
    # The all-response scan above reads the statuses and header nodes the table
    # loops already walk, so one dangling shared component would otherwise earn
    # the same statement twice. Collapse exact repeats on the (code, location,
    # detail) triple — each loop keeps its own wording, and any finding that
    # differs in subject, location, or detail survives untouched.
    unique: list[Violation] = []
    seen: set[tuple[str, str, str]] = set()
    for violation in found:
        identity = (violation.code, violation.location, violation.detail)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(violation)
    return unique


#: What :func:`tools.contracts.schema_docs.resolve_refs` raises when a pointer cannot be
#: followed — the same set ``check_local_refs`` refuses. Reading through one of them is a
#: document defect for these checks to report, never an exception to let reach the CLI as
#: exit 2 "validator internal error".
_RESOLUTION_FAILURES: Final[tuple[type[Exception], ...]] = (ValueError, KeyError, IndexError, TypeError)


def _resolve(node: Any, document: Mapping[str, Any]) -> Any:
    if isinstance(node, Mapping) and "$ref" in node:
        return resolve_refs(node, root=document)
    return node


def _resolved_request_body(item: Mapping[str, Any], document: Mapping[str, Any]) -> Mapping[str, Any]:
    """The operation's requestBody object, or an empty one when it cannot be read.

    A requestBody is often a `$ref` to a shared component, and a document whose component
    is missing is a document with a defect, not a validator crash: following the pointer
    raises, which would reach the CLI as exit 2 "validator internal error" and leave the
    very weakness these checks exist to report unreported. An empty body is what the two
    checks below read as "not required" and "bound to no schema". The exception set is the
    one :func:`tools.contracts.schema_docs.check_local_refs` refuses, so a pointer that
    walks through a list index or a scalar is a finding too.
    """
    try:
        resolved = _resolve(item.get("requestBody", {}), document)
    except _RESOLUTION_FAILURES:
        return {}
    return resolved if isinstance(resolved, Mapping) else {}


def _resolved_response(
    responses: Mapping[str, Any], status: int, document: Mapping[str, Any]
) -> tuple[Mapping[str, Any], str | None]:
    """The response object for a status, or the reason it could not be read.

    A response is often a `$ref` to a shared component — the two contracts answer a 401
    with one documented `Unauthorized` — and a document whose component is missing is a
    document with a defect, not a validator crash: following the pointer raises
    `KeyError`, which would reach the CLI as an internal error and leave the very
    absence it came to report unreported. The caller names what it found instead.
    """
    return _resolved_response_node(responses.get(str(status), {}), document)


def _shallow_response(node: Any, document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The response object one pointer hop away, with nested `$ref`s left alone.

    :func:`_resolved_response_node` reads a response the way the table loops do:
    ``resolve_refs`` inlines every nested reference, so when a *header's* component
    is what vanished, that read fails at the response and the member carrying the
    bad pointer is never named. Following the response's own pointer one hop
    without recursing keeps each declared header a node the header read can
    resolve on its own. A node that is not a readable object at this depth answers
    ``None`` and the caller reports it at the response.
    """
    if not isinstance(node, Mapping):
        return None
    reference = node.get("$ref")
    if reference is None:
        return node
    # Mirror resolve_refs' own guard: only local pointers are walkable here. Any
    # other spelling must fall through to the full read, which names it.
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return None
    target: Any = document
    try:
        for segment in reference[2:].split("/"):
            target = target[segment.replace("~1", "/").replace("~0", "~")]
    except _RESOLUTION_FAILURES:
        return None
    return target if isinstance(target, Mapping) else None


def _alias_chained_response(node: Any, document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The one-hop response node with pure-`$ref` alias components walked through.

    :func:`_shallow_response` stops at a component that is itself only a
    ``$ref`` — an alias carrying no member of its own — so a media-type or
    binding read taken there sees an empty document and reports a mismatch the
    document never made. Keep taking guarded hops while the hop is a pure
    ``$ref`` node (``$ref`` its only member), following each pointer at most
    once so a cycle ends as a failure like any other un-followable hop. The
    all-response scan owns the drift a failed chain hides; callers skip.
    """
    response = _shallow_response(node, document)
    followed: set[str] = set()
    while response is not None and set(response) == {"$ref"}:
        reference = response["$ref"]
        if not isinstance(reference, str) or reference in followed:
            return None
        followed.add(reference)
        response = _shallow_response(response, document)
    return response


def _media_type_map(container: Mapping[str, Any]) -> tuple[Mapping[str, Any], str | None]:
    """The ``content`` map a response or requestBody declares, or why it is not one.

    An absent ``content`` member is the empty map — a bodyless answer says so
    itself — but a *declared* member of any other shape (null, a string, a
    number, a list) makes every plain read explode: ``set(content)`` raises a
    ``TypeError``, and so does the ``"application/json" in content`` test
    :func:`_json_schema_ref` runs. Unguarded, that reached the CLI as exit 2
    "validator internal error" for a document that is simply malformed. The
    caller names the defect once for the node it owns, in the wording the
    other member-shape refusals use.
    """
    content = container.get("content", {})
    if isinstance(content, Mapping):
        return content, None
    return {}, f"is {type(content).__name__}, not a media-type map"


def _resolved_response_node(
    node: Any, document: Mapping[str, Any]
) -> tuple[Mapping[str, Any], str | None]:
    """The response object a declared node names, or the reason it cannot be read.

    The all-response scan in :func:`_check_operation` holds the node itself rather
    than a status, so it asks this question directly and reports the same wording as
    :func:`_resolved_response` above: one dangling shared component earns one
    finding per operation+status, whichever loop gets there first.
    """
    try:
        resolved = _resolve(node, document)
    except KeyError as error:
        return {}, f"$ref names {error}, a component member the document does not define"
    except _RESOLUTION_FAILURES as error:
        # A pointer that walks through a list index or a scalar is a document
        # defect named here, never the exception reaching the CLI as exit 2.
        return {}, f"$ref cannot be followed: {error!r}"
    if not isinstance(resolved, Mapping):
        return {}, f"is {type(resolved).__name__}, not a response object"
    return resolved, None


def _json_schema_ref(container: Mapping[str, Any], document: Mapping[str, Any]) -> str | None:
    """Return the ``application/json`` schema ``$ref`` before inlining happened.

    The loops that ask this question of a response or body guard the shape of
    ``content`` themselves and name the member once; the ``isinstance`` walls
    here are the last line so no reader hands the membership test a scalar it
    would raise over as exit 2, and a media-type entry or schema that is not an
    object simply binds no readable schema — ``None``, which every caller
    reports as its own finding.
    """
    content = container.get("content", {})
    if not isinstance(content, Mapping) or "application/json" not in content:
        return None
    entry = content["application/json"]
    if not isinstance(entry, Mapping):
        return None
    schema = entry.get("schema", {})
    if not isinstance(schema, Mapping):
        return None
    ref = schema.get("$ref")
    return ref if isinstance(ref, str) else None


def _required_request_parameter(
    item: Mapping[str, Any], document: Mapping[str, Any], name: str, location: str
) -> str:
    """How one required request parameter is declared: ``missing``, ``optional`` or ``ok``.

    Matching name and location alone (what the old declaration check did) accepted a
    parameter the document marked optional, so a whole contract could weaken its
    `Idempotency-Key`, `Upload-Offset`, `Upload-Checksum` or `Content-Length` to a
    suggestion and nothing would say so. The three-way answer keeps the two failures
    distinguishable in the finding: a parameter that is not declared at all is a
    different defect from one that is declared and then not required. The same question
    is asked of the ``header``, ``path`` and ``query`` locations — a path placeholder or
    a spec-pinned query the document leaves optional fails exactly the way an optional
    `Idempotency-Key` does. Every matching declaration is consulted, not just the first:
    OpenAPI requires parameter names to be unique per location, and an optional twin
    hiding behind a required first entry is an ambiguous declaration a generated client
    may still drop, so one non-required match is enough to answer ``optional``. HTTP
    folds field names case-insensitively (RFC 9110 §5.1), so a ``header`` name matches
    whatever casing the document declares; ``path`` and ``query`` names are URI
    elements, not field names, and stay exact.
    """
    declared_parameters = item.get("parameters", [])
    if not isinstance(declared_parameters, list):
        # The integrity loop above already named the member as a defect; here it simply
        # declares nothing, so the required parameter reads as missing rather than
        # raising past the CLI as exit 2.
        return "missing"
    matched = False
    all_required = True
    for parameter in declared_parameters:
        try:
            resolved = _resolve(parameter, document)
        except _RESOLUTION_FAILURES:
            # A declaration that cannot be read is not a declaration that the parameter
            # is required: the check has to fail closed, exactly as it does when the
            # member is absent, rather than raise past the CLI as exit 2. The reference
            # integrity loop above names the unreadable `$ref` itself.
            continue
        if not isinstance(resolved, Mapping):
            continue
        declared_name = resolved.get("name")
        if location == "header":
            name_matches = isinstance(declared_name, str) and declared_name.lower() == name.lower()
        else:
            name_matches = declared_name == name
        if name_matches and resolved.get("in") == location:
            matched = True
            if resolved.get("required") is not True:
                all_required = False
    if not matched:
        return "missing"
    return "ok" if all_required else "optional"


def _resolved_header(
    headers: Mapping[str, Any], name: str, document: Mapping[str, Any]
) -> tuple[Mapping[str, Any], str | None]:
    """The Header Object a response declares under one name, or why it cannot be read.

    Both contracts spell every required response header as a ``$ref`` to a shared
    component — the `UploadOffset` behind `Upload-Offset`, the `WwwAuthenticate` behind
    the 401 challenge — so a document whose component is missing is a document with a
    defect, not a validator crash: following the pointer raises, which would reach the
    CLI as exit 2 "validator internal error" and leave the very header this check came
    to demand unreported. The caller names what it found instead. Header names are
    matched case-insensitively, as HTTP and the response validator match them.
    """
    node: Any = {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            node = value
            break
    return _read_header_node(node, document)


def _read_header_node(
    node: Any, document: Mapping[str, Any]
) -> tuple[Mapping[str, Any], str | None]:
    """The Header Object a declared node names, or why it cannot be read.

    The all-response scan in :func:`_check_operation` holds the declared member
    itself rather than a name to look up, so it asks this question directly and
    reports the same wording family :func:`_resolved_header` uses: one dangling
    shared component earns one finding per operation+status+header, whichever loop
    gets there first.
    """
    try:
        resolved = _resolve(node, document)
    except KeyError as error:
        return {}, f"$ref names {error}, a component member the document does not define"
    except _RESOLUTION_FAILURES as error:
        return {}, f"$ref cannot be followed: {error!r}"
    if not isinstance(resolved, Mapping):
        return {}, f"is {type(resolved).__name__}, not a header object"
    return resolved, None


def _requires_bearer(document: Mapping[str, Any], operation: Operation) -> bool:
    paths = document.get("paths", {})
    item = paths.get(operation.path, {}).get(operation.method.lower(), {})
    security = item.get("security", document.get("security", []))
    return any("bearerAuth" in entry for entry in security)
