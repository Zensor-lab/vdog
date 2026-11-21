"""Flash-layout export tests (work package 0.9.3): role resolution, offsets
derived from the partition table (hardcoded 0x10000/0xe000 assumptions are
rejected), builder-output cross-checks, and refusal of unknown/stale/test
outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.firmware.contract import ContractError
from tools.firmware.export_flash_layout import export_flash_layout

import support


def _export(build_dir: Path) -> dict:
    return export_flash_layout(build_dir, support.PARTITION_CSV)


def test_export_produces_valid_baseline_layout(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "vdog_xiao_sense_proto")
    layout = _export(build_dir)
    from tools.firmware import contract

    assert contract.validate_flash_layout(layout) == []
    assert layout["schema"] == "vdog-flash-layout-v1"
    assert layout["target"] == "esp32s3"
    assert layout["flash_size_bytes"] == 8_388_608
    assert layout["upload"] == {
        "flash_mode": "dio", "flash_size": "8MB", "flash_freq": "80m",
    }
    by_role = {s["role"]: s for s in layout["segments"]}
    assert {s["offset"] for s in layout["segments"]} == {0x0, 0x8000, 0xF000, 0x20000}
    for role, seg in by_role.items():
        data = (build_dir / contract.ROLE_BUILD_FILE[role]).read_bytes()
        assert seg["file"] == f"images/{contract.ROLE_BUILD_FILE[role]}"
        assert seg["sha256"] == hashlib.sha256(data).hexdigest()
        assert seg["size"] == len(data)


def test_export_accepts_idf_style_relocated_paths(tmp_path: Path) -> None:
    # The pinned PlatformIO builder lists non-existent IDF template paths in
    # flasher_args.json (verified at the 0.2 baseline); those must resolve to
    # the canonical root files rather than be guessed at.
    build_dir = support.write_build_dir(tmp_path / "vdog_xiao_sense_proto")
    flasher = json.loads((build_dir / "flasher_args.json").read_text())
    assert "partition_table/partition-table.bin" in flasher["flash_files"].values()
    _export(build_dir)


def test_export_rejects_wrong_chip(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto", chip="esp32"
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("chip" in e for e in exc.value.errors)


def test_export_rejects_inconsistent_flash_size(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        flash_settings={"flash_mode": "dio", "flash_size": "4MB", "flash_freq": "80m"},
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("flash_size" in e for e in exc.value.errors)


@pytest.mark.parametrize(
    "role,forbidden",
    [("application", 0x10000), ("ota_data_initial", 0xE000)],
)
def test_export_rejects_hardcoded_legacy_offsets(
    tmp_path: Path, role: str, forbidden: int
) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        offsets={
            "bootloader": 0x0,
            "partition_table": 0x8000,
            "ota_data_initial": 0xF000,
            "application": 0x20000,
            **{role: forbidden},
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    messages = " ".join(exc.value.errors)
    assert role in messages
    assert "0x10000" in messages or "0xe000" in messages


def test_export_rejects_unexpected_root_bin(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        extra_root_bins={"test.bin": b"\xE9\x01"},  # e.g. pio test runner left over
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("test.bin" in e for e in exc.value.errors)


def test_export_rejects_unknown_flash_file(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        flash_files={
            "0x0": "bootloader/bootloader.bin",
            "0x8000": "partition_table/partition-table.bin",
            "0xf000": "ota_data_initial.bin",
            "0x100": "mystery.bin",
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("does not match any known role" in e for e in exc.value.errors)


def test_export_rejects_missing_canonical_output(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto", omit={"firmware.bin"}
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("missing" in e.lower() for e in exc.value.errors)


def test_export_rejects_missing_flasher_args(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto", omit={"flasher_args.json"}
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("flasher_args.json" in e for e in exc.value.errors)


def test_export_rejects_conflicting_flash_args_text(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        flash_args=(
            "--flash-mode dio --flash-freq 80m --flash-size 8MB\n"
            "0x0 bootloader/bootloader.bin\n"
            "0x8000 partition_table/partition-table.bin\n"
            "0xf000 ota_data_initial.bin\n"
        ),  # application line missing
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("conflict" in e for e in exc.value.errors)


def test_export_rejects_bad_flash_args_flag_line(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        flash_args="0x0 bootloader.bin\n",
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("first line" in e for e in exc.value.errors)


def test_export_rejects_ota_size_mismatch(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(),
            "ota_data_initial.bin": b"\xFF" * 0x1000,  # otadata is 0x2000
            "firmware.bin": support.make_esp_image(kind="app"),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("otadata" in e for e in exc.value.errors)


def test_export_rejects_corrupt_partition_binary(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(corrupt_md5=True),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": support.make_esp_image(kind="app"),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("MD5" in e for e in exc.value.errors)


def test_export_rejects_wrong_chip_image(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": support.make_esp_image(kind="app", chip_id=0x00),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("chip_id" in e for e in exc.value.errors)


def test_export_rejects_image_without_descriptor(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": support.make_esp_image(kind="raw"),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("descriptor" in e for e in exc.value.errors)


def test_export_rejects_oversized_application(tmp_path: Path) -> None:
    big = support.make_esp_image(
        kind="app", extra_segments=[b"\xAB" * (0x300000 + 0x1000)]
    )
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": big,
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("exceeds app0" in e for e in exc.value.errors)


def test_export_rejects_oversized_bootloader(tmp_path: Path) -> None:
    big = support.make_esp_image(
        kind="bootloader", extra_segments=[b"\xCD" * (0x8000 + 0x1000)]
    )
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": big,
            "partitions.bin": support.make_partitions_bin(),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": support.make_esp_image(kind="app"),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("no room" in e for e in exc.value.errors)


def test_export_rejects_csv_binary_divergence(tmp_path: Path) -> None:
    # partitions.bin claims an entry list that disagrees with the CSV.
    build_dir = support.write_build_dir(
        tmp_path / "vdog_xiao_sense_proto",
        images={
            "bootloader.bin": support.make_esp_image(kind="bootloader"),
            "partitions.bin": support.make_partitions_bin(
                entries=[
                    ("nvs", 1, 0x02, 0x9000, 0x6000),
                    ("otadata", 1, 0x00, 0xF000, 0x2000),
                    ("phy_init", 1, 0x01, 0x11000, 0x1000),
                    ("app0", 0, 0x10, 0x20000, 0x100000),  # CSV says 0x300000
                    ("app1", 0, 0x11, 0x320000, 0x300000),
                    ("storage", 1, 0x82, 0x620000, 0x1E0000),
                ]
            ),
            "ota_data_initial.bin": support.make_ota_initial(),
            "firmware.bin": support.make_esp_image(kind="app"),
        },
    )
    with pytest.raises(ContractError) as exc:
        _export(build_dir)
    assert any("app0" in e for e in exc.value.errors)


def test_export_rejects_missing_build_dir(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as exc:
        export_flash_layout(tmp_path / "nowhere", support.PARTITION_CSV)
    assert any("not a directory" in e for e in exc.value.errors)
