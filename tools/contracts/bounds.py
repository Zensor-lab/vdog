"""Frozen numeric bounds shared by the generator, the validator and the tests.

Every constant cites the requirement it comes from. Sources are
``docs/specs/media-format.md`` (section 2 table unless noted) and
``docs/specs/interfaces.md``. Nothing may read a bound from anywhere else, so a
spec change has exactly one place to land.
"""

from __future__ import annotations

# --- JSON number range (media-format.md §2 "JSON integer range") -------------
UINT53_MAX: int = 2**53 - 1

# --- Media v1 bounds (media-format.md §2) ------------------------------------
MEDIA_VERSION: int = 1

MAX_SEGMENT_DURATION_US: int = 120_000_000  # hard maximum; target is 60 s
MAX_DIMENSION_PX: int = 1600
MIN_DIMENSION_PX: int = 1
MIN_NOMINAL_FPS: int = 1
MAX_NOMINAL_FPS: int = 30
MIN_FRAME_BYTES: int = 1
MAX_FRAME_BYTES: int = 2_097_152
MAX_FRAMES_PER_CLIP: int = 3_600
MAX_PAYLOAD_BYTES: int = 268_435_456  # 256 MiB
MAX_INDEX_LINE_BYTES: int = 512  # including the LF
MAX_INDEX_BYTES: int = 1_843_200
MAX_MANIFEST_BYTES: int = 16_384
MAX_ACTIVE_BYTES: int = 16_384

JPEG_SOI: bytes = b"\xff\xd8"
JPEG_EOI: bytes = b"\xff\xd9"

CLOCK_SOURCES: tuple[str, ...] = ("unknown", "phone", "sntp")
CLOSE_REASONS: tuple[str, ...] = (
    "duration",
    "size",
    "settings",
    "clock_change",
    "shutdown",
    "storage_fault",
    "recovery",
    "ota",
)

CLIP_FILE_NAMES: tuple[str, ...] = ("video.mjpg", "frames.jsonl")
MANIFEST_NAME: str = "manifest.json"
ACTIVE_NAME: str = "active.json"
CHECKSUMS_NAME: str = "checksums.json"
PART_SUFFIX: str = ".part"

# --- API bounds (interfaces.md §1, §4, §6, §8) ------------------------------
API_VERSION: int = 1
MAX_CONTROL_BODY_BYTES: int = 16 * 1024  # control request bodies ≤16 KiB
MAX_UPLOAD_INIT_BODY_BYTES: int = 32 * 1024  # backend upload init exception
MAX_CHUNK_BYTES: int = 1_048_576  # PATCH chunk body
MIN_CHUNK_BYTES: int = 1
MAX_CURSOR_CHARS: int = 256
MAX_PAGE_LIMIT: int = 100
DEVICE_PAGE_DEFAULT: int = 50
BACKEND_PAGE_DEFAULT: int = 100
DEVICE_LEASE_DEFAULT_S: int = 300
DEVICE_MAX_CLIP_LEASES: int = 2
DEVICE_MAX_DOWNLOADING_CLIENTS: int = 1
UPLOAD_EXPIRY_S: int = 86_400
MAX_EVENT_CLIPS: int = 10
MIN_EVENT_CLIPS: int = 1
MAX_EVENT_LABEL_CHARS: int = 120
MAX_PROTECTED_BYTES: int = 2_000_000_000

# The status set the contract may use for a refusal. interfaces.md §1 lists the
# generic set and the file-conditional section additionally assigns 412
# CONTENT_CHANGED, so 412 belongs here too. ``check_openapi`` refuses any operation
# that documents a status outside this set plus its own 2xx codes.
DOCUMENTED_ERROR_STATUSES: frozenset[int] = frozenset(
    {400, 401, 403, 404, 409, 410, 412, 413, 416, 422, 429, 503}
)

# --- Golden fixture synthesis -------------------------------------------------
# Fixture JPEGs are 64x64 grayscale: the smallest size that still exercises SOF
# parsing, real Huffman-coded entropy data and a non-trivial CRC/SHA pair.
FIXTURE_FRAME_WIDTH: int = 64
FIXTURE_FRAME_HEIGHT: int = 64
FIXTURE_JPEG_QUALITY: int = 40
FIXTURE_NOMINAL_FPS: int = 15
