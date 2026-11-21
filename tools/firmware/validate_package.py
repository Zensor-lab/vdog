"""Full validation of a vdog firmware installation ZIP (0.9.4).

Checks, from the archive alone (no source checkout or ``.pio`` directory):
ZIP/path safety, single-root §4 payload set, ``firmware-release-v1`` schema +
semantic validation, SHA-256/size coverage (manifest files, SHA256SUMS,
external ``.sha256``), flash-layout ↔ manifest ↔ partition-table agreement,
overlap and flash-bounds, image header sanity (chip ID, descriptors), OTA
data shape, identity/tag/build-ID consistency and the packaged ``install.py
check`` executed inside an isolated clean temporary directory.

Specs: docs/plans/0.9-firmware-ci-release.md sections 3-4, work package 0.9.4,
docs/plans/0.9-round1-assignment.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.firmware import contract
from tools.firmware.contract import (
    MANIFEST_FILE,
    SHA256SUMS_FILE,
    VERSION_FILE,
    ContractError,
    EXPECTED_FLASH_BYTES,
    FLASH_ARGS_FILE,
    FLASH_LAYOUT_FILE,
    PACKAGE_REQUIRED_FILES,
    PACKAGE_SELF_EXCLUDED_FROM_MANIFEST,
    PARTITION_TABLE_FILE,
    PARTITION_TABLE_MAX_BYTES,
    ROLE_BUILD_FILE,
    cross_check_partition_set,
    parse_partition_csv,
    parse_partition_table_binary,
    validate_manifest,
    validate_flash_layout,
)
from tools.firmware.metadata import check_version_against_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "firmware-release-v1.schema.json"
MAX_ZIP_ENTRY_BYTES = 64 * 1024 * 1024  # far above any legitimate payload file
INSTALL_CHECK_TIMEOUT_SECONDS = 120


class ValidationError(Exception):
    """Fatal single-error validation abort (malformed archive, unreadable zip)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_zip_name(name: str) -> str | None:
    """Return a rejection reason for a ZIP member name, or None if safe."""
    if name == "":
        return "empty member name"
    if "\\" in name:
        return f"backslash in member name {name!r}"
    if name.startswith("/"):
        return f"absolute member name {name!r}"
    if len(name) >= 2 and name[1] == ":":
        return f"drive-qualified member name {name!r}"
    parts = name.split("/")
    if any(part in ("", ".") for part in parts[:-1]) or name.endswith("/.." ):
        return f"unsafe empty/dot segment in {name!r}"
    if ".." in parts:
        return f"path escape in member name {name!r}"
    return None


