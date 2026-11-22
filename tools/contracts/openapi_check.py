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

from pathlib import Path
from typing import Any, Mapping

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
    "ETagSha256": {"type": "string", "pattern": '^[0-9a-f]{64}$', "_quoted": True},
    "ContentRange": {"type": "string", "pattern": "^bytes ([0-9]+-[0-9]+|\\*)/[0-9]+$"},
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
        response = _resolve(responses.get(str(status), {}), document)
        if schema_name is None:
            if not response.get("content"):
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
    for status, names in operation.required_response_headers.items():
        response = _resolve(responses.get(str(status), {}), document)
        header_names = {str(key).lower() for key in response.get("headers", {})}
        for name in names:
            if name.lower() not in header_names:
                found.append(
                    Violation(
                        E.SPEC_STRUCTURE_MISSING,
                        f"{where} responses/{status} headers/{name}",
                        "the spec requires this header in that response",
                    )
                )
    for status, names in operation.documented_response_headers.items():
        response = _resolve(responses.get(str(status), {}), document)
        header_names = {str(key).lower() for key in response.get("headers", {})}
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
    # The media types :mod:`tools.contracts.api_validate` accepts are the ones this
    # document publishes, per operation and status, so the operation table cannot drift
    # into a second source of truth: a media type added to one side and not the other is
    # a finding here rather than a rule that quietly stops matching anything.
    if operation.request_schema is None:
        body = _resolve(item.get("requestBody", {}), document)
        published = set(body.get("content", {})) if isinstance(body, Mapping) else set()
        if published != set(operation.request_content_types):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} requestBody content",
                    f"publishes {sorted(published)}, the operation table carries "
                    f"{sorted(operation.request_content_types)}",
                )
            )
    for status, types in operation.response_content_types.items():
        response = _resolve(responses.get(str(status), {}), document)
        published = set(response.get("content", {})) if isinstance(response, Mapping) else set()
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
            status = int(status_key)
        except ValueError:
            continue
        if not (operation.is_head or status == 204):
            continue
        resolved = _resolve(response, document)
        if isinstance(resolved, Mapping) and resolved.get("content"):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} responses/{status} content",
                    "promises a body the method or status forbids",
                )
            )

    if operation.request_schema is not None:
        body = item.get("requestBody", {})
        if body.get("required") is not True:
            found.append(Violation(E.SPEC_STRUCTURE_MISSING, f"{where} requestBody", "not required"))
        ref = _json_schema_ref(body, document)
        if ref != f"#/components/schemas/{operation.request_schema}":
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} requestBody",
                    f"binds {ref!r} instead of {operation.request_schema}",
                )
            )
    for name in operation.required_request_headers:
        if not _declares_parameter(item, document, name, "header"):
            found.append(
                Violation(
                    E.SPEC_STRUCTURE_MISSING,
                    f"{where} parameters/{name}",
                    "the spec requires this request header",
                )
            )
    return found


def _resolve(node: Any, document: Mapping[str, Any]) -> Any:
    if isinstance(node, Mapping) and "$ref" in node:
        return resolve_refs(node, root=document)
    return node


def _json_schema_ref(container: Mapping[str, Any], document: Mapping[str, Any]) -> str | None:
    """Return the ``application/json`` schema ``$ref`` before inlining happened."""
    content = container.get("content", {})
    if "application/json" not in content:
        return None
    schema = content["application/json"].get("schema", {})
    ref = schema.get("$ref")
    return ref if isinstance(ref, str) else None


def _declares_parameter(
    item: Mapping[str, Any], document: Mapping[str, Any], name: str, location: str
) -> bool:
    for parameter in item.get("parameters", []):
        resolved = _resolve(parameter, document)
        if resolved.get("name") == name and resolved.get("in") == location:
            return True
    return False


def _requires_bearer(document: Mapping[str, Any], operation: Operation) -> bool:
    paths = document.get("paths", {})
    item = paths.get(operation.path, {}).get(operation.method.lower(), {})
    security = item.get("security", document.get("security", []))
    return any("bearerAuth" in entry for entry in security)
