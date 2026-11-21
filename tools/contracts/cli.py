"""Command line entry point for the contract validator.

``tools/validate_contracts.py`` is a thin shim onto :func:`main` here. The CLI
takes no arguments, opens no sockets, reads no environment variables and prints a
deterministic summary: sorted fixture lines, sorted category counts, then every
finding. Exit status is 0 when every check passes, 1 when a contract or fixture
check fails, and 2 when the validator itself broke.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Sequence

from .errors import Violation
from .validate import Report, validate_contracts

#: Marker printed first so an evidence record can be grepped for this run.
BANNER = "vdog contracts 0.6 - media and API schema/fixture validation"

_USAGE = "tools/validate_contracts.py takes no arguments"


def repository_root(argv_directory: str | None = None) -> Path:
    """Return the repository root, i.e. the directory holding ``contracts/``."""
    start = Path(argv_directory) if argv_directory is not None else Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / "contracts" / "fixtures" / "fixtures.json").is_file():
            return candidate
    raise FileNotFoundError("contracts/fixtures/fixtures.json not found from " + str(start))


def render(report: Report) -> list[str]:
    """Render the deterministic report lines (sorted, no timestamps, no paths-host)."""
    lines = [BANNER]
    versions = " | ".join(f"{name} {value}" for name, value in sorted(report.versions.items()))
    lines.append(f"toolchain: {versions}")
    lines.append(
        f"fixtures: {report.fixture_total} total "
        f"({report.media_total} media, {report.api_total} api)"
    )
    lines.append(f"contract document findings: {len(report.contract_violations)}")
    for category, count in sorted(report.categories.items()):
        lines.append(f"category {category}: {count}")
    lines.append("fixtures:")
    for result in sorted(report.results, key=lambda item: item.id):
        status = "PASS" if result.passed else "FAIL"
        detail = f"expected={result.expected}"
        if result.expected_codes:
            detail += f" expected_codes={','.join(result.expected_codes)}"
        if result.observed_codes:
            detail += f" observed_codes={','.join(result.observed_codes)}"
        lines.append(f"  {status} {result.id} [{result.kind}/{result.contract}] {detail}")
    findings = report.violations
    if findings:
        lines.append(f"findings: {len(findings)}")
        for violation in _sorted_violations(findings):
            lines.append(f"  {violation.render()}")
    else:
        lines.append("findings: 0")
    lines.append("RESULT: PASS" if report.passed else "RESULT: FAIL")
    return lines


def _sorted_violations(violations: Sequence[Violation]) -> list[Violation]:
    return sorted(violations, key=lambda item: (item.code, item.location, item.detail))


def main(argv: Sequence[str] | None = None) -> int:
    """Run every check and return the process exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        root = repository_root()
    except FileNotFoundError as error:
        print(f"contracts not found: {error}", file=sys.stderr)
        return 2
    try:
        report = validate_contracts(root)
    except Exception:  # noqa: BLE001 - an internal fault must be exit 2, not a traceback
        print("validator internal error:", file=sys.stderr)
        traceback.print_exc()
        return 2
    for line in render(report):
        print(line)
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the shim
    sys.exit(main())
