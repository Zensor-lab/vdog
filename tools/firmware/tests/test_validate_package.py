"""Package validation tests (work packages 0.9.4/0.9.8): the validator must
accept exactly the qualified payload set and reject tampered archives —
path escapes, symlinks, corruption, truncation, renames, wrong-chip images,
hash mismatches, overlap/bounds/partition violations and identity drift —
entirely offline (no source checkout, no .pio directory)."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from tools.firmware.validate_package import validate_package_bytes

import support


@pytest.fixture()
def package(tmp_path: Path):
    zip_path, sha_path, payload, manifest = support.package_from_build_dir(tmp_path)
    return zip_path, sha_path, payload, manifest


def _bytes_of(payload: dict[str, bytes]) -> bytes:
    """Re-zip a mutated payload under the manifest's build_id root."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "out.zip"
        support.rezip(target, payload)
        return target.read_bytes()


def test_valid_package_has_no_failures(package) -> None:
    zip_path, _sha, _payload, _manifest = package
    assert validate_package_bytes(zip_path.read_bytes()) == []


def test_installer_check_runs_without_source_tree(package, monkeypatch, tmp_path) -> None:
    # The packaged install.py runs in an isolated cwd with no repo markers;
    # validate_package already executed it via run_installer_check.
    zip_path, _sha, _payload, _manifest = package
    assert validate_package_bytes(
        zip_path.read_bytes(),
        cwd_isolation=tmp_path / "clean-cwd",
    ) == []


def test_non_zip_rejected() -> None:
    failures = validate_package_bytes(b"this is not a zip file at all")
    assert failures and "ZIP" in failures[0]


def test_external_digest_mismatch(package) -> None:
    zip_path, _sha, _payload, _manifest = package
    failures = validate_package_bytes(
        zip_path.read_bytes(), expected_zip_sha256="0" * 64
    )
    assert any("external digest" in f for f in failures)


# ---------------------------------------------------------------------------
# ZIP/path safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    ["../escape.bin", "/etc/passwd", "images/../../out.bin", "images\\evil.bin",
     "a/./b.bin", "C:/evil.bin"],
)
def test_dangerous_member_names_rejected(package, member: str) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    tampered[member] = b"evil"
    failures = validate_package_bytes(_bytes_of(tampered))
    assert failures
    assert any(
        word in f for f in failures
        for word in ("path escape", "absolute", "backslash", "unsafe", "illegal",
                     "unexpected", "drive")
    )


