"""Shared synthetic builders and fake adapters for the 0.9 tool tests.

Formats (ESP image container, partition table binary + MD5 trailer, OTA
data) were verified byte-for-byte against the pinned 0.2 baseline build and
esptool 5.4.0; these builders reproduce them for synthetic fixtures.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from tools.firmware import contract
from tools.firmware.package import (
    create_package,
    default_payload_sources,
    write_deterministic_zip,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_HEADER = REPO_ROOT / "firmware" / "core" / "vdog_core.h"
PARTITION_CSV = REPO_ROOT / "firmware" / "partitions" / "vdog_8mb_two_ota.csv"

FULL_SHA_A = "3aa5c6e7f8091b2c3d4e5f60718293a4b5c6d7e8"
FULL_SHA_B = "0f1e2d3c4b5a69788796a5b4c3d2e1f00a1b2c3d"
SHA_A_12 = FULL_SHA_A[:12]

APP_DESC_MAGIC_BYTES = struct.pack("<I", 0xABCD5432)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# ESP image containers (bootloader / application)
# ---------------------------------------------------------------------------


def make_esp_image(
    *,
    kind: str = "app",
    chip_id: int = 9,
    append_digest: int = 1,
    magic: int = 0xE9,
    segment_count_override: int | None = None,
    flash_mode: int = 2,
    flash_size_freq: int = 0x3F,
    entry: int = 0x40375EA8,
    extra_segments: list[bytes] | None = None,
) -> bytes:
    if kind == "app":
        desc = APP_DESC_MAGIC_BYTES + b"\x00" * (256 - 4)
        segments = [desc, b"\xAB" * 128]
    elif kind == "bootloader":
        desc = b"\x50" + b"\x00" * 63
        segments = [desc, b"\xCD" * 96]
    else:  # raw: caller-provided segments only (invalid descriptor)
        segments = list(extra_segments or [b"\x11" * 64])
    if extra_segments and kind != "raw":
        segments += list(extra_segments)
    seg_count = segment_count_override if segment_count_override is not None else len(segments)
    header = struct.pack("<BBBBI", magic, seg_count, flash_mode, flash_size_freq, entry)
    extended = bytearray(16)
    extended[0] = 0xEE          # wp_pin
    extended[4] = chip_id       # IMAGE_CHIP_ID (byte 12 of the file)
    extended[15] = append_digest
    body = bytearray()
    checksum = 0xEF
    for segment in segments:
        body += struct.pack("<II", 0x3C020000 + len(body), len(segment))
        body += segment
        for byte in segment:
            checksum ^= byte
    if append_digest:
        pad = (16 - ((len(header) + len(extended) + len(body) + 1 + 32) % 16)) % 16
        tail = b"\x00" * pad + bytes([checksum]) + b"\x22" * 32
    else:
        tail = bytes([checksum])
    return bytes(header) + bytes(extended) + bytes(body) + tail


# ---------------------------------------------------------------------------
# Partition table binary (matches the baseline CSV layout)
# ---------------------------------------------------------------------------

BASELINE_ENTRIES = [
    ("nvs", 1, 0x02, 0x9000, 0x6000),
    ("otadata", 1, 0x00, 0xF000, 0x2000),
    ("phy_init", 1, 0x01, 0x11000, 0x1000),
    ("app0", 0, 0x10, 0x20000, 0x300000),
    ("app1", 0, 0x11, 0x320000, 0x300000),
    ("storage", 1, 0x82, 0x620000, 0x1E0000),
]


def make_partitions_bin(entries: list[tuple[str, int, int, int, int]] | None = None,
                        *, corrupt_md5: bool = False, tamper_at: tuple[int, int] | None = None) -> bytes:
    entries = entries if entries is not None else BASELINE_ENTRIES
    table = bytearray(3072)
    for index in range(3072):
        table[index] = 0xFF
    used = bytearray()
    for name, type_, subtype, offset, size in entries:
        entry = bytearray(32)
        entry[0:2] = struct.pack("<H", 0x50AA)
        entry[2] = type_
        entry[3] = subtype
        entry[4:8] = struct.pack("<I", offset)
        entry[8:12] = struct.pack("<I", size)
        entry[12:28] = name.encode("ascii").ljust(16, b"\x00")
        table[(index_pos := len(used)):(index_pos + 32)] = entry
        used += entry
    count = len(used)
    # Builder trailer inside the first free slot: 2 opaque checksum bytes at
    # slot+0 and the 16-byte MD5 over all entry bytes at slot+16.
    slot_start = count
    table[slot_start] = 0xEB
    table[slot_start + 1] = 0xEB
    md5 = hashlib.md5(bytes(used)).digest()
    if corrupt_md5:
        md5 = bytes([md5[0] ^ 0xFF]) + md5[1:]
    table[slot_start + 16:slot_start + 32] = md5
    if tamper_at is not None:
        pos, value = tamper_at
        table[pos] = value
    return bytes(table)


def make_ota_initial(size: int = 0x2000) -> bytes:
    return b"\xFF" * size


# ---------------------------------------------------------------------------
# Synthetic PlatformIO build directory
# ---------------------------------------------------------------------------

FLASHER_TEMPLATE = {
    "bootloader": "bootloader/bootloader.bin",
    "partition_table": "partition_table/partition-table.bin",
    "ota_data_initial": "ota_data_initial.bin",
    "application": "vdog_firmware.bin",
}


def write_build_dir(
    build_dir: Path,
    *,
    images: dict[str, bytes] | None = None,
    offsets: dict[str, int] | None = None,
    flash_files: dict[str, str] | None = None,
    flash_settings: dict[str, str] | None = None,
    chip: str = "esp32s3",
    extra_root_bins: dict[str, bytes] | None = None,
    omit: set[str] | None = None,
    flasher_args: dict[str, Any] | None = None,
    flash_args: str | None = None,
) -> Path:
    """Write a synthetic normal-build directory (canonical root files +
    IDF-style flasher_args.json exactly like the pinned PlatformIO builder)."""
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    omit = omit or set()
    images = images or {
        "bootloader.bin": make_esp_image(kind="bootloader"),
        "partitions.bin": make_partitions_bin(),
        "ota_data_initial.bin": make_ota_initial(),
        "firmware.bin": make_esp_image(kind="app"),
    }
    offsets = offsets or {
        "bootloader": 0x0,
        "partition_table": 0x8000,
        "ota_data_initial": 0xF000,
        "application": 0x20000,
    }
    role_to_file = {
        "bootloader": "bootloader.bin",
        "partition_table": "partitions.bin",
        "ota_data_initial": "ota_data_initial.bin",
        "application": "firmware.bin",
    }
    for role, filename in role_to_file.items():
        if filename in omit:
            continue
        (build_dir / filename).write_bytes(images[filename])
    for name, data in (extra_root_bins or {}).items():
        (build_dir / name).write_bytes(data)
    if flasher_args is None:
        flash_files = flash_files or {
            hex(offsets[role]): FLASHER_TEMPLATE[role] for role in role_to_file
        }
        flash_settings = flash_settings or {
            "flash_mode": "dio", "flash_size": "8MB", "flash_freq": "80m",
        }
        flasher_args = {
            "write_flash_args": ["--flash-mode", flash_settings["flash_mode"],
                                 "--flash-size", flash_settings["flash_size"],
                                 "--flash-freq", flash_settings["flash_freq"]],
            "flash_settings": flash_settings,
            "flash_files": flash_files,
            "extra_esptool_args": {
                "after": "hard-reset", "before": "default-reset",
                "stub": True, "chip": chip,
            },
        }
    if "flasher_args.json" not in omit:
        (build_dir / "flasher_args.json").write_text(
            json.dumps(flasher_args, indent=4), encoding="utf-8"
        )
    if flash_args is None:
        lines = [
            f"--flash-mode {flash_settings['flash_mode'] if flash_settings else 'dio'} "
            f"--flash-freq {flash_settings['flash_freq'] if flash_settings else '80m'} "
            f"--flash-size {flash_settings['flash_size'] if flash_settings else '8MB'}"
        ]
        for off_key, path in sorted(
            (flasher_args.get("flash_files") or {}).items(),
            key=lambda kv: int(kv[0], 16),
        ):
            lines.append(f"{hex(int(off_key, 16))} {path}")
        flash_args = "\n".join(lines) + "\n"
    if "flash_args" not in omit:
        (build_dir / "flash_args").write_text(flash_args, encoding="utf-8")
    return build_dir


def write_metadata(
    directory: Path,
    *,
    kind: str = "local",
    sha: str | None = None,
    build_id: str | None = None,
    name: str = "vdog-build-metadata.json",
    **overrides: Any,
) -> Path:
    if kind == "local":
        sha = sha or "local"
        build_id = build_id or "local"
    elif kind == "pr":
        sha = sha or FULL_SHA_A
        build_id = build_id or f"pr-7-{sha[:12] if sha != 'local' else ''}"
    elif kind == "main":
        sha = sha or FULL_SHA_B
        build_id = build_id or f"main-{sha[:12] if sha != 'local' else ''}"
    doc = {
        "schema": "vdog-build-metadata-v1",
        "firmware_version": "0.2.0-proto",
        "source_sha": sha,
        "build_id": build_id,
        "environment": "vdog_xiao_sense_proto",
        "platform": "platformio/espressif32@8.0.0",
        "idf_version": "v6.1.0",
        "esptool_version": "5.4.0",
    }
    doc.update(overrides)
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def make_text_sources(directory: Path) -> dict[str, Path]:
    """Install/notes/license sources (INSTALL/RELEASE_NOTES come from paths)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, text in (
        ("INSTALL.md", "# Install\nRun install.py check, then plan, then install.\n"),
        ("RELEASE_NOTES.md", "# Release notes\nPrototype bootstrap.\n"),
        ("LICENSE", "MIT-like placeholder license text for tests.\n"),
        ("THIRD_PARTY_NOTICES.md", "# Notices\nESP-IDF Apache-2.0 etc.\n"),
    ):
        path = directory / name
        path.write_text(text, encoding="utf-8")
        paths[name] = path
    return paths


