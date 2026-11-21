"""Normative contract helpers for the vdog firmware release artifacts.

This module is the executable mirror of
``contracts/firmware-release-v1.schema.json`` plus the ``vdog-flash-layout-v1``
contract from ``docs/plans/0.9-round1-assignment.md``. It is deliberately
stdlib-only so the packaged installer can reuse the same rules; the JSON
Schema is the human-reviewable contract and the pytest suite cross-checks
that both accept/reject the same fixtures.

Specs: docs/plans/0.9-firmware-ci-release.md sections 3-4,
docs/plans/0.9-round1-assignment.md (interface contracts).
"""

from __future__ import annotations

import hashlib
import re
import struct
from typing import Any

# ---------------------------------------------------------------------------
# Frozen contract constants (round-1 baseline, docs/toolchain.md, 0.2 pins)
# ---------------------------------------------------------------------------

RELEASE_SCHEMA = "firmware-release-v1"
FLASH_LAYOUT_SCHEMA = "vdog-flash-layout-v1"
BUILD_METADATA_SCHEMA = "vdog-build-metadata-v1"

PACKAGE_FORMAT_VERSION = 1
PRODUCT = "vdog"
PRODUCT_SLUG = "vdog-xiao-sense"
HARDWARE_CLASS = "seeed-xiao-esp32s3-sense"
BOARD = "seeed_xiao_esp32s3"
ENVIRONMENT = "vdog_xiao_sense_proto"
TARGET = "esp32s3"
EXPECTED_FLASH_BYTES = 8_388_608
FIRMWARE_VERSION = "0.2.0-proto"
RELEASE_CHANNEL = "prototype"

TOOLCHAIN_PLATFORMIO_CORE = "6.2.0"
TOOLCHAIN_PLATFORM = "platformio/espressif32@8.0.0"
TOOLCHAIN_IDF_VERSION = "v6.1.0"
TOOLCHAIN_ESPTOOL_VERSION = "5.4.0"

FLASH_MODE = "dio"
FLASH_SIZE = "8MB"
FLASH_FREQ = "80m"

IMAGE_ROLES: tuple[str, ...] = (
    "bootloader",
    "partition_table",
    "ota_data_initial",
    "application",
)
#: Canonical PlatformIO build-dir filenames per role (never glob by basename).
ROLE_BUILD_FILE: dict[str, str] = {
    "bootloader": "bootloader.bin",
    "partition_table": "partitions.bin",
    "ota_data_initial": "ota_data_initial.bin",
    "application": "firmware.bin",
}
#: Builder-template (IDF) names observed in generated ``flasher_args.json``
#: that PlatformIO relocates/renames to the canonical root files.
ROLE_BUILDER_TEMPLATE_FILES: dict[str, tuple[str, ...]] = {
    "bootloader": ("bootloader.bin", "bootloader/bootloader.bin"),
    "partition_table": ("partitions.bin", "partition_table/partition-table.bin"),
    "ota_data_initial": ("ota_data_initial.bin",),
    "application": ("firmware.bin", "vdog_firmware.bin"),
}

