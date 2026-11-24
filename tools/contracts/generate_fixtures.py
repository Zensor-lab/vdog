"""Deterministic writer for ``contracts/fixtures/**``.

Run from the repository root::

    uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \\
      python -m tools.contracts.generate_fixtures [<output-dir>]

With no argument it rewrites ``contracts/fixtures``; with an argument it writes
that directory instead, which is how the validator regenerates the corpus into a
temporary directory and proves byte-identical reproducibility (AC-09).

Writes are all-or-nothing per run: every file is produced in memory first, then
compared against what is on disk, and only differing files are written. Nothing
here ever deletes an unrelated file: an unexpected file under the output directory
is reported by the validator instead (``FIXTURE_UNREFERENCED``).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Sequence

from .bounds import (
    ACTIVE_NAME,
    CHECKSUMS_NAME,
    MAX_DIMENSION_PX,
    MAX_INDEX_BYTES,
    MAX_NOMINAL_FPS,
    CLIP_FILE_NAMES,
    MANIFEST_NAME,
    MAX_ACTIVE_BYTES,
    MAX_MANIFEST_BYTES,
    UINT53_MAX,
)
from .fixture_spec import (
    MediaCorpus,
    MediaFixture,
    _raw_number,
    api_fixtures,
    boot_id,
    media_fixtures,
)
from .api_model import ALL_OPERATIONS
from .jpeg import jpeg_seed, make_jpeg
from .media_model import (
    BuiltClip,
    ClipPlan,
    active_document,
    build_index,
    checksums_document,
    crc32_hex,
    dump_json,
    manifest_document,
    sha256_hex,
    split_index_lines,
)

#: Namespace used for values that must look real but carry no semantic meaning.
_OPAQUE_NAMESPACE = "vdog-fixture"

INDEX_TRUNCATION_KEEP_CHARS: Final[int] = 30
PAYLOAD_TAIL_CUT_BYTES: Final[int] = 16
OFFSET_INFLATION_BYTES: Final[int] = 512
LONG_INDEX_LINE_CRC_CHARS: Final[int] = 600


@dataclass
class _Editable:
    """Mutable view of a built segment so a corruption can be applied to one file."""

    built: BuiltClip

    def lines(self) -> list[bytes]:
        return [body for _raw, body in split_index_lines(self.built.index)]

    def line_json(self, position: int) -> dict[str, Any]:
        lines = self.lines()
        return json.loads(lines[position].decode("utf-8"))

    def set_line(self, position: int, record: Mapping[str, Any]) -> None:
        lines = self.lines()
        # ``allow_nan=False``: a frame record carries integers and hex strings, and if it
        # ever carried a non-finite float that would be a generator bug, not a wire form.
        lines[position] = json.dumps(
            dict(record), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self.built.index = b"".join(line + b"\n" for line in lines)

    def set_raw_index(self, index: bytes) -> None:
        self.built.index = index

    def truncate_payload(self, keep_bytes: int) -> None:
        self.built.payload = self.built.payload[:keep_bytes]

def _flip_hex(value: str) -> str:
    """Change one hex digit deterministically so a hash/CRC no longer matches."""
    last = value[-1]
    flipped = "0" if last != "0" else "1"
    return value[:-1] + flipped


def _corrupt_crc(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["crc32"] = _flip_hex(record["crc32"])
    editable.set_line(1, record)


def _corrupt_payload_tail(editable: _Editable) -> None:
    """Cut the tail of the payload and shrink the final record to match.

    Keeping the index aligned with the shortened file is what isolates the defect:
    the retained slice is a truncated JPEG whose declared CRC still describes the
    complete frame, so the fixture proves both the CRC check and the marker check.
    """
    record = editable.line_json(-1)
    record["size"] = record["size"] - PAYLOAD_TAIL_CUT_BYTES
    editable.set_line(-1, record)
    editable.truncate_payload(len(editable.built.payload) - PAYLOAD_TAIL_CUT_BYTES)


def _corrupt_index_tail(editable: _Editable) -> None:
    """Leave the last line unterminated: recovery must keep the validated prefix."""
    lines = editable.lines()
    prefix = lines[:-1]
    partial = lines[-1][:INDEX_TRUNCATION_KEEP_CHARS]
    sizes = [_line_size(line) for line in prefix]
    editable.built.payload = b"".join(
        editable.built.payload[sum(sizes[:i]) : sum(sizes[:i]) + sizes[i]]
        for i in range(len(sizes))
    )
    editable.built.index = b"".join(line + b"\n" for line in prefix) + partial
    if editable.built.manifest is not None:
        editable.built.manifest["frame_count"] = len(prefix)
        editable.built.manifest["duration_us"] = _line_t_us(prefix[-1]) + 66_667


def _corrupt_index_middle(editable: _Editable) -> None:
    """Truncate a non-final line, keeping later complete lines behind it."""
    lines = editable.lines()
    sizes = [_line_size(line) for line in lines]
    prefix_count = 1
    prefix_bytes = sum(sizes[:prefix_count])
    editable.built.payload = editable.built.payload[:prefix_bytes]
    damaged = lines[1][:INDEX_TRUNCATION_KEEP_CHARS]
    rebuilt = [lines[0], damaged, lines[2], lines[3]]
    # The retained validated prefix is exactly one frame, so the manifest agrees
    # with what a recovering reader would keep and only the malformed line fails.
    editable.built.index = b"".join(line + b"\n" for line in rebuilt)
    if editable.built.manifest is not None:
        editable.built.manifest["frame_count"] = prefix_count
        editable.built.manifest["duration_us"] = _line_t_us(lines[0]) + 66_667


def _line_size(line: bytes) -> int:
    return int(json.loads(line.decode("utf-8"))["size"])


def _line_t_us(line: bytes) -> int:
    return int(json.loads(line.decode("utf-8"))["t_us"])


def _corrupt_seq_skip(editable: _Editable) -> None:
    record = editable.line_json(2)
    record["seq"] = 3
    editable.set_line(2, record)


def _corrupt_t_us_backwards(editable: _Editable) -> None:
    record = editable.line_json(2)
    record["t_us"] = 1_000
    editable.set_line(2, record)


def _corrupt_t_us_duplicate(editable: _Editable) -> None:
    record = editable.line_json(2)
    record["t_us"] = _line_t_us(editable.lines()[1])
    editable.set_line(2, record)


def _corrupt_t_us_first_nonzero(editable: _Editable) -> None:
    record = editable.line_json(0)
    record["t_us"] = 1_000
    editable.set_line(0, record)


def _corrupt_duration_le_final(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["duration_us"] = _line_t_us(editable.lines()[-1])


def _corrupt_duration_too_long(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["duration_us"] = 120_000_001


def _corrupt_frame_size_zero(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["size"] = 0
    editable.set_line(1, record)


def _corrupt_frame_size_large(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["size"] = 2_097_153
    editable.set_line(1, record)


def _corrupt_index_line_too_long(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["crc32"] = "a" * LONG_INDEX_LINE_CRC_CHARS
    editable.set_line(1, record)


def _corrupt_dimensions_oversized(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["profile"]["width"] = 1_601


def _corrupt_sof_mismatch(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["profile"]["width"] = 48


def _corrupt_id_syntax(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["device_id"] = editable.built.manifest["device_id"].upper()


def _corrupt_clip_boot_prefix(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    other_boot = boot_id("clip-boot-prefix-other")
    sequence = editable.built.manifest["clip_id"].rsplit("-", 1)[1]
    editable.built.manifest["clip_id"] = f"{other_boot}-{sequence}"


def _corrupt_unsupported_version(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["v"] = 2


def _corrupt_manifest_too_large(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    # The spec bounds the whole manifest, not this string, so an unbounded field is
    # the honest way to exceed 16,384 bytes while staying otherwise conforming.
    editable.built.manifest["firmware_version"] = "0.1.0-" + "x" * (MAX_MANIFEST_BYTES + 64)


def _corrupt_close_reason(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["close_reason"] = "battery"


def _corrupt_recovered_disagrees(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["recovered"] = True
    editable.built.manifest["close_reason"] = "duration"


def _corrupt_offset_beyond_payload(editable: _Editable) -> None:
    record = editable.line_json(-1)
    record["size"] = record["size"] + OFFSET_INFLATION_BYTES
    editable.set_line(-1, record)


def _corrupt_offset_overflow(editable: _Editable) -> None:
    record = editable.line_json(-1)
    record["offset"] = UINT53_MAX
    record["size"] = 1_024
    editable.set_line(-1, record)


def _corrupt_manifest_hash(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    entry = editable.built.manifest["files"][CLIP_FILE_NAMES[1]]
    entry["sha256"] = _flip_hex(entry["sha256"])


def _corrupt_checksum_hash(editable: _Editable) -> None:
    assert editable.built.checksums is not None
    entry = editable.built.checksums["files"][CLIP_FILE_NAMES[0]]
    entry["sha256"] = _flip_hex(entry["sha256"])


def _corrupt_checksum_size(editable: _Editable) -> None:
    assert editable.built.checksums is not None
    entry = editable.built.checksums["files"][CLIP_FILE_NAMES[0]]
    entry["bytes"] = entry["bytes"] + 7


def _rewrite_first_index_line(index: bytes, replacements: tuple[tuple[bytes, bytes], ...]) -> bytes:
    """Rewrite the first record's bytes in place, leaving every other line untouched.

    The notation is the vector, so the text is edited rather than the parsed record:
    ``json.dumps`` would write ``1e-400`` back as ``0.0`` and ``0.0`` back as ``0``,
    which is precisely the spelling the vector exists to demonstrate.
    """
    lines = index.split(b"\n")
    line = lines[0]
    for old, new in replacements:
        line, count = line.replace(old, new, 1), line.count(old)
        if count != 1:  # pragma: no cover - the record's members are generator-owned
            raise KeyError(f"{old!r} is not a member of the first index record")
    lines[0] = line
    return b"\n".join(lines)


def _corrupt_index_first_t_us_fractional(editable: _Editable) -> None:
    # The float this token converts to is exactly zero, so a validator that parses the
    # index into binary floats reads a conformant first timestamp; parsed as a decimal it
    # stays what the writer sent — a fraction — and the frame record's `type: integer`
    # is what refuses it.
    editable.built.index = _rewrite_first_index_line(
        editable.built.index, ((b'"t_us":0', b'"t_us":1e-400'),)
    )


def _corrupt_index_integral_notations(editable: _Editable) -> None:
    # ``0``, ``0.0`` and ``0e0`` name the same integer, and the published contract says
    # any JSON integer notation is a legal way to write one. A validator that refused the
    # exponential or fractional spelling would reject bytes a conforming writer may send.
    editable.built.index = _rewrite_first_index_line(
        editable.built.index,
        (
            (b'"seq":0', b'"seq":0.0'),
            (b'"offset":0', b'"offset":0e0'),
            (b'"t_us":0', b'"t_us":0E+0'),
        ),
    )


def _corrupt_manifest_sha_trailing_newline(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    entry = editable.built.manifest["files"][CLIP_FILE_NAMES[0]]
    # The shape, not the value: a digest with one byte of padding glued to it still looks
    # like a hash to a reader that only asks whether the field is a string, and a hash it
    # cannot compare is a file it never verified.
    entry["sha256"] = entry["sha256"] + "\n"


def _corrupt_manifest_bytes_non_integer(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    entry = editable.built.manifest["files"][CLIP_FILE_NAMES[1]]
    entry["bytes"] = str(entry["bytes"])  # a length that arrived as text, not a number


def _corrupt_checksums_sha_trailing_newline(editable: _Editable) -> None:
    assert editable.built.checksums is not None
    entry = editable.built.checksums["files"][CLIP_FILE_NAMES[0]]
    entry["sha256"] = entry["sha256"] + "\n"


def _corrupt_checksums_bytes_non_integer(editable: _Editable) -> None:
    assert editable.built.checksums is not None
    entry = editable.built.checksums["files"][CLIP_FILE_NAMES[1]]
    entry["bytes"] = str(entry["bytes"])


def _corrupt_index_bom(editable: _Editable) -> None:
    editable.set_raw_index(b"\xef\xbb\xbf" + editable.built.index)


def _corrupt_index_blank_line(editable: _Editable) -> None:
    lines = editable.lines()
    rebuilt = lines[0] + b"\n\n" + b"".join(line + b"\n" for line in lines[1:])
    editable.set_raw_index(rebuilt)


def _corrupt_index_crlf(editable: _Editable) -> None:
    editable.set_raw_index(editable.built.index.replace(b"\n", b"\r\n"))


def _corrupt_clock_nullity(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["clock"] = {
        "source": "unknown",
        "start_utc": "2026-03-04T11:02:03.250Z",
        "uncertainty_ms": 120,
    }


def _corrupt_manifest_bad_type(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    # A type the schema rejects but no dedicated invariant covers, so the generic
    # schema code is the honest report.
    editable.built.manifest["dropped_frames"] = "many"


def _corrupt_manifest_missing_field(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    del editable.built.manifest["firmware_version"]


def _corrupt_active_bad_type(editable: _Editable) -> None:
    assert editable.built.active is not None
    editable.built.active["start_boot_us"] = "one-second"


def _corrupt_frame_unknown_property(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["note"] = "written by a reader that invented a field"
    editable.set_line(1, record)


def _corrupt_frame_missing_field(editable: _Editable) -> None:
    record = editable.line_json(1)
    del record["crc32"]
    editable.set_line(1, record)


def _corrupt_frame_line_not_object(editable: _Editable) -> None:
    lines = editable.lines()
    lines[1] = b"[1,2]"
    editable.built.index = b"".join(line + b"\n" for line in lines)


def _corrupt_frame_t_us_too_large(editable: _Editable) -> None:
    record = editable.line_json(-1)
    record["t_us"] = 120_000_001
    editable.set_line(-1, record)


def _corrupt_offset_not_contiguous(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["offset"] = record["offset"] + 1
    editable.set_line(1, record)


def _corrupt_payload_trailing(editable: _Editable) -> None:
    # Bytes after the last record: the index stops early, so the tail is unreachable.
    editable.built.payload = editable.built.payload + b"\x00" * 8


def _corrupt_index_empty(editable: _Editable) -> None:
    editable.set_raw_index(b"")


def _corrupt_clock_source(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["clock"]["source"] = "gps"


def _corrupt_clock_timestamp(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["clock"]["start_utc"] = "2026-03-04T11:02:03Z"


def _corrupt_jpeg_soi(editable: _Editable) -> None:
    # The first frame loses its SOI marker; the recorded CRC then cannot match either.
    payload = bytearray(editable.built.payload)
    payload[0:2] = b"\xff\xdb"
    editable.built.payload = bytes(payload)


def _corrupt_jpeg_entropy(editable: _Editable) -> None:
    # Deep inside the first frame's scan data: markers stay, the decode does not.
    payload = bytearray(editable.built.payload)
    for position in range(120, min(240, len(payload))):
        payload[position] ^= 0xFF
    editable.built.payload = bytes(payload)


def _corrupt_double_jpeg_record(editable: _Editable) -> None:
    """The final record's slice becomes two complete JPEGs concatenated.

    The second image is a real distinct-seed generation at the profile's own size, so
    every marker, decode and hash the walk checks stays honest about the doubled bytes:
    the record's ``size`` covers both, its ``crc32`` is the CRC of the concatenation,
    the payload's length follows, and :meth:`BuiltClip.recompute_integrity` re-points
    the manifest afterwards. Only the marker chain can see that one indexed slice holds
    two images — the decoder reads the first and the second is frame data no playback
    time will ever reach (media-format.md §3: one record, one JPEG, ending where the
    file does).
    """
    assert editable.built.manifest is not None
    profile = editable.built.manifest["profile"]
    record = editable.line_json(-1)
    second = make_jpeg(
        profile["width"],
        profile["height"],
        jpeg_seed("clip", "double-jpeg-record", "second-image"),
    )
    first = editable.built.payload[record["offset"] : record["offset"] + record["size"]]
    record["size"] = record["size"] + len(second)
    record["crc32"] = crc32_hex(first + second)
    editable.set_line(-1, record)
    editable.built.payload = editable.built.payload + second


def _corrupt_checksums_missing_entry(editable: _Editable) -> None:
    assert editable.built.checksums is not None
    del editable.built.checksums["files"][MANIFEST_NAME]


def _corrupt_frame_version(editable: _Editable) -> None:
    record = editable.line_json(1)
    record["v"] = 2  # a future writer's line is not this contract's record
    editable.set_line(1, record)


def _corrupt_nominal_fps_high(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    editable.built.manifest["profile"]["nominal_fps"] = MAX_NOMINAL_FPS + 1


def _corrupt_nominal_fps_zero(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    # A zero rate would make every duration arithmetic meaningless.
    editable.built.manifest["profile"]["nominal_fps"] = 0


def _corrupt_active_profile_oversized(editable: _Editable) -> None:
    assert editable.built.active is not None
    editable.built.active["profile"]["width"] = MAX_DIMENSION_PX + 1


def _corrupt_frame_count(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    # One more frame than the index actually records: the bytes still agree with
    # themselves, so only the manifest's own count can reveal the defect.
    editable.built.manifest["frame_count"] = editable.built.manifest["frame_count"] + 1


def _corrupt_manifest_size(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    entry = editable.built.manifest["files"][CLIP_FILE_NAMES[1]]
    entry["bytes"] = entry["bytes"] + 5


def _corrupt_clock_impossible_date(editable: _Editable) -> None:
    assert editable.built.manifest is not None
    # Every character has the documented RFC3339 shape; only a calendar check can
    # notice that February has no thirtieth day.
    editable.built.manifest["clock"]["start_utc"] = "2026-02-30T12:00:00.000Z"


#: A declared index length above the 1,843,200-byte ceiling of media-format.md §2 and
#: below the 268,435,456-byte payload ceiling, so the schema can only refuse it if the
#: index really has its own, smaller, bound.
OVERSIZED_INDEX_DECLARATION_BYTES: Final[int] = 2_000_000
assert OVERSIZED_INDEX_DECLARATION_BYTES > MAX_INDEX_BYTES


def _raw_manifest_number(key: str, notation: str) -> FileMutation:
    """A whole-manifest rewrite of one number, written in the notation under test."""

    def mutate(_fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]) -> dict[str, bytes]:
        return _replace(files, MANIFEST_NAME, _raw_number(files[MANIFEST_NAME], key, notation))

    return mutate


def _mutate_manifest_notations(**notations: str) -> FileMutation:
    """Rewrite several manifest numbers in their under-test notations, honestly.

    A *valid* vector may not cheat on the checksum side: the raw rewrite changes
    ``manifest.json``'s bytes, so the sidecar that certifies them is recomputed from
    the rewritten document here, in the generator, and never by hand afterwards.
    """

    def mutate(_fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]) -> dict[str, bytes]:
        data = files[MANIFEST_NAME]
        for key, notation in notations.items():
            data = _raw_number(data, key, notation)
        files[MANIFEST_NAME] = data
        if CHECKSUMS_NAME in files:
            content = {name: blob for name, blob in files.items() if name != CHECKSUMS_NAME}
            files[CHECKSUMS_NAME] = dump_json(checksums_document(content))
        return files

    return mutate


def _mutate_index_declared_oversize(
    _fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    """Point the manifest's index declaration above the index bound, bytes untouched.

    Only the ``frames.jsonl`` entry is rewritten: the committed index keeps its real
    length, so the vector proves both that the index maximum exists and that a declared
    length nobody can measure is a second, independent finding.
    """
    data = files[MANIFEST_NAME]
    pattern = re.compile(rb'("frames\.jsonl":\{"bytes":)[0-9]+')
    replaced, count = pattern.subn(
        rb"\g<1>" + str(OVERSIZED_INDEX_DECLARATION_BYTES).encode("ascii"), data, count=1
    )
    if count != 1:  # pragma: no cover - the entry is part of the committed manifest
        raise KeyError("frames.jsonl file entry absent from the committed manifest")
    return _replace(files, MANIFEST_NAME, replaced)



CORRUPTIONS: Final[Mapping[str, Callable[[_Editable], None]]] = {
    "frame_crc_flip": _corrupt_crc,
    "payload_tail_cut": _corrupt_payload_tail,
    "index_tail_cut": _corrupt_index_tail,
    "index_line_malformed": _corrupt_index_middle,
    "seq_skip": _corrupt_seq_skip,
    "t_us_backwards": _corrupt_t_us_backwards,
    "t_us_duplicate": _corrupt_t_us_duplicate,
    "t_us_first_nonzero": _corrupt_t_us_first_nonzero,
    "duration_le_final_t": _corrupt_duration_le_final,
    "duration_too_long": _corrupt_duration_too_long,
    "frame_size_zero": _corrupt_frame_size_zero,
    "frame_size_too_large": _corrupt_frame_size_large,
    "index_line_too_long": _corrupt_index_line_too_long,
    "dimensions_oversized": _corrupt_dimensions_oversized,
    "sof_dimension_mismatch": _corrupt_sof_mismatch,
    "id_syntax_invalid": _corrupt_id_syntax,
    "clip_boot_prefix_mismatch": _corrupt_clip_boot_prefix,
    "unsupported_version": _corrupt_unsupported_version,
    "manifest_too_large": _corrupt_manifest_too_large,
    "close_reason_unknown": _corrupt_close_reason,
    "recovered_disagrees": _corrupt_recovered_disagrees,
    "offset_beyond_payload": _corrupt_offset_beyond_payload,
    "offset_arithmetic_overflow": _corrupt_offset_overflow,
    "manifest_hash_mismatch": _corrupt_manifest_hash,
    "checksum_hash_mismatch": _corrupt_checksum_hash,
    "checksum_size_mismatch": _corrupt_checksum_size,
    "index_bom": _corrupt_index_bom,
    "index_blank_line": _corrupt_index_blank_line,
    "index_crlf": _corrupt_index_crlf,
    "clock_nullity": _corrupt_clock_nullity,
    "manifest_bad_type": _corrupt_manifest_bad_type,
    "manifest_missing_field": _corrupt_manifest_missing_field,
    "active_bad_type": _corrupt_active_bad_type,
    "frame_unknown_property": _corrupt_frame_unknown_property,
    "frame_missing_field": _corrupt_frame_missing_field,
    "frame_line_not_object": _corrupt_frame_line_not_object,
    "frame_t_us_too_large": _corrupt_frame_t_us_too_large,
    "offset_not_contiguous": _corrupt_offset_not_contiguous,
    "payload_trailing": _corrupt_payload_trailing,
    "index_empty": _corrupt_index_empty,
    "clock_source_unknown": _corrupt_clock_source,
    "clock_timestamp_invalid": _corrupt_clock_timestamp,
    "clock_timestamp_impossible_date": _corrupt_clock_impossible_date,
    "jpeg_soi_missing": _corrupt_jpeg_soi,
    "jpeg_entropy_garbage": _corrupt_jpeg_entropy,
    "double_jpeg_record": _corrupt_double_jpeg_record,
    "checksums_missing_entry": _corrupt_checksums_missing_entry,
    "manifest_size_mismatch": _corrupt_manifest_size,
    "manifest_sha_trailing_newline": _corrupt_manifest_sha_trailing_newline,
    "manifest_bytes_non_integer": _corrupt_manifest_bytes_non_integer,
    "checksums_sha_trailing_newline": _corrupt_checksums_sha_trailing_newline,
    "checksums_bytes_non_integer": _corrupt_checksums_bytes_non_integer,
    "index_first_t_us_fractional": _corrupt_index_first_t_us_fractional,
    "index_integral_notations": _corrupt_index_integral_notations,
    "frame_count_mismatch": _corrupt_frame_count,
    "frame_version": _corrupt_frame_version,
    "nominal_fps_high": _corrupt_nominal_fps_high,
    "nominal_fps_zero": _corrupt_nominal_fps_zero,
    "active_profile_oversized": _corrupt_active_profile_oversized,
}

#: Corruptions that must keep their own (wrong) integrity values, so the manifest
#: and checksums must not be re-pointed at the corrupted bytes afterwards.
PRESERVES_INTEGRITY: Final[frozenset[str]] = frozenset(
    {
        "manifest_hash_mismatch",
        "checksum_hash_mismatch",
        "checksum_size_mismatch",
        "checksums_missing_entry",
        "manifest_size_mismatch",
        # These four defect *is* a malformed integrity field, so recomputing the
        # manifest or the sidecar afterwards would repair the very thing under test.
        "manifest_sha_trailing_newline",
        "manifest_bytes_non_integer",
        "checksums_sha_trailing_newline",
        "checksums_bytes_non_integer",
    }
)

#: Whole-file rewrites that no in-place model edit can express: a file whose bytes
#: never parse, a file that must not exist, and a file that must not be there.
FileMutation = Callable[[MediaFixture, BuiltClip, dict[str, bytes]], dict[str, bytes]]


def _replace(files: dict[str, bytes], name: str, data: bytes) -> dict[str, bytes]:
    files[name] = data
    return files


def _mutate_manifest_not_json(
    _fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    return _replace(files, MANIFEST_NAME, b"not json\n")


def _mutate_manifest_absent(
    _fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    del files[MANIFEST_NAME]
    return files


def _mutate_active_not_json(
    _fixture: MediaFixture, _built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    return _replace(files, ACTIVE_NAME, b"{oops\n")


def _mutate_active_too_large(
    fixture: MediaFixture, built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    assert built.active is not None
    padded = dict(built.active)
    # The bound is on the whole record, so an unbounded documented field is the
    # honest way to exceed it without inventing a field.
    padded["firmware_version"] = "0.1.0-" + "x" * (MAX_ACTIVE_BYTES + 64)
    return _replace(files, ACTIVE_NAME, dump_json(padded))


def _mutate_active_with_manifest(
    fixture: MediaFixture, built: BuiltClip, files: dict[str, bytes]
) -> dict[str, bytes]:
    return _replace(
        files, MANIFEST_NAME, dump_json(manifest_document(fixture.plan, built.payload, built.index))
    )


FILE_MUTATIONS: Final[Mapping[str, FileMutation]] = {
    "manifest_not_json": _mutate_manifest_not_json,
    "manifest_absent": _mutate_manifest_absent,
    "active_not_json": _mutate_active_not_json,
    "active_too_large": _mutate_active_too_large,
    "active_with_manifest": _mutate_active_with_manifest,
    "duration_too_long_decimal": _raw_manifest_number("duration_us", "120000001.0"),
    "duration_too_long_exponent": _raw_manifest_number("duration_us", "1.20000001e8"),
    "dimensions_oversized_decimal": _raw_manifest_number("width", "1601.0"),
    "nominal_fps_high_decimal": _raw_manifest_number("nominal_fps", "31.0"),
    # The exact-number pair on the manifest path: the integral spellings a conforming
    # writer may send (and must be accepted), and the fraction that a binary-float
    # parse would silently round into the integer it is not (and must be refused).
    "manifest_integral_notations": _mutate_manifest_notations(
        duration_us="266667.0", frame_count="4.0", capture_order="42.0"
    ),
    # The same three integers in exponent notation: `type: integer` reads `4e0` as the
    # integer 4 exactly as it reads `4`, so an exact-number parser has to agree.
    "manifest_exponent_notations": _mutate_manifest_notations(
        duration_us="2.66667e5", frame_count="4e0", capture_order="4.2e1"
    ),
    # The profile's own two numbers, in the integral spellings a conforming writer may
    # send: the crop bound a derivative is measured against comes from these, so a clip
    # that spells them ``64.0`` must keep its pixels and not quietly leave the map.
    "manifest_integral_dimension_notations": _mutate_manifest_notations(
        width="64.0", height="64.0"
    ),
    "manifest_duration_rolls_to_integer": _raw_manifest_number(
        "duration_us", "266667.000000000001"
    ),
    "index_declared_oversize": _mutate_index_declared_oversize,
}


def committed_files(fixture: MediaFixture) -> dict[str, bytes]:
    """The exact bytes this fixture ships, after its declared corruption."""
    built = build_media(fixture)
    files = dict(built.files())
    mutation = FILE_MUTATIONS.get(fixture.corruption or "")
    if mutation is not None:
        files = mutation(fixture, built, files)
    return files


def build_frames(plan: ClipPlan) -> list[bytes]:
    """Real JPEG bytes for one segment: deterministic, distinct per frame seed."""
    return [
        make_jpeg(plan.profile.width, plan.profile.height, frame.jpeg_key)
        for frame in plan.frames
    ]


def build_media(fixture: MediaFixture) -> BuiltClip:
    """Build one committed media vector exactly as it ships."""
    frames = build_frames(fixture.plan)
    payload = b"".join(frames)
    index = build_index(frames, [frame.t_us for frame in fixture.plan.frames])
    if fixture.kind == "active":
        built = BuiltClip(
            payload=payload,
            index=index,
            active=active_document(fixture.plan),
            active_state=True,
        )
    else:
        built = BuiltClip(
            payload=payload,
            index=index,
            manifest=manifest_document(fixture.plan, payload, index),
        )
    if fixture.checksums:
        built.checksums = checksums_document(built.files())

    if fixture.corruption is not None:
        corruption = CORRUPTIONS.get(fixture.corruption)
        if corruption is None and fixture.corruption not in FILE_MUTATIONS:  # pragma: no cover
            raise KeyError(f"undeclared corruption {fixture.corruption!r}")
        if corruption is not None:
            corruption(_Editable(built))
            if fixture.corruption not in PRESERVES_INTEGRITY:
                built.recompute_integrity()
        if not fixture.checksums:
            built.checksums = None
    return built


def _b64url(data: bytes) -> str:
    """Unpadded base64url, the only form interfaces.md §8 accepts."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_standard(data: bytes) -> str:
    """Padded standard base64, which is what a wrong-alphabet vector must look like."""
    return base64.b64encode(data).decode("ascii")


