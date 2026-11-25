"""Deterministic tiny JPEG synthesis and minimal JPEG marker parsing.

Fixture JPEGs must be real entropy-coded JPEG images: marker checks alone are not
sufficient validation (media-format.md §3), so the fixtures exercise an actual
decoder and the generator must reproduce identical bytes on every run.

Determinism comes from three things only: the seed string, the requested
dimensions and :data:`tools.contracts.bounds.FIXTURE_JPEG_QUALITY`. There is no
clock, no locale and no filesystem input, so regeneration is byte-identical for a
pinned Pillow version.
"""

from __future__ import annotations

import hashlib
import io
from typing import Final

from PIL import Image

from .bounds import FIXTURE_JPEG_QUALITY, JPEG_EOI, JPEG_SOI

#: The standalone marker bytes of the two end markers, derived from the same
#: ``bounds.py`` constants the validator compares payloads against.
SOI_MARKER: Final[int] = JPEG_SOI[-1]
EOI_MARKER: Final[int] = JPEG_EOI[-1]

#: Markers that introduce a start-of-frame segment: ``0xC0``-``0xCF`` minus DHT
#: (``0xC4``), JPG (``0xC8``) and DAC (``0xCC``).
SOF_MARKERS: Final[frozenset[int]] = frozenset(
    marker for marker in range(0xC0, 0xD0) if marker not in {0xC4, 0xC8, 0xCC}
)

_MARKER_SEGMENT_LENGTH = 2

#: The codes that, seen after an ``FF`` inside a scan, are structure rather than
#: entropy-coded data: the stuffed byte, the restart range, and the table, definition
#: and start-of-scan segments a multi-scan image carries between scans (DHT ``0xC4``,
#: DAC ``0xCC``, DNL ``0xDC``, SOS ``0xDA``), together with the comment (COM ``0xFE``)
#: and application (APPn ``0xE0``-``0xEF``) segments an encoder may place at the same
#: boundaries — all of them read by their length as the scan continues, per T.81
#: §§B.2.1/B.2.4, so a payload of one that embeds marker-like bytes is never mistaken
#: for the scan itself. Every other code inside a scan is data — including ``01``,
#: which is a standalone marker in a header but an un-stuffed byte in entropy data.
#: This is the scan half of the walk only: :func:`sof_dimensions` stops at the first
#: SOF and never reads scan data at all.
_IN_SCAN_MARKER_CODES: Final[frozenset[int]] = frozenset(
    {
        0x00,
        0xC4,
        0xCC,
        0xDC,
        0xDA,
        0xFE,
        SOI_MARKER,
        EOI_MARKER,
        *range(0xD0, 0xD8),
        *range(0xE0, 0xF0),
    }
)


class JpegStructureError(ValueError):
    """Raised when a byte string is not a walkable JPEG marker sequence."""


def jpeg_seed(*parts: object) -> str:
    """Stable textual seed for one fixture frame; identical inputs give one image."""
    return "|".join(str(part) for part in parts)