#: Fixed section-1 payload set (master plan section 4), relative to the ZIP
#: root. ``manifest.json`` and ``SHA256SUMS`` are excluded from manifest
#: self-hashing; ``SHA256SUMS`` covers every payload file plus ``manifest.json``
#: and excludes itself.
PACKAGE_REQUIRED_FILES: frozenset[str] = frozenset(
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
#: Files excluded from manifest.json self-referential hashing (section 4).
PACKAGE_SELF_EXCLUDED_FROM_MANIFEST: frozenset[str] = frozenset(
    {"manifest.json", "SHA256SUMS"}
)
#: File excluded from SHA256SUMS self-hashing (section 4).
SHA256SUMS_FILE = "SHA256SUMS"
MANIFEST_FILE = "manifest.json"
VERSION_FILE = "VERSION.json"
FLASH_LAYOUT_FILE = "flash/flash-layout.json"
FLASH_ARGS_FILE = "flash/flash_args"
PARTITION_TABLE_FILE = "flash/partitions.csv"

FULL_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
SHA12_RE = re.compile(r"\A[0-9a-f]{12}\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
BUILD_ID_RE = re.compile(r"\A(?:pr-[0-9]{1,9}-[0-9a-f]{12}|main-[0-9a-f]{12}|local)\Z")
BUILD_ID_TOKEN_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
TAG_RE = re.compile(r"\Afirmware-main-[0-9a-f]{12}\Z")

SOURCE_KINDS: tuple[str, ...] = ("pr", "main", "local")
FLASH_MODES: tuple[str, ...] = ("dio", "qio", "dout", "qout")
FLASH_SIZES: tuple[str, ...] = ("1MB", "2MB", "4MB", "8MB", "16MB")
FLASH_FREQS: tuple[str, ...] = (
    "20m", "26m", "40m", "48m", "60m", "80m", "120m",
)
CSV_SUBTYPES: frozenset[str] = frozenset(
    {
        "boot",
        "ota_0", "ota_1", "ota_2", "ota_3", "ota_4", "ota_5",
        "ota_6", "ota_7", "ota_8", "ota_9", "ota_10", "ota_11",
        "ota_12", "ota_13", "ota_14", "ota_15",
        "nvs", "ota", "phy", "coredump", "nvs_key", "fat", "spiffs", "any",
    }
)

# ESP image container facts (verified against esptool 5.4.0, the pinned
# tool-esptool@2.50400.0 line, and the 0.2 baseline build bytes).
ESP_IMAGE_MAGIC = 0xE9
ESP_EXT_HEADER_LEN = 16
ESP_COMMON_HEADER_LEN = 8
ESP_TOTAL_HEADER_LEN = ESP_COMMON_HEADER_LEN + ESP_EXT_HEADER_LEN
ESP_SEG_HEADER_LEN = 8
ESP_SHA256_LEN = 32
ESP_CHECKSUM_MAGIC = 0xEF
ESP32S3_IMAGE_CHIP_ID = 0x09
ESP_MAX_SEGMENTS = 16
PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_MAX_BYTES = 0xC00
PARTITION_ENTRY_MAGIC = 0x50AA  # on-disk bytes AA 50 (u16 little-endian)
PARTITION_ENTRY_SIZE = 32
OTA_DATA_MAGIC_BYTE = 0xC9
OTA_DATA_SECTOR_SIZE = 0x1000

#: CSV subtype name -> (type, subtype) numeric pair used in the binary table.
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


class ContractError(ValueError):
    """Raised for contract violations with a deterministic message list."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) if errors else "contract error")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


# ---------------------------------------------------------------------------
# Path normalization (master plan section 4: normalized relative paths)
# ---------------------------------------------------------------------------


def validate_relative_package_path(path: Any, *, where: str) -> list[str]:
    """Return contract errors for one manifest/ZIP-relative path."""
    if not _is_str(path):
        return [f"{where}: must be a string"]
    errors: list[str] = []
    if path == "" or len(path) > 255:
        errors.append(f"{where}: length {len(path)} outside 1..255")
        return errors
    if path.startswith("/") or "\\" in path:
        errors.append(f"{where}: absolute or backslash path {path!r}")
        return errors
    if re.match(r"^[A-Za-z]:", path):
        errors.append(f"{where}: drive-qualified path {path!r}")
        return errors
    if path.endswith("/"):
        errors.append(f"{where}: trailing separator in {path!r}")
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            errors.append(f"{where}: unsafe segment {segment!r} in {path!r}")
        elif not re.fullmatch(r"[A-Za-z0-9 ._\-]+", segment):
            errors.append(f"{where}: illegal characters in segment {segment!r}")
    return errors


def normalize_package_path(path: str) -> str:
    """Normalize and validate one package-relative path.

    Raises ContractError on any escape, absolute path, dot segment, backslash,
    drive letter, or empty segment.
    """
    errors = validate_relative_package_path(path, where="path")
    if errors:
        raise ContractError(errors)
    return path


# ---------------------------------------------------------------------------
# vdog-build-metadata-v1 (consumed; produced by the firmware packet)
# ---------------------------------------------------------------------------


def validate_build_metadata(doc: Any) -> list[str]:
    """Validate a vdog-build-metadata-v1 document; return error strings."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["build metadata: document must be a JSON object"]
    if doc.get("schema") != BUILD_METADATA_SCHEMA:
        errors.append(
            f"build metadata: schema must be {BUILD_METADATA_SCHEMA!r}, "
            f"got {doc.get('schema')!r}"
        )
    if doc.get("firmware_version") != FIRMWARE_VERSION:
        errors.append(
            f"build metadata: firmware_version must be {FIRMWARE_VERSION!r}, "
            f"got {doc.get('firmware_version')!r}"
        )
    if doc.get("environment") != ENVIRONMENT:
        errors.append(
            f"build metadata: environment must be {ENVIRONMENT!r}, "
            f"got {doc.get('environment')!r}"
        )
    if doc.get("platform") != TOOLCHAIN_PLATFORM:
        errors.append(
            f"build metadata: platform must be {TOOLCHAIN_PLATFORM!r}, "
            f"got {doc.get('platform')!r}"
        )
    if doc.get("idf_version") != TOOLCHAIN_IDF_VERSION:
        errors.append(
            f"build metadata: idf_version must be {TOOLCHAIN_IDF_VERSION!r}, "
            f"got {doc.get('idf_version')!r}"
        )
    if doc.get("esptool_version") != TOOLCHAIN_ESPTOOL_VERSION:
        errors.append(
            f"build metadata: esptool_version must be "
            f"{TOOLCHAIN_ESPTOOL_VERSION!r}, got {doc.get('esptool_version')!r}"
        )
    errors.extend(validate_source_sha(doc.get("source_sha"), where="build metadata.source_sha"))
    errors.extend(validate_build_id_token(doc.get("build_id"), where="build metadata.build_id"))
    return errors


def validate_source_sha(value: Any, *, where: str) -> list[str]:
    """Full 40-hex object ID or the literal ``local`` (round-1 addendum)."""
    if value == "local":
        return []
    if _is_str(value) and FULL_SHA_RE.match(value):
        return []
    return [f"{where}: must be a full 40-hex SHA or 'local', got {value!r}"]


def validate_build_id_token(value: Any, *, where: str) -> list[str]:
    """Build ID token charset ``[A-Za-z0-9._-]{1,64}`` (round-1 addendum)."""
    if value == "local":
        return []
    if _is_str(value) and BUILD_ID_TOKEN_RE.match(value):
        return []
    return [f"{where}: must match [A-Za-z0-9._-]{{1,64}} or 'local', got {value!r}"]


def validate_build_id(value: Any, *, where: str) -> list[str]:
    """Release-contract build ID: ``pr-<n>-<sha12>`` / ``main-<sha12>`` / ``local``."""
    if not _is_str(value) or not BUILD_ID_RE.match(value):
        return [
            f"{where}: must be pr-<n>-<sha12>, main-<sha12> or 'local', "
            f"got {value!r}"
        ]
    return []


# ---------------------------------------------------------------------------
# firmware-release-v1 manifest validation
# ---------------------------------------------------------------------------


def short_sha(sha40: str) -> str:
    """First 12 hex characters of a full SHA (names only; full SHA kept in metadata)."""
    if sha40 == "local":
        return "local"
    if not FULL_SHA_RE.match(sha40):
        raise ContractError([f"short_sha: {sha40!r} is not a full 40-hex SHA"])
    return sha40[:12]


def derive_build_id(kind: str, *, pr_number: int | None, sha: str) -> str:
    """Derive the release build ID per master plan section 3."""
    if kind == "local":
        return "local"
    if kind == "pr":
        if not _is_int(pr_number) or pr_number < 1:
            raise ContractError([f"derive_build_id: invalid pr_number {pr_number!r}"])
        return f"pr-{pr_number}-{short_sha(sha)}"
    if kind == "main":
        return f"main-{short_sha(sha)}"
    raise ContractError([f"derive_build_id: unknown kind {kind!r}"])


def derive_tag(kind: str, sha: str) -> str | None:
    """Git tag for main releases only (master plan section 3)."""
    if kind == "main":
        return f"firmware-main-{short_sha(sha)}"
    return None


def _check_constants(doc: dict[str, Any], errors: list[str]) -> None:
    const_fields = {
        "schema": RELEASE_SCHEMA,
        "package_format_version": PACKAGE_FORMAT_VERSION,
        "product": PRODUCT,
        "product_slug": PRODUCT_SLUG,
        "hardware_class": HARDWARE_CLASS,
        "board": BOARD,
        "environment": ENVIRONMENT,
        "target": TARGET,
        "expected_flash_bytes": EXPECTED_FLASH_BYTES,
        "firmware_version": FIRMWARE_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "hardware_verified": False,
        "recording_available": False,
        "device_ota_available": False,
    }
    for field, want in const_fields.items():
        got = doc.get(field)
        if got != want or type(got) is not type(want):
            errors.append(f"manifest.{field}: must be {want!r}, got {got!r}")


def validate_manifest(doc: Any) -> list[str]:
    """Validate a ``firmware-release-v1`` manifest document.

    Returns a deterministic list of error strings (empty when valid). Mirrors
    contracts/firmware-release-v1.schema.json plus the section 4 coverage
    rules (self-exclusion of manifest.json/SHA256SUMS, role coverage,
    identity/tag/build-ID consistency).
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["manifest: document must be a JSON object"]

    for field in (
        "schema", "package_format_version", "product", "product_slug",
        "hardware_class", "board", "environment", "target",
        "expected_flash_bytes", "firmware_version", "release_channel",
        "hardware_verified", "recording_available", "device_ota_available",
        "source", "build_id", "tag", "ci", "toolchain", "flash", "images",
        "partition_table", "flash_layout_file", "files",
    ):
        if field not in doc:
            errors.append(f"manifest: missing required field {field!r}")
    for field in doc:
        if field not in {
            "schema", "package_format_version", "product", "product_slug",
            "hardware_class", "board", "environment", "target",
            "expected_flash_bytes", "firmware_version", "release_channel",
            "hardware_verified", "recording_available", "device_ota_available",
            "source", "build_id", "tag", "ci", "toolchain", "flash", "images",
            "partition_table", "flash_layout_file", "files",
        }:
            errors.append(f"manifest: unknown field {field!r}")

    _check_constants(doc, errors)

    errors.extend(_validate_source(doc.get("source")))

    errors.extend(validate_build_id(doc.get("build_id"), where="manifest.build_id"))

    tag = doc.get("tag")
    if tag is not None:
        if not _is_str(tag) or not TAG_RE.match(tag):
            errors.append(
                f"manifest.tag: must be null or firmware-main-<sha12>, got {tag!r}"
            )

    errors.extend(_validate_ci(doc.get("ci")))
    errors.extend(_validate_toolchain(doc.get("toolchain")))
    errors.extend(_validate_flash(doc.get("flash")))
    errors.extend(_validate_images(doc.get("images")))
    images = doc.get("images")
    if isinstance(images, list):
        flash = doc.get("flash")
        flash_bytes = (
            flash.get("size_bytes")
            if isinstance(flash, dict) and _is_int(flash.get("size_bytes"))
            else EXPECTED_FLASH_BYTES
        )
        errors.extend(check_segment_overlaps(images, where="manifest.images"))
        errors.extend(check_segments_fit(images, where="manifest.images",
                                           flash_bytes=flash_bytes))
    errors.extend(_validate_partition_table(doc.get("partition_table")))

    flf = doc.get("flash_layout_file")
    errors.extend(
        validate_relative_package_path(flf, where="manifest.flash_layout_file")
    )
    if flf != FLASH_LAYOUT_FILE:
        errors.append(
            f"manifest.flash_layout_file: must be {FLASH_LAYOUT_FILE!r}, got {flf!r}"
        )

    errors.extend(_validate_files(doc))
    errors.extend(_validate_identity_consistency(doc))
    return errors


def _validate_source(source: Any) -> list[str]:
    if not isinstance(source, dict):
        return ["manifest.source: must be an object"]
    errors: list[str] = []
    for field in ("kind", "sha", "sha_short", "dirty"):
        if field not in source:
            errors.append(f"manifest.source: missing {field!r}")
    for field in source:
        if field not in {"kind", "sha", "sha_short", "pr_number", "base_sha", "dirty"}:
            errors.append(f"manifest.source: unknown field {field!r}")
    kind = source.get("kind")
    if kind not in SOURCE_KINDS:
        errors.append(f"manifest.source.kind: must be one of {SOURCE_KINDS}, got {kind!r}")
        return errors
    if source.get("dirty") is not False:
        errors.append(
            f"manifest.source.dirty: must be false, got {source.get('dirty')!r}"
        )
    sha = source.get("sha")
    sha_short = source.get("sha_short")
    if kind == "local":
        if sha != "local":
            errors.append(f"manifest.source.sha: local kind requires 'local', got {sha!r}")
        if sha_short != "local":
            errors.append(
                f"manifest.source.sha_short: local kind requires 'local', got {sha_short!r}"
            )
        if source.get("pr_number") is not None:
            errors.append("manifest.source.pr_number: must be null for local kind")
        if source.get("base_sha") is not None:
            errors.append("manifest.source.base_sha: must be null for local kind")
        return errors
    if not _is_str(sha) or not FULL_SHA_RE.match(sha):
        errors.append(f"manifest.source.sha: {kind} kind requires full 40-hex SHA, got {sha!r}")
        return errors
    if not _is_str(sha_short) or not SHA12_RE.match(sha_short):
        errors.append(
            f"manifest.source.sha_short: requires 12-hex short SHA, got {sha_short!r}"
        )
    elif sha[:12] != sha_short:
        errors.append(
            f"manifest.source.sha_short: {sha_short!r} does not match sha prefix {sha[:12]!r}"
        )
    if kind == "pr":
        pr = source.get("pr_number")
        if not _is_int(pr) or not (1 <= pr <= 2_147_483_647):
            errors.append(
                f"manifest.source.pr_number: pr kind requires integer >= 1, got {pr!r}"
            )
        base = source.get("base_sha")
        if not _is_str(base) or not FULL_SHA_RE.match(base):
            errors.append(
                f"manifest.source.base_sha: pr kind requires full 40-hex base SHA, got {base!r}"
            )
        elif _is_str(sha) and FULL_SHA_RE.match(sha) and base == sha:
            errors.append("manifest.source.base_sha: base SHA must differ from head SHA")
    else:  # main
        if "pr_number" in source and source.get("pr_number") is not None:
            errors.append("manifest.source.pr_number: must be null for main kind")
        if "base_sha" in source and source.get("base_sha") is not None:
            errors.append("manifest.source.base_sha: must be null for main kind")
    return errors


def _validate_ci(ci: Any) -> list[str]:
    if ci is None:
        return []
    if not isinstance(ci, dict):
        return ["manifest.ci: must be an object or null"]
    errors: list[str] = []
    if set(ci) != {"run_id", "attempt"}:
        errors.append(f"manifest.ci: must have exactly run_id/attempt, got {sorted(ci)}")
    for field in ("run_id", "attempt"):
        value = ci.get(field)
        if not _is_int(value) or value < 1:
            errors.append(f"manifest.ci.{field}: must be an integer >= 1, got {value!r}")
    return errors


def _validate_toolchain(toolchain: Any) -> list[str]:
    if not isinstance(toolchain, dict):
        return ["manifest.toolchain: must be an object"]
    errors: list[str] = []
    if set(toolchain) != {
        "platformio_core", "platform", "idf_version", "esptool_version"
    }:
        errors.append(
            "manifest.toolchain: must have exactly platformio_core/platform/"
            f"idf_version/esptool_version, got {sorted(toolchain)}"
        )
    pins = {
        "platform": TOOLCHAIN_PLATFORM,
        "esptool_version": TOOLCHAIN_ESPTOOL_VERSION,
        "idf_version": TOOLCHAIN_IDF_VERSION,
    }
    for field, want in pins.items():
        if toolchain.get(field) != want:
            errors.append(
                f"manifest.toolchain.{field}: must be {want!r}, got {toolchain.get(field)!r}"
            )
    pcore = toolchain.get("platformio_core")
    if not _is_str(pcore) or not (1 <= len(pcore) <= 64):
        errors.append(
            f"manifest.toolchain.platformio_core: must be a 1..64 char string, got {pcore!r}"
        )
    return errors


def _validate_flash(flash: Any) -> list[str]:
    if not isinstance(flash, dict):
        return ["manifest.flash: must be an object"]
    errors: list[str] = []
    if set(flash) != {"mode", "size", "freq", "size_bytes"}:
        errors.append(f"manifest.flash: keys must be mode/size/freq/size_bytes, got {sorted(flash)}")
    # The round-1 baseline is frozen: the release contract only ever carries
    # the qualified dio/8MB/80m/8388608 upload parameters. The allowed-value
    # enums stay as documentation of what esptool accepts at all.
    pins = {
        "mode": (FLASH_MODE, FLASH_MODES),
        "size": (FLASH_SIZE, FLASH_SIZES),
        "freq": (FLASH_FREQ, FLASH_FREQS),
        "size_bytes": (EXPECTED_FLASH_BYTES, None),
    }
    for field, (want, enum) in pins.items():
        value = flash.get(field)
        if enum is not None and value not in enum:
            errors.append(f"manifest.flash.{field}: invalid {value!r}")
        elif enum is None and (not _is_int(value) or value < 1):
            errors.append(f"manifest.flash.{field}: must be an integer >= 1, got {value!r}")
        elif value != want:
            errors.append(
                f"manifest.flash.{field}: must be {want!r} (frozen baseline), got {value!r}"
            )
    return errors


def _validate_images(images: Any) -> list[str]:
    if not isinstance(images, list):
        return ["manifest.images: must be an array"]
    errors: list[str] = []
    if len(images) != 4:
        errors.append(f"manifest.images: must contain exactly 4 segments, got {len(images)}")
    seen: set[str] = set()
    for index, image in enumerate(images):
        where = f"manifest.images[{index}]"
        if not isinstance(image, dict):
            errors.append(f"{where}: must be an object")
            continue
        if set(image) != {"role", "file", "offset", "size", "sha256"}:
            errors.append(f"{where}: keys must be role/file/offset/size/sha256, got {sorted(image)}")
        role = image.get("role")
        if role not in IMAGE_ROLES:
            errors.append(f"{where}.role: invalid {role!r}")
        elif role in seen:
            errors.append(f"{where}.role: duplicate role {role!r}")
        else:
            seen.add(role)
            want_file = f"images/{ROLE_BUILD_FILE[role]}"
            if image.get("file") != want_file:
                errors.append(f"{where}.file: must be {want_file!r}, got {image.get('file')!r}")
            else:
                errors.extend(validate_relative_package_path(image.get("file"), where=f"{where}.file"))
        for field in ("offset", "size"):
            value = image.get(field)
            if not _is_int(value) or value < (0 if field == "offset" else 1):
                errors.append(f"{where}.{field}: invalid {value!r}")
        digest = image.get("sha256")
        if not _is_str(digest) or not SHA256_RE.match(digest):
            errors.append(f"{where}.sha256: must be 64-hex, got {digest!r}")
    missing = set(IMAGE_ROLES) - seen
    if missing:
        errors.append(f"manifest.images: missing roles {sorted(missing)}")
    return errors


def _validate_partition_table(pt: Any) -> list[str]:
    if not isinstance(pt, dict):
        return ["manifest.partition_table: must be an object"]
    errors: list[str] = []
    if set(pt) != {"file", "sha256", "size", "entries"}:
        errors.append(
            f"manifest.partition_table: keys must be file/sha256/size/entries, got {sorted(pt)}"
        )
    if pt.get("file") != PARTITION_TABLE_FILE:
        errors.append(
            f"manifest.partition_table.file: must be {PARTITION_TABLE_FILE!r}, got {pt.get('file')!r}"
        )
    digest = pt.get("sha256")
    if not _is_str(digest) or not SHA256_RE.match(digest):
        errors.append(f"manifest.partition_table.sha256: must be 64-hex, got {digest!r}")
    size = pt.get("size")
    if not _is_int(size) or size < 1:
        errors.append(f"manifest.partition_table.size: must be >= 1, got {size!r}")
    entries = pt.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("manifest.partition_table.entries: must be a non-empty array")
        return errors
    for index, entry in enumerate(entries):
        where = f"manifest.partition_table.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        if set(entry) != {"name", "type", "subtype", "offset", "size"}:
            errors.append(f"{where}: keys must be name/type/subtype/offset/size, got {sorted(entry)}")
        name = entry.get("name")
        if not _is_str(name) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,16}", name or ""):
            errors.append(f"{where}.name: invalid {name!r}")
        if entry.get("type") not in ("app", "data"):
            errors.append(f"{where}.type: must be app/data, got {entry.get('type')!r}")
        if entry.get("subtype") not in CSV_SUBTYPES:
            errors.append(f"{where}.subtype: invalid {entry.get('subtype')!r}")
        for field in ("offset", "size"):
            value = entry.get(field)
            if not _is_int(value) or value < (0 if field == "offset" else 1):
                errors.append(f"{where}.{field}: invalid {value!r}")
    return errors


def _validate_files(doc: dict[str, Any]) -> list[str]:
    files = doc.get("files")
    if not isinstance(files, list):
        return ["manifest.files: must be an array"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(files):
        where = f"manifest.files[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        if set(entry) != {"path", "size", "sha256"}:
            errors.append(f"{where}: keys must be path/size/sha256, got {sorted(entry)}")
        path = entry.get("path")
        path_errors = validate_relative_package_path(path, where=f"{where}.path")
        errors.extend(path_errors)
        if _is_str(path):
            if path in seen:
                errors.append(f"{where}.path: duplicate {path!r}")
            seen.add(path)
            if path in PACKAGE_SELF_EXCLUDED_FROM_MANIFEST:
                errors.append(
                    f"{where}.path: {path!r} must be excluded from manifest self-hashing"
                )
            elif path not in PACKAGE_REQUIRED_FILES:
                errors.append(f"{where}.path: {path!r} is not part of the section 4 payload")
        size = entry.get("size")
        if not _is_int(size) or size < 0:
            errors.append(f"{where}.size: must be >= 0, got {size!r}")
        digest = entry.get("sha256")
        if not _is_str(digest) or not SHA256_RE.match(digest):
            errors.append(f"{where}.sha256: must be 64-hex, got {digest!r}")
    # Section 4 coverage: every payload file except manifest.json/SHA256SUMS.
    want = set(PACKAGE_REQUIRED_FILES) - set(PACKAGE_SELF_EXCLUDED_FROM_MANIFEST)
    missing = want - seen
    if missing:
        errors.append(f"manifest.files: missing payload coverage for {sorted(missing)}")
    # images[] and partition_table references must themselves be covered.
    images = doc.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and _is_str(image.get("file")):
                if image["file"] not in seen:
                    errors.append(
                        f"manifest.files: image {image['file']!r} lacks size+SHA256 coverage"
                    )
    return errors


def _validate_identity_consistency(doc: dict[str, Any]) -> list[str]:
    """Cross-field identity rules: build ID/tag vs source kind and SHA."""
    errors: list[str] = []
    source = doc.get("source")
    build_id = doc.get("build_id")
    tag = doc.get("tag")
    if not isinstance(source, dict) or not _is_str(build_id):
        return errors
    kind = source.get("kind")
    sha = source.get("sha")
    if kind == "pr":
        want = None
        if _is_int(source.get("pr_number")) and _is_str(sha) and FULL_SHA_RE.match(sha):
            want = f"pr-{source['pr_number']}-{sha[:12]}"
        if want is not None and build_id != want:
            errors.append(f"manifest.build_id: {build_id!r} does not match pr identity {want!r}")
        if tag is not None:
            errors.append("manifest.tag: PR releases must not carry a tag")
    elif kind == "main":
        want = None
        if _is_str(sha) and FULL_SHA_RE.match(sha):
            want = f"main-{sha[:12]}"
        if want is not None and build_id != want:
            errors.append(f"manifest.build_id: {build_id!r} does not match main identity {want!r}")
        if tag is None:
            errors.append("manifest.tag: main releases must carry firmware-main-<sha12>")
        elif _is_str(sha) and FULL_SHA_RE.match(sha) and tag != f"firmware-main-{sha[:12]}":
            errors.append(
                f"manifest.tag: {tag!r} does not match main SHA identity {sha[:12]!r}"
            )
    else:  # local
        if build_id != "local":
            errors.append(f"manifest.build_id: local kind requires 'local', got {build_id!r}")
        if tag is not None:
            errors.append("manifest.tag: local builds must not carry a tag")
        if doc.get("ci") is not None:
            errors.append(
                f"manifest.ci: local builds are unpublishable and must not carry "
                f"CI identity, got {doc.get('ci')!r}"
            )
    if kind == "main" and tag is not None and not _is_str(tag):
        errors.append(f"manifest.tag: must be string for main kind, got {tag!r}")
    return errors


# ---------------------------------------------------------------------------
# vdog-flash-layout-v1
# ---------------------------------------------------------------------------


def validate_flash_layout(doc: Any) -> list[str]:
    """Validate a vdog-flash-layout-v1 document; return error strings."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["flash layout: document must be a JSON object"]
    for field in ("schema", "target", "flash_size_bytes", "upload", "segments"):
        if field not in doc:
            errors.append(f"flash layout: missing required field {field!r}")
    for field in doc:
        if field not in {"schema", "target", "flash_size_bytes", "upload", "segments"}:
            errors.append(f"flash layout: unknown field {field!r}")
    if doc.get("schema") != FLASH_LAYOUT_SCHEMA:
        errors.append(f"flash layout: schema must be {FLASH_LAYOUT_SCHEMA!r}, got {doc.get('schema')!r}")
    if doc.get("target") != TARGET:
        errors.append(f"flash layout: target must be {TARGET!r}, got {doc.get('target')!r}")
    if doc.get("flash_size_bytes") != EXPECTED_FLASH_BYTES:
        errors.append(
            f"flash layout: flash_size_bytes must be {EXPECTED_FLASH_BYTES}, "
            f"got {doc.get('flash_size_bytes')!r}"
        )
    upload = doc.get("upload")
    if not isinstance(upload, dict) or set(upload) != {"flash_mode", "flash_size", "flash_freq"}:
        errors.append(f"flash layout: upload must be flash_mode/flash_size/flash_freq, got {upload!r}")
    else:
        # Frozen round-1 baseline: dio / 8MB / 80m.
        pins = {
            "flash_mode": (FLASH_MODE, FLASH_MODES),
            "flash_size": (FLASH_SIZE, FLASH_SIZES),
            "flash_freq": (FLASH_FREQ, FLASH_FREQS),
        }
        for field, (want, enum) in pins.items():
            value = upload.get(field)
            if value not in enum:
                errors.append(f"flash layout: upload.{field} invalid {value!r}")
            elif value != want:
                errors.append(
                    f"flash layout: upload.{field} must be {want!r} "
                    f"(frozen baseline), got {value!r}"
                )
    segments = doc.get("segments")
    if not isinstance(segments, list):
        errors.append("flash layout: segments must be an array")
        return errors
    if len(segments) != 4:
        errors.append(f"flash layout: segments must contain exactly 4 entries, got {len(segments)}")
    seen: set[str] = set()
    for index, seg in enumerate(segments):
        where = f"flash layout segments[{index}]"
        if not isinstance(seg, dict):
            errors.append(f"{where}: must be an object")
            continue
        if set(seg) != {"role", "file", "offset", "size", "sha256"}:
            errors.append(f"{where}: keys must be role/file/offset/size/sha256, got {sorted(seg)}")
        role = seg.get("role")
        if role not in IMAGE_ROLES:
            errors.append(f"{where}: invalid role {role!r}")
        elif role in seen:
            errors.append(f"{where}: duplicate role {role!r}")
        else:
            seen.add(role)
            want_file = f"images/{ROLE_BUILD_FILE[role]}"
            if seg.get("file") != want_file:
                errors.append(f"{where}: file must be {want_file!r}, got {seg.get('file')!r}")
            errors.extend(validate_relative_package_path(seg.get("file"), where=f"{where}.file"))
        if not _is_int(seg.get("offset")) or seg["offset"] < 0:
            errors.append(f"{where}: invalid offset {seg.get('offset')!r}")
        if not _is_int(seg.get("size")) or seg["size"] < 1:
            errors.append(f"{where}: invalid size {seg.get('size')!r}")
        digest = seg.get("sha256")
        if not _is_str(digest) or not SHA256_RE.match(digest):
            errors.append(f"{where}: sha256 must be 64-hex, got {digest!r}")
    missing = set(IMAGE_ROLES) - seen
    if missing:
        errors.append(f"flash layout: missing roles {sorted(missing)}")
    if isinstance(segments, list):
        errors.extend(check_segment_overlaps(segments, where="flash layout"))
        errors.extend(check_segments_fit(segments, where="flash layout"))
    return errors


def check_segment_overlaps(segments: list[dict[str, Any]], *, where: str) -> list[str]:
    errors: list[str] = []
    valid = [
        s for s in segments
        if isinstance(s, dict) and _is_int(s.get("offset")) and _is_int(s.get("size"))
    ]
    ordered = sorted(valid, key=lambda s: (s["offset"], s["size"]))
    for left, right in zip(ordered, ordered[1:]):
        if right["offset"] < left["offset"] + left["size"]:
            errors.append(
                f"{where}: segment {left.get('role')!r}@0x{left['offset']:x}+0x{left['size']:x} "
                f"overlaps {right.get('role')!r}@0x{right['offset']:x}"
            )
    return errors


def check_segments_fit(segments: list[dict[str, Any]], *, where: str,
                       flash_bytes: int = EXPECTED_FLASH_BYTES) -> list[str]:
    errors: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        offset, size = seg.get("offset"), seg.get("size")
        if _is_int(offset) and _is_int(size) and offset + size > flash_bytes:
            errors.append(
                f"{where}: segment {seg.get('role')!r}@0x{offset:x}+0x{size:x} "
                f"exceeds flash size 0x{flash_bytes:x}"
            )
    return errors


# ---------------------------------------------------------------------------
# Partition table (binary + CSV) parsing — formats verified byte-for-byte
# against the 0.2 baseline build and esptool 5.4.0.
# ---------------------------------------------------------------------------


class PartitionEntry:
    __slots__ = ("name", "type", "subtype", "offset", "size", "label_bytes")

    def __init__(self, name: str, type_: int, subtype: int, offset: int, size: int,
                 label_bytes: bytes) -> None:
        self.name = name
        self.type = type_
        self.subtype = subtype
        self.offset = offset
        self.size = size
        self.label_bytes = label_bytes

    def as_dict(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "type": self.type,
            "subtype": self.subtype,
            "offset": self.offset,
            "size": self.size,
        }

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PartitionEntry)
            and (self.name, self.type, self.subtype, self.offset, self.size)
            == (other.name, other.type, other.subtype, other.offset, other.size)
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"PartitionEntry({self.name!r}, type={self.type}, subtype={self.subtype:#x}, "
            f"offset={self.offset:#x}, size={self.size:#x})"
        )


