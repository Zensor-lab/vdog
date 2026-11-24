"""Media contract invariants over the committed corpus (AC-02, AC-03).

These tests read the committed bytes rather than the generator's output, so a
fixture that only *looks* right in memory cannot pass.
"""

from __future__ import annotations

import decimal
import hashlib
import copy
import json
import re
import zlib

import pytest

from tools.contracts import errors as E
from tools.contracts.bounds import (
    ACTIVE_NAME,
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    CLIP_FILE_NAMES,
    CLOSE_REASONS,
    MAX_FRAMES_PER_CLIP,
    MAX_INDEX_BYTES,
    MAX_INDEX_LINE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PAYLOAD_BYTES,
    MEDIA_VERSION,
    UINT53_MAX,
)
from tools.contracts.jpeg import decode_size, sof_dimensions
from tools.contracts.media_validate import (
    FRAME_DEDICATED_RULES,
    MANIFEST_DEDICATED_RULES,
    validate_media_fixture,
)
from tools.contracts.openapi_check import load_media_schemas
from tools.contracts.schema_docs import decimal_is_integral

from conftest import FIXTURES, REPO_ROOT, baseline_files, synthetic_media_entry

#: Fields the active (interrupted-segment) record does not carry at all: the
#: finalization facts only exist once a segment is closed.
_ACTIVE_ABSENT_FIELDS = ("close_reason", "duration_us", "frame_count")

INDEX_NAME = CLIP_FILE_NAMES[1]
PAYLOAD_NAME = CLIP_FILE_NAMES[0]
LOWER_HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")


@pytest.fixture(scope="module")
def schemas() -> dict:
    loaded, violations = load_media_schemas(REPO_ROOT / "contracts" / "media-v1")
    assert not violations, [violation.render() for violation in violations]
    return loaded


@pytest.fixture(scope="module")
def index() -> list[dict]:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    return [entry for entry in document["fixtures"] if entry["kind"] in {"clip", "active"}]


def _suffix(entry: dict) -> str:
    return ".part" if entry["kind"] == "active" else ""


def _read(fixture_id: str, name: str) -> bytes:
    return (FIXTURES / fixture_id / name).read_bytes()


def _index_bytes(entry: dict) -> bytes:
    return _read(entry["id"], INDEX_NAME + _suffix(entry))


def _payload_bytes(entry: dict) -> bytes:
    return _read(entry["id"], PAYLOAD_NAME + _suffix(entry))


def _records(entry: dict) -> list[dict]:
    """The committed index records, in whatever notation they were written in.

    ``type: integer`` admits ``0``, ``0.0`` and ``0e0`` as the same integer, and the media
    walk parses the index with ``parse_float=decimal.Decimal`` so an exponent cannot be
    rounded away before it is judged. These helpers then slice payload bytes by those very
    numbers, so they read the file the same way and reduce an integral decimal to the
    ``int`` a slice needs: a test that instead refused the notation would be refusing bytes
    the published contract calls conformant.
    """
    lines = _index_bytes(entry).decode("utf-8").split("\n")
    records = []
    for line in lines:
        if not line:
            continue
        record = json.loads(line, parse_float=decimal.Decimal)
        records.append(
            {
                key: int(value)
                if isinstance(value, decimal.Decimal) and decimal_is_integral(value)
                else value
                for key, value in record.items()
            }
        )
    return records


def _entry_id(entry: dict) -> str:
    return entry["id"]


def media_entries(index: list[dict], expected: str) -> list[dict]:
    return [entry for entry in index if entry["expected"] == expected]


def test_media_schemas_are_valid_2020_12_documents(schemas: dict) -> None:
    from jsonschema import Draft202012Validator

    assert set(schemas) == {"frame", "manifest", "active"}
    for name, document in schemas.items():
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


def test_valid_media_vectors_produce_no_findings(index: list[dict], schemas: dict) -> None:
    for entry in media_entries(index, "valid"):
        violations = validate_media_fixture(FIXTURES, entry, schemas)
        assert not violations, [violation.render() for violation in violations]


def test_invalid_media_vectors_produce_exactly_their_declared_codes(
    index: list[dict], schemas: dict
) -> None:
    for entry in media_entries(index, "invalid"):
        observed = {
            violation.code for violation in validate_media_fixture(FIXTURES, entry, schemas)
        }
        assert observed == set(entry["expected_error_codes"]), (
            entry["id"],
            sorted(observed),
            entry["expected_error_codes"],
        )


# --- AC-02: the valid corpus really exercises the format ---------------------


def test_baseline_has_at_least_three_frames(index: list[dict]) -> None:
    baseline = next(entry for entry in index if entry["id"] == "media/valid/baseline")
    records = _records(baseline)
    assert len(records) >= 3
    assert [record["seq"] for record in records] == list(range(len(records)))


def test_frame_crc32_matches_the_exact_committed_bytes(index: list[dict]) -> None:
    """AC-02: CRCs are real zlib CRC-32/ISO-HDLC values over exact frame slices."""
    for entry in media_entries(index, "valid"):
        payload = _payload_bytes(entry)
        for record in _records(entry):
            frame = payload[record["offset"] : record["offset"] + record["size"]]
            assert format(zlib.crc32(frame) & 0xFFFFFFFF, "08x") == record["crc32"], entry["id"]


def test_offsets_are_contiguous_and_end_at_the_payload_size(index: list[dict]) -> None:
    for entry in media_entries(index, "valid"):
        payload = _payload_bytes(entry)
        end = 0
        for position, record in enumerate(_records(entry)):
            assert record["offset"] == end, (entry["id"], position)
            end += record["size"]
        assert end == len(payload), entry["id"]


def test_timestamps_start_at_zero_and_increase_strictly(index: list[dict]) -> None:
    for entry in media_entries(index, "valid"):
        stamps = [record["t_us"] for record in _records(entry)]
        assert stamps[0] == 0, entry["id"]
        assert all(later > earlier for earlier, later in zip(stamps, stamps[1:])), entry["id"]


def test_gap_fixture_exercises_a_large_timestamp_jump(index: list[dict]) -> None:
    gap = next(entry for entry in index if entry["id"] == "media/valid/gap-long-jump")
    stamps = [record["t_us"] for record in _records(gap)]
    assert max(later - earlier for earlier, later in zip(stamps, stamps[1:])) >= 1_000_000


def test_every_valid_frame_is_a_real_jpeg_matching_the_profile(index: list[dict]) -> None:
    """AC-02: SOI/EOI, a real Pillow decode, and SOF dimensions that match the manifest."""
    for entry in media_entries(index, "valid"):
        active = entry["kind"] == "active"
        payload = _payload_bytes(entry)
        document = json.loads(
            _read(entry["id"], "active.json" if active else "manifest.json").decode("utf-8")
        )
        width = document["profile"]["width"]
        height = document["profile"]["height"]
        for record in _records(entry):
            frame = payload[record["offset"] : record["offset"] + record["size"]]
            assert frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"), entry["id"]
            assert decode_size(frame) == (width, height), entry["id"]
            assert sof_dimensions(frame) == (width, height), entry["id"]


def test_frames_are_distinct_per_frame_bytes(index: list[dict]) -> None:
    """AC-09: the generator seeds every frame, so no two frames collapse to one blob."""
    baseline = next(entry for entry in index if entry["id"] == "media/valid/baseline")
    payload = _read(baseline["id"], PAYLOAD_NAME)
    frames = [
        payload[record["offset"] : record["offset"] + record["size"]]
        for record in _records(baseline)
    ]
    assert len(set(frames)) == len(frames)


