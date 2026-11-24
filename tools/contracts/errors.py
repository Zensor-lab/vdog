"""Stable validator error codes.

A code is a public, frozen name: golden fixtures declare the codes they must
produce, so renaming or repurposing a code is a contract change. ``CODES`` is the
single registry; ``tools/contracts/tests/test_error_codes.py`` asserts every code
emitted anywhere in the package is registered here and that every registered code
is exercised by at least one invalid fixture or unit test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    """One validator finding: a stable code plus a precise location and detail."""

    code: str
    location: str
    detail: str = ""

    def render(self) -> str:
        """Stable one-line rendering used by both the CLI and the tests."""
        if not self.detail:
            return f"{self.code}: {self.location}"
        return f"{self.code}: {self.location}: {self.detail}"


# --- Index line / frame record -------------------------------------------------
FRAME_LINE_TOO_LONG = "FRAME_LINE_TOO_LONG"
FRAME_LINE_MALFORMED = "FRAME_LINE_MALFORMED"
FRAME_LINE_NOT_OBJECT = "FRAME_LINE_NOT_OBJECT"
FRAME_SCHEMA = "FRAME_SCHEMA"
FRAME_SIZE_INVALID = "FRAME_SIZE_INVALID"
NOMINAL_FPS_INVALID = "NOMINAL_FPS_INVALID"
FRAME_SEQ_NOT_CONSECUTIVE = "FRAME_SEQ_NOT_CONSECUTIVE"
FRAME_T_US_FIRST_NOT_ZERO = "FRAME_T_US_FIRST_NOT_ZERO"
FRAME_T_US_DUPLICATE = "FRAME_T_US_DUPLICATE"
FRAME_T_US_NOT_INCREASING = "FRAME_T_US_NOT_INCREASING"
FRAME_T_US_TOO_LARGE = "FRAME_T_US_TOO_LARGE"
FRAME_CRC_MISMATCH = "FRAME_CRC_MISMATCH"
FRAME_COUNT_MISMATCH = "FRAME_COUNT_MISMATCH"
FRAME_SCHEMA_MISSING_FIELD = "FRAME_SCHEMA_MISSING_FIELD"

# --- Payload and offset arithmetic --------------------------------------------
OFFSET_ARITHMETIC_OVERFLOW = "OFFSET_ARITHMETIC_OVERFLOW"
OFFSET_NOT_CONTIGUOUS = "OFFSET_NOT_CONTIGUOUS"
OFFSET_EXCEEDS_PAYLOAD = "OFFSET_EXCEEDS_PAYLOAD"
PAYLOAD_TRAILING_BYTES = "PAYLOAD_TRAILING_BYTES"
PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
INDEX_TRUNCATED = "INDEX_TRUNCATED"
INDEX_ENCODING_INVALID = "INDEX_ENCODING_INVALID"
INDEX_TOO_LARGE = "INDEX_TOO_LARGE"
INDEX_EMPTY = "INDEX_EMPTY"

# --- JPEG ---------------------------------------------------------------------
JPEG_SOI_MISSING = "JPEG_SOI_MISSING"
JPEG_EOI_MISSING = "JPEG_EOI_MISSING"
# The decoder cannot read the slice, and, with a detail that begins "marker chain to
# EOI:", the structural walk of :func:`tools.contracts.jpeg.first_image_end_offset`
# could not finish it either. Both are the same claim — the bytes do not hold the image
# the record indexes — and neither lets the validator name trailing bytes it never
# located, which is JPEG_TRAILING_DATA's alone.
JPEG_DECODE_FAILED = "JPEG_DECODE_FAILED"
JPEG_SOF_DIMENSION_MISMATCH = "JPEG_SOF_DIMENSION_MISMATCH"
# The indexed slice runs past the first image's EOI: media-format.md §3 says each
# record starts where the preceding one ends and the final one ends at the exact
# file size, so one indexed slice is exactly one JPEG — the decoder reads only the
# first image, and the bytes beside it are frame data no record or playback time
# will ever reach.
JPEG_TRAILING_DATA = "JPEG_TRAILING_DATA"

# --- Manifest / active record -------------------------------------------------
MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
MANIFEST_SCHEMA = "MANIFEST_SCHEMA"
MANIFEST_SCHEMA_MISSING_FIELD = "MANIFEST_SCHEMA_MISSING_FIELD"
MANIFEST_JSON_INVALID = "MANIFEST_JSON_INVALID"
MANIFEST_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
MANIFEST_SIZE_MISMATCH = "MANIFEST_SIZE_MISMATCH"
ACTIVE_TOO_LARGE = "ACTIVE_TOO_LARGE"
ACTIVE_SCHEMA = "ACTIVE_SCHEMA"
ACTIVE_JSON_INVALID = "ACTIVE_JSON_INVALID"
ACTIVE_WITH_MANIFEST = "ACTIVE_WITH_MANIFEST"
CHECKSUMS_SCHEMA = "CHECKSUMS_SCHEMA"
CHECKSUM_HASH_MISMATCH = "CHECKSUM_HASH_MISMATCH"
CHECKSUM_SIZE_MISMATCH = "CHECKSUM_SIZE_MISMATCH"
CLIP_FILE_UNEXPECTED = "CLIP_FILE_UNEXPECTED"

# --- Identity, clock, duration, version ---------------------------------------
ID_SYNTAX_INVALID = "ID_SYNTAX_INVALID"
CLIP_BOOT_PREFIX_MISMATCH = "CLIP_BOOT_PREFIX_MISMATCH"
VERSION_UNSUPPORTED = "VERSION_UNSUPPORTED"
CLOCK_NULLITY_MISMATCH = "CLOCK_NULLITY_MISMATCH"
CLOCK_TIMESTAMP_INVALID = "CLOCK_TIMESTAMP_INVALID"
CLOCK_SOURCE_UNKNOWN_VALUE = "CLOCK_SOURCE_UNKNOWN_VALUE"
DURATION_LE_FINAL_T_US = "DURATION_LE_FINAL_T_US"
DURATION_TOO_LONG = "DURATION_TOO_LONG"
# media-format.md §4 fixes a recovered segment's close time: last frame time plus
# one nominal frame period, clamped to the maximum duration. A measured close is
# not available across a reset, so a recovered manifest whose duration is any
# other number states a playback end the format cannot have produced.
DURATION_RECOVERED_MISMATCH = "DURATION_RECOVERED_MISMATCH"
DIMENSIONS_EXCEEDED = "DIMENSIONS_EXCEEDED"
CLOSE_REASON_UNKNOWN = "CLOSE_REASON_UNKNOWN"
RECOVERED_CLOSE_REASON_DISAGREE = "RECOVERED_CLOSE_REASON_DISAGREE"

# --- Fixture corpus ------------------------------------------------------------
FIXTURE_INDEX_INVALID = "FIXTURE_INDEX_INVALID"
FIXTURE_FILE_MISSING = "FIXTURE_FILE_MISSING"
FIXTURE_UNREFERENCED = "FIXTURE_UNREFERENCED"
FIXTURE_DUPLICATE = "FIXTURE_DUPLICATE"
FIXTURE_EXPECTED_PASS = "FIXTURE_EXPECTED_PASS"
FIXTURE_UNEXPECTED_CODE = "FIXTURE_UNEXPECTED_CODE"
FIXTURE_MISSING_CODE = "FIXTURE_MISSING_CODE"
GENERATOR_DRIFT = "GENERATOR_DRIFT"

# --- Contract documents --------------------------------------------------------
SCHEMA_DOCUMENT_INVALID = "SCHEMA_DOCUMENT_INVALID"
SPEC_PARSE_FAILED = "SPEC_PARSE_FAILED"
SPEC_STRUCTURE_MISSING = "SPEC_STRUCTURE_MISSING"
SPEC_COMPONENT_DRIFT = "SPEC_COMPONENT_DRIFT"
SPEC_STATUS_MISSING = "SPEC_STATUS_MISSING"
SPEC_STATUS_UNDOCUMENTED = "SPEC_STATUS_UNDOCUMENTED"
SPEC_STATUS_NOT_ALLOWED = "SPEC_STATUS_NOT_ALLOWED"
SPEC_SECURITY_MISSING = "SPEC_SECURITY_MISSING"
OTA_SCHEMA_PRESENT = "OTA_SCHEMA_PRESENT"
OTA_DEFERRAL_MISSING = "OTA_DEFERRAL_MISSING"

# --- API fixtures --------------------------------------------------------------
API_SCHEMA = "API_SCHEMA"
API_SCHEMA_MISSING_FIELD = "API_SCHEMA_MISSING_FIELD"
API_VERSION_MISSING = "API_VERSION_MISSING"
API_VERSION_UNSUPPORTED = "API_VERSION_UNSUPPORTED"
API_BODY_TOO_LARGE = "API_BODY_TOO_LARGE"
API_DIRECTION_MISMATCH = "API_DIRECTION_MISMATCH"
ERROR_ENVELOPE_INVALID = "ERROR_ENVELOPE_INVALID"
ERROR_CODE_UNDOCUMENTED = "ERROR_CODE_UNDOCUMENTED"
API_STATUS_UNDOCUMENTED = "API_STATUS_UNDOCUMENTED"
API_OPERATION_UNKNOWN = "API_OPERATION_UNKNOWN"

# --- Media/base64 binding, uploads, ranges and headers -------------------------
BASE64URL_ALPHABET_INVALID = "BASE64URL_ALPHABET_INVALID"
BASE64URL_LENGTH_INVALID = "BASE64URL_LENGTH_INVALID"
MANIFEST_DECODED_TOO_LARGE = "MANIFEST_DECODED_TOO_LARGE"
MANIFEST_JSON_INVALID_DECODED = "MANIFEST_JSON_INVALID_DECODED"
MANIFEST_DECODED_SCHEMA = "MANIFEST_DECODED_SCHEMA"
CURSOR_TOO_LONG = "CURSOR_TOO_LONG"
PAGE_LIMIT_INVALID = "PAGE_LIMIT_INVALID"
FILE_NAME_NOT_ALLOWED = "FILE_NAME_NOT_ALLOWED"
UPLOAD_OFFSET_INVALID = "UPLOAD_OFFSET_INVALID"
UPLOAD_LENGTH_INVALID = "UPLOAD_LENGTH_INVALID"
UPLOAD_CHECKSUM_SYNTAX = "UPLOAD_CHECKSUM_SYNTAX"
CHUNK_SIZE_INVALID = "CHUNK_SIZE_INVALID"
CONTENT_RANGE_INVALID = "CONTENT_RANGE_INVALID"
CONTENT_LENGTH_MISMATCH = "CONTENT_LENGTH_MISMATCH"
ETAG_INVALID = "ETAG_INVALID"
ACCEPT_RANGES_INVALID = "ACCEPT_RANGES_INVALID"
HEADER_MISSING = "HEADER_MISSING"
HEADER_INVALID = "HEADER_INVALID"
RANGE_MULTI_NOT_ALLOWED = "RANGE_MULTI_NOT_ALLOWED"
# The `If-Match` of a resume that is not the ETag of the answer it accompanies: the
# required refusal is 412 CONTENT_CHANGED (interfaces.md §4, RFC 9110 §13.2.2), so a
# grant that carries both is the violation.
IF_MATCH_ETAG_DISAGREE = "IF_MATCH_ETAG_DISAGREE"
# A chunk whose committed bytes hash differently than its well-formed Upload-Checksum
# declares: the required refusal is 422 INTEGRITY_FAILURE (interfaces.md §8), so the
# header's claim about these exact bytes is what fails here, not its spelling.
CHUNK_HASH_MISMATCH = "CHUNK_HASH_MISMATCH"

#: Every validator code, registered explicitly so that adding a constant without
#: registering it is a test failure rather than a silently unknown code.
CODES: frozenset[str] = frozenset(
    (
        # index line / frame record
        FRAME_LINE_TOO_LONG,
        FRAME_LINE_MALFORMED,
        FRAME_LINE_NOT_OBJECT,
        FRAME_SCHEMA,
        FRAME_SCHEMA_MISSING_FIELD,
        FRAME_SIZE_INVALID,
        NOMINAL_FPS_INVALID,
        FRAME_SEQ_NOT_CONSECUTIVE,
        FRAME_T_US_FIRST_NOT_ZERO,
        FRAME_T_US_DUPLICATE,
        FRAME_T_US_NOT_INCREASING,
        FRAME_T_US_TOO_LARGE,
        FRAME_CRC_MISMATCH,
        FRAME_COUNT_MISMATCH,
        # payload and offset arithmetic
        OFFSET_ARITHMETIC_OVERFLOW,
        OFFSET_NOT_CONTIGUOUS,
        OFFSET_EXCEEDS_PAYLOAD,
        PAYLOAD_TRAILING_BYTES,
        PAYLOAD_TOO_LARGE,
        INDEX_TRUNCATED,
        INDEX_ENCODING_INVALID,
        INDEX_TOO_LARGE,
        INDEX_EMPTY,
        # jpeg
        JPEG_SOI_MISSING,
        JPEG_EOI_MISSING,
        JPEG_DECODE_FAILED,
        JPEG_SOF_DIMENSION_MISMATCH,
        JPEG_TRAILING_DATA,
        # manifest / active record
        MANIFEST_MISSING,
        MANIFEST_TOO_LARGE,
        MANIFEST_SCHEMA,
        MANIFEST_SCHEMA_MISSING_FIELD,
        MANIFEST_JSON_INVALID,
        MANIFEST_HASH_MISMATCH,
        MANIFEST_SIZE_MISMATCH,
        ACTIVE_TOO_LARGE,
        ACTIVE_SCHEMA,
        ACTIVE_JSON_INVALID,
        ACTIVE_WITH_MANIFEST,
        CHECKSUMS_SCHEMA,
        CHECKSUM_HASH_MISMATCH,
        CHECKSUM_SIZE_MISMATCH,
        CLIP_FILE_UNEXPECTED,
        # identity, clock, duration, version
        ID_SYNTAX_INVALID,
        CLIP_BOOT_PREFIX_MISMATCH,
        VERSION_UNSUPPORTED,
        CLOCK_NULLITY_MISMATCH,
        CLOCK_TIMESTAMP_INVALID,
        CLOCK_SOURCE_UNKNOWN_VALUE,
        DURATION_LE_FINAL_T_US,
        DURATION_TOO_LONG,
        DURATION_RECOVERED_MISMATCH,
        DIMENSIONS_EXCEEDED,
        CLOSE_REASON_UNKNOWN,
        RECOVERED_CLOSE_REASON_DISAGREE,
        # fixture corpus
        FIXTURE_INDEX_INVALID,
        FIXTURE_FILE_MISSING,
        FIXTURE_UNREFERENCED,
        FIXTURE_DUPLICATE,
        FIXTURE_EXPECTED_PASS,
        FIXTURE_UNEXPECTED_CODE,
        FIXTURE_MISSING_CODE,
        GENERATOR_DRIFT,
        # contract documents
        SCHEMA_DOCUMENT_INVALID,
        SPEC_PARSE_FAILED,
        SPEC_STRUCTURE_MISSING,
        SPEC_COMPONENT_DRIFT,
        SPEC_STATUS_MISSING,
        SPEC_STATUS_UNDOCUMENTED,
        SPEC_STATUS_NOT_ALLOWED,
        SPEC_SECURITY_MISSING,
        OTA_SCHEMA_PRESENT,
        OTA_DEFERRAL_MISSING,
        # api fixtures
        API_SCHEMA,
        API_SCHEMA_MISSING_FIELD,
        API_VERSION_MISSING,
        API_VERSION_UNSUPPORTED,
        API_BODY_TOO_LARGE,
        API_DIRECTION_MISMATCH,
        ERROR_ENVELOPE_INVALID,
        ERROR_CODE_UNDOCUMENTED,
        API_STATUS_UNDOCUMENTED,
        API_OPERATION_UNKNOWN,
        # uploads, ranges, headers, base64 binding
        BASE64URL_ALPHABET_INVALID,
        BASE64URL_LENGTH_INVALID,
        MANIFEST_DECODED_TOO_LARGE,
        MANIFEST_JSON_INVALID_DECODED,
        MANIFEST_DECODED_SCHEMA,
        CURSOR_TOO_LONG,
        PAGE_LIMIT_INVALID,
        FILE_NAME_NOT_ALLOWED,
        UPLOAD_OFFSET_INVALID,
        UPLOAD_LENGTH_INVALID,
        UPLOAD_CHECKSUM_SYNTAX,
        CHUNK_SIZE_INVALID,
        CONTENT_RANGE_INVALID,
        CONTENT_LENGTH_MISMATCH,
        ETAG_INVALID,
        ACCEPT_RANGES_INVALID,
        HEADER_MISSING,
        HEADER_INVALID,
        RANGE_MULTI_NOT_ALLOWED,
        IF_MATCH_ETAG_DISAGREE,
        CHUNK_HASH_MISMATCH,
    )
)