def parse_partition_table_binary(
    data: bytes,
    *,
    where: str = "partition table",
    flash_bytes: int = EXPECTED_FLASH_BYTES,
) -> list[PartitionEntry]:
    """Parse the ESP-IDF partition-table binary; raise ContractError on any anomaly.

    Entry layout (verified against the pinned builder output): 32-byte entries,
    magic u16 0xAA50 at +0, type u8 at +2, subtype u8 at +3, offset u32 LE at
    +4, size u32 LE at +8, label[16] at +12, flags u32 at +28 (must be zero for
    this layout). Parsing stops at the first non-magic slot; the remainder must
    be erased (0xFF) except for the builder trailer inside the first free
    slot, whose 16-byte MD5 over the entry bytes (when present) is verified.
    """
    errors: list[str] = []
    entries: list[PartitionEntry] = []
    if len(data) != PARTITION_TABLE_MAX_BYTES:
        errors.append(
            f"{where}: size {len(data)} != {PARTITION_TABLE_MAX_BYTES} (max table)"
        )
    end = min(len(data), PARTITION_TABLE_MAX_BYTES)
    count = 0
    while (count + 1) * PARTITION_ENTRY_SIZE <= end:
        entry = data[count * PARTITION_ENTRY_SIZE:(count + 1) * PARTITION_ENTRY_SIZE]
        magic = struct.unpack_from("<H", entry, 0)[0]
        if magic != PARTITION_ENTRY_MAGIC:
            break
        type_ = entry[2]
        subtype = entry[3]
        offset = struct.unpack_from("<I", entry, 4)[0]
        size = struct.unpack_from("<I", entry, 8)[0]
        label_bytes = entry[12:28]
        flags = struct.unpack_from("<I", entry, 28)[0]
        stripped = label_bytes.rstrip(b"\x00")
        try:
            name = stripped.decode("ascii")
        except UnicodeDecodeError:
            errors.append(f"{where}: entry {count} label is not ASCII")
            count += 1
            continue
        if not stripped or not re.fullmatch(r"[A-Za-z0-9_\-]{1,16}", name):
            errors.append(f"{where}: entry {count} invalid label {name!r}")
        if flags != 0:
            errors.append(f"{where}: entry {count} nonzero flags {flags:#x}")
        if type_ not in (0, 1):
            errors.append(f"{where}: entry {count} invalid type {type_}")
        if size < 1 or offset + size > flash_bytes:
            errors.append(
                f"{where}: entry {count} {name!r} {offset:#x}+{size:#x} exceeds flash"
            )
        entries.append(PartitionEntry(name, type_, subtype, offset, size, label_bytes))
        count += 1
        if len(entries) >= 64:
            errors.append(f"{where}: too many entries")
            break
    # Tail validation: everything after the last entry must be erased except
    # the builder trailer bytes inside the first free 32-byte slot.
    tail_start = count * PARTITION_ENTRY_SIZE
    tail = data[tail_start:end]
    if tail:
        trailer_slot = tail[:PARTITION_ENTRY_SIZE]
        beyond = tail[PARTITION_ENTRY_SIZE:]
        if any(b != 0xFF for b in beyond):
            errors.append(f"{where}: non-erased bytes beyond the builder trailer region")
        md5_region = trailer_slot[16:32]
        if any(b != 0xFF for b in md5_region):
            expected_md5 = hashlib.md5(
                b"".join(
                    data[i * PARTITION_ENTRY_SIZE:(i + 1) * PARTITION_ENTRY_SIZE]
                    for i in range(count)
                )
            ).digest()
            if md5_region != expected_md5:
                errors.append(
                    f"{where}: partition table MD5 trailer mismatch "
                    f"({md5_region.hex()} != {expected_md5.hex()})"
                )
        opaque = trailer_slot[0:16]
        if any(b not in (0xFF,) for b in opaque) and count == 0:
            errors.append(f"{where}: no partition entries found")
    if not entries:
        errors.append(f"{where}: no partition entries found")
    if errors:
        raise ContractError(errors)
    return entries