def package_from_build_dir(
    tmp_path: Path,
    *,
    build_dir: Path | None = None,
    metadata_path: Path | None = None,
    sources: dict[str, Path] | None = None,
    kind: str = "auto",
    pr_number: int | None = None,
    base_sha: str | None = None,
    run_id: int | None = None,
    attempt: int | None = None,
    output_dir: Path | None = None,
    require_fresh_metadata: bool = True,
    build_metadata_overrides: dict[str, Any] | None = None,
    partition_csv: Path | None = None,
    flash_layout: dict[str, Any] | None = None,
    skip_git_verify: bool = True,
) -> tuple[Path, Path, dict[str, bytes], dict[str, Any]]:
    """Build a complete synthetic package. Returns (zip, sha256 file, payload, manifest).

    ``skip_git_verify`` defaults to True because these fixtures fabricate
    pr/main identities that are deliberately not the checkout's HEAD; the
    default-on release-path verification is covered by dedicated tests.
    """
    tmp_path = Path(tmp_path)
    if build_dir is None:
        build_dir = write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    if metadata_path is None:
        metadata_path = write_metadata(tmp_path / "meta", **(build_metadata_overrides or {}))
        # Freshness: metadata must be newer than builder outputs.
        metadata_path.touch()
    sources = sources or _default_sources(tmp_path)
    out_dir = Path(output_dir or tmp_path / "dist")
    zip_path, sha_path = create_package(
        build_dir=build_dir,
        partition_csv=partition_csv or PARTITION_CSV,
        metadata_path=metadata_path,
        core_header_path=CORE_HEADER,
        kind=kind,
        pr_number=pr_number,
        base_sha=base_sha,
        run_id=run_id,
        attempt=attempt,
        output_dir=out_dir,
        require_fresh_metadata=require_fresh_metadata,
        skip_git_verify=skip_git_verify,
        flash_layout=flash_layout,
        **sources,
    )
    payload = _payload_from_zip(zip_path)
    manifest = json.loads(payload["manifest.json"].decode("utf-8"))
    return zip_path, sha_path, payload, manifest


