"""Media-contract validation of one committed clip or active segment.

Every rule implemented here comes from ``docs/specs/media-format.md``; the code
names are stable because golden fixtures declare them (``tools/contracts/errors.py``).

The walk follows the recovery algorithm of section 6 on purpose: the index is
parsed line by line and stops at the first malformed, oversized, nonconsecutive,
out-of-range, nonmonotonic or CRC-failing entry, keeping only the maximal validated
prefix. That gives one focused code per defect instead of a cascade, which is what
makes the negative fixtures meaningful test vectors.
"""

from __future__ import annotations

import decimal
import json
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from . import errors as E
from .bounds import (
    JPEG_EOI,
    JPEG_SOI,
    ACTIVE_NAME,
    MAX_SEGMENT_DURATION_US,
    CHECKSUMS_NAME,
    CLIP_FILE_NAMES,
    CLOSE_REASONS,
    CLOCK_SOURCES,
    MAX_ACTIVE_BYTES,
    MAX_DIMENSION_PX,
    MAX_FRAMES_PER_CLIP,
    MAX_FRAME_BYTES,
    MAX_INDEX_BYTES,
    MAX_INDEX_LINE_BYTES,
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    MAX_PAYLOAD_BYTES,
    MEDIA_VERSION,
    MIN_FRAME_BYTES,
    MAX_NOMINAL_FPS,
    MIN_DIMENSION_PX,
    MIN_NOMINAL_FPS,
    PART_SUFFIX,
    UINT53_MAX,
)
from .errors import Violation
from .jpeg import JpegStructureError, decode_size, sof_dimensions
from .media_model import sha256_hex, split_index_lines
from .schema_docs import decimal_is_integral, schema_error_report

# Anchored with \A/\Z, not ^/$: a trailing newline is not a contract identifier, and
# a C writer that leaves the terminator in the buffer must be refused.
_LOWER_HEX_32 = re.compile(r"\A[0-9a-f]{32}\Z")
_LOWER_HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")
_CLIP_ID = re.compile(r"\A[0-9a-f]{32}-[0-9a-f]{8}\Z")
_RFC3339_MS_Z = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
_UTF8_BOM = b"\xef\xbb\xbf"

#: Every suppressed schema keyword must name the dedicated check that reports it
#: more precisely, and each of those checks has to be exercised by a committed
#: vector (``tests/test_error_codes.py``). A pair with no dedicated code here is a
#: suppression of nothing, and a pair whose dedicated check was deleted cannot pass
#: that test either: this table is the only way a keyword can be silenced.
FRAME_DEDICATED_RULES: Final[Mapping[tuple[str, str], tuple[str, ...]]] = {
    ("v", "const"): (E.VERSION_UNSUPPORTED,),
    ("size", "minimum"): (E.FRAME_SIZE_INVALID,),
    ("size", "maximum"): (E.FRAME_SIZE_INVALID,),
    ("t_us", "minimum"): (E.FRAME_T_US_TOO_LARGE,),
    ("t_us", "maximum"): (E.FRAME_T_US_TOO_LARGE,),
    # seq must equal its own record number, and :func:`_walk_index` refuses any record
    # at or past ``MAX_FRAMES_PER_CLIP`` before it is even parsed, so a seq outside
    # 0..3599 can only arrive through one of those two findings. The walk gate is what
    # covers an active segment: it has no ``frame_count`` for the manifest bound to
    # catch, so without that gate this suppression would silence the ceiling entirely.
    ("seq", "minimum"): (E.FRAME_SEQ_NOT_CONSECUTIVE, E.FRAME_COUNT_MISMATCH),
    ("seq", "maximum"): (E.FRAME_SEQ_NOT_CONSECUTIVE, E.FRAME_COUNT_MISMATCH),
    # offset is bounded by the payload walk and the 2^53-1 arithmetic gate.
    ("offset", "maximum"): (E.OFFSET_EXCEEDS_PAYLOAD, E.OFFSET_ARITHMETIC_OVERFLOW),
    ("crc32", "pattern"): (E.FRAME_CRC_MISMATCH,),
}

MANIFEST_DEDICATED_RULES: Final[Mapping[tuple[str, str], tuple[str, ...]]] = {
    ("v", "const"): (E.VERSION_UNSUPPORTED,),
    ("device_id", "pattern"): (E.ID_SYNTAX_INVALID,),
    ("boot_id", "pattern"): (E.ID_SYNTAX_INVALID,),
    ("clip_id", "pattern"): (E.ID_SYNTAX_INVALID, E.CLIP_BOOT_PREFIX_MISMATCH),
    ("close_reason", "enum"): (E.CLOSE_REASON_UNKNOWN, E.RECOVERED_CLOSE_REASON_DISAGREE),
    ("duration_us", "minimum"): (E.DURATION_LE_FINAL_T_US,),
    ("duration_us", "maximum"): (E.DURATION_TOO_LONG,),
    ("width", "minimum"): (E.DIMENSIONS_EXCEEDED,),
    ("width", "maximum"): (E.DIMENSIONS_EXCEEDED,),
    ("height", "minimum"): (E.DIMENSIONS_EXCEEDED,),
    ("height", "maximum"): (E.DIMENSIONS_EXCEEDED,),
    ("nominal_fps", "minimum"): (E.NOMINAL_FPS_INVALID,),
    ("nominal_fps", "maximum"): (E.NOMINAL_FPS_INVALID,),
    ("source", "enum"): (E.CLOCK_SOURCE_UNKNOWN_VALUE,),
    ("start_utc", "pattern"): (E.CLOCK_TIMESTAMP_INVALID,),
    # The shape *and* the calendar: _clock_violations parses the timestamp for real, so
    # it reports an impossible date more precisely than a format keyword can, and the
    # strict checker in schema_docs is what makes that keyword mean anything at all.
    ("start_utc", "format"): (E.CLOCK_TIMESTAMP_INVALID,),
    # The count is checked against the records actually walked, so both bounds are
    # reported by that comparison (an empty index also reports INDEX_EMPTY).
    ("frame_count", "minimum"): (E.FRAME_COUNT_MISMATCH, E.INDEX_EMPTY),
    ("frame_count", "maximum"): (E.FRAME_COUNT_MISMATCH,),
}

