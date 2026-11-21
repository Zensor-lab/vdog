"""Source identity, build ID derivation and VERSION.json emission (0.9.2).

Consumes the ``vdog-build-metadata-v1`` document emitted by the firmware
build (produced by the ESP32 packet at ``firmware/.vdog-build-metadata.json``)
and turns it into the release identity fields of ``firmware-release-v1`` and
the payload ``VERSION.json``.

Specs: docs/plans/0.9-firmware-ci-release.md sections 3-4,
docs/plans/0.9-round1-assignment.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow `python tools/firmware/metadata.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.firmware import contract
from tools.firmware.contract import (
    BUILD_METADATA_SCHEMA,
    ContractError,
    ENVIRONMENT,
    EXPECTED_FLASH_BYTES,
    FIRMWARE_VERSION,
    PACKAGE_FORMAT_VERSION,
    PRODUCT,
    PRODUCT_SLUG,
    RELEASE_CHANNEL,
    TARGET,
    TOOLCHAIN_ESPTOOL_VERSION,
    TOOLCHAIN_IDF_VERSION,
    TOOLCHAIN_PLATFORM,
    TOOLCHAIN_PLATFORMIO_CORE,
    derive_build_id,
    derive_tag,
    short_sha,
    validate_build_metadata,
)

DEFAULT_METADATA_PATH = Path("firmware/.vdog-build-metadata.json")
DEFAULT_CORE_HEADER = Path("firmware/core/vdog_core.h")
GIT_TIMEOUT_SECONDS = 30


class MetadataError(ContractError):
    """Identity/metadata validation failure carrying all collected errors."""


def load_build_metadata(path: Path) -> dict[str, Any]:
    """Read and validate a vdog-build-metadata-v1 JSON file."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise MetadataError([f"build metadata: cannot read {path}: {exc}"]) from exc
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError([f"build metadata: invalid JSON in {path}: {exc}"]) from exc
    errors = validate_build_metadata(doc)
    if errors:
        raise MetadataError(errors)
    return doc


def check_build_metadata_freshness(
    build_dir: Path,
    metadata: dict[str, Any],
    *,
    metadata_path: Path,
    environment: str = ENVIRONMENT,
    staleness_tolerance_seconds: float = 1.0,
) -> None:
    """Reject build dirs whose build metadata is missing/stale (Orchestrator
    addendum, 2026-11-21).

    The export/package steps may only consume a build directory produced by a
    plain ``pio run -e vdog_xiao_sense_proto`` that exited 0; the firmware-side
    metadata post-action rewrites ``.vdog-build-metadata.json`` inside that
    same run. Therefore the metadata file must:

    * exist at the requested path (a missing file is a hard failure — a build
      directory from before the metadata integration, or one cleaned/partially
      rebuilt, is not acceptable);
    * declare ``environment`` equal to the build directory name (no consuming
      a different environment's identity);
    * be at least as new as every builder output it is packaged with (a
      stale identity document from an earlier run is a hard failure).
    """
    errors: list[str] = []
    path = Path(metadata_path)
    if not path.is_file():
        errors.append(
            f"build metadata: {path} is missing — the build dir may only be used "
            "from a plain `pio run` exit 0 whose metadata post-action wrote this file"
        )
    if Path(build_dir).resolve().name != environment:
        errors.append(
            f"build metadata: build dir {Path(build_dir).name!r} does not match the "
            f"metadata environment {metadata.get('environment')!r}/{environment!r}"
        )
    if path.is_file():
        mtime = path.stat().st_mtime
        outputs = [
            Path(build_dir) / name
            for name in (
                *sorted(contract.ROLE_BUILD_FILE.values()),
                "flasher_args.json",
                "flash_args",
            )
        ]
        newest = 0.0
        for output in outputs:
            try:
                newest = max(newest, output.stat().st_mtime)
            except OSError:
                continue  # existence itself is validated by the exporter
        if newest and mtime < newest - staleness_tolerance_seconds:
            errors.append(
                f"build metadata: {path} (mtime {mtime}) is older than the builder "
                "outputs (mtime {0}); the identity is stale relative to this build — "
                "rerun pio run".format(newest)
            )
    if errors:
        raise MetadataError(errors)


