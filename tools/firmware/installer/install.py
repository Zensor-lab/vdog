#!/usr/bin/env python3
"""vdog XIAO ESP32S3 Sense prebuilt-firmware installer (prototype bootstrap).

Stdlib-only single-file CLI shipped at the ZIP root, implementing the
contract in docs/plans/0.9-firmware-ci-release.md section 4:

  check    Validate the package/manifest/hashes locally; never opens a port.
  ports    Enumerate serial ports; no flashing, no automatic selection.
  plan     Print validated segments/actions; never opens a port.
  inspect  Explicit read-only chip/flash/security inspection; never writes.
  install  Explicit port + board; validates package and device, prints the
           exact write ranges and requires consent before any write.

Safety properties (CI-08 / CI-T08 / 0.9.5):
  * an explicit ``--port`` is always required for serial operations;
  * the chip must be esp32s3 and the flash the expected 8MB before any write;
  * the pinned esptool version is verified and never silently substituted;
  * writes go only to manifest-approved ranges matching the partition table;
  * there is no wiping, security-configuration, or override switch reachable
    from this CLI; nothing outside the four manifest image ranges is written;
  * NVS/SD contents are never written and provisioned/unknown devices are
    refused.

This file is intentionally self-contained (mirrors the rules in
tools/firmware/contract.py, whose tests cross-check these validators) so the
packaged ZIP needs nothing but a supported Python 3.12 runtime and the locked
installer dependencies for serial access.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Frozen contract constants (mirror of tools/firmware/contract.py, verified
# equal by tools/firmware/tests/test_install_cli.py).
# ---------------------------------------------------------------------------

ESPTOOL_VERSION = "5.4.0"
TARGET = "esp32s3"
CHIP_DISPLAY_RE = re.compile(r"Chip is ESP32-S3(?![0-9])", re.IGNORECASE)
HARDWARE_CLASS = "seeed-xiao-esp32s3-sense"
EXPECTED_FLASH_BYTES = 8_388_608
FLASH_MODE, FLASH_SIZE, FLASH_FREQ = "dio", "8MB", "80m"
FIRMWARE_VERSION = "0.2.0-proto"
RELEASE_CHANNEL = "prototype"
ENVIRONMENT = "vdog_xiao_sense_proto"
PRODUCT_SLUG = "vdog-xiao-sense"

IMAGE_ROLES = ("bootloader", "partition_table", "ota_data_initial", "application")
ROLE_FILES = {
    "bootloader": "images/bootloader.bin",
    "partition_table": "images/partitions.bin",
    "ota_data_initial": "images/ota_data_initial.bin",
    "application": "images/firmware.bin",
}
REQUIRED_FILES = frozenset(
    {
        "INSTALL.md",
        "RELEASE_NOTES.md",
        "VERSION.json",
        "manifest.json",
        "SHA256SUMS",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "images/bootloader.bin",
        "images/partitions.bin",
        "images/ota_data_initial.bin",
        "images/firmware.bin",
        "flash/partitions.csv",
        "flash/flash-layout.json",
        "flash/flash_args",
        "install.py",
        "install.sh",
        "install.ps1",
        "requirements-installer.lock",
    }
)
SELF_EXCLUDED = frozenset({"manifest.json", "SHA256SUMS"})

FULL_SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|local)\Z")
BUILD_ID_RE = re.compile(r"\A(?:pr-[0-9]{1,9}-[0-9a-f]{12}|main-[0-9a-f]{12}|local)\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
TAG_RE = re.compile(r"\Afirmware-main-[0-9a-f]{12}\Z")
PORT_RE = re.compile(r"\A[A-Za-z0-9._/:\-]{1,64}\Z")

ESP_IMAGE_MAGIC = 0xE9
ESP32S3_IMAGE_CHIP_ID = 0x09
APP_DESC_MAGIC = 0xABCD5432
BOOTLOADER_DESC_MAGIC = 0x50
PARTITION_ENTRY_MAGIC = 0x50AA  # on-disk bytes AA 50 (u16 little-endian)
PARTITION_ENTRY_SIZE = 32
PARTITION_TABLE_MAX_BYTES = 0xC00
OTA_DATA_MAGIC_BYTE = 0xC9

# Exit codes.
EXIT_OK = 0
EXIT_PACKAGE_INVALID = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_FLASH_FAILED = 4
EXIT_ENVIRONMENT = 5

CONNECT_TIMEOUT_SECONDS = 90
WRITE_TIMEOUT_SECONDS = 600
READ_TIMEOUT_SECONDS = 180
VERSION_TIMEOUT_SECONDS = 60


class InstallerError(Exception):
    def __init__(self, message: str, code: int = EXIT_REFUSED) -> None:
        super().__init__(message)
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Compact contract validators (stdlib-only; tools/firmware/tests keeps these
# in lockstep with tools/firmware/contract.py via shared fixture corpora)
# ---------------------------------------------------------------------------


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _path_ok(path: Any) -> bool:
    if not isinstance(path, str) or not path or len(path) > 255:
        return False
    if path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path):
        return False
    return all(seg not in ("", ".", "..") for seg in path.rstrip("/").split("/"))


def validate_manifest(data: Any) -> list[str]:
    """Structural manifest checks (firmware-release-v1)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["manifest.json: not an object"]
    known_manifest_fields = {
        "schema", "package_format_version", "product", "product_slug",
        "hardware_class", "board", "environment", "target",
        "expected_flash_bytes", "firmware_version", "release_channel",
        "hardware_verified", "recording_available", "device_ota_available",
        "source", "build_id", "tag", "ci", "toolchain", "flash", "images",
        "partition_table", "flash_layout_file", "files",
    }
    for field in data:
        if field not in known_manifest_fields:
            errors.append(f"manifest: unknown field {field!r}")
    consts = {
        "schema": "firmware-release-v1",
        "package_format_version": 1,
        "product": "vdog",
        "product_slug": PRODUCT_SLUG,
        "hardware_class": HARDWARE_CLASS,
        "board": "seeed_xiao_esp32s3",
        "environment": ENVIRONMENT,
        "target": TARGET,
        "expected_flash_bytes": EXPECTED_FLASH_BYTES,
        "firmware_version": FIRMWARE_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "hardware_verified": False,
        "recording_available": False,
        "device_ota_available": False,
        "flash_layout_file": "flash/flash-layout.json",
    }
    for field, want in consts.items():
        if data.get(field) != want:
            errors.append(f"manifest.{field}: must be {want!r}, got {data.get(field)!r}")
    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("manifest.source: must be an object")
    else:
        kind = source.get("kind")
        if kind not in ("pr", "main", "local"):
            errors.append(f"manifest.source.kind: invalid {kind!r}")
        sha = source.get("sha")
        if not isinstance(sha, str) or not FULL_SHA_RE.match(sha):
            errors.append(f"manifest.source.sha: invalid {sha!r}")
        if source.get("dirty") is not False:
            errors.append("manifest.source.dirty: must be false")
        if kind == "pr":
            if not _is_int(source.get("pr_number")) or source["pr_number"] < 1:
                errors.append("manifest.source.pr_number: invalid")
            base = source.get("base_sha")
            if not isinstance(base, str) or not re.match(r"\A[0-9a-f]{40}\Z", base):
                errors.append("manifest.source.base_sha: pr kind requires full SHA")
        if kind == "local" and (sha != "local" or source.get("sha_short") != "local"):
            errors.append("manifest.source: local kind must use 'local' identity")
        if kind in ("pr", "main") and isinstance(sha, str) and re.match(r"\A[0-9a-f]{40}\Z", sha):
            if source.get("sha_short") != sha[:12]:
                errors.append("manifest.source.sha_short: does not match sha")
    build_id = data.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID_RE.match(build_id):
        errors.append(f"manifest.build_id: invalid {build_id!r}")
    tag = data.get("tag")
    kind = source.get("kind") if isinstance(source, dict) else None
    if kind == "main":
        if not isinstance(tag, str) or not TAG_RE.match(tag):
            errors.append(f"manifest.tag: main release requires firmware-main-<sha12>, got {tag!r}")
        elif isinstance(source, dict) and isinstance(source.get("sha"), str):
            if tag != f"firmware-main-{source['sha'][:12]}":
                errors.append("manifest.tag: does not match the main SHA identity")
    elif tag is not None:
        errors.append(f"manifest.tag: only main releases carry tags, got {tag!r}")
    ci = data.get("ci")
    if ci is not None:
        if not isinstance(ci, dict) or not all(
            _is_int(ci.get(k)) and ci[k] >= 1 for k in ("run_id", "attempt")
        ):
            errors.append(f"manifest.ci: must be null or run_id/attempt >= 1, got {ci!r}")
    toolchain = data.get("toolchain")
    if not isinstance(toolchain, dict):
        errors.append("manifest.toolchain: must be an object")
    else:
        for field, want in (
            ("platform", "platformio/espressif32@8.0.0"),
            ("esptool_version", ESPTOOL_VERSION),
            ("idf_version", "v6.1.0"),
        ):
            if toolchain.get(field) != want:
                errors.append(f"manifest.toolchain.{field}: must be {want!r}")
    flash = data.get("flash")
    if not isinstance(flash, dict):
        errors.append("manifest.flash: must be an object")
    else:
        want_flash = {
            "mode": FLASH_MODE, "size": FLASH_SIZE, "freq": FLASH_FREQ,
            "size_bytes": EXPECTED_FLASH_BYTES,
        }
        for field, want in want_flash.items():
            if flash.get(field) != want:
                errors.append(f"manifest.flash.{field}: must be {want!r}, got {flash.get(field)!r}")
    images = data.get("images")
    seen: set[str] = set()
    offsets: dict[str, int] = {}
    if not isinstance(images, list) or len(images) != 4:
        errors.append("manifest.images: must contain exactly 4 segments")
    else:
        for index, image in enumerate(images):
            where = f"manifest.images[{index}]"
            if not isinstance(image, dict) or set(image) != {"role", "file", "offset", "size", "sha256"}:
                errors.append(f"{where}: invalid shape")
                continue
            role = image["role"]
            if role not in IMAGE_ROLES or role in seen:
                errors.append(f"{where}: bad or duplicate role {role!r}")
                continue
            seen.add(role)
            if image["file"] != ROLE_FILES[role]:
                errors.append(f"{where}.file: must be {ROLE_FILES[role]!r}")
            if not _path_ok(image["file"]):
                errors.append(f"{where}.file: unsafe path {image['file']!r}")
            if not _is_int(image["offset"]) or image["offset"] < 0:
                errors.append(f"{where}.offset: invalid")
            else:
                offsets[role] = image["offset"]
            if not _is_int(image["size"]) or image["size"] < 1:
                errors.append(f"{where}.size: invalid")
            if not isinstance(image["sha256"], str) or not SHA256_RE.match(image["sha256"]):
                errors.append(f"{where}.sha256: invalid")
        if set(IMAGE_ROLES) != seen:
            errors.append(f"manifest.images: roles {sorted(seen)} != {sorted(IMAGE_ROLES)}")
        ordered = sorted(
            (i for i in images if isinstance(i, dict) and _is_int(i.get("offset")) and _is_int(i.get("size"))),
            key=lambda i: i["offset"],
        )
        for left, right in zip(ordered, ordered[1:]):
            if right["offset"] < left["offset"] + left["size"]:
                errors.append(
                    f"manifest.images: {left['role']}@0x{left['offset']:x} overlaps "
                    f"{right['role']}@0x{right['offset']:x}"
                )
        for image in ordered:
            if image["offset"] + image["size"] > EXPECTED_FLASH_BYTES:
                errors.append(f"manifest.images: {image['role']} exceeds flash size")
    pt = data.get("partition_table")
    if not isinstance(pt, dict):
        errors.append("manifest.partition_table: must be an object")
    else:
        if pt.get("file") != "flash/partitions.csv":
            errors.append("manifest.partition_table.file: must be flash/partitions.csv")
        if not isinstance(pt.get("sha256"), str) or not SHA256_RE.match(pt["sha256"]):
            errors.append("manifest.partition_table.sha256: invalid")
        if not _is_int(pt.get("size")) or pt["size"] < 1:
            errors.append("manifest.partition_table.size: invalid")
        entries = pt.get("entries")
        if not isinstance(entries, list) or not entries:
            errors.append("manifest.partition_table.entries: must be a non-empty list")
        else:
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("name"), str)
                    or entry.get("type") not in ("app", "data")
                    or not isinstance(entry.get("subtype"), str)
                    or not _is_int(entry.get("offset"))
                    or not _is_int(entry.get("size"))
                    or entry["size"] < 1
                ):
                    errors.append(f"manifest.partition_table.entries: invalid entry {entry!r}")
    files = data.get("files")
    covered: set[str] = set()
    if not isinstance(files, list):
        errors.append("manifest.files: must be an array")
    else:
        for entry in files:
            if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
                errors.append(f"manifest.files: invalid entry {entry!r}")
                continue
            path = entry["path"]
            if not _path_ok(path):
                errors.append(f"manifest.files: unsafe path {path!r}")
                continue
            if path in SELF_EXCLUDED:
                errors.append(f"manifest.files: {path} must be self-excluded")
            if path not in REQUIRED_FILES:
                errors.append(f"manifest.files: unexpected path {path!r}")
            if not isinstance(entry["sha256"], str) or not SHA256_RE.match(entry["sha256"]):
                errors.append(f"manifest.files: {path} sha256 invalid")
            if not _is_int(entry["size"]) or entry["size"] < 0:
                errors.append(f"manifest.files: {path} size invalid")
            covered.add(path)
        want_cover = set(REQUIRED_FILES) - set(SELF_EXCLUDED)
        if covered - want_cover:
            errors.append(f"manifest.files: covers unexpected {sorted(covered - want_cover)}")
        if want_cover - covered:
            errors.append(f"manifest.files: missing coverage {sorted(want_cover - covered)}")
    # Identity cross-field: build_id must agree with source kind/SHA.
    if isinstance(source, dict) and isinstance(build_id, str):
        sha = source.get("sha")
        if kind == "pr" and _is_int(source.get("pr_number")) and isinstance(sha, str) \
                and re.match(r"\A[0-9a-f]{40}\Z", sha):
            if build_id != f"pr-{source['pr_number']}-{sha[:12]}":
                errors.append(f"manifest.build_id: {build_id!r} inconsistent with pr identity")
        if kind == "main" and isinstance(sha, str) and re.match(r"\A[0-9a-f]{40}\Z", sha):
            if build_id != f"main-{sha[:12]}":
                errors.append(f"manifest.build_id: {build_id!r} inconsistent with main identity")
        if kind == "local" and build_id != "local":
            errors.append(f"manifest.build_id: local kind requires 'local', got {build_id!r}")
    return errors


