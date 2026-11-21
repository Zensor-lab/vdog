"""Deterministic, safe assembly of the vdog firmware installation ZIP (0.9.4).

Builds the single-root payload defined by docs/plans/0.9-firmware-ci-release.md
section 4 from a normal PlatformIO build directory plus the consumed
``vdog-build-metadata-v1`` document: stable entry ordering, fixed timestamps,
no symlinks/absolute paths, ``manifest.json`` + ``SHA256SUMS`` with the exact
self-exclusion rules, and an external ``<zip>.sha256``.

Specs: docs/plans/0.9-firmware-ci-release.md sections 3-4, work packages
0.9.3-0.9.4, docs/plans/0.9-round1-assignment.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.firmware import contract, metadata
from tools.firmware.contract import (
    ContractError,
    EXPECTED_FLASH_BYTES,
    MANIFEST_FILE,
    SHA256SUMS_FILE,
    TOOLCHAIN_ESPTOOL_VERSION,
    TOOLCHAIN_IDF_VERSION,
    TOOLCHAIN_PLATFORM,
    TOOLCHAIN_PLATFORMIO_CORE,
    derive_tag,
    parse_partition_csv,
)
from tools.firmware.export_flash_layout import (
    DEFAULT_BUILD_DIR,
    DEFAULT_PARTITION_CSV,
    export_flash_layout,
)
from tools.firmware.metadata import (
    DEFAULT_CORE_HEADER,
    DEFAULT_METADATA_PATH,
    check_build_metadata_freshness,
    check_metadata_against_manifest,
    check_version_against_manifest,
    dump_json,
    expected_version_from_core_header,
    load_build_metadata,
    source_identity,
    version_document,
)

TOOLS_DIR = Path(__file__).resolve().parent
INSTALLER_DIR = TOOLS_DIR / "installer"
TEMPLATES_DIR = TOOLS_DIR / "templates"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = TOOLS_DIR / "dist"

#: Fixed ZIP timestamps keep byte-for-byte determinism across runs.
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644
DIR_MODE = 0o755


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_root_name(build_id: str) -> str:
    return f"vdog-xiao-sense-{build_id}"


def _auto_kind(build_id: str) -> tuple[str, int | None]:
    if build_id == "local":
        return "local", None
    if build_id.startswith("pr-"):
        try:
            _, number, _rest = build_id.split("-", 2)
            return "pr", int(number)
        except ValueError:
            raise ContractError([f"package: cannot derive PR number from build_id {build_id!r}"])
    if build_id.startswith("main-"):
        return "main", None
    raise ContractError([f"package: unrecognized build_id {build_id!r}"])


def build_payload(
    *,
    build_dir: Path,
    partition_csv: Path,
    metadata_path: Path,
    core_header_path: Path,
    install_md_path: Path,
    release_notes_md_path: Path,
    license_path: Path,
    third_party_notices_path: Path,
    install_py_path: Path,
    install_sh_path: Path,
    install_ps1_path: Path,
    requirements_lock_path: Path,
    kind: str,
    pr_number: int | None,
    base_sha: str | None,
    run_id: int | None,
    attempt: int | None,
    flash_layout: dict[str, Any] | None = None,
    repo_root: Path | None = None,
    require_fresh_metadata: bool = True,
    skip_git_verify: bool = False,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Return (payload files keyed by package-relative path, manifest document).

    Deterministic: identical inputs produce identical bytes. Raises
    ContractError listing every problem found.

    The build directory may only come from a plain ``pio run`` exit 0 whose
    metadata post-action refreshed the ``vdog-build-metadata-v1`` file; a
    missing or stale metadata document relative to the builder outputs is a
    hard failure (``require_fresh_metadata`` is for forensics only and must
    never be used for release packaging).
    """
    errors: list[str] = []
    build_meta = load_build_metadata(metadata_path)
    if require_fresh_metadata:
        try:
            check_build_metadata_freshness(build_dir, build_meta,
                                           metadata_path=metadata_path)
        except ContractError as exc:
            errors.extend(exc.errors)
    header_version = expected_version_from_core_header(core_header_path)
    if header_version != build_meta["firmware_version"]:
        errors.append(
            f"package: build metadata firmware_version {build_meta['firmware_version']!r} "
            f"does not match vdog_core.h version {header_version!r}"
        )

    kind_derived, derived_pr = _auto_kind(build_meta["build_id"])
    if kind == "auto":
        kind = kind_derived
    elif kind != kind_derived:
        errors.append(
            f"package: --release-kind {kind!r} contradicts metadata build_id "
            f"{build_meta['build_id']!r} (kind {kind_derived!r})"
        )
    if kind == "pr" and pr_number is None:
        pr_number = derived_pr

    try:
        source = source_identity(
            build_meta, kind=kind, pr_number=pr_number, base_sha=base_sha
        )
    except ContractError as exc:
        errors.extend(exc.errors)
        raise ContractError(errors) from None

    if (run_id is None) != (attempt is None):
        errors.append("package: --run-id and --attempt must be supplied together")
        raise ContractError(errors)
    ci = None if run_id is None else {"run_id": run_id, "attempt": attempt}
    if kind == "local" and ci is not None:
        raise ContractError(
            ["package: local builds are unpublishable and must not carry CI "
             "identity (run_id/attempt are reserved for pr/main)"]
        )

    if repo_root is None and not skip_git_verify and kind in ("pr", "main"):
        # Release path default: CI-looking identities are always checked
        # against the checkout (dirty tree or replaced source is refused).
        repo_root = REPO_ROOT
    if repo_root is not None:
        try:
            metadata.verify_source_identity(
                repo_root,
                kind=kind,
                expected_sha=None if kind == "local" else build_meta["source_sha"],
            )
        except ContractError as exc:
            errors.extend(exc.errors)

    if flash_layout is None:
        try:
            flash_layout = export_flash_layout(build_dir, partition_csv)
        except ContractError as exc:
            errors.extend(exc.errors)
            raise ContractError(errors) from None
    else:
        layout_errors = contract.validate_flash_layout(flash_layout)
        if layout_errors:
            raise ContractError(list(layout_errors))

    layout_by_role = {seg["role"]: seg for seg in flash_layout["segments"]}

    # --- read images and verify against the layout -------------------------
    image_payload: dict[str, bytes] = {}
    images_manifest: list[dict[str, Any]] = []
    for role in contract.IMAGE_ROLES:
        seg = layout_by_role[role]
        src = Path(build_dir) / contract.ROLE_BUILD_FILE[role]
        try:
            data = src.read_bytes()
        except OSError as exc:
            errors.append(f"package: cannot read {src}: {exc}")
            continue
        digest = sha256_bytes(data)
        if digest != seg["sha256"]:
            errors.append(
                f"package: {src.name} sha256 {digest} != flash layout {seg['sha256']}"
            )
            continue
        if len(data) != seg["size"]:
            errors.append(
                f"package: {src.name} size {len(data)} != flash layout {seg['size']}"
            )
            continue
        image_payload[seg["file"]] = data
        images_manifest.append(
            {
                "role": role,
                "file": seg["file"],
                "offset": seg["offset"],
                "size": len(data),
                "sha256": digest,
            }
        )

    # --- read supplied text/payload sources --------------------------------
    def read_source(path: Path, *, dest: str, required: bool = True) -> bytes | None:
        try:
            return Path(path).read_bytes()
        except OSError as exc:
            if required:
                errors.append(f"package: cannot read required source {path} for {dest}: {exc}")
            return None

    supplied: dict[str, bytes] = {}
    for dest, path in (
        ("INSTALL.md", install_md_path),
        ("RELEASE_NOTES.md", release_notes_md_path),
        ("LICENSE", license_path),
        ("THIRD_PARTY_NOTICES.md", third_party_notices_path),
        ("install.py", install_py_path),
        ("install.sh", install_sh_path),
        ("install.ps1", install_ps1_path),
        ("requirements-installer.lock", requirements_lock_path),
    ):
        data = read_source(path, dest=dest)
        if data is not None:
            supplied[dest] = data

    csv_bytes = read_source(partition_csv, dest="flash/partitions.csv")
    csv_entries: list[dict[str, Any]] = []
    if csv_bytes is not None:
        try:
            csv_entries = parse_partition_csv(
                csv_bytes.decode("utf-8"), where=str(partition_csv)
            )
        except ContractError as exc:
            errors.extend(exc.errors)
        supplied["flash/partitions.csv"] = csv_bytes

    if errors:
        raise ContractError(errors)

    # --- manifest identity ---------------------------------------------------
    tag = derive_tag(kind, source["sha"])
    toolchain = {
        "platformio_core": TOOLCHAIN_PLATFORMIO_CORE,
        "platform": TOOLCHAIN_PLATFORM,
        "idf_version": TOOLCHAIN_IDF_VERSION,
        "esptool_version": TOOLCHAIN_ESPTOOL_VERSION,
    }
    version_doc = version_document(
        source=source, build_id=build_meta["build_id"], tag=tag, ci=ci
    )

    manifest: dict[str, Any] = {
        "schema": contract.RELEASE_SCHEMA,
        "package_format_version": contract.PACKAGE_FORMAT_VERSION,
        "product": contract.PRODUCT,
        "product_slug": contract.PRODUCT_SLUG,
        "hardware_class": contract.HARDWARE_CLASS,
        "board": contract.BOARD,
        "environment": contract.ENVIRONMENT,
        "target": contract.TARGET,
        "expected_flash_bytes": EXPECTED_FLASH_BYTES,
        "firmware_version": contract.FIRMWARE_VERSION,
        "release_channel": contract.RELEASE_CHANNEL,
        "hardware_verified": False,
        "recording_available": False,
        "device_ota_available": False,
        "source": source,
        "build_id": build_meta["build_id"],
        "tag": tag,
        "ci": ci,
        "toolchain": toolchain,
        "flash": {
            "mode": flash_layout["upload"]["flash_mode"],
            "size": flash_layout["upload"]["flash_size"],
            "freq": flash_layout["upload"]["flash_freq"],
            "size_bytes": flash_layout["flash_size_bytes"],
        },
        "images": images_manifest,
        "partition_table": {
            "file": "flash/partitions.csv",
            "sha256": sha256_bytes(csv_bytes) if csv_bytes is not None else "0" * 64,
            "size": len(csv_bytes) if csv_bytes is not None else 0,
            "entries": csv_entries,
        },
        "flash_layout_file": contract.FLASH_LAYOUT_FILE,
        "files": [],  # filled below
    }

    # Identity cross-checks run before the files list exists (files coverage is
    # validated once below after the payload bytes are known).
    errors.extend(check_version_against_manifest(version_doc, manifest))
    errors.extend(check_metadata_against_manifest(build_meta, manifest))
    if errors:
        raise ContractError(errors)

    # --- generated payload ----------------------------------------------------
    layout_text = dump_json(flash_layout)
    supplied["flash/flash-layout.json"] = layout_text.encode("utf-8")
    flash_args_lines = [
        f"--flash-mode {flash_layout['upload']['flash_mode']} "
        f"--flash-freq {flash_layout['upload']['flash_freq']} "
        f"--flash-size {flash_layout['upload']['flash_size']}"
    ]
    for seg in flash_layout["segments"]:
        flash_args_lines.append(f"0x{seg['offset']:x} {seg['file']}")
    supplied["flash/flash_args"] = (
        "\n".join(flash_args_lines) + "\n"
    ).encode("utf-8")
    supplied["VERSION.json"] = dump_json(version_doc).encode("utf-8")

    manifest_json_text = dump_json(manifest)
    manifest_bytes = manifest_json_text.encode("utf-8")

    # files[] covers every payload file except manifest.json and SHA256SUMS.
    payload = dict(image_payload)
    payload.update(supplied)
    payload[MANIFEST_FILE] = manifest_bytes
    files = sorted(
        (
            {"path": path, "size": len(data), "sha256": sha256_bytes(data)}
            for path, data in payload.items()
            if path not in contract.PACKAGE_SELF_EXCLUDED_FROM_MANIFEST
        ),
        key=lambda item: item["path"],
    )
    manifest["files"] = files
    manifest_bytes = dump_json(manifest).encode("utf-8")
    payload[MANIFEST_FILE] = manifest_bytes

    # SHA256SUMS covers the manifest and all payload files, excluding itself.
    sums_lines = []
    for path in sorted(set(payload) - {SHA256SUMS_FILE}):
        sums_lines.append(f"{sha256_bytes(payload[path])}  {path}")
    payload[SHA256SUMS_FILE] = ("\n".join(sums_lines) + "\n").encode("utf-8")

    missing = set(contract.PACKAGE_REQUIRED_FILES) - set(payload)
    extra = set(payload) - set(contract.PACKAGE_REQUIRED_FILES)
    if missing:
        errors.append(f"package: payload is missing {sorted(missing)}")
    if extra:
        errors.append(f"package: payload has unexpected files {sorted(extra)}")
    if errors:
        raise ContractError(errors)

    manifest_errors = contract.validate_manifest(json_loads_compat(manifest_bytes))
    if manifest_errors:
        raise ContractError([f"package: {e}" for e in manifest_errors])
    return payload, manifest