def test_symlink_member_rejected(package) -> None:
    zip_path, _sha, payload, manifest = package
    root = f"vdog-xiao-sense-{manifest['build_id']}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, data in payload.items():
            archive.writestr(f"{root}/{path}", data)
        info = zipfile.ZipInfo(f"{root}/evil-link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "images/firmware.bin")
    failures = validate_package_bytes(buf.getvalue())
    assert any("symlink" in f for f in failures)


def test_encrypted_member_rejected(package) -> None:
    zip_path, _sha, payload, manifest = package
    root = f"vdog-xiao-sense-{manifest['build_id']}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, data in payload.items():
            archive.writestr(f"{root}/{path}", data)
    # Set the encryption flag on install.py's central-directory entry.
    raw = bytearray(buf.getvalue())
    target = f"{root}/install.py".encode("utf-8")
    pos, patched = 0, False
    while True:
        pos = raw.find(b"PK\x01\x02", pos)
        if pos < 0:
            break
        name_len = int.from_bytes(raw[pos + 28:pos + 30], "little")
        if raw[pos + 46:pos + 46 + name_len] == target:
            raw[pos + 8] |= 0x01
            patched = True
        pos += 4
    assert patched, "central directory entry for install.py not found"
    failures = validate_package_bytes(bytes(raw))
    assert any("encrypted" in f for f in failures)


def test_wrong_root_name_rejected(package) -> None:
    zip_path, _sha, payload, manifest = package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, data in payload.items():
            archive.writestr(f"someone-elses-firmware/{path}", data)
    failures = validate_package_bytes(buf.getvalue())
    assert any("root directory" in f for f in failures)


def test_root_build_id_mismatch_rejected(package) -> None:
    zip_path, _sha, payload, manifest = package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, data in payload.items():
            archive.writestr(f"vdog-xiao-sense-deadbeefdead/{path}", data)
    failures = validate_package_bytes(buf.getvalue())
    assert any("does not match build_id" in f for f in failures)


def test_truncated_archive_rejected(package) -> None:
    zip_path, _sha, _payload, _manifest = package
    data = zip_path.read_bytes()
    failures = validate_package_bytes(data[: len(data) // 2])
    assert failures


# ---------------------------------------------------------------------------
# Payload set tampering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["install.py", "install.sh", "install.ps1", "requirements-installer.lock",
     "images/firmware.bin", "flash/partitions.csv", "VERSION.json", "LICENSE"],
)
def test_missing_required_file_rejected(package, missing: str) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = {k: v for k, v in payload.items() if k != missing}
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any(missing in f for f in failures)


def test_unexpected_extra_file_rejected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    tampered["backdoor.sh"] = b"#!/bin/sh\n"
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("unexpected file" in f for f in failures)


def test_renamed_image_rejected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    tampered["images/app.bin"] = tampered.pop("images/firmware.bin")
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("images/firmware.bin" in f for f in failures)


# ---------------------------------------------------------------------------
# Content tampering
# ---------------------------------------------------------------------------


def test_flipped_image_byte_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    data = bytearray(tampered["images/firmware.bin"])
    data[0x40] ^= 0xFF
    tampered["images/firmware.bin"] = bytes(data)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("sha256" in f.lower() for f in failures)


def test_consistently_rehashed_corruption_still_detected(package) -> None:
    # An attacker who recomputes every hash still fails the ESP image
    # structural checks (broken XOR checksum over the flipped byte).
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    data = bytearray(tampered["images/firmware.bin"])
    data[0x40] ^= 0xFF
    tampered["images/firmware.bin"] = bytes(data)
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("checksum" in f.lower() for f in failures)


def test_wrong_chip_image_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    tampered["images/firmware.bin"] = support.make_esp_image(kind="app", chip_id=0)
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("chip" in f.lower() for f in failures)


def test_partition_table_swapped_to_foreign_layout_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    foreign = support.make_partitions_bin(
        entries=[("vendor", 1, 0x02, 0x9000, 0x6000), ("app0", 0, 0x10, 0x10000, 0x300000)]
    )
    tampered["images/partitions.bin"] = foreign
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("partition" in f.lower() for f in failures)


def test_sums_entry_tampering_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    lines = tampered["SHA256SUMS"].decode("utf-8").splitlines()
    first, rest = lines[0].split("  ", 1)
    lines[0] = f"{'0' * 64}  {rest}"
    tampered["SHA256SUMS"] = ("\n".join(lines) + "\n").encode("utf-8")
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("SHA256SUMS" in f for f in failures)


def test_manifest_files_tampering_detected(package) -> None:
    zip_path, _sha, payload, manifest = package
    tampered = dict(payload)
    manifest = json.loads(json.dumps(manifest))
    manifest["files"][0]["sha256"] = "0" * 64
    tampered["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("sha256" in f.lower() for f in failures)


def test_flash_args_content_tampering_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    text = tampered["flash/flash_args"].decode("utf-8")
    tampered["flash/flash_args"] = text.replace("0x20000", "0x10000").encode("utf-8")
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("flash_args" in f for f in failures)


def test_version_json_identity_drift_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    version = json.loads(tampered["VERSION.json"])
    version["build_id"] = "main-000000000000"
    tampered["VERSION.json"] = (
        json.dumps(version, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("VERSION.json" in f for f in failures)


def test_flash_baseline_drift_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    manifest = json.loads(tampered["manifest.json"])
    manifest["flash"]["mode"] = "qio"
    manifest["files"] = [
        e for e in manifest["files"] if e["path"] != "manifest.json"
    ]
    tampered["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("flash" in f.lower() for f in failures)


def test_layout_manifest_disagreement_detected(package) -> None:
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    layout = json.loads(tampered["flash/flash-layout.json"])
    seg = next(s for s in layout["segments"] if s["role"] == "application")
    seg["offset"] = 0x21000
    tampered["flash/flash-layout.json"] = (
        json.dumps(layout, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("offset" in f.lower() for f in failures)


def test_hardcoded_legacy_role_offsets_rejected(tmp_path: Path) -> None:
    """Manifest/layout claiming 0x10000 app + 0xe000 otadata (ESP32 legacy
    assumptions) must be rejected against the real partition table."""
    build_dir = support.write_build_dir(
        tmp_path / "build" / "vdog_xiao_sense_proto"
    )
    meta = support.write_metadata(tmp_path / "meta")
    meta.touch()
    zip_path, _sha, payload, manifest = support.package_from_build_dir(
        tmp_path, build_dir=build_dir, metadata_path=meta
    )
    tampered = dict(payload)
    manifest_doc = json.loads(tampered["manifest.json"])
    layout = json.loads(tampered["flash/flash-layout.json"])
    for doc, key in ((manifest_doc, "images"), (layout, "segments")):
        for seg in doc[key]:
            if seg["role"] == "application":
                seg["offset"] = 0x10000
            if seg["role"] == "ota_data_initial":
                seg["offset"] = 0xE000
    tampered["manifest.json"] = (
        json.dumps(manifest_doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    tampered["flash/flash-layout.json"] = (
        json.dumps(layout, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("0x10000" in f or "partition table requires" in f for f in failures)
    assert any("0xe000" in f or "partition table requires" in f for f in failures)


def _custom_csv(tmp_path: Path, mutate) -> Path:
    text = support.PARTITION_CSV.read_text(encoding="utf-8")
    path = tmp_path / "custom-partitions.csv"
    path.write_text(mutate(text), encoding="utf-8")
    return path


def _shrink_app0(text: str) -> str:
    import re

    new, n = re.subn(
        r"(app0,\s+app,\s+ota_0,\s+0x20000,\s+)0x300000", r"\g<1>0x40", text
    )
    assert n == 1
    return new


def _move_nvs_to_start(text: str) -> str:
    import re

    new, n = re.subn(
        r"(nvs,\s+data,\s+nvs,\s+)0x9000,(\s+)0x6000", r"\g<1>0x0,\g<2>0x100000", text
    )
    assert n == 1
    return new


def _manual_layout(image_bytes: dict[str, bytes]) -> dict:
    """A valid vdog-flash-layout-v1 built straight from image bytes (bypasses
    the export step so the validator's own partition checks can be targeted)."""
    from tools.firmware import contract

    offsets = {
        "bootloader": 0x0, "partition_table": 0x8000,
        "ota_data_initial": 0xF000, "application": 0x20000,
    }
    return {
        "schema": "vdog-flash-layout-v1",
        "target": "esp32s3",
        "flash_size_bytes": 8_388_608,
        "upload": {"flash_mode": "dio", "flash_size": "8MB", "flash_freq": "80m"},
        "segments": [
            {
                "role": role,
                "file": f"images/{contract.ROLE_BUILD_FILE[role]}",
                "offset": offsets[role],
                "size": len(image_bytes[role]),
                "sha256": hashlib.sha256(image_bytes[role]).hexdigest(),
            }
            for role in contract.IMAGE_ROLES
        ],
    }


def _binary_tuples(entries: list[dict]) -> list[tuple]:
    return [
        (e["name"], 0 if e["type"] == "app" else 1,
         {"nvs": 0x02, "ota": 0x00, "phy": 0x01, "ota_0": 0x10, "ota_1": 0x11,
          "spiffs": 0x82}[e["subtype"]],
         e["offset"], e["size"])
        for e in entries
    ]


def test_oversized_application_image_rejected(tmp_path: Path) -> None:
    # app0 partition shrunk below the packaged firmware.bin size; the export
    # step is bypassed with a hand-built layout to exercise the validator.
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    app = (build_dir / "firmware.bin").read_bytes()
    entries = [dict(e) for e in support.BASELINE_PARTITIONS]
    for e in entries:
        if e["name"] == "app0":
            e["size"] = 0x40
    csv_path = _custom_csv(tmp_path, _shrink_app0)
    (build_dir / "partitions.bin").write_bytes(
        support.make_partitions_bin(entries=_binary_tuples(entries))
    )
    image_bytes = {
        role: (build_dir / name).read_bytes()
        for role, name in {
            "bootloader": "bootloader.bin", "partition_table": "partitions.bin",
            "ota_data_initial": "ota_data_initial.bin", "application": "firmware.bin",
        }.items()
    }
    zip_path, _sha, payload, manifest = support.package_from_build_dir(
        tmp_path / "out", build_dir=build_dir, partition_csv=csv_path,
        flash_layout=_manual_layout(image_bytes),
    )
    failures = validate_package_bytes(zip_path.read_bytes())
    assert failures and any("app0" in f for f in failures)


def test_written_ranges_must_not_touch_nvs(tmp_path: Path) -> None:
    # NVS partition moved to flash start: the bootloader write range would
    # clobber NVS — the validator must refuse the package outright.
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    entries = [dict(e) for e in support.BASELINE_PARTITIONS]
    for e in entries:
        if e["name"] == "nvs":
            e["offset"] = 0x0
            e["size"] = 0x100000
    (build_dir / "partitions.bin").write_bytes(
        support.make_partitions_bin(entries=_binary_tuples(entries))
    )
    csv_path = _custom_csv(
        tmp_path,
        _move_nvs_to_start,
    )
    image_bytes = {
        role: (build_dir / name).read_bytes()
        for role, name in {
            "bootloader": "bootloader.bin", "partition_table": "partitions.bin",
            "ota_data_initial": "ota_data_initial.bin", "application": "firmware.bin",
        }.items()
    }
    zip_path, _sha, payload, manifest = support.package_from_build_dir(
        tmp_path / "out", build_dir=build_dir, partition_csv=csv_path,
        flash_layout=_manual_layout(image_bytes),
    )
    failures = validate_package_bytes(zip_path.read_bytes())
    assert any("NVS" in f for f in failures)


def test_installer_check_failure_is_reported(package) -> None:
    # A sabotaged packaged install.py (hashes recomputed consistently) must
    # be caught by executing it inside an isolated clean directory.
    zip_path, _sha, payload, _manifest = package
    tampered = dict(payload)
    tampered["install.py"] = b"raise SystemExit('sabotaged')\n"
    support.with_resolved_hashes(tampered)
    failures = validate_package_bytes(_bytes_of(tampered))
    assert any("install.py check failed" in f for f in failures)