def build_media_corpus(media: Sequence[MediaFixture]) -> MediaCorpus:
    """Compute the real committed values the API vectors quote."""
    by_id = {fixture.id: build_media(fixture) for fixture in media}
    baseline = by_id["media/valid/baseline"]
    gap = by_id["media/valid/gap-long-jump"]
    recovered = by_id["media/valid/recovered-prefix"]
    notation_dimensions = by_id["media/valid/manifest-integral-dimension-notations"]
    wide_second = by_id["media/valid/wide-second-device"]
    assert notation_dimensions.manifest is not None
    assert wide_second.manifest is not None
    assert baseline.manifest is not None
    manifest_bytes = dump_json(baseline.manifest)
    chunk = baseline.payload[:512]
    decoded_oversize = json.dumps(
        {"v": 1, "pad": "p" * (16_385 - len('{"v":1,"pad":""}'))},
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert len(decoded_oversize) == MAX_MANIFEST_BYTES + 1
    # Both of these are manifests the media validator refuses and the OpenAPI mirror
    # accepts, which is the whole point: they are bound for an upload initialization,
    # where nothing but those media rules can notice them.
    sequence = baseline.manifest["clip_id"].rsplit("-", 1)[1]
    boot_prefix_manifest = {
        **baseline.manifest,
        "clip_id": f"{boot_id('boot-prefix-rival')}-{sequence}",
    }
    unknown_clock_manifest = {
        **baseline.manifest,
        "clock": {**baseline.manifest["clock"], "source": "unknown"},
    }
    return MediaCorpus(
        baseline_clip_id=baseline.manifest["clip_id"],
        baseline_manifest=baseline.manifest,
        baseline_payload_bytes=len(baseline.payload),
        baseline_payload_sha256=sha256_hex(baseline.payload),
        baseline_index_bytes=len(baseline.index),
        baseline_index_sha256=sha256_hex(baseline.index),
        baseline_manifest_base64url=_b64url(manifest_bytes),
        baseline_chunk_sha256=sha256_hex(chunk),
        baseline_chunk_bytes=len(chunk),
        baseline_chunk=chunk,
        notation_dimensions_clip_id=notation_dimensions.manifest["clip_id"],
        notation_dimensions_payload_sha256=sha256_hex(notation_dimensions.payload),
        notation_dimensions_index_sha256=sha256_hex(notation_dimensions.index),
        wide_second_device_device_id=wide_second.manifest["device_id"],
        wide_second_device_clip_id=wide_second.manifest["clip_id"],
        wide_second_device_payload_sha256=sha256_hex(wide_second.payload),
        wide_second_device_index_sha256=sha256_hex(wide_second.index),
        gap_clip_id=gap.manifest["clip_id"] if gap.manifest else "",
        gap_payload_bytes=len(gap.payload),
        gap_index_bytes=len(gap.index),
        recovered_clip_id=recovered.manifest["clip_id"] if recovered.manifest else "",
        recovered_payload_bytes=len(recovered.payload),
        recovered_index_bytes=len(recovered.index),
        other_clip_id=f"{boot_id('effective-from')}-00000001",
        oversize_manifest_base64url="A" * (MAX_MANIFEST_BYTES * 3),
        decoded_oversize_manifest_base64url=_b64url(decoded_oversize),
        padded_manifest_base64url=_b64_standard(b"\xfb\xff" + manifest_bytes),
        non_json_manifest_base64url=_b64url(b"this is not json"),
        invalid_manifest_base64url=_b64url(dump_json({"v": 1})),
        boot_prefix_manifest_base64url=_b64url(dump_json(boot_prefix_manifest)),
        unknown_clock_timestamp_manifest_base64url=_b64url(dump_json(unknown_clock_manifest)),
    )


def fixtures_index(
    media: Sequence[MediaFixture], api: Sequence[Any]
) -> dict[str, Any]:
    """Build the ``fixtures.json`` payload: every committed vector, self-describing."""
    entries: list[dict[str, Any]] = []
    for fixture in media:
        entries.append(
            {
                "id": fixture.id,
                "kind": fixture.kind,
                "contract": "media-v1",
                "category": fixture.category,
                "expected": fixture.expected,
                "expected_error_codes": sorted(fixture.codes),
                "corruption": fixture.corruption,
                "files": sorted(committed_files(fixture).keys()),
                "invariant": fixture.invariant,
            }
        )
    for fixture in api:
        entry: dict[str, Any] = {
            "id": fixture.id,
            "kind": "api",
            "contract": f"{fixture.contract}-v1",
            "category": fixture.category,
            "expected": fixture.expected,
            "expected_error_codes": sorted(fixture.codes),
            "files": sorted(fixture.files),
            "invariant": fixture.invariant,
            "operation": fixture.operation,
            "operation_id": None,
            "method": None,
            "path": None,
            "direction": fixture.direction,
            "status": fixture.status,
            "schema": fixture.schema,
            "api_error_code": fixture.api_error_code,
        }
        operation = ALL_OPERATIONS[fixture.operation]
        entry["operation_id"] = operation.operation_id
        entry["method"] = operation.method
        entry["path"] = operation.path
        entries.append(entry)
    for entry in entries:
        if entry["expected"] == "valid" and entry["expected_error_codes"]:
            raise ValueError(f"valid fixture {entry['id']} declares error codes")
        if entry["expected"] == "invalid" and not entry["expected_error_codes"]:
            raise ValueError(f"invalid fixture {entry['id']} declares no error codes")
    return {
        "v": 1,
        "package": "0.6",
        "generated_by": "python -m tools.contracts.generate_fixtures",
        "fixtures": sorted(entries, key=lambda item: item["id"]),
    }


@lru_cache(maxsize=1)
def _build_all_cached() -> dict[str, bytes]:
    """The corpus, built once per process: it is a pure function of the spec tables."""
    return dict(_build_all())


def build_all() -> dict[str, bytes]:
    """Return every fixture file as ``relative path -> exact bytes``.

    The result is a fresh dict over cached, immutable values, so callers may compare
    and re-key it without disturbing a later regeneration sweep.
    """
    return dict(_build_all_cached())


def _build_all() -> dict[str, bytes]:
    media = media_fixtures()
    corpus = build_media_corpus(media)
    api = api_fixtures(corpus)
    out: dict[str, bytes] = {}
    for fixture in media:
        for name, data in committed_files(fixture).items():
            out[f"{fixture.dir_path}/{name}"] = data
    for fixture in api:
        if fixture.raw_body is not None:
            # Written verbatim: the whole point of such a vector is a wire form that no
            # serializer in this module may produce, so the bytes are the specification.
            out[fixture.body_file or ""] = fixture.raw_body
        elif fixture.chunk_body is not None:
            # The octet-stream body of a chunk upload, written as the bytes the device
            # would hash: a checksum vector whose chunk is only *described* in a header
            # would leave the hash comparing against nothing.
            out[fixture.body_file or ""] = fixture.chunk_body
        elif fixture.body is not None:
            out[fixture.body_file or ""] = dump_json(fixture.body)
        if fixture.headers is not None:
            out[fixture.headers_file or ""] = dump_json(
                {key: fixture.headers[key] for key in sorted(fixture.headers)}
            )
        if fixture.request_headers is not None:
            # The request a granted range answers: written as its own sidecar so the
            # answer's own header map stays a statement about the answer alone.
            out[fixture.request_headers_file or ""] = dump_json(
                {key: fixture.request_headers[key] for key in sorted(fixture.request_headers)}
            )
    out["fixtures.json"] = (
        json.dumps(
            fixtures_index(media, api),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return out


def write_all(output_dir: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Write the corpus under ``output_dir``; return ``(written, unchanged)`` counts."""
    files = build_all()
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    unchanged = 0
    for relative, data in sorted(files.items()):
        target = output_dir / relative
        if target.exists() and target.read_bytes() == data:
            unchanged += 1
            continue
        written += 1
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return written, unchanged


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m tools.contracts.generate_fixtures``."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.contracts.generate_fixtures",
        description="Regenerate contracts/fixtures deterministically.",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="contracts/fixtures",
        help="directory to write (default: contracts/fixtures)",
    )
    parser.add_argument("--dry-run", action="store_true", help="count changes without writing")
    args = parser.parse_args(argv)
    written, unchanged = write_all(Path(args.output_dir), dry_run=args.dry_run)
    print(f"generate_fixtures: {written} written, {unchanged} unchanged -> {args.output_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI path
    sys.exit(main())
