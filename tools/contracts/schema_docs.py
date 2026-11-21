"""Document loading, ``$ref`` resolution and schema-error reporting helpers.

One place decides how a JSON Schema or OpenAPI 3.1 document is read and how a
schema error is turned into a validator code, so the media and API validators cannot
drift apart in their reporting.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

#: Keys stripped before comparing two documents that must say the same thing.
_NON_SEMANTIC_KEYS: frozenset[str] = frozenset(
    {"description", "title", "$comment", "examples", "example", "deprecated"}
)


def load_json(path: Path) -> Any:
    """Parse a committed JSON document, rejecting a UTF-8 BOM."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path}: unexpected UTF-8 BOM")
    return json.loads(raw.decode("utf-8"))


def load_yaml(path: Path) -> Any:
    """Parse a committed YAML document with the safe loader only."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical(document: Any) -> Any:
    """Return a copy of ``document`` without documentation-only keys, recursively."""
    if isinstance(document, Mapping):
        return {
            key: canonical(value)
            for key, value in document.items()
            if key not in _NON_SEMANTIC_KEYS
        }
    if isinstance(document, list):
        return [canonical(item) for item in document]
    return document


def resolve_refs(document: Any, *, root: Mapping[str, Any] | None = None, _stack: deque[str] | None = None) -> Any:
    """Inline every local ``$ref`` so plain JSON Schema validation can run.

    Only ``#/...`` JSON pointers are supported, which is all either contract uses. A
    reference cycle is expanded once and then refused: a recursive wire contract
    would be a design change worth failing on rather than looping over.
    """
    base = document if root is None else root
    stack = _stack if _stack is not None else deque()
    if isinstance(document, Mapping):
        if "$ref" in document:
            ref = document["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ValueError(f"unsupported $ref {ref!r}; only local pointers are allowed")
            if ref in stack:
                raise ValueError(f"recursive $ref {ref!r} in the contract")
            target = _pointer(base, ref)
            stack.append(ref)
            try:
                return resolve_refs(target, root=base, _stack=stack)
            finally:
                stack.pop()
        return {key: resolve_refs(value, root=base, _stack=stack) for key, value in document.items()}
    if isinstance(document, list):
        return [resolve_refs(item, root=base, _stack=stack) for item in document]
    return document


def schema_error_report(
    schema: Mapping[str, Any], instance: Any
) -> list[tuple[str, str, str]]:
    """Return ``(property, keyword, message)`` for every schema violation.

    ``property`` is the last key of the failing instance path (or the special value
    ``""`` for errors at the document root), which lets callers suppress the generic
    schema code where a dedicated invariant already reports the same bound.
    """
    validator = Draft202012Validator(schema)
    report: list[tuple[str, str, str]] = []
    for error in sorted(validator.iter_errors(instance), key=_error_sort_key):
        property_name = ""
        for part in reversed(list(error.absolute_path)):
            if isinstance(part, str):
                property_name = part
                break
        keyword = str(error.validator or "")
        message = error.message.replace("\n", " ")
        if len(message) > 200:
            message = message[:197] + "..."
        report.append((property_name, keyword, message))
    return report


def check_metaschema(document: Mapping[str, Any]) -> str | None:
    """Return a short failure description when a document is not a valid 2020-12 schema."""
    try:
        Draft202012Validator.check_schema(document)
    except ValidationError as error:  # pragma: no cover - only on a bad contract file
        return str(error.message).replace("\n", " ")
    return None


def _pointer(document: Mapping[str, Any], ref: str) -> Any:
    node: Any = document
    for fragment in ref[2:].split("/"):
        key = fragment.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(key)]
        else:
            node = node[key]
    return node


def _error_sort_key(error: ValidationError) -> tuple[str, ...]:
    return tuple(str(part) for part in error.absolute_path)
