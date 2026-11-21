"""Deterministic packaging tests (work package 0.9.4): payload completeness,
self-exclusion rules, ZIP determinism/safety properties, identity flows for
local/pr/main, and lock/digest artifacts."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from tools.firmware import contract
from tools.firmware.contract import ContractError
from tools.firmware.package import (
    ZIP_DATE_TIME,
    package_root_name,
)
from tools.firmware.validate_package import validate_package_bytes

import support

TOOLS_DIR = support.REPO_ROOT / "tools/firmware"


def test_valid_package_passes_full_validation(tmp_path: Path) -> None:
    zip_path, _sha, payload, manifest = support.package_from_build_dir(tmp_path)
    assert validate_package_bytes(zip_path.read_bytes()) == []
    assert set(payload) == set(contract.PACKAGE_REQUIRED_FILES)
    assert manifest["schema"] == "firmware-release-v1"


def test_packaging_is_byte_deterministic(tmp_path: Path) -> None:
    zip_a, _sa, payload_a, manifest_a = support.package_from_build_dir(
        tmp_path / "a"
    )
    zip_b, _sb, payload_b, manifest_b = support.package_from_build_dir(
        tmp_path / "b"
    )
    assert zip_a.read_bytes() == zip_b.read_bytes()
    assert payload_a == payload_b
    assert manifest_a == manifest_b


def test_zip_entries_sorted_fixed_metadata(tmp_path: Path) -> None:
    zip_path, _sha, _payload, _manifest = support.package_from_build_dir(tmp_path)
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names)
        roots = {n.split("/", 1)[0] for n in names}
        assert roots == {"vdog-xiao-sense-local"}
        for info in infos:
            assert info.date_time == ZIP_DATE_TIME
            assert info.create_system == 0
            mode = stat.S_IMODE(info.external_attr >> 16)
            if info.is_dir():
                assert mode == 0o755
            else:
                assert mode == 0o644
                assert info.compress_type == zipfile.ZIP_DEFLATED
                assert not stat.S_ISLNK(info.external_attr >> 16)


def test_no_absolute_or_escaping_members(tmp_path: Path) -> None:
    zip_path, _sha, _payload, _manifest = support.package_from_build_dir(tmp_path)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            assert not info.filename.startswith("/")
            assert "\\" not in info.filename
            assert ".." not in info.filename.split("/")


def test_manifest_self_exclusion_and_coverage(tmp_path: Path) -> None:
    _zip, _sha, payload, manifest = support.package_from_build_dir(tmp_path)
    covered = {entry["path"] for entry in manifest["files"]}
    assert "manifest.json" not in covered
    assert "SHA256SUMS" not in covered
    assert covered == set(contract.PACKAGE_REQUIRED_FILES) - {
        "manifest.json", "SHA256SUMS",
    }
    for entry in manifest["files"]:
        data = payload[entry["path"]]
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["size"] == len(data)
    sums_text = payload["SHA256SUMS"].decode("utf-8")
    sums = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in sums_text.splitlines() if line
    }
    assert set(sums) == set(contract.PACKAGE_REQUIRED_FILES) - {"SHA256SUMS"}
    assert "manifest.json" in sums
    for path, digest in sums.items():
        assert hashlib.sha256(payload[path]).hexdigest() == digest


def test_external_digest_sidecar(tmp_path: Path) -> None:
    zip_path, sha_path, _payload, _manifest = support.package_from_build_dir(tmp_path)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert sha_path.read_text(encoding="utf-8").split() == [digest, zip_path.name]


def test_pr_identity_and_ci(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="pr")
    meta.touch()
    _zip, _sha, payload, manifest = support.package_from_build_dir(
        tmp_path / "out",
        build_dir=build_dir,
        metadata_path=meta,
        pr_number=7,
        base_sha=support.FULL_SHA_B,
        run_id=12345,
        attempt=2,
    )
    assert manifest["source"] == {
        "kind": "pr", "sha": support.FULL_SHA_A, "sha_short": support.SHA_A_12,
        "pr_number": 7, "base_sha": support.FULL_SHA_B, "dirty": False,
    }
    assert manifest["build_id"] == f"pr-7-{support.SHA_A_12}"
    assert manifest["tag"] is None
    assert manifest["ci"] == {"run_id": 12345, "attempt": 2}
    version = json.loads(payload["VERSION.json"])
    assert version["pr_number"] == 7 and version["ci_attempt"] == 2
    assert validate_package_bytes(_zip.read_bytes()) == []


def test_main_identity_carries_tag(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="main")
    meta.touch()
    _zip, _sha, payload, manifest = support.package_from_build_dir(
        tmp_path / "out", build_dir=build_dir, metadata_path=meta
    )
    sha12 = support.FULL_SHA_B[:12]
    assert manifest["tag"] == f"firmware-main-{sha12}"
    assert manifest["build_id"] == f"main-{sha12}"
    assert json.loads(payload["VERSION.json"])["tag"] == f"firmware-main-{sha12}"
    assert package_root_name(manifest["build_id"]) in _zip.name


def test_kind_contradiction_rejected(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="pr")
    meta.touch()
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=meta, kind="main"
        )
    assert any("contradicts" in e for e in exc.value.errors)


def test_run_id_attempt_must_pair(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="pr")
    meta.touch()
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=meta,
            pr_number=7, base_sha=support.FULL_SHA_B, run_id=9, attempt=None,
        )
    assert any("together" in e for e in exc.value.errors)


def test_local_build_must_not_carry_ci_identity(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, run_id=5, attempt=1,
        )
    assert any("must not carry CI identity" in e for e in exc.value.errors)


def test_pr_main_identity_verifies_checkout_by_default(tmp_path: Path) -> None:
    # The release path verifies pr/main identities against the checkout even
    # when the caller omits repo_root: a synthetic CI-looking SHA that is not
    # HEAD must be refused (no --verify-git flag required).
    from tools.firmware import package as pkg

    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="pr")
    meta.touch()
    sources = support._default_sources(tmp_path)
    with pytest.raises(ContractError) as exc:
        pkg.build_payload(
            build_dir=build_dir,
            partition_csv=support.PARTITION_CSV,
            metadata_path=meta,
            core_header_path=support.CORE_HEADER,
            kind="pr", pr_number=7, base_sha=support.FULL_SHA_B,
            run_id=None, attempt=None,
            **sources,
        )
    assert any("replaced source" in e or "dirty source" in e for e in exc.value.errors)


def test_pr_package_requires_base_sha(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", kind="pr")
    meta.touch()
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=meta,
            pr_number=7, base_sha=None,
        )
    assert any("base" in e.lower() for e in exc.value.errors)


def test_version_mismatch_with_core_header_rejected(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta", firmware_version="0.9.9-proto")
    meta.touch()
    with pytest.raises(ContractError):
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=meta
        )


def test_package_contains_pinned_installer_lock(tmp_path: Path) -> None:
    _zip, _sha, payload, manifest = support.package_from_build_dir(tmp_path)
    lock_bytes = payload["requirements-installer.lock"]
    on_disk = (TOOLS_DIR / "installer/requirements-installer.lock").read_bytes()
    assert lock_bytes == on_disk
    text = lock_bytes.decode("utf-8")
    assert "esptool==5.4.0" in text
    pins = [line for line in text.splitlines() if "==" in line and not line.startswith("#")]
    assert pins
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "==" in line and not line.startswith("#") and not line.startswith(" "):
            window = "\n".join(lines[index:index + 60])
            assert "--hash=sha256:" in window.split("# via")[0], line
    assert manifest["toolchain"]["esptool_version"] == "5.4.0"


def test_dev_lock_pins_test_dependencies() -> None:
    text = (TOOLS_DIR / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "pytest==" in text and "jsonschema==" in text
    assert "--hash=sha256:" in text


def test_packaged_install_py_is_repo_installer(tmp_path: Path) -> None:
    _zip, _sha, payload, _manifest = support.package_from_build_dir(tmp_path)
    on_disk = (TOOLS_DIR / "installer/install.py").read_bytes()
    assert payload["install.py"] == on_disk


def test_packaged_install_py_is_stdlib_only(tmp_path: Path) -> None:
    import ast
    import sys

    _zip, _sha, payload, _manifest = support.package_from_build_dir(tmp_path)
    tree = ast.parse(payload["install.py"].decode("utf-8"))
    for node in tree.body:  # module level only
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            root = name.split(".")[0]
            assert root in sys.stdlib_module_names, f"non-stdlib module-level import {name}"


def test_packaging_survives_spaces_and_unicode_paths(tmp_path: Path) -> None:
    odd = tmp_path / "wörk dir" / "测试 dir"
    build_dir = support.write_build_dir(odd / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(odd / "meta")
    meta.touch()
    zip_path, _sha, _payload, manifest = support.package_from_build_dir(
        odd / "dist", build_dir=build_dir, metadata_path=meta, output_dir=odd / "dist"
    )
    assert validate_package_bytes(zip_path.read_bytes()) == []
    assert manifest["build_id"] == "local"
