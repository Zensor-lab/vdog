"""Document loading, ``$ref`` resolution and schema-error reporting helpers.

One place decides how a JSON Schema or OpenAPI 3.1 document is read and how a
schema error is turned into a validator code, so the media and API validators cannot
drift apart in their reporting — including the one :class:`~jsonschema.FormatChecker`
that gives ``format: date-time`` a meaning at all.
"""

from __future__ import annotations

import decimal
import json
import re
from collections import deque
from collections.abc import Hashable
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping

import referencing
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema._types import draft202012_type_checker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import create
from referencing.jsonschema import specification_with

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


def decimal_is_integral(value: decimal.Decimal) -> bool:
    """True when the digits a ``Decimal`` carries denote a whole number.

    ``type: integer`` accepts an integral number written in any JSON notation, and the
    media validator parses the frame index with ``parse_float=decimal.Decimal`` so an
    exponent cannot be rounded away before the check runs. Judgement is on the digits
    themselves, not on the binary float nearest them: ``0.0`` and ``0e0`` are the two
    extra spellings the contract publishes for ``0``, ``1.20000001e8`` is exactly
    ``120000001``, and ``1e-400`` is a fraction — even though the float it converts to
    is ``0.0``, which the default checker would have called an integer.
    """
    if not value.is_finite():
        return False
    _, digits, exponent = value.as_tuple()
    if exponent >= 0:
        return True
    return all(digit == 0 for digit in digits[exponent:])


def is_json_integer(checker: object, instance: Any) -> bool:
    """``type: integer`` for a document parsed with ``parse_float=decimal.Decimal``.

    jsonschema's own checker recognises ``int`` and an integral ``float``; a
    :class:`~decimal.Decimal` is a third spelling the media walk now hands it, and
    without this branch every ``0.0``/``0e0`` index line the contract publishes as
    valid would be refused as ``"0.0" is not of type "integer"``.
    """
    if isinstance(instance, bool):
        return False
    if isinstance(instance, int):
        return True
    if isinstance(instance, decimal.Decimal):
        return decimal_is_integral(instance)
    return isinstance(instance, float) and instance.is_integer()


#: :class:`~jsonschema.Draft202012Validator` with the integer branch above, which is
#: what lets :func:`schema_error_report` judge a ``Decimal`` instance at all. Built
#: without a ``version`` so no global validator registration happens as a side effect.
DRAFT202012_VALIDATOR: Final = create(
    meta_schema=Draft202012Validator.META_SCHEMA,
    validators=Draft202012Validator.VALIDATORS,
    type_checker=draft202012_type_checker.redefine("integer", is_json_integer),
)

#: The base URI the local-reference registry of :func:`schema_error_report`
#: registers the document root under, matching the empty base every ``#/…``
#: pointer in a contract document carries. The registry is built offline from
#: the caller's own document — no URI is ever fetched.
_REPORT_BASE_URI: Final[str] = ""

#: Synthetic member :func:`schema_error_report` hangs the validated node on
#: inside its shallow copy of the root, so ``#/`` pointers keep resolving
#: against the whole document while the validator judges the raw node. No
#: committed schema references it, and OpenAPI's ``x-`` prefix reserves it
#: from meaning anything to a document reader.
_REPORT_TARGET_MEMBER: Final[str] = "x-schema-error-report-target"

#: The Draft 2020-12 specification used to read a root that spells no
#: ``$schema`` of its own — which an OpenAPI document never does. Its schemas
#: are 2020-12 (the documents' ``jsonSchemaDialect`` says so, and
#: :data:`DRAFT202012_VALIDATOR` is what judges them either way).
_2020_12_SPECIFICATION: Final = specification_with(
    "https://json-schema.org/draft/2020-12/schema"
)


def mapping_or_empty(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, and ``{}`` when it is not.

    ``document.get("components", {})`` hands the caller ``None`` (or any other
    declared value) when the document spells ``components: null``, and the
    plain ``.get`` on the result then raises ``AttributeError`` out of the CLI
    as exit 2 "validator internal error" for what is a malformed document, not
    a broken validator. Every reader of a document container — the component
    map and its ``schemas``/``headers``/``securitySchemes`` sub-containers —
    reads through this guard so an unusable value declares nothing and the
    named findings for what it fails to define still fire (the caller owns
    naming the shape itself, once).
    """
    return value if isinstance(value, Mapping) else {}


def load_json(path: Path) -> Any:
    """Parse a committed JSON document, rejecting a UTF-8 BOM."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path}: unexpected UTF-8 BOM")
    return json.loads(raw.decode("utf-8"))


