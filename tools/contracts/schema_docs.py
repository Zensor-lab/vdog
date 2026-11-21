"""Document loading, ``$ref`` resolution and schema-error reporting helpers.

One place decides how a JSON Schema or OpenAPI 3.1 document is read and how a
schema error is turned into a validator code, so the media and API validators cannot
drift apart in their reporting — including the one :class:`~jsonschema.FormatChecker`
that gives ``format: date-time`` a meaning at all.
"""

from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

#: Keys stripped before comparing two documents that must say the same thing.
_NON_SEMANTIC_KEYS: frozenset[str] = frozenset(
    {"description", "title", "$comment", "examples", "example", "deprecated"}
)

#: RFC 3339 ``date-time`` (the one ``format`` this contract uses), spelled out so every
#: field can be examined: four-digit year, two-digit month/day, the case-tolerant ``T``
#: RFC 3339 §5.6 allows, an optional fraction of any digit count, and either a
#: case-tolerant ``Z`` or a ``±HH:MM`` offset.
_RFC3339_DATE_TIME = re.compile(
    r"\A(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"[Tt](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:\.[0-9]+)?"
    r"(?:[Zz]|(?P<offset>[+-][0-9]{2}:[0-9]{2}))\Z"
)


def is_rfc3339_date_time(value: Any) -> bool:
    """True when ``value`` is a real RFC 3339 instant, not merely one shaped like it.

    ``format`` is informational in JSON Schema unless a validator is handed a checker,
    and a ``pattern`` can only ever test the shape, so ``2026-02-30T12:00:00.000Z`` and
    ``2026-01-01T25:00:00.000Z`` pass a regex and mean nothing. Constructing an actual
    :class:`~datetime.datetime` is what makes an impossible calendar date impossible.

    A leap second (``:60``) is refused: no contract vector, and no timestamp this
    product can write at millisecond precision, carries one, so accepting it would
    widen the published wire form for no documented reason.
    """
    if not isinstance(value, str):
        return True  # format constrains strings only; the type keyword owns the rest
    match = _RFC3339_DATE_TIME.match(value)
    if match is None:
        return False
    offset = match.group("offset")
    if offset is not None and (int(offset[1:3]) > 23 or int(offset[4:6]) > 59):
        return False
    try:
        datetime(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            second=int(match.group("second")),
        )
    except ValueError:
        return False
    return True


#: The one format checker every schema-error report in the package uses, so the media
#: and API validators cannot disagree about what a timestamp means. Formats it does not
#: register (``binary``, say) stay informational, which is what the contract expects of
#: an annotation it does not define semantics for.
FORMAT_CHECKER = FormatChecker()
FORMAT_CHECKER.checks("date-time")(is_rfc3339_date_time)


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
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
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
    """Return a short failure description when a document is not a valid 2020-12 schema.

    A parseable document whose *keywords* are wrong — a ``maximum`` that is text, say —
    raises :class:`~jsonschema.exceptions.SchemaError`, not ``ValidationError``. Both
    have to be caught here: either one escaping turns a bad contract file into a CLI
    exit 2 "validator internal error" instead of the exit 1 finding it is.
    """
    try:
        Draft202012Validator.check_schema(document)
    except (SchemaError, ValidationError) as error:
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
