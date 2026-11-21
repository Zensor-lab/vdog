"""Structural lockfile drift checks for the CI workflows (round-2 fixes F1/F2).

The ``firmware-main.yml`` lockfile-drift step used to be inline grep/regex
code that no PR-runnable test ever executed. Both bugs shipped green:

* the component-lock grep matched legitimate DEPENDENCY-CONSTRAINT entries
  (``version: ^1.3.1``, ``'>=5.1'``, ``'>=5.0'`` under a component's own
  ``dependencies:`` list) and therefore rejected the valid committed
  ``firmware/dependencies.lock`` on every ``main`` run;
* the installer-lock parser could not handle uv's line continuations
  (``bitstring==5.0.0 \\``) and rejected the real committed lock.

This module replaces both checks with structural validation and is called
verbatim from the workflow::

    python -m tools.firmware.check_lockfiles --component-lock firmware/dependencies.lock
    python -m tools.firmware.check_lockfiles --installer-lock tools/firmware/installer/requirements-installer.lock

Rules (docs/plans/0.9-firmware-ci-release.md section 7, packet
docs/plans/0.9-review-round2-fixes.md F1/F2):

* component lock (YAML): validate ONLY the resolved ``version`` keys of the
  top-level ``dependencies:`` mapping entries — every entry needs an exact
  version (no range operators); every registry component additionally
  carries a sha256 ``component_hash`` (the ``idf`` framework entry has
  none). ``espressif/esp32-camera`` resolves to 2.1.9 and ``idf`` to 6.1.0.
  Constraint strings inside per-component ``dependencies:`` list items are
  dependency constraints, not resolved versions, and are ignored.
* installer lock (uv pip compile --generate-hashes format): every
  requirement is pinned ``name==version`` (uv ``\\`` continuation lines are
  handled), every requirement carries at least one well-formed
  ``--hash=sha256:...`` entry, and ``esptool`` is the qualified 5.4.0.

pyyaml comes from ``requirements-dev.lock`` (this is dev/CI tooling; nothing
at installer runtime parses YAML).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

# Resolved versions are dotted numerics with an optional pre-release/build
# suffix; constraint operators (^, >=, ~, >, <=, ==... ) never match.
EXACT_VERSION_RE = re.compile(r"\A[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.]+)?\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
HASH_LINE_RE = re.compile(r"\A--hash=sha256:([0-9a-f]{64})\Z")
REQUIREMENT_RE = re.compile(r"\A([A-Za-z0-9._-]+)==([^;\s]+)\Z")

# Component entries the release contract pins exactly (master plan section 7).
PINNED_COMPONENT_VERSIONS = {
    "espressif/esp32-camera": "2.1.9",
    "idf": "6.1.0",
}

EXIT_OK = 0
EXIT_LOCKFILE_INVALID = 1


def _as_mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _version_text(value: Any) -> str | None:
    """Render a YAML scalar as the version token text, or None if not numeric.

    Unquoted single-segment versions (``version: 6``, ``version: 6.1``) load
    as ``int``/``float``; they are still operator-free exact versions, so
    accept their plain textual rendering (booleans are excluded — YAML 1.1
    coerces ``yes``/``no`` to ``bool``). Multi-dot versions load as ``str``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def check_component_lock(path: Path) -> list[str]:
    """Return drift errors for an IDF component lock (empty list = OK).

    Only the resolved ``version`` keys of the top-level ``dependencies:``
    mapping are validated; per-component ``dependencies:`` list items hold
    dependency constraints (``^1.3.1`` etc.) and are never inspected.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"component lock: cannot read {path}: {exc}"]
    except yaml.YAMLError as exc:
        return [f"component lock: {path} is not valid YAML: {exc}"]
    deps = _as_mapping((data or {}).get("dependencies") if isinstance(data, dict) else None)
    if deps is None:
        return [f"component lock: {path} has no top-level 'dependencies:' mapping"]
    if not deps:
        return [f"component lock: {path} 'dependencies:' mapping is empty"]

    errors: list[str] = []
    for name, entry in deps.items():
        component = _as_mapping(entry)
        if component is None:
            errors.append(f"component lock: {name}: entry is not a mapping")
            continue
        version = component.get("version")
        version_text = _version_text(version)
        if version_text is None or not EXACT_VERSION_RE.match(version_text):
            errors.append(
                f"component lock: {name}: resolved version must be exact, got {version!r}"
            )
        source = _as_mapping(component.get("source")) or {}
        is_idf = source.get("type") == "idf"
        if not is_idf:
            component_hash = component.get("component_hash")
            if not isinstance(component_hash, str) or not SHA256_RE.match(component_hash):
                errors.append(
                    f"component lock: {name}: missing or invalid component_hash "
                    f"({component_hash!r})"
                )
    for name, want in PINNED_COMPONENT_VERSIONS.items():
        entry = _as_mapping(deps.get(name))
        if entry is None:
            errors.append(f"component lock: managed component {name} is missing")
        elif entry.get("version") != want:
            errors.append(
                f"component lock: {name} must resolve to {want!r}, got {entry.get('version')!r}"
            )
    return errors


def _strip_continuation(line: str) -> str:
    """Drop uv's trailing `` \\`` line-continuation marker."""
    return line.rstrip().removesuffix("\\").rstrip()


