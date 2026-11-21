"""The golden-fixture corpus, stated declaratively as the single source of truth.

``python -m tools.contracts.generate_fixtures`` turns this module into
``contracts/fixtures/**`` plus its ``fixtures.json`` index; nothing else may write
into that tree. Each entry states what it proves, which validator codes it must
produce when it is a negative vector, and which requirement category it belongs to
(``tools/contracts/tests/test_ac_coverage.py`` turns those categories into the
acceptance-criteria coverage check).

Byte-level determinism, not review convenience, decides the shape of this file:
every value here is derived from a literal or from a hash of a literal, so no run
can drift.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Sequence

from .api_model import ALL_OPERATIONS, Operation
from .bounds import (
    API_VERSION,
    DEVICE_LEASE_DEFAULT_S,
    DEVICE_MAX_CLIP_LEASES,
    DEVICE_MAX_DOWNLOADING_CLIENTS,
    FIXTURE_FRAME_HEIGHT,
    FIXTURE_FRAME_WIDTH,
    FIXTURE_JPEG_QUALITY,
    FIXTURE_NOMINAL_FPS,
    MAX_CHUNK_BYTES,
    MAX_CURSOR_CHARS,
    MAX_FRAME_BYTES,
    MAX_INDEX_LINE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PAGE_LIMIT,
    MAX_PROTECTED_BYTES,
    UINT53_MAX,
    UPLOAD_EXPIRY_S,
)
from .errors import (
    ACCEPT_RANGES_INVALID,
    ACTIVE_JSON_INVALID,
    ACTIVE_SCHEMA,
    ACTIVE_TOO_LARGE,
    ACTIVE_WITH_MANIFEST,
    API_BODY_TOO_LARGE,
    API_SCHEMA,
    API_SCHEMA_MISSING_FIELD,
    API_VERSION_MISSING,
    API_VERSION_UNSUPPORTED,
    BASE64URL_ALPHABET_INVALID,
    BASE64URL_LENGTH_INVALID,
    CHECKSUMS_SCHEMA,
    CHECKSUM_HASH_MISMATCH,
    CHECKSUM_SIZE_MISMATCH,
    CHUNK_SIZE_INVALID,
    CLIP_BOOT_PREFIX_MISMATCH,
    CLOCK_NULLITY_MISMATCH,
    CLOCK_SOURCE_UNKNOWN_VALUE,
    CLOCK_TIMESTAMP_INVALID,
    CLOSE_REASON_UNKNOWN,
    CONTENT_LENGTH_MISMATCH,
    CONTENT_RANGE_INVALID,
    CURSOR_TOO_LONG,
    DIMENSIONS_EXCEEDED,
    DURATION_LE_FINAL_T_US,
    DURATION_TOO_LONG,
    ERROR_CODE_UNDOCUMENTED,
    ERROR_ENVELOPE_INVALID,
    ETAG_INVALID,
    FILE_NAME_NOT_ALLOWED,
    FRAME_COUNT_MISMATCH,
    FRAME_CRC_MISMATCH,
    FRAME_LINE_MALFORMED,
    FRAME_LINE_NOT_OBJECT,
    FRAME_LINE_TOO_LONG,
    FRAME_SCHEMA,
    FRAME_SCHEMA_MISSING_FIELD,
    FRAME_SEQ_NOT_CONSECUTIVE,
    FRAME_SIZE_INVALID,
    FRAME_T_US_DUPLICATE,
    FRAME_T_US_FIRST_NOT_ZERO,
    FRAME_T_US_NOT_INCREASING,
    FRAME_T_US_TOO_LARGE,
    HEADER_INVALID,
    HEADER_MISSING,
    ID_SYNTAX_INVALID,
    INDEX_EMPTY,
    INDEX_ENCODING_INVALID,
    INDEX_TRUNCATED,
    JPEG_DECODE_FAILED,
    JPEG_EOI_MISSING,
    JPEG_SOF_DIMENSION_MISMATCH,
    JPEG_SOI_MISSING,
    MANIFEST_DECODED_SCHEMA,
    MANIFEST_DECODED_TOO_LARGE,
    MANIFEST_HASH_MISMATCH,
    MANIFEST_JSON_INVALID,
    MANIFEST_JSON_INVALID_DECODED,
    MANIFEST_MISSING,
    MANIFEST_SCHEMA,
    MANIFEST_SCHEMA_MISSING_FIELD,
    MANIFEST_SIZE_MISMATCH,
    NOMINAL_FPS_INVALID,
    MANIFEST_TOO_LARGE,
    OFFSET_ARITHMETIC_OVERFLOW,
    OFFSET_EXCEEDS_PAYLOAD,
    OFFSET_NOT_CONTIGUOUS,
    PAGE_LIMIT_INVALID,
    PAYLOAD_TRAILING_BYTES,
    RANGE_MULTI_NOT_ALLOWED,
    RECOVERED_CLOSE_REASON_DISAGREE,
    UPLOAD_CHECKSUM_SYNTAX,
    UPLOAD_LENGTH_INVALID,
    UPLOAD_OFFSET_INVALID,
    VERSION_UNSUPPORTED,
)
from .jpeg import jpeg_seed
from .media_model import ClipPlan, ClockPlan, FramePlan, ProfilePlan

#: Provisioned device identity used across the corpus (media-format.md §1).
DEVICE_ID: Final[str] = "0123456789abcdef0123456789abcdef"

#: Second device identity, used only where a mismatch must be exercised.
OTHER_DEVICE_ID: Final[str] = "fedcba9876543210fedcba9876543210"

NOMINAL_FRAME_PERIOD_US: Final[int] = 66_667  # 15 fps, rounded up


def boot_id(name: str) -> str:
    """Deterministic 32-hex boot id for one fixture segment."""
    return hashlib.sha256(f"boot|{name}".encode("utf-8")).hexdigest()[:32]


def _token(name: str) -> str:
    """Deterministic 32-byte base64url (unpadded) credential for a fixture."""
    return base64.urlsafe_b64encode(hashlib.sha256(name.encode("utf-8")).digest()[:32]).decode("ascii").rstrip("=")


def _uuid(name: str) -> str:
    """Deterministic canonical UUID for a fixture."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"vdog-fixture|{name}"))


def _sha(name: str) -> str:
    """Deterministic 64-hex SHA-256-looking value for opaque hash fields."""
    return hashlib.sha256(f"vdog-fixture|{name}".encode("utf-8")).hexdigest()


def _frames(base: str, times: Sequence[int]) -> tuple[FramePlan, ...]:
    """Frame plans whose JPEG bytes depend only on ``base`` and the frame number."""
    return tuple(
        FramePlan(t_us=t_us, jpeg_key=jpeg_seed("clip", base, index))
        for index, t_us in enumerate(times)
    )


def _plan(
    name: str,
    times: Sequence[int],
    *,
    close_reason: str = "duration",
    recovered: bool = False,
    clock: ClockPlan = ClockPlan("unknown", None, None),
    capture_order: int = 42,
    dropped_frames: int = 0,
    duration_us: int | None = None,
    sequence: int = 0,
    firmware_version: str = "0.1.0",
    hardware_revision: str = "xiao-esp32s3-sense-proto-a",
    width: int = FIXTURE_FRAME_WIDTH,
    height: int = FIXTURE_FRAME_HEIGHT,
) -> ClipPlan:
    """Build one deterministic segment plan; ``duration_us`` defaults to one frame past the last."""
    if not times:
        raise ValueError("a fixture segment needs at least one frame")
    return ClipPlan(
        device_id=DEVICE_ID,
        boot_id=boot_id(name),
        sequence=sequence,
        capture_order=capture_order,
        firmware_version=firmware_version,
        hardware_revision=hardware_revision,
        profile=ProfilePlan(
            width=width,
            height=height,
            nominal_fps=FIXTURE_NOMINAL_FPS,
            jpeg_quality=FIXTURE_JPEG_QUALITY,
        ),
        clock=clock,
        start_boot_us=1_000_000,
        frames=_frames(name, times),
        duration_us=duration_us if duration_us is not None else times[-1] + NOMINAL_FRAME_PERIOD_US,
        close_reason=close_reason,
        recovered=recovered,
        dropped_frames=dropped_frames,
    )


@dataclass(frozen=True)
class MediaFixture:
    """One committed segment vector: a finalized clip directory or an active segment."""

    id: str
    kind: str  # "clip" | "active"
    category: str
    plan: ClipPlan
    invariant: str
    expected: str = "valid"  # "valid" | "invalid"
    codes: tuple[str, ...] = ()
    corruption: str | None = None
    checksums: bool = True

    @property
    def dir_path(self) -> str:
        return self.id


@dataclass(frozen=True)
class ApiFixture:
    """One committed API vector of one operation, request or response side."""

    id: str
    contract: str
    category: str
    operation: str
    direction: str  # "request" | "response"
    invariant: str
    expected: str = "valid"
    codes: tuple[str, ...] = ()
    status: int | None = None
    schema: str | None = None
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    api_error_code: str | None = None

    @property
    def body_file(self) -> str | None:
        if self.body is None:
            return None
        return f"{self.id}.json"

    @property
    def headers_file(self) -> str | None:
        if self.headers is None:
            return None
        return f"{self.id}.headers.json"

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(path for path in (self.body_file, self.headers_file) if path is not None)


# ---------------------------------------------------------------------------
# Media vectors (AC-02 valid coverage, AC-03 invalid coverage)
# ---------------------------------------------------------------------------

SNTP_CLOCK: Final = ClockPlan("sntp", "2026-03-04T11:02:03.250Z", 120)
PHONE_CLOCK: Final = ClockPlan("phone", "2026-06-01T08:30:00.000Z", 250)
PHONE_CLOCK_CHANGED: Final = ClockPlan("phone", "2026-06-01T09:15:00.500Z", 900)

VALID_BASELINE_TIMES: Final[tuple[int, ...]] = (0, 66_667, 133_333, 200_000)
SHORT_TIMES: Final[tuple[int, ...]] = (0, 66_667, 133_333)
TWO_FRAME_TIMES: Final[tuple[int, ...]] = (0, 66_667)


def _valid_media() -> tuple[MediaFixture, ...]:
    return (
        MediaFixture(
            id="media/valid/baseline",
            kind="clip",
            category="baseline",
            plan=_plan("baseline", VALID_BASELINE_TIMES, clock=SNTP_CLOCK, capture_order=42),
            invariant=(
                "AC-02 baseline: four retained frames, consecutive seq, contiguous offsets, "
                "strictly increasing t_us from zero, real CRC-32 and SHA-256, known SNTP clock, "
                "duration one nominal frame period past the last t_us"
            ),
        ),
        MediaFixture(
            id="media/valid/gap-long-jump",
            kind="clip",
            category="time",
            plan=_plan("gap-long-jump", (0, 250_000, 45_000_000), capture_order=43),
            invariant=(
                "AC-02 capture gap: a 44.75 s jump is expressed by timestamps only, with no "
                "invented filler records, and duration still exceeds the final t_us"
            ),
        ),
        MediaFixture(
            id="media/valid/clock-unknown",
            kind="clip",
            category="clock",
            plan=_plan("clock-unknown", SHORT_TIMES, capture_order=44),
            invariant=(
                "AC-02 unknown UTC: clock.source unknown with start_utc and uncertainty_ms both "
                "null, and a card-local capture_order that still orders eviction"
            ),
        ),
        MediaFixture(
            id="media/valid/clock-phone",
            kind="clip",
            category="clock",
            plan=_plan("clock-phone", SHORT_TIMES, clock=PHONE_CLOCK, close_reason="settings", capture_order=45),
            invariant=(
                "AC-02 known clock: phone-derived UTC with millisecond precision and trailing Z "
                "plus a nonnegative uncertainty_ms, closed early for a settings change"
            ),
        ),
        MediaFixture(
            id="media/valid/early-close-size",
            kind="clip",
            category="close-reason",
            plan=_plan("early-close-size", SHORT_TIMES, close_reason="size", capture_order=46, duration_us=180_000),
            invariant=(
                "AC-02 early close: split before the payload bound with close_reason size and a "
                "measured segment close time"
            ),
        ),
        MediaFixture(
            id="media/valid/recovered-prefix",
            kind="clip",
            category="recovery",
            plan=_plan(
                "recovered-prefix",
                TWO_FRAME_TIMES,
                close_reason="recovery",
                recovered=True,
                capture_order=47,
                duration_us=133_334,
            ),
            invariant=(
                "AC-02 recovered prefix: maximal validated prefix republished as a recovered "
                "manifest, so recovered true pairs with close_reason recovery and duration is "
                "last frame time plus one nominal frame period"
            ),
        ),
        MediaFixture(
            id="media/valid/close-reason-clock-change",
            kind="clip",
            category="close-reason",
            plan=_plan(
                "close-reason-clock-change",
                SHORT_TIMES,
                close_reason="clock_change",
                clock=PHONE_CLOCK_CHANGED,
                capture_order=48,
            ),
            invariant="Close cause clock_change: the segment closed before the UTC mapping changed",
        ),
        MediaFixture(
            id="media/valid/close-reason-shutdown",
            kind="clip",
            category="close-reason",
            plan=_plan("close-reason-shutdown", SHORT_TIMES, close_reason="shutdown", capture_order=49),
            invariant="Close cause shutdown: a clean stop checkpointed the active segment",
        ),
        MediaFixture(
            id="media/valid/close-reason-storage-fault",
            kind="clip",
            category="close-reason",
            plan=_plan(
                "close-reason-storage-fault",
                SHORT_TIMES,
                close_reason="storage_fault",
                capture_order=50,
                dropped_frames=3,
            ),
            invariant=(
                "Close cause storage_fault with observed acquisition drops counted in "
                "dropped_frames (unknown losses across reset stay uncounted)"
            ),
        ),
        MediaFixture(
            id="media/valid/close-reason-ota",
            kind="clip",
            category="close-reason",
            plan=_plan("close-reason-ota", SHORT_TIMES, close_reason="ota", capture_order=51),
            invariant="Close cause ota: the active segment closed and synced before staging",
        ),
        MediaFixture(
            id="media/valid/active-unknown-clock",
            kind="active",
            category="active-record",
            plan=_plan("active-unknown-clock", TWO_FRAME_TIMES, capture_order=52),
            checksums=False,
            invariant=(
                "AC-02 active vector: active.json published before the first payload append with "
                "the manifest field rules, payload and index carrying .part names and no manifest"
            ),
        ),
    )