_FRAME_SUPPRESSED: frozenset[tuple[str, str]] = frozenset(FRAME_DEDICATED_RULES)
_MANIFEST_SUPPRESSED: frozenset[tuple[str, str]] = frozenset(MANIFEST_DEDICATED_RULES)

#: The pairs :func:`validate_manifest_fields` re-reports, and so the only pairs the HTTP
#: layer may silence while running it. Deliberately narrower than
#: :data:`_MANIFEST_SUPPRESSED`: a wire body meets those six rules and none of the numeric
#: bounds, and silencing a keyword whose dedicated check never ran on this path would leave
#: the defect reported by nobody at all.
#:
#: The three ``type`` rows are here because a member of the wrong type is still a *present*
#: member, and those rules refuse any present value that is not the string they name; without
#: them an integer ``device_id`` would be reported twice for one defect. ``start_utc`` and
#: ``recovered`` are deliberately absent: their rules read a string and a bool and stay silent
#: on a member of some other type, so the mirror's own keyword is the only thing that can name
#: such a value on this path.
MANIFEST_WIRE_SUPPRESSED: frozenset[tuple[str, str]] = frozenset(
    {
        ("v", "const"),
        ("device_id", "pattern"),
        ("device_id", "type"),
        ("boot_id", "pattern"),
        ("boot_id", "type"),
        ("clip_id", "pattern"),
        ("clip_id", "type"),
        ("close_reason", "enum"),
        ("source", "enum"),
        ("start_utc", "pattern"),
        ("start_utc", "format"),
    }
)


@dataclass
class _Walk:
    """Result of the maximal-validated-prefix index walk."""

    records: list[dict[str, Any]] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    stopped: bool = False