def _default_sources(tmp_path: Path) -> dict[str, Path]:
    texts = make_text_sources(tmp_path / "sources")
    sources = default_payload_sources(
        install_md_path=texts["INSTALL.md"],
        release_notes_md_path=texts["RELEASE_NOTES.md"],
        license_path=texts["LICENSE"],
        third_party_notices_path=texts["THIRD_PARTY_NOTICES.md"],
        install_sh_path=None,
        install_ps1_path=None,
        requirements_lock_path=None,
    )
    return sources


def _payload_from_zip(zip_path: Path) -> dict[str, bytes]:
    import zipfile

    payload: dict[str, bytes] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel = info.filename.split("/", 1)[1]
            payload[rel] = archive.read(info)
    return payload


def rezip(zip_path: Path, payload: dict[str, bytes], *, build_id: str | None = None) -> Path:
    """Rewrite the ZIP with modified payload (tamper testing)."""
    if build_id is None:
        build_id = json.loads(payload["manifest.json"].decode("utf-8"))["build_id"]
    write_deterministic_zip(payload, build_id, zip_path)
    return Path(zip_path)


def with_resolved_hashes(payload: dict[str, bytes]) -> dict[str, bytes]:
    """After mutating images/layout, recompute manifest file/image entries,
    layout segment hashes and SHA256SUMS so only the intended fault remains."""
    manifest = json.loads(payload["manifest.json"].decode("utf-8"))
    layout = json.loads(payload["flash/flash-layout.json"].decode("utf-8"))
    for segment in layout["segments"]:
        data = payload[segment["file"]]
        segment["sha256"] = sha256_bytes(data)
        segment["size"] = len(data)
    for image in manifest["images"]:
        data = payload[image["file"]]
        image["sha256"] = sha256_bytes(data)
        image["size"] = len(data)
    layout_bytes = (json.dumps(layout, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    payload["flash/flash-layout.json"] = layout_bytes
    files = sorted(
        (
            {"path": p, "size": len(d), "sha256": sha256_bytes(d)}
            for p, d in payload.items()
            if p not in ("manifest.json", "SHA256SUMS")
        ),
        key=lambda item: item["path"],
    )
    manifest["files"] = files
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2,
                                 ensure_ascii=False) + "\n").encode()
    payload["manifest.json"] = manifest_bytes
    sums = "".join(
        f"{sha256_bytes(d)}  {p}\n"
        for p, d in sorted(payload.items())
        if p != "SHA256SUMS"
    ).encode()
    payload["SHA256SUMS"] = sums
    return payload