def format_partition_csv_row(name: str, type_: str, subtype: str, offset: int, size: int) -> str:
    return f"{name}, {type_}, {subtype}, 0x{offset:x}, 0x{size:x},"


def parse_partition_csv(text: str, *, where: str = "partition CSV") -> list[dict[str, Any]]:
    """Parse a PlatformIO/IDF partition CSV; raise ContractError on anomalies."""
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            errors.append(f"{where}:{line_no}: expected 5+ comma fields, got {raw!r}")
            continue
        name, type_, subtype, offset_s, size_s = parts[:5]
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,16}", name):
            errors.append(f"{where}:{line_no}: invalid name {name!r}")
            continue
        if type_ not in ("app", "data"):
            errors.append(f"{where}:{line_no}: invalid type {type_!r}")
        if subtype not in CSV_SUBTYPES:
            errors.append(f"{where}:{line_no}: invalid subtype {subtype!r}")
        try:
            offset = int(offset_s, 16) if offset_s else 0
        except ValueError:
            errors.append(f"{where}:{line_no}: invalid offset {offset_s!r}")
            continue
        try:
            size = int(size_s, 16) if size_s else 0
        except ValueError:
            errors.append(f"{where}:{line_no}: invalid size {size_s!r}")
            continue
        if size < 1:
            errors.append(f"{where}:{line_no}: size must be >= 1")
        entries.append(
            {"name": name, "type": type_, "subtype": subtype, "offset": offset, "size": size}
        )
    if not entries:
        errors.append(f"{where}: no partition entries")
    if errors:
        raise ContractError(errors)
    return entries