@dataclass(frozen=True)
class _Negative:
    """One AC-03 negative media vector, described once."""

    id: str
    category: str
    corruption: str
    codes: tuple[str, ...]
    invariant: str
    kind: str = "clip"
    checksums: bool = False


_NEGATIVE_MEDIA: Final[tuple[_Negative, ...]] = (
    _Negative(
        id="media/invalid/frame-crc-mismatch",
        category="crc",
        corruption="frame_crc_flip",
        codes=(FRAME_CRC_MISMATCH,),
        invariant="AC-03 bad CRC: the declared CRC-32 disagrees with the exact payload bytes",
    ),
    _Negative(
        id="media/invalid/payload-truncated",
        category="payload",
        corruption="payload_tail_cut",
        codes=(FRAME_CRC_MISMATCH, JPEG_EOI_MISSING),
        invariant=(
            "AC-03 truncated payload: the final JPEG loses its tail, so the retained slice fails "
            "both its CRC and its EOI marker"
        ),
    ),
    _Negative(
        id="media/invalid/index-final-line-incomplete",
        category="index",
        corruption="index_tail_cut",
        codes=(INDEX_TRUNCATED,),
        invariant=(
            "AC-03 truncated index at the valid-prefix boundary: the final line lost its "
            "terminator, so recovery keeps the maximal validated prefix only"
        ),
    ),
    _Negative(
        id="media/invalid/index-malformed-midline",
        category="index",
        corruption="index_line_malformed",
        codes=(FRAME_LINE_MALFORMED,),
        invariant=(
            "AC-03 truncated index at a non-final line: a malformed middle line stops validation "
            "even though a later complete line exists"
        ),
    ),
    _Negative(
        id="media/invalid/seq-nonconsecutive",
        category="index",
        corruption="seq_skip",
        codes=(FRAME_SEQ_NOT_CONSECUTIVE,),
        invariant="AC-03 nonconsecutive seq: seq jumps 1 to 3, which recovery would truncate",
    ),
    _Negative(
        id="media/invalid/t-us-decreasing",
        category="time",
        corruption="t_us_backwards",
        codes=(FRAME_T_US_NOT_INCREASING,),
        invariant="AC-03 nonmonotonic capture time: a later frame carries a smaller t_us",
    ),
    _Negative(
        id="media/invalid/t-us-duplicate",
        category="time",
        corruption="t_us_duplicate",
        codes=(FRAME_T_US_DUPLICATE,),
        invariant=(
            "AC-03 duplicate capture time: a hardware timestamp tie must drop the frame and count "
            "the drop instead of falsifying time"
        ),
    ),
    _Negative(
        id="media/invalid/t-us-first-nonzero",
        category="time",
        corruption="t_us_first_nonzero",
        codes=(FRAME_T_US_FIRST_NOT_ZERO,),
        invariant="AC-03 first t_us must be zero: the segment-relative baseline is broken",
    ),
    _Negative(
        id="media/invalid/duration-le-final-t-us",
        category="time",
        corruption="duration_le_final_t",
        codes=(DURATION_LE_FINAL_T_US,),
        invariant="AC-03 duration_us equals the final t_us, so the exclusive media end is wrong",
    ),
    _Negative(
        id="media/invalid/duration-too-long",
        category="time",
        corruption="duration_too_long",
        codes=(DURATION_TOO_LONG,),
        invariant="AC-03 duration_us exceeds the 120,000,000 us hard segment maximum",
    ),
    _Negative(
        id="media/invalid/frame-size-zero",
        category="boundary",
        corruption="frame_size_zero",
        codes=(FRAME_SIZE_INVALID,),
        invariant="AC-03 frame size 0: below the 1-byte payload floor",
    ),
    _Negative(
        id="media/invalid/frame-size-too-large",
        category="boundary",
        corruption="frame_size_too_large",
        codes=(FRAME_SIZE_INVALID,),
        invariant=f"AC-03 frame size {MAX_FRAME_BYTES + 1}: above the 2,097,152-byte ceiling",
    ),
    _Negative(
        id="media/invalid/index-line-too-long",
        category="boundary",
        corruption="index_line_too_long",
        codes=(FRAME_LINE_TOO_LONG,),
        invariant="AC-03 index line above 512 bytes including its newline",
    ),
    _Negative(
        id="media/invalid/dimensions-oversized",
        category="dimensions",
        corruption="dimensions_oversized",
        codes=(DIMENSIONS_EXCEEDED,),
        invariant="AC-03 oversized dimension: profile width 1601 exceeds the 1600 bound",
    ),
    _Negative(
        id="media/invalid/sof-dimension-mismatch",
        category="dimensions",
        corruption="sof_dimension_mismatch",
        codes=(JPEG_SOF_DIMENSION_MISMATCH,),
        invariant="AC-03 JPEG SOF width 64 disagrees with the manifest profile width 48",
    ),
    _Negative(
        id="media/invalid/id-syntax-invalid",
        category="id",
        corruption="id_syntax_invalid",
        codes=(ID_SYNTAX_INVALID,),
        invariant="AC-03 invalid ID syntax: an uppercase device_id is not 32 lowercase hex",
    ),
    _Negative(
        id="media/invalid/clip-boot-prefix-mismatch",
        category="id",
        corruption="clip_boot_prefix_mismatch",
        codes=(CLIP_BOOT_PREFIX_MISMATCH,),
        invariant="AC-03 clip_id boot prefix differs from boot_id (both individually well formed)",
    ),
    _Negative(
        id="media/invalid/unsupported-version",
        category="version",
        corruption="unsupported_version",
        codes=(VERSION_UNSUPPORTED,),
        invariant="AC-03 unsupported version: v 2 must be rejected, not partially honoured",
    ),
    _Negative(
        id="media/invalid/manifest-too-large",
        category="boundary",
        corruption="manifest_too_large",
        codes=(MANIFEST_TOO_LARGE,),
        invariant=f"AC-03 manifest above the {MAX_MANIFEST_BYTES}-byte bound is refused before parsing",
    ),
    _Negative(
        id="media/invalid/close-reason-unknown",
        category="close-reason",
        corruption="close_reason_unknown",
        codes=(CLOSE_REASON_UNKNOWN,),
        invariant="AC-03 unknown close_reason value outside the eight documented causes",
    ),
    _Negative(
        id="media/invalid/recovered-close-reason-disagree",
        category="recovery",
        corruption="recovered_disagrees",
        codes=(RECOVERED_CLOSE_REASON_DISAGREE,),
        invariant=(
            "AC-03 recovered true with close_reason duration: a recovered segment always uses "
            "recovery, and only recovery implies recovered"
        ),
    ),
    _Negative(
        id="media/invalid/offset-beyond-payload-end",
        category="boundary",
        corruption="offset_beyond_payload",
        codes=(OFFSET_EXCEEDS_PAYLOAD,),
        invariant="AC-03 offset+size of the final record runs past the end of the payload",
    ),
    _Negative(
        id="media/invalid/offset-arithmetic-overflow",
        category="overflow",
        corruption="offset_arithmetic_overflow",
        codes=(OFFSET_ARITHMETIC_OVERFLOW,),
        invariant=(
            f"AC-03 boundary arithmetic: offset {UINT53_MAX} plus a nonzero size overflows the "
            "2^53-1 JSON integer range and must be refused before any read or allocation"
        ),
    ),
    _Negative(
        id="media/invalid/manifest-hash-mismatch",
        category="hash",
        corruption="manifest_hash_mismatch",
        codes=(MANIFEST_HASH_MISMATCH,),
        invariant="AC-03/AC-06 hash: the manifest declares a SHA-256 the file bytes do not have",
    ),
    _Negative(
        id="media/invalid/checksum-hash-mismatch",
        category="hash",
        corruption="checksum_hash_mismatch",
        checksums=True,
        codes=(CHECKSUM_HASH_MISMATCH,),
        invariant="AC-06 hash: the committed checksums.json disagrees with the committed bytes",
    ),
    _Negative(
        id="media/invalid/checksum-size-mismatch",
        category="hash",
        corruption="checksum_size_mismatch",
        checksums=True,
        codes=(CHECKSUM_SIZE_MISMATCH,),
        invariant="AC-06 hash: checksums.json records the wrong byte count for the payload",
    ),
    _Negative(
        id="media/invalid/index-with-bom",
        category="encoding",
        corruption="index_bom",
        codes=(INDEX_ENCODING_INVALID,),
        invariant="AC-03/AC-06 encoding: a UTF-8 BOM before the first index line is not LF-only JSONL",
    ),
    _Negative(
        id="media/invalid/index-with-blank-line",
        category="encoding",
        corruption="index_blank_line",
        codes=(INDEX_ENCODING_INVALID,),
        invariant="AC-03/AC-06 encoding: a blank line inside the index is forbidden",
    ),
    _Negative(
        id="media/invalid/index-with-crlf",
        category="encoding",
        corruption="index_crlf",
        codes=(INDEX_ENCODING_INVALID,),
        invariant="AC-06 encoding: CR LF line endings are not the LF-only index format",
    ),
    _Negative(
        id="media/invalid/clock-nullity-mismatch",
        category="clock",
        corruption="clock_nullity",
        codes=(CLOCK_NULLITY_MISMATCH,),
        invariant=(
            "AC-06 time: clock.source unknown while start_utc carries a timestamp, so the null "
            "pairing that keeps unknown UTC unknown is broken"
        ),
    ),
    _Negative(
        id="media/invalid/frame-unsupported-version",
        category="version",
        corruption="frame_version",
        codes=(VERSION_UNSUPPORTED,),
        invariant=(
            "AC-03 version: an index line whose v is not 1 is not a v1 record, even when every "
            "other byte of the segment still agrees"
        ),
    ),
    _Negative(
        id="media/invalid/nominal-fps-too-high",
        category="profile",
        corruption="nominal_fps_high",
        codes=(NOMINAL_FPS_INVALID,),
        invariant="AC-03 profile: nominal_fps is bounded at 30 frames per second by the profile table",
    ),
    _Negative(
        id="media/invalid/nominal-fps-zero",
        category="profile",
        corruption="nominal_fps_zero",
        codes=(NOMINAL_FPS_INVALID,),
        invariant="AC-03 profile: a zero nominal rate makes every duration arithmetic meaningless",
    ),
    _Negative(
        id="media/invalid/active-profile-oversized",
        kind="active",
        category="profile",
        corruption="active_profile_oversized",
        codes=(DIMENSIONS_EXCEEDED,),
        invariant=(
            "AC-02 active record: an interrupted segment reuses the manifest field rules, so its "
            "profile is bounded at 1600 px too"
        ),
    ),
    _Negative(
        id="media/invalid/manifest-bad-type",
        category="manifest",
        corruption="manifest_bad_type",
        codes=(MANIFEST_SCHEMA,),
        invariant="AC-03 manifest schema: dropped_frames is a count, never free text",
    ),
    _Negative(
        id="media/invalid/manifest-missing-field",
        category="manifest",
        corruption="manifest_missing_field",
        codes=(MANIFEST_SCHEMA_MISSING_FIELD,),
        invariant="AC-03 manifest schema: firmware_version is required so the build is attributable",
    ),
    _Negative(
        id="media/invalid/manifest-size-mismatch",
        category="hash",
        corruption="manifest_size_mismatch",
        codes=(MANIFEST_SIZE_MISMATCH,),
        invariant="AC-06 hash: the manifest declares an index length the file does not have",
    ),
    _Negative(
        id="media/invalid/frame-count-mismatch",
        category="manifest",
        corruption="frame_count_mismatch",
        codes=(FRAME_COUNT_MISMATCH,),
        invariant=(
            "AC-03 manifest: frame_count counts the index records, so a clip that promises one "
            "more frame than it wrote is refused"
        ),
    ),
    _Negative(
        id="media/invalid/manifest-not-json",
        category="manifest",
        corruption="manifest_not_json",
        codes=(MANIFEST_JSON_INVALID,),
        invariant="AC-03 manifest: a completion record that is not JSON cannot close a clip",
    ),
    _Negative(
        id="media/invalid/manifest-absent",
        category="manifest",
        corruption="manifest_absent",
        codes=(MANIFEST_MISSING,),
        invariant="AC-03 manifest: a directory without manifest.json is not a finalized clip",
    ),
    _Negative(
        id="media/invalid/frame-unknown-property",
        category="index",
        corruption="frame_unknown_property",
        codes=(FRAME_SCHEMA,),
        invariant="AC-03 index schema: the write side rejects unknown frame-record fields",
    ),
    _Negative(
        id="media/invalid/frame-missing-field",
        category="index",
        corruption="frame_missing_field",
        codes=(FRAME_SCHEMA_MISSING_FIELD,),
        invariant="AC-03 index schema: a record without crc32 cannot be verified at all",
    ),
    _Negative(
        id="media/invalid/frame-line-not-object",
        category="index",
        corruption="frame_line_not_object",
        codes=(FRAME_LINE_NOT_OBJECT,),
        invariant="AC-03 index: every line is one JSON object, never an array or scalar",
    ),
    _Negative(
        id="media/invalid/frame-t-us-too-large",
        category="boundary",
        corruption="frame_t_us_too_large",
        codes=(FRAME_T_US_TOO_LARGE,),
        invariant="AC-03 boundary: a frame timestamp beyond 120,000,000 us exceeds the segment bound",
    ),
    _Negative(
        id="media/invalid/offset-not-contiguous",
        category="index",
        corruption="offset_not_contiguous",
        codes=(OFFSET_NOT_CONTIGUOUS,),
        invariant="AC-03 offset continuity: the record offset must equal prev.offset + prev.size",
    ),
    _Negative(
        id="media/invalid/payload-trailing-bytes",
        category="payload",
        corruption="payload_trailing",
        codes=(PAYLOAD_TRAILING_BYTES,),
        invariant="AC-03 payload: bytes after the final record are unreachable and refuse the clip",
    ),
    _Negative(
        id="media/invalid/index-empty",
        category="index",
        corruption="index_empty",
        codes=(INDEX_EMPTY, MANIFEST_SCHEMA),
        invariant=(
            "AC-03 index: a clip with no index record describes no frames, and the manifest cannot "
            "declare a zero-length file either"
        ),
    ),
    _Negative(
        id="media/invalid/clock-source-unknown",
        category="clock",
        corruption="clock_source_unknown",
        codes=(CLOCK_SOURCE_UNKNOWN_VALUE,),
        invariant="AC-06 time: clock.source is unknown|phone|sntp; a made-up source is refused",
    ),
    _Negative(
        id="media/invalid/clock-timestamp-invalid",
        category="clock",
        corruption="clock_timestamp_invalid",
        codes=(CLOCK_TIMESTAMP_INVALID,),
        invariant="AC-06 time: start_utc is RFC3339 UTC with millisecond precision and trailing Z",
    ),
    _Negative(
        id="media/invalid/jpeg-soi-missing",
        category="jpeg",
        corruption="jpeg_soi_missing",
        codes=(FRAME_CRC_MISMATCH, JPEG_SOI_MISSING),
        invariant=(
            "AC-03 JPEG: a payload slice that does not open with SOI is not a frame, and its "
            "recorded CRC no longer describes these bytes either"
        ),
    ),
    _Negative(
        id="media/invalid/jpeg-decode-failed",
        category="jpeg",
        corruption="jpeg_entropy_garbage",
        codes=(FRAME_CRC_MISMATCH, JPEG_DECODE_FAILED),
        invariant=(
            "AC-03 JPEG: markers alone are not a frame, so entropy data a decoder rejects is "
            "refused even though the slice still ends with EOI"
        ),
    ),
    _Negative(
        id="media/invalid/checksums-missing-entry",
        category="hash",
        corruption="checksums_missing_entry",
        checksums=True,
        codes=(CHECKSUMS_SCHEMA,),
        invariant="AC-06 hash: checksums.json must describe every file the clip ships",
    ),
    _Negative(
        id="media/invalid/duration-too-long-decimal",
        category="time",
        corruption="duration_too_long_decimal",
        codes=(DURATION_TOO_LONG,),
        invariant=(
            "AC-03 duration_us 120000001.0: a JSON integer may be written with a fraction "
            "part, and the 120,000,000 us maximum still has to reach it"
        ),
    ),
    _Negative(
        id="media/invalid/duration-too-long-exponent",
        category="time",
        corruption="duration_too_long_exponent",
        codes=(DURATION_TOO_LONG,),
        invariant=(
            "AC-03 duration_us 1.20000001e8: exponent notation is a JSON integer too, so "
            "the segment maximum cannot be skipped by how the number is spelled"
        ),
    ),
    _Negative(
        id="media/invalid/dimensions-oversized-decimal",
        category="dimensions",
        corruption="dimensions_oversized_decimal",
        codes=(DIMENSIONS_EXCEEDED,),
        invariant=(
            "AC-03 oversized dimension written as 1601.0: the 1600 px profile bound applies "
            "to any integral JSON number, not only to one written without a fraction part"
        ),
    ),
    _Negative(
        id="media/invalid/nominal-fps-high-decimal",
        category="profile",
        corruption="nominal_fps_high_decimal",
        codes=(NOMINAL_FPS_INVALID,),
        invariant=(
            "AC-03 profile: nominal_fps 31.0 is above the 30 frames-per-second bound even "
            "though its notation is not the plain integer form the writer uses"
        ),
    ),
    _Negative(
        id="media/invalid/index-declared-oversize",
        category="boundary",
        corruption="index_declared_oversize",
        codes=(MANIFEST_SCHEMA, MANIFEST_SIZE_MISMATCH),
        invariant=(
            "AC-03 boundary: files[frames.jsonl].bytes above the 1,843,200-byte index "
            "maximum is refused by the schema and disagrees with the committed bytes, so "
            "the index does not inherit the payload file's 268,435,456-byte ceiling"
        ),
    ),
    _Negative(
        id="media/invalid/clock-timestamp-impossible-date",
        category="clock",
        corruption="clock_timestamp_impossible_date",
        codes=(CLOCK_TIMESTAMP_INVALID,),
        invariant=(
            "AC-06 time: 2026-02-30 has the documented RFC3339 shape but no such day exists, "
            "so the calendar is checked and not only the pattern"
        ),
    ),
    _Negative(
        id="media/invalid/active-bad-type",
        kind="active",
        category="active-record",
        corruption="active_bad_type",
        codes=(ACTIVE_SCHEMA,),
        invariant="AC-03 active record: start_boot_us is an integer boot offset, not text",
    ),
    _Negative(
        id="media/invalid/active-not-json",
        kind="active",
        category="active-record",
        corruption="active_not_json",
        codes=(ACTIVE_JSON_INVALID,),
        invariant="AC-03 active record: a record that is not JSON cannot name an in-progress segment",
    ),
    _Negative(
        id="media/invalid/active-too-large",
        kind="active",
        category="boundary",
        corruption="active_too_large",
        codes=(ACTIVE_TOO_LARGE,),
        invariant="AC-03 boundary: active.json is bounded at 16,384 bytes like the manifest",
    ),
    _Negative(
        id="media/invalid/active-with-manifest",
        kind="active",
        category="active-record",
        corruption="active_with_manifest",
        codes=(ACTIVE_WITH_MANIFEST,),
        invariant=(
            "AC-02 active record: an interrupted segment publishes active.json only, because a "
            "completion manifest here would claim a close that never happened"
        ),
    ),
)


