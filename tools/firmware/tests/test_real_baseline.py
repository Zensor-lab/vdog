"""Real-baseline tests (master plan 0.9.8 / CI-T03): run the pinned
PlatformIO environment build on the host and validate the tooling against
genuine builder output. Skips only when explicitly requested
(``VDOG_SKIP_REAL_BUILD=1``) or when the pinned toolchain is unavailable;
the Stage 0.9 acceptance run must not skip these."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.firmware import contract
from tools.firmware.export_flash_layout import export_flash_layout
from tools.firmware.validate_package import validate_package_bytes

import support

REPO_ROOT = support.REPO_ROOT
BUILD_DIR = REPO_ROOT / "firmware/.pio/build/vdog_xiao_sense_proto"
PIO_TIMEOUT_SECONDS = 900

pytestmark = pytest.mark.skipif(
    os.environ.get("VDOG_SKIP_REAL_BUILD") == "1",
    reason="VDOG_SKIP_REAL_BUILD=1 (toolchain checks intentionally skipped)",
)


def _ensure_build() -> None:
    if BUILD_DIR.is_dir() and (BUILD_DIR / "flasher_args.json").is_file():
        return
    pio = shutil.which("pio")
    if pio is None:
        pytest.skip("PlatformIO Core not available on this host")
    proc = subprocess.run(
        [pio, "run", "-d", "firmware", "-e", "vdog_xiao_sense_proto"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=PIO_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-4000:]
        pytest.fail(
            "plain `pio run -d firmware -e vdog_xiao_sense_proto` did not exit 0 "
            f"(packaging requires exactly such a build):\n{tail}"
        )


@pytest.fixture(scope="module")
def real_build() -> Path:
    _ensure_build()
    assert (BUILD_DIR / "flasher_args.json").is_file()
    return BUILD_DIR


def test_real_build_has_exactly_canonical_images(real_build: Path) -> None:
    found = sorted(p.name for p in real_build.glob("*.bin"))
    assert found == sorted(contract.ROLE_BUILD_FILE.values())


def test_real_export_matches_contract_offsets(real_build: Path) -> None:
    layout = export_flash_layout(real_build, support.PARTITION_CSV)
    assert contract.validate_flash_layout(layout) == []
    by_role = {seg["role"]: seg for seg in layout["segments"]}
    assert by_role["bootloader"]["offset"] == 0x0
    assert by_role["partition_table"]["offset"] == 0x8000
    assert by_role["ota_data_initial"]["offset"] == 0xF000
    assert by_role["application"]["offset"] == 0x20000
    assert layout["target"] == "esp32s3"
    assert layout["flash_size_bytes"] == 8_388_608
    assert layout["upload"] == {
        "flash_mode": "dio", "flash_size": "8MB", "flash_freq": "80m",
    }
    for role, seg in by_role.items():
        assert seg["file"] == f"images/{contract.ROLE_BUILD_FILE[role]}"
        data = (real_build / contract.ROLE_BUILD_FILE[role]).read_bytes()
        assert len(data) == seg["size"]


def test_real_images_and_partition_table_parse(real_build: Path) -> None:
    bootloader = contract.parse_esp_image(
        (real_build / "bootloader.bin").read_bytes(), where="bootloader.bin"
    )
    assert bootloader.chip_id == 9
    assert contract.find_desc_segment(
        (real_build / "bootloader.bin").read_bytes(), kind="bootloader"
    )
    app = contract.parse_esp_image(
        (real_build / "firmware.bin").read_bytes(), where="firmware.bin"
    )
    assert app.chip_id == 9
    assert contract.find_desc_segment(
        (real_build / "firmware.bin").read_bytes(), kind="app"
    )
    entries = contract.parse_partition_table_binary(
        (real_build / "partitions.bin").read_bytes(), where="partitions.bin"
    )
    assert [e.name for e in entries] == [e["name"] for e in support.BASELINE_PARTITIONS]
    assert entries == contract.csv_entries_to_binary_maps(
        contract.parse_partition_csv(
            support.PARTITION_CSV.read_text(encoding="utf-8"), where="repo csv"
        )
    )
    assert contract.validate_ota_data_initial(
        (real_build / "ota_data_initial.bin").read_bytes()
    ) == []


def test_real_build_packages_and_validates_end_to_end(tmp_path: Path, real_build: Path) -> None:
    """Export -> package -> validate on genuine builder output. The identity
    document is a fixture at an explicit path (the in-tree
    ``firmware/.vdog-build-metadata.json`` is generated per build and is
    owned by the firmware packet, never by these tests)."""
    meta = support.write_metadata(tmp_path / "meta", kind="local")
    meta.touch()  # freshness: written after the (pre-existing) build outputs
    zip_path, sha_path, payload, manifest = support.package_from_build_dir(
        tmp_path / "out", build_dir=real_build, metadata_path=meta
    )
    assert validate_package_bytes(zip_path.read_bytes()) == []
    assert manifest["build_id"] == "local"
    assert manifest["images"][3]["offset"] == 0x20000
    import hashlib

    assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == (
        sha_path.read_text(encoding="utf-8").split()[0]
    )


def test_esptool_image_info_cross_check(real_build: Path) -> None:
    """Authoritative container verification stays with esptool: when a
    resolvable esptool exists, its independent image-info must accept the
    packaged images."""
    # Prefer the PlatformIO-pinned tool package (qualified with this
    # baseline); only then fall back to an ambient binary that verifiably
    # reports the pinned esptool 5.4.0.
    candidates = [
        str(Path.home() / ".platformio/packages/tool-esptool/esptool"),
        shutil.which("esptool"),
    ]
    binary = next((c for c in candidates if c and Path(c).is_file()), None)
    if binary is None:
        pytest.skip("no esptool binary available for cross-check")
    ver = subprocess.run(
        [binary, "version"], capture_output=True, text=True, timeout=60,
    )
    ver_out = ver.stdout + ver.stderr
    if "5.4.0" not in ver_out:
        pytest.skip(
            f"available esptool at {binary} is not the pinned 5.4.0 "
            f"(reports: {ver_out.strip().splitlines()[:1]})"
        )
    for name in ("bootloader.bin", "firmware.bin"):
        proc = subprocess.run(
            [binary, "--chip", "esp32s3", "image-info", str(real_build / name)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, f"esptool image-info rejected {name}:\n{proc.stdout}\n{proc.stderr}"
        assert (proc.stdout + proc.stderr).strip()


def test_stale_identity_document_is_refused_on_real_build(
    tmp_path: Path, real_build: Path
) -> None:
    """Addendum item 2 on real output: an identity document older than the
    builder outputs must never be packaged."""
    import time

    meta = support.write_metadata(tmp_path / "meta", kind="local")
    old = time.time() - 86_400
    os.utime(meta, (old, old))
    from tools.firmware.contract import ContractError

    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path / "out", build_dir=real_build, metadata_path=meta
        )
    assert any("stale" in e for e in exc.value.errors)