def check_installer_lock(path: Path) -> list[str]:
    """Return drift errors for the hashed installer lock (empty = OK)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"installer lock: cannot read {path}: {exc}"]

    errors: list[str] = []
    requirements: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = _strip_continuation(raw)
        if line.lstrip().startswith("--hash="):
            if current is None:
                errors.append(f"installer lock: hash outside a requirement: {line.strip()!r}")
                continue
            match = HASH_LINE_RE.match(line.strip())
            if match is None:
                errors.append(
                    f"installer lock: {current['name']}: malformed hash {line.strip()!r}"
                )
            else:
                current["hashes"].append(match.group(1))
            continue
        if raw[:1].isspace():
            continue  # indented metadata (e.g. "# via ..." already caught)
        if current is not None:
            requirements.append(current)
        match = REQUIREMENT_RE.match(line.strip())
        if match is None:
            errors.append(f"installer lock: unpinned requirement {line.strip()!r}")
            current = None
            continue
        current = {"name": match.group(1), "version": match.group(2), "hashes": []}
    if current is not None:
        requirements.append(current)

    if not requirements and not errors:
        errors.append("installer lock: no requirements parsed")
    for requirement in requirements:
        if not requirement["hashes"]:
            errors.append(
                f"installer lock: {requirement['name']}: no --hash=sha256 entries"
            )
    pinned = {r["name"].lower(): r["version"] for r in requirements}
    if pinned.get("esptool") != "5.4.0":
        errors.append(
            "installer lock: esptool must be the qualified 5.4.0, got "
            f"{pinned.get('esptool')!r}"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.check_lockfiles",
        description="Structurally validate the committed firmware lockfiles.",
    )
    parser.add_argument(
        "--component-lock",
        type=Path,
        default=None,
        help="path to firmware/dependencies.lock (IDF component lock)",
    )
    parser.add_argument(
        "--installer-lock",
        type=Path,
        default=None,
        help="path to tools/firmware/installer/requirements-installer.lock",
    )
    args = parser.parse_args(argv)
    if args.component_lock is None and args.installer_lock is None:
        parser.error("at least one of --component-lock / --installer-lock is required")

    failures = 0
    if args.component_lock is not None:
        errors = check_component_lock(args.component_lock)
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            failures += 1
        else:
            print(f"component lock OK: {args.component_lock}")
    if args.installer_lock is not None:
        errors = check_installer_lock(args.installer_lock)
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            failures += 1
        else:
            print(f"installer lock OK: {args.installer_lock}")
    return EXIT_LOCKFILE_INVALID if failures else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