def json_loads_compat(data: bytes) -> Any:
    import json

    return json.loads(data.decode("utf-8"))


def write_deterministic_zip(payload: dict[str, bytes], build_id: str,
                            zip_path: Path) -> bytes:
    """Write the ZIP with one root dir, stable order, fixed metadata; return bytes."""
    root = package_root_name(build_id)
    entries: dict[str, bytes | None] = {}
    entries[f"{root}/"] = None
    for path in payload:
        parts = path.split("/")
        for index in range(1, len(parts)):
            entries[f"{root}/{'/'.join(parts[:index])}/"] = None
    for path, data in payload.items():
        entries[f"{root}/{path}"] = data

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_DATE_TIME)
            info.create_system = 0  # MS-DOS: no POSIX symlink/uid metadata at all
            data = entries[name]
            if data is None:
                info.external_attr = (DIR_MODE << 16) | 0x10
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, b"")
            else:
                info.external_attr = FILE_MODE << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)
    return zip_path.read_bytes()


def default_payload_sources(
    *,
    install_md_path: Path | None,
    release_notes_md_path: Path | None,
    license_path: Path | None,
    third_party_notices_path: Path | None,
    install_sh_path: Path | None,
    install_ps1_path: Path | None,
    requirements_lock_path: Path | None,
) -> dict[str, Path]:
    """Resolve payload source paths; round-2 replaces the placeholder wrappers."""
    return {
        "install_md_path": install_md_path or (REPO_ROOT / "docs/installation.md"),
        "release_notes_md_path": release_notes_md_path
        or (TEMPLATES_DIR / "RELEASE_NOTES.md"),
        "license_path": license_path or (REPO_ROOT / "LICENSE"),
        "third_party_notices_path": third_party_notices_path
        or (TEMPLATES_DIR / "THIRD_PARTY_NOTICES.md"),
        "install_py_path": INSTALLER_DIR / "install.py",
        "install_sh_path": install_sh_path or (INSTALLER_DIR / "install.sh"),
        "install_ps1_path": install_ps1_path or (INSTALLER_DIR / "install.ps1"),
        "requirements_lock_path": requirements_lock_path
        or (INSTALLER_DIR / "requirements-installer.lock"),
    }