def test_manifest_hashes_match_the_committed_bytes(index: list[dict]) -> None:
    for entry in media_entries(index, "valid"):
        if entry["kind"] == "active":
            continue
        document = json.loads(_read(entry["id"], "manifest.json").decode("utf-8"))
        for name in CLIP_FILE_NAMES:
            data = _read(entry["id"], name)
            assert document["files"][name]["bytes"] == len(data), entry["id"]
            assert document["files"][name]["sha256"] == hashlib.sha256(data).hexdigest()


def test_checksums_describe_every_shipped_file(index: list[dict]) -> None:
    """AC-02/decision 9: each valid clip ships checksums.json over the other three files."""
    for entry in media_entries(index, "valid"):
        if entry["kind"] == "active":
            continue
        document = json.loads(_read(entry["id"], CHECKSUMS_NAME).decode("utf-8"))
        assert document["v"] == MEDIA_VERSION
        assert set(document["files"]) == {*CLIP_FILE_NAMES, "manifest.json"}
        for name, entry_document in document["files"].items():
            data = _read(entry["id"], name)
            assert entry_document["bytes"] == len(data)
            assert LOWER_HEX_64.match(entry_document["sha256"])
            assert entry_document["sha256"] == hashlib.sha256(data).hexdigest()


def test_invalid_clips_ship_no_checksums_except_the_checksum_vectors(index: list[dict]) -> None:
    """A defect stays isolated: only the two checksum vectors ship checksums.json."""
    for entry in media_entries(index, "invalid"):
        carries = CHECKSUMS_NAME in entry["files"]
        assert carries == entry["id"].startswith("media/invalid/checksum"), entry["id"]


#: Bounds a vector is *allowed* to break, because breaking it is the vector's purpose.
_INDEX_BOUND_EXEMPTIONS: dict[str, str] = {
    "INDEX_ENCODING_INVALID": "BOM / CR / blank-line rule",
    "FRAME_LINE_TOO_LONG": "512-byte index line rule",
    "INDEX_TRUNCATED": "final LF terminator rule",
    "INDEX_TOO_LARGE": "total index size rule",
}


def test_index_encoding_bounds_on_every_vector(index: list[dict]) -> None:
    for entry in index:
        codes = set(entry["expected_error_codes"])
        if E.INDEX_EMPTY in codes:
            continue  # this vector's whole point is an index with no records at all
        active = entry["kind"] == "active"
        index_bytes = _read(entry["id"], INDEX_NAME + (".part" if active else ""))
        if "INDEX_ENCODING_INVALID" not in codes:
            assert not index_bytes.startswith(b"\xef\xbb\xbf"), entry["id"]
            assert b"\r" not in index_bytes, entry["id"]
        if "INDEX_TRUNCATED" not in codes:
            assert index_bytes.endswith(b"\n"), entry["id"]
        if "INDEX_TOO_LARGE" not in codes:
            assert len(index_bytes) <= MAX_INDEX_BYTES, entry["id"]
        lines = index_bytes.split(b"\n")
        if "INDEX_TRUNCATED" not in codes:
            assert lines[-1] == b"", entry["id"]
            body_lines = lines[:-1]
        else:
            body_lines = [line for line in lines if line]
        if "INDEX_ENCODING_INVALID" not in codes:
            assert all(body_lines), entry["id"]
        if "FRAME_LINE_TOO_LONG" not in codes:
            for line in body_lines:
                assert len(line) + 1 <= MAX_INDEX_LINE_BYTES, entry["id"]


def test_valid_manifests_respect_the_size_bound(index: list[dict]) -> None:
    for entry in media_entries(index, "valid"):
        name = "active.json" if entry["kind"] == "active" else "manifest.json"
        assert len(_read(entry["id"], name)) <= MAX_MANIFEST_BYTES, entry["id"]


def test_close_reasons_and_recovery_agree_across_the_valid_corpus(index: list[dict]) -> None:
    reasons = set()
    for entry in media_entries(index, "valid"):
        if entry["kind"] == "active":
            continue
        document = json.loads(_read(entry["id"], "manifest.json").decode("utf-8"))
        reasons.add(document["close_reason"])
        assert document["close_reason"] in CLOSE_REASONS
        assert document["recovered"] == (document["close_reason"] == "recovery")
    assert {"duration", "size", "recovery", "shutdown", "ota"} <= reasons


def test_active_vector_is_the_partial_file_set(index: list[dict]) -> None:
    active = next(entry for entry in index if entry["kind"] == "active")
    assert set(active["files"]) == {
        PAYLOAD_NAME + ".part",
        INDEX_NAME + ".part",
        "active.json",
    }


def test_unknown_clock_vector_has_two_nulls(index: list[dict]) -> None:
    entry = next(entry for entry in index if entry["id"] == "media/valid/clock-unknown")
    clock = json.loads(_read(entry["id"], "manifest.json").decode("utf-8"))["clock"]
    assert clock == {"source": "unknown", "start_utc": None, "uncertainty_ms": None}


def test_known_clock_vector_carries_millisecond_utc(index: list[dict]) -> None:
    entry = next(entry for entry in index if entry["id"] == "media/valid/clock-phone")
    clock = json.loads(_read(entry["id"], "manifest.json").decode("utf-8"))["clock"]
    assert clock["source"] == "phone"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", clock["start_utc"])
    assert clock["uncertainty_ms"] >= 0


# --- AC-03: every required media defect is a labeled negative vector ---------