def _construct_mapping_without_duplicate_keys(
    loader: yaml.SafeConstructor, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    """Build a plain mapping, refusing a key the node already declares.

    :func:`yaml.safe_load` keeps the *last* of two literal keys, so a document
    that spells ``Upload-Offset:`` twice hands its readers one entry and every
    downstream duplicate-spelling gate sees nothing. The refusal therefore has
    to happen here, while both keys are still on the parse tree.
    """
    mapping: dict[Any, Any] = {}
    # Only the node's *own* explicit keys are duplicate candidates: a key the
    # node also declares while a ``<<`` source contributes it is YAML's
    # documented override, not a collision, and PyYAML lets the explicit
    # member win whatever the textual order.
    explicit: set[Any] = set()
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            # A ``<<`` key contributes the aliased map, not a literal key of its
            # own: merge it in as the safe constructor does (first source wins
            # among merges, explicit assignment beats all of them), but never
            # submit the merge itself to the duplicate check below.
            #
            # A sequence of merge sources is walked at the *node* level, the
            # way ``BaseConstructor.flatten_mapping`` walks it, before anything
            # is constructed. Constructing it instead loses the anchored
            # sequence to the loader's already-constructed memo: the anchor was
            # registered when its own key constructed it shallowly, so
            # ``construct_object`` hands back the generator-backed list while
            # its pending generator has appended nothing yet — every merged key
            # would then silently vanish while ``yaml.safe_load`` merges them.
            # Each entry has to name a mapping; a source that names anything
            # else is the same document defect the stock constructor refuses.
            if isinstance(value_node, yaml.nodes.SequenceNode):
                for entry_node in value_node.value:
                    if not isinstance(entry_node, yaml.nodes.MappingNode):
                        raise yaml.constructor.ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            "expected a mapping for merging, but found "
                            f"{entry_node.id}",
                            key_node.start_mark,
                        )
                    source = loader.construct_object(entry_node, deep=True)
                    for merged_key, merged_value in source.items():
                        mapping.setdefault(merged_key, merged_value)
                continue
            merged = loader.construct_object(value_node, deep=True)
            if not isinstance(merged, Mapping):
                # The same refusal ``BaseConstructor.flatten_mapping``
                # raises: a merge that names a scalar is a document defect,
                # not a member to drop on the floor.
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"expected a mapping for merging, but found {type(merged).__name__}",
                    key_node.start_mark,
                )
            for merged_key, merged_value in merged.items():
                mapping.setdefault(merged_key, merged_value)
            continue
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, Hashable):
            # Same refusal the stock safe constructor raises: an unhashable key
            # cannot become a mapping member, and it dies as a ``YAMLError``
            # like every other load failure — never a bare ``TypeError``.
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            )
        if key in explicit:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        explicit.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


class _DuplicateKeyRejectingSafeLoader(yaml.SafeLoader):
    """The safe loader, refusing an explicit duplicate mapping key at parse time.

    SafeLoader only — nothing here resolves arbitrary Python tags — and the sole
    change is the default-mapping constructor above, so a committed document
    that spells one key twice is a parse failure the validator reports as
    ``SPEC_PARSE_FAILED`` rather than a silently halved mapping.
    """


_DuplicateKeyRejectingSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_without_duplicate_keys
)


def load_yaml(path: Path) -> Any:
    """Parse a committed YAML document with the safe loader only.

    The loader is :class:`_DuplicateKeyRejectingSafeLoader`, so a duplicate
    explicit mapping key raises a ``yaml.YAMLError`` here — the caller in
    ``validate.py`` turns any load failure into a ``SPEC_PARSE_FAILED`` naming
    the file — instead of the later keys quietly overwriting the earlier ones.
    """
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_DuplicateKeyRejectingSafeLoader)


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