def csv_entries_to_binary_maps(entries: list[dict[str, Any]]) -> list[PartitionEntry]:
    """Convert parsed CSV rows to expected binary entries (validates subtypes)."""
    out: list[PartitionEntry] = []
    errors: list[str] = []
    for entry in entries:
        code = CSV_SUBTYPE_CODES.get(str(entry["subtype"]))
        if code is None:
            errors.append(f"CSV entry {entry['name']!r}: unmappable subtype {entry['subtype']!r}")
            continue
        want_type, want_subtype = code
        if entry["type"] == "app" and want_type != 0:
            errors.append(f"CSV entry {entry['name']!r}: type/subtype mismatch")
        if entry["type"] == "data" and want_type not in (0, 1, 255):
            errors.append(f"CSV entry {entry['name']!r}: type/subtype mismatch")
        out.append(
            PartitionEntry(
                str(entry["name"]), want_type, want_subtype,
                int(entry["offset"]), int(entry["size"]),
                str(entry["name"]).encode("ascii"),
            )
        )
    if errors:
        raise ContractError(errors)
    return out


def cross_check_partition_set(
    csv_entries: list[dict[str, Any]],
    binary_entries: list[PartitionEntry],
    *,
    where: str = "partition table",
) -> list[str]:
    """CSV rows and parsed binary entries must describe the same table."""
    errors: list[str] = []
    try:
        expected = csv_entries_to_binary_maps(csv_entries)
    except ContractError as exc:
        return list(exc.errors)
    if len(expected) != len(binary_entries):
        errors.append(
            f"{where}: CSV has {len(expected)} entries, binary has {len(binary_entries)}"
        )
        return errors
    for exp, got in zip(expected, binary_entries):
        if exp != got:
            errors.append(f"{where}: CSV entry {exp!r} != binary entry {got!r}")
    return errors