def media_fixtures() -> tuple[MediaFixture, ...]:
    """Every committed media vector, valid first then negative."""
    valid = _valid_media()
    negatives = tuple(
        MediaFixture(
            id=item.id,
            kind=item.kind,
            category=item.category,
            plan=_plan("baseline", VALID_BASELINE_TIMES, clock=SNTP_CLOCK, capture_order=42),
            invariant=item.invariant,
            expected="invalid",
            codes=item.codes,
            corruption=item.corruption,
            checksums=item.checksums,
        )
        for item in _NEGATIVE_MEDIA
    )
    return valid + negatives


def baseline_plan() -> ClipPlan:
    """The baseline segment other vectors bind against (hashes, ids, ranges)."""
    return _plan("baseline", VALID_BASELINE_TIMES, clock=SNTP_CLOCK, capture_order=42)


# ---------------------------------------------------------------------------
# API vectors (AC-04 device, AC-05 backend)
# ---------------------------------------------------------------------------


@dataclass
class _ApiList:
    """Accumulator with the invariant bookkeeping kept next to each vector."""

    items: list[ApiFixture] = field(default_factory=list)

    def add(
        self,
        *,
        id: str,
        contract: str,
        category: str,
        operation: str,
        direction: str,
        invariant: str,
        expected: str = "valid",
        codes: tuple[str, ...] = (),
        status: int | None = None,
        schema: str | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        api_error_code: str | None = None,
    ) -> None:
        if operation not in ALL_OPERATIONS:
            raise KeyError(f"undeclared operation {operation}")
        self.items.append(
            ApiFixture(
                id=f"{contract}/{'valid' if expected == 'valid' else 'invalid'}/{id}",
                contract=contract,
                category=category,
                operation=operation,
                direction=direction,
                invariant=invariant,
                expected=expected,
                codes=codes,
                status=status,
                schema=schema,
                body=body,
                headers=headers,
                api_error_code=api_error_code,
            )
        )


def _error_body(code: str, message: str, *, retryable: bool, request_id: str) -> dict[str, Any]:
    """One exact error envelope in the shape interfaces.md §1 shows."""
    return {
        "v": API_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        },
    }