def resolve_refs(
    document: Any,
    *,
    root: Mapping[str, Any] | None = None,
    mode: str = "schema",
    _stack: deque[str] | None = None,
) -> Any:
    """Inline every local ``$ref`` so plain JSON Schema validation can run.

    Only ``#/...`` JSON pointers are supported, which is all either contract uses. A
    reference cycle is expanded once and then refused: a recursive wire contract
    would be a design change worth failing on rather than looping over. Only a
    pointer that a chain actually reaches again while in flight is a cycle: the
    node's own ``$ref`` sits on the stack for the *target* expansion, while
    sibling subtrees are evaluated with the stack as it stood before that push
    (a fresh copy each), because a sibling re-referencing the same finite
    target — ``{"$ref": A, "allOf": [{"$ref": A}]}`` — is two independent
    assertions of one document, which standard validators accept. Genuine
    recursion, a target expansion that reaches an enclosing in-flight pointer,
    still raises.

    ``mode`` states which document position is being resolved, because the two
    positions read a ``$ref`` node differently:

    * ``"schema"`` (the default) reads a JSON Schema 2020-12 Schema Object
      (§8.2.3.1): a ``$ref``'s sibling members are assertions that conjoin with
      the referenced target, so when target and siblings are both mappings the
      result is their conjunction ``{"allOf": [target, siblings]}`` — no
      sibling key can overwrite a target keyword, which a ``{**target,
      **siblings}`` merge would allow. It is *not*, however, an
      annotation-scope-preserving conjunction (§11.3): a sibling
      ``unevaluatedProperties``/``unevaluatedItems`` cannot observe the
      annotations the referenced target produces across the allOf split, so
      this expansion is for structural readers only and never for judging an
      instance — :func:`schema_error_report` takes the raw node plus the
      document ``root`` and lets the standard library keep ``$ref`` in scope.
      A boolean target conjoins the obvious way (``true`` leaves the siblings
      standing alone, ``false`` makes the whole node unsatisfiable); any other
      scalar target cannot conjoin with siblings at all and is refused by its
      ``$ref``.
    * ``"reference"`` reads OpenAPI 3.1 Reference Object positions
      (``components/responses``, ``headers``, ``parameters``, ``requestBodies``
      or ``securitySchemes`` entries): a Reference Object carries only
      ``$ref``, and every member beside it is decoration the reference does not
      merge, at *every* hop of a chain — if a hop lands on a node that is
      itself a ``$ref`` node, its siblings are stripped again and followed.
      Reference mode therefore never conjoins a sibling assertion. Members of
      a resolved document object are themselves document members and descend
      in reference mode, except in schema positions — the value of a ``schema``
      member, and entries under ``components/schemas`` (a pointer hop that
      lands there) — where Schema Object semantics apply and nested ``$ref``s
      keep the conjunction rules above.

    Dangling pointers, unsupported pointers and cycles raise the same
    ``ValueError``/``KeyError`` classes in both modes, so guarded readers turn
    them into named findings. Schema positions call :func:`resolve_refs`
    directly (schema mode is the default); Reference Object positions read
    through :func:`resolve_reference`.
    """
    if mode not in ("schema", "reference"):
        raise ValueError(f"unknown resolution mode {mode!r}; expected 'schema' or 'reference'")
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
            # Independent sibling subtrees see the stack as it stood before
            # this node's own pointer was pushed: a sibling re-referencing the
            # node's target is a second, self-contained assertion of the same
            # finite document, not a re-expansion of the target walk. Each
            # sibling gets a fresh copy so sibling chains stay independent of
            # one another; the target expansion keeps the pushed stack, which
            # is what still refuses genuine recursion.
            sibling_stack = deque(stack)
            stack.append(ref)
            try:
                # A Reference-Object hop that lands under ``components/schemas``
                # has landed on a Schema Object: its members are schema
                # keywords, so it descends with Schema Object semantics.
                target_mode = (
                    "schema" if mode == "reference" and ref.startswith("#/components/schemas/") else mode
                )
                resolved = resolve_refs(target, root=base, mode=target_mode, _stack=stack)
            finally:
                stack.pop()
            if mode == "reference":
                # Reference Object semantics: only ``$ref`` is meaningful here,
                # so the siblings are not even walked — decoration (including a
                # dangling pointer inside it) is inert and never merged.
                return resolved
            siblings = {
                key: resolve_refs(value, root=base, mode=mode, _stack=deque(sibling_stack))
                for key, value in document.items()
                if key != "$ref"
            }
            if isinstance(resolved, Mapping):
                if not siblings:
                    return resolved
                return {"allOf": [resolved, siblings]}
            if resolved is True:
                return siblings
            if resolved is False:
                return False
            if siblings:
                raise ValueError(
                    f"$ref {ref!r} targets {resolved!r}; a schema object cannot "
                    f"conjoin {sorted(siblings)} with it"
                )
            return resolved
        return {
            key: resolve_refs(
                value,
                root=base,
                mode="schema" if mode == "reference" and key == "schema" else mode,
                _stack=stack,
            )
            for key, value in document.items()
        }
    if isinstance(document, list):
        return [resolve_refs(item, root=base, mode=mode, _stack=stack) for item in document]
    return document