def validate_flash_layout(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["flash-layout.json: not an object"]
    for field in data:
        if field not in {"schema", "target", "flash_size_bytes", "upload", "segments"}:
            errors.append(f"flash-layout.json: unknown field {field!r}")
    if data.get("schema") != "vdog-flash-layout-v1":
        errors.append(f"flash-layout.json: schema {data.get('schema')!r}")
    if data.get("target") != TARGET:
        errors.append(f"flash-layout.json: target {data.get('target')!r}")
    if data.get("flash_size_bytes") != EXPECTED_FLASH_BYTES:
        errors.append("flash-layout.json: flash_size_bytes must be 8388608")
    upload = data.get("upload")
    if not isinstance(upload, dict) or upload != {
        "flash_mode": FLASH_MODE, "flash_size": FLASH_SIZE, "flash_freq": FLASH_FREQ,
    }:
        errors.append(f"flash-layout.json: upload {upload!r} must be dio/8MB/80m")
    segments = data.get("segments")
    roles: set[str] = set()
    if not isinstance(segments, list) or len(segments) != 4:
        errors.append("flash-layout.json: segments must contain 4 entries")
    else:
        for seg in segments:
            if not isinstance(seg, dict) or set(seg) != {"role", "file", "offset", "size", "sha256"}:
                errors.append(f"flash-layout.json: invalid segment {seg!r}")
                continue
            role = seg["role"]
            if role not in IMAGE_ROLES or role in roles:
                errors.append(f"flash-layout.json: bad/duplicate role {role!r}")
                continue
            roles.add(role)
            if seg["file"] != ROLE_FILES[role]:
                errors.append(f"flash-layout.json: {role} file {seg['file']!r}")
            if not _is_int(seg["offset"]) or not _is_int(seg["size"]) or seg["size"] < 1:
                errors.append(f"flash-layout.json: {role} offset/size invalid")
            if not isinstance(seg["sha256"], str) or not SHA256_RE.match(seg["sha256"]):
                errors.append(f"flash-layout.json: {role} sha256 invalid")
        if roles != set(IMAGE_ROLES):
            errors.append("flash-layout.json: roles incomplete")
    valid_segs = [
        s for s in (segments if isinstance(segments, list) else [])
        if isinstance(s, dict) and _is_int(s.get("offset")) and _is_int(s.get("size"))
    ]
    ordered = sorted(valid_segs, key=lambda s: s["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if right["offset"] < left["offset"] + left["size"]:
            errors.append(
                f"flash-layout.json: {left.get('role')} overlaps {right.get('role')}"
            )
    for seg in ordered:
        if seg["offset"] + seg["size"] > EXPECTED_FLASH_BYTES:
            errors.append(f"flash-layout.json: {seg.get('role')} exceeds flash size")
    return errors


def parse_partition_entries(data: bytes, *, where: str = "partition table") -> list[dict[str, Any]]:
    """Parse the binary partition table; raise InstallerError on anomalies."""
    if len(data) != PARTITION_TABLE_MAX_BYTES:
        raise InstallerError(
            f"{where}: size {len(data)} != {PARTITION_TABLE_MAX_BYTES}", EXIT_PACKAGE_INVALID
        )
    entries: list[dict[str, Any]] = []
    count = 0
    while (count + 1) * PARTITION_ENTRY_SIZE <= len(data):
        raw = data[count * PARTITION_ENTRY_SIZE:(count + 1) * PARTITION_ENTRY_SIZE]
        if int.from_bytes(raw[0:2], "little") != PARTITION_ENTRY_MAGIC:
            break
        entries.append(
            {
                "type": raw[2],
                "subtype": raw[3],
                "offset": int.from_bytes(raw[4:8], "little"),
                "size": int.from_bytes(raw[8:12], "little"),
                "name": raw[12:28].rstrip(b"\x00").decode("ascii", "replace"),
            }
        )
        count += 1
    tail = data[count * PARTITION_ENTRY_SIZE:]
    if tail[PARTITION_ENTRY_SIZE:] and any(b != 0xFF for b in tail[PARTITION_ENTRY_SIZE:]):
        raise InstallerError(f"{where}: non-erased bytes after entries", EXIT_PACKAGE_INVALID)
    md5_region = tail[16:32] if len(tail) >= 32 else b""
    if md5_region and any(b != 0xFF for b in md5_region):
        import hashlib as _h

        expected = _h.md5(data[: count * PARTITION_ENTRY_SIZE]).digest()
        if md5_region != expected:
            raise InstallerError(f"{where}: MD5 trailer mismatch", EXIT_PACKAGE_INVALID)
    if not entries:
        raise InstallerError(f"{where}: no entries", EXIT_PACKAGE_INVALID)
    return entries


def _walk_segments(data: bytes) -> list[bytes]:
    """Return the segment payloads of an ESP image container (best effort)."""
    segs: list[bytes] = []
    if len(data) < 24:
        return segs
    segment_count = data[1]
    if not 1 <= segment_count <= 16:
        return segs
    off = 24
    for _ in range(segment_count):
        if off + 8 > len(data):
            return segs
        size = int.from_bytes(data[off + 4:off + 8], "little")
        seg = data[off + 8:off + 8 + size]
        if len(seg) != size:
            return segs
        segs.append(seg)
        off += 8 + size
    return segs


def check_image_header(data: bytes, *, where: str,
                       expect_desc: str | None = None) -> list[str]:
    """Structural ESP image sanity: magic, chip ID, segments, descriptor.

    ``expect_desc`` is "app" (application), "bootloader" or None (any).
    """
    errors: list[str] = []
    if len(data) < 42 or data[0] != ESP_IMAGE_MAGIC:
        return [f"{where}: not an ESP image (magic)"]
    segment_count = data[1]
    if not 1 <= segment_count <= 16:
        errors.append(f"{where}: segment count {segment_count}")
    if data[12] != ESP32S3_IMAGE_CHIP_ID:  # extended header chip_id byte
        errors.append(
            f"{where}: chip id {data[12]} is not esp32s3 ({ESP32S3_IMAGE_CHIP_ID})"
        )
    if data[23] not in (0, 1):
        errors.append(f"{where}: append_digest field invalid")
    segs = _walk_segments(data)
    app_desc = any(len(seg) >= 4 and int.from_bytes(seg[:4], "little") == APP_DESC_MAGIC
                   for seg in segs)
    boot_desc = any(len(seg) >= 1 and seg[0] == BOOTLOADER_DESC_MAGIC for seg in segs)
    if expect_desc == "app" and not app_desc:
        errors.append(f"{where}: no app descriptor segment (not a normal app image?)")
    elif expect_desc == "bootloader" and not boot_desc:
        errors.append(f"{where}: no bootloader descriptor segment")
    elif expect_desc is None and not (app_desc or boot_desc):
        errors.append(f"{where}: no app/bootloader descriptor segment found")
    return errors


# ---------------------------------------------------------------------------
# Package (extracted ZIP root) loading and full offline validation
# ---------------------------------------------------------------------------


class Package:
    """One extracted installation package rooted at a directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def read(self, rel: str) -> bytes:
        path = self.root / rel
        try:
            return path.read_bytes()
        except OSError as exc:
            raise InstallerError(f"package: cannot read {rel}: {exc}", EXIT_PACKAGE_INVALID) from exc

    def load_json(self, rel: str) -> Any:
        try:
            return json.loads(self.read(rel).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstallerError(f"package: {rel} invalid JSON: {exc}", EXIT_PACKAGE_INVALID) from exc

    def build_id(self) -> str:
        return str(self.load_json("manifest.json").get("build_id"))

    def validate(self) -> dict[str, Any]:
        """Full offline validation of the package. Raises InstallerError."""
        failures: list[str] = []
        for rel in sorted(REQUIRED_FILES):
            if not (self.root / rel).is_file():
                failures.append(f"package: missing required file {rel}")
        if failures:
            raise InstallerError("\n".join(failures), EXIT_PACKAGE_INVALID)
        manifest = self.load_json("manifest.json")
        failures.extend(validate_manifest(manifest))
        layout = self.load_json("flash/flash-layout.json")
        failures.extend(validate_flash_layout(layout))
        if failures:
            raise InstallerError("\n".join(failures), EXIT_PACKAGE_INVALID)

        # Hash/size coverage from manifest.files + SHA256SUMS.
        for entry in manifest["files"]:
            data = self.read(entry["path"])
            if sha256_bytes(data) != entry["sha256"]:
                failures.append(f"package: {entry['path']} sha256 mismatch vs manifest")
            if len(data) != entry["size"]:
                failures.append(
                    f"package: {entry['path']} size {len(data)} != manifest {entry['size']}"
                )
        sums = {}
        for line in self.read("SHA256SUMS").decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2 or not SHA256_RE.match(parts[0]):
                failures.append(f"SHA256SUMS: malformed line {line!r}")
                continue
            sums[parts[1]] = parts[0]
        want = set(REQUIRED_FILES) - {"SHA256SUMS"}
        if set(sums) != want:
            failures.append(
                f"SHA256SUMS: covers {sorted(set(sums) ^ want)} incorrectly"
            )
        for path, digest in sums.items():
            if path == "SHA256SUMS":
                continue
            data = self.read(path)
            if sha256_bytes(data) != digest:
                failures.append(f"SHA256SUMS: {path} sha256 mismatch")

        # Version.json identity agreement.
        version = self.load_json("VERSION.json")
        source = manifest["source"]
        for field, want in (
            ("build_id", manifest["build_id"]),
            ("firmware_version", manifest["firmware_version"]),
            ("release_channel", manifest["release_channel"]),
            ("source_sha", source["sha"]),
            ("tag", manifest["tag"]),
        ):
            if version.get(field) != want:
                failures.append(
                    f"VERSION.json.{field}: {version.get(field)!r} != manifest {want!r}"
                )

        # Images vs manifest/layout + headers.
        by_role = {i["role"]: i for i in manifest["images"]}
        layout_by_role = {s["role"]: s for s in layout["segments"]}
        for role in IMAGE_ROLES:
            data = self.read(ROLE_FILES[role])
            for src_name, src in (("manifest", by_role), ("layout", layout_by_role)):
                if sha256_bytes(data) != src[role]["sha256"]:
                    failures.append(f"package: {role} sha256 mismatch vs {src_name}")
                if len(data) != src[role]["size"]:
                    failures.append(f"package: {role} size mismatch vs {src_name}")
                if by_role[role]["offset"] != layout_by_role[role]["offset"]:
                    failures.append(f"package: {role} offset manifest/layout disagree")
            if role == "bootloader":
                failures.extend(check_image_header(
                    data, where=ROLE_FILES[role], expect_desc="bootloader"))
            elif role == "application":
                failures.extend(check_image_header(
                    data, where=ROLE_FILES[role], expect_desc="app"))

        # Partition table CSV + binary + role offsets.
        csv_text = self.read("flash/partitions.csv").decode("utf-8", "replace")
        csv_entries = self._parse_csv(csv_text, failures)
        binary_entries = parse_partition_entries(self.read(ROLE_FILES["partition_table"]),
                                                 where="images/partitions.bin")
        manifest_entries = manifest["partition_table"]["entries"]
        if csv_entries and manifest_entries != csv_entries:
            failures.append("package: manifest partition entries do not mirror the CSV")
        by_name = {e["name"]: e for e in binary_entries}
        otadata = by_name.get("otadata")
        app0 = by_name.get("app0")
        nvs = by_name.get("nvs")
        if not (otadata and app0 and nvs):
            failures.append("package: partition table missing nvs/otadata/app0")
            raise InstallerError("\n".join(failures), EXIT_PACKAGE_INVALID)
        want_offsets = {
            "bootloader": 0,
            "partition_table": 0x8000,
            "ota_data_initial": otadata["offset"],
            "application": app0["offset"],
        }
        for role, want_off in want_offsets.items():
            if by_role[role]["offset"] != want_off:
                failures.append(
                    f"package: {role} offset 0x{by_role[role]['offset']:x} != partition-"
                    f"derived 0x{want_off:x} (fixed 0x10000/0xe000 assumptions are rejected)"
                )
        ota = self.read(ROLE_FILES["ota_data_initial"])
        if len(ota) != otadata["size"]:
            failures.append("package: ota_data_initial.bin size != otadata partition")
        for sector in range(len(ota) // 0x1000):
            block = ota[sector * 0x1000:(sector + 1) * 0x1000]
            if all(b == 0xFF for b in block) or block[0] == OTA_DATA_MAGIC_BYTE:
                continue
            failures.append(f"package: ota_data_initial.bin sector {sector} invalid")
        app = self.read(ROLE_FILES["application"])
        if len(app) > app0["size"]:
            failures.append("package: application exceeds the app0 partition (oversized)")
        bl = self.read(ROLE_FILES["bootloader"])
        if len(bl) > 0x8000:
            failures.append("package: bootloader exceeds its region")
        # Written ranges must never intersect NVS.
        for image in manifest["images"]:
            if (image["offset"] < nvs["offset"] + nvs["size"]
                    and nvs["offset"] < image["offset"] + image["size"]):
                failures.append(f"package: {image['role']} range would touch NVS")
        if failures:
            raise InstallerError("\n".join(failures), EXIT_PACKAGE_INVALID)
        return manifest

    def _parse_csv(self, text: str, failures: list[str]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line_no, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                failures.append(f"flash/partitions.csv:{line_no}: malformed")
                continue
            try:
                entries.append(
                    {
                        "name": parts[0],
                        "type": parts[1],
                        "subtype": parts[2],
                        "offset": int(parts[3], 16) if parts[3] else 0,
                        "size": int(parts[4], 16) if parts[4] else 0,
                    }
                )
            except ValueError:
                failures.append(f"flash/partitions.csv:{line_no}: malformed numbers")
        return entries


# ---------------------------------------------------------------------------
# esptool transport (fakeable adapter)
# ---------------------------------------------------------------------------


class EsptoolFailure(Exception):
    """Transport-level failure (serial error, tool failure, bad output)."""


class EsptoolTransport:
    """Runs the pinned esptool as a subprocess with fixed argv vectors.

    Only the operations this class exposes are reachable from the CLI:
    identification, read-only flash reads and segment writes. There is no
    wiping or security-configuration operation available anywhere, by design.
    """

    def __init__(self, command: list[str]) -> None:
        self.command = list(command)
        self.calls: list[list[str]] = []

    # -- plumbing -----------------------------------------------------------
    def _run(self, args: list[str], timeout: int) -> str:
        argv = [*self.command, *args]
        self.calls.append(argv)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise EsptoolFailure(f"cannot execute esptool ({argv[0]}): {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise EsptoolFailure(f"esptool timed out after {timeout}s") from exc
        if proc.returncode != 0:
            tail = " | ".join(
                (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            )
            raise EsptoolFailure(
                f"esptool exited {proc.returncode}: {tail}"
            )
        return (proc.stdout or "") + (proc.stderr or "")

    @staticmethod
    def _global_args(port: str, *, after: str) -> list[str]:
        return [
            "--chip", TARGET,
            "--port", port,
            "--before", "default-reset",
            "--after", after,
            "--connect-attempts", "3",
        ]

    # -- read-only operations ------------------------------------------------
    def version(self) -> str:
        out = self._run(["version"], VERSION_TIMEOUT_SECONDS)
        match = re.search(r"esptool v(\d+\.\d+\.\d+)", out)
        if not match:
            raise EsptoolFailure(f"cannot parse esptool version output: {out[:120]!r}")
        return match.group(1)

    def flash_id(self, port: str) -> tuple[str, int]:
        out = self._run(self._global_args(port, after="no-reset") + ["flash-id"],
                        CONNECT_TIMEOUT_SECONDS)
        if not CHIP_DISPLAY_RE.search(out):
            raise EsptoolFailure(f"device is not an ESP32-S3: {self._chip_line(out)!r}")
        size = self._parse_flash_size(out)
        if size is None:
            raise EsptoolFailure(f"cannot detect flash size from: {self._size_line(out)!r}")
        return TARGET, size

    @staticmethod
    def _chip_line(out: str) -> str:
        for line in out.splitlines():
            if line.strip().lower().startswith("chip is"):
                return line.strip()
        return "<no 'Chip is' line>"

    @staticmethod
    def _size_line(out: str) -> str:
        for line in out.splitlines():
            if "Detected flash size" in line:
                return line.strip()
        return "<no flash size line>"

    @staticmethod
    def _parse_flash_size(out: str) -> int | None:
        match = re.search(r"Detected flash size:\s*([0-9.]+)\s*([KM]B|MiB|MB)", out, re.I)
        if not match:
            return None
        value, unit = float(match.group(1)), match.group(2).upper()
        mult = {"KB": 1024, "MB": 1024 ** 2, "MIB": 1024 ** 2}[unit]
        return int(value * mult)

    def security_flags(self, port: str) -> dict[str, bool]:
        out = self._run(self._global_args(port, after="no-reset")
                        + ["get-security-info"], CONNECT_TIMEOUT_SECONDS)
        result: dict[str, bool] = {}
        for key, pattern in (
            ("secure_boot", r"Secure Boot:\s*(\w+)"),
            ("flash_encryption", r"Flash Encryption:\s*(\w+)"),
        ):
            match = re.search(pattern, out)
            if not match:
                raise EsptoolFailure(
                    f"security report incomplete: missing {key}; refusing to continue"
                )
            result[key] = match.group(1).lower().startswith("enable")
        return result

    def read_flash(self, port: str, offset: int, size: int) -> bytes:
        with tempfile.TemporaryDirectory(prefix="vdog-read-") as tmp:
            out_file = Path(tmp) / "read.bin"
            self._run(
                self._global_args(port, after="no-reset")
                + ["read-flash", str(offset), str(size), str(out_file)],
                READ_TIMEOUT_SECONDS,
            )
            try:
                return out_file.read_bytes()
            except OSError as exc:
                raise EsptoolFailure(f"esptool did not produce read data: {exc}") from exc

    # -- the only write operation (never outside manifest-approved ranges) ----
    def write_flash(self, port: str, offset: int, image_path: Path, *,
                    final: bool) -> None:
        self._run(
            self._global_args(port, after="hard-reset" if final else "no-reset")
            + [
                "write-flash",
                "--flash-mode", FLASH_MODE,
                "--flash-size", FLASH_SIZE,
                "--flash-freq", FLASH_FREQ,
                hex(offset),
                str(image_path),
            ],
            WRITE_TIMEOUT_SECONDS,
        )


def resolve_esptool_command(explicit_python: str | None) -> list[str]:
    """Resolve the pinned esptool invocation; never fall back to an ambient tool."""
    candidates: list[str | None] = [explicit_python, os.environ.get("VDOG_ESPTOOL_PYTHON")]
    for candidate in candidates:
        if candidate:
            return [candidate, "-m", "esptool"]
    if importlib.util.find_spec("esptool") is not None:
        return [sys.executable, "-m", "esptool"]
    raise InstallerError(
        "esptool is not available to this Python. Run the installer through the "
        "packaged setup wrapper (install.sh/install.ps1), install the locked "
        "requirements-installer.lock into the environment running install.py, or "
        "point --esptool-python at the Python of the qualified installer "
        "environment (esptool==5.4.0).",
        EXIT_ENVIRONMENT,
    )


def ensure_pinned_esptool(transport: EsptoolTransport) -> None:
    version = transport.version()
    if version != ESPTOOL_VERSION:
        raise InstallerError(
            f"esptool version {version} is not the qualified {ESPTOOL_VERSION}; "
            "refusing to use it (never silently use an ambient esptool)",
            EXIT_ENVIRONMENT,
        )


def default_ports_provider() -> list[tuple[str, str]]:
    try:
        import serial.tools.list_ports  # type: ignore
    except ImportError as exc:
        raise InstallerError(
            "serial port enumeration needs the locked installer dependencies "
            "(pyserial). Run install.py through the packaged setup wrapper or "
            "install requirements-installer.lock first.",
            EXIT_ENVIRONMENT,
        ) from exc
    return [
        (p.device, p.description or "")
        for p in serial.tools.list_ports.comports()
    ]


# ---------------------------------------------------------------------------
# Device-state decision logic (blank factory vs matching dev layout vs refuse)
# ---------------------------------------------------------------------------


def classify_device(transport: EsptoolTransport, port: str, manifest: dict[str, Any],
                    log: Callable[[str], None]) -> str:
    """Return "factory-blank" or "dev-match"; raise InstallerError otherwise.

    * chip must report esp32s3 and flash 8MB;
    * secure boot / flash encryption must both be off;
    * demonstrably blank (partition table, otadata and NVS head all erased)
      may use the explicit factory-install route after confirmation;
    * an existing installation is accepted only when its partition table
      exactly matches the packaged manifest and the device is unprovisioned
      (empty NVS);
    * unreadable/unknown layouts and paired/provisioned devices are refused —
      never assumed blank.
    """
    _chip, size = transport.flash_id(port)
    if size != EXPECTED_FLASH_BYTES:
        raise InstallerError(
            f"refusing: device flash is {size} bytes, expected {EXPECTED_FLASH_BYTES} (8MB)",
            EXIT_REFUSED,
        )
    flags = transport.security_flags(port)
    if flags["secure_boot"] or flags["flash_encryption"]:
        raise InstallerError(
            f"refusing: device security state {flags} is not an unprotected "
            "development board; a security-enabled device needs a separately "
            "qualified process",
            EXIT_REFUSED,
        )
    image_by_role = {i["role"]: i for i in manifest["images"]}
    pt_image = image_by_role["partition_table"]
    table = transport.read_flash(port, pt_image["offset"], PARTITION_TABLE_MAX_BYTES)
    ota_image = image_by_role["ota_data_initial"]
    otadata = transport.read_flash(port, ota_image["offset"], ota_image["size"])
    nvs = next(e for e in manifest["partition_table"]["entries"] if e["name"] == "nvs")
    nvs_head = transport.read_flash(port, nvs["offset"], min(0x1000, nvs["size"]))

    if all(b == 0xFF for b in table):
        if all(b == 0xFF for b in otadata) and all(b == 0xFF for b in nvs_head):
            log("device state: blank factory board (partition table/otadata/NVS head erased)")
            return "factory-blank"
        raise InstallerError(
            "refusing: partition table area is erased but otadata/NVS is not — an "
            "erased table next to populated data is an unknown state, never assumed blank",
            EXIT_REFUSED,
        )
    try:
        entries = parse_partition_entries(table, where="on-device partition table")
    except InstallerError as exc:
        raise InstallerError(
            f"refusing: on-device partition table is unreadable/unknown: {exc}", EXIT_REFUSED
        ) from exc
    expected = {
        e["name"]: e for e in manifest["partition_table"]["entries"]
        if e["name"] in {"nvs", "otadata", "phy_init", "app0", "app1", "storage"}
    }
    got = {e["name"]: e for e in entries}
    if set(got) != set(expected):
        raise InstallerError(
            f"refusing: device partition layout {sorted(got)} does not match the "
            "qualified development layout; unknown layouts are never overwritten",
            EXIT_REFUSED,
        )
    for name, want in expected.items():
        if got[name]["offset"] != want["offset"] or got[name]["size"] != want["size"]:
            raise InstallerError(
                f"refusing: device partition {name!r} at 0x{got[name]['offset']:x}/"
                f"0x{got[name]['size']:x} differs from the qualified layout "
                f"(0x{want['offset']:x}/0x{want['size']:x}) — layout migration is out of scope",
                EXIT_REFUSED,
            )
    if not all(b == 0xFF for b in nvs_head):
        raise InstallerError(
            "refusing: NVS partition contains settings — the board is provisioned/"
            "paired; replacing it needs the separately qualified preservation route "
            "(this installer never touches NVS)",
            EXIT_REFUSED,
        )
    for sector in range(len(otadata) // 0x1000):
        block = otadata[sector * 0x1000:(sector + 1) * 0x1000]
        if all(b == 0xFF for b in block) or block[0] == OTA_DATA_MAGIC_BYTE:
            continue
        raise InstallerError(
            f"refusing: otadata sector {sector} is neither erased nor valid", EXIT_REFUSED
        )
    log("device state: matching unprovisioned development layout (replace allowed)")
    return "dev-match"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class InstallerApp:
    def __init__(
        self,
        package_root: Path,
        *,
        transport: EsptoolTransport | None = None,
        esptool_python: str | None = None,
        ports_provider: Callable[[], list[tuple[str, str]]] | None = None,
        input_fn: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
        err: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
    ) -> None:
        self.package = Package(package_root)
        self._transport = transport
        self.esptool_python = esptool_python
        self.ports_provider = ports_provider or default_ports_provider
        self.input_fn = input_fn
        self.out = out
        self.err = err

    def get_transport(self) -> EsptoolTransport:
        if self._transport is None:
            self._transport = EsptoolTransport(
                resolve_esptool_command(self.esptool_python)
            )
        return self._transport

    # -- identity logging -----------------------------------------------------
    def log_identity(self) -> None:
        manifest = self.package.load_json("manifest.json")
        source = manifest.get("source", {}) if isinstance(manifest, dict) else {}
        self.out(
            f"vdog package: {manifest.get('product_slug')!r} build_id={manifest.get('build_id')} "
            f"source={source.get('sha_short') if isinstance(source, dict) else '?'} "
            f"channel={manifest.get('release_channel')} version={manifest.get('firmware_version')} "
            f"(hardware_verified=false, recording_available=false, device_ota_available=false)"
        )

    # -- check ------------------------------------------------------------------
    def cmd_check(self) -> int:
        self.log_identity()
        manifest = self.package.validate()
        self.out(
            f"check: OK — manifest, layout, {len(manifest['images'])} images, hashes, "
            "partition table and headers all consistent"
        )
        return EXIT_OK

    # -- ports -----------------------------------------------------------------
    def cmd_ports(self) -> int:
        ports = self.ports_provider()
        if not ports:
            self.out("ports: no serial ports found")
            return EXIT_OK
        for device, description in ports:
            self.out(f"port: {device}  ({description})")
        self.out("ports: pass an explicit --port; this tool never auto-selects")
        return EXIT_OK

    # -- plan --------------------------------------------------------------------
    def plan_lines(self, manifest: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        esptool_hint = " ".join(
            self._transport.command if self._transport else ["<esptool>"]
        )
        for image in manifest["images"]:
            end = image["offset"] + image["size"] - 1
            lines.append(
                f"write: role={image['role']} file={image['file']} "
                f"range=0x{image['offset']:08x}..0x{end:08x} ({image['size']} B) "
                f"sha256={image['sha256'][:12]}…"
            )
            lines.append(
                f"invoke: {esptool_hint} --chip esp32s3 --port <port> --before default-reset "
                f"--after {'hard-reset' if image['role'] == 'application' else 'no-reset'} "
                f"write-flash --flash-mode {FLASH_MODE} --flash-size {FLASH_SIZE} "
                f"--flash-freq {FLASH_FREQ} 0x{image['offset']:x} {image['file']}"
            )
        lines.append(
            "read-back verify: each written range is read back and compared to the "
            "manifest sha256"
        )
        lines.append("never written: NVS, phy_init, storage, SD card, security fuses")
        return lines

    def cmd_plan(self, board: str) -> int:
        if board != HARDWARE_CLASS:
            raise InstallerError(
                f"unsupported --board {board!r}; this package supports "
                f"{HARDWARE_CLASS!r} only",
                EXIT_USAGE,
            )
        self.log_identity()
        manifest = self.package.validate()
        for line in self.plan_lines(manifest):
            self.out(line)
        return EXIT_OK

    # -- inspect -----------------------------------------------------------------
    def cmd_inspect(self, port: str) -> int:
        self._require_port(port)
        self.log_identity()
        manifest = self.package.validate()
        transport = self.get_transport()
        ensure_pinned_esptool(transport)
        try:
            chip, size = transport.flash_id(port)
            self.out(f"inspect: chip={chip} flash={size} bytes ({size // (1024 * 1024)}MB)")
            flags = transport.security_flags(port)
            self.out(f"inspect: security={flags}")
            state = classify_device(transport, port, manifest, self.out)
            self.out(f"inspect: state={state}")
        except EsptoolFailure as exc:
            raise InstallerError(f"inspect failed: {exc}", EXIT_FLASH_FAILED) from exc
        return EXIT_OK

    # -- install -----------------------------------------------------------------
    def cmd_install(self, port: str, board: str, *, dry_run: bool,
                    confirm_replace: bool) -> int:
        if board != HARDWARE_CLASS:
            raise InstallerError(
                f"unsupported --board {board!r}; this package supports "
                f"{HARDWARE_CLASS!r} only (hardware class acknowledgment)",
                EXIT_USAGE,
            )
        self._require_port(port)
        self.log_identity()
        manifest = self.package.validate()
        self.out(f"install: package validated for build_id={manifest['build_id']}")
        for line in self.plan_lines(manifest):
            self.out(line)

        if dry_run:
            self.out("install --dry-run: nothing was executed and no port was opened")
            return EXIT_OK

        transport = self.get_transport()
        ensure_pinned_esptool(transport)
        try:
            state = classify_device(transport, port, manifest, self.out)
            self._consent(manifest, confirm_replace=confirm_replace, state=state)
            images = {i["role"]: i for i in manifest["images"]}
            ordered = [images[role] for role in IMAGE_ROLES]
            for index, image in enumerate(ordered):
                final = index == len(ordered) - 1
                self.out(
                    f"write: {image['role']} -> 0x{image['offset']:08x} "
                    f"({image['size']} B)"
                )
                transport.write_flash(
                    port, image["offset"], self.package.root / image["file"],
                    final=final,
                )
            for image in ordered:
                back = transport.read_flash(port, image["offset"], image["size"])
                if sha256_bytes(back) != image["sha256"]:
                    raise InstallerError(
                        f"install failed: read-back verification of {image['role']} "
                        f"at 0x{image['offset']:08x} did not match the manifest digest; "
                        "the board may need a manual power cycle",
                        EXIT_FLASH_FAILED,
                    )
            self.out(
                f"install: OK — build_id={manifest['build_id']} written to ranges "
                + ", ".join(f"0x{i['offset']:x}" for i in ordered)
                + "; device was reset"
            )
        except EsptoolFailure as exc:
            raise InstallerError(f"install failed: {exc}", EXIT_FLASH_FAILED) from exc
        return EXIT_OK

    def _require_port(self, port: str | None) -> None:
        if not port:
            raise InstallerError(
                "an explicit --port is required (see `install.py ports`); "
                "this installer never auto-selects a port",
                EXIT_USAGE,
            )
        if not PORT_RE.match(port) or any(seg in (".", "..") for seg in port.split("/")):
            raise InstallerError(f"invalid --port value {port!r}", EXIT_USAGE)

    def _consent(self, manifest: dict[str, Any], *, confirm_replace: bool,
                 state: str) -> None:
        self.out("")
        self.out("ABOUT TO WRITE — exact ranges:")
        for image in manifest["images"]:
            end = image["offset"] + image["size"] - 1
            self.out(
                f"  {image['role']:<17} 0x{image['offset']:08x} .. 0x{end:08x}  "
                f"({image['size']} bytes)  <- {image['file']}"
            )
        self.out(
            "This prototype route replaces the listed firmware ranges and resets "
            f"boot selection; mode: {state}. NVS, storage, SD and security fuses "
            "are not touched."
        )
        if confirm_replace:
            self.out("consent: explicit --confirm-replace supplied (noninteractive)")
            return
        try:
            answer = self.input_fn("Type 'install' to proceed with the writes above: ")
        except EOFError as exc:
            raise InstallerError("aborted: no consent (no input available)", EXIT_REFUSED) from exc
        if answer.strip() != "install":
            raise InstallerError("aborted: consent not given; nothing was written", EXIT_REFUSED)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the vdog XIAO ESP32S3 Sense prototype firmware bundle.",
    )
    parser.add_argument(
        "--package", type=Path, default=None,
        help="extracted package directory (default: the directory containing this file)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate the package locally; no serial access")
    sub.add_parser("ports", help="list serial ports; never flashes or auto-selects")

    p_plan = sub.add_parser("plan", help="print validated segments; no serial access")
    p_plan.add_argument("--board", required=True)

    p_inspect = sub.add_parser("inspect", help="read-only device inspection")
    p_inspect.add_argument("--port", required=True)

    p_install = sub.add_parser("install", help="write the manifest-approved ranges")
    p_install.add_argument("--port", required=True)
    p_install.add_argument("--board", required=True)
    p_install.add_argument("--dry-run", action="store_true",
                           help="print the planned invocation without opening the port")
    p_install.add_argument("--confirm-replace", action="store_true",
                           help="explicit noninteractive consent to replace the listed "
                                "firmware ranges (never a security or layout override)")
    for sp in (p_inspect, p_install):
        sp.add_argument("--esptool-python",
                        help="Python interpreter of the qualified installer environment "
                             "used to run esptool 5.4.0 (never an ambient tool)")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    transport: EsptoolTransport | None = None,
    ports_provider: Callable[[], list[tuple[str, str]]] | None = None,
    input_fn: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    package_root = args.package or Path(__file__).resolve().parent
    app = InstallerApp(
        package_root,
        transport=transport,
        esptool_python=getattr(args, "esptool_python", None),
        ports_provider=ports_provider,
        input_fn=input_fn,
        out=out,
    )
    try:
        if args.command == "check":
            return app.cmd_check()
        if args.command == "ports":
            return app.cmd_ports()
        if args.command == "plan":
            return app.cmd_plan(args.board)
        if args.command == "inspect":
            return app.cmd_inspect(args.port)
        if args.command == "install":
            return app.cmd_install(
                args.port, args.board,
                dry_run=args.dry_run, confirm_replace=args.confirm_replace,
            )
        parser.error(f"unknown command {args.command}")  # pragma: no cover
    except InstallerError as exc:
        for line in str(exc).splitlines():
            print(f"error: {line}", file=sys.stderr)
        return exc.code
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
