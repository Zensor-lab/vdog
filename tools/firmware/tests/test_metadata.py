"""Identity/metadata tests (work package 0.9.2), including the two
Orchestrator addendum items carried over from Packet A:

1. strict CI identity — empty/malformed ``source_sha``/``build_id`` is a hard
   failure in ``pr``/``main`` mode and never silently downgraded to local;
   ``local`` is only available through the explicit kind argument and marks
   the package unpublishable (``tag=null``, ``ci=null``, ``build_id=local``);
2. build-dir gating — packaging/export refuse a build directory whose
   ``.vdog-build-metadata.json`` is missing or stale relative to builder
   outputs (only a plain ``pio run`` exit 0 refreshes it).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.firmware import metadata as md
from tools.firmware import package as pkg
from tools.firmware.contract import ContractError

import support


# ---------------------------------------------------------------------------
# vdog-build-metadata-v1 loading
# ---------------------------------------------------------------------------


def test_load_build_metadata_valid(tmp_path: Path) -> None:
    path = support.write_metadata(tmp_path)
    doc = md.load_build_metadata(path)
    assert doc["schema"] == "vdog-build-metadata-v1"
    assert doc["build_id"] == "local"


def test_load_build_metadata_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as exc:
        md.load_build_metadata(tmp_path / "nope.json")
    assert any("cannot read" in e for e in exc.value.errors)


def test_load_build_metadata_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        md.load_build_metadata(path)
    assert any("invalid JSON" in e for e in exc.value.errors)


# ---------------------------------------------------------------------------
# Addendum item 1 — strict CI identity, no silent "local" downgrade
# ---------------------------------------------------------------------------


def test_local_identity_only_through_explicit_local() -> None:
    source = md.source_identity(
        {"schema": "vdog-build-metadata-v1", "firmware_version": "0.2.0-proto",
         "source_sha": "local", "build_id": "local",
         "environment": "vdog_xiao_sense_proto",
         "platform": "platformio/espressif32@8.0.0", "idf_version": "v6.1.0",
         "esptool_version": "5.4.0"},
        kind="local",
    )
    assert source == {
        "kind": "local", "sha": "local", "sha_short": "local",
        "pr_number": None, "base_sha": None, "dirty": False,
    }


def test_real_sha_never_demoted_to_local() -> None:
    meta = {
        "schema": "vdog-build-metadata-v1", "firmware_version": "0.2.0-proto",
        "source_sha": support.FULL_SHA_A, "build_id": f"main-{support.SHA_A_12}",
        "environment": "vdog_xiao_sense_proto",
        "platform": "platformio/espressif32@8.0.0", "idf_version": "v6.1.0",
        "esptool_version": "5.4.0",
    }
    with pytest.raises(ContractError) as exc:
        md.source_identity(meta, kind="local")
    assert any("local packaging requires the metadata local identity" in e
               for e in exc.value.errors)


@pytest.mark.parametrize("kind", ["pr", "main"])
@pytest.mark.parametrize(
    "sha,build_id",
    [
        ("", ""),                                   # empty CI identity
        ("local", "local"),                         # firmware-side empty mapping
        ("0f1e", "pr-7-000000000000"),              # malformed sha
        (support.FULL_SHA_A.upper(), "x"),          # uppercase not accepted
        (support.FULL_SHA_A, ""),                   # missing build_id
        (support.FULL_SHA_A, "totally-made-up"),    # unrelated token
    ],
    ids=["empty", "local-mapping", "short-sha", "upper-sha", "empty-id", "bogus-id"],
)
def test_ci_kind_hard_fails_on_bad_identity(kind: str, sha: str, build_id: str) -> None:
    meta = {
        "schema": "vdog-build-metadata-v1", "firmware_version": "0.2.0-proto",
        "source_sha": sha, "build_id": build_id,
        "environment": "vdog_xiao_sense_proto",
        "platform": "platformio/espressif32@8.0.0", "idf_version": "v6.1.0",
        "esptool_version": "5.4.0",
    }
    with pytest.raises(ContractError):
        md.source_identity(meta, kind=kind, pr_number=7, base_sha=support.FULL_SHA_B)


def test_ci_kind_requires_matching_build_id_and_base_sha() -> None:
    meta = {
        "schema": "vdog-build-metadata-v1", "firmware_version": "0.2.0-proto",
        "source_sha": support.FULL_SHA_A, "build_id": f"main-{support.SHA_A_12}",
        "environment": "vdog_xiao_sense_proto",
        "platform": "platformio/espressif32@8.0.0", "idf_version": "v6.1.0",
        "esptool_version": "5.4.0",
    }
    # main identity under pr kind: hard failure, no downgrade.
    with pytest.raises(ContractError):
        md.source_identity(meta, kind="pr", pr_number=7, base_sha=support.FULL_SHA_B)
    # pr identity without base SHA: hard failure.
    pr_meta = dict(meta, build_id=f"pr-7-{support.SHA_A_12}")
    with pytest.raises(ContractError) as exc:
        md.source_identity(pr_meta, kind="pr", pr_number=7, base_sha=None)
    assert any("base" in e for e in exc.value.errors)
    with pytest.raises(ContractError):
        md.source_identity(pr_meta, kind="pr", pr_number=7, base_sha=support.FULL_SHA_A)
    # valid pr identity works.
    source = md.source_identity(
        pr_meta, kind="pr", pr_number=7, base_sha=support.FULL_SHA_B
    )
    assert source["kind"] == "pr" and source["pr_number"] == 7


def test_local_package_is_unpublishable(tmp_path: Path) -> None:
    zip_path, _sha, _payload, manifest = support.package_from_build_dir(tmp_path)
    assert manifest["source"]["kind"] == "local"
    assert manifest["build_id"] == "local"
    assert manifest["tag"] is None
    assert manifest["ci"] is None


def test_metadata_cli_requires_explicit_kind(tmp_path: Path) -> None:
    path = support.write_metadata(tmp_path)
    with pytest.raises(SystemExit) as exc:
        md._main(["--metadata", str(path)])
    assert exc.value.code == 2  # argparse: --kind is required, never inferred


def test_metadata_cli_emits_local_version_document(tmp_path: Path) -> None:
    path = support.write_metadata(tmp_path)
    out = tmp_path / "VERSION.json"
    assert md._main(["--metadata", str(path), "--kind", "local",
                     "--core-header", str(support.CORE_HEADER),
                     "--output", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "vdog-version-v1"
    assert doc["build_id"] == "local" and doc["tag"] is None
    assert doc["ci_run_id"] is None and doc["ci_attempt"] is None
    assert doc["toolchain"]["esptool_version"] == "5.4.0"


def test_metadata_cli_rejects_ci_kind_for_local_metadata(tmp_path: Path) -> None:
    path = support.write_metadata(tmp_path)
    assert md._main(["--metadata", str(path), "--kind", "main",
                     "--core-header", str(support.CORE_HEADER)]) == 1


# ---------------------------------------------------------------------------
# Addendum item 2 — build-dir metadata freshness gate
# ---------------------------------------------------------------------------


def _fresh(tmp_path: Path) -> tuple[Path, Path]:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta")
    meta.touch()
    return build_dir, meta


def test_freshness_gate_accepts_fresh(tmp_path: Path) -> None:
    build_dir, meta = _fresh(tmp_path)
    doc = md.load_build_metadata(meta)
    md.check_build_metadata_freshness(build_dir, doc, metadata_path=meta)


def test_freshness_gate_rejects_missing(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    missing = tmp_path / "build" / "vdog_xiao_sense_proto" / ".vdog-build-metadata.json"
    doc = md.load_build_metadata(support.write_metadata(tmp_path / "meta"))
    with pytest.raises(ContractError) as exc:
        md.check_build_metadata_freshness(build_dir, doc, metadata_path=missing)
    assert any("missing" in e for e in exc.value.errors)


def test_freshness_gate_rejects_stale(tmp_path: Path) -> None:
    build_dir, meta = _fresh(tmp_path)
    old = 1_000_000_000.0  # 2001: long before the builder outputs
    os.utime(meta, (old, old))
    doc = md.load_build_metadata(meta)
    with pytest.raises(ContractError) as exc:
        md.check_build_metadata_freshness(build_dir, doc, metadata_path=meta)
    assert any("stale" in e for e in exc.value.errors)


def test_freshness_gate_rejects_environment_mismatch(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "some_other_env")
    meta = support.write_metadata(tmp_path / "meta")
    doc = md.load_build_metadata(meta)
    with pytest.raises(ContractError) as exc:
        md.check_build_metadata_freshness(build_dir, doc, metadata_path=meta)
    assert any("does not match the metadata environment" in e for e in exc.value.errors)


def test_packaging_refuses_stale_metadata(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    meta = support.write_metadata(tmp_path / "meta")
    old = 1_000_000_000.0
    os.utime(meta, (old, old))
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=meta
        )
    assert any("stale" in e for e in exc.value.errors)


def test_packaging_refuses_missing_metadata(tmp_path: Path) -> None:
    build_dir = support.write_build_dir(tmp_path / "build" / "vdog_xiao_sense_proto")
    with pytest.raises(ContractError) as exc:
        support.package_from_build_dir(
            tmp_path, build_dir=build_dir, metadata_path=tmp_path / "absent.json"
        )
    assert any("cannot read" in e for e in exc.value.errors)


# ---------------------------------------------------------------------------
# VERSION.json / metadata cross-checks
# ---------------------------------------------------------------------------


def test_version_document_agrees_with_manifest(tmp_path: Path) -> None:
    _zip, _sha, _payload, manifest = support.package_from_build_dir(tmp_path)
    source = manifest["source"]
    doc = md.version_document(
        source=source, build_id=manifest["build_id"], tag=manifest["tag"],
        ci=manifest["ci"],
    )
    assert md.check_version_against_manifest(doc, manifest) == []
    doc["build_id"] = "other"
    assert any("build_id" in e for e in md.check_version_against_manifest(doc, manifest))


def test_check_metadata_against_manifest_detects_divergence(tmp_path: Path) -> None:
    _zip, _sha, _payload, manifest = support.package_from_build_dir(tmp_path)
    meta = {"firmware_version": manifest["firmware_version"],
            "environment": manifest["environment"],
            "source_sha": "local", "build_id": "local",
            "esptool_version": "5.4.0", "platform": "platformio/espressif32@8.0.0",
            "idf_version": "v6.1.0"}
    assert md.check_metadata_against_manifest(meta, manifest) == []
    meta["build_id"] = "main-000000000000"
    assert any("build_id" in e for e in md.check_metadata_against_manifest(meta, manifest))


def test_core_header_version_matches_baseline() -> None:
    assert md.expected_version_from_core_header(support.CORE_HEADER) == "0.2.0-proto"


def test_core_header_rejects_missing_defines(tmp_path: Path) -> None:
    path = tmp_path / "broken.h"
    path.write_text("#define NOTHING 1\n", encoding="utf-8")
    with pytest.raises(ContractError):
        md.expected_version_from_core_header(path)


# ---------------------------------------------------------------------------
# Git source verification (dirty / replaced source rejection)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.invalid",
         "-c", "user.name=vdog-test", *args],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    head = _git(repo, "rev-parse", "HEAD")
    return repo, head


def test_verify_source_identity_clean_head(git_repo: tuple[Path, str]) -> None:
    repo, head = git_repo
    md.verify_source_identity(repo, kind="main", expected_sha=head)


def test_verify_source_identity_replaces_source(git_repo: tuple[Path, str]) -> None:
    repo, _head = git_repo
    with pytest.raises(ContractError) as exc:
        md.verify_source_identity(repo, kind="main", expected_sha="0" * 40)
    assert any("replaced source" in e for e in exc.value.errors)


def test_verify_source_identity_rejects_dirty(git_repo: tuple[Path, str]) -> None:
    repo, head = git_repo
    (repo / "dirty.txt").write_text("untracked\n", encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        md.verify_source_identity(repo, kind="main", expected_sha=head)
    assert any("dirty source" in e for e in exc.value.errors)


def test_verify_source_identity_local_builds(git_repo: tuple[Path, str]) -> None:
    repo, _head = git_repo
    md.verify_source_identity(repo, kind="local", expected_sha=None)
    with pytest.raises(ContractError):
        md.verify_source_identity(repo, kind="local", expected_sha="0" * 40)


def test_packaging_verify_git_replaces_source(tmp_path: Path, git_repo) -> None:
    # pr metadata claiming a SHA that is not HEAD must be rejected when
    # --verify-git semantics are requested (repo_root provided).
    repo, _head = git_repo
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
            repo_root=repo,
            **sources,
        )
    assert any("replaced source" in e for e in exc.value.errors)