def resolve_reference(node: Any, root: Mapping[str, Any] | None = None) -> Any:
    """Inline a local ``$ref`` the way an OpenAPI Reference Object is resolved.

    A Reference Object (the ``$ref`` beside a response, header, parameter,
    requestBody or securityScheme) is not a Schema Object: OpenAPI 3.1 lets it
    carry only ``summary`` and ``description``, and neither augments the target
    — the rest is decoration the reference does not merge, at *every* hop of a
    reference chain, not just the first. So this is :func:`resolve_refs` in
    ``mode="reference"``: each hop strips the non-``$ref`` members it carries
    and follows its pointer (a hop that lands on another ``$ref`` node is
    stripped again), and members of a resolved document object descend in
    reference mode — except in schema positions (the value of a ``schema``
    member, and entries under ``components/schemas``), where Schema Object
    semantics apply and nested ``$ref``s keep the sibling-conjunction rules.
    Keeping a gate decision about the target independent of what rode along
    beside the reference is the whole point. Schema positions (Schema Objects,
    where siblings *are* assertions) keep :func:`resolve_refs` directly. A node
    without ``$ref`` is walked by the same reference-mode read — nested
    references in it are still inlined, with Reference Object semantics at
    every further hop.
    """
    return resolve_refs(node, root=root, mode="reference")


def check_local_refs(document: Mapping[str, Any]) -> str | None:
    """Return a short failure description when a document's local ``$ref``s do not resolve.

    The metaschema accepts any ``$ref`` that is a URI-reference, so a typo'd pointer
    (``#/$defs/index_file_entry`` written as ``#/$defs/index_file``) is a perfectly
    valid schema and still cannot be used: resolution happens lazily inside
    ``iter_errors``, where the raised ``KeyError`` would leave the CLI at exit 2
    "validator internal error". Checking resolution here, while the file is the thing
    being reported, is what turns that class of bad contract file into an exit-1
    finding named after the file.
    """
    try:
        resolve_refs(document)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        return f"unresolvable $ref: {error}"
    return None


def schema_error_report(
    schema: Mapping[str, Any],
    instance: Any,
    *,
    root: Mapping[str, Any] | None = None,
) -> list[tuple[str, str, str]]:
    """Return ``(property, keyword, message)`` for every schema violation.

    ``property`` is the last key of the failing instance path (or the special value
    ``""`` for errors at the document root), which lets callers suppress the generic
    schema code where a dedicated invariant already reports the same bound.

    Instances may hold :class:`~decimal.Decimal` (the media index is parsed that way);
    :data:`DRAFT202012_VALIDATOR` is the ordinary 2020-12 validator plus the integer
    branch that makes such an instance judgeable.

    ``root`` states which complete document the ``schema`` node was read out of, and
    is what keeps ``$ref`` in its JSON Schema scope. With no root the node is judged
    as it always has been — self-contained, its own ``#/…`` pointers resolving only
    inside itself. With a root the **raw, unexpanded** node is judged against a
    :class:`referencing.Registry` whose single resource at base URI ``""`` is the
    root document, so every ``#/…`` pointer resolves against the whole document
    offline (nothing leaves the machine) and — the part the
    ``{"allOf": [target, siblings]}`` pre-expansion of :func:`resolve_refs` cannot
    express (JSON Schema 2020-12 §11.3) — a ``unevaluatedProperties``/
    ``unevaluatedItems`` sibling of a ``$ref`` still observes the annotations the
    referenced target produced in its own scope. Because the validator anchors the
    *evaluated* schema as the resource bare ``#/…`` pointers resolve inside, the node
    is handed over as a member of a shallow copy of the root: the copy's own
    top-level ``$ref`` — never meaningful in an OpenAPI or media-document root —
    becomes the pointer to the node, and every other member, and every pointer the
    node or its targets spell, resolves exactly as in the committed document.
    """
    validator = _rooted_validator(schema, root)
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


def _rooted_validator(
    schema: Mapping[str, Any], root: Mapping[str, Any] | None
) -> DRAFT202012_VALIDATOR:
    """The instance validator :func:`schema_error_report` judges ``schema`` with.

    With no root (or with the whole document as its own schema, where today's
    self-contained read already resolves every pointer inside itself) this is
    the plain validator over the node. With a distinct root the node travels
    as :data:`_REPORT_TARGET_MEMBER` of a shallow copy of that root, so bare
    ``#/…`` pointers reach the document's own members while the validator
    still evaluates the raw node — ``$ref`` included, which the standard
    library follows through the offline registry without ever expanding the
    tree. A root that spells its own top-level ``$ref`` loses that assertion
    to the pointer onto the node: the node, never the root, is what this
    report judges, and no contract root spells one.
    """
    if root is None or root is schema:
        return DRAFT202012_VALIDATOR(schema, format_checker=FORMAT_CHECKER)
    registry = referencing.Registry().with_resource(
        _REPORT_BASE_URI,
        referencing.Resource.from_contents(
            root, default_specification=_2020_12_SPECIFICATION
        ),
    )
    rooted = dict(root)
    rooted[_REPORT_TARGET_MEMBER] = schema
    rooted["$ref"] = f"#/{_REPORT_TARGET_MEMBER}"
    return DRAFT202012_VALIDATOR(
        rooted, format_checker=FORMAT_CHECKER, registry=registry
    )


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
