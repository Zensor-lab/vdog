"""Normalize the pinned PlatformIO builder outputs into vdog-flash-layout-v1.

Resolves the four packaged roles (bootloader, partition_table,
ota_data_initial, application) from a normal ``pio run`` build directory and
cross-checks them against the builder-generated ``flasher_args.json``,
``flash_args`` and the partition-table CSV + binary. Missing, unknown or
conflicting outputs are hard errors: the tool never globs by basename, never
falls back to stale files and never packages a ``pio test`` runner image.

Specs: docs/plans/0.9-firmware-ci-release.md sections 2 and 4, work package
0.9.3, docs/plans/0.9-round1-assignment.md (vdog-flash-layout-v1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.firmware import contract
from tools.firmware.contract import (
    ContractError,
    EXPECTED_FLASH_BYTES,
    FLASH_LAYOUT_SCHEMA,
    IMAGE_ROLES,
    ROLE_BUILD_FILE,
    ROLE_BUILDER_TEMPLATE_FILES,
    TARGET,
    parse_partition_csv,
    parse_partition_table_binary,
    cross_check_partition_set,
)

DEFAULT_BUILD_DIR = Path("firmware/.pio/build/vdog_xiao_sense_proto")
DEFAULT_PARTITION_CSV = Path("firmware/partitions/vdog_8mb_two_ota.csv")
FLASHER_ARGS_FILE = "flasher_args.json"
FLASH_ARGS_TEXT_FILE = "flash_args"

#: Offsets that fixed assumptions would wrongly accept; the contract requires
#: derivation from the builder outputs and the partition table instead
#: (master plan 0.9.3 acceptance).
FORBIDDEN_HARDCODED_OFFSETS = {
    "application": 0x10000,
    "ota_data_initial": 0xE000,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(errors: list[str], message: str) -> None:
    errors.append(f"export_flash_layout: {message}")


def _load_flasher_args(build_dir: Path, errors: list[str]) -> dict[str, Any]:
    path = build_dir / FLASHER_ARGS_FILE
    if not path.is_file():
        _error(errors, f"missing required builder metadata {path}")
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _error(errors, f"cannot parse {path}: {exc}")
        return {}
    return doc


def _check_build_dir_root_bins(build_dir: Path, errors: list[str]) -> None:
    """The build root must hold exactly the four canonical images.

    Any additional root-level ``*.bin`` (for example a test runner left by an
    embedded ``pio test`` build) is a hard error: packaging must never pick it
    up, and its presence means the build directory state is not the clean
    normal-release build the contract assumes.
    """
    found = sorted(p.name for p in build_dir.glob("*.bin"))
    want = sorted(ROLE_BUILD_FILE.values())
    if found != want:
        extra = sorted(set(found) - set(want))
        missing = sorted(set(want) - set(found))
        _error(
            errors,
            f"build dir {build_dir} root .bin files {found} must be exactly {want}"
            + (f" (unexpected: {extra})" if extra else "")
            + (f" (missing: {missing})" if missing else ""),
        )


def _resolve_role_files(build_dir: Path, flasher: dict[str, Any],
                        errors: list[str]) -> dict[str, Path]:
    """Resolve each role to its canonical build-dir file, cross-checked.

    Reconciliation rules (never basename-globbing):
      * the canonical ``.pio`` root file for the role must exist;
      * ``flasher_args.json`` "flash_files" must contain exactly four entries;
      * each entry path's basename must match one role's known builder name
        set (IDF template paths like ``bootloader/bootloader.bin`` or
        ``vdog_firmware.bin`` are accepted for their declared role only);
      * an entry path that exists in the build dir must be byte-identical to
        the canonical file for that role;
      * an entry path that does not exist is accepted only when its basename
        belongs to the same role's builder-template set (PlatformIO
        relocation observed at the 0.2 baseline).
    """
    flash_files = flasher.get("flash_files")
    if not isinstance(flash_files, dict):
        _error(errors, "flasher_args.json: missing/invalid 'flash_files' object")
        return {}
    if len(flash_files) != 4:
        _error(
            errors,
            f"flasher_args.json flash_files must contain exactly the 4 release "
            f"images, got {len(flash_files)}: {sorted(flash_files.values())}",
        )

    # basename -> role from the fixed per-role builder name sets.
    name_to_role: dict[str, str] = {}
    for role, names in ROLE_BUILDER_TEMPLATE_FILES.items():
        for name in names:
            name_to_role[Path(name).name] = role

    resolved: dict[str, Path] = {}
    for raw_offset, raw_path in sorted(flash_files.items()):
        where = f"flasher_args.json flash_files[{raw_offset!r}]"
        if not isinstance(raw_offset, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", raw_offset):
            _error(errors, f"{where}: offset key must be 0x-hex, got {raw_offset!r}")
            continue
        if not isinstance(raw_path, str) or not raw_path:
            _error(errors, f"{where}: file must be a non-empty string, got {raw_path!r}")
            continue
        if raw_path.startswith("/") or "\\" in raw_path or ".." in Path(raw_path).parts:
            _error(errors, f"{where}: unsafe path {raw_path!r}")
            continue
        basename = Path(raw_path).name
        role = name_to_role.get(basename)
        if role is None:
            _error(
                errors,
                f"{where}: {raw_path!r} does not match any known role image "
                f"(unknown output; refusing to guess)",
            )
            continue
        if role in resolved:
            _error(errors, f"{where}: duplicate {role!r} output {raw_path!r}")
            continue
        canonical = build_dir / ROLE_BUILD_FILE[role]
        if not canonical.is_file():
            _error(
                errors,
                f"{where}: canonical builder output {canonical} for role {role!r} "
                f"is missing (stale or partial build?)",
            )
            continue
        listed = build_dir / raw_path
        if listed.exists():
            if listed.resolve() != canonical.resolve() and (
                sha256_file(listed) != sha256_file(canonical)
            ):
                _error(
                    errors,
                    f"{where}: listed path {raw_path!r} conflicts with canonical "
                    f"{ROLE_BUILD_FILE[role]} (different bytes)",
                )
                continue
        else:
            if raw_path not in ROLE_BUILDER_TEMPLATE_FILES[role]:
                _error(
                    errors,
                    f"{where}: path {raw_path!r} does not exist and is not a known "
                    f"builder-template alias for role {role!r}",
                )
                continue
        resolved[role] = canonical
    missing = set(IMAGE_ROLES) - set(resolved)
    if missing:
        _error(errors, f"flasher_args.json is missing role outputs {sorted(missing)}")
    return resolved


def _check_flash_args_text(build_dir: Path, flasher: dict[str, Any],
                           errors: list[str]) -> dict[str, str]:
    """Validate the generated ``flash_args`` text against flasher_args.json."""
    path = build_dir / FLASH_ARGS_TEXT_FILE
    if not path.is_file():
        _error(errors, f"missing required builder metadata {path}")
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _error(errors, f"cannot read {path}: {exc}")
        return {}
    mapping: dict[str, str] = {}
    if not lines:
        _error(errors, f"{path}: empty")
        return mapping
    first = lines[0].strip()
    match = re.fullmatch(
        r"--flash-mode (\S+) --flash-freq (\S+) --flash-size (\S+)", first
    )
    if not match:
        _error(
            errors,
            f"{path}: first line must be the esptool flash flags line, got {first!r}",
        )
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"0x[0-9a-fA-F]+", parts[0]):
            _error(errors, f"{path}: bad entry line {line!r}")
            continue
        offset_key = hex(int(parts[0], 16))
        mapping[offset_key] = parts[1]
    return mapping


def _canonical_offset_keys(flasher: dict[str, Any], errors: list[str]) -> dict[str, int]:
    """Normalize flash_files offsets to canonical lowercase hex ints keyed by role."""
    flash_files = flasher.get("flash_files") or {}
    out: dict[str, int] = {}
    name_to_role: dict[str, str] = {}
    for role, names in ROLE_BUILDER_TEMPLATE_FILES.items():
        for name in names:
            name_to_role[Path(name).name] = role
    for raw_offset, raw_path in flash_files.items():
        role = name_to_role.get(Path(str(raw_path)).name)
        if role is None:
            continue
        try:
            out[role] = int(str(raw_offset), 16)
        except ValueError:
            _error(errors, f"flasher_args.json: unparseable offset {raw_offset!r}")
    return out


def export_flash_layout(
    build_dir: Path,
    partition_csv: Path,
    *,
    flash_size_bytes: int = EXPECTED_FLASH_BYTES,
) -> dict[str, Any]:
    """Build the vdog-flash-layout-v1 document; raise ContractError on any issue."""
    errors: list[str] = []
    build_dir = Path(build_dir)
    partition_csv = Path(partition_csv)
    if not build_dir.is_dir():
        raise ContractError([f"export_flash_layout: build dir {build_dir} is not a directory"])

    _check_build_dir_root_bins(build_dir, errors)
    flasher = _load_flasher_args(build_dir, errors)
    role_files = _resolve_role_files(build_dir, flasher, errors) if flasher else {}
    flash_args_map = _check_flash_args_text(build_dir, flasher, errors) if flasher else {}
    if errors:
        raise ContractError(errors)

    # --- upload parameters from the builder --------------------------------
    settings = flasher.get("flash_settings")
    if not isinstance(settings, dict):
        raise ContractError(["export_flash_layout: flasher_args.json missing 'flash_settings'"])
    upload = {
        "flash_mode": str(settings.get("flash_mode", "")).lower(),
        "flash_size": str(settings.get("flash_size", "")),
        "flash_freq": str(settings.get("flash_freq", "")).lower(),
    }
    for field, allowed in (
        ("flash_mode", contract.FLASH_MODES),
        ("flash_size", contract.FLASH_SIZES),
        ("flash_freq", contract.FLASH_FREQS),
    ):
        if upload[field] not in allowed:
            _error(errors, f"flasher_args.json flash_settings.{field} invalid: {upload[field]!r}")
    if upload["flash_size"] != f"{flash_size_bytes // (1024 * 1024)}MB":
        _error(
            errors,
            f"flasher_args.json flash_size {upload['flash_size']!r} inconsistent with "
            f"expected flash size {flash_size_bytes}",
        )
    extra = flasher.get("extra_esptool_args") or {}
    if str(extra.get("chip", TARGET)) != TARGET:
        _error(errors, f"flasher_args.json extra_esptool_args.chip {extra.get('chip')!r} != {TARGET!r}")

    # --- cross-check the flash_args text file against flasher_args.json ----
    flash_files = flasher.get("flash_files") or {}
    expected_text = {
        hex(int(str(off), 16)): str(pth) for off, pth in flash_files.items()
    }
    normalized_expected = {off: Path(pth).name for off, pth in expected_text.items()}
    normalized_got = {off: Path(pth).name for off, pth in flash_args_map.items()}
    if normalized_got != normalized_expected:
        _error(
            errors,
            f"flash_args entries {sorted(normalized_got.items())} conflict with "
            f"flasher_args.json {sorted(normalized_expected.items())}",
        )
    if errors:
        raise ContractError(errors)

    # --- partition table: CSV, binary and derived role offsets -------------
    try:
        csv_text = partition_csv.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError([f"export_flash_layout: cannot read {partition_csv}: {exc}"]) from exc
    csv_entries = parse_partition_csv(csv_text, where=str(partition_csv))
    partitions_bin = build_dir / ROLE_BUILD_FILE["partition_table"]
    try:
        binary_entries = parse_partition_table_binary(
            partitions_bin.read_bytes(), where=str(partitions_bin),
            flash_bytes=flash_size_bytes,
        )
    except ContractError as exc:
        raise ContractError(list(exc.errors)) from None
    errors.extend(
        cross_check_partition_set(csv_entries, binary_entries, where=str(partitions_bin))
    )

    def find_entry(*, name: str | None = None, type_: int | None = None,
                   subtype: int | None = None) -> contract.PartitionEntry | None:
        for entry in binary_entries:
            if name is not None and entry.name != name:
                continue
            if type_ is not None and entry.type != type_:
                continue
            if subtype is not None and entry.subtype != subtype:
                continue
            return entry
        return None

    otadata = find_entry(name="otadata")
    app0 = find_entry(name="app0") or find_entry(type_=0, subtype=0x10)
    if otadata is None:
        _error(errors, "partition table has no 'otadata' entry")
    if app0 is None:
        _error(errors, "partition table has no first OTA application entry ('app0')")
    if errors:
        raise ContractError(errors)
    assert otadata is not None and app0 is not None

    offsets = _canonical_offset_keys(flasher, errors)
    want_offsets = {
        "bootloader": 0,
        "partition_table": contract.PARTITION_TABLE_OFFSET,
        "ota_data_initial": otadata.offset,
        "application": app0.offset,
    }
    for role, want in want_offsets.items():
        got = offsets.get(role)
        if got != want:
            _error(
                errors,
                f"flasher_args.json offset for {role!r} is {got!r}, but the partition "
                f"table/contract requires {want:#x} (hardcoded offset assumptions such "
                f"as 0x10000 app or 0xe000 otadata are rejected)",
            )
    for role, forbidden in FORBIDDEN_HARDCODED_OFFSETS.items():
        if offsets.get(role) == forbidden and offsets.get(role) != want_offsets[role]:
            _error(
                errors,
                f"{role} offset {forbidden:#x} matches a forbidden hardcoded assumption",
            )

    # Image/role sanity against partitions.
    sizes: dict[str, int] = {}
    digests: dict[str, str] = {}
    for role in IMAGE_ROLES:
        path = role_files[role]
        data = path.read_bytes()
        sizes[role] = len(data)
        digests[role] = hashlib.sha256(data).hexdigest()
        if role == "bootloader":
            if len(data) > contract.PARTITION_TABLE_OFFSET:
                _error(errors, f"bootloader.bin ({len(data)} B) leaves no room for the table at 0x8000")
            contract.parse_esp_image(data, where="bootloader.bin")
            if contract.find_desc_segment(data, kind="bootloader") is None:
                _error(errors, "bootloader.bin has no bootloader descriptor segment")
        elif role == "partition_table":
            pass  # already parsed above
        elif role == "ota_data_initial":
            if len(data) != otadata.size:
                _error(errors, f"ota_data_initial.bin size {len(data)} != otadata partition {otadata.size:#x}")
            errors.extend(f"export_flash_layout: {e}" for e in
                          contract.validate_ota_data_initial(data, where="ota_data_initial.bin"))
        elif role == "application":
            if len(data) > app0.size:
                _error(
                    errors,
                    f"firmware.bin ({len(data)} B) exceeds app0 partition size "
                    f"{app0.size:#x} — oversized application image",
                )
            contract.parse_esp_image(data, where="firmware.bin")
            if contract.find_desc_segment(data, kind="app") is None:
                _error(errors, "firmware.bin has no app descriptor (not a normal application image?)")
    if errors:
        raise ContractError(errors)

    layout = {
        "schema": FLASH_LAYOUT_SCHEMA,
        "target": TARGET,
        "flash_size_bytes": flash_size_bytes,
        "upload": upload,
        "segments": [
            {
                "role": role,
                "file": f"images/{ROLE_BUILD_FILE[role]}",
                "offset": want_offsets[role],
                "size": sizes[role],
                "sha256": digests[role],
            }
            for role in IMAGE_ROLES
        ],
    }
    layout_errors = contract.validate_flash_layout(layout)
    if layout_errors:
        raise ContractError(layout_errors)
    return layout


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.export_flash_layout",
        description="Export vdog-flash-layout-v1 from a PlatformIO build directory.",
    )
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--partition-csv", type=Path, default=DEFAULT_PARTITION_CSV)
    parser.add_argument("--flash-size-bytes", type=int, default=EXPECTED_FLASH_BYTES)
    parser.add_argument("--output", type=Path,
                        help="write the layout JSON here (default: stdout)")
    args = parser.parse_args(argv)
    try:
        layout = export_flash_layout(
            args.build_dir, args.partition_csv,
            flash_size_bytes=args.flash_size_bytes,
        )
    except ContractError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    text = json.dumps(layout, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
