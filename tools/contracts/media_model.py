"""Typed model of one original-recording segment and its canonical serialization.

The generator and the validator share this module for *serialization* only (key
order, compact separators, LF framing, the ``checksums.json`` shape) so committed
fixtures are byte-stable. Every integrity value is recomputed from bytes by the
validator; nothing serialized here is trusted as evidence.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from .bounds import (
    ACTIVE_NAME,
    CHECKSUMS_NAME,
    CLIP_FILE_NAMES,
    MANIFEST_NAME,
    MEDIA_VERSION,
    PART_SUFFIX,
)

#: Key order of a frame index line, matching the normative example in
#: media-format.md §3 so committed JSONL stays byte-stable and diff-friendly.
FRAME_RECORD_KEYS: Final[tuple[str, ...]] = ("v", "seq", "offset", "size", "t_us", "crc32")


@dataclass(frozen=True)
class ProfilePlan:
    """Recording profile: bounded dimensions, nominal fps, driver quality."""

    width: int
    height: int
    nominal_fps: int
    jpeg_quality: int


@dataclass(frozen=True)
class ClockPlan:
    """Clock mapping of a segment.

    ``unknown`` requires both ``start_utc`` and ``uncertainty_ms`` to be ``None``;
    ``phone``/``sntp`` require both to be set. The validator enforces the pairing
    so a violation reports one stable code instead of a schema cascade.
    """

    source: str
    start_utc: str | None
    uncertainty_ms: int | None


@dataclass(frozen=True)
class FramePlan:
    """One retained frame: capture time plus the seed that produces its JPEG."""

    t_us: int
    jpeg_key: str


@dataclass(frozen=True)
class ClipPlan:
    """Everything needed to synthesize one segment deterministically."""

    device_id: str
    boot_id: str
    sequence: int
    capture_order: int
    firmware_version: str
    hardware_revision: str
    profile: ProfilePlan
    clock: ClockPlan
    start_boot_us: int
    frames: tuple[FramePlan, ...]
    duration_us: int
    close_reason: str = "duration"
    recovered: bool = False
    dropped_frames: int = 0

    @property
    def clip_id(self) -> str:
        return f"{self.boot_id}-{self.sequence:08x}"


@dataclass
class BuiltClip:
    """Serialized segment bytes plus the records that describe them.

    ``active=True`` models an interrupted segment: the two payload files carry the
    ``.part`` suffix and only ``active.json`` is published, per media-format.md §5.
    """

    payload: bytes
    index: bytes
    manifest: dict[str, Any] | None = None
    active: dict[str, Any] | None = None
    checksums: dict[str, Any] | None = None
    active_state: bool = False

    @property
    def payload_name(self) -> str:
        return CLIP_FILE_NAMES[0] + (PART_SUFFIX if self.active_state else "")

    @property
    def index_name(self) -> str:
        return CLIP_FILE_NAMES[1] + (PART_SUFFIX if self.active_state else "")

    def files(self) -> dict[str, bytes]:
        """Return the on-disk mapping ``file name -> exact bytes``."""
        out: dict[str, bytes] = {self.payload_name: self.payload, self.index_name: self.index}
        if self.active_state:
            if self.active is None:  # pragma: no cover - generator invariant
                raise ValueError("active segment requires an active.json record")
            out[ACTIVE_NAME] = dump_json(self.active)
        else:
            if self.manifest is None:  # pragma: no cover - generator invariant
                raise ValueError("finalized segment requires a manifest")
            out[MANIFEST_NAME] = dump_json(self.manifest)
        if self.checksums is not None:
            out[CHECKSUMS_NAME] = dump_json(self.checksums)
        return out

    def recompute_integrity(self) -> None:
        """Re-point the manifest/checksums at the current payload and index bytes.

        Used after a deliberate corruption so the fixture tests exactly one defect
        instead of cascading hash failures. An active segment only refreshes its
        checksums.
        """
        if self.manifest is not None:
            self.manifest["files"]["video.mjpg"] = {
                "bytes": len(self.payload),
                "sha256": sha256_hex(self.payload),
            }
            self.manifest["files"]["frames.jsonl"] = {
                "bytes": len(self.index),
                "sha256": sha256_hex(self.index),
            }
        if self.checksums is not None:
            # The sidecar covers the clip's files, and it is not one of them: hashing a
            # document that contains its own hash is undefined, so the refresh measures
            # the content files exactly as the original build did (which ran before
            # `checksums` existed and so could not list it either).
            content = {
                name: data for name, data in self.files().items() if name != CHECKSUMS_NAME
            }
            self.checksums = checksums_document(content)


def crc32_hex(data: bytes) -> str:
    """CRC-32/ISO-HDLC (the zlib CRC) as eight lowercase hexadecimal digits."""
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")


def sha256_hex(data: bytes) -> str:
    """SHA-256 over the exact bytes as 64 lowercase hexadecimal digits."""
    return hashlib.sha256(data).hexdigest()


def dump_json(document: Mapping[str, Any]) -> bytes:
    """Canonical compact JSON with one trailing LF: UTF-8, no BOM, no CR.

    ``allow_nan=False`` is part of the writer's contract, not a nicety: ``NaN`` and
    ``Infinity`` have no JSON notation (RFC 8259 §6), so a committed vector that
    carried one would be a wire value no conforming reader can parse. A non-finite
    float reaching this call is a generator bug, and refusing it here is what keeps
    the corpus free of them.
    """
    return (
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def frame_record_line(*, seq: int, offset: int, size: int, t_us: int, crc32: str) -> bytes:
    """Serialize exactly one index line, including its LF terminator."""
    record = {
        "v": MEDIA_VERSION,
        "seq": seq,
        "offset": offset,
        "size": size,
        "t_us": t_us,
        "crc32": crc32,
    }
    return dump_json(record)


def split_index_lines(index: bytes) -> list[tuple[bytes, bytes]]:
    """Split an index into ``(raw_line_with_terminator, line_body)`` pairs.

    The raw form keeps the terminator so the "at most 512 bytes including newline"
    bound is measured exactly as written. A trailing fragment with no terminator is
    returned with itself as the raw form, which is how a truncated index is detected.
    """
    lines: list[tuple[bytes, bytes]] = []
    parts = index.split(b"\n")
    for chunk in parts[:-1]:
        lines.append((chunk + b"\n", chunk))
    if parts[-1]:
        lines.append((parts[-1], parts[-1]))
    return lines


def build_index(frames: Sequence[bytes], t_us_values: Sequence[int]) -> bytes:
    """Build the index for concatenated JPEG frames, computing real CRCs.

    Records are laid out contiguously from offset zero, which is what a conforming
    writer must produce. The validator never trusts this output: it recomputes
    offsets, sizes and CRCs from the payload bytes.
    """
    if len(frames) != len(t_us_values):
        raise ValueError("frames and timestamps must be the same length")
    lines: list[bytes] = []
    offset = 0
    for seq, (frame, t_us) in enumerate(zip(frames, t_us_values)):
        lines.append(
            frame_record_line(
                seq=seq,
                offset=offset,
                size=len(frame),
                t_us=t_us,
                crc32=crc32_hex(frame),
            )
        )
        offset += len(frame)
    return b"".join(lines)


def manifest_document(plan: ClipPlan, payload: bytes, index: bytes) -> dict[str, Any]:
    """Build the completion manifest for one built segment."""
    return {
        "v": MEDIA_VERSION,
        "device_id": plan.device_id,
        "boot_id": plan.boot_id,
        "clip_id": plan.clip_id,
        "capture_order": plan.capture_order,
        "firmware_version": plan.firmware_version,
        "hardware_revision": plan.hardware_revision,
        "profile": _profile_document(plan.profile),
        "clock": _clock_document(plan.clock),
        "start_boot_us": plan.start_boot_us,
        "duration_us": plan.duration_us,
        "frame_count": len(plan.frames),
        "dropped_frames": plan.dropped_frames,
        "close_reason": plan.close_reason,
        "recovered": plan.recovered,
        "files": {
            CLIP_FILE_NAMES[0]: {"bytes": len(payload), "sha256": sha256_hex(payload)},
            CLIP_FILE_NAMES[1]: {"bytes": len(index), "sha256": sha256_hex(index)},
        },
    }


def active_document(plan: ClipPlan) -> dict[str, Any]:
    """Build the bounded active-state record for one in-progress segment."""
    return {
        "v": MEDIA_VERSION,
        "device_id": plan.device_id,
        "boot_id": plan.boot_id,
        "clip_id": plan.clip_id,
        "capture_order": plan.capture_order,
        "firmware_version": plan.firmware_version,
        "hardware_revision": plan.hardware_revision,
        "profile": _profile_document(plan.profile),
        "clock": _clock_document(plan.clock),
        "start_boot_us": plan.start_boot_us,
    }


def checksums_document(files: Mapping[str, bytes]) -> dict[str, Any]:
    """Build the harness ``checksums.json`` covering every committed clip file."""
    return {
        "v": MEDIA_VERSION,
        "files": {
            name: {"bytes": len(data), "sha256": sha256_hex(data)}
            for name, data in sorted(files.items())
        },
    }


def _profile_document(profile: ProfilePlan) -> dict[str, Any]:
    return {
        "width": profile.width,
        "height": profile.height,
        "nominal_fps": profile.nominal_fps,
        "jpeg_quality": profile.jpeg_quality,
    }


def _clock_document(clock: ClockPlan) -> dict[str, Any]:
    return {
        "source": clock.source,
        "start_utc": clock.start_utc,
        "uncertainty_ms": clock.uncertainty_ms,
    }