# ---------------------------------------------------------------------------
# Standalone valid documents + mutation corpus (shared by contract tests and
# the installer drift cross-check in test_install_cli.py)
# ---------------------------------------------------------------------------

BASELINE_PARTITIONS = [
    {"name": "nvs", "type": "data", "subtype": "nvs", "offset": 0x9000, "size": 0x6000},
    {"name": "otadata", "type": "data", "subtype": "ota", "offset": 0xF000, "size": 0x2000},
    {"name": "phy_init", "type": "data", "subtype": "phy", "offset": 0x11000, "size": 0x1000},
    {"name": "app0", "type": "app", "subtype": "ota_0", "offset": 0x20000, "size": 0x300000},
    {"name": "app1", "type": "app", "subtype": "ota_1", "offset": 0x320000, "size": 0x300000},
    {"name": "storage", "type": "data", "subtype": "spiffs", "offset": 0x620000, "size": 0x1E0000},
]

_SEGMENT_SIZES = {
    "bootloader": 22944,
    "partition_table": 3072,
    "ota_data_initial": 8192,
    "application": 208361,
}
_SEGMENT_OFFSETS = {
    "bootloader": 0x0,
    "partition_table": 0x8000,
    "ota_data_initial": 0xF000,
    "application": 0x20000,
}


def valid_segments() -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "file": f"images/{contract.ROLE_BUILD_FILE[role]}",
            "offset": _SEGMENT_OFFSETS[role],
            "size": _SEGMENT_SIZES[role],
            "sha256": "a" * 64,
        }
        for role in contract.IMAGE_ROLES
    ]


