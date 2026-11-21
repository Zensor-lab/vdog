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


class JpegStructureError(ValueError):
    """Raised when a byte string is not a walkable JPEG marker sequence."""


def jpeg_seed(*parts: object) -> str:
    """Stable textual seed for one fixture frame; identical inputs give one image."""
    return "|".join(str(part) for part in parts)


def make_jpeg(width: int, height: int, seed: str, *, quality: int = FIXTURE_JPEG_QUALITY) -> bytes:
    """Return one deterministic 8-bit grayscale JPEG of ``width`` x ``height``.

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

    image = Image.frombytes("L", (width, height), bytes(pixels))
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=quality, optimize=True, progressive=False)
    return stream.getvalue()


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