def _synth_image(width: int, height: int, seed: str) -> Image.Image:
    """Build the deterministic grayscale image every fixture JPEG encodes.

    The pixel pattern is derived from ``sha256(seed)`` only: a smooth diagonal
    gradient keeps the file small while four hash-derived rectangles make every
    seed produce a distinct Huffman-coded bitstream, so distinct frames give
    distinct CRC-32 and SHA-256 values instead of synthetic duplicates.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    pixels = bytearray(width * height)
    span = max(width + height - 2, 1)
    for y in range(height):
        row = y * width
        for x in range(width):
            # Smooth base so the encoder has real DC prediction work to do.
            base = ((x + y) * 255) // span
            pixels[row + x] = base & 0xFF

    # Hash-derived rectangles: visible, seed-dependent structure.
    blocks = 4
    for block in range(blocks):
        corner_x = digest[block * 4] % max(width - 1, 1)
        corner_y = digest[block * 4 + 1] % max(height - 1, 1)
        block_w = 1 + digest[block * 4 + 2] % max(min(width, height) // 2, 1)
        block_h = 1 + digest[block * 4 + 3] % max(min(height, width) // 2, 1)
        level = 32 + (digest[block * 8 + 4] % 224)
        for y in range(corner_y, min(corner_y + block_h, height)):
            row = y * width
            for x in range(corner_x, min(corner_x + block_w, width)):
                pixels[row + x] = level

    return Image.frombytes("L", (width, height), bytes(pixels))


def make_jpeg(width: int, height: int, seed: str, *, quality: int = FIXTURE_JPEG_QUALITY) -> bytes:
    """Return one deterministic 8-bit grayscale JPEG of ``width`` x ``height``.

    The pixels come from :func:`_synth_image`, so the same seed, dimensions and
    quality always encode the same file — the encoder adds no clock, locale or
    filesystem input of its own.
    """
    stream = io.BytesIO()
    _synth_image(width, height, seed).save(
        stream, format="JPEG", quality=quality, optimize=True, progressive=False
    )
    return stream.getvalue()


def make_progressive_jpeg(
    width: int, height: int, seed: str, *, quality: int = FIXTURE_JPEG_QUALITY
) -> bytes:
    """Return one deterministic progressive JPEG whose seed-derived comments sit between scans.

    The same :func:`_synth_image` pixels are saved with ``progressive=True``, and one
    COM segment is then inserted immediately before every structural SOS after the
    first, located by a marker-chain walk — never a naive byte search, because scan
    data can hide anything. The seed-derived COM payload embeds the marker bytes
    ``FF D9`` and ``FF D8``: an in-scan comment is structure read by its length
    (T.81 §§B.2.1/B.2.4), and these are exactly the bytes a walk that mistook it for
    scan data would stop on. The helper raises instead of shipping a vacuous fixture:
    fewer than two SOS markers, an insertion that did not land, or a file that does
    not end exactly at its first EOI are generation failures, not silent passes.
    """
    stream = io.BytesIO()
    _synth_image(width, height, seed).save(
        stream, format="JPEG", quality=quality, optimize=True, progressive=True
    )
    data = stream.getvalue()
    scans = _structural_scan_offsets(data)
    if len(scans) < 2:
        raise JpegStructureError(
            f"progressive synthesis produced {len(scans)} SOS markers; a fixture needs"
            " at least two scans for a comment to sit between"
        )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    comment = b"\xff\xd9" + digest[:12] + b"\xff\xd8" + digest[12:24]
    segment = b"\xff\xfe" + (len(comment) + _MARKER_SEGMENT_LENGTH).to_bytes(2, "big") + comment
    for offset in reversed(scans[1:]):
        data = data[:offset] + segment + data[offset:]
    for offset in _structural_scan_offsets(data)[1:]:
        if data[offset - len(segment) : offset] != segment:
            raise JpegStructureError("a comment segment failed to land before its scan")
    if first_image_end_offset(data) + 2 != len(data):
        raise JpegStructureError("the progressive image does not end at its first EOI")
    return data


def sof_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return ``(width, height)`` from the first SOF segment, or ``None``.

    Walks the marker chain instead of scanning for a signature, so a payload that
    merely contains SOF-looking bytes inside entropy data is not mistaken for a
    header. Returns ``None`` when the marker chain ends before any SOF.
    """
    if not data.startswith(JPEG_SOI):
        raise JpegStructureError("payload does not start with SOI")
    pos = 2
    end = len(data)
    while pos < end:
        if data[pos] != 0xFF:
            raise JpegStructureError(f"expected marker prefix at offset {pos}")
        # Fill bytes (0xFF) may precede a marker.
        while pos < end and data[pos] == 0xFF:
            pos += 1
        if pos >= end:
            raise JpegStructureError("truncated marker sequence")
        marker = data[pos]
        pos += 1
        if marker == 0x00 or marker == SOI_MARKER or 0xD0 <= marker <= 0xD7:
            continue  # standalone markers carry no segment length
        if marker == EOI_MARKER:
            return None  # EOI before any SOF
        if pos + _MARKER_SEGMENT_LENGTH > end:
            raise JpegStructureError("segment length field truncated")
        length = int.from_bytes(data[pos : pos + _MARKER_SEGMENT_LENGTH], "big")
        if length < _MARKER_SEGMENT_LENGTH:
            raise JpegStructureError(f"invalid segment length {length}")
        segment_end = pos + length
        if segment_end > end:
            raise JpegStructureError("segment extends past the payload")
        if marker in SOF_MARKERS:
            if length < 8:
                raise JpegStructureError("SOF segment too short")
            height = int.from_bytes(data[pos + 3 : pos + 5], "big")
            width = int.from_bytes(data[pos + 5 : pos + 7], "big")
            return width, height
        pos = segment_end
    return None