REQUIRED_MEDIA_DEFECTS: dict[str, tuple[str, ...]] = {
    "media/invalid/frame-crc-mismatch": (E.FRAME_CRC_MISMATCH,),
    "media/invalid/payload-truncated": (E.FRAME_CRC_MISMATCH, E.JPEG_EOI_MISSING),
    "media/invalid/index-final-line-incomplete": (E.INDEX_TRUNCATED,),
    "media/invalid/index-malformed-midline": (E.FRAME_LINE_MALFORMED,),
    "media/invalid/seq-nonconsecutive": (E.FRAME_SEQ_NOT_CONSECUTIVE,),
    "media/invalid/t-us-decreasing": (E.FRAME_T_US_NOT_INCREASING,),
    "media/invalid/t-us-duplicate": (E.FRAME_T_US_DUPLICATE,),
    "media/invalid/t-us-first-nonzero": (E.FRAME_T_US_FIRST_NOT_ZERO,),
    "media/invalid/duration-le-final-t-us": (E.DURATION_LE_FINAL_T_US,),
    "media/invalid/duration-too-long": (E.DURATION_TOO_LONG,),
    "media/invalid/frame-size-zero": (E.FRAME_SIZE_INVALID,),
    "media/invalid/frame-size-too-large": (E.FRAME_SIZE_INVALID,),
    "media/invalid/index-line-too-long": (E.FRAME_LINE_TOO_LONG,),
    "media/invalid/dimensions-oversized": (E.DIMENSIONS_EXCEEDED,),
    "media/invalid/sof-dimension-mismatch": (E.JPEG_SOF_DIMENSION_MISMATCH,),
    "media/invalid/id-syntax-invalid": (E.ID_SYNTAX_INVALID,),
    "media/invalid/clip-boot-prefix-mismatch": (E.CLIP_BOOT_PREFIX_MISMATCH,),
    "media/invalid/unsupported-version": (E.VERSION_UNSUPPORTED,),
    "media/invalid/manifest-too-large": (E.MANIFEST_TOO_LARGE,),
    "media/invalid/close-reason-unknown": (E.CLOSE_REASON_UNKNOWN,),
    "media/invalid/recovered-close-reason-disagree": (E.RECOVERED_CLOSE_REASON_DISAGREE,),
    "media/invalid/offset-beyond-payload-end": (E.OFFSET_EXCEEDS_PAYLOAD,),
    "media/invalid/offset-arithmetic-overflow": (E.OFFSET_ARITHMETIC_OVERFLOW,),
    "media/invalid/manifest-hash-mismatch": (E.MANIFEST_HASH_MISMATCH,),
    "media/invalid/checksum-hash-mismatch": (E.CHECKSUM_HASH_MISMATCH,),
    "media/invalid/checksum-size-mismatch": (E.CHECKSUM_SIZE_MISMATCH,),
    "media/invalid/index-with-bom": (E.INDEX_ENCODING_INVALID,),
    "media/invalid/index-with-crlf": (E.INDEX_ENCODING_INVALID,),
    "media/invalid/index-with-blank-line": (E.INDEX_ENCODING_INVALID,),
    "media/invalid/clock-nullity-mismatch": (E.CLOCK_NULLITY_MISMATCH,),
    "media/invalid/duration-too-long-decimal": (E.DURATION_TOO_LONG,),
    "media/invalid/duration-too-long-exponent": (E.DURATION_TOO_LONG,),
    "media/invalid/dimensions-oversized-decimal": (E.DIMENSIONS_EXCEEDED,),
    "media/invalid/nominal-fps-high-decimal": (E.NOMINAL_FPS_INVALID,),
    "media/invalid/index-declared-oversize": (E.MANIFEST_SCHEMA, E.MANIFEST_SIZE_MISMATCH),
    "media/invalid/clock-timestamp-impossible-date": (E.CLOCK_TIMESTAMP_INVALID,),
    # Round 4: malformed integrity fields, the walk's own record ceiling, and the
    # shared JSON integer bound on a clock estimate.
    "media/invalid/manifest-sha-trailing-newline": (E.MANIFEST_HASH_MISMATCH, E.MANIFEST_SCHEMA),
    "media/invalid/manifest-size-non-integer": (E.MANIFEST_SIZE_MISMATCH, E.MANIFEST_SCHEMA),
    "media/invalid/checksums-sha-trailing-newline": (E.CHECKSUMS_SCHEMA,),
    "media/invalid/checksums-size-non-integer": (E.CHECKSUMS_SCHEMA,),
    "media/invalid/index-records-above-clip-ceiling": (E.FRAME_COUNT_MISMATCH,),
    "media/invalid/clock-uncertainty-above-uint53": (E.CLOCK_NULLITY_MISMATCH, E.MANIFEST_SCHEMA),
}


@pytest.mark.parametrize("fixture_id, codes", sorted(REQUIRED_MEDIA_DEFECTS.items()))
def test_required_media_defect_is_covered(
    fixture_id: str, codes: tuple[str, ...], index: list[dict], schemas: dict
) -> None:
    entry = next((item for item in index if item["id"] == fixture_id), None)
    assert entry is not None, f"{fixture_id} is missing from the corpus"
    assert entry["expected"] == "invalid"
    observed = {violation.code for violation in validate_media_fixture(FIXTURES, entry, schemas)}
    assert set(codes) <= observed, (fixture_id, sorted(observed))
    assert observed == set(entry["expected_error_codes"])


def test_truncated_index_keeps_a_valid_prefix(index: list[dict]) -> None:
    """AC-03: the prefix boundary is real, not just a parse failure."""
    entry = next(
        item for item in index if item["id"] == "media/invalid/index-final-line-incomplete"
    )
    raw = _read(entry["id"], INDEX_NAME)
    lines = raw.split(b"\n")
    assert len(lines) == 4  # three LF-terminated records, then the damaged one
    for line in lines[:3]:
        json.loads(line.decode("utf-8"))
    assert lines[3], "the damaged record is still present, which is what the vector proves"
    assert not raw.endswith(b"\n"), "the final record has no LF terminator"
    with pytest.raises(json.JSONDecodeError):
        json.loads(lines[3].decode("utf-8"))


def test_recovered_prefix_keeps_only_its_valid_prefix(index: list[dict]) -> None:
    entry = next(item for item in index if item["id"] == "media/valid/recovered-prefix")
    document = json.loads(_read(entry["id"], "manifest.json").decode("utf-8"))
    assert document["recovered"] is True
    assert document["close_reason"] == "recovery"
    assert document["frame_count"] == len(_records(entry))


# --- Decision 10: a suppressed keyword must have a dedicated check -----------

def _pair_id(pair: tuple[str, str]) -> str:
    """A case name that says which keyword of which property is under test."""
    property_name, keyword = pair
    return f"{property_name}-{keyword}"


def _resolved(document: dict) -> dict:
    """The schema with every local ``$ref`` inlined, so keywords become visible.

    Several identifier properties are ``{"$ref": "#/$defs/…"}`` nodes: searching the
    raw document would hide their ``pattern`` keyword and let a suppression test skip a
    rule that really is silenced.
    """
    from tools.contracts.schema_docs import resolve_refs

    return resolve_refs(copy.deepcopy(document))