def _load_json(data: bytes, *, what: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{what}: invalid JSON: {exc}") from exc


def _schema_errors(manifest: Any) -> list[str]:
    """JSON Schema pass (dev environment); skipped when jsonschema is absent."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - repo file should exist
        return [f"schema: cannot read {SCHEMA_PATH}: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(manifest), key=str):
        location = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"schema: {location}: {err.message}")
    return errors


def validate_package_bytes(
    zip_bytes: bytes,
    *,
    run_installer_check: bool = True,
    expected_zip_sha256: str | None = None,
    cwd_isolation: Path | None = None,
) -> list[str]:
    """Validate package bytes; return the complete deterministic failure list."""
    failures: list[str] = []
    if expected_zip_sha256 is not None and _sha256(zip_bytes) != expected_zip_sha256:
        failures.append(
            f"external digest: zip sha256 {_sha256(zip_bytes)} != expected "
            f"{expected_zip_sha256}"
        )
        return failures
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"archive: not a readable ZIP: {exc}"]
    with archive:
        infos = archive.infolist()
        names: list[str] = []
        for info in infos:
            reason = _reject_zip_name(info.filename)
            if reason:
                failures.append(f"archive: {reason}")
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                failures.append(f"archive: symlink member {info.filename!r}")
                continue
            if info.file_size > MAX_ZIP_ENTRY_BYTES:
                failures.append(
                    f"archive: member {info.filename!r} uncompressed size {info.file_size} "
                    f"exceeds limit {MAX_ZIP_ENTRY_BYTES}"
                )
                continue
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                failures.append(
                    f"archive: member {info.filename!r} uses unsupported compression "
                    f"{info.compress_type}"
                )
                continue
            if info.flag_bits & 0x1:
                failures.append(f"archive: member {info.filename!r} is encrypted")
                continue
            names.append(info.filename)

        # CRC integrity pass, only once no member is unsafe to read.
        if not failures:
            try:
                if archive.testzip() is not None:
                    failures.append("archive: CRC check failed on at least one member")
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                return [f"archive: cannot extract members: {exc}"]

        # --- single root directory -----------------------------------------
        root_candidates = {n.split("/", 1)[0] for n in names}
        if len(root_candidates) != 1:
            failures.append(
                f"archive: expected a single root directory, found {sorted(root_candidates)}"
            )
            return failures
        root = next(iter(root_candidates))
        if not root.startswith("vdog-xiao-sense-"):
            failures.append(f"archive: root directory {root!r} must start with 'vdog-xiao-sense-'")
            return failures
        payload: dict[str, bytes] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            if "/" not in info.filename:
                failures.append(f"archive: file outside root directory: {info.filename!r}")
                continue
            rel = info.filename.split("/", 1)[1]
            if rel == "":
                continue
            try:
                payload[rel] = archive.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                failures.append(f"archive: cannot extract {info.filename!r}: {exc}")
        if not payload:
            failures.append("archive: no payload files found")
            return failures

    # --- section 4 payload set ----------------------------------------------
    missing = sorted(set(PACKAGE_REQUIRED_FILES) - set(payload))
    extra = sorted(set(payload) - set(PACKAGE_REQUIRED_FILES))
    for name in missing:
        failures.append(f"payload: required file missing: {name}")
    for name in extra:
        failures.append(f"payload: unexpected file: {name}")

    # --- manifest ------------------------------------------------------------
    manifest: dict[str, Any] | None = None
    if MANIFEST_FILE not in payload:
        failures.append("payload: manifest.json missing")
    else:
        try:
            manifest = _load_json(payload[MANIFEST_FILE], what=MANIFEST_FILE)
        except ValidationError as exc:
            failures.append(str(exc))
    if manifest is not None:
        failures.extend(validate_manifest(manifest))
        failures.extend(_schema_errors(manifest))

    # --- SHA256SUMS -----------------------------------------------------------
    if SHA256SUMS_FILE in payload:
        try:
            sums_text = payload[SHA256SUMS_FILE].decode("utf-8")
        except UnicodeDecodeError:
            sums_text = ""
            failures.append(f"{SHA256SUMS_FILE}: not valid UTF-8")
        covered: dict[str, str] = {}
        for line_no, line in enumerate(sums_text.splitlines(), start=1):
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                failures.append(f"{SHA256SUMS_FILE}:{line_no}: malformed line {line!r}")
                continue
            digest, path = parts
            if path in covered:
                failures.append(f"{SHA256SUMS_FILE}:{line_no}: duplicate path {path!r}")
            covered[path] = digest
            errors = contract.validate_relative_package_path(
                path, where=f"{SHA256SUMS_FILE}:{line_no}"
            )
            failures.extend(errors)
        want_cover = set(payload) - {SHA256SUMS_FILE}
        for path in sorted(want_cover - set(covered)):
            failures.append(f"{SHA256SUMS_FILE}: missing coverage for {path}")
        for path in sorted(set(covered) - want_cover):
            failures.append(f"{SHA256SUMS_FILE}: covers unknown/extra path {path}")
        for path, digest in sorted(covered.items()):
            data = payload.get(path)
            if data is not None and _sha256(data) != digest:
                failures.append(
                    f"{SHA256SUMS_FILE}: {path} sha256 mismatch "
                    f"({digest} != {_sha256(data)})"
                )

    # --- manifest.files coverage ---------------------------------------------
    if manifest is not None and isinstance(manifest.get("files"), list):
        covered = {
            entry["path"]: entry
            for entry in manifest["files"]
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        want = set(PACKAGE_REQUIRED_FILES) - set(PACKAGE_SELF_EXCLUDED_FROM_MANIFEST)
        for path in sorted(want - set(covered)):
            failures.append(f"manifest.files: missing coverage for {path}")
        for path in sorted(set(covered) - want):
            failures.append(f"manifest.files: unexpected covered path {path!r}")
        for path, entry in sorted(covered.items()):
            data = payload.get(path)
            if data is None:
                continue
            if entry.get("size") != len(data):
                failures.append(
                    f"manifest.files: {path} size {entry.get('size')} != actual {len(data)}"
                )
            if entry.get("sha256") != _sha256(data):
                failures.append(f"manifest.files: {path} sha256 mismatch")

    if failures:
        # Content-level checks below depend on a sane manifest/payload set.
        return failures

    assert manifest is not None
    build_id = manifest["build_id"]
    if root != f"vdog-xiao-sense-{build_id}":
        failures.append(
            f"identity: root directory {root!r} does not match build_id {build_id!r}"
        )

    # --- images vs manifest + layout ------------------------------------------
    layout_doc: Any = None
    if FLASH_LAYOUT_FILE not in payload:
        failures.append(f"payload: {FLASH_LAYOUT_FILE} missing")
    else:
        try:
            layout_doc = _load_json(payload[FLASH_LAYOUT_FILE], what=FLASH_LAYOUT_FILE)
        except ValidationError as exc:
            failures.append(str(exc))
    layout_ok = False
    if layout_doc is not None:
        layout_errors = validate_flash_layout(layout_doc)
        failures.extend(layout_errors)
        layout_ok = not layout_errors

    def image_bytes(role: str) -> bytes | None:
        return payload.get(f"images/{ROLE_BUILD_FILE[role]}")

    manifest_images = {
        entry["role"]: entry
        for entry in manifest.get("images", [])
        if isinstance(entry, dict) and isinstance(entry.get("role"), str)
    }
    for role in contract.IMAGE_ROLES:
        entry = manifest_images.get(role)
        data = image_bytes(role)
        if data is None:
            failures.append(f"images: missing images/{ROLE_BUILD_FILE[role]}")
            continue
        if _sha256(data) != (entry or {}).get("sha256"):
            failures.append(f"images: {role} sha256 mismatch vs manifest")
        if len(data) != (entry or {}).get("size"):
            failures.append(f"images: {role} size mismatch vs manifest")
        if layout_ok:
            seg = next(
                (s for s in layout_doc["segments"] if s["role"] == role), None
            )
            if seg is None:
                failures.append(f"flash layout: missing role {role}")
                continue
            for field in ("offset", "size", "sha256", "file"):
                if entry is not None and seg[field] != entry[field]:
                    failures.append(
                        f"flash layout: {role} {field} {seg[field]!r} != manifest {entry[field]!r}"
                    )
            if _sha256(data) != seg["sha256"]:
                failures.append(f"images: {role} sha256 mismatch vs flash layout")

    # --- structural image checks (boot/app headers, ota data) -----------------
    if failures:
        return failures
    bl = image_bytes("bootloader")
    app = image_bytes("application")
    ptb = image_bytes("partition_table")
    ota = image_bytes("ota_data_initial")
    assert bl and app and ptb and ota
    try:
        contract.parse_esp_image(bl, where="images/bootloader.bin")
    except ContractError as exc:
        failures.extend(exc.errors)
    if contract.find_desc_segment(bl, kind="bootloader") is None:
        failures.append("images/bootloader.bin: no bootloader descriptor segment")
    try:
        contract.parse_esp_image(app, where="images/firmware.bin")
    except ContractError as exc:
        failures.extend(exc.errors)
    if contract.find_desc_segment(app, kind="app") is None:
        failures.append("images/firmware.bin: no app descriptor segment (wrong image?)")
    failures.extend(
        contract.validate_ota_data_initial(ota, where="images/ota_data_initial.bin")
    )

    # --- partition table: CSV <-> binary <-> layout/manifest ------------------
    csv_bytes = payload[PARTITION_TABLE_FILE]
    pt = manifest["partition_table"]
    if _sha256(csv_bytes) != pt["sha256"]:
        failures.append("partition_table: CSV sha256 mismatch vs manifest")
    if len(csv_bytes) != pt["size"]:
        failures.append(
            f"partition_table: CSV size {len(csv_bytes)} != manifest {pt['size']}"
        )
    csv_entries: list[dict[str, Any]] = []
    binary_entries = None
    try:
        csv_entries = parse_partition_csv(csv_bytes.decode("utf-8"), where=PARTITION_TABLE_FILE)
    except (ContractError, UnicodeDecodeError) as exc:
        errors = exc.errors if isinstance(exc, ContractError) else [str(exc)]
        failures.extend(f"partition_table: {e}" for e in errors)
    try:
        binary_entries = parse_partition_table_binary(
            ptb, where="images/partitions.bin",
            flash_bytes=manifest["flash"]["size_bytes"],
        )
    except ContractError as exc:
        failures.extend(exc.errors)
    if csv_entries and binary_entries is not None:
        failures.extend(
            cross_check_partition_set(csv_entries, binary_entries,
                                      where="partition table CSV vs binary")
        )
        # manifest entries must mirror the CSV rows.
        man_entries = pt.get("entries")
        if man_entries != csv_entries:
            failures.append("partition_table: manifest entries do not mirror the CSV")

        def entry(name: str) -> dict[str, Any] | None:
            return next((e for e in csv_entries if e["name"] == name), None)

        otadata = entry("otadata")
        app0 = entry("app0")
        nvs = entry("nvs")
        if otadata is None or app0 is None or nvs is None:
            failures.append("partition_table: expected nvs/otadata/app0 entries")
        else:
            want_offsets = {
                "bootloader": 0,
                "partition_table": contract.PARTITION_TABLE_OFFSET,
                "ota_data_initial": otadata["offset"],
                "application": app0["offset"],
            }
            for role, want in want_offsets.items():
                seg = manifest_images[role]
                if seg["offset"] != want:
                    failures.append(
                        f"role offsets: {role} at 0x{seg['offset']:x} but partition "
                        f"table requires 0x{want:x} (hardcoded 0x10000/0xe000 assumptions fail)"
                    )
            if len(ota) != otadata["size"]:
                failures.append(
                    f"images/ota_data_initial.bin size {len(ota)} != otadata partition "
                    f"{otadata['size']:#x}"
                )
            if len(app) > app0["size"]:
                failures.append(
                    f"images/firmware.bin size {len(app)} exceeds app0 partition "
                    f"{app0['size']:#x} (oversized image)"
                )
            if len(bl) > contract.PARTITION_TABLE_OFFSET:
                failures.append("images/bootloader.bin too large for the 0x8000 bootloader region")
            # Written ranges must not touch NVS or run past the flash.
            for role, seg in manifest_images.items():
                if seg["offset"] < nvs["offset"] + nvs["size"] and \
                        nvs["offset"] < seg["offset"] + seg["size"]:
                    failures.append(
                        f"flash bounds: {role} written range overlaps NVS partition — forbidden"
                    )
            failures.extend(
                contract.check_segment_overlaps(list(manifest_images.values()),
                                                where="manifest.images")
            )
            failures.extend(
                contract.check_segments_fit(list(manifest_images.values()),
                                            where="manifest.images",
                                            flash_bytes=manifest["flash"]["size_bytes"])
            )

    # --- flash parameters ------------------------------------------------------
    flash = manifest["flash"]
    if layout_ok:
        if (
            flash["mode"] != layout_doc["upload"]["flash_mode"]
            or flash["size"] != layout_doc["upload"]["flash_size"]
            or flash["freq"] != layout_doc["upload"]["flash_freq"]
            or flash["size_bytes"] != layout_doc["flash_size_bytes"]
        ):
            failures.append(
                f"flash: manifest {flash!r} disagrees with layout upload "
                f"{layout_doc['upload']!r}"
            )
    for field, want in (
        ("mode", contract.FLASH_MODE),
        ("size", contract.FLASH_SIZE),
        ("freq", contract.FLASH_FREQ),
        ("size_bytes", EXPECTED_FLASH_BYTES),
    ):
        if flash[field] != want:
            failures.append(f"flash: {field} {flash[field]!r} != baseline {want!r}")

    # --- flash_args text file ---------------------------------------------------
    flash_args_text = payload[FLASH_ARGS_FILE].decode("utf-8", "replace")
    lines = [ln for ln in flash_args_text.splitlines() if ln.strip()]
    if not lines:
        failures.append(f"{FLASH_ARGS_FILE}: empty")
    else:
        flag_line = lines[0]
        want_flags = (
            f"--flash-mode {flash['mode']} --flash-freq {flash['freq']} "
            f"--flash-size {flash['size']}"
        )
        if flag_line.strip() != want_flags:
            failures.append(f"{FLASH_ARGS_FILE}: flag line {flag_line!r} != {want_flags!r}")
        expect_lines = {
            f"0x{manifest_images[r]['offset']:x} images/{ROLE_BUILD_FILE[r]}"
            for r in contract.IMAGE_ROLES
        }
        got_lines = {ln.strip() for ln in lines[1:]}
        if got_lines != expect_lines:
            failures.append(
                f"{FLASH_ARGS_FILE}: entries {sorted(got_lines)} != {sorted(expect_lines)}"
            )

    # --- VERSION.json vs manifest -------------------------------------------------
    try:
        version_doc = _load_json(payload[VERSION_FILE], what=VERSION_FILE)
    except ValidationError as exc:
        failures.append(str(exc))
    else:
        failures.extend(check_version_against_manifest(version_doc, manifest))

    if failures:
        return failures

    # --- packaged install.py check in an isolated clean directory -----------------
    if run_installer_check:
        failures.extend(
            _run_packaged_installer_check(zip_bytes, cwd_isolation=cwd_isolation)
        )
    return failures


def _run_packaged_installer_check(zip_bytes: bytes, *,
                                  cwd_isolation: Path | None) -> list[str]:
    """Extract to a clean temp dir and run the ZIP's own install.py check.

    Proves the package validates offline with no source checkout and no .pio
    directory: the subprocess runs with cwd inside the temp tree.
    """
    import io
    import os

    with tempfile.TemporaryDirectory(prefix="vdog-validate-") as tmp:
        tmp_path = Path(tmp)
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for info in archive.infolist():
                reason = _reject_zip_name(info.filename)
                if reason:
                    return [f"archive: {reason}"]
                if info.is_dir():
                    continue
                rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
                if not rel:
                    continue
                target = extract_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.write_bytes(archive.read(info))
                except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                    return [f"archive: cannot extract {info.filename!r}: {exc}"]
        # Guard: no .pio and no repo markers may exist in the isolated tree.
        if any(p.name == ".pio" for p in extract_dir.rglob("*")):
            return ["installer check: unexpected .pio directory inside the package"]
        workdir = Path(cwd_isolation) if cwd_isolation else tmp_path / "cwd"
        workdir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(extract_dir / "install.py"), "check"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=INSTALL_CHECK_TIMEOUT_SECONDS,
            env=env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            tail = " | ".join(detail[-8:]) if detail else f"exit {proc.returncode}"
            return [f"install.py check failed (exit {proc.returncode}): {tail}"]
    return []


def validate_package_file(zip_path: Path, *, expected_zip_sha256: str | None = None,
                          run_installer_check: bool = True) -> list[str]:
    try:
        data = Path(zip_path).read_bytes()
    except OSError as exc:
        return [f"archive: cannot read {zip_path}: {exc}"]
    return validate_package_bytes(
        data,
        expected_zip_sha256=expected_zip_sha256,
        run_installer_check=run_installer_check,
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.validate_package",
        description="Validate a vdog firmware installation ZIP offline.",
    )
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--expected-sha256", help="expected sha256 of the ZIP itself")
    parser.add_argument("--skip-installer-check", action="store_true",
                        help="skip running the packaged install.py check")
    args = parser.parse_args(argv)
    expected = args.expected_sha256
    if expected is None:
        sidecar = Path(str(args.zip_path) + ".sha256")
        if sidecar.is_file():
            try:
                expected = sidecar.read_text(encoding="utf-8").split()[0]
            except (OSError, IndexError):
                expected = None
    failures = validate_package_file(
        args.zip_path,
        expected_zip_sha256=expected,
        run_installer_check=not args.skip_installer_check,
    )
    if failures:
        for failure in failures:
            print(f"invalid: {failure}", file=sys.stderr)
        return 1
    print("valid: package satisfies firmware-release-v1")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