def valid_layout_doc() -> dict[str, Any]:
    return {
        "schema": "vdog-flash-layout-v1",
        "target": "esp32s3",
        "flash_size_bytes": 8_388_608,
        "upload": {"flash_mode": "dio", "flash_size": "8MB", "flash_freq": "80m"},
        "segments": valid_segments(),
    }


def valid_manifest_doc(
    *,
    kind: str = "local",
    sha: str = "local",
    pr_number: int | None = None,
    base_sha: str | None = None,
) -> dict[str, Any]:
    if kind == "local":
        source = {
            "kind": "local", "sha": "local", "sha_short": "local",
            "pr_number": None, "base_sha": None, "dirty": False,
        }
        build_id, tag = "local", None
    elif kind == "pr":
        source = {
            "kind": "pr", "sha": sha, "sha_short": sha[:12],
            "pr_number": pr_number, "base_sha": base_sha, "dirty": False,
        }
        build_id, tag = f"pr-{pr_number}-{sha[:12]}", None
    else:
        source = {
            "kind": "main", "sha": sha, "sha_short": sha[:12],
            "pr_number": None, "base_sha": None, "dirty": False,
        }
        build_id, tag = f"main-{sha[:12]}", f"firmware-main-{sha[:12]}"
    covered = sorted(
        set(contract.PACKAGE_REQUIRED_FILES) - set(contract.PACKAGE_SELF_EXCLUDED_FROM_MANIFEST)
    )
    return {
        "schema": "firmware-release-v1",
        "package_format_version": 1,
        "product": "vdog",
        "product_slug": "vdog-xiao-sense",
        "hardware_class": "seeed-xiao-esp32s3-sense",
        "board": "seeed_xiao_esp32s3",
        "environment": "vdog_xiao_sense_proto",
        "target": "esp32s3",
        "expected_flash_bytes": 8_388_608,
        "firmware_version": "0.2.0-proto",
        "release_channel": "prototype",
        "hardware_verified": False,
        "recording_available": False,
        "device_ota_available": False,
        "source": source,
        "build_id": build_id,
        "tag": tag,
        "ci": None,
        "toolchain": {
            "platformio_core": "6.2.0",
            "platform": "platformio/espressif32@8.0.0",
            "idf_version": "v6.1.0",
            "esptool_version": "5.4.0",
        },
        "flash": {"mode": "dio", "size": "8MB", "freq": "80m", "size_bytes": 8_388_608},
        "images": valid_segments(),
        "partition_table": {
            "file": "flash/partitions.csv",
            "sha256": "c" * 64,
            "size": 512,
            "entries": [dict(e) for e in BASELINE_PARTITIONS],
        },
        "flash_layout_file": "flash/flash-layout.json",
        "files": [
            {"path": path, "size": 10, "sha256": "b" * 64} for path in covered
        ],
    }