def create_package(
    *,
    output_dir: Path,
    zip_name: str | None = None,
    flash_layout: dict[str, Any] | None = None,
    verify_git: bool = False,
    require_fresh_metadata: bool = True,
    skip_git_verify: bool = False,
    **sources: Any,
) -> tuple[Path, Path]:
    """Build, validate and write the ZIP + external .sha256. Returns paths."""
    payload, _manifest = build_payload(
        repo_root=REPO_ROOT if verify_git else None,
        flash_layout=flash_layout,
        require_fresh_metadata=require_fresh_metadata,
        skip_git_verify=skip_git_verify,
        **sources,
    )
    build_id = _manifest["build_id"]
    zip_path = Path(output_dir) / (zip_name or f"{package_root_name(build_id)}.zip")
    zip_bytes = write_deterministic_zip(payload, build_id, zip_path)
    digest = sha256_bytes(zip_bytes)
    sha_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, sha_path


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.package",
        description="Assemble the deterministic vdog firmware installation ZIP.",
    )
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--partition-csv", type=Path, default=DEFAULT_PARTITION_CSV)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH,
                        help="vdog-build-metadata-v1 JSON (path argument so the "
                             "ESP32 packet owns the in-tree emitter)")
    parser.add_argument("--core-header", type=Path, default=DEFAULT_CORE_HEADER)
    parser.add_argument("--install-md", type=Path, required=True)
    parser.add_argument("--release-notes-md", type=Path, required=True)
    parser.add_argument("--license", dest="license_path", type=Path, default=None)
    parser.add_argument("--third-party-notices", dest="third_party_notices_path",
                        type=Path, default=None)
    parser.add_argument("--install-sh", type=Path, default=None)
    parser.add_argument("--install-ps1", type=Path, default=None)
    parser.add_argument("--requirements-lock", type=Path, default=None)
    parser.add_argument("--release-kind", choices=("auto",) + contract.SOURCE_KINDS,
                        default="auto")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--base-sha")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--verify-git", action="store_true",
                        help="also verify local-kind builds (pr/main are verified "
                             "by default)")
    parser.add_argument("--skip-git-verify", action="store_true",
                        help="forensics only: skip the default dirty/replaced-source "
                             "check for pr/main identities; never use for releases")
    parser.add_argument("--allow-stale-metadata", action="store_true",
                        help="forensics only: skip the metadata freshness gate; "
                             "never use for release packaging")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--zip-name")
    parser.add_argument("--no-self-validate", action="store_true",
                        help="skip the post-build validate_package pass")
    args = parser.parse_args(argv)

    sources = default_payload_sources(
        install_md_path=args.install_md,
        release_notes_md_path=args.release_notes_md,
        license_path=args.license_path,
        third_party_notices_path=args.third_party_notices_path,
        install_sh_path=args.install_sh,
        install_ps1_path=args.install_ps1,
        requirements_lock_path=args.requirements_lock,
    )
    try:
        zip_path, sha_path = create_package(
            build_dir=args.build_dir,
            partition_csv=args.partition_csv,
            metadata_path=args.metadata,
            core_header_path=args.core_header,
            kind=args.release_kind,
            pr_number=args.pr_number,
            base_sha=args.base_sha,
            run_id=args.run_id,
            attempt=args.attempt,
            output_dir=args.output_dir,
            zip_name=args.zip_name,
            verify_git=args.verify_git,
            require_fresh_metadata=not args.allow_stale_metadata,
            skip_git_verify=args.skip_git_verify,
            **sources,
        )
    except ContractError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"packaged: {zip_path}")
    print(f"digest:   {sha_path}")
    if not args.no_self_validate:
        from tools.firmware.validate_package import validate_package_file

        failures = validate_package_file(zip_path)
        if failures:
            for failure in failures:
                print(f"validate: {failure}", file=sys.stderr)
            return 1
        print("validate: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