# ---------------------------------------------------------------------------
# ESP image container sanity (structural; authoritative checksum verification
# stays with the pinned esptool — tests cross-check via `image-info`).
# ---------------------------------------------------------------------------


class EspImageHeader:
    __slots__ = (
        "magic", "segment_count", "flash_mode", "flash_size_freq", "entrypoint",
        "chip_id", "append_digest", "segments", "checksum_ok",
    )

    def __init__(self, **kw: Any) -> None:
        for key in self.__slots__:
            setattr(self, key, kw.get(key))


def parse_esp_image(
    data: bytes,
    *,
    where: str = "image",
    expect_chip_id: int = ESP32S3_IMAGE_CHIP_ID,
) -> EspImageHeader:
    """Validate the ESP image container structurally; raise ContractError.

    Verifies magic, segment count, extended-header chip ID, append_digest
    field, the segment walk, the trailing zero padding + XOR checksum
    placement (and, for append-digest images, the trailing 32-byte digest).
    """
    errors: list[str] = []
    if len(data) < ESP_TOTAL_HEADER_LEN + ESP_SEG_HEADER_LEN + 1:
        raise ContractError([f"{where}: too short to be an ESP image"])
    magic, segment_count, flash_mode, flash_size_freq, entrypoint = struct.unpack_from(
        "<BBBBI", data, 0
    )
    if magic != ESP_IMAGE_MAGIC:
        errors.append(f"{where}: magic {magic:#x} != {ESP_IMAGE_MAGIC:#x}")
    if not 1 <= segment_count <= ESP_MAX_SEGMENTS:
        errors.append(f"{where}: segment count {segment_count} outside 1..{ESP_MAX_SEGMENTS}")
    ext = data[ESP_COMMON_HEADER_LEN:ESP_TOTAL_HEADER_LEN]
    chip_id = ext[4]
    if chip_id != expect_chip_id:
        errors.append(
            f"{where}: extended header chip_id {chip_id} != {expect_chip_id} "
            f"(expected chip {TARGET!r})"
        )
    append_digest = ext[15]
    if append_digest not in (0, 1):
        errors.append(f"{where}: append_digest field {append_digest:#x} not 0 or 1")
    if flash_mode not in (0, 1, 2, 3, 15):
        errors.append(f"{where}: flash_mode {flash_mode} not a known encoding")
    segments: list[tuple[int, int]] = []
    checksum = ESP_CHECKSUM_MAGIC
    if not errors:
        off = ESP_TOTAL_HEADER_LEN
        for index in range(segment_count):
            if off + ESP_SEG_HEADER_LEN > len(data):
                errors.append(f"{where}: truncated segment header {index}")
                break
            load, size = struct.unpack_from("<II", data, off)
            if size < 1 or size > 0x800_000:
                errors.append(f"{where}: segment {index} implausible size {size:#x}")
                break
            seg = data[off + ESP_SEG_HEADER_LEN: off + ESP_SEG_HEADER_LEN + size]
            if len(seg) != size:
                errors.append(f"{where}: truncated segment {index} data")
                break
            for byte in seg:
                checksum ^= byte
            segments.append((load, size))
            off += ESP_SEG_HEADER_LEN + size
        # Tail: zero padding to align, 1-byte checksum, then optional digest.
        tail = data[off:]
        if append_digest == 1:
            if len(tail) < ESP_SHA256_LEN + 1:
                errors.append(f"{where}: truncated trailing checksum+digest")
            else:
                # The SHA-256 digest occupies the last 32 bytes at a 16-byte
                # aligned position; the XOR checksum sits immediately before it
                # behind zero alignment padding (verified against esptool
                # 5.4.0 images built by the pinned toolchain).
                pad = len(tail) - ESP_SHA256_LEN - 1
                if pad > 15:
                    errors.append(f"{where}: excessive trailing alignment padding")
                elif any(b != 0 for b in tail[:pad]):
                    errors.append(f"{where}: non-zero padding before trailing checksum")
                if tail[pad] != checksum:
                    errors.append(
                        f"{where}: XOR checksum {tail[pad]:#x} != computed {checksum:#x}"
                    )
        else:
            stripped = tail
            pad = 0
            while stripped and stripped[-1] == 0 and pad < 3:
                stripped = stripped[:-1]
                pad += 1
            if not stripped:
                errors.append(f"{where}: missing trailing checksum byte")
            elif stripped[-1] != checksum:
                errors.append(
                    f"{where}: XOR checksum {stripped[-1]:#x} != computed {checksum:#x}"
                )
    header = EspImageHeader(
        magic=magic,
        segment_count=segment_count,
        flash_mode=flash_mode,
        flash_size_freq=flash_size_freq,
        entrypoint=entrypoint,
        chip_id=chip_id,
        append_digest=append_digest,
        segments=segments,
    )
    if errors:
        raise ContractError([f"{where}: {e}" if not e.startswith(where) else e for e in errors])
    return header