def _m(manifest: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    node: Any = manifest
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


#: (name, mutate, expected contract-error substring, visible_to_jsonschema)
MANIFEST_MUTATIONS: list[tuple[str, Any, str, bool]] = [
    ("schema rename", lambda m: _m(m, ("schema",), "firmware-release-v0"),
     "manifest.schema", True),
    ("channel dev", lambda m: _m(m, ("release_channel",), "dev"),
     "release_channel", True),
    ("hardware_verified true", lambda m: _m(m, ("hardware_verified",), True),
     "hardware_verified", True),
    ("recording true", lambda m: _m(m, ("recording_available",), True),
     "recording_available", True),
    ("dirty source", lambda m: _m(m, ("source", "dirty"), True),
     "dirty", True),
    ("unknown extra field", lambda m: m.update({"surprise": 1}),
     "unknown field", True),
    ("target esp32", lambda m: _m(m, ("target",), "esp32"),
     "target", True),
    ("esptool not pinned",
     lambda m: _m(m, ("toolchain", "esptool_version"), "4.8.1"),
     "esptool_version", True),
    ("platform unpinned",
     lambda m: _m(m, ("toolchain", "platform"), "platformio/espressif32@6.0.0"),
     "platform", True),
    ("flash mode qio", lambda m: _m(m, ("flash", "mode"), "qio"),
     "flash", True),
    ("flash size 4MB", lambda m: _m(m, ("flash", "size"), "4MB"),
     "flash.size", True),
    ("duplicate role images",
     lambda m: _m(m, ("images", 1, "role"), "bootloader"),
     "duplicate role", False),
    ("missing role image", lambda m: m.__setitem__("images", m["images"][:3]),
     "missing roles", True),
    ("overlapping images",
     lambda m: _m(m, ("images", 3, "offset"), 0x8000),
     "overlaps", False),
    ("image past flash end",
     lambda m: _m(m, ("images", 3, "size"), 8_388_608),
     "exceeds flash size", False),
    ("image file escape",
     lambda m: _m(m, ("images", 0, "file"), "../bootloader.bin"),
     "images/bootloader.bin", True),
    ("bad sha256 hex", lambda m: _m(m, ("images", 0, "sha256"), "xyz"),
     "sha256", True),
    ("local kind with tag", lambda m: m.__setitem__("tag", "firmware-main-abcdef012345"),
     "must not carry a tag", False),
    ("self-excluded in files",
     lambda m: m["files"].append({"path": "manifest.json", "size": 1, "sha256": "d" * 64}),
     "must be excluded", False),
    ("missing files coverage", lambda m: m["files"].pop(),
     "missing payload coverage", False),
    ("unknown covered file",
     lambda m: m["files"].append({"path": "evil.bin", "size": 1, "sha256": "d" * 64}),
     "not part of the section 4 payload", False),
    ("ci attempt zero", lambda m: m.__setitem__("ci", {"run_id": 5, "attempt": 0}),
     "attempt", True),
    ("ci extra key", lambda m: m.__setitem__("ci", {"run_id": 5, "attempt": 1, "url": "x"}),
     "run_id/attempt", True),
    ("local carrying ci", lambda m: m.__setitem__("ci", {"run_id": 5, "attempt": 1}),
     "must not carry", True),
    ("toolchain extra key", lambda m: m["toolchain"].update({"extra": "x"}),
     "toolchain", True),
    ("flash extra key", lambda m: m["flash"].update({"extra": "x"}),
     "flash", True),
    ("source extra key", lambda m: m["source"].update({"extra": "x"}),
     "source", True),
    ("duplicate files path", lambda m: m["files"].append(dict(m["files"][0])),
     "duplicate", False),
    ("files path traversal",
     lambda m: m["files"].append({"path": "images/../b.bin", "size": 1,
                                  "sha256": "d" * 64}),
     "unsafe", True),
    ("partition entry bad type",
     lambda m: _m(m, ("partition_table", "entries", 0, "type"), "magic"),
     "type", True),
]


LAYOUT_MUTATIONS: list[tuple[str, Any, str]] = [
    ("schema rename", lambda d: d.__setitem__("schema", "vdog-flash-layout-v0"), "schema"),
    ("target esp32", lambda d: d.__setitem__("target", "esp32"), "target"),
    ("flash 4MB", lambda d: d.__setitem__("flash_size_bytes", 4_194_304), "flash_size_bytes"),
    ("upload qio", lambda d: _m(d, ("upload", "flash_mode"), "qio"), "flash_mode"),
    ("upload size 4MB", lambda d: _m(d, ("upload", "flash_size"), "4MB"), "flash_size"),
    ("missing segment", lambda d: d.__setitem__("segments", d["segments"][:3]), "exactly 4"),
    ("duplicate role", lambda d: _m(d, ("segments", 1, "role"), "bootloader"), "duplicate"),
    ("overlapping", lambda d: _m(d, ("segments", 3, "offset"), 0x9000), "overlaps"),
    ("past flash", lambda d: _m(d, ("segments", 3, "size"), 8_388_608), "exceeds flash"),
    ("bad file path", lambda d: _m(d, ("segments", 0, "file"), "images/../b.bin"), "unsafe"),
    ("unknown field", lambda d: d.__setitem__("extra", 1), "unknown field"),
]


# ---------------------------------------------------------------------------
# Fake serial/esptool adapter (mirrors tools.firmware.installer.install API)
# ---------------------------------------------------------------------------


class FakeTransport:
    """Programmable stand-in for EsptoolTransport; records every call."""

    def __init__(
        self,
        *,
        version: str = "5.4.0",
        chip: str = "esp32s3",
        flash_size: int = 8_388_608,
        security: dict[str, bool] | None = None,
        flash_map: dict[int, bytes] | None = None,
        version_fail: bool = False,
        fail_version: str | None = None,
        fail_on_call: int | None = None,
        fail_on_write: int | None = None,
        corrupt_store: bool = False,
    ) -> None:
        from tools.firmware.installer.install import EsptoolFailure

        self._failure_cls = EsptoolFailure
        self.command = ["fake-esptool"]
        self.version_value = version
        self.chip = chip
        self.flash_size = flash_size
        self.security = security or {"secure_boot": False, "flash_encryption": False}
        self.flash_map = dict(flash_map or {})
        self.version_fail = version_fail
        self.fail_version = fail_version
        self.fail_on_call = fail_on_call
        self.fail_on_write = fail_on_write
        self.corrupt_store = corrupt_store
        self.calls: list[list[Any]] = []
        self.writes: list[tuple[int, str, bool]] = []
        self.reads: list[tuple[int, int]] = []

    # -- adapter surface -----------------------------------------------------
    def _maybe_fail(self, kind: str) -> None:
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise self._failure_cls(f"injected serial failure at call {kind}")

    def version(self) -> str:
        self.calls.append(["version"])
        self._maybe_fail("version")
        if self.version_fail:
            raise self._failure_cls("esptool missing")
        return self.fail_version or self.version_value

    def flash_id(self, port: str) -> tuple[str, int]:
        self.calls.append(["flash-id", port])
        self._maybe_fail("flash-id")
        if self.chip != "esp32s3":
            raise self._failure_cls(f"device is not an ESP32-S3: 'Chip is {self.chip}'")
        return self.chip, self.flash_size

    def security_flags(self, port: str) -> dict[str, bool]:
        self.calls.append(["get-security-info", port])
        self._maybe_fail("security")
        return dict(self.security)

    def read_flash(self, port: str, offset: int, size: int) -> bytes:
        self.calls.append(["read-flash", port, offset, size])
        self._maybe_fail("read-flash")
        self.reads.append((offset, size))
        out = bytearray(b"\xFF" * size)
        for region_start, region in self.flash_map.items():
            region_end = region_start + len(region)
            if offset < region_end and region_start < offset + size:
                overlap_start = max(offset, region_start)
                overlap_end = min(offset + size, region_end)
                out[overlap_start - offset:overlap_end - offset] = region[
                    overlap_start - region_start:overlap_end - region_start
                ]
        return bytes(out)

    def write_flash(self, port: str, offset: int, image_path: Path, *, final: bool) -> None:
        self.calls.append(["write-flash", port, offset, str(image_path), final])
        self._maybe_fail("write-flash")
        if self.fail_on_write is not None and len(self.writes) == self.fail_on_write:
            raise self._failure_cls(f"injected write failure at segment {offset:#x}")
        data = Path(image_path).read_bytes()
        self.writes.append((offset, sha256_bytes(data), final))
        if self.corrupt_store:
            flipped = bytearray(data)
            if flipped:
                flipped[-1] ^= 0xFF
            self.flash_map[offset] = bytes(flipped)
        else:
            self.flash_map[offset] = data


def blank_device_table(build_dir_payload: dict[str, bytes]) -> dict[int, bytes]:
    """flash_map simulating a device already holding the dev layout."""
    return {
        0x8000: build_dir_payload["images/partitions.bin"],
        0xF000: build_dir_payload["images/ota_data_initial.bin"],
    }


def extract_zip(zip_path: Path, destination: Path) -> Path:
    import zipfile

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
    root = next(iter(destination.iterdir()))
    return root