def validate_media_fixture(
    root: Path,
    entry: Mapping[str, Any],
    schemas: Mapping[str, Mapping[str, Any]],
) -> list[Violation]:
    """Validate one committed media vector against the media contract.

    ``root`` is the fixtures directory, ``entry`` is its ``fixtures.json`` record and
    ``schemas`` holds the parsed ``contracts/media-v1`` documents.
    """
    violations: list[Violation] = []
    fixture_dir = root / str(entry["id"])
    committed = [str(name) for name in entry.get("files", [])]
    active_state = entry["kind"] == "active"
    payload_name = CLIP_FILE_NAMES[0] + (PART_SUFFIX if active_state else "")
    index_name = CLIP_FILE_NAMES[1] + (PART_SUFFIX if active_state else "")
    record_name = ACTIVE_NAME if active_state else MANIFEST_NAME

    if not fixture_dir.is_dir():
        return [Violation(E.FIXTURE_FILE_MISSING, str(entry["id"]), "fixture directory absent")]
    for name in committed:
        if not (fixture_dir / name).is_file():
            violations.append(Violation(E.FIXTURE_FILE_MISSING, f"{entry['id']}/{name}"))
    if violations:
        return violations
    for path in sorted(fixture_dir.iterdir()):
        if path.is_file() and path.name not in committed:
            violations.append(
                Violation(
                    E.CLIP_FILE_UNEXPECTED,
                    f"{entry['id']}/{path.name}",
                    "not declared in fixtures.json",
                )
            )

    if record_name not in committed:
        # The record is what names the clip, so its absence is the defect itself.
        return [
            Violation(
                E.ACTIVE_JSON_INVALID if active_state else E.MANIFEST_MISSING,
                f"{entry['id']}/{record_name}",
                "the required record is not part of the committed file set",
            )
        ]
    if active_state and MANIFEST_NAME in committed:
        return [
            Violation(
                E.ACTIVE_WITH_MANIFEST,
                f"{entry['id']}/{MANIFEST_NAME}",
                "an interrupted segment publishes active.json and no completion manifest",
            )
        ]

    payload = (fixture_dir / payload_name).read_bytes()
    index = (fixture_dir / index_name).read_bytes()
    record_bytes = (fixture_dir / record_name).read_bytes()

    if len(payload) > MAX_PAYLOAD_BYTES:
        violations.append(
            Violation(E.PAYLOAD_TOO_LARGE, f"{entry['id']}/{payload_name}", f"{len(payload)} bytes")
        )
    if len(index) > MAX_INDEX_BYTES:
        violations.append(
            Violation(E.INDEX_TOO_LARGE, f"{entry['id']}/{index_name}", f"{len(index)} bytes")
        )

    bound = MAX_ACTIVE_BYTES if active_state else MAX_MANIFEST_BYTES
    if len(record_bytes) > bound:
        violations.append(
            Violation(
                E.ACTIVE_TOO_LARGE if active_state else E.MANIFEST_TOO_LARGE,
                f"{entry['id']}/{record_name}",
                f"{len(record_bytes)} bytes exceeds the {bound}-byte bound",
            )
        )
        # Refuse an over-limit record before parsing it: the bound exists to keep a
        # hostile document from being read into memory in the first place.
        return violations
    try:
        # ``parse_float=decimal.Decimal`` for the same reason the index walk parses that
        # way (see :func:`_walk_index`): the manifest's durations, counts and byte
        # lengths are integers the contract bounds exactly, and a binary-float read of
        # ``266667.000000000001`` rounds into a value every ``type: integer`` check and
        # every dedicated bound below would then read as the integer ``266667``. The
        # digits the writer sent are what the bounds have to judge.
        record = json.loads(record_bytes.decode("utf-8"), parse_float=decimal.Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        violations.append(
            Violation(
                E.ACTIVE_JSON_INVALID if active_state else E.MANIFEST_JSON_INVALID,
                f"{entry['id']}/{record_name}",
                str(error).replace("\n", " "),
            )
        )
        # A record that will not parse cannot inform any later check.
        return violations
    if not isinstance(record, dict):
        violations.append(
            Violation(
                E.ACTIVE_JSON_INVALID if active_state else E.MANIFEST_JSON_INVALID,
                f"{entry['id']}/{record_name}",
                "top level is not a JSON object",
            )
        )
        return violations

    profile = record.get("profile") if isinstance(record.get("profile"), Mapping) else None
    width = profile.get("width") if profile is not None else None
    height = profile.get("height") if profile is not None else None
    dims_in_bounds = (
        _is_int(width)
        and _is_int(height)
        and MIN_DIMENSION_PX <= width <= MAX_DIMENSION_PX
        and MIN_DIMENSION_PX <= height <= MAX_DIMENSION_PX
    )

    walk = _Walk()
    encoding_problem = _index_encoding_problem(index)
    if encoding_problem is not None:
        walk.stopped = True
        walk.violations.append(
            Violation(
                E.INDEX_ENCODING_INVALID,
                f"{entry['id']}/{index_name}",
                encoding_problem,
            )
        )
    elif not index:
        walk.stopped = True
        walk.violations.append(Violation(E.INDEX_EMPTY, f"{entry['id']}/{index_name}"))
    else:
        walk = _walk_index(
            index,
            payload,
            frame_schema=schemas["frame"],
            width=width if dims_in_bounds else None,
            height=height if dims_in_bounds else None,
        )

    if not walk.stopped and walk.records:
        declared_end = walk.records[-1]["offset"] + walk.records[-1]["size"]
        if declared_end < len(payload):
            violations.append(
                Violation(
                    E.PAYLOAD_TRAILING_BYTES,
                    f"{entry['id']}/{payload_name}",
                    f"index ends at {declared_end} but the payload is {len(payload)} bytes",
                )
            )
        if not active_state and record.get("frame_count") != len(walk.records):
            violations.append(
                Violation(
                    E.FRAME_COUNT_MISMATCH,
                    f"{entry['id']}/{record_name}",
                    f"frame_count {record.get('frame_count')!r} but {len(walk.records)} validated records",
                )
            )

    violations.extend(walk.violations)

    if active_state:
        violations.extend(_validate_active_record(record, schemas["active"]))
    else:
        violations.extend(
            _validate_manifest(
                record,
                schemas["manifest"],
                payload=payload,
                index=index,
                records=walk.records,
            )
        )

    if CHECKSUMS_NAME in committed:
        violations.extend(_validate_checksums(fixture_dir, committed))

    return violations


def _index_encoding_problem(index: bytes) -> str | None:
    """Return why this index is not LF-only UTF-8 JSONL, or ``None`` when it is."""
    if index.startswith(_UTF8_BOM):
        return "UTF-8 BOM before the first line"
    if b"\r" in index:
        return "CR byte present; the index is LF-only"
    try:
        index.decode("utf-8")
    except UnicodeDecodeError:
        return "index is not valid UTF-8"
    parts = index.split(b"\n")
    if any(part == b"" for part in parts[:-1]):
        return "blank line inside the index"
    return None


def _walk_index(
    index: bytes,
    payload: bytes,
    *,
    frame_schema: Mapping[str, Any],
    width: int | None,
    height: int | None,
) -> _Walk:
    """Parse the index until the first unusable entry, checking every bound."""
    walk = _Walk()
    previous_end = 0
    previous_t_us: int | None = None
    for position, (raw_line, body) in enumerate(split_index_lines(index)):
        if position >= MAX_FRAMES_PER_CLIP:
            # One gate for both segment kinds, before this record is measured or
            # parsed: media-format.md §2 keeps at most 3,600 frames in a clip, and an
            # active segment has no `frame_count` for the manifest bound to catch, so
            # the walk is the only thing that can refuse the 3,601st record.
            walk.violations.append(
                Violation(
                    E.FRAME_COUNT_MISMATCH,
                    f"line {position + 1}",
                    f"a clip retains at most {MAX_FRAMES_PER_CLIP} frames, and this is "
                    f"record number {position}",
                )
            )
            walk.stopped = True
            return walk
        location = f"line {position + 1}"
        if len(raw_line) > MAX_INDEX_LINE_BYTES:
            walk.violations.append(
                Violation(
                    E.FRAME_LINE_TOO_LONG,
                    location,
                    f"{len(raw_line)} bytes including the newline exceeds {MAX_INDEX_LINE_BYTES}",
                )
            )
            walk.stopped = True
            return walk
        if body == b"":
            walk.violations.append(Violation(E.FRAME_LINE_MALFORMED, location, "blank line"))
            walk.stopped = True
            return walk
        if not raw_line.endswith(b"\n"):
            walk.violations.append(
                Violation(
                    E.INDEX_TRUNCATED,
                    location,
                    "final line has no LF terminator; only the preceding records are a valid prefix",
                )
            )
            walk.stopped = True
            return walk
        try:
            # ``parse_float=Decimal`` keeps the notation a record has to survive on.
            # The default float conversion turns ``1e-400`` into exactly ``0.0``, and a
            # timestamp written that way would then read as a legal zero through every
            # check below; as a ``Decimal`` it stays the fraction the frame record's
            # ``type: integer`` refuses. ``1e999`` becomes ``inf`` under that same
            # default — an integral float to Python, and an ``OverflowError`` in the
            # ``int()`` further down — and stays an exact, enormous integer as a
            # ``Decimal``, which the bounds below refuse as the out-of-range value it is.
            record = json.loads(body.decode("utf-8"), parse_float=decimal.Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            walk.violations.append(
                Violation(E.FRAME_LINE_MALFORMED, location, str(error).replace("\n", " "))
            )
            walk.stopped = True
            return walk
        if not isinstance(record, dict):
            walk.violations.append(Violation(E.FRAME_LINE_NOT_OBJECT, location))
            walk.stopped = True
            return walk

        explicit = _record_bound_violations(record, location)
        structural = [
            finding
            for finding in schema_error_report(frame_schema, record)
            if (finding[0], finding[1]) not in _FRAME_SUPPRESSED
        ]
        if explicit or structural:
            walk.violations.extend(explicit)
            for property_name, keyword, message in structural:
                code = E.FRAME_SCHEMA_MISSING_FIELD if keyword == "required" else E.FRAME_SCHEMA
                where = f"{location}{f' at {property_name}' if property_name else ''}"
                walk.violations.append(Violation(code, where, message))
            walk.stopped = True
            return walk

        seq = record["seq"]
        offset = record["offset"]
        size = record["size"]
        t_us = record["t_us"]

        # Gating findings: these make every later record unverifiable, so the walk
        # stops at the first one (section 6 keeps only the maximal valid prefix).
        #
        # Byte positions come first, because everything below does arithmetic with
        # them. `type: integer` in the frame schema accepts any JSON integer notation,
        # so `0`, `0.0` and `0e0` are all a legal way to write the same offset; the
        # published contract says so, and this package's own bounds checks agree. What
        # the schema cannot express is that a byte position has to *index*: a slice and
        # a length need real `int`s. So the notation is accepted on the schema's terms
        # and normalised before the first addition, rather than refused for a spelling
        # the contract publishes as valid. A value that is not an integer in any
        # notation (5.5, a string, a bool) is refused here too: the `type` report above
        # already names it, and this keeps such a value out of the arithmetic and the
        # slice whatever path it came by. A missing offset or size is not this branch's
        # to catch — the `required` report above refuses the record before either field
        # is even read, so there is no absent case to see here.
        if not all(_is_int(record[name]) for name in ("seq", "offset", "size", "t_us")):
            walk.violations.append(
                Violation(
                    E.FRAME_SCHEMA,
                    location,
                    f"seq {seq!r}, offset {offset!r}, size {size!r} and t_us {t_us!r} must be "
                    f"JSON integers in some notation, per the frame record's `type: integer`",
                )
            )
            walk.stopped = True
            return walk
        # Every one of the four is now a value ``int()`` may be handed: :func:`_is_int`
        # refuses the non-numbers JSON admits no notation for (``Infinity`` and ``NaN``
        # literals, and their ``Decimal`` spellings), so nothing below can raise where the
        # contract wants a code, and the notation may be ``0e0`` or ``1.20000001e8`` while
        # the arithmetic, the comparisons and the slice all need real ``int``s.
        seq, offset, size, t_us = (int(record[name]) for name in ("seq", "offset", "size", "t_us"))

        if seq != position:
            walk.violations.append(
                Violation(
                    E.FRAME_SEQ_NOT_CONSECUTIVE,
                    location,
                    f"seq {seq} but record number {position}",
                )
            )
            walk.stopped = True
            return walk
        if previous_t_us is None:
            if t_us != 0:
                walk.violations.append(
                    Violation(
                        E.FRAME_T_US_FIRST_NOT_ZERO,
                        location,
                        f"first t_us is {t_us}; it must be zero",
                    )
                )
                walk.stopped = True
                return walk
        else:
            if t_us == previous_t_us:
                walk.violations.append(
                    Violation(
                        E.FRAME_T_US_DUPLICATE,
                        location,
                        f"t_us {t_us} repeats the previous record; drop the frame and count it",
                    )
                )
                walk.stopped = True
                return walk
            if t_us < previous_t_us:
                walk.violations.append(
                    Violation(
                        E.FRAME_T_US_NOT_INCREASING,
                        location,
                        f"t_us {t_us} is below the previous {previous_t_us}",
                    )
                )
                walk.stopped = True
                return walk
        if offset + size > UINT53_MAX:
            walk.violations.append(
                Violation(
                    E.OFFSET_ARITHMETIC_OVERFLOW,
                    location,
                    f"offset {offset} + size {size} overflows the 2^53-1 range; refuse before reading",
                )
            )
            walk.stopped = True
            return walk
        if offset != previous_end:
            walk.violations.append(
                Violation(
                    E.OFFSET_NOT_CONTIGUOUS,
                    location,
                    f"offset {offset} but the previous record ended at {previous_end}",
                )
            )
            walk.stopped = True
            return walk
        if offset + size > len(payload):
            walk.violations.append(
                Violation(
                    E.OFFSET_EXCEEDS_PAYLOAD,
                    location,
                    f"offset {offset} + size {size} passes the payload end {len(payload)}",
                )
            )
            walk.stopped = True
            return walk

        # Content findings for this one record: collect all of them, then stop. The
        # two positions are plain `int`s by now whatever notation the line used, so
        # this slice is always one a reader could take.
        frame = payload[offset : offset + size]
        if format(zlib.crc32(frame) & 0xFFFFFFFF, "08x") != record["crc32"]:
            walk.violations.append(
                Violation(
                    E.FRAME_CRC_MISMATCH,
                    location,
                    f"declared crc32 {record['crc32']!r} is not the CRC of these {len(frame)} bytes",
                )
            )
        walk.violations.extend(_jpeg_violations(frame, location, width=width, height=height))
        if walk.violations:
            walk.stopped = True
            return walk

        walk.records.append(record)
        previous_end = offset + size
        previous_t_us = t_us
    return walk


def _record_bound_violations(record: Mapping[str, Any], location: str) -> list[Violation]:
    """Bounds checked explicitly so each one reports its own stable code."""
    found: list[Violation] = []

    if record.get("v") != MEDIA_VERSION:
        # An index line written by a future writer is not this contract's record.
        found.append(
            Violation(E.VERSION_UNSUPPORTED, location, f"record v {record.get('v')!r}")
        )
    size = record.get("size")
    if _is_int(size) and not MIN_FRAME_BYTES <= size <= MAX_FRAME_BYTES:
        found.append(
            Violation(
                E.FRAME_SIZE_INVALID,
                location,
                f"size {size} is outside {MIN_FRAME_BYTES}..{MAX_FRAME_BYTES} bytes",
            )
        )
    t_us = record.get("t_us")
    if _is_int(t_us) and not 0 <= t_us <= MAX_SEGMENT_DURATION_US:
        found.append(
            Violation(
                E.FRAME_T_US_TOO_LARGE,
                location,
                f"t_us {t_us} is outside 0..{MAX_SEGMENT_DURATION_US}",
            )
        )
    return found


def _jpeg_violations(
    frame: bytes, location: str, *, width: int | None, height: int | None
) -> list[Violation]:
    """SOI/EOI markers, a real Pillow decode and the SOF dimension agreement."""
    found: list[Violation] = []
    if not frame.startswith(JPEG_SOI):
        return [Violation(E.JPEG_SOI_MISSING, location, "payload slice does not start with SOI")]
    if not frame.endswith(JPEG_EOI):
        return [Violation(E.JPEG_EOI_MISSING, location, "payload slice does not end with EOI")]
    try:
        decoded = decode_size(frame)
    except JpegStructureError as error:
        return [Violation(E.JPEG_DECODE_FAILED, location, str(error).replace("\n", " ")[:160])]
    try:
        sof = sof_dimensions(frame)
    except JpegStructureError as error:
        return [Violation(E.JPEG_DECODE_FAILED, location, f"marker chain: {error}")]
    if sof is None:
        found.append(Violation(E.JPEG_DECODE_FAILED, location, "no SOF segment found"))
    elif (width, height) != (None, None) and sof != (width, height):
        found.append(
            Violation(
                E.JPEG_SOF_DIMENSION_MISMATCH,
                location,
                f"JPEG SOF {sof[0]}x{sof[1]} disagrees with the manifest profile {width}x{height}",
            )
        )
    if decoded != sof:
        found.append(
            Violation(
                E.JPEG_DECODE_FAILED,
                location,
                f"decoder reported {decoded[0]}x{decoded[1]} but SOF reported {sof[0]}x{sof[1]}",
            )
        )
    return found


def validate_manifest_fields(
    record: Mapping[str, Any],
    *,
    location_prefix: str = "manifest",
) -> list[Violation]:
    """Manifest identity, close-reason and clock rules, callable without a clip.

    These six checks need nothing but the manifest record itself: no payload, no
    index, no schema document.  That makes them the rules the HTTP layer can run
    over a decoded ``manifest_base64url`` — a POST /uploads body or a
    ``GET /clips/{clip_id}/manifest`` response — before it trusts that manifest to
    name a clip at all.  The clip-directory validator calls the same function from
    :func:`_validate_manifest`, so a manifest is refused for the same reason over
    either transport, and the reported location is the caller's own naming of the
    place the record came from (``manifest`` for a clip directory,
    ``manifest_base64url`` for a wire body).
    """
    found: list[Violation] = []
    # Absence is the schema's to report — required-ness is a `required` keyword, and a
    # wire body that omitted these members is already refused as a schema violation —
    # so each rule below judges a member that is actually there. Without that gate a
    # body of `{"v": 1}` would be reported six times over for the shape it never
    # claimed, and the one finding that describes it would be buried.
    if record.get("v") != MEDIA_VERSION:
        found.append(
            Violation(E.VERSION_UNSUPPORTED, location_prefix, f"v {record.get('v')!r}")
        )
    for field_name in ("device_id", "boot_id"):
        if field_name not in record:
            continue
        value = record.get(field_name)
        if not isinstance(value, str) or _LOWER_HEX_32.match(value) is None:
            found.append(
                Violation(
                    E.ID_SYNTAX_INVALID,
                    f"{location_prefix}.{field_name}",
                    "must be 32 lowercase hexadecimal characters",
                )
            )
    clip_id = record.get("clip_id")
    boot_id = record.get("boot_id")
    if "clip_id" in record and (not isinstance(clip_id, str) or _CLIP_ID.match(clip_id) is None):
        found.append(
            Violation(
                E.ID_SYNTAX_INVALID,
                f"{location_prefix}.clip_id",
                "must be <32 hex>-<8 hex>",
            )
        )
    elif (
        isinstance(clip_id, str)
        and isinstance(boot_id, str)
        and clip_id.split("-", 1)[0] != boot_id
    ):
        found.append(
            Violation(
                E.CLIP_BOOT_PREFIX_MISMATCH,
                f"{location_prefix}.clip_id",
                "the boot_id prefix of clip_id must equal boot_id",
            )
        )

    close_reason = record.get("close_reason")
    if "close_reason" in record and close_reason not in CLOSE_REASONS:
        found.append(
            Violation(
                E.CLOSE_REASON_UNKNOWN,
                f"{location_prefix}.close_reason",
                f"{close_reason!r} is not one of {', '.join(CLOSE_REASONS)}",
            )
        )
    recovered = record.get("recovered")
    if isinstance(recovered, bool) and recovered != (close_reason == "recovery"):
        found.append(
            Violation(
                E.RECOVERED_CLOSE_REASON_DISAGREE,
                f"{location_prefix}.recovered",
                f"recovered {recovered!r} with close_reason {close_reason!r}",
            )
        )

    if "clock" in record:
        found.extend(_clock_violations(record["clock"], f"{location_prefix}.clock"))
    return found


def _validate_manifest(
    record: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    payload: bytes,
    index: bytes,
    records: Sequence[dict[str, Any]],
) -> list[Violation]:
    """Manifest cross-field rules from media-format.md §2 and §4."""
    found: list[Violation] = validate_manifest_fields(record)

    frame_count = record.get("frame_count")
    if _is_int(frame_count) and not 1 <= frame_count <= MAX_FRAMES_PER_CLIP:
        found.append(
            Violation(
                E.FRAME_COUNT_MISMATCH,
                "manifest.frame_count",
                f"{frame_count} is outside 1..{MAX_FRAMES_PER_CLIP} retained frames",
            )
        )

    duration_us = record.get("duration_us")
    if _is_int(duration_us):
        if duration_us > MAX_SEGMENT_DURATION_US:
            found.append(
                Violation(
                    E.DURATION_TOO_LONG,
                    "manifest.duration_us",
                    f"{duration_us} exceeds the {MAX_SEGMENT_DURATION_US:,} us segment maximum",
                )
            )
        elif records and duration_us <= records[-1]["t_us"]:
            found.append(
                Violation(
                    E.DURATION_LE_FINAL_T_US,
                    "manifest.duration_us",
                    f"{duration_us} does not exceed the final t_us {records[-1]['t_us']}",
                )
            )

    found.extend(_profile_bound_violations(record.get("profile"), "manifest.profile"))

    files = record.get("files")
    if isinstance(files, Mapping):
        actual = {CLIP_FILE_NAMES[0]: payload, CLIP_FILE_NAMES[1]: index}
        for name, data in actual.items():
            entry = files.get(name)
            if not isinstance(entry, Mapping):
                continue  # the schema reports a missing file entry
            declared_bytes = entry.get("bytes")
            declared_sha = entry.get("sha256")
            # A file entry the validator cannot measure is a defect, not a check to
            # skip: silently passing a malformed declaration would let a manifest
            # state no length at all and still certify the bytes beside it.
            if not _is_int(declared_bytes):
                found.append(
                    Violation(
                        E.MANIFEST_SIZE_MISMATCH,
                        f"manifest.files.{name}.bytes",
                        f"declares {declared_bytes!r}; the length must be a JSON integer "
                        f"so the {len(data)} committed bytes can be checked against it",
                    )
                )
            elif declared_bytes != len(data):
                found.append(
                    Violation(
                        E.MANIFEST_SIZE_MISMATCH,
                        f"manifest.files.{name}.bytes",
                        f"declares {declared_bytes}, the file is {len(data)}",
                    )
                )
            if not isinstance(declared_sha, str) or _LOWER_HEX_64.match(declared_sha) is None:
                found.append(
                    Violation(
                        E.MANIFEST_HASH_MISMATCH,
                        f"manifest.files.{name}.sha256",
                        f"declares {_shape(declared_sha)}; the digest must be exactly 64 "
                        f"lowercase hexadecimal characters to be compared at all",
                    )
                )
            elif declared_sha != sha256_hex(data):
                found.append(
                    Violation(
                        E.MANIFEST_HASH_MISMATCH,
                        f"manifest.files.{name}.sha256",
                        "the committed bytes hash differently",
                    )
                )

    for property_name, keyword, message in schema_error_report(schema, record):
        if (property_name, keyword) in _MANIFEST_SUPPRESSED:
            continue
        code = E.MANIFEST_SCHEMA_MISSING_FIELD if keyword == "required" else E.MANIFEST_SCHEMA
        found.append(
            Violation(code, f"manifest{f'.{property_name}' if property_name else ''}", message)
        )
    return found


def _validate_active_record(record: Mapping[str, Any], schema: Mapping[str, Any]) -> list[Violation]:
    """Active-state record rules from media-format.md §5."""
    found: list[Violation] = []
    if record.get("v") != MEDIA_VERSION:
        found.append(Violation(E.VERSION_UNSUPPORTED, "active", f"v {record.get('v')!r}"))
    for field_name in ("device_id", "boot_id"):
        value = record.get(field_name)
        if not isinstance(value, str) or _LOWER_HEX_32.match(value) is None:
            found.append(
                Violation(E.ID_SYNTAX_INVALID, f"active.{field_name}", "not 32 lowercase hex")
            )
    clip_id = record.get("clip_id")
    boot_id = record.get("boot_id")
    if not isinstance(clip_id, str) or _CLIP_ID.match(clip_id) is None:
        found.append(Violation(E.ID_SYNTAX_INVALID, "active.clip_id", "not <32 hex>-<8 hex>"))
    elif isinstance(boot_id, str) and clip_id.split("-", 1)[0] != boot_id:
        found.append(
            Violation(
                E.CLIP_BOOT_PREFIX_MISMATCH,
                "active.clip_id",
                "the boot_id prefix of clip_id must equal boot_id",
            )
        )
    found.extend(_profile_bound_violations(record.get("profile"), "active.profile"))
    found.extend(_clock_violations(record.get("clock"), "active.clock"))
    for property_name, keyword, message in schema_error_report(schema, record):
        if (property_name, keyword) in _MANIFEST_SUPPRESSED:
            continue
        found.append(
            Violation(
                E.ACTIVE_SCHEMA,
                f"active{f'.{property_name}' if property_name else ''}",
                message,
            )
        )
    return found


def _profile_bound_violations(profile: Any, location: str) -> list[Violation]:
    """The recording profile bounds of media-format.md §2, for both record kinds.

    The active record reuses the manifest's field rules (§5), so it gets exactly the
    same explicit bounds; without this the suppressed schema keywords would silence
    the profile on an interrupted segment.
    """
    found: list[Violation] = []
    if not isinstance(profile, Mapping):
        return found  # the schema reports the shape
    for key in ("width", "height"):
        value = profile.get(key)
        if _is_int(value) and not MIN_DIMENSION_PX <= value <= MAX_DIMENSION_PX:
            found.append(
                Violation(
                    E.DIMENSIONS_EXCEEDED,
                    f"{location}.{key}",
                    f"{value} is outside {MIN_DIMENSION_PX}..{MAX_DIMENSION_PX} px",
                )
            )
    fps = profile.get("nominal_fps")
    if _is_int(fps) and not MIN_NOMINAL_FPS <= fps <= MAX_NOMINAL_FPS:
        found.append(
            Violation(
                E.NOMINAL_FPS_INVALID,
                f"{location}.nominal_fps",
                f"{fps} is outside {MIN_NOMINAL_FPS}..{MAX_NOMINAL_FPS} frames per second",
            )
        )
    return found


def _clock_violations(clock: Any, location: str) -> list[Violation]:
    """The null-ness pairing and RFC3339 form that keeps unknown UTC unknown."""
    found: list[Violation] = []
    if not isinstance(clock, Mapping):
        return found  # the schema reports the shape
    source = clock.get("source")
    if source not in CLOCK_SOURCES:
        found.append(
            Violation(
                E.CLOCK_SOURCE_UNKNOWN_VALUE,
                f"{location}.source",
                f"{source!r} is not one of {', '.join(CLOCK_SOURCES)}",
            )
        )
        return found
    start_utc = clock.get("start_utc")
    uncertainty = clock.get("uncertainty_ms")
    if source == "unknown":
        if start_utc is not None or uncertainty is not None:
            found.append(
                Violation(
                    E.CLOCK_NULLITY_MISMATCH,
                    location,
                    "an unknown clock source requires start_utc and uncertainty_ms to both be null",
                )
            )
    else:
        if start_utc is None or uncertainty is None:
            found.append(
                Violation(
                    E.CLOCK_NULLITY_MISMATCH,
                    location,
                    f"a {source} clock requires both start_utc and uncertainty_ms",
                )
            )
        if _is_int(uncertainty) and uncertainty < 0:
            found.append(
                Violation(
                    E.CLOCK_NULLITY_MISMATCH,
                    f"{location}.uncertainty_ms",
                    f"{uncertainty} is negative; an estimate is never negative",
                )
            )
        elif _is_int(uncertainty) and uncertainty > UINT53_MAX:
            # media-format.md §2 puts every JSON integer of this format inside the
            # range a conforming reader represents exactly, so an uncertainty the
            # schema's own ceiling keyword also refuses is reported here, where the
            # pairing rule lives and where the number can be named.
            found.append(
                Violation(
                    E.CLOCK_NULLITY_MISMATCH,
                    f"{location}.uncertainty_ms",
                    f"{uncertainty} is above the {UINT53_MAX} shared JSON integer ceiling",
                )
            )
    if isinstance(start_utc, str):
        if _RFC3339_MS_Z.match(start_utc) is None:
            found.append(
                Violation(
                    E.CLOCK_TIMESTAMP_INVALID,
                    f"{location}.start_utc",
                    f"{start_utc!r} is not RFC3339 UTC with millisecond precision and trailing Z",
                )
            )
        else:
            try:
                datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError as error:
                found.append(
                    Violation(
                        E.CLOCK_TIMESTAMP_INVALID,
                        f"{location}.start_utc",
                        f"{start_utc!r}: {error}",
                    )
                )
    return found


def _validate_checksums(fixture_dir: Path, committed: list[str]) -> list[Violation]:
    """The harness ``checksums.json`` must describe the other committed files exactly."""
    name = CHECKSUMS_NAME
    path = fixture_dir / name
    found: list[Violation] = []
    expected = {file_name for file_name in committed if file_name != name}
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [Violation(E.CHECKSUMS_SCHEMA, name, str(error).replace("\n", " "))]
    if not isinstance(document, Mapping) or document.get("v") != MEDIA_VERSION:
        return [Violation(E.CHECKSUMS_SCHEMA, name, "must be an object with v: 1")]
    entries = document.get("files")
    if not isinstance(entries, Mapping):
        return [Violation(E.CHECKSUMS_SCHEMA, name, "files must be an object")]
    if set(entries) != expected:
        found.append(
            Violation(
                E.CHECKSUMS_SCHEMA,
                name,
                f"describes {sorted(entries)} but the clip ships {sorted(expected)}",
            )
        )
    for file_name in sorted(expected):
        entry = entries.get(file_name)
        data = (fixture_dir / file_name).read_bytes()
        if not isinstance(entry, Mapping):
            found.append(Violation(E.CHECKSUMS_SCHEMA, f"{name}:{file_name}", "entry missing"))
            continue
        declared_bytes = entry.get("bytes")
        declared_sha = entry.get("sha256")
        # Both integrity fields are compared or reported, never skipped: a digest with
        # a stray byte or a length that is not a number would otherwise certify a file
        # nobody ever measured.
        if not _is_int(declared_bytes):
            found.append(
                Violation(
                    E.CHECKSUMS_SCHEMA,
                    f"{name}:{file_name}",
                    f"records {_shape(declared_bytes)} as its length; the byte count must be "
                    f"a JSON integer to be compared at all",
                )
            )
        elif declared_bytes != len(data):
            found.append(
                Violation(
                    E.CHECKSUM_SIZE_MISMATCH,
                    f"{name}:{file_name}",
                    f"records {declared_bytes} bytes, the file is {len(data)}",
                )
            )
        if not isinstance(declared_sha, str) or _LOWER_HEX_64.match(declared_sha) is None:
            found.append(
                Violation(
                    E.CHECKSUMS_SCHEMA,
                    f"{name}:{file_name}",
                    f"records {_shape(declared_sha)} as its digest; the checksum must be "
                    f"exactly 64 lowercase hexadecimal characters to be compared at all",
                )
            )
        elif declared_sha != sha256_hex(data):
            found.append(
                Violation(
                    E.CHECKSUM_HASH_MISMATCH,
                    f"{name}:{file_name}",
                    "the committed bytes hash differently",
                )
            )
    return found


def _shape(value: Any) -> str:
    """How a malformed integrity value is worth naming in a finding.

    The repr is what makes the defect reviewable: a trailing ``\\n`` on a digest is
    exactly the hole this check exists to close, so it has to be visible rather than
    inferred from a code.
    """
    if isinstance(value, str):
        rendered = repr(value if len(value) <= 80 else value[:77] + "...")
        return f"a {len(value)}-character string {rendered}"
    return f"a {type(value).__name__} {value!r}"


def _is_int(value: Any) -> bool:
    """True for a JSON integer as ``json`` decodes one, excluding the bool Python calls an int.

    ``type: integer`` in the contract accepts an integral number in *any* JSON number
    notation, so ``120000001``, ``120000001.0`` and ``1.20000001e8`` are all integers
    and every dedicated bound has to apply to all three spellings: a bound skipped for
    one of them is a bound the schema keyword no longer reports either, because the
    suppressed pair in :data:`MANIFEST_DEDICATED_RULES` silences it in exchange for a
    check that never ran.

    What is not a number is refused, and the index walk depends on that: ``nan`` and
    ``inf`` have no JSON notation at all (RFC 8259 §6), neither answers ``is_integer()``
    with ``True``, and neither is an integral ``Decimal`` — so a line holding the
    ``Infinity`` literal Python's reader does accept stops at the walk's gate instead of
    reaching the ``int()`` below it, where it would raise. A document that carries one is
    a document whose ``type`` is wrong, which is what :func:`is_json_integer` reports;
    measuring such a value against a bound would dress a type error up as an out-of-range
    value.

    The ``Decimal`` branch exists because :func:`_walk_index` parses the index with
    ``parse_float=decimal.Decimal``: an exponent that a float would round into an
    integer (``1e-400``) or into ``inf`` (``1e999``) has to be judged on the digits
    the writer actually sent, not on the binary approximation of them. ``1e999`` stays a
    finite, exact, enormous integer — ``int()`` of it is safe, and the bound refuses it as
    the out-of-range timestamp it is.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, decimal.Decimal):
        return decimal_is_integral(value)
    return isinstance(value, float) and value.is_integer()