APP_DESC_MAGIC = 0xABCD5432
BOOTLOADER_DESC_MAGIC = 0x50


def find_desc_segment(data: bytes, *, kind: str) -> bytes | None:
    """Return the segment data starting with the app/bootloader descriptor.

    ``kind`` is ``"app"`` (magic word 0xABCD5432) or ``"bootloader"``
    (magic byte 0x50). Returns None when no segment carries the descriptor.
    """
    if len(data) < ESP_TOTAL_HEADER_LEN:
        return None
    segment_count = data[1]
    if not 1 <= segment_count <= ESP_MAX_SEGMENTS:
        return None
    off = ESP_TOTAL_HEADER_LEN
    for _ in range(segment_count):
        if off + ESP_SEG_HEADER_LEN > len(data):
            return None
        _load, size = struct.unpack_from("<II", data, off)
        seg = data[off + ESP_SEG_HEADER_LEN: off + ESP_SEG_HEADER_LEN + size]
        if kind == "app" and len(seg) >= 4 and struct.unpack_from("<I", seg, 0)[0] == APP_DESC_MAGIC:
            return seg
        if kind == "bootloader" and len(seg) >= 1 and seg[0] == BOOTLOADER_DESC_MAGIC:
            return seg
        off += ESP_SEG_HEADER_LEN + size
    return None


def validate_ota_data_initial(data: bytes, *, where: str = "ota data") -> list[str]:
    """The packaged initial OTA data image: erased sectors or valid C9 sectors."""
    errors: list[str] = []
    if len(data) == 0 or len(data) % OTA_DATA_SECTOR_SIZE != 0:
        errors.append(
            f"{where}: size {len(data)} is not a positive multiple of "
            f"0x{OTA_DATA_SECTOR_SIZE:x}"
        )
        return errors
    for sector in range(len(data) // OTA_DATA_SECTOR_SIZE):
        base = sector * OTA_DATA_SECTOR_SIZE
        block = data[base: base + OTA_DATA_SECTOR_SIZE]
        if all(b == 0xFF for b in block):
            continue
        if block[0] != OTA_DATA_MAGIC_BYTE:
            errors.append(
                f"{where}: sector {sector} magic {block[0]:#x} is neither erased "
                f"nor OTA magic {OTA_DATA_MAGIC_BYTE:#x}"
            )
    return errors