def _clip_with_frame_count(total: int) -> dict[str, bytes]:
    """A self-consistent segment of ``total`` frames: only a bound can object.

    The baseline frames repeat, so every per-frame invariant (offset contiguity, CRC-32,
    increasing timestamps) holds and the manifest declares the count the index really
    has. That is what makes this vector able to kill the frame-ceiling check: the
    walked-count comparison cannot report anything here.
    """
    files = baseline_files()
    index_lines = [json.loads(line) for line in files[INDEX_NAME].split(b"\n") if line]
    frame = files[PAYLOAD_NAME][: index_lines[0]["size"]]
    size = len(frame)
    digest = format(zlib.crc32(frame) & 0xFFFFFFFF, "08x")

    payload = frame * total
    lines = []
    for position in range(total):
        lines.append(
            json.dumps(
                {
                    "v": 1,
                    "seq": position,
                    "offset": position * size,
                    "size": size,
                    "t_us": position * 1_000,
                    "crc32": digest,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )
    index = b"\n".join(lines) + b"\n"

    manifest = json.loads(files[MANIFEST_NAME])
    manifest["frame_count"] = total
    manifest["duration_us"] = (total - 1) * 1_000 + 1
    manifest["files"]["video.mjpg"] = {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest["files"]["frames.jsonl"] = {
        "bytes": len(index),
        "sha256": hashlib.sha256(index).hexdigest(),
    }
    return {
        PAYLOAD_NAME: payload,
        INDEX_NAME: index,
        MANIFEST_NAME: json.dumps(manifest, separators=(",", ":")).encode("utf-8") + b"\n",
    }


def _find_property(node: object, property_name: str) -> dict | None:
    """Find one property schema anywhere in a document, by name."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and property_name in properties:
            candidate = properties[property_name]
            if isinstance(candidate, dict):
                return candidate
        for key in ("$defs", "definitions", "items"):
            found = _find_property(node.get(key), property_name)
            if found is not None:
                return found
        for value in node.values():
            found = _find_property(value, property_name)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_property(value, property_name)
            if found is not None:
                return found
    return None


def _violating_value(node: dict, keyword: str) -> object:
    """A value that breaks exactly this keyword and no other."""
    if keyword == "const":
        return 3 if node.get("const") == 2 else 2
    if keyword == "maximum":
        return node["maximum"] + 1
    if keyword == "minimum":
        return node["minimum"] - 1
    if keyword == "pattern":
        return "not-a-contract-value"
    if keyword == "enum":
        return "not_a_documented_value"
    if keyword == "format":
        # The documented RFC3339 shape, but the calendar has no such day: only a real
        # date-time check (and the dedicated clock check that replaces it) can see it.
        return "2026-02-30T12:00:00.000Z"
    raise AssertionError(f"no violation known for keyword {keyword!r}")


def _assert_dedicated_check_fires(
    tmp_path, entry: dict, dedicated: tuple[str, ...], schemas: dict
) -> None:
    observed = {
        violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)
    }
    assert observed, f"{entry['id']} reports nothing: a defect slipped through"
    assert set(dedicated) & observed, (
        f"{entry['id']} reported {sorted(observed)} instead of any dedicated check "
        f"{sorted(dedicated)}"
    )


@pytest.mark.parametrize("pair", sorted(FRAME_DEDICATED_RULES), ids=_pair_id)
def test_a_suppressed_frame_keyword_is_still_refused(tmp_path, schemas, pair) -> None:
    """Decision 10: silencing a schema keyword may never silence the bound itself."""
    property_name, keyword = pair
    node = _find_property(_resolved(schemas["frame"]), property_name)
    assert node is not None, f"frame schema has no property {property_name}"
    assert keyword in node, f"{property_name} carries no {keyword} keyword to suppress"

    files = baseline_files()
    lines = files[INDEX_NAME].split(b"\n")
    record = json.loads(lines[1])
    record[property_name] = _violating_value(node, keyword)
    lines[1] = json.dumps(record, separators=(",", ":"), sort_keys=False).encode("utf-8")
    files[INDEX_NAME] = b"\n".join(lines)

    entry = synthetic_media_entry(tmp_path, f"frame-{property_name}-{keyword}", files)
    _assert_dedicated_check_fires(tmp_path, entry, FRAME_DEDICATED_RULES[pair], schemas)


@pytest.mark.parametrize("pair", sorted(MANIFEST_DEDICATED_RULES), ids=_pair_id)
def test_a_suppressed_manifest_keyword_is_still_refused(tmp_path, schemas, pair) -> None:
    """The manifest may not keep a bound only in a keyword the validator ignores."""
    property_name, keyword = pair
    node = _find_property(_resolved(schemas["manifest"]), property_name)
    assert node is not None, f"manifest schema has no property {property_name}"
    assert keyword in node, f"{property_name} carries no {keyword} keyword to suppress"

    if (property_name, keyword) == ("frame_count", "maximum"):
        # A declared count above the ceiling is only detectable by the bound itself:
        # a segment whose index really has that many frames is otherwise conformant.
        files = _clip_with_frame_count(node["maximum"] + 1)
    else:
        files = baseline_files()
        record = json.loads(files[MANIFEST_NAME])
        _set_anywhere(record, property_name, _violating_value(node, keyword))
        files[MANIFEST_NAME] = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"

    entry = synthetic_media_entry(tmp_path, f"manifest-{property_name}-{keyword}", files)
    _assert_dedicated_check_fires(tmp_path, entry, MANIFEST_DEDICATED_RULES[pair], schemas)


@pytest.mark.parametrize("pair", sorted(MANIFEST_DEDICATED_RULES), ids=_pair_id)
def test_a_suppressed_active_keyword_is_still_refused(tmp_path, schemas, pair) -> None:
    """media-format.md §5: an interrupted segment reuses the manifest field rules."""
    property_name, keyword = pair
    node = _find_property(_resolved(schemas["active"]), property_name)
    if node is None:
        # The active record is a manifest-shaped record that omits the finalization
        # fields, so a pair can legitimately have nothing to suppress here — but only
        # for a field on this list, never for one the record does contain.
        assert property_name in _ACTIVE_ABSENT_FIELDS, (
            f"the active record has no {property_name} and that field is not a known"
            " finalization-only field"
        )
        pytest.skip(f"active record has no {property_name} field")
    assert keyword in node, f"{property_name} carries no {keyword} keyword to suppress"

    files = _active_files()
    record = json.loads(files[ACTIVE_NAME])
    if property_name in ("source", "start_utc"):
        # The committed interrupted segment has no known UTC; a clock-field violation
        # has to be tested against a segment that does, or the nullity rule would
        # report a different (and correct) defect instead.
        baseline = json.loads(baseline_files()[MANIFEST_NAME])
        record["clock"] = dict(baseline["clock"])
    _set_anywhere(record, property_name, _violating_value(node, keyword))
    files[ACTIVE_NAME] = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"

    entry = synthetic_media_entry(
        tmp_path, f"active-{property_name}-{keyword}", files, kind="active"
    )
    _assert_dedicated_check_fires(tmp_path, entry, MANIFEST_DEDICATED_RULES[pair], schemas)


def _active_files() -> dict[str, bytes]:
    """The committed interrupted segment, as the name -> bytes map the validator wants."""
    source = FIXTURES / "media" / "valid" / "active-unknown-clock"
    return {path.name: path.read_bytes() for path in sorted(source.iterdir())}


def _set_anywhere(record: dict, property_name: str, value: object) -> None:
    """Set a property wherever it sits in the record (top level or one object down)."""
    if property_name in record:
        record[property_name] = value
        return
    for nested in record.values():
        if isinstance(nested, dict) and property_name in nested:
            nested[property_name] = value
            return
    raise AssertionError(f"{property_name} is not present in the baseline record")


def test_a_segment_over_the_frame_ceiling_is_refused_by_the_bound(tmp_path, schemas) -> None:
    """MAX_FRAMES_PER_CLIP is enforced, not merely declared.

    The segment is internally consistent, so the only finding available is the ceiling
    itself; deleting that check leaves this test red.
    """
    entry = synthetic_media_entry(
        tmp_path, "frame-count-over-ceiling", _clip_with_frame_count(MAX_FRAMES_PER_CLIP + 1)
    )
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert observed == {E.FRAME_COUNT_MISMATCH}, sorted(observed)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("device_id", "0123456789abcdef0123456789abcdef\n"),
        ("boot_id", "39dba04fcee20cb62d55bb235c3392ec\r"),
        ("clip_id", "39dba04fcee20cb62d55bb235c3392ec-00000000\n"),
    ],
)
def test_a_terminator_inside_an_identifier_is_refused(tmp_path, schemas, field_name, value) -> None:
    """media-format.md §2: an ID is *exactly* the hex run, so a stray byte fails.

    The schema ``pattern`` behind these fields is suppressed in favour of the dedicated
    checks, so only an anchored check can catch the trailing byte a C writer leaves.
    """
    files = baseline_files()
    record = json.loads(files[MANIFEST_NAME])
    record[field_name] = value
    if field_name == "clip_id":
        record["clip_id"] = value
    files[MANIFEST_NAME] = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"

    entry = synthetic_media_entry(tmp_path, f"manifest-{field_name}-terminator", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert E.ID_SYNTAX_INVALID in observed, sorted(observed)


# --- Round 2: JSON number notation, the index ceiling, the calendar ----------


def test_is_int_accepts_only_integral_json_numbers() -> None:
    """``type: integer`` is about the *value*, so every bound has to follow it.

    A bound skipped for the integral-float spelling is a bound nobody reports: the
    schema keyword for it is suppressed in favour of the dedicated check that skipped
    it, so the pair of them is silent. ``nan`` and ``inf`` have no JSON notation at all.
    """
    from tools.contracts.media_validate import _is_int

    assert _is_int(0) and _is_int(1) and _is_int(-(2**53 - 1))
    assert _is_int(1.0) and _is_int(120000001.0) and _is_int(1.20000001e8)
    assert not _is_int(True)
    assert not _is_int(False)
    assert not _is_int(1.5)
    assert not _is_int(float("nan"))
    assert not _is_int(float("inf"))
    assert not _is_int("1")
    assert not _is_int(None)


def _baseline_files_without_checksums() -> dict[str, bytes]:
    """The committed baseline segment, minus the harness checksums file.

    These tests rewrite one record, which makes a checksum comparison a second finding
    about a defect that has nothing to do with integrity; the vectors that *are* about
    integrity are the committed checksum ones.
    """
    return {
        name: data for name, data in baseline_files().items() if name != CHECKSUMS_NAME
    }


def _manifest_bytes_with_raw_number(key: str, notation: str) -> bytes:
    """The committed manifest with one number rewritten as *raw* JSON text."""
    data = baseline_files()[MANIFEST_NAME]
    member = key.encode("utf-8")
    replaced, count = re.subn(
        rb'"%b":-?[0-9]+' % member,
        b'"%b":%b' % (member, notation.encode("utf-8")),
        data,
        count=1,
    )
    assert count == 1, (key, notation)
    return replaced


def _repoint_manifest_entry(files: dict[str, bytes], file_name: str) -> None:
    """Make the manifest describe the bytes these tests just rewrote.

    Only the *index line notation* is under test here, so the hash and length of the
    edited file are made true; the committed corpus has its own integrity vectors.
    """
    manifest = json.loads(files[MANIFEST_NAME])
    data = files[file_name]
    manifest["files"][file_name] = {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    files[MANIFEST_NAME] = json.dumps(manifest, separators=(",", ":")).encode("utf-8") + b"\n"


@pytest.mark.parametrize(
    ("key", "notation", "code"),
    [
        ("duration_us", "120000001.0", E.DURATION_TOO_LONG),
        ("duration_us", "1.20000001e8", E.DURATION_TOO_LONG),
        ("width", "1601.0", E.DIMENSIONS_EXCEEDED),
        ("nominal_fps", "31.0", E.NOMINAL_FPS_INVALID),
    ],
    ids=["duration-decimal", "duration-exponent", "width-decimal", "nominal-fps-decimal"],
)
def test_an_integral_float_still_meets_its_dedicated_bound(
    tmp_path, schemas, key: str, notation: str, code: str
) -> None:
    """Every spelling of a JSON integer reaches the dedicated bound, and only it.

    The notation is written straight into the bytes here, which is what a nonconforming
    writer produces; the corpus vectors of the same names are the committed evidence.
    """
    files = _baseline_files_without_checksums()
    files[MANIFEST_NAME] = _manifest_bytes_with_raw_number(key, notation)
    entry = synthetic_media_entry(tmp_path, f"float-{key}-{notation}", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert observed == {code}, (key, notation, sorted(observed))


@pytest.mark.parametrize(
    ("field_name", "raw", "case_id"),
    [
        ("offset", "434.5", "offset-half"),
        ("size", "413.5", "size-half"),
        ("offset", '"434"', "offset-string"),
        ("size", '"413"', "size-string"),
        ("offset", "true", "offset-bool"),
        ("size", "true", "size-bool"),
    ],
    ids=["offset-half", "size-half", "offset-string", "size-string", "offset-bool", "size-bool"],
)
def test_a_float_byte_position_is_a_finding_not_a_crash(
    tmp_path, schemas, field_name: str, raw: str, case_id: str
) -> None:
    """A byte position that is not a JSON integer is named, never raised through.

    `type: integer` refuses a half, a string and the bool Python calls an int, and
    neither the walk's arithmetic nor its payload slice could use any of them. Today
    the schema's structural report names all six of these before the walk is asked, so
    the `TypeError` this guards against is a counterfactual about the layered check as a
    whole rather than about this branch alone: lift the type keyword the way
    :func:`test_a_byte_position_the_schema_no_longer_types_is_still_a_finding` does and
    such a value reaches arithmetic that can only raise or quietly fudge it. Integral
    notations — `434.0`, `4.34e2` — are the opposite case and belong to
    :func:`test_an_integral_byte_position_in_any_notation_validates`.
    """
    files = _baseline_files_without_checksums()
    lines = files[INDEX_NAME].split(b"\n")
    record = json.loads(lines[1])
    member = field_name.encode("utf-8")
    replaced, count = re.subn(
        rb'"%b":-?[0-9]+' % member,
        b'"%b":%b' % (member, raw.encode("utf-8")),
        lines[1],
        count=1,
    )
    assert count == 1
    lines[1] = replaced
    files[INDEX_NAME] = b"\n".join(lines)
    _repoint_manifest_entry(files, INDEX_NAME)

    entry = synthetic_media_entry(tmp_path, f"float-{case_id}", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert observed == {E.FRAME_SCHEMA}, sorted(observed)


@pytest.mark.parametrize(
    ("edits", "bad_crc", "codes", "case_id"),
    [
        ((("offset", "0.0"),), False, set(), "offset-decimal"),
        ((("size", "434.0"),), False, set(), "size-decimal"),
        ((("size", "4.34e2"),), False, set(), "size-exponent"),
        ((("offset", "0.0"), ("size", "4.34e2")), False, set(), "both-notations"),
        ((("size", "434.0"),), True, {E.FRAME_CRC_MISMATCH}, "size-decimal-bad-crc"),
    ],
    ids=[
        "offset-decimal",
        "size-decimal",
        "size-exponent",
        "both-notations",
        "size-decimal-bad-crc",
    ],
)
def test_an_integral_byte_position_in_any_notation_validates(
    tmp_path,
    schemas,
    edits: tuple[tuple[str, str], ...],
    bad_crc: bool,
    codes: set[str],
    case_id: str,
) -> None:
    """`0.0` and `4.34e2` are JSON integers, so they are byte positions too (AC-03).

    The frame record publishes `type: integer`, which every whole-number JSON notation
    satisfies, and the shared :func:`_is_int` the dedicated bounds use agrees; the
    walk may not be stricter than the contract it certifies. It has to normalise to
    `int` and then do exactly what it does for the plain spelling. The last case
    corrupts the CRC of the *same* float-written record: if normalisation let the walk
    skip the line, that finding would be missing too. And because the record is the
    first one, a clean run also proves the following record's plain integer `offset`
    continues from the `previous_end` these notations produced.
    """
    files = _baseline_files_without_checksums()
    lines = files[INDEX_NAME].split(b"\n")
    record = lines[0]
    for field_name, raw in edits:
        member = field_name.encode("utf-8")
        replaced, count = re.subn(
            rb'"%b":-?[0-9]+' % member,
            b'"%b":%b' % (member, raw.encode("utf-8")),
            record,
            count=1,
        )
        assert count == 1, (field_name, raw)
        record = replaced
    if bad_crc:
        declared = f'"crc32":"{json.loads(record)["crc32"]}"'.encode("utf-8")
        assert declared in record
        record = record.replace(declared, b'"crc32":"deadbeef"')
    lines[0] = record
    files[INDEX_NAME] = b"\n".join(lines)
    _repoint_manifest_entry(files, INDEX_NAME)

    entry = synthetic_media_entry(tmp_path, f"notation-{case_id}", files)
    observed = [violation for violation in validate_media_fixture(tmp_path, entry, schemas)]
    assert {violation.code for violation in observed} == codes, [
        violation.render() for violation in observed
    ]


@pytest.mark.parametrize(("raw", "case_id"), [("434.5", "half"), ("true", "bool")])
def test_a_byte_position_the_schema_no_longer_types_is_still_a_finding(
    tmp_path, schemas, raw: str, case_id: str
) -> None:
    """The walk's own integer check stops a byte position `int()` would fudge.

    `type: integer` in the frame record refuses a half and a bool today, so the schema
    report names the line first and the walk never sees either value. That ordering is
    not something the walk may lean on: converting with `int()` is what makes the
    payload slice legal, and `int()` on its own is no judge — it truncates `434.5` to a
    byte position the writer never wrote, and reads `true` as `1`. Either one would be
    checked against the *wrong* bytes, reported as a CRC or continuity defect, or pass
    unnoticed. Here the type keyword is lifted out of the schema — the state a later
    edit to that document could put it in — so it is the walk's own check or a wrong
    answer, and it has to be a finding.
    """
    weakened = copy.deepcopy(schemas)
    del weakened["frame"]["properties"]["offset"]["type"]
    files = _baseline_files_without_checksums()
    lines = files[INDEX_NAME].split(b"\n")
    replaced, count = re.subn(rb'"offset":-?[0-9]+', b'"offset":%b' % raw.encode("utf-8"), lines[1], count=1)
    assert count == 1
    lines[1] = replaced
    files[INDEX_NAME] = b"\n".join(lines)
    _repoint_manifest_entry(files, INDEX_NAME)

    entry = synthetic_media_entry(tmp_path, f"offset-untyped-{case_id}", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, weakened)}
    assert observed == {E.FRAME_SCHEMA}, sorted(observed)


def test_the_manifest_bounds_the_index_below_the_payload(schemas: dict) -> None:
    """media-format.md §2: frames.jsonl has its own 1,843,200-byte ceiling.

    Sharing the payload entry's 268,435,456-byte maximum would let a manifest declare an
    index three times the size the format allows, so the boundary is pinned on both
    sides of the two file entries.
    """
    from tools.contracts.schema_docs import schema_error_report

    manifest = json.loads(baseline_files()[MANIFEST_NAME])
    manifest["files"]["video.mjpg"]["bytes"] = MAX_PAYLOAD_BYTES
    manifest["files"]["frames.jsonl"]["bytes"] = MAX_INDEX_BYTES
    assert not schema_error_report(schemas["manifest"], manifest)

    manifest["files"]["frames.jsonl"]["bytes"] = MAX_INDEX_BYTES + 1
    found = [(property_name, keyword) for property_name, keyword, _ in schema_error_report(
        schemas["manifest"], manifest
    )]
    assert found == [("bytes", "maximum")], found


# --- Round 4: integrity fields are compared or reported, and the bounds the
#     schema cannot reach are enforced by the walk and the clock check ------------

#: The four ways a manifest or sidecar entry can state an integrity property that is
#: nothing to compare: a digest with a stray byte, a digest that is not a string at all,
#: and a length that arrived as text or as nothing.
_INTEGRITY_DAMAGE = [
    (MANIFEST_NAME, PAYLOAD_NAME, "sha256", lambda value: value + "\n",
     {E.MANIFEST_HASH_MISMATCH, E.MANIFEST_SCHEMA}),
    (MANIFEST_NAME, INDEX_NAME, "sha256", lambda value: None,
     {E.MANIFEST_HASH_MISMATCH, E.MANIFEST_SCHEMA}),
    (MANIFEST_NAME, INDEX_NAME, "bytes", str,
     {E.MANIFEST_SIZE_MISMATCH, E.MANIFEST_SCHEMA}),
    (MANIFEST_NAME, PAYLOAD_NAME, "bytes", lambda value: None,
     {E.MANIFEST_SIZE_MISMATCH, E.MANIFEST_SCHEMA}),
    (CHECKSUMS_NAME, PAYLOAD_NAME, "sha256", lambda value: value + " ",
     {E.CHECKSUMS_SCHEMA,}),
    (CHECKSUMS_NAME, INDEX_NAME, "bytes", str, {E.CHECKSUMS_SCHEMA,}),
]


@pytest.mark.parametrize(
    ("document", "file_name", "property_name", "damage", "codes"),
    _INTEGRITY_DAMAGE,
    ids=[
        "manifest-digest-padded",
        "manifest-digest-null",
        "manifest-index-length-as-text",
        "manifest-payload-length-null",
        "sidecar-digest-padded",
        "sidecar-length-as-text",
    ],
)
def test_a_malformed_integrity_field_is_reported_not_skipped(
    tmp_path, schemas, document, file_name, property_name, damage, codes
) -> None:
    """A field the validator cannot measure is a defect, never a check to pass over.

    Every case used to be silent: the dedicated checks only compared a digest once it
    matched ``[0-9a-f]{64}`` and only compared a length once it was an integer, so the
    malformed declaration certified the bytes beside it by default. Now each one names
    the shape it was handed, and the schema keyword refuses it too where a keyword can.
    """
    files = baseline_files()
    if document == MANIFEST_NAME:
        # The sidecar describes the manifest's own bytes, so a manifest edit travels
        # without it: a stale sidecar would report a second defect the case is not about.
        del files[CHECKSUMS_NAME]
    record = json.loads(files[document])
    declaration = record["files"][file_name]
    declaration[property_name] = damage(declaration[property_name])
    files[document] = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"

    entry = synthetic_media_entry(tmp_path, f"integrity-{property_name}-{file_name}", files)
    observed = {
        violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)
    }
    assert observed == codes, (document, file_name, property_name, sorted(observed))


def test_the_digest_shape_is_pinned_where_the_digest_is_declared(schemas) -> None:
    """``minLength``/``maxLength``: 64 is a fact about the value, not only the pattern.

    The three notations that publish a digest must say so identically, because the OpenAPI
    mirrors are what a consumer generates a parser from; a mirror without the length
    keywords accepts a padded digest the media schema refuses.
    """
    import yaml

    node = _find_property(_resolved(schemas["manifest"]), "sha256")
    assert node is not None, "the manifest declares no sha256 property"
    assert node["minLength"] == node["maxLength"] == 64, node
    assert node["pattern"] == "^[0-9a-f]{64}$", node

    for contract in ("device", "backend"):
        document = yaml.safe_load(
            (REPO_ROOT / "contracts" / f"{contract}-v1.yaml").read_text(encoding="utf-8")
        )
        mirror = document["components"]["schemas"]["Sha256"]
        assert mirror["minLength"] == mirror["maxLength"] == 64, contract
        assert mirror["pattern"] == "^[0-9a-f]{64}$", contract


def _active_with_frame_count(total: int) -> dict[str, bytes]:
    """An interrupted segment of ``total`` frames, with nothing declaring the count.

    The same repeated baseline frame keeps every per-frame invariant true; the point is
    that an active record carries no ``frame_count``, so no manifest bound exists for the
    3,601st record to trip and only the walk can refuse it.
    """
    clip = _clip_with_frame_count(total)
    return {
        PAYLOAD_NAME + ".part": clip[PAYLOAD_NAME],
        INDEX_NAME + ".part": clip[INDEX_NAME],
        ACTIVE_NAME: _active_files()[ACTIVE_NAME],
    }


@pytest.mark.parametrize(
    ("kind", "total", "codes"),
    [
        ("clip", MAX_FRAMES_PER_CLIP, set()),
        ("clip", MAX_FRAMES_PER_CLIP + 1, {E.FRAME_COUNT_MISMATCH}),
        ("active", MAX_FRAMES_PER_CLIP, set()),
        ("active", MAX_FRAMES_PER_CLIP + 1, {E.FRAME_COUNT_MISMATCH}),
    ],
    ids=["clip-at-ceiling", "clip-past-ceiling", "active-at-ceiling", "active-past-ceiling"],
)
def test_the_walk_refuses_the_record_past_the_clip_ceiling(
    tmp_path, schemas, kind, total, codes
) -> None:
    """media-format.md §2's 3,600-frame bound is enforced while walking, for both kinds.

    The finalized half of this was already covered by the manifest's ``frame_count``
    comparison; the active half had nothing to compare against, which is why the gate has
    to sit in the walk before a record is measured or parsed — the 3,601st record's ``seq``
    is outside the frame schema, and reporting that instead of the ceiling would blame
    the record for a bound on the clip.
    """
    files = (
        _clip_with_frame_count(total) if kind == "clip" else _active_with_frame_count(total)
    )
    entry = synthetic_media_entry(tmp_path, f"{kind}-records-{total}", files, kind=kind)
    observed = {
        violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)
    }
    assert observed == codes, (kind, total, sorted(observed))


def test_the_committed_over_ceiling_vector_is_an_active_segment(index: list[dict]) -> None:
    """The one committed over-ceiling vector is the kind no manifest bound can reach."""
    entry = next(
        item for item in index if item["id"] == "media/invalid/index-records-above-clip-ceiling"
    )
    assert entry["kind"] == "active", entry["kind"]
    assert entry["expected_error_codes"] == [E.FRAME_COUNT_MISMATCH]
    lines = [line for line in _index_bytes(entry).split(b"\n") if line]
    assert len(lines) == MAX_FRAMES_PER_CLIP + 1, len(lines)
    record = json.loads(_read(entry["id"], ACTIVE_NAME))
    assert "frame_count" not in record, "an active record must not declare a count"


@pytest.mark.parametrize(
    ("uncertainty", "codes"),
    [
        (UINT53_MAX, set()),
        (UINT53_MAX + 1, {E.CLOCK_NULLITY_MISMATCH, E.MANIFEST_SCHEMA}),
    ],
    ids=["at-the-ceiling", "one-past-the-ceiling"],
)
def test_the_clock_uncertainty_ceiling_is_enforced_beside_the_schema_keyword(
    tmp_path, schemas, uncertainty, codes
) -> None:
    """media-format.md §2 bounds every JSON integer of this format at 2^53−1.

    The dedicated check owned only the negative half, so an estimate above the range a
    conforming reader represents exactly was refused by a keyword the harness suppresses
    for its sibling properties and nothing else named it. Both halves are asserted here:
    the ceiling value itself is conformant, and one past it reports where it lives.
    """
    files = baseline_files()
    del files[CHECKSUMS_NAME]
    record = json.loads(files[MANIFEST_NAME])
    record["clock"]["uncertainty_ms"] = uncertainty
    files[MANIFEST_NAME] = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"

    entry = synthetic_media_entry(tmp_path, f"clock-uncertainty-{uncertainty}", files)
    observed = {
        violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)
    }
    assert observed == codes, (uncertainty, sorted(observed))


def test_the_committed_uncertainty_vector_carries_the_refused_value(index: list[dict]) -> None:
    """The dedicated ceiling has a corpus vector of its own, not only a unit test."""
    entry = next(
        item for item in index if item["id"] == "media/invalid/clock-uncertainty-above-uint53"
    )
    assert entry["expected"] == "invalid"
    assert entry["expected_error_codes"] == [E.CLOCK_NULLITY_MISMATCH, E.MANIFEST_SCHEMA]
    manifest = json.loads(_read(entry["id"], MANIFEST_NAME))
    assert manifest["clock"]["uncertainty_ms"] == UINT53_MAX + 1


# --- Round 5: how an integer may be written, and the field rules on their own ----

#: ``(notation, integral?, case)`` for the digits a JSON number may arrive in.
_INTEGER_NOTATIONS: tuple[tuple[str, bool, str], ...] = (
    ("0", True, "plain"),
    ("0.0", True, "fraction-part"),
    ("0e0", True, "exponent"),
    ("0E+0", True, "signed-exponent"),
    ("120000001", True, "wide-plain"),
    ("120000001.0", True, "wide-fraction"),
    ("1.20000001e8", True, "wide-exponent"),
    ("1e-400", False, "subnormal-that-floats-round-to-zero"),
    ("0.5", False, "half"),
    ("1.5e0", False, "half-by-exponent"),
    ("Infinity", False, "infinity"),
    ("NaN", False, "not-a-number"),
)


@pytest.mark.parametrize(
    ("notation", "integral", "case"),
    _INTEGER_NOTATIONS,
    ids=[case for *_rest, case in _INTEGER_NOTATIONS],
)
def test_a_json_integer_is_judged_on_the_digits_it_carries(
    notation: str, integral: bool, case: str
) -> None:
    """``type: integer`` is about the number, and the number is what was written (AC-06).

    The judge runs on a ``Decimal``, because the binary float a default parse produces
    has already answered the question wrongly: ``1e-400`` converts to exactly ``0.0``,
    which every float-based check would call an integer.
    """
    assert decimal_is_integral(decimal.Decimal(notation)) is integral, case
    if notation == "1e-400":
        assert float("1e-400") == 0.0  # the trap this predicate exists to avoid


def test_the_index_is_parsed_so_an_exponent_survives_the_parse(index: list[dict], schemas) -> None:
    """A fractional ``t_us`` is refused, and the committed bytes really say it (AC-03)."""
    entry = next(item for item in index if item["id"] == "media/invalid/index-first-t-us-fractional")
    assert entry["expected"] == "invalid"
    assert entry["expected_error_codes"] == [E.FRAME_SCHEMA]
    assert b'"t_us":1e-400' in _index_bytes(entry)
    observed = {violation.code for violation in validate_media_fixture(FIXTURES, entry, schemas)}
    assert observed == {E.FRAME_SCHEMA}, observed


def test_the_frame_record_admits_every_integral_notation(index: list[dict], schemas) -> None:
    """What the schema publishes as valid notation must validate (AC-02)."""
    entry = next(item for item in index if item["id"] == "media/valid/index-integral-notations")
    raw = _index_bytes(entry)
    assert b'"seq":0.0' in raw and b'"offset":0e0' in raw and b'"t_us":0E+0' in raw
    assert entry["expected"] == "valid"
    assert validate_media_fixture(FIXTURES, entry, schemas) == []


def test_an_overflowing_exponent_is_a_finding_and_never_a_crash(tmp_path, schemas) -> None:
    """``1e999`` is an integral spelling of a number no byte position can be.

    A float parse would have produced ``inf``, which Python calls an integer, and the
    walk's ``int()`` would then have raised: the crash this gate exists to turn into a
    named bound violation.
    """
    files = baseline_files()
    lines = files[INDEX_NAME].split(b"\n")
    assert b'"t_us":66667' in lines[1]
    lines[1] = lines[1].replace(b'"t_us":66667', b'"t_us":1e999')
    files[INDEX_NAME] = b"\n".join(lines)
    entry = synthetic_media_entry(tmp_path, "index-t-us-overflow", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert E.FRAME_T_US_TOO_LARGE in observed, observed


def test_the_gate_the_walk_trusts_refuses_every_spelling_it_cannot_hold() -> None:
    """One predicate decides what the walk's arithmetic may hold: :func:`_is_int`.

    The walk parses with ``parse_float=Decimal``, so what it has to refuse are the
    ``Decimal`` spellings a float would have rounded away (``1e-400``) and the two literals
    JSON admits no notation for — ``int()`` of either raises, where the contract wants a
    code. The integral spellings the published record admits (``0``, ``0.0``, ``0e0``) are
    the ones it must accept, or a conforming writer's bytes would be refused.
    """
    from tools.contracts.media_validate import _is_int

    assert _is_int(decimal.Decimal("0")) is True
    assert _is_int(decimal.Decimal("0.0")) is True
    assert _is_int(decimal.Decimal("0e0")) is True
    assert _is_int(decimal.Decimal("1.20000001e8")) is True
    assert _is_int(decimal.Decimal("-120000001.0")) is True
    assert _is_int(decimal.Decimal("1e-400")) is False
    assert _is_int(decimal.Decimal("1.5")) is False
    assert _is_int(decimal.Decimal("Infinity")) is False
    assert _is_int(decimal.Decimal("NaN")) is False
    assert _is_int(float("inf")) is False
    assert _is_int(float("nan")) is False
    assert _is_int(True) is False
    assert _is_int("0") is False


def test_an_index_line_written_as_a_non_number_is_refused_not_crashed(tmp_path, schemas) -> None:
    """The gate above is the walk's only precondition, so it has to hold for both literals.

    Python's JSON reader accepts ``Infinity`` and ``NaN``, and a line holding one would
    otherwise reach ``int()`` in the byte arithmetic below the gate — an exception escaping
    the run rather than the ``FRAME_SCHEMA`` finding the record's ``type`` calls for.
    """
    for notation in ("Infinity", "NaN"):
        files = {
            name: data for name, data in baseline_files().items() if name != CHECKSUMS_NAME
        }
        lines = files[INDEX_NAME].split(b"\n")
        assert b'"t_us":0,' in lines[0], lines[0]
        lines[0] = lines[0].replace(b'"t_us":0,', b'"t_us":%s,' % notation.encode(), 1)
        files[INDEX_NAME] = b"\n".join(lines)
        entry = synthetic_media_entry(tmp_path, f"index-first-t-us-{notation}", files)
        observed = {
            violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)
        }
        assert E.FRAME_SCHEMA in observed, (notation, observed)


@pytest.mark.parametrize(
    ("member", "notation"),
    [
        ("nominal_fps", "Infinity"),
        ("nominal_fps", "NaN"),
        ("width", "Infinity"),
        ("frame_count", "Infinity"),
        ("duration_us", "Infinity"),
    ],
    ids=["fps-inf", "fps-nan", "width-inf", "count-inf", "duration-inf"],
)
def test_a_manifest_member_written_as_a_non_number_is_refused_not_measured(
    tmp_path, schemas, member: str, notation: str
) -> None:
    """``Infinity`` has no JSON notation, so its *type* is the defect (AC-06).

    A bound would be the wrong report: comparing a ceiling with something that is not a
    number dresses a type error up as an out-of-range value. The schema's ``type`` check
    is what refuses it, and the walk's own gate is what keeps the same spelling in an
    index line out of ``int()``.
    """
    files = {
        name: data for name, data in baseline_files().items() if name != CHECKSUMS_NAME
    }
    original = files[MANIFEST_NAME]
    rewritten, count = re.subn(
        rb'"%b":\s*-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?' % member.encode(),
        b'"%b":%b' % (member.encode(), notation.encode()),
        original,
        count=1,
    )
    assert count == 1, member
    files[MANIFEST_NAME] = rewritten
    entry = synthetic_media_entry(tmp_path, f"manifest-{member}-{notation}", files)
    observed = {violation.code for violation in validate_media_fixture(tmp_path, entry, schemas)}
    assert E.MANIFEST_SCHEMA in observed, (member, notation, observed)


def _baseline_manifest() -> dict:
    return json.loads(baseline_files()[MANIFEST_NAME])


def test_the_field_rules_judge_what_is_there_and_leave_absence_to_the_schema() -> None:
    """Required-ness is a ``required`` keyword; these are the rules about present members."""
    from tools.contracts.media_validate import validate_manifest_fields

    assert validate_manifest_fields({"v": MEDIA_VERSION}) == []
    assert validate_manifest_fields(_baseline_manifest()) == []

    melted = validate_manifest_fields(
        {**_baseline_manifest(), "close_reason": "melted"}, location_prefix="manifest_base64url"
    )
    assert [violation.code for violation in melted] == [E.CLOSE_REASON_UNKNOWN]
    assert melted[0].location == "manifest_base64url.close_reason"


def test_the_field_rules_name_the_transport_that_carried_the_manifest() -> None:
    """The same defect over either wire differs only in where it was found."""
    from tools.contracts.media_validate import validate_manifest_fields

    baseline = _baseline_manifest()
    on_card = validate_manifest_fields({**baseline, "boot_id": "0" * 32})
    on_wire = validate_manifest_fields(
        {**baseline, "boot_id": "0" * 32}, location_prefix="manifest_base64url"
    )
    assert [v.location for v in on_card] != [v.location for v in on_wire]
    assert [v.code for v in on_card] == [v.code for v in on_wire]
    assert on_wire[0].location.startswith("manifest_base64url.")


def test_a_terminator_attached_to_an_identifier_makes_it_a_different_identifier() -> None:
    """32 hex is 32 hex, and a newline is a thirty-third character (AC-06)."""
    from tools.contracts.media_validate import validate_manifest_fields

    baseline = _baseline_manifest()
    for field, expected in (
        ("device_id", [E.ID_SYNTAX_INVALID]),
        ("clip_id", [E.ID_SYNTAX_INVALID]),
        ("boot_id", [E.ID_SYNTAX_INVALID, E.CLIP_BOOT_PREFIX_MISMATCH]),
    ):
        found = validate_manifest_fields({**baseline, field: baseline[field] + "\n"})
        assert [violation.code for violation in found] == expected, (field, found)


def test_a_timestamp_with_the_terminator_still_attached_is_not_a_timestamp() -> None:
    """The clock's calendar check reads the whole value, not up to the first newline."""
    from tools.contracts.media_validate import validate_manifest_fields

    baseline = _baseline_manifest()
    assert baseline["clock"]["source"] == "sntp"
    stamped = baseline["clock"]["start_utc"]
    found = validate_manifest_fields(
        {**baseline, "clock": {**baseline["clock"], "start_utc": stamped + "\n"}}
    )
    assert [violation.code for violation in found] == [E.CLOCK_TIMESTAMP_INVALID], found


def test_a_manifest_number_is_judged_on_the_digits_it_carries(index: list[dict], schemas: dict) -> None:
    """``266667.000000000001`` is not the integer it rounds to, and ``266667.0`` is (AC-03).

    The frame index has parsed exact numbers since round two; the manifest is the other
    record the device writes, and a duration that becomes legal only on the way through a
    binary float is a duration nobody stated. The valid twin is what keeps the refusal
    from being a refusal of the notation as such, and its checksums are recomputed in the
    generator because a sidecar that certifies other bytes than it ships is a defect of
    the corpus, not of the clip.
    """
    by_id = {entry["id"]: entry for entry in index}
    invalid = by_id["media/invalid/manifest-duration-rolls-to-integer"]
    assert {violation.code for violation in validate_media_fixture(FIXTURES, invalid, schemas)} == {
        E.MANIFEST_SCHEMA
    }
    data = _read(invalid["id"], MANIFEST_NAME)
    assert b'"duration_us":266667.000000000001' in data
    assert float("266667.000000000001") == 266667.0

    valid = by_id["media/valid/manifest-integral-notations"]
    assert {violation.code for violation in validate_media_fixture(FIXTURES, valid, schemas)} == set()
    data = _read(valid["id"], MANIFEST_NAME)
    for notation in (b'"duration_us":266667.0', b'"frame_count":4.0', b'"capture_order":42.0'):
        assert notation in data, notation
    manifest = json.loads(data.decode("utf-8"), parse_float=decimal.Decimal)
    checksums = json.loads(_read(valid["id"], CHECKSUMS_NAME).decode("utf-8"))
    entry = checksums["files"][MANIFEST_NAME]
    assert entry["bytes"] == len(data)
    assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    # The record still says what the baseline says it says: the notation is the only edit.
    baseline = by_id["media/valid/baseline"]
    assert manifest["duration_us"] == decimal.Decimal("266667.0")
    assert manifest["frame_count"] == 4
    assert manifest["capture_order"] == json.loads(
        _read(baseline["id"], MANIFEST_NAME).decode("utf-8")
    )["capture_order"]