def device_fixtures(media: "MediaCorpus") -> tuple[ApiFixture, ...]:
    """Device-contract vectors: AC-04 coverage of pairing through events."""
    out = _ApiList()
    op = "device.pair"
    out.add(
        id="pair-request",
        contract="device",
        category="auth",
        operation=op,
        direction="request",
        schema="PairRequest",
        body={"v": API_VERSION, "setup_secret": _token("setup-secret-1"), "client_name": "Owner phone"},
        invariant="POST /pair request with the QR setup secret (32-byte unpadded base64url)",
    )
    out.add(
        id="pair-response-201",
        contract="device",
        category="auth",
        operation=op,
        direction="response",
        status=201,
        schema="PairResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "token_id": "tok-owner-1",
            "access_token": _token("access-token-1"),
        },
        invariant="AC-04 pair success: 201 with the single owner token returned once",
    )
    out.add(
        id="pair-response-409-already-owned",
        contract="device",
        category="auth",
        operation=op,
        direction="response",
        status=409,
        api_error_code="ALREADY_OWNED",
        body=_error_body("ALREADY_OWNED", "Device already has an owner", retryable=False, request_id="req-7a1"),
        invariant="AC-04 pair while owned: 409 ALREADY_OWNED even inside an open physical window",
    )
    out.add(
        id="pair-response-400-bad-secret",
        contract="device",
        category="auth",
        operation=op,
        direction="response",
        status=400,
        api_error_code="MALFORMED_REQUEST",
        body=_error_body(
            "MALFORMED_REQUEST", "Setup secret rejected", retryable=False, request_id="req-7a2"
        ),
        invariant="AC-04 pair with a rejected setup secret: 400 malformed, rate limited to 5/minute",
    )
    out.add(
        id="pair-request-missing-version",
        contract="device",
        category="version",
        operation=op,
        direction="request",
        schema="PairRequest",
        body={"setup_secret": _token("setup-secret-1"), "client_name": "Owner phone"},
        expected="invalid",
        codes=(API_VERSION_MISSING,),
        invariant="AC-06 version: a control request without top-level v:1 is refused",
    )
    out.add(
        id="pair-request-padded-secret",
        contract="device",
        category="auth",
        operation=op,
        direction="request",
        schema="PairRequest",
        body={"v": API_VERSION, "setup_secret": _token("setup-secret-1") + "==", "client_name": "Owner phone"},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04/AC-06 auth: base64url padding is not the documented unpadded credential form",
    )
    out.add(
        id="pair-response-unsupported-version",
        contract="device",
        category="version",
        operation=op,
        direction="response",
        status=201,
        schema="PairResponse",
        body={
            "v": API_VERSION + 1,
            "device_id": DEVICE_ID,
            "token_id": "tok-owner-1",
            "access_token": _token("access-token-1"),
        },
        expected="invalid",
        codes=(API_VERSION_UNSUPPORTED,),
        invariant="AC-06 version: an unknown major version fails rather than being partly honoured",
    )

    op = "device.revoke_token"
    out.add(
        id="tokens-revoke-request",
        contract="device",
        category="auth",
        operation=op,
        direction="request",
        schema="RevokeTokenRequest",
        body={"v": API_VERSION, "token_id": "tok-owner-1"},
        invariant="POST /tokens/revoke request: the owner revokes its own token",
    )
    out.add(
        id="tokens-revoke-response-200",
        contract="device",
        category="auth",
        operation=op,
        direction="response",
        status=200,
        schema="RevokeTokenResponse",
        body={"v": API_VERSION, "revoked": True},
        invariant="POST /tokens/revoke success; ownership stays locked after the last revoke",
    )
    out.add(
        id="tokens-revoke-request-missing-token",
        contract="device",
        category="auth",
        operation=op,
        direction="request",
        schema="RevokeTokenRequest",
        body={"v": API_VERSION},
        expected="invalid",
        codes=(API_SCHEMA_MISSING_FIELD,),
        invariant="AC-04 revoke without token_id is a malformed write",
    )

    op = "device.get_capabilities"
    out.add(
        id="capabilities-response-200",
        contract="device",
        category="status",
        operation=op,
        direction="response",
        status=200,
        schema="CapabilitiesResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "firmware_version": "0.1.0",
            "hardware_revision": "xiao-esp32s3-sense-proto-a",
            "media_versions": [1],
            "features": ["record", "clips", "leases", "preview", "events"],
            "limits": {
                "inactive_slot_max_image_bytes": 3_145_728,
                "max_concurrent_downloading_clients": DEVICE_MAX_DOWNLOADING_CLIENTS,
                "max_clip_leases": DEVICE_MAX_CLIP_LEASES,
                "default_lease_s": DEVICE_LEASE_DEFAULT_S,
                "max_download_range_bytes": MAX_CHUNK_BYTES,
                "protected_max_bytes": MAX_PROTECTED_BYTES,
                "protected_ceiling_bytes": MAX_PROTECTED_BYTES,
                "max_index_line_bytes": MAX_INDEX_LINE_BYTES,
                "max_manifest_bytes": MAX_MANIFEST_BYTES,
            },
        },
        invariant=(
            "AC-04 capabilities: implemented features only, media_versions [1], applied limits and "
            "the protection ceiling discoverable"
        ),
    )
    out.add(
        id="capabilities-response-missing-limits",
        contract="device",
        category="status",
        operation=op,
        direction="response",
        status=200,
        schema="CapabilitiesResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "firmware_version": "0.1.0",
            "hardware_revision": "xiao-esp32s3-sense-proto-a",
            "media_versions": [1],
            "features": ["record"],
        },
        expected="invalid",
        codes=(API_SCHEMA_MISSING_FIELD,),
        invariant="AC-04 capabilities without limits omits the applied resource limits it must report",
    )

    states = (
        ("booting", None),
        ("recovering", "RECOVERY_REQUIRED"),
        ("recording", None),
        ("storage_fault", "NO_CARD"),
        ("camera_fault", "CAMERA_INIT"),
        ("storage_full", "NO_EVICTABLE_SPACE"),
        ("updating", None),
        ("shutting_down", None),
    )
    for state, fault in states:
        recording_active = state == "recording"
        out.add(
            id=f"status-response-200-{state}",
            contract="device",
            category="status",
            operation="device.get_status",
            direction="response",
            status=200,
            schema="StatusResponse",
            body={
                "v": API_VERSION,
                "device_id": DEVICE_ID,
                "boot_id": boot_id(f"status-{state}"),
                "state": state,
                "fault_code": fault,
                "uptime_ms": 42_000,
                "recording": {
                    "clip_id": media.baseline_clip_id if recording_active else None,
                    "frames": 240 if recording_active else 0,
                    "dropped_frames": 0,
                },
                "storage": {
                    "mounted": True,
                    "total_bytes": 29_157_488_640,
                    "free_bytes": 21_474_836_480,
                    "rolling_bytes": 1_073_741_824,
                    "protected_bytes": 536_870_912,
                    "retained_duration_s": 10_080,
                },
                "power": {"battery_mv": 3_980, "external_power": False},
                "network": {"mode": "off", "connected": False},
                "settings_revision": 4,
            },
            invariant=(
                f"AC-04 status state {state}" + (f" with fault_code {fault}" if fault else " with no fault")
            ),
        )
    out.add(
        id="status-response-200-unmounted",
        contract="device",
        category="status",
        operation="device.get_status",
        direction="response",
        status=200,
        schema="StatusResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "boot_id": boot_id("status-unmounted"),
            "state": "storage_fault",
            "fault_code": "NO_CARD",
            "uptime_ms": 5_000,
            "recording": {"clip_id": None, "frames": 0, "dropped_frames": 0},
            "storage": {
                "mounted": False,
                "total_bytes": None,
                "free_bytes": None,
                "rolling_bytes": None,
                "protected_bytes": None,
                "retained_duration_s": None,
            },
            "power": {"battery_mv": None, "external_power": None},
            "network": {"mode": "off", "connected": False},
            "settings_revision": 0,
        },
        invariant=(
            "AC-04 unmounted storage: every total is null (zero means measured zero), and "
            "battery_mv/external_power are null when not measurable"
        ),
    )
    out.add(
        id="status-response-200-bad-state",
        contract="device",
        category="status",
        operation="device.get_status",
        direction="response",
        status=200,
        schema="StatusResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "boot_id": boot_id("status-bad-state"),
            "state": "paused",
            "fault_code": None,
            "uptime_ms": 1_000,
            "recording": {"clip_id": None, "frames": 0, "dropped_frames": 0},
            "storage": {
                "mounted": True,
                "total_bytes": 1,
                "free_bytes": 1,
                "rolling_bytes": 0,
                "protected_bytes": 0,
                "retained_duration_s": 0,
            },
            "power": {"battery_mv": 3_900, "external_power": True},
            "network": {"mode": "off", "connected": False},
            "settings_revision": 0,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 status: `paused` is not one of the eight documented states",
    )
    out.add(
        id="status-response-200-bad-clip-id",
        contract="device",
        category="id",
        operation="device.get_status",
        direction="response",
        status=200,
        schema="StatusResponse",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "boot_id": boot_id("status-bad-clip"),
            "state": "recording",
            "fault_code": None,
            "uptime_ms": 1_000,
            "recording": {"clip_id": "../../etc/passwd", "frames": 1, "dropped_frames": 0},
            "storage": {
                "mounted": True,
                "total_bytes": 1,
                "free_bytes": 1,
                "rolling_bytes": 0,
                "protected_bytes": 0,
                "retained_duration_s": 0,
            },
            "power": {"battery_mv": 3_900, "external_power": True},
            "network": {"mode": "ap", "connected": True},
            "settings_revision": 0,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant=(
            "AC-03/AC-04 id: a caller-visible clip id that is not <boot_id>-<8 hex> is rejected "
            "before any path lookup"
        ),
    )

    profile = {"width": 640, "height": 480, "nominal_fps": 15, "jpeg_quality": 20}
    out.add(
        id="settings-response-200",
        contract="device",
        category="settings",
        operation="device.get_settings",
        direction="response",
        status=200,
        schema="SettingsResponse",
        body={
            "v": API_VERSION,
            "revision": 4,
            "recording_profile": profile,
            "network": {"mode": "off", "ssid": None},
            "preview_enabled": False,
        },
        invariant="AC-04 GET /settings: revision plus profile, never a password",
    )
    out.add(
        id="settings-put-request",
        contract="device",
        category="settings",
        operation="device.put_settings",
        direction="request",
        schema="PutSettingsRequest",
        body={"v": API_VERSION, "expected_revision": 4, "recording_profile": profile, "preview_enabled": True},
        invariant="AC-04 PUT /settings compare-and-swap with expected_revision",
    )
    out.add(
        id="settings-put-response-200",
        contract="device",
        category="settings",
        operation="device.put_settings",
        direction="response",
        status=200,
        schema="PutSettingsResponse",
        body={"v": API_VERSION, "revision": 5, "effective_from_clip_id": media.other_clip_id},
        invariant="AC-04 settings accepted: new revision plus the segment the change takes effect in",
    )
    out.add(
        id="settings-put-response-409-revision-conflict",
        contract="device",
        category="settings",
        operation="device.put_settings",
        direction="response",
        status=409,
        api_error_code="REVISION_CONFLICT",
        body=_error_body(
            "REVISION_CONFLICT", "Settings revision is stale", retryable=False, request_id="req-8c1"
        ),
        invariant="AC-04 stale write returns 409 REVISION_CONFLICT together with the current revision",
    )
    out.add(
        id="settings-put-response-400-unsupported-profile",
        contract="device",
        category="settings",
        operation="device.put_settings",
        direction="response",
        status=400,
        api_error_code="MALFORMED_REQUEST",
        body=_error_body(
            "MALFORMED_REQUEST", "Recording profile is not qualified", retryable=False, request_id="req-8c2"
        ),
        invariant="AC-04 unsupported recording profile rejected with 400",
    )
    out.add(
        id="settings-put-request-unknown-field",
        contract="device",
        category="settings",
        operation="device.put_settings",
        direction="request",
        schema="PutSettingsRequest",
        body={
            "v": API_VERSION,
            "expected_revision": 4,
            "recording_profile": profile,
            "force_now": True,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 write-side objects reject unknown fields, so no hidden remote-stop exists",
    )
    out.add(
        id="settings-put-request-negative-revision",
        contract="device",
        category="boundary",
        operation="device.put_settings",
        direction="request",
        schema="PutSettingsRequest",
        body={"v": API_VERSION, "expected_revision": -1},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-06 boundary: expected_revision is a nonnegative integer",
    )

    out.add(
        id="time-request-valid",
        contract="device",
        category="time",
        operation="device.post_time",
        direction="request",
        schema="TimeRequest",
        body={"v": API_VERSION, "utc": "2026-07-02T13:45:21.750Z", "uncertainty_ms": 150},
        invariant="AC-04 POST /time with RFC3339 UTC millisecond precision and trailing Z",
    )
    out.add(
        id="time-response-200",
        contract="device",
        category="time",
        operation="device.post_time",
        direction="response",
        status=200,
        schema="TimeResponse",
        body={"v": API_VERSION, "applied": True},
        invariant="AC-04 accepted correction; the active segment closed before the mapping changed",
    )
    out.add(
        id="time-request-missing-milliseconds",
        contract="device",
        category="time",
        operation="device.post_time",
        direction="request",
        schema="TimeRequest",
        body={"v": API_VERSION, "utc": "2026-07-02T13:45:21Z", "uncertainty_ms": 150},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 invalid UTC: second precision is not the documented millisecond form",
    )
    out.add(
        id="time-request-local-offset",
        contract="device",
        category="time",
        operation="device.post_time",
        direction="request",
        schema="TimeRequest",
        body={"v": API_VERSION, "utc": "2026-07-02T15:45:21.750+02:00", "uncertainty_ms": 150},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 invalid UTC: a local offset is not UTC with a trailing Z",
    )
    out.add(
        id="time-request-negative-uncertainty",
        contract="device",
        category="time",
        operation="device.post_time",
        direction="request",
        schema="TimeRequest",
        body={"v": API_VERSION, "utc": "2026-07-02T13:45:21.750Z", "uncertainty_ms": -1},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 negative uncertainty_ms is rejected: an estimate is never negative",
    )

    page = {
        "v": API_VERSION,
        "items": [
            {
                "clip_id": media.baseline_clip_id,
                "start_utc": "2026-03-04T11:02:03.250Z",
                "duration_us": 266_667,
                "frame_count": 4,
                "bytes": media.baseline_payload_bytes + media.baseline_index_bytes,
                "protected": False,
                "recovered": False,
            },
            {
                "clip_id": media.recovered_clip_id,
                "start_utc": None,
                "duration_us": 133_334,
                "frame_count": 2,
                "bytes": media.recovered_payload_bytes + media.recovered_index_bytes,
                "protected": True,
                "recovered": True,
            },
        ],
        "next_cursor": "cur_" + "a" * 32,
    }
    out.add(
        id="clips-page-response-200",
        contract="device",
        category="catalog",
        operation="device.list_clips",
        direction="response",
        status=200,
        schema="ClipsPage",
        body=page,
        invariant=(
            "AC-04 clips page: finalized valid clips only, real committed clip ids, null start_utc "
            "while the clock was unknown, opaque cursor within 256 characters"
        ),
    )
    out.add(
        id="clips-page-response-200-bad-start-utc",
        contract="device",
        category="catalog",
        operation="device.list_clips",
        direction="response",
        status=200,
        schema="ClipsPage",
        body={
            **page,
            "items": [
                {**page["items"][0], "start_utc": "2026-02-30T12:00:00.000Z"},
                page["items"][1],
            ],
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant=(
            "AC-04/AC-06 catalog: a page entry whose start_utc names a date the calendar "
            "does not have is not a conformant summary, shape or no shape"
        ),
    )
    out.add(
        id="clips-page-response-409-cursor-expired",
        contract="device",
        category="pagination",
        operation="device.list_clips",
        direction="response",
        status=409,
        api_error_code="CURSOR_EXPIRED",
        body=_error_body("CURSOR_EXPIRED", "Cursor expired", retryable=False, request_id="req-9d1"),
        invariant="AC-04 expired cursor returns 409 CURSOR_EXPIRED and the listing restarts",
    )
    out.add(
        id="clips-page-request-cursor-too-long",
        contract="device",
        category="pagination",
        operation="device.list_clips",
        direction="request",
        headers={"cursor": "c" * 257},
        expected="invalid",
        codes=(CURSOR_TOO_LONG,),
        invariant="AC-04/AC-06 pagination: a cursor above 256 characters is refused",
    )
    out.add(
        id="clips-page-request-limit-too-large",
        contract="device",
        category="pagination",
        operation="device.list_clips",
        direction="request",
        headers={"limit": str(MAX_PAGE_LIMIT + 1)},
        expected="invalid",
        codes=(PAGE_LIMIT_INVALID,),
        invariant="AC-04/AC-06 pagination: limit above the 100 maximum is refused (default 50)",
    )

    lease_id = "lease-0000000000000000000000000001"
    out.add(
        id="preview-response-200",
        contract="device",
        category="preview",
        operation="device.get_preview",
        direction="response",
        status=200,
        headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"},
        invariant=(
            "AC-04 GET /preview is documented as a multipart MJPEG stream, so it carries no "
            "schema-validated JSON body"
        ),
    )
    out.add(
        id="preview-response-503-unavailable",
        contract="device",
        category="preview",
        operation="device.get_preview",
        direction="response",
        status=503,
        api_error_code="UNAVAILABLE",
        headers={"Retry-After": "5"},
        body=_error_body(
            "UNAVAILABLE", "Preview client slot busy", retryable=True, request_id="req-pv-1"
        ),
        invariant="AC-04 preview may close with 503, and the second client is refused with Retry-After",
    )
    out.add(
        id="preview-response-200-wrong-content-type",
        contract="device",
        category="preview",
        operation="device.get_preview",
        direction="response",
        status=200,
        headers={"Content-Type": "text/plain"},
        expected="invalid",
        codes=(HEADER_INVALID,),
        invariant="AC-04 a preview that answers text/plain is not the documented multipart stream",
    )
    out.add(
        id="clip-manifest-response-200",
        contract="device",
        category="manifest",
        operation="device.get_clip_manifest",
        direction="response",
        status=200,
        schema="Manifest",
        body=media.baseline_manifest,
        invariant=(
            "AC-04/AC-06 GET /clips/{clip_id}/manifest returns the exact immutable committed "
            "manifest.json, so this vector is those bytes"
        ),
    )
    out.add(
        id="clip-manifest-response-410-clip-gone",
        contract="device",
        category="manifest",
        operation="device.get_clip_manifest",
        direction="response",
        status=410,
        api_error_code="CLIP_GONE",
        body=_error_body("CLIP_GONE", "Clip was deleted", retryable=False, request_id="req-mf-1"),
        invariant="AC-04 a known evicted clip is 410 CLIP_GONE on the manifest route too",
    )
    out.add(
        id="clip-manifest-response-200-bad-frame-count",
        contract="device",
        category="manifest",
        operation="device.get_clip_manifest",
        direction="response",
        status=200,
        schema="Manifest",
        body={**media.baseline_manifest, "frame_count": 0},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 a manifest claiming zero frames cannot describe this clip",
    )

    out.add(
        id="clip-manifest-response-200-bad-clock-date",
        contract="device",
        category="manifest",
        operation="device.get_clip_manifest",
        direction="response",
        status=200,
        schema="Manifest",
        body={
            **media.baseline_manifest,
            "clock": {
                **media.baseline_manifest["clock"],
                "start_utc": "2026-02-30T12:00:00.000Z",
            },
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant=(
            "AC-04/AC-06 manifest clock: an impossible calendar date in start_utc is not a "
            "timestamp, even though its shape matches the documented RFC3339 pattern"
        ),
    )

    out.add(
        id="lease-create-request",
        contract="device",
        category="lease",
        operation="device.create_lease",
        direction="request",
        schema="VersionedRequest",
        body={"v": API_VERSION},
        invariant="POST /clips/{clip_id}/leases request body carries only the version",
    )
    out.add(
        id="lease-create-response-201",
        contract="device",
        category="lease",
        operation="device.create_lease",
        direction="response",
        status=201,
        schema="LeaseResponse",
        body={"v": API_VERSION, "lease_id": lease_id, "expires_in_s": DEVICE_LEASE_DEFAULT_S},
        invariant="AC-04 lease granted: 201 with the documented 300 s default",
    )
    out.add(
        id="lease-create-response-409-lease-limit",
        contract="device",
        category="lease",
        operation="device.create_lease",
        direction="response",
        status=409,
        api_error_code="LEASE_LIMIT",
        body=_error_body(
            "LEASE_LIMIT", "Lease quota exhausted", retryable=True, request_id="req-ae1"
        ),
        invariant="AC-04 a third lease is refused with 409 LEASE_LIMIT (two clip leases maximum)",
    )
    out.add(
        id="lease-renew-response-200",
        contract="device",
        category="lease",
        operation="device.renew_lease",
        direction="response",
        status=200,
        schema="LeaseResponse",
        body={"v": API_VERSION, "lease_id": lease_id, "expires_in_s": DEVICE_LEASE_DEFAULT_S},
        invariant="AC-04 renewal returns the same lease id with a fresh 300 s",
    )
    out.add(
        id="lease-renew-response-409-storage-pressure",
        contract="device",
        category="lease",
        operation="device.renew_lease",
        direction="response",
        status=409,
        api_error_code="STORAGE_PRESSURE",
        body=_error_body(
            "STORAGE_PRESSURE", "Renewal denied for free space", retryable=True, request_id="req-ae2"
        ),
        invariant="AC-04 renewal may be denied with 409 STORAGE_PRESSURE to protect recording",
    )
    out.add(
        id="lease-renew-response-409-lease-expired",
        contract="device",
        category="lease",
        operation="device.renew_lease",
        direction="response",
        status=409,
        api_error_code="LEASE_EXPIRED",
        body=_error_body("LEASE_EXPIRED", "Lease expired", retryable=False, request_id="req-ae3"),
        invariant="AC-04 renewing an expired lease returns 409 LEASE_EXPIRED",
    )
    out.add(
        id="lease-delete-204",
        contract="device",
        category="lease",
        operation="device.delete_lease",
        direction="response",
        status=204,
        invariant="AC-04 DELETE /leases/{lease_id} is idempotent with no body",
    )
    out.add(
        id="lease-create-response-bad-expiry",
        contract="device",
        category="lease",
        operation="device.create_lease",
        direction="response",
        status=201,
        schema="LeaseResponse",
        body={"v": API_VERSION, "lease_id": lease_id, "expires_in_s": 0},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 a zero-second lease is refused: expiry must be positive",
    )

    payload_etag = f'"{media.baseline_payload_sha256}"'
    out.add(
        id="clip-file-request-with-lease",
        contract="device",
        category="lease",
        operation="device.get_clip_file",
        direction="request",
        headers={
            "X-Clip-Lease": lease_id,
            "Range": "bytes=0-1023",
        },
        invariant="AC-04 range request requires X-Clip-Lease and one single range only",
    )
    out.add(
        id="clip-file-response-200",
        contract="device",
        category="etag",
        operation="device.get_clip_file",
        direction="response",
        status=200,
        headers={
            "Accept-Ranges": "bytes",
            "ETag": payload_etag,
            "Content-Length": str(media.baseline_payload_bytes),
        },
        invariant=(
            "AC-04 whole-file response: ETag is the quoted SHA-256 of the committed payload, "
            "Accept-Ranges bytes, exact Content-Length"
        ),
    )
    out.add(
        id="clip-file-response-206",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
            "ETag": payload_etag,
            "Content-Length": "1024",
        },
        invariant=(
            "AC-04 single-range response: Content-Range names the granted slice of the real "
            "committed file, ETag unchanged, Content-Length equals the slice"
        ),
    )
    out.add(
        id="clip-file-response-412-content-changed",
        contract="device",
        category="etag",
        operation="device.get_clip_file",
        direction="response",
        status=412,
        api_error_code="CONTENT_CHANGED",
        headers={"If-Match": f'"{"0" * 64}"', "Range": "bytes=1024-2047"},
        body=_error_body(
            "CONTENT_CHANGED", "ETag no longer matches", retryable=False, request_id="req-bf1"
        ),
        invariant=(
            "AC-04 resume with an If-Match value that is not the original ETag returns 412 "
            "CONTENT_CHANGED"
        ),
    )
    out.add(
        id="clip-file-response-416-multi-range",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=416,
        api_error_code="RANGE_INVALID",
        headers={"Range": "bytes=0-99,200-299", "Accept-Ranges": "bytes"},
        body=_error_body(
            "RANGE_INVALID", "Only a single range is supported", retryable=False, request_id="req-bf2"
        ),
        invariant="AC-04 a multipart range is rejected with 416; only bytes=start-end is granted",
    )
    out.add(
        id="clip-file-response-410-clip-gone",
        contract="device",
        category="catalog",
        operation="device.get_clip_file",
        direction="response",
        status=410,
        api_error_code="CLIP_GONE",
        headers={"X-Clip-Lease": lease_id},
        body=_error_body("CLIP_GONE", "Clip was evicted", retryable=False, request_id="req-bf3"),
        invariant="AC-04 a known evicted clip returns 410 CLIP_GONE",
    )
    out.add(
        id="clip-file-response-409-lease-expired",
        contract="device",
        category="lease",
        operation="device.get_clip_file",
        direction="response",
        status=409,
        api_error_code="LEASE_EXPIRED",
        headers={"X-Clip-Lease": lease_id},
        body=_error_body(
            "LEASE_EXPIRED",
            "Lease expired before the response started",
            retryable=False,
            request_id="req-bf6",
        ),
        invariant=(
            "AC-04 interfaces.md §4: expiry checked before the response began is a "
            "complete 409 LEASE_EXPIRED body, because no header had been sent yet to "
            "withdraw — the after-headers case can only close the stream"
        ),
    )
    for bad_id, code, detail in (
        (
            {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 1024-0/{media.baseline_payload_bytes}",
                "ETag": payload_etag,
                "Content-Length": "1024",
            },
            CONTENT_RANGE_INVALID,
            "Content-Range with first greater than last",
        ),
        (
            {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
                "ETag": payload_etag,
                "Content-Length": "2048",
            },
            CONTENT_LENGTH_MISMATCH,
            "Content-Length disagreeing with the granted slice",
        ),
        (
            {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
                "ETag": media.baseline_payload_sha256,
                "Content-Length": "1024",
            },
            ETAG_INVALID,
            "unquoted ETag",
        ),
        (
            {
                "Accept-Ranges": "none",
                "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
                "ETag": payload_etag,
                "Content-Length": "1024",
            },
            ACCEPT_RANGES_INVALID,
            "Accept-Ranges none on an immutable file",
        ),
    ):
        out.add(
            id=f"clip-file-response-206-bad-{code.lower()}",
            contract="device",
            category="range",
            operation="device.get_clip_file",
            direction="response",
            status=206,
            headers=bad_id,
            expected="invalid",
            codes=(code,),
            invariant=f"AC-04/AC-06 range: {detail} violates the documented 206 rules",
        )
    out.add(
        id="clip-file-response-416-without-multi-range",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=416,
        headers={"Range": "bytes=0-99", "Accept-Ranges": "bytes"},
        body=_error_body(
            "RANGE_INVALID", "Only a single range is supported", retryable=False, request_id="req-bf4"
        ),
        expected="invalid",
        codes=(RANGE_MULTI_NOT_ALLOWED,),
        invariant=(
            "AC-06 range: 416 is only ever the answer to a multipart or suffix range, so claiming "
            "it for a supported single range is contract misuse"
        ),
    )
    out.add(
        id="clip-file-response-416-hyphenless",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=416,
        api_error_code="RANGE_INVALID",
        headers={"Range": "bytes=10", "Accept-Ranges": "bytes"},
        body=_error_body(
            "RANGE_INVALID", "Malformed range specifier", retryable=False, request_id="req-bf7"
        ),
        invariant=(
            "AC-04/AC-06 range: `bytes=10` is not a range this contract supports, so 416 "
            "is the required answer and the refusal is conformant"
        ),
    )
    out.add(
        id="clip-file-response-206-hyphenless",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=206,
        headers={
            "Range": "bytes=10",
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
            "ETag": payload_etag,
            "Content-Length": "1024",
        },
        expected="invalid",
        codes=(RANGE_MULTI_NOT_ALLOWED,),
        invariant=(
            "AC-06 range: a specifier with no hyphen is not a single bytes=start-end or "
            "bytes=start- range, so granting it with 206 is contract misuse"
        ),
    )
    out.add(
        id="clip-file-response-416-beyond-eof",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=416,
        api_error_code="RANGE_INVALID",
        headers={
            "Range": "bytes=999999999-",
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes */{media.baseline_payload_bytes}",
        },
        body=_error_body(
            "RANGE_INVALID",
            "Range starts past the end of the file",
            retryable=False,
            request_id="req-bf8",
        ),
        invariant=(
            "AC-04/AC-06 range: a supported range whose start is at or past the end is "
            "unsatisfiable, and the 416 proves it with `Content-Range: bytes */<total>`"
        ),
    )
    out.add(
        id="clip-file-response-416-reversed",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=416,
        api_error_code="RANGE_INVALID",
        headers={"Range": "bytes=200-100", "Accept-Ranges": "bytes"},
        body=_error_body(
            "RANGE_INVALID", "Range end precedes its start", retryable=False, request_id="req-bf9"
        ),
        invariant=(
            "AC-04/AC-06 range: an endpoint ordering no file can satisfy is refused with "
            "416 rather than served"
        ),
    )
    out.add(
        id="clip-file-response-206-reversed",
        contract="device",
        category="range",
        operation="device.get_clip_file",
        direction="response",
        status=206,
        headers={
            "Range": "bytes=200-100",
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes 0-1023/{media.baseline_payload_bytes}",
            "ETag": payload_etag,
            "Content-Length": "1024",
        },
        expected="invalid",
        codes=(RANGE_MULTI_NOT_ALLOWED,),
        invariant=(
            "AC-06 range: bytes after their own end cannot be granted, so answering that "
            "ordering with 206 instead of 416 is contract misuse"
        ),
    )
    out.add(
        id="clip-file-response-410-undocumented-code",
        contract="device",
        category="error-envelope",
        operation="device.get_clip_file",
        direction="response",
        status=410,
        api_error_code="CLIP_EXPIRED",
        body=_error_body("CLIP_EXPIRED", "Clip is old", retryable=False, request_id="req-bf5"),
        expected="invalid",
        codes=(ERROR_CODE_UNDOCUMENTED,),
        invariant=(
            "AC-06 error: CLIP_EXPIRED is not a documented code, so clients would branch on an "
            "invented name instead of CLIP_GONE"
        ),
    )
    out.add(
        id="clip-file-response-missing-required-headers",
        contract="device",
        category="etag",
        operation="device.get_clip_file",
        direction="response",
        status=206,
        headers={"Content-Length": "1024"},
        expected="invalid",
        codes=(HEADER_MISSING, HEADER_MISSING, HEADER_MISSING),
        invariant="AC-04 206 without Accept-Ranges, Content-Range and ETag is not a valid response",
    )

    out.add(
        id="event-create-request",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="request",
        schema="DeviceEventRequest",
        body={
            "v": API_VERSION,
            "event_id": _uuid("event-1"),
            "clip_ids": [media.baseline_clip_id, media.gap_clip_id],
            "label": "Fetch at the park",
        },
        invariant="AC-04 valid pin set: 1-10 finalized clip ids, client UUID, label within 120 chars",
    )
    out.add(
        id="event-create-response-201",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="response",
        status=201,
        schema="DeviceEventResponse",
        body={
            "v": API_VERSION,
            "event_id": _uuid("event-1"),
            "clip_ids": [media.baseline_clip_id, media.gap_clip_id],
            "label": "Fetch at the park",
            "newly_protected_bytes": media.baseline_payload_bytes
            + media.baseline_index_bytes
            + media.gap_payload_bytes
            + media.gap_index_bytes,
            "protected_bytes": 536_870_912,
        },
        invariant="AC-04 pins applied atomically after computing the newly protected bytes",
    )
    out.add(
        id="event-create-response-409-protection-quota",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="response",
        status=409,
        api_error_code="PROTECTION_QUOTA",
        body=_error_body(
            "PROTECTION_QUOTA", "Protection ceiling would be exceeded", retryable=False, request_id="req-c01"
        ),
        invariant="AC-04 409 PROTECTION_QUOTA when the pins would pass the 2,000,000,000-byte ceiling",
    )
    out.add(
        id="event-create-response-409-idempotency-collision",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="response",
        status=409,
        api_error_code="IDEMPOTENCY_CONFLICT",
        body=_error_body(
            "IDEMPOTENCY_CONFLICT", "Same event_id, different content", retryable=False, request_id="req-c02"
        ),
        invariant="AC-04 same event_id with different content returns 409, not a silent overwrite",
    )
    out.add(
        id="event-create-request-too-many-clips",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="request",
        schema="DeviceEventRequest",
        body={
            "v": API_VERSION,
            "event_id": _uuid("event-11"),
            "clip_ids": [f"{boot_id(f'pin-{i}')}-00000000" for i in range(11)],
            "label": "Too many",
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 more than ten clip ids in one event is rejected with 400",
    )
    out.add(
        id="event-create-request-label-too-long",
        contract="device",
        category="event",
        operation="device.create_event",
        direction="request",
        schema="DeviceEventRequest",
        body={
            "v": API_VERSION,
            "event_id": _uuid("event-long-label"),
            "clip_ids": [media.baseline_clip_id],
            "label": "l" * 121,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-04 a label above 120 characters is rejected",
    )
    out.add(
        id="event-create-request-bad-uuid",
        contract="device",
        category="id",
        operation="device.create_event",
        direction="request",
        schema="DeviceEventRequest",
        body={
            "v": API_VERSION,
            "event_id": "not-a-uuid",
            "clip_ids": [media.baseline_clip_id],
            "label": "Bad id",
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-06 id: event_id must be a canonical client UUID",
    )
    out.add(
        id="events-page-response-200",
        contract="device",
        category="event",
        operation="device.list_events",
        direction="response",
        status=200,
        schema="DeviceEventsPage",
        body={
            "v": API_VERSION,
            "items": [
                {
                    "v": API_VERSION,
                    "event_id": _uuid("event-1"),
                    "clip_ids": [media.baseline_clip_id],
                    "label": "Fetch at the park",
                }
            ],
            "next_cursor": None,
        },
        invariant="GET /events lists event metadata with a null cursor at the end",
    )
    out.add(
        id="event-delete-204",
        contract="device",
        category="event",
        operation="device.delete_event",
        direction="response",
        status=204,
        invariant="AC-04 DELETE /events/{event_id} removes only this event's pins",
    )
    out.add(
        id="error-envelope-storage-full",
        contract="device",
        category="error-envelope",
        operation="device.post_ota",
        direction="response",
        status=503,
        api_error_code="STORAGE_FULL",
        headers={"Retry-After": "30"},
        body=_error_body(
            "STORAGE_FULL",
            "No evictable recording space",
            retryable=False,
            request_id="req-storage-full-1",
        ),
        invariant=(
            "AC-04 error envelope: the exact shape and code interfaces.md §1 shows, with Retry-After "
            "where retry is meaningful"
        ),
    )
    out.add(
        id="error-envelope-missing-fields",
        contract="device",
        category="error-envelope",
        operation="device.get_status",
        direction="response",
        status=503,
        body={
            "v": API_VERSION,
            "error": {"code": "UNAVAILABLE", "message": "Temporarily unavailable"},
        },
        expected="invalid",
        codes=(ERROR_ENVELOPE_INVALID,),
        invariant="AC-04 error envelope without retryable/request_id is not the documented envelope",
    )
    out.add(
        id="error-envelope-lowercase-code",
        contract="device",
        category="error-envelope",
        operation="device.get_status",
        direction="response",
        status=503,
        body=_error_body("unavailable", "Temporarily unavailable", retryable=True, request_id="req-x1"),
        expected="invalid",
        codes=(ERROR_ENVELOPE_INVALID,),
        invariant="AC-06 error: codes are stable upper-snake-case names, never free text",
    )
    out.add(
        id="ota-stage-response-202",
        contract="device",
        category="ota",
        operation="device.post_ota",
        direction="response",
        status=202,
        schema="OtaStageResponse",
        body={"v": API_VERSION, "state": "reboot_pending"},
        invariant=(
            "AC-07 successful staging of the deferred signed envelope returns 202 reboot_pending; "
            "no request body vector exists because the encoding is deferred to 2.10"
        ),
    )
    return tuple(out.items)


def backend_fixtures(media: "MediaCorpus") -> tuple[ApiFixture, ...]:
    """Backend-contract vectors: AC-05 coverage of identity through health."""
    out = _ApiList()
    idempotency = _uuid("idempotency-upload-1")

    out.add(
        id="tokens-create-request",
        contract="backend",
        category="auth",
        operation="backend.create_token",
        direction="request",
        schema="CreateTokenRequest",
        body={"v": API_VERSION, "scope": "device-upload", "device_id": DEVICE_ID},
        invariant="AC-05 admin creates a scoped device-upload token bound to one device",
    )
    out.add(
        id="tokens-create-response-201",
        contract="backend",
        category="auth",
        operation="backend.create_token",
        direction="response",
        status=201,
        schema="CreateTokenResponse",
        body={
            "v": API_VERSION,
            "token_id": "tok-upload-1",
            "token": _token("backend-token-1"),
            "scope": "device-upload",
            "device_id": DEVICE_ID,
        },
        invariant="AC-05 token returned once as 32-byte unpadded base64url; only hashes are stored",
    )
    out.add(
        id="tokens-create-response-403",
        contract="backend",
        category="auth",
        operation="backend.create_token",
        direction="response",
        status=403,
        api_error_code="FORBIDDEN",
        body=_error_body(
            "FORBIDDEN", "Admin credential required", retryable=False, request_id="req-be-1"
        ),
        invariant="AC-05 a device-upload token cannot mint tokens: 403 wrong privilege",
    )
    out.add(
        id="tokens-delete-204",
        contract="backend",
        category="auth",
        operation="backend.delete_token",
        direction="response",
        status=204,
        invariant="AC-05 DELETE /tokens/{id} revokes a scoped token",
    )
    out.add(
        id="tokens-create-request-bad-scope",
        contract="backend",
        category="auth",
        operation="backend.create_token",
        direction="request",
        schema="CreateTokenRequest",
        body={"v": API_VERSION, "scope": "superuser"},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-05 only the owner and device-upload scopes exist",
    )

    out.add(
        id="device-register-request",
        contract="backend",
        category="identity",
        operation="backend.register_device",
        direction="request",
        schema="RegisterDeviceRequest",
        body={"v": API_VERSION, "device_id": DEVICE_ID, "label": "Chest camera"},
        invariant="AC-05 owner registers {device_id,label}; registration alone grants no camera access",
    )
    out.add(
        id="device-register-response-201",
        contract="backend",
        category="identity",
        operation="backend.register_device",
        direction="response",
        status=201,
        schema="DeviceRecord",
        body={"v": API_VERSION, "device_id": DEVICE_ID, "label": "Chest camera"},
        invariant="AC-05 registration record",
    )
    out.add(
        id="device-register-request-bad-device-id",
        contract="backend",
        category="id",
        operation="backend.register_device",
        direction="request",
        schema="RegisterDeviceRequest",
        body={"v": API_VERSION, "device_id": OTHER_DEVICE_ID.upper(), "label": "Chest camera"},
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-06 id: device_id is 32 lowercase hex, so uppercase is refused",
    )
    out.add(
        id="devices-page-response-200",
        contract="backend",
        category="catalog",
        operation="backend.list_devices",
        direction="response",
        status=200,
        schema="DevicesPage",
        body={
            "v": API_VERSION,
            "items": [{"v": API_VERSION, "device_id": DEVICE_ID, "label": "Chest camera"}],
            "next_cursor": None,
        },
        invariant="AC-05 owner-scoped paginated device catalog",
    )

    out.add(
        id="clips-page-response-200",
        contract="backend",
        category="catalog",
        operation="backend.list_clips",
        direction="response",
        status=200,
        schema="BackendClipsPage",
        body={
            "v": API_VERSION,
            "items": [
                {
                    "device_id": DEVICE_ID,
                    "clip_id": media.baseline_clip_id,
                    "start_utc": "2026-03-04T11:02:03.250Z",
                    "duration_us": 266_667,
                    "frame_count": 4,
                    "bytes": media.baseline_payload_bytes + media.baseline_index_bytes,
                    "recovered": False,
                    "manifest_summary": {
                        "duration_us": 266_667,
                        "frame_count": 4,
                        "clock_source": "sntp",
                        "close_reason": "duration",
                        "recovered": False,
                    },
                }
            ],
            "next_cursor": "cur_" + "b" * 40,
        },
        invariant="AC-05 clips page carries the device id and an original-manifest summary",
    )
    out.add(
        id="clips-page-request-cursor-too-long",
        contract="backend",
        category="pagination",
        operation="backend.list_clips",
        direction="request",
        headers={"cursor": "c" * (MAX_CURSOR_CHARS + 1), "limit": str(MAX_PAGE_LIMIT)},
        expected="invalid",
        codes=(CURSOR_TOO_LONG,),
        invariant="AC-05/AC-06 pagination: cursor bounded to 256 characters",
    )
    out.add(
        id="clips-page-request-limit-too-large",
        contract="backend",
        category="pagination",
        operation="backend.list_clips",
        direction="request",
        headers={"limit": str(MAX_PAGE_LIMIT + 1)},
        expected="invalid",
        codes=(PAGE_LIMIT_INVALID,),
        invariant="AC-05/AC-06 pagination: limit above 100 is refused (default 100)",
    )
    out.add(
        id="clip-detail-response-200",
        contract="backend",
        category="catalog",
        operation="backend.get_clip",
        direction="response",
        status=200,
        schema="StoredClip",
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "manifest": media.baseline_manifest,
            "uploaded_at": "2026-03-04T12:00:00.000Z",
            "integrity_state": "verified",
            "derivatives": [
                {
                    "derivative_id": "drv-1",
                    "type": "transcode",
                    "preset": "h264-vbr-720p",
                    "sha256": _sha("derivative-output"),
                    "output": {"width": 1280, "height": 720},
                }
            ],
        },
        invariant=(
            "AC-05 GET /clips/{clip_id}: the exact stored manifest, upload time, integrity state "
            "and derivative metadata"
        ),
    )
    out.add(
        id="clip-detail-response-missing-version",
        contract="backend",
        category="version",
        operation="backend.get_clip",
        direction="response",
        status=200,
        schema="StoredClip",
        body={
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "manifest": media.baseline_manifest,
            "uploaded_at": "2026-03-04T12:00:00.000Z",
            "integrity_state": "verified",
            "derivatives": [],
        },
        expected="invalid",
        codes=(API_VERSION_MISSING,),
        invariant="AC-06 version: every response object carries top-level v:1",
    )
    out.add(
        id="clip-delete-response-202",
        contract="backend",
        category="catalog",
        operation="backend.delete_clip",
        direction="response",
        status=202,
        schema="DeletingResponse",
        body={"v": API_VERSION, "state": "deleting"},
        invariant="AC-05 owner deletion is accepted with 202 deleting and never touches the SD card",
    )
    out.add(
        id="clip-delete-response-409-clip-protected",
        contract="backend",
        category="catalog",
        operation="backend.delete_clip",
        direction="response",
        status=409,
        api_error_code="CLIP_PROTECTED",
        body=_error_body(
            "CLIP_PROTECTED", "Server event pins remain", retryable=False, request_id="req-cl-1"
        ),
        invariant="AC-05 deletion returns 409 CLIP_PROTECTED until every server event pin is removed",
    )
    out.add(
        id="clip-file-response-206",
        contract="backend",
        category="range",
        operation="backend.get_clip_file",
        direction="response",
        status=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": (
                f"bytes 0-{media.baseline_index_bytes - 1}/{media.baseline_index_bytes}"
            ),
            "ETag": f'"{media.baseline_index_sha256}"',
            "Content-Length": str(media.baseline_index_bytes),
        },
        invariant=(
            "AC-05 original download uses the same ETag/Range rules as the device, against the real "
            "committed index bytes"
        ),
    )
    out.add(
        id="clip-file-response-200",
        contract="backend",
        category="etag",
        operation="backend.get_clip_file",
        direction="response",
        status=200,
        headers={
            "Accept-Ranges": "bytes",
            "ETag": f'"{media.baseline_payload_sha256}"',
            "Content-Length": str(media.baseline_payload_bytes),
        },
        invariant=(
            "AC-05 a whole-original download advertises bytes, the whole-file ETag and the exact "
            "committed payload length"
        ),
    )

    out.add(
        id="clip-file-response-410-clip-gone",
        contract="backend",
        category="catalog",
        operation="backend.get_clip",
        direction="response",
        status=410,
        api_error_code="CLIP_GONE",
        body=_error_body("CLIP_GONE", "Clip was deleted", retryable=False, request_id="req-cl-2"),
        invariant="AC-05 a known deleted clip returns 410 CLIP_GONE",
    )

    upload_id = "upl_0000000000000000000000000000001"
    out.add(
        id="upload-create-request",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": idempotency},
        body={"v": API_VERSION, "manifest_base64url": media.baseline_manifest_base64url},
        invariant=(
            "AC-05 POST /uploads carries unpadded base64url of the committed baseline manifest.json "
            "bytes plus an Idempotency-Key UUID"
        ),
    )
    out.add(
        id="upload-create-response-201",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="response",
        status=201,
        schema="UploadCreated",
        body={
            "v": API_VERSION,
            "upload_id": upload_id,
            "state": "receiving",
            "offsets": {"video.mjpg": 0, "frames.jsonl": 0},
            "expires_in_s": UPLOAD_EXPIRY_S,
        },
        invariant="AC-05 init returns receiving with both offsets at zero and the 86400 s expiry",
    )
    out.add(
        id="upload-create-response-409-idempotency-mismatch",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="response",
        status=409,
        api_error_code="IDEMPOTENCY_CONFLICT",
        body=_error_body(
            "IDEMPOTENCY_CONFLICT", "Same Idempotency-Key, different request", retryable=False, request_id="req-up-1"
        ),
        invariant="AC-05 same Idempotency-Key with a different request body returns 409",
    )
    out.add(
        id="upload-create-response-413-encoded-too-large",
        contract="backend",
        category="boundary",
        operation="backend.create_upload",
        direction="response",
        status=413,
        api_error_code="BOUND_EXCEEDED",
        body=_error_body(
            "BOUND_EXCEEDED", "Encoded request exceeds 32 KiB", retryable=False, request_id="req-up-2"
        ),
        invariant="AC-05 an encoded initialization above the 32 KiB body limit returns 413",
    )
    out.add(
        id="upload-create-response-422-decoded-too-large",
        contract="backend",
        category="boundary",
        operation="backend.create_upload",
        direction="response",
        status=422,
        api_error_code="INTEGRITY_FAILURE",
        body=_error_body(
            "INTEGRITY_FAILURE", "Decoded manifest exceeds 16 KiB", retryable=False, request_id="req-up-3"
        ),
        invariant="AC-05 a decoded manifest above 16 KiB returns 422 before any allocation",
    )
    out.add(
        id="upload-create-request-encoded-too-large",
        contract="backend",
        category="boundary",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-oversize")},
        body={"v": API_VERSION, "manifest_base64url": media.oversize_manifest_base64url},
        expected="invalid",
        codes=(API_BODY_TOO_LARGE,),
        invariant=(
            "AC-05/AC-06 boundary: this initialization body is larger than 32,768 bytes, so the "
            "server refuses it before decoding anything"
        ),
    )
    out.add(
        id="upload-create-request-bad-length",
        contract="backend",
        category="hash",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-length")},
        body={"v": API_VERSION, "manifest_base64url": "A" * 4097},
        expected="invalid",
        codes=(BASE64URL_LENGTH_INVALID,),
        invariant=(
            "AC-05 a base64 length that is 1 mod 4 cannot be produced by any encoder, so the "
            "binding is refused before it is decoded"
        ),
    )

    out.add(
        id="upload-create-request-decoded-too-large",
        contract="backend",
        category="boundary",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-decoded")},
        body={"v": API_VERSION, "manifest_base64url": media.decoded_oversize_manifest_base64url},
        expected="invalid",
        codes=(MANIFEST_DECODED_TOO_LARGE,),
        invariant=(
            "AC-05/AC-06 boundary: alphabet-legal base64url whose decoded length is 16,385 bytes, "
            "one past the manifest bound"
        ),
    )
    out.add(
        id="upload-create-request-bad-alphabet",
        contract="backend",
        category="hash",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-alphabet")},
        body={"v": API_VERSION, "manifest_base64url": media.padded_manifest_base64url},
        expected="invalid",
        codes=(BASE64URL_ALPHABET_INVALID,),
        invariant="AC-05 padded base64 with '+' and '/' is not the documented unpadded base64url",
    )
    out.add(
        id="upload-create-request-not-json",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-notjson")},
        body={"v": API_VERSION, "manifest_base64url": media.non_json_manifest_base64url},
        expected="invalid",
        codes=(MANIFEST_JSON_INVALID_DECODED,),
        invariant="AC-05 decodable bytes that are not JSON are rejected during initialization",
    )
    out.add(
        id="upload-create-request-invalid-manifest",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-badschema")},
        body={"v": API_VERSION, "manifest_base64url": media.invalid_manifest_base64url},
        expected="invalid",
        codes=(MANIFEST_DECODED_SCHEMA,),
        invariant="AC-05 JSON that is not a valid media manifest is rejected before allocation",
    )
    out.add(
        id="upload-create-request-missing-field",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={"Idempotency-Key": _uuid("idempotency-missing")},
        body={"v": API_VERSION},
        expected="invalid",
        codes=(API_SCHEMA_MISSING_FIELD,),
        invariant="AC-05 initialization without manifest_base64url is refused",
    )
    out.add(
        id="upload-create-request-missing-idempotency-key",
        contract="backend",
        category="upload",
        operation="backend.create_upload",
        direction="request",
        schema="CreateUploadRequest",
        headers={},
        body={"v": API_VERSION, "manifest_base64url": media.baseline_manifest_base64url},
        expected="invalid",
        codes=(HEADER_MISSING,),
        invariant="AC-05 the required Idempotency-Key header cannot be omitted",
    )

    out.add(
        id="upload-patch-request-valid",
        contract="backend",
        category="upload",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "0",
            "Upload-Checksum": f"sha256 {media.baseline_chunk_sha256}",
            "Content-Length": str(media.baseline_chunk_bytes),
        },
        invariant=(
            "AC-05 chunk append carries the expected offset plus sha256 over the chunk, within the "
            "1-1,048,576 byte body range"
        ),
    )
    out.add(
        id="upload-patch-response-204",
        contract="backend",
        category="upload",
        operation="backend.patch_upload_file",
        direction="response",
        status=204,
        headers={"Upload-Offset": str(media.baseline_chunk_bytes)},
        invariant="AC-05 accepted chunk returns 204 with the new authoritative Upload-Offset",
    )
    out.add(
        id="upload-patch-response-409-wrong-offset",
        contract="backend",
        category="upload",
        operation="backend.patch_upload_file",
        direction="response",
        status=409,
        api_error_code="OFFSET_CONFLICT",
        headers={"Upload-Offset": str(media.baseline_chunk_bytes)},
        body=_error_body(
            "OFFSET_CONFLICT", "Offset does not match", retryable=False, request_id="req-up-4"
        ),
        invariant=(
            "AC-05 a wrong offset returns 409 with the authoritative offset and never appends "
            "repeated bytes implicitly"
        ),
    )
    out.add(
        id="upload-patch-response-422-bad-hash",
        contract="backend",
        category="hash",
        operation="backend.patch_upload_file",
        direction="response",
        status=422,
        api_error_code="INTEGRITY_FAILURE",
        body=_error_body(
            "INTEGRITY_FAILURE", "Chunk hash mismatch", retryable=False, request_id="req-up-5"
        ),
        invariant="AC-05 a chunk whose hash does not match Upload-Checksum returns 422",
    )
    out.add(
        id="upload-patch-response-413-oversized",
        contract="backend",
        category="boundary",
        operation="backend.patch_upload_file",
        direction="response",
        status=413,
        api_error_code="BOUND_EXCEEDED",
        body=_error_body(
            "BOUND_EXCEEDED", "Chunk exceeds 1,048,576 bytes", retryable=False, request_id="req-up-6"
        ),
        invariant="AC-05 an oversized chunk body returns 413",
    )
    out.add(
        id="upload-patch-request-empty-body",
        contract="backend",
        category="boundary",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "0",
            "Upload-Checksum": f"sha256 {_sha('empty-chunk')}",
            "Content-Length": "0",
        },
        expected="invalid",
        codes=(CHUNK_SIZE_INVALID,),
        invariant=f"AC-05/AC-06 boundary: a 0-byte chunk is below the {1}-byte floor and is 400",
    )
    out.add(
        id="upload-patch-request-oversized-body",
        contract="backend",
        category="boundary",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "0",
            "Upload-Checksum": f"sha256 {_sha('oversize-chunk')}",
            "Content-Length": str(MAX_CHUNK_BYTES + 1),
        },
        expected="invalid",
        codes=(CHUNK_SIZE_INVALID,),
        invariant=(
            f"AC-05/AC-06 boundary: Content-Length {MAX_CHUNK_BYTES + 1} is above the 1,048,576-byte "
            "chunk ceiling and is 413"
        ),
    )
    out.add(
        id="upload-patch-request-bad-checksum",
        contract="backend",
        category="hash",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "0",
            "Upload-Checksum": f"sha256 {_sha('chunk').upper()}",
            "Content-Length": str(media.baseline_chunk_bytes),
        },
        expected="invalid",
        codes=(UPLOAD_CHECKSUM_SYNTAX,),
        invariant="AC-05/AC-06 hash: Upload-Checksum must be lowercase hex over exactly 64 digits",
    )
    out.add(
        id="upload-patch-request-disallowed-name",
        contract="backend",
        category="upload",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "0",
            "Upload-Checksum": f"sha256 {media.baseline_chunk_sha256}",
            "Content-Length": str(media.baseline_chunk_bytes),
            "X-Upload-Name": "manifest.json",
        },
        expected="invalid",
        codes=(FILE_NAME_NOT_ALLOWED,),
        invariant="AC-05 only video.mjpg and frames.jsonl may be streamed, never the manifest",
    )
    out.add(
        id="upload-patch-request-negative-offset",
        contract="backend",
        category="upload",
        operation="backend.patch_upload_file",
        direction="request",
        headers={
            "Upload-Offset": "-1",
            "Upload-Checksum": f"sha256 {media.baseline_chunk_sha256}",
            "Content-Length": str(media.baseline_chunk_bytes),
        },
        expected="invalid",
        codes=(UPLOAD_OFFSET_INVALID,),
        invariant="AC-05/AC-06 boundary: a negative Upload-Offset is refused outright",
    )
    out.add(
        id="upload-head-response-200",
        contract="backend",
        category="upload",
        operation="backend.head_upload_file",
        direction="response",
        status=200,
        headers={
            "Upload-Offset": str(media.baseline_payload_bytes),
            "Upload-Length": str(media.baseline_payload_bytes),
        },
        invariant="AC-05 HEAD returns the authoritative committed offset and declared length",
    )
    out.add(
        id="upload-head-response-bad-length",
        contract="backend",
        category="boundary",
        operation="backend.head_upload_file",
        direction="response",
        status=200,
        headers={"Upload-Offset": "0", "Upload-Length": "0"},
        expected="invalid",
        codes=(UPLOAD_LENGTH_INVALID,),
        invariant="AC-05/AC-06 boundary: a declared length of zero cannot be a finalized clip file",
    )
    out.add(
        id="upload-head-response-missing-offset",
        contract="backend",
        category="upload",
        operation="backend.head_upload_file",
        direction="response",
        status=200,
        headers={"Upload-Length": str(media.baseline_payload_bytes)},
        expected="invalid",
        codes=(HEADER_MISSING,),
        invariant="AC-05 HEAD without the authoritative Upload-Offset cannot steer a retry",
    )
    out.add(
        id="upload-commit-request",
        contract="backend",
        category="upload",
        operation="backend.commit_upload",
        direction="request",
        schema="VersionedRequest",
        body={"v": API_VERSION},
        invariant="POST /uploads/{id}/commit body carries only the version",
    )
    out.add(
        id="upload-commit-response-201-stored",
        contract="backend",
        category="upload",
        operation="backend.commit_upload",
        direction="response",
        status=201,
        schema="UploadCommitted",
        body={"v": API_VERSION, "clip_id": media.baseline_clip_id, "state": "stored"},
        invariant="AC-05 commit returns 201 stored only after durability",
    )
    out.add(
        id="upload-commit-response-201-repeat",
        contract="backend",
        category="upload",
        operation="backend.commit_upload",
        direction="response",
        status=201,
        schema="UploadCommitted",
        body={"v": API_VERSION, "clip_id": media.baseline_clip_id, "state": "stored"},
        invariant="AC-05 a repeated commit returns the identical result (idempotent)",
    )
    out.add(
        id="upload-commit-response-422-integrity",
        contract="backend",
        category="hash",
        operation="backend.commit_upload",
        direction="response",
        status=422,
        api_error_code="INTEGRITY_FAILURE",
        body=_error_body(
            "INTEGRITY_FAILURE",
            "Declared hashes disagree",
            retryable=False,
            request_id="req-up-7",
        ),
        invariant="AC-05 integrity failure returns 422 and creates no catalog entry",
    )
    out.add(
        id="upload-commit-response-409-clip-id-collision",
        contract="backend",
        category="upload",
        operation="backend.commit_upload",
        direction="response",
        status=409,
        api_error_code="CLIP_ID_COLLISION",
        body=_error_body(
            "CLIP_ID_COLLISION",
            "Same clip id, different bytes",
            retryable=False,
            request_id="req-up-8",
        ),
        invariant=(
            "AC-05 existing (device_id,clip_id) with different manifest or data hashes returns 409 "
            "CLIP_ID_COLLISION"
        ),
    )
    out.add(
        id="upload-get-response-200",
        contract="backend",
        category="upload",
        operation="backend.get_upload",
        direction="response",
        status=200,
        schema="UploadDetail",
        body={
            "v": API_VERSION,
            "upload_id": upload_id,
            "state": "receiving",
            "offsets": {
                "video.mjpg": media.baseline_chunk_bytes,
                "frames.jsonl": 0,
            },
            "expires_at": "2026-03-05T12:00:00.000Z",
        },
        invariant="AC-05 GET /uploads/{id} reports state, offsets and the expiry",
    )
    out.add(
        id="upload-delete-204",
        contract="backend",
        category="upload",
        operation="backend.delete_upload",
        direction="response",
        status=204,
        invariant="AC-05 DELETE /uploads/{id} cancels a receiving upload idempotently",
    )
    out.add(
        id="upload-get-response-410-expired",
        contract="backend",
        category="upload",
        operation="backend.get_upload",
        direction="response",
        status=410,
        api_error_code="EXPIRED",
        body=_error_body(
            "EXPIRED", "Upload expired after 24 h", retryable=False, request_id="req-up-9"
        ),
        invariant="AC-05 an inactive receiving upload older than 24 h returns 410",
    )

    out.add(
        id="event-create-request",
        contract="backend",
        category="event",
        operation="backend.create_event",
        direction="request",
        schema="BackendEventRequest",
        body={
            "v": API_VERSION,
            "event_id": _uuid("backend-event-1"),
            "device_id": DEVICE_ID,
            "clip_ids": [media.baseline_clip_id],
            "label": "Owner review",
        },
        invariant="AC-05 server event association is scoped by device_id and is not a pin ack",
    )
    out.add(
        id="event-create-response-201",
        contract="backend",
        category="event",
        operation="backend.create_event",
        direction="response",
        status=201,
        schema="BackendEventRecord",
        body={
            "v": API_VERSION,
            "event_id": _uuid("backend-event-1"),
            "device_id": DEVICE_ID,
            "clip_ids": [media.baseline_clip_id],
            "label": "Owner review",
        },
        invariant="AC-05 created server event record",
    )
    out.add(
        id="events-page-response-200",
        contract="backend",
        category="event",
        operation="backend.list_events",
        direction="response",
        status=200,
        schema="BackendEventsPage",
        body={
            "v": API_VERSION,
            "items": [
                {
                    "v": API_VERSION,
                    "event_id": _uuid("backend-event-1"),
                    "device_id": DEVICE_ID,
                    "clip_ids": [media.baseline_clip_id],
                    "label": "Owner review",
                }
            ],
            "next_cursor": None,
        },
        invariant="AC-05 owner event list",
    )
    out.add(
        id="event-delete-204",
        contract="backend",
        category="event",
        operation="backend.delete_event",
        direction="response",
        status=204,
        invariant="AC-05 owner event removal",
    )

    job_types = ("transcode", "stabilize")
    out.add(
        id="job-create-request",
        contract="backend",
        category="job",
        operation="backend.create_job",
        direction="request",
        schema="CreateJobRequest",
        headers={"Idempotency-Key": _uuid("idempotency-job")},
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "type": job_types[0],
            "preset": "h264-vbr-720p",
        },
        invariant="AC-05 POST /jobs with a documented type, an approved preset and Idempotency-Key",
    )
    out.add(
        id="job-create-response-201",
        contract="backend",
        category="job",
        operation="backend.create_job",
        direction="response",
        status=201,
        schema="JobRecord",
        body={
            "v": API_VERSION,
            "job_id": "job-0000",
            "state": "queued",
            "progress": None,
            "error_code": None,
            "derivative_id": None,
        },
        invariant=(
            "AC-05 accepted work is queued with no fabricated progress estimate until a child "
            "reports one"
        ),
    )

    job_states: tuple[tuple[str, float | None, str | None, str | None], ...] = (
        ("queued", None, None, None),
        ("running", 0.4, None, None),
        ("cancel_requested", 0.7, None, None),
        ("succeeded", 1.0, None, "drv-1"),
        ("failed", None, "WORKER_EXITED", None),
        ("cancelled", None, None, None),
        ("interrupted", None, None, None),
    )
    for state, progress, error_code, derivative_id in job_states:
        out.add(
            id=f"job-response-200-{state}",
            contract="backend",
            category="job",
            operation="backend.get_job",
            direction="response",
            status=200,
            schema="JobRecord",
            body={
                "v": API_VERSION,
                "job_id": "job-0001",
                "state": state,
                "progress": progress,
                "error_code": error_code,
                "derivative_id": derivative_id,
            },
            invariant=(
                f"AC-05 job state {state} with progress "
                + ("null (no fabricated estimate)" if progress is None else f"{progress}")
            ),
        )
    out.add(
        id="job-delete-response-202",
        contract="backend",
        category="job",
        operation="backend.delete_job",
        direction="response",
        status=202,
        schema="JobCancellation",
        body={"v": API_VERSION, "state": "cancel_requested"},
        invariant="AC-05 cancellation returns 202 while stopping",
    )
    out.add(
        id="job-create-request-bad-type",
        contract="backend",
        category="job",
        operation="backend.create_job",
        direction="request",
        schema="CreateJobRequest",
        headers={"Idempotency-Key": _uuid("idempotency-job-bad")},
        body={
            "v": API_VERSION,
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "type": "watermark",
            "preset": "h264-vbr-720p",
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-05 only transcode and stabilize exist as job types",
    )
    out.add(
        id="job-response-200-bad-state",
        contract="backend",
        category="job",
        operation="backend.get_job",
        direction="response",
        status=200,
        schema="JobRecord",
        body={
            "v": API_VERSION,
            "job_id": "job-0002",
            "state": "done",
            "progress": None,
            "error_code": None,
            "derivative_id": None,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-05 `done` is not one of the seven documented job states",
    )
    out.add(
        id="job-response-200-progress-out-of-range",
        contract="backend",
        category="boundary",
        operation="backend.get_job",
        direction="response",
        status=200,
        schema="JobRecord",
        body={
            "v": API_VERSION,
            "job_id": "job-0003",
            "state": "running",
            "progress": 1.5,
            "error_code": None,
            "derivative_id": None,
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-05/AC-06 boundary: progress is a fraction in [0,1]",
    )

    out.add(
        id="derivative-response-200",
        contract="backend",
        category="derivative",
        operation="backend.get_derivative",
        direction="response",
        status=200,
        schema="DerivativeRecord",
        body={
            "v": API_VERSION,
            "derivative_id": "drv-1",
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "job_id": "job-0001",
            "type": "transcode",
            "preset": "h264-vbr-720p",
            "encoder_version": "libx264-0.165",
            "filter_version": "vdog-eis-1",
            "params": {"crf": 23, "gop_frames": 30, "duplicate_policy": "frame_duplication"},
            "output": {"width": 1280, "height": 720},
            "crop": {"x": 0, "y": 120, "width": 64, "height": 36},
            "original_hashes": {
                "video.mjpg": media.baseline_payload_sha256,
                "frames.jsonl": media.baseline_index_sha256,
            },
            "sha256": _sha("derivative-output"),
        },
        invariant=(
            "AC-05 a derivative records the original hashes of the committed files, encoder and "
            "filter versions, parameters, output dimensions, crop and its own hash"
        ),
    )
    out.add(
        id="derivative-file-response-200",
        contract="backend",
        category="etag",
        operation="backend.get_derivative_file",
        direction="response",
        status=200,
        headers={
            "Accept-Ranges": "bytes",
            "ETag": f'"{_sha("derivative-output")}"',
            "Content-Length": "8192",
        },
        invariant="AC-05 the whole-derivative download advertises bytes and its ETag",
    )

    out.add(
        id="derivative-file-response-206",
        contract="backend",
        category="range",
        operation="backend.get_derivative_file",
        direction="response",
        status=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": "bytes 0-4095/8192",
            "ETag": f'"{_sha("derivative-output")}"',
            "Content-Length": "4096",
        },
        invariant="AC-05 derivative download reuses the same ETag/Range rules",
    )
    out.add(
        id="derivative-delete-response-202",
        contract="backend",
        category="derivative",
        operation="backend.delete_derivative",
        direction="response",
        status=202,
        schema="DeletingResponse",
        body={"v": API_VERSION, "state": "deleting"},
        invariant="AC-05 owner derivative deletion with idempotent cleanup and no original effect",
    )
    out.add(
        id="derivative-response-200-bad-hash",
        contract="backend",
        category="hash",
        operation="backend.get_derivative",
        direction="response",
        status=200,
        schema="DerivativeRecord",
        body={
            "v": API_VERSION,
            "derivative_id": "drv-2",
            "device_id": DEVICE_ID,
            "clip_id": media.baseline_clip_id,
            "job_id": "job-0002",
            "type": "stabilize",
            "preset": "eis-medium",
            "encoder_version": "libx264-0.165",
            "filter_version": "vdog-eis-1",
            "params": {},
            "output": {"width": 1280, "height": 720},
            "crop": {"x": 0, "y": 0, "width": 64, "height": 36},
            "original_hashes": {
                "video.mjpg": media.baseline_payload_sha256.upper(),
                "frames.jsonl": media.baseline_index_sha256,
            },
            "sha256": _sha("derivative-output"),
        },
        expected="invalid",
        codes=(API_SCHEMA,),
        invariant="AC-06 hash: recorded hashes are 64 lowercase hex, never uppercase",
    )

    out.add(
        id="health-live-response-200",
        contract="backend",
        category="health",
        operation="backend.get_health_live",
        direction="response",
        status=200,
        schema="HealthRecord",
        body={"v": API_VERSION, "status": "ok"},
        invariant="AC-05 minimal liveness body",
    )
    out.add(
        id="health-ready-response-200",
        contract="backend",
        category="health",
        operation="backend.get_health_ready",
        direction="response",
        status=200,
        schema="HealthRecord",
        body={"v": API_VERSION, "status": "ok"},
        invariant="AC-05 readiness verified over DB, storage and the required workers",
    )
    out.add(
        id="health-ready-response-503",
        contract="backend",
        category="health",
        operation="backend.get_health_ready",
        direction="response",
        status=503,
        api_error_code="UNAVAILABLE",
        headers={"Retry-After": "5"},
        body=_error_body(
            "UNAVAILABLE", "Storage dependency unavailable", retryable=True, request_id="req-hl-1"
        ),
        invariant="AC-05 readiness failure is 503 with the shared envelope and Retry-After",
    )
    return tuple(out.items)


@dataclass(frozen=True)
class MediaCorpus:
    """Real committed media values that API vectors bind against.

    Binding API fixtures to actual committed clip bytes (hashes, sizes, clip ids,
    base64url manifest) turns the two halves of the corpus into one cross-checked
    set: a clip edit that changes a hash immediately invalidates the API vectors
    that quote it.
    """

    baseline_clip_id: str
    baseline_manifest: dict[str, Any]
    baseline_payload_bytes: int
    baseline_payload_sha256: str
    baseline_index_bytes: int
    baseline_index_sha256: str
    baseline_manifest_base64url: str
    baseline_chunk_sha256: str
    baseline_chunk_bytes: int
    gap_clip_id: str
    gap_payload_bytes: int
    gap_index_bytes: int
    recovered_clip_id: str
    recovered_payload_bytes: int
    recovered_index_bytes: int
    other_clip_id: str
    oversize_manifest_base64url: str
    decoded_oversize_manifest_base64url: str
    padded_manifest_base64url: str
    non_json_manifest_base64url: str
    invalid_manifest_base64url: str


#: A conformant value for each response header a documented refusal has to carry. The
#: generator writes exact bytes, so it can only emit a header it can name exactly.
_COMPLETION_HEADER_VALUE: Final[Mapping[str, str]] = {
    "Upload-Offset": "1024",
    "Upload-Length": "4096",
    "Accept-Ranges": "bytes",
    "Content-Range": "bytes 0-433/434",
    "ETag": '"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"',
    "Content-Length": "434",
}


def _completion_headers(operation: Operation, status: int) -> dict[str, str] | None:
    """The headers the contract requires on this refusal, or ``None`` for a bare body.

    A response the operation table marks as carrying headers cannot be represented by a
    body alone: the validator checks every required header for the status. Naming the
    value here keeps the completion pass able to emit such a refusal; today no documented
    refusal needs one, and the honest answer for those is ``None``, not an empty sidecar.
    """
    names = operation.required_response_headers.get(status, ())
    if not names:
        return None
    missing = sorted(name for name in names if name not in _COMPLETION_HEADER_VALUE)
    if missing:  # pragma: no cover - refuses a document edit nobody valued
        raise ValueError(f"{operation.key} {status} requires unvalued headers {missing}")
    return {name: _COMPLETION_HEADER_VALUE[name] for name in names}


def _complete_status_coverage(
    items: Sequence[ApiFixture], contract: str, ac: str
) -> list[ApiFixture]:
    """One well-formed example for every documented status nobody else exercised.

    The OpenAPI documents promise these responses, so shipping them without a single
    committed example would leave the contract's most common outcome untested: an
    honest refusal in the shared envelope. Each vector is a *valid* vector precisely
    because the refusal itself is conformant.
    """
    covered = {(item.operation, item.status) for item in items if item.direction == "response"}
    taken = {item.id for item in items}
    out = _ApiList()
    for key, operation in ALL_OPERATIONS.items():
        if operation.contract != contract:
            continue
        for status in sorted(operation.error_codes):
            if (key, status) in covered:
                continue
            documented = operation.error_codes[status]
            if not documented:
                raise ValueError(
                    f"{key} documents status {status} with no stable error code; a"
                    " refusal a client cannot branch on is not a contract"
                )
            code = documented[0]
            slug = key.split(".", 1)[1]
            candidate = f"{slug}-response-{status}-{code.lower()}"
            suffix = 2
            while f"{contract}/valid/{candidate}" in taken:  # pragma: no cover - defensive
                candidate = f"{slug}-response-{status}-{code.lower()}-{suffix}"
                suffix += 1
            taken.add(f"{contract}/valid/{candidate}")
            out.add(
                id=candidate,
                contract=contract,
                category="error",
                operation=key,
                direction="response",
                status=status,
                body=_error_body(
                    code,
                    f"{operation.operation_id} refused with {code}",
                    retryable=status >= 500,
                    request_id=f"req-{slug}-{status}",
                ),
                headers=_completion_headers(operation, status),
                api_error_code=code,
                invariant=(
                    f"{ac} {key} documents {status}; the refusal arrives in the shared "
                    f"envelope with the code the contract allows for it"
                ),
            )
    return out.items


def api_fixtures(media: MediaCorpus) -> tuple[ApiFixture, ...]:
    """Every committed API vector: device first, then backend, each status covered."""
    device = list(device_fixtures(media))
    backend = list(backend_fixtures(media))
    return (
        tuple(device + _complete_status_coverage(device, "device", "AC-04"))
        + tuple(backend + _complete_status_coverage(backend, "backend", "AC-05"))
    )
