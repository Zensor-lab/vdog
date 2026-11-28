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

Safety properties (CI-08 / CI-T08 / 0.9.5, hardened by the baseline Item #17
P0-1/P0-2/P1-1 items):
  * an explicit ``--port`` is always required for serial operations;
  * the chip must be esp32s3 and the flash the expected 8MB before any write;
  * the pinned esptool version is verified and never silently substituted;
  * writes go only to manifest-approved ranges matching the partition table;
  * device reads are exact-length: a short read is fatal, never blank/matching;
  * an installed device is replaceable only when its partition table equals
    the validated packaged table semantically (type, subtype, offset, size,
    flags, labels, no duplicates) and byte-for-byte, and its otadata parses
    strictly as pinned ESP-IDF v6.1 select records (no 0xC9 heuristics);
  * classification, operator consent, every write and every read-back
    verification run on ONE live verified esptool connection (chip, flash
    size, MAC pinned from the read-only preflight probe, and security-off
    are verified on that connection; the port stays held, so a same-path
    device swap is refused and a connection loss never continues or resets);
    the read-only preflight CLI probe uses exactly one session-establishing
    ``--before default-reset`` and then ``--before no-reset`` steps,
    re-verifying the explicit port path and never following a renumbered
    one; exactly one explicit reset, only after every written range has
    been read back and verified; no failure path resets the board;
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
import types
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Frozen contract constants (mirror of tools/firmware/contract.py, verified
# equal by tools/firmware/tests/test_install_cli.py).
# ---------------------------------------------------------------------------

ESPTOOL_VERSION = "5.4.0"
TARGET = "esp32s3"
# esptool 5.x prints f"{'Chip type:':<20}{esp.get_chip_description()}" (pinned
# 5.4.0 sdist esptool/__init__.py:568-572), e.g. "Chip type:          ESP32-S3
# (QFN56) (revision v0.2)"; the pre-5 "Chip is ..." form is accepted too for
# robustness. Whitespace-tolerant padding; (?![0-9]) keeps ESP32-S3xx variants
# from matching.
CHIP_DISPLAY_RE = re.compile(
    r"(?:Chip type:|Chip is)\s+ESP32-S3(?![0-9])", re.IGNORECASE
)
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
#: esp_flash_partitions.h (pinned IDF v6.1): PART_FLAG_ENCRYPTED | PART_FLAG_READONLY
PARTITION_FLAG_BITS = 0x3
#: The gen_esp32part.py builder trailer (MD5_PARTITION_BEGIN) inside the
#: first free slot; the 16-byte MD5 sits at slot offset 16.
PARTITION_MD5_SLOT_MAGIC = b"\xeb\xeb"

# On-device OTA select records: pinned ESP-IDF v6.1 esp_ota_select_entry_t
# (esp_flash_partitions.h, release/v6.1) — uint32 ota_seq, opaque
# seq_label[20], uint32 ota_state, uint32 crc (esp_rom_crc32_le over the
# ota_seq field, per bootloader_common_ota_select_crc). The legacy
# single-byte 0xC9 "valid sector" heuristic is retired (P0-2).
OTA_DATA_SECTOR_SIZE = 0x1000
OTA_SELECT_ENTRY_SIZE = 32
OTA_IMG_STATE_NAMES = {
    0x00000000: "NEW",
    0x00000001: "PENDING_VERIFY",
    0x00000002: "VALID",
    0x00000003: "INVALID",
    0x00000004: "ABORTED",
    0xFFFFFFFF: "UNDEFINED",
}

#: CSV subtype name -> (type, subtype) codes; mirrors
#: contract.CSV_SUBTYPE_CODES (equality enforced by test_install_cli).
CSV_SUBTYPE_CODES: dict[str, tuple[int, int]] = {
    "boot": (0, 0x00),
    "nvs": (1, 0x02),
    "ota": (1, 0x00),
    "phy": (1, 0x01),
    "coredump": (1, 0x03),
    "nvs_key": (1, 0x04),
    "fat": (1, 0x81),
    "spiffs": (1, 0x82),
    "any": (255, 255),
}
for _i in range(16):
    CSV_SUBTYPE_CODES[f"ota_{_i}"] = (0, 0x10 + _i)

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
        for field in source:
            if field not in {
                "kind", "sha", "sha_short", "pr_number", "base_sha", "dirty"
            }:
                errors.append(f"manifest.source: unknown field {field!r}")
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
            elif base == sha:
                errors.append("manifest.source.base_sha: base SHA must differ from head SHA")
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
        if (
            not isinstance(ci, dict)
            or set(ci) != {"run_id", "attempt"}
            or not all(_is_int(ci.get(k)) and ci[k] >= 1 for k in ("run_id", "attempt"))
        ):
            errors.append(f"manifest.ci: must be null or run_id/attempt >= 1, got {ci!r}")
        if kind == "local":
            errors.append(
                "manifest.ci: local builds are unpublishable and must not carry "
                f"CI identity, got {ci!r}"
            )
    toolchain = data.get("toolchain")
    if not isinstance(toolchain, dict):
        errors.append("manifest.toolchain: must be an object")
    else:
        if set(toolchain) != {
            "platformio_core", "platform", "idf_version", "esptool_version"
        }:
            errors.append("manifest.toolchain: must have exactly the four pin fields")
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
        if set(flash) != set(want_flash):
            errors.append("manifest.flash: keys must be mode/size/freq/size_bytes")
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
            if path in covered:
                errors.append(f"manifest.files: duplicate path {path!r}")
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
    """Parse the binary partition table with strict semantics (P0-1).

    Every semantic field is parsed — type, subtype, offset, size, flags and
    label — and anomalies are errors, never blank/matching assumptions:
    unknown flag bits, non-ASCII or empty labels and DUPLICATE labels are all
    rejected; bytes after the entries must be erased except for the
    gen_esp32part builder trailer (0xEBEB slot magic at +0, erased padding at
    +2..16 and the 16-byte MD5 over all entry bytes at +16), whose presence
    is verified against the computed digest.
    """
    if len(data) != PARTITION_TABLE_MAX_BYTES:
        raise InstallerError(
            f"{where}: size {len(data)} != {PARTITION_TABLE_MAX_BYTES}", EXIT_PACKAGE_INVALID
        )
    entries: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    count = 0
    while (count + 1) * PARTITION_ENTRY_SIZE <= len(data):
        raw = data[count * PARTITION_ENTRY_SIZE:(count + 1) * PARTITION_ENTRY_SIZE]
        if int.from_bytes(raw[0:2], "little") != PARTITION_ENTRY_MAGIC:
            break
        flags = int.from_bytes(raw[28:32], "little")
        if flags & ~PARTITION_FLAG_BITS:
            raise InstallerError(
                f"{where}: entry {count} unknown flag bits {flags:#x}", EXIT_PACKAGE_INVALID
            )
        label_bytes = raw[12:28]
        stripped = label_bytes.rstrip(b"\x00")
        try:
            name = stripped.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InstallerError(
                f"{where}: entry {count} label is not ASCII", EXIT_PACKAGE_INVALID
            ) from exc
        if not stripped or not re.fullmatch(r"[A-Za-z0-9_\-]{1,16}", name):
            raise InstallerError(
                f"{where}: entry {count} invalid label {name!r}", EXIT_PACKAGE_INVALID
            )
        if name in seen_labels:
            raise InstallerError(
                f"{where}: duplicate label {name!r}", EXIT_PACKAGE_INVALID
            )
        seen_labels.add(name)
        entries.append(
            {
                "type": raw[2],
                "subtype": raw[3],
                "offset": int.from_bytes(raw[4:8], "little"),
                "size": int.from_bytes(raw[8:12], "little"),
                "flags": flags,
                "name": name,
            }
        )
        count += 1
    tail = data[count * PARTITION_ENTRY_SIZE:]
    if tail:
        slot = tail[:PARTITION_ENTRY_SIZE]
        beyond = tail[PARTITION_ENTRY_SIZE:]
        if beyond and any(b != 0xFF for b in beyond):
            raise InstallerError(f"{where}: non-erased bytes after entries", EXIT_PACKAGE_INVALID)
        md5_region = slot[16:32]
        if any(b != 0xFF for b in md5_region):
            if slot[0:2] != PARTITION_MD5_SLOT_MAGIC:
                raise InstallerError(
                    f"{where}: MD5 trailer without the builder slot magic "
                    f"(slot starts {slot[0:2].hex()})", EXIT_PACKAGE_INVALID
                )
            if any(b != 0xFF for b in slot[2:16]):
                raise InstallerError(
                    f"{where}: non-erased builder trailer padding", EXIT_PACKAGE_INVALID
                )
            expected = hashlib.md5(data[: count * PARTITION_ENTRY_SIZE]).digest()
            if md5_region != expected:
                raise InstallerError(f"{where}: MD5 trailer mismatch", EXIT_PACKAGE_INVALID)
        elif slot[0:2] == PARTITION_MD5_SLOT_MAGIC:
            raise InstallerError(
                f"{where}: builder trailer magic without an MD5", EXIT_PACKAGE_INVALID
            )
    if not entries:
        raise InstallerError(f"{where}: no entries", EXIT_PACKAGE_INVALID)
    return entries


def esp_ota_crc32(data: bytes) -> int:
    """Mirror of contract.esp_ota_crc32 (esp_rom_crc32_le with the bootloader's
    UINT32_MAX seed — the IDF ROM-compat implementation complements the seed
    on entry and inverts the result, components/esp_rom/patches/esp_rom_crc.c,
    composing to zlib.crc32(data, 0xFFFFFFFF)); equality is enforced by
    test_install_cli."""
    crc = 0  # esp_rom_crc32_le complements the seed: UINT32_MAX ^ UINT32_MAX
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF  # ...and complements the result


def require_ota_data_records(data: bytes, *, where: str = "on-device otadata") -> None:
    """Strict on-device otadata acceptance (P0-2), mirroring
    contract.validate_ota_data_records for the pinned ESP-IDF v6.1
    esp_ota_select_entry_t: each sector is fully erased, or carries exactly
    one 32-byte record with a defined ota_state and the correct CRC32 over
    ota_seq, with the rest of the sector erased. Legacy 0xC9-headed and any
    other corrupted records are refused."""
    errors: list[str] = []
    if len(data) != 2 * OTA_DATA_SECTOR_SIZE:
        raise InstallerError(
            f"refusing: {where} size {len(data)} != {2 * OTA_DATA_SECTOR_SIZE} "
            "(two OTA sectors, each 0x1000)",
            EXIT_REFUSED,
        )
    for sector in range(2):
        base = sector * OTA_DATA_SECTOR_SIZE
        block = data[base: base + OTA_DATA_SECTOR_SIZE]
        if all(b == 0xFF for b in block):
            continue
        entry = block[:OTA_SELECT_ENTRY_SIZE]
        if any(b != 0xFF for b in block[OTA_SELECT_ENTRY_SIZE:]):
            errors.append(
                f"{where}: sector {sector} is not erased beyond the "
                f"{OTA_SELECT_ENTRY_SIZE}-byte select entry (torn or legacy "
                "multi-slot content is never accepted)"
            )
            continue
        ota_state = int.from_bytes(entry[24:28], "little")
        crc = int.from_bytes(entry[28:32], "little")
        want_crc = esp_ota_crc32(entry[0:4])
        if ota_state not in OTA_IMG_STATE_NAMES:
            errors.append(
                f"{where}: sector {sector} ota_state {ota_state:#010x} is not a "
                "defined v6.1 esp_ota_img_states_t value"
            )
        if crc != want_crc:
            errors.append(
                f"{where}: sector {sector} crc32 {crc:#010x} != {want_crc:#010x} "
                "over ota_seq (v6.1 bootloader CRC policy)"
            )
    if errors:
        raise InstallerError(
            "refusing: " + "; ".join(errors) + " — corrupted OTA records are never "
            "treated as an acceptable development state",
            EXIT_REFUSED,
        )


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
        # P0-2: the qualified packaged initializer must be TWO FULLY ERASED
        # sectors — boot selection is established by the device's own first
        # boot, never pre-baked into the shipped image. (contract.py applies
        # the same rule at build time; this is the install-time gate.)
        if len(ota) != 2 * OTA_DATA_SECTOR_SIZE:
            failures.append(
                "package: ota_data_initial.bin size != two erased OTA sectors"
            )
        else:
            for sector in range(2):
                block = ota[sector * OTA_DATA_SECTOR_SIZE:(sector + 1) * OTA_DATA_SECTOR_SIZE]
                if any(b != 0xFF for b in block):
                    failures.append(
                        f"package: ota_data_initial.bin sector {sector} is not "
                        "fully erased (pre-baked OTA records are rejected)"
                    )
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
    identification, read-only flash reads, segment writes (always
    ``--after no-reset``) and the single explicit post-verification reset.
    There is no wiping or security-configuration operation available
    anywhere, by design.

    P1-1 — one verified download session per operation sequence: the FIRST
    operation on a port establishes the session with exactly one
    ``--before default-reset``; every later operation reuses that session and
    passes ``--before no-reset``, so esptool keeps the board in the stub
    bootloader and no reset transition can silently drop or renumber the
    native USB port mid-operation. Before each operation the session re-checks
    that the explicit port path is still enumerated; if it disappears the
    session is torn down and the failure is raised — the installer never
    follows a renumbered port on its own.
    """

    def __init__(self, command: list[str], *,
                 ports_provider: Callable[[], list[tuple[str, str]]] | None = None) -> None:
        self.command = list(command)
        self.calls: list[list[str]] = []
        self.ports_provider = ports_provider
        self.session_port: str | None = None
        self.session_verified = False

    # -- session bookkeeping -------------------------------------------------
    def invalidate_session(self) -> None:
        self.session_port = None
        self.session_verified = False

    def _check_port_identity(self, port: str) -> None:
        """The explicit port path must still be enumerated; a vanished port
        mid-session is fatal, never transparently followed to a new path."""
        if self.session_port is None or self.ports_provider is None:
            return
        try:
            present = [device for device, _desc in self.ports_provider()]
        except Exception as exc:  # noqa: BLE001 - enumeration loss is fatal too
            self.invalidate_session()
            raise EsptoolFailure(
                f"cannot confirm port {port} identity mid-session: {exc}"
            ) from exc
        if port not in present:
            self.invalidate_session()
            raise EsptoolFailure(
                f"port {port} disappeared mid-session (reset transition or USB "
                "re-enumeration); refusing to follow a renumbered port — check "
                "`install.py ports` for the current path and rerun explicitly"
            )

    def _check_exact_read(self, data: bytes, offset: int, size: int) -> bytes:
        if len(data) != size:
            self.invalidate_session()
            raise EsptoolFailure(
                f"esptool read at 0x{offset:x} returned {len(data)} bytes, "
                f"expected exactly {size} (short reads are never treated as "
                "blank or matching)"
            )
        return data

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

    def _global_args(self, port: str, *, after: str) -> list[str]:
        # Within an established verified session the board is already in the
        # stub bootloader: NO further reset (--before no-reset) until the one
        # explicit reset() at the very end. Only a fresh session pays the one
        # establishing --before default-reset.
        before = (
            "no-reset"
            if (self.session_verified and self.session_port == port)
            else "default-reset"
        )
        return [
            "--chip", TARGET,
            "--port", port,
            "--before", before,
            "--after", after,
            "--connect-attempts", "3",
        ]

    def _establish(self, port: str) -> None:
        """A successful operation on ``port`` (re)establishes the session."""
        self.session_port = port
        self.session_verified = True

    def _fail(self, message: str) -> None:
        """Any transport failure tears the session down: the next attempt is
        a fresh explicit session-establishing operation, never a silent
        mid-operation reset."""
        self.invalidate_session()
        raise EsptoolFailure(message)

    # -- read-only operations ------------------------------------------------
    def version(self) -> str:
        out = self._run(["version"], VERSION_TIMEOUT_SECONDS)
        match = re.search(r"esptool v(\d+\.\d+\.\d+)", out)
        if not match:
            raise EsptoolFailure(f"cannot parse esptool version output: {out[:120]!r}")
        return match.group(1)

    def flash_id(self, port: str) -> tuple[str, int]:
        self._check_port_identity(port)
        try:
            out = self._run(self._global_args(port, after="no-reset") + ["flash-id"],
                            CONNECT_TIMEOUT_SECONDS)
        except EsptoolFailure:
            self.invalidate_session()
            raise
        if not CHIP_DISPLAY_RE.search(out):
            self.invalidate_session()
            raise EsptoolFailure(f"device is not an ESP32-S3: {self._chip_line(out)!r}")
        size = self._parse_flash_size(out)
        if size is None:
            self.invalidate_session()
            raise EsptoolFailure(f"cannot detect flash size from: {self._size_line(out)!r}")
        self._establish(port)
        return TARGET, size

    @staticmethod
    def _chip_line(out: str) -> str:
        for line in out.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("chip type:") or stripped.startswith("chip is"):
                return line.strip()
        return "<no 'Chip type:'/'Chip is' line>"

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
        self._check_port_identity(port)
        try:
            out = self._run(self._global_args(port, after="no-reset")
                            + ["get-security-info"], CONNECT_TIMEOUT_SECONDS)
        except EsptoolFailure:
            self.invalidate_session()
            raise
        result: dict[str, bool] = {}
        for key, pattern in (
            ("secure_boot", r"Secure Boot:\s*(\w+)"),
            ("flash_encryption", r"Flash Encryption:\s*(\w+)"),
        ):
            match = re.search(pattern, out)
            if not match:
                self._fail(
                    f"security report incomplete: missing {key}; refusing to continue"
                )
            result[key] = match.group(1).lower().startswith("enable")
        self._establish(port)
        return result

    def read_flash(self, port: str, offset: int, size: int) -> bytes:
        self._check_port_identity(port)
        with tempfile.TemporaryDirectory(prefix="vdog-read-") as tmp:
            out_file = Path(tmp) / "read.bin"
            try:
                self._run(
                    self._global_args(port, after="no-reset")
                    + ["read-flash", str(offset), str(size), str(out_file)],
                    READ_TIMEOUT_SECONDS,
                )
                try:
                    data = out_file.read_bytes()
                except OSError as exc:
                    raise EsptoolFailure(f"esptool did not produce read data: {exc}") from exc
            except EsptoolFailure:
                self.invalidate_session()
                raise
        self._establish(port)
        # P0-1: exact-length reads. A truncated read must never be mistaken
        # for erased content or accepted as matching an expected digest.
        return self._check_exact_read(data, offset, size)

    def read_mac(self, port: str) -> str:
        """Read the MAC address through the CLI (read-only preflight pin).

        The MAC becomes the install-session identity pin: the single live
        write connection must report the same MAC or the install aborts
        with zero writes (same-path device swap protection)."""
        self._check_port_identity(port)
        try:
            out = self._run(self._global_args(port, after="no-reset") + ["read-mac"],
                            CONNECT_TIMEOUT_SECONDS)
        except EsptoolFailure:
            self.invalidate_session()
            raise
        match = re.search(r"MAC:\s*([0-9a-fA-F:]{17})", out)
        if not match:
            self._fail("esptool did not report a MAC address; refusing to continue")
        self._establish(port)
        return match.group(1).lower()

    # -- the only write operation (never outside manifest-approved ranges) ----
    def write_flash(self, port: str, offset: int, image_path: Path) -> None:
        self._check_port_identity(port)
        # Every write keeps the board in the bootloader (``--after no-reset``);
        # the single reset happens afterwards via reset(), only once every
        # written range has been read back and verified.
        try:
            self._run(
                self._global_args(port, after="no-reset")
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
        except EsptoolFailure:
            self.invalidate_session()
            raise
        self._establish(port)

    # -- the one and only reset (after ALL verification succeeded) ------------
    def reset(self, port: str) -> None:
        """Hard-reset the board exactly once, after read-back verification.

        Runs the read-only ``flash-id`` command with ``--after hard-reset``
        so esptool itself performs the only reset of the install (verified
        against the pinned 5.4.0 CLI: ``--before`` accepts
        ``default-reset`` and ``--after`` accepts ``hard-reset``;
        esptool/__init__.py:418-428). The download session ends here: the
        port legitimately re-enumerates after the reset, and nothing runs
        after this point.
        """
        self._check_port_identity(port)
        try:
            self._run(self._global_args(port, after="hard-reset") + ["flash-id"],
                      CONNECT_TIMEOUT_SECONDS)
        except EsptoolFailure:
            self.invalidate_session()
            raise
        self.invalidate_session()


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


class EsptoolSessionBackend:
    """The production write-session backend: ONE esptool 5.4.0 API connection
    for the whole install (P0, review round 1 of PR #9).

    Every chip access after ``connect()`` goes through the single
    ``ESPLoader`` connection esptool opened there — no per-command
    subprocesses and no reopening of the serial path after consent. The
    port stays held by this process until close()/reset(), so a different
    ESP32-S3 presenting the same path can never be written to mid-install:
    the connection itself, not the path string, is the write target. The
    esptool import is lazy so environments without it (and the entire test
    suite, which injects fakes) are unaffected. Live hardware behavior of
    this path remains UNVERIFIED until a qualified on-device run.
    """

    def __init__(self, *, ports_provider: Callable[[], list[tuple[str, str]]] | None = None,
                 esptool_module: Any = None) -> None:
        self.ports_provider = ports_provider
        self._esp: Any = None
        self._write_fn: Any = None
        # Offline-test seam: inject a stub exposing detect_chip,
        # _get_flash_info and __version__ (same surface the real
        # esptool/esptool.cmds modules provide). None = the real library.
        self._module = esptool_module

    def _library(self) -> Any:
        """Resolve the esptool API surface — and PIN it. The interpreter
        running install.py must carry exactly the qualified esptool build,
        never just the CLI subprocess (PR-R2 review finding)."""
        if self._module is not None:
            module = self._module
        else:
            try:
                import esptool
                from esptool import detect_chip
                from esptool.cmds import _get_flash_info
            except ImportError as exc:
                raise EsptoolFailure(
                    f"the qualified esptool 5.4.0 API is not importable here: {exc}"
                ) from exc
            module = types.SimpleNamespace(
                esptool=esptool, detect_chip=detect_chip,
                _get_flash_info=_get_flash_info,
            )
            from esptool import run_stub as _run_stub
            from esptool.cmds import write_flash as _wf, _set_flash_parameters as _sfp
            module.write_flash = _wf
            module.run_stub = _run_stub
            module._set_flash_parameters = _sfp
        version = getattr(getattr(module, "esptool", None), "__version__", None)
        if version != ESPTOOL_VERSION:
            raise EsptoolFailure(
                f"esptool API backend version {version!r} is not the qualified "
                f"{ESPTOOL_VERSION!r}; run install.py through the packaged setup "
                "wrapper so the CLI and the API backend share one pinned "
                "interpreter (never a silently ambient esptool)"
            )
        return module

    def connect(self, port: str, *, expect: dict[str, Any]) -> dict[str, Any]:
        if self.ports_provider is not None:
            try:
                present = [device for device, _desc in self.ports_provider()]
            except Exception as exc:  # noqa: BLE001 - enumeration loss is fatal
                raise EsptoolFailure(f"cannot confirm port {port}: {exc}") from exc
            if port not in present:
                raise EsptoolFailure(
                    f"port {port} is not currently enumerated; refusing to open a "
                    "write connection on a vanished path"
                )
        lib = self._library()
        self._write_fn = lib.write_flash

        def _native(exc: BaseException, what: str) -> EsptoolFailure:
            """Translate esptool/pyserial errors at the backend boundary:
            operators get the installer's failure codes, never a raw
            traceback (PR-R3 review finding)."""
            if isinstance(exc, EsptoolFailure):
                return exc
            return EsptoolFailure(
                f"esptool {what} failed ({type(exc).__name__}: {exc}); the install "
                "aborted, the board was not reset"
            )

        try:
            self._esp = lib.detect_chip(port, connect_mode="default-reset",
                                        connect_attempts=3)
            chip_name = str(self._esp.CHIP_NAME)  # capture before any close()
            if not re.search(r"esp[- ]?32[- ]?s3", chip_name, re.I):
                raise EsptoolFailure(f"device is not an ESP32-S3: {chip_name!r}")
            # The single-connection rule FIRST: esptool's error recovery can
            # close/reopen/reconnect the port and retry; that path is denied
            # from here on, so any I/O error aborts instead of silently
            # retargeting whatever answers the path now.
            def _deny_reopen(*_args: Any, **_kwargs: Any) -> None:
                raise EsptoolFailure(
                    "esptool attempted to reopen the serial port mid-session; a vdog "
                    "install runs on one verified connection and never reconnects — "
                    "the install aborted, the board was not reset"
                )
            self._esp._port.open = _deny_reopen
            # Flash initialization identical to the pinned CLI (PR-R3 P0):
            # upload the stub flasher (CLI __init__.py:615-617), and because
            # a ROM loader has not enabled the flash interface, attach it
            # explicitly (cmds.py:2054-2057); then configure flash
            # parameters, which esptool requires after attach and before
            # ANY flash read or write (cmds.py:2163-2167).
            if not getattr(self._esp, "IS_STUB", False):
                self._esp = lib.run_stub(self._esp)
            if not getattr(self._esp, "IS_STUB", False):
                self._esp.flash_spi_attach(0)
            lib._set_flash_parameters(self._esp, FLASH_SIZE)
            # Flash size exactly as esptool derives it (display string like
            # "8MB"; PR-R2 finding).
            _vendor, _device, size_str = lib._get_flash_info(self._esp)
            match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KM]i?B)",
                                 str(size_str), re.I)
            if not match:
                raise EsptoolFailure(f"cannot detect flash size from {size_str!r}")
            mult = {"KB": 1024, "MB": 1024 ** 2,
                    "MIB": 1024 ** 2}[match.group(2).upper()]
            flash_bytes = int(float(match.group(1)) * mult)
            # S3 read_mac takes mac_type "BASE_MAC" (anything else returns
            # None — PR-R2 finding) and yields the six MAC bytes.
            raw_mac = self._esp.read_mac()
            if raw_mac is None:
                raise EsptoolFailure(
                    "esptool returned no BASE_MAC on the live connection; identity "
                    "cannot be verified, refusing to write"
                )
            mac = ":".join(f"{b:02x}" for b in bytes(raw_mac))
            security = self._esp.get_security_info()
            # Incomplete security information must never default to
            # "protection off" (PR-R3 P1): both fields are required and
            # range-checked.
            if not isinstance(security, dict) or "flags" not in security \
                    or "flash_crypt_cnt" not in security:
                raise EsptoolFailure(
                    "security report incomplete (missing flags or "
                    "flash_crypt_cnt); refusing to treat unknown protection state "
                    "as unprotected"
                )
            # Strict integer fields (PR B P2): bool is an int subclass and
            # int(0.5) silently truncates — a float or bool in the security
            # report is a malformed report, not a value to coerce.
            for field in ("flags", "flash_crypt_cnt"):
                value = security[field]
                if not isinstance(value, int) or isinstance(value, bool):
                    raise EsptoolFailure(
                        "security report malformed (%s must be an integer, "
                        "got %s %r); refusing to continue"
                        % (field, type(value).__name__, value)
                    )
            flags = security["flags"]
            crypt_cnt = security["flash_crypt_cnt"]
            if not 0 <= flags <= 0xFFFFFFFF or not 0 <= crypt_cnt <= 0xFF:
                raise EsptoolFailure("security report out of range; refusing to continue")
        except Exception as exc:  # noqa: BLE001 - translated, never leaked
            self.close()
            raise _native(exc, "connection/identity") from exc
        # Flash encryption is flash_crypt_cnt ODD BIT PARITY (esptool's own
        # convention at cmds.py:1487), not a flag bit; SECURE_BOOT_EN is
        # bit 0 of flags (PR-R2: bit 1 is SECURE_BOOT_AGGRESSIVE_REVOKE).
        return {
            "chip": "esp32s3",
            "flash_bytes": flash_bytes,
            "mac": mac,
            "secure_boot": bool(flags & 0x1),
            "flash_encryption": bin(crypt_cnt).count("1") % 2 == 1,
        }

    def read_flash(self, port: str, offset: int, size: int) -> bytes:
        if self._esp is None:
            raise EsptoolFailure("install session is not connected")
        try:
            return self._esp.read_flash(offset, size)
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise EsptoolFailure(
                f"esptool read_flash at 0x{offset:x} failed "
                f"({type(exc).__name__}: {exc}); the install aborted, "
                "the board was not reset"
            ) from exc

    def write_flash(self, port: str, offset: int, image_path: Path) -> None:
        if self._esp is None:
            raise EsptoolFailure("install session is not connected")
        try:
            self._write_fn(self._esp, [(offset, str(image_path))],
                           flash_mode=FLASH_MODE, flash_size=FLASH_SIZE,
                           flash_freq=FLASH_FREQ)
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise EsptoolFailure(
                f"esptool write of 0x{offset:x} failed "
                f"({type(exc).__name__}: {exc}); the install aborted, "
                "the board was not reset"
            ) from exc

    def reset(self, port: str) -> None:
        if self._esp is None:
            raise EsptoolFailure("install session is not connected")
        try:
            self._esp.hard_reset()
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise EsptoolFailure(
                f"the single explicit reset failed "
                f"({type(exc).__name__}: {exc}); the board may need a "
                "manual power cycle"
            ) from exc

    def close(self) -> None:
        esp, self._esp = self._esp, None
        if esp is not None:
            try:
                esp._port.close()  # ESPLoader.__exit__ closes exactly this
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass


class VerifiedInstallSession:
    """One live verified connection for preflight classification, operator
    consent, ALL writes and ALL read-back verification (P0, review round 1).

    The connection is opened by classify() — BEFORE consent is ever asked —
    and the explicit port path stays held by this process until finish()
    performs the single reset or an error path closes it without one, so
    "the path" can never silently become a different board mid-flow. The
    connection's own chip/flash/MAC/security are verified before anything
    is written; the MAC must equal the preflight pin (a different ESP32-S3
    that took the path after preflight aborts with zero writes). Any
    failure aborts without resetting. The backend is EsptoolSessionBackend
    in production and an injected fake in tests; protocol:

        connect(port, *, expect) -> {"chip", "flash_bytes", "mac",
                                     "secure_boot", "flash_encryption"}
        read_flash(port, offset, size) -> bytes
        write_flash(port, offset, image_path) -> None
        reset(port) -> None
        close() -> None
    """

    def __init__(self, backend: Any, package: "Package", manifest: dict[str, Any],
                 packaged_table: bytes, log: Callable[[str], None], *,
                 expect: dict[str, Any]) -> None:
        self.backend = backend
        self.package = package
        self.manifest = manifest
        self.packaged_table = packaged_table
        self.log = log
        self.expect = dict(expect)
        self.identity: dict[str, Any] | None = None
        self._closed = False

    # -- transport-shaped surface consumed by classify_device ----------------
    def flash_id(self, port: str) -> tuple[str, int]:
        self._require_open()
        return str(self.identity["chip"]), int(self.identity["flash_bytes"])

    def security_flags(self, port: str) -> dict[str, bool]:
        self._require_open()
        return {"secure_boot": bool(self.identity["secure_boot"]),
                "flash_encryption": bool(self.identity["flash_encryption"])}

    def read_flash(self, port: str, offset: int, size: int) -> bytes:
        self._require_open()
        return self.backend.read_flash(port, offset, size)

    def _require_open(self) -> None:
        if self.identity is None or self._closed:
            raise EsptoolFailure("install session is not connected")

    # -- lifecycle ------------------------------------------------------------
    def classify(self, port: str) -> str:
        self.identity = self.backend.connect(port, expect=self.expect)
        want_mac = str(self.expect.get("mac", "")).lower()
        got_mac = str(self.identity.get("mac", "")).lower()
        if want_mac and got_mac != want_mac:
            self.close()
            raise InstallerError(
                f"refusing: the device answering {port} changed between preflight "
                f"and connect (preflight MAC {want_mac}, connection MAC {got_mac}) "
                "— a same-path device swap is never written to; nothing was written",
                EXIT_REFUSED,
            )
        return classify_device(self, port, self.manifest, self.log,
                               packaged_table=self.packaged_table)

    def write_and_verify(self, port: str) -> list[dict[str, Any]]:
        self._require_open()
        images = {i["role"]: i for i in self.manifest["images"]}
        ordered = [images[role] for role in IMAGE_ROLES]
        # Phase 1 — write every manifest range on the live connection; the
        # stub stays loaded because nothing between writes leaves it.
        for image in ordered:
            self.log(
                f"write: {image['role']} -> 0x{image['offset']:08x} "
                f"({image['size']} B)"
            )
            self.backend.write_flash(
                port, image["offset"], self.package.root / image["file"]
            )
        # Phase 2 — verify every range by read-back on the same connection,
        # BEFORE any reset; short reads are fatal, never "close enough".
        for image in ordered:
            back = self.backend.read_flash(port, image["offset"], image["size"])
            if len(back) != image["size"]:
                raise EsptoolFailure(
                    f"read-back of {image['role']} at 0x{image['offset']:x} returned "
                    f"{len(back)} bytes, expected exactly {image['size']}"
                )
            if sha256_bytes(back) != image["sha256"]:
                raise InstallerError(
                    f"install failed: read-back verification of {image['role']} "
                    f"at 0x{image['offset']:08x} did not match the manifest digest; "
                    "no reset was performed; the board may need a manual power cycle",
                    EXIT_FLASH_FAILED,
                )
        return ordered

    def finish(self, port: str) -> None:
        try:
            self.backend.reset(port)
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self.backend.close()
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass


def _read_exact(transport: EsptoolTransport, port: str, label: str,
                offset: int, size: int) -> bytes:
    """Every device read must return EXACTLY the requested length (P0-1).

    A short read must never be treated as blank, as erased or as matching:
    it means the read (or the board) died mid-transfer and the whole
    classification is untrustworthy.
    """
    data = transport.read_flash(port, offset, size)
    if len(data) != size:
        raise InstallerError(
            f"refusing: {label} read at 0x{offset:x} returned {len(data)} bytes, "
            f"expected exactly {size} — short reads are never treated as blank "
            "or matching",
            EXIT_FLASH_FAILED,
        )
    return data


def _compare_partitions_semantically(got: list[dict[str, Any]],
                                     want: list[dict[str, Any]],
                                     *, where: str) -> None:
    """Field-by-field semantic comparison (P0-1): type, subtype, offset,
    size, flags and label, in table order. The packaged table has already
    passed every validator offline, so any difference is an unknown device
    state and is refused with the offending field named."""
    if len(got) != len(want):
        raise InstallerError(
            f"refusing: {where} has {len(got)} entries, does not match the "
            f"qualified development layout ({len(want)} expected); unknown "
            "layouts are never overwritten",
            EXIT_REFUSED,
        )
    for index, (device, wanted) in enumerate(zip(got, want)):
        for field in ("name", "type", "subtype", "offset", "size", "flags"):
            if device[field] != wanted[field]:
                raise InstallerError(
                    f"refusing: {where} entry {index} ({wanted['name']!r}) "
                    f"{field} {device[field]!r} differs from the qualified "
                    f"layout — the validated packaged value is {wanted[field]!r}; "
                    "only the byte-exact qualified table is replaceable",
                    EXIT_REFUSED,
                )


def classify_device(transport: EsptoolTransport, port: str, manifest: dict[str, Any],
                    log: Callable[[str], None], *,
                    packaged_table: bytes) -> str:
    """Return "factory-blank" or "dev-match"; raise InstallerError otherwise.

    * chip must report esp32s3 and flash 8MB;
    * secure boot / flash encryption must both be off;
    * every device read is exact-length (a short read never reads as blank);
    * demonstrably blank (partition table, otadata and NVS all fully erased)
      may use the explicit factory-install route after confirmation;
    * an existing installation is accepted ONLY when its partition table
      matches the validated packaged table both semantically (type, subtype,
      offset, size, flags, labels, duplicate labels) and byte-for-byte, the
      NVS is provably empty across the FULL partition, and the on-device
      otadata parses strictly as pinned v6.1 select records (P0-2);
    * unreadable/unknown layouts, corrupted records and paired/provisioned
      devices are refused — never assumed blank.
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
    table = _read_exact(transport, port, "on-device partition table",
                        pt_image["offset"], PARTITION_TABLE_MAX_BYTES)
    ota_image = image_by_role["ota_data_initial"]
    otadata = _read_exact(transport, port, "on-device otadata",
                          ota_image["offset"], ota_image["size"])
    nvs = next(e for e in manifest["partition_table"]["entries"] if e["name"] == "nvs")
    # Read the FULL NVS partition: provable blankness (and the refusal of
    # provisioned boards) must not depend on the first sector alone.
    nvs_data = _read_exact(transport, port, "on-device NVS", nvs["offset"], nvs["size"])

    if all(b == 0xFF for b in table):
        if all(b == 0xFF for b in otadata) and all(b == 0xFF for b in nvs_data):
            log("device state: blank factory board (partition table/otadata/NVS erased)")
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
    # P0-1 replacement gate: the packaged table (fully validated offline) is
    # the only thing this device table may equal — semantic field-by-field
    # for an actionable message, then byte-for-byte for the actual decision.
    packaged_entries = parse_partition_entries(
        packaged_table, where="packaged images/partitions.bin"
    )
    _compare_partitions_semantically(entries, packaged_entries,
                                     where="on-device partition table")
    if table != packaged_table:
        raise InstallerError(
            "refusing: the on-device partition table differs byte-for-byte from "
            "the validated packaged table (identical semantic fields with any "
            "other byte — padding, trailer or reserved area — is still an "
            "unqualified table)",
            EXIT_REFUSED,
        )
    # Cross-check against the manifest's CSV-derived mirror as a third
    # independent witness for the semantic fields.
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
        code = CSV_SUBTYPE_CODES.get(str(want["subtype"]))
        want_type = 0 if want["type"] == "app" else 1
        if code is None or code != (want_type, got[name]["subtype"]) \
                or want_type != got[name]["type"]:
            raise InstallerError(
                f"refusing: device partition {name!r} type/subtype "
                f"{got[name]['type']}/{got[name]['subtype']:#x} does not match the "
                f"qualified CSV ({want['type']}/{want['subtype']})",
                EXIT_REFUSED,
            )
        if got[name]["offset"] != want["offset"] or got[name]["size"] != want["size"]:
            raise InstallerError(
                f"refusing: device partition {name!r} at 0x{got[name]['offset']:x}/"
                f"0x{got[name]['size']:x} differs from the qualified layout "
                f"(0x{want['offset']:x}/0x{want['size']:x}) — layout migration is out of scope",
                EXIT_REFUSED,
            )
        if got[name]["flags"] != 0:
            raise InstallerError(
                f"refusing: device partition {name!r} carries flags "
                f"{got[name]['flags']:#x}; the qualified layout is flag-free",
                EXIT_REFUSED,
            )
    if not all(b == 0xFF for b in nvs_data):
        raise InstallerError(
            "refusing: NVS partition contains settings — the board is provisioned/"
            "paired; replacing it needs the separately qualified preservation route "
            "(this installer never touches NVS)",
            EXIT_REFUSED,
        )
    require_ota_data_records(otadata, where="on-device otadata")
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
        session_backend: Any = None,
        esptool_python: str | None = None,
        ports_provider: Callable[[], list[tuple[str, str]]] | None = None,
        input_fn: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
        err: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
    ) -> None:
        self.package = Package(package_root)
        self._transport = transport
        self._session_backend = session_backend
        self.esptool_python = esptool_python
        self.ports_provider = ports_provider or default_ports_provider
        self.input_fn = input_fn
        self.out = out
        self.err = err

    def get_transport(self) -> EsptoolTransport:
        if self._transport is None:
            self._transport = EsptoolTransport(
                resolve_esptool_command(self.esptool_python),
                ports_provider=self.ports_provider,
            )
        return self._transport

    def get_session_backend(self) -> Any:
        """The write-phase backend. Tests inject a fake; production opens the
        single live esptool API connection."""
        if self._session_backend is None:
            self._session_backend = EsptoolSessionBackend(
                ports_provider=self.ports_provider,
            )
        return self._session_backend

    def _require_pinned_esptool(self, transport: EsptoolTransport) -> None:
        """Version gate; a broken/missing esptool is an environment failure,
        never a traceback and never a silent substitute."""
        try:
            ensure_pinned_esptool(transport)
        except EsptoolFailure as exc:
            raise InstallerError(
                f"esptool availability check failed: {exc}", EXIT_ENVIRONMENT
            ) from exc

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
        lines.append(
            "session: ONE live verified esptool 5.4.0 connection carries classification, "
            "consent, every write, every read-back verification and the single reset — "
            "the port stays held by this process the whole time, so the write target is "
            "the verified connection (chip + flash + MAC pinned from preflight + "
            "security-off), never just a path string another board could take over"
        )
        lines.append(
            "preflight: read-only CLI probe on the pinned esptool (one --before "
            "default-reset establishing step, then --before no-reset steps; the "
            "explicit port path is re-verified before every step and a vanished or "
            "renumbered port is never followed)"
        )
        for image in manifest["images"]:
            end = image["offset"] + image["size"] - 1
            lines.append(
                f"write: role={image['role']} file={image['file']} "
                f"range=0x{image['offset']:08x}..0x{end:08x} ({image['size']} B) "
                f"sha256={image['sha256'][:12]}…"
            )
            lines.append(
                f"invoke: esptool API write-flash on the live verified connection "
                f"--flash-mode {FLASH_MODE} --flash-size {FLASH_SIZE} "
                f"--flash-freq {FLASH_FREQ} 0x{image['offset']:x} {image['file']} "
                f"(stub stays loaded between steps; no per-command reconnect)"
            )
        lines.append(
            "read-back verify: each written range is read back on the same connection "
            "(exact length required) and compared to the manifest sha256; on any "
            "mismatch or connection loss NO reset is performed (manual power cycle needed)"
        )
        lines.append(
            "reset: exactly one explicit hard reset on the same connection, only after "
            "every digest matched; it is also the connection's last operation"
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
        self._require_pinned_esptool(transport)
        try:
            chip, size = transport.flash_id(port)
            self.out(f"inspect: chip={chip} flash={size} bytes ({size // (1024 * 1024)}MB)")
            flags = transport.security_flags(port)
            self.out(f"inspect: security={flags}")
            state = classify_device(
                transport, port, manifest, self.out,
                packaged_table=self.package.read(ROLE_FILES["partition_table"]),
            )
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
        self._require_pinned_esptool(transport)
        # Read-only preflight probe (CLI): the MAC read here becomes the
        # identity pin the single live write connection must reproduce.
        try:
            transport.flash_id(port)
            pin_mac = transport.read_mac(port)
        except EsptoolFailure as exc:
            raise InstallerError(f"install failed: {exc}", EXIT_FLASH_FAILED) from exc
        session = VerifiedInstallSession(
            self.get_session_backend(), self.package, manifest,
            self.package.read(ROLE_FILES["partition_table"]), self.out,
            expect={"chip": TARGET, "flash_bytes": EXPECTED_FLASH_BYTES,
                    "mac": pin_mac},
        )
        try:
            # ONE live verified connection: chip, flash, MAC pin and security
            # are verified on it during classification, it stays held through
            # consent, carries every write and every read-back verification,
            # and performs the single reset — or none at all on any failure.
            state = session.classify(port)
            self._consent(manifest, confirm_replace=confirm_replace, state=state)
            ordered = session.write_and_verify(port)
            try:
                session.finish(port)
            except EsptoolFailure as exc:
                raise InstallerError(
                    f"install: every range was written and read-back verified, but the "
                    f"single explicit reset failed ({exc}); the board may need a "
                    "manual power cycle",
                    EXIT_FLASH_FAILED,
                ) from exc
            self.out(
                f"install: OK — build_id={manifest['build_id']} written to ranges "
                + ", ".join(f"0x{i['offset']:x}" for i in ordered)
                + "; device was reset"
            )
        except EsptoolFailure as exc:
            raise InstallerError(f"install failed: {exc}", EXIT_FLASH_FAILED) from exc
        finally:
            session.close()  # idempotent; ensures no handle survives any exit
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
                             "used for the read-only esptool CLI probe (never an "
                             "ambient tool). NOTE: the install session's esptool API "
                             "backend runs in the interpreter executing install.py "
                             "itself and must carry exactly esptool 5.4.0 — run the "
                             "whole installer through install.sh/install.ps1 so both "
                             "share one pinned environment")
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
        # A test-injected transport doubles as the session backend; when
        # None, both resolve to their real production implementations.
        session_backend=transport,
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