def first_image_end_offset(data: bytes) -> int:
    """Return the offset of the marker that ends the first image in ``data``.

    Walks the marker chain structurally like :func:`sof_dimensions` — fill bytes,
    standalone markers (``00``, ``01``, ``D0``-``D7``), variable-length segments read
    by their length field — and then, once a scan (``DA``) has been opened, walks the
    entropy-coded data as a scan: ``FF00`` is a stuffed byte, ``D0``-``D7`` are restart
    markers, and ``C4``/``CC``/``DC``/``DA`` (DHT, DAC, DNL and the next SOS of a
    multi-scan image) are the segments a scan may legitimately be interrupted by, read
    by length as the scan continues. The first ``D9`` (EOI) ends the image. The
    returned offset is that of the ``FF`` starting the two-byte marker, so the first
    image is exactly ``data[: first_image_end_offset(data) + 2]``.

    A second ``D8`` (SOI) *inside scan data* means the first image ended early: the
    data cannot hold a well-formed image at all, so the walk returns that marker's
    offset for the caller to name rather than raising — a second JPEG concatenated
    behind the first, or spliced into the middle of one, is precisely what this offset
    exists to reveal. Any other structural failure (a truncated marker or segment)
    raises :class:`JpegStructureError`, as the other walks in this module do.
    """
    if not data.startswith(JPEG_SOI):
        raise JpegStructureError("payload does not start with SOI")
    pos = 2
    end = len(data)
    scanning = False
    while pos < end:
        if scanning and data[pos] != 0xFF:
            pos += 1  # entropy-coded data carries no structure to read
            continue
        if data[pos] != 0xFF:
            raise JpegStructureError(f"expected marker prefix at offset {pos}")
        while pos < end and data[pos] == 0xFF:
            pos += 1  # fill bytes may precede a marker
        if pos >= end:
            raise JpegStructureError("truncated marker sequence")
        marker = data[pos]
        if scanning and marker not in _IN_SCAN_MARKER_CODES:
            pos += 1  # entropy-coded data that merely looks like a marker prefix
            continue
        if scanning:
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                pos += 1  # stuffed byte or restart: the scan continues
                continue
            if marker == EOI_MARKER:
                return pos - 1  # the FF starting this EOI is the image's last byte
            if marker == SOI_MARKER:
                return pos - 1  # a new image is starting: this one ended early
        pos += 1
        if marker == 0x00 or marker == 0x01 or marker == SOI_MARKER or 0xD0 <= marker <= 0xD7:
            continue  # standalone markers carry no segment length
        if marker == EOI_MARKER:
            return pos - 2  # EOI before any scan: the image ends here
        if pos + _MARKER_SEGMENT_LENGTH > end:
            raise JpegStructureError("segment length field truncated")
        length = int.from_bytes(data[pos : pos + _MARKER_SEGMENT_LENGTH], "big")
        if length < _MARKER_SEGMENT_LENGTH:
            raise JpegStructureError(f"invalid segment length {length}")
        segment_end = pos + length
        if segment_end > end:
            raise JpegStructureError("segment extends past the payload")
        if marker == 0xDA:  # SOS: everything after the header is scan data
            scanning = True
        pos = segment_end
    raise JpegStructureError("marker sequence ends before any EOI")


def _structural_scan_offsets(data: bytes) -> list[int]:
    """Return, in order, the offset of the ``FF`` starting every SOS in the marker chain.

    Walks the chain structurally like :func:`first_image_end_offset` — the in-scan codes
    consume their segments by length, everything else inside a scan is data — and records
    each SOS whether it opened the first scan or reopened the scan as a multi-scan image
    continued. Reaching EOI ends the walk; a second SOI inside a scan, or any truncated
    marker or segment, raises :class:`JpegStructureError` — this walk reads a generator's
    own bytes, where a broken chain is a synthesis bug rather than a reported finding.
    """
    if not data.startswith(JPEG_SOI):
        raise JpegStructureError("payload does not start with SOI")
    pos = 2
    end = len(data)
    scanning = False
    scans: list[int] = []
    while pos < end:
        if scanning and data[pos] != 0xFF:
            pos += 1  # entropy-coded data carries no structure to read
            continue
        if data[pos] != 0xFF:
            raise JpegStructureError(f"expected marker prefix at offset {pos}")
        marker_start = pos
        while pos < end and data[pos] == 0xFF:
            pos += 1  # fill bytes may precede a marker
        if pos >= end:
            raise JpegStructureError("truncated marker sequence")
        marker = data[pos]
        if scanning and marker not in _IN_SCAN_MARKER_CODES:
            pos += 1  # entropy-coded data that merely looks like a marker prefix
            continue
        if scanning:
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                pos += 1  # stuffed byte or restart: the scan continues
                continue
            if marker == EOI_MARKER:
                return scans  # the image ends here
            if marker == SOI_MARKER:
                raise JpegStructureError("a second SOI interrupted the scan")
        pos += 1
        if marker == 0x00 or marker == 0x01 or marker == SOI_MARKER or 0xD0 <= marker <= 0xD7:
            continue  # standalone markers carry no segment length
        if marker == EOI_MARKER:
            return scans  # EOI before any scan: the walk is over
        if pos + _MARKER_SEGMENT_LENGTH > end:
            raise JpegStructureError("segment length field truncated")
        length = int.from_bytes(data[pos : pos + _MARKER_SEGMENT_LENGTH], "big")
        if length < _MARKER_SEGMENT_LENGTH:
            raise JpegStructureError(f"invalid segment length {length}")
        segment_end = pos + length
        if segment_end > end:
            raise JpegStructureError("segment extends past the payload")
        if marker == 0xDA:
            scans.append(marker_start)
            scanning = True
        pos = segment_end
    raise JpegStructureError("marker sequence ends before any EOI")


def decode_size(data: bytes) -> tuple[int, int]:
    """Decode with Pillow and return ``(width, height)``.

    Marker checks alone are not sufficient validation (media-format.md §3), so this
    is a real entropy decode. Raises :class:`JpegStructureError` when the image will
    not decode at all.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return int(image.width), int(image.height)
    except Exception as error:  # Pillow raises many decoder-specific types
        raise JpegStructureError(str(error)) from error