def expected_version_from_core_header(path: Path) -> str:
    """Reconstruct the semantic version string from firmware/core/vdog_core.h.

    Guards against a metadata document disagreeing with the compiled-in
    version (addendum: firmware_version must match vdog_core.h).
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataError([f"core header: cannot read {path}: {exc}"]) from exc

    def define(name: str) -> str:
        match = re.search(
            rf"^[ \t]*#[ \t]*define[ \t]+{re.escape(name)}[ \t]+(\S+)[ \t]*$",
            text,
            re.MULTILINE,
        )
        if not match:
            raise MetadataError([f"core header: missing #define {name}"])
        return match.group(1)

    major, minor, patch = define("VDOG_VERSION_MAJOR"), define("VDOG_VERSION_MINOR"), define("VDOG_VERSION_PATCH")
    suffix = define("VDOG_VERSION_SUFFIX")
    if not re.fullmatch(r"\d+[uU]?", major) or not re.fullmatch(r"\d+[uU]?", minor) \
            or not re.fullmatch(r"\d+[uU]?", patch):
        raise MetadataError(["core header: version components must be decimal"])
    major_i, minor_i, patch_i = (int(v.rstrip("uU")) for v in (major, minor, patch))
    if len(suffix) < 2 or not (suffix.startswith('"') and suffix.endswith('"')):
        raise MetadataError([f"core header: unexpected suffix literal {suffix!r}"])
    inner = suffix[1:-1]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", inner):
        raise MetadataError([f"core header: invalid version suffix {inner!r}"])
    return f"{major_i}.{minor_i}.{patch_i}-{inner}"


def source_identity(
    metadata: dict[str, Any],
    *,
    kind: str,
    pr_number: int | None = None,
    base_sha: str | None = None,
) -> dict[str, Any]:
    """Build the validated ``manifest.source`` object from build metadata.

    ``local`` accepts the metadata's literal ``local`` identity — and only
    that literal identity: a metadata document carrying ``local`` cannot be
    packaged as a ``pr``/``main`` release, and a metadata document carrying a
    real SHA cannot be silently demoted to ``local``. In CI mode (``pr`` or
    ``main``) an empty-string, missing-shaped or otherwise malformed
    ``source_sha``/``build_id`` is a HARD failure and is never downgraded to
    ``local`` (Orchestrator addendum, 2026-11-21; the firmware-side generator
    maps empty CI inputs to ``local`` at build time only). A ``local``
    package is local/unpublishable in manifest terms: ``source.kind=local``,
    ``build_id="local"``, ``tag=null`` and ``ci=null``, so no tag/release
    identity can ever be attached to it.
    """
    errors = validate_build_metadata(metadata)
    if errors:
        raise MetadataError(errors)
    if kind not in contract.SOURCE_KINDS:
        raise MetadataError([f"source_identity: unknown kind {kind!r}"])
    sha = metadata["source_sha"]
    build_id = metadata["build_id"]
    if kind == "local":
        if sha != "local" or build_id != "local":
            raise MetadataError(
                [
                    "source_identity: local packaging requires the metadata local "
                    f"identity, got source_sha={sha!r} build_id={build_id!r}"
                ]
            )
        return {
            "kind": "local",
            "sha": "local",
            "sha_short": "local",
            "pr_number": None,
            "base_sha": None,
            "dirty": False,
        }
    if not contract.FULL_SHA_RE.match(sha):
        raise MetadataError(
            [f"source_identity: {kind} packaging requires a full-SHA metadata "
             f"source_sha, got {sha!r} (run the build with VDOG_SOURCE_SHA set)"]
        )
    want_build_id = derive_build_id(kind, pr_number=pr_number, sha=sha)
    if build_id != want_build_id:
        raise MetadataError(
            [f"source_identity: metadata build_id {build_id!r} does not match "
             f"the {kind} identity {want_build_id!r}"]
        )
    if kind == "pr":
        if base_sha is None or not contract.FULL_SHA_RE.match(base_sha):
            raise MetadataError(
                [f"source_identity: pr kind requires a full-SHA --base-sha, got {base_sha!r}"]
            )
        if base_sha == sha:
            raise MetadataError(["source_identity: base SHA must differ from head SHA"])
    return {
        "kind": kind,
        "sha": sha,
        "sha_short": short_sha(sha),
        "pr_number": pr_number if kind == "pr" else None,
        "base_sha": base_sha if kind == "pr" else None,
        "dirty": False,
    }


def derive_tag_for(kind: str, sha: str) -> str | None:
    return derive_tag(kind, sha)


# ---------------------------------------------------------------------------
# Git source verification (dirty / replaced-source rejection)
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo_root), *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MetadataError([f"git {args[0]} failed: {exc}"]) from exc
    if proc.returncode != 0:
        raise MetadataError(
            [f"git {args[0]} exited {proc.returncode}: {proc.stderr.strip()}"]
        )
    return proc.stdout


def verify_source_identity(
    repo_root: Path,
    *,
    kind: str,
    expected_sha: str | None,
    require_clean: bool = True,
) -> None:
    """Reject dirty or replaced sources before packaging (master plan 0.9.2).

    ``main``/``pr`` packaging calls this with ``require_clean=True``: the
    checked-out HEAD must be the claimed full SHA (no replaced source) and the
    tracked worktree must be clean (no dirty source). Local builds keep an
    explicit local identity and are never claimed to be any commit.
    """
    errors: list[str] = []
    if kind == "local":
        if expected_sha is not None:
            errors.append("verify_source_identity: local builds must not claim a SHA")
        return_check = _git(repo_root, "rev-parse", "--git-dir")
        if not return_check:
            errors.append("verify_source_identity: not a git checkout")
        if errors:
            raise MetadataError(errors)
        return
    if expected_sha is None or not contract.FULL_SHA_RE.match(expected_sha):
        raise MetadataError(
            [f"verify_source_identity: {kind} builds need a full-SHA source, got {expected_sha!r}"]
        )
    head = _git(repo_root, "rev-parse", "HEAD").strip()
    if head != expected_sha:
        errors.append(
            f"verify_source_identity: checkout HEAD {head!r} does not match claimed "
            f"source SHA {expected_sha!r} (replaced source)"
        )
    if require_clean:
        status = _git(
            repo_root, "status", "--porcelain", "--untracked-files=normal",
            "--ignore-submodules=none",
        )
        dirty = [line for line in status.splitlines() if line.strip()]
        # Ignored/generated build output (firmware/.pio, .vdog-build-metadata.json)
        # never appears in --porcelain; anything listed is a real source change.
        if dirty:
            errors.append(
                "verify_source_identity: dirty source tree — commit or stash before "
                f"packaging ({len(dirty)} entries, e.g. {dirty[0]!r})"
            )
    if errors:
        raise MetadataError(errors)


# ---------------------------------------------------------------------------
# VERSION.json emission (deterministic)
# ---------------------------------------------------------------------------


def version_document(
    *,
    source: dict[str, Any],
    build_id: str,
    tag: str | None,
    ci: dict[str, int] | None,
) -> dict[str, Any]:
    """Deterministic VERSION.json payload (master plan section 4)."""
    errors = contract.validate_build_id(build_id, where="VERSION.json.build_id")
    if errors:
        raise MetadataError(errors)
    return {
        "schema": "vdog-version-v1",
        "package_format_version": PACKAGE_FORMAT_VERSION,
        "product": PRODUCT,
        "product_slug": PRODUCT_SLUG,
        "hardware_class": contract.HARDWARE_CLASS,
        "board": contract.BOARD,
        "environment": contract.ENVIRONMENT,
        "target": TARGET,
        "expected_flash_bytes": EXPECTED_FLASH_BYTES,
        "firmware_version": FIRMWARE_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "hardware_verified": False,
        "recording_available": False,
        "device_ota_available": False,
        "source_kind": source["kind"],
        "source_sha": source["sha"],
        "source_sha_short": source["sha_short"],
        "pr_number": source.get("pr_number"),
        "base_sha": source.get("base_sha"),
        "build_id": build_id,
        "tag": tag,
        "ci_run_id": None if ci is None else ci["run_id"],
        "ci_attempt": None if ci is None else ci["attempt"],
        "toolchain": {
            "platformio_core": TOOLCHAIN_PLATFORMIO_CORE,
            "platform": TOOLCHAIN_PLATFORM,
            "idf_version": TOOLCHAIN_IDF_VERSION,
            "esptool_version": TOOLCHAIN_ESPTOOL_VERSION,
        },
    }


def dump_json(data: Any) -> str:
    """Canonical deterministic JSON text used for all emitted JSON files."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def check_version_against_manifest(version: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """VERSION.json must agree with the manifest identity field-by-field."""
    errors: list[str] = []
    source = manifest.get("source", {})
    pairs = {
        "firmware_version": manifest.get("firmware_version"),
        "release_channel": manifest.get("release_channel"),
        "hardware_verified": manifest.get("hardware_verified"),
        "recording_available": manifest.get("recording_available"),
        "device_ota_available": manifest.get("device_ota_available"),
        "build_id": manifest.get("build_id"),
        "tag": manifest.get("tag"),
        "target": manifest.get("target"),
        "board": manifest.get("board"),
        "environment": manifest.get("environment"),
        "expected_flash_bytes": manifest.get("expected_flash_bytes"),
        "source_kind": source.get("kind"),
        "source_sha": source.get("sha"),
        "source_sha_short": source.get("sha_short"),
        "pr_number": source.get("pr_number"),
        "base_sha": source.get("base_sha"),
        "ci_run_id": None if manifest.get("ci") is None else manifest["ci"]["run_id"],
        "ci_attempt": None if manifest.get("ci") is None else manifest["ci"]["attempt"],
    }
    for field, want in pairs.items():
        if version.get(field) != want:
            errors.append(
                f"VERSION.json.{field}: {version.get(field)!r} != manifest {want!r}"
            )
    if version.get("toolchain") != manifest.get("toolchain"):
        errors.append(
            f"VERSION.json.toolchain: {version.get('toolchain')!r} != manifest "
            f"{manifest.get('toolchain')!r}"
        )
    return errors


def check_metadata_against_manifest(
    metadata: dict[str, Any], manifest: dict[str, Any]
) -> list[str]:
    """The consumed build metadata must match the manifest it describes."""
    errors: list[str] = []
    source = manifest.get("source") or {}
    if not isinstance(source, dict):
        return ["manifest.source: must be an object"]
    if metadata.get("firmware_version") != manifest.get("firmware_version"):
        errors.append(
            f"metadata.firmware_version {metadata.get('firmware_version')!r} != "
            f"manifest {manifest.get('firmware_version')!r}"
        )
    if metadata.get("environment") != manifest.get("environment"):
        errors.append(
            f"metadata.environment {metadata.get('environment')!r} != manifest "
            f"{manifest.get('environment')!r}"
        )
    if metadata.get("source_sha") != source.get("sha"):
        errors.append(
            f"metadata.source_sha {metadata.get('source_sha')!r} != manifest "
            f"source.sha {source.get('sha')!r}"
        )
    if metadata.get("build_id") != manifest.get("build_id"):
        errors.append(
            f"metadata.build_id {metadata.get('build_id')!r} != manifest "
            f"build_id {manifest.get('build_id')!r}"
        )
    toolchain = manifest.get("toolchain") or {}
    if metadata.get("esptool_version") != toolchain.get("esptool_version"):
        errors.append("metadata.esptool_version != manifest toolchain.esptool_version")
    if metadata.get("platform") != toolchain.get("platform"):
        errors.append("metadata.platform != manifest toolchain.platform")
    if metadata.get("idf_version") != toolchain.get("idf_version"):
        errors.append("metadata.idf_version != manifest toolchain.idf_version")
    return errors


# ---------------------------------------------------------------------------
# CLI (smoke-testable entry point)
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.metadata",
        description="Validate/inspect vdog-build-metadata-v1 and emit VERSION.json.",
    )
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH,
                        help="path to the vdog-build-metadata-v1 JSON")
    parser.add_argument("--core-header", type=Path, default=DEFAULT_CORE_HEADER,
                        help="vdog_core.h path used for version cross-check")
    parser.add_argument("--kind", choices=contract.SOURCE_KINDS, required=True,
                        help="expected identity kind; 'local' is the explicit "
                             "local/unpublishable mode and is never inferred")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--base-sha")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--verify-git", action="store_true",
                        help="verify HEAD/clean tree for pr/main identities")
    parser.add_argument("--output", type=Path,
                        help="write VERSION.json here instead of stdout")
    args = parser.parse_args(argv)

    try:
        metadata = load_build_metadata(args.metadata)
        header_version = expected_version_from_core_header(args.core_header)
        if header_version != metadata["firmware_version"]:
            raise MetadataError(
                [f"firmware_version {metadata['firmware_version']!r} does not match "
                 f"vdog_core.h version {header_version!r}"]
            )
        source = source_identity(
            metadata, kind=args.kind, pr_number=args.pr_number, base_sha=args.base_sha
        )
        if args.verify_git:
            verify_source_identity(
                args.repo_root,
                kind=args.kind,
                expected_sha=None if args.kind == "local" else metadata["source_sha"],
            )
        tag = derive_tag_for(args.kind, metadata["source_sha"])
        doc = version_document(
            source=source, build_id=metadata["build_id"], tag=tag, ci=None
        )
    except ContractError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    text = dump_json(doc)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
