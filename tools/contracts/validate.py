"""Whole-corpus validation orchestration.

One call produces the ordered report the CLI prints: contract documents first, then
the fixture index, then every fixture in sorted order, then the two reproducibility
sweeps (unreferenced files and byte-identical regeneration). Everything is offline
and deterministic: no network, no device, no clock read, no environment read.
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import errors as E
from .api_validate import validate_api_fixture
from .errors import Violation
from .generate_fixtures import build_all
from .media_validate import validate_media_fixture
from .openapi_check import (
    check_headers_contract,
    check_manifest_component,
    check_openapi,
    check_ota_deferral,
    check_shared_error_envelope,
    load_media_schemas,
)
from .schema_docs import load_json, load_yaml

#: Names the CLI reports so an evidence record can pin what ran.
DEPENDENCY_NAMES: tuple[str, ...] = ("jsonschema", "PyYAML", "Pillow")


@dataclass
class FixtureResult:
    """One fixture's verdict, in the shape the CLI and the tests consume.

    ``violations`` are the findings the validator actually observed, which is what a
    negative vector is *supposed* to produce. ``failures`` are the expected-outcome
    mismatches: empty means the vector behaved as ``fixtures.json`` declares.
    """

    id: str
    kind: str
    contract: str
    category: str
    expected: str
    expected_codes: tuple[str, ...]
    observed_codes: tuple[str, ...]
    violations: list[Violation] = field(default_factory=list)
    failures: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when the vector produced exactly the outcome the index declares."""
        return not self.failures


@dataclass
class Report:
    """Everything the validator learned about the committed contracts."""

    contract_violations: list[Violation] = field(default_factory=list)
    results: list[FixtureResult] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)
    fixture_total: int = 0
    media_total: int = 0
    api_total: int = 0
    categories: dict[str, int] = field(default_factory=dict)

    @property
    def violations(self) -> list[Violation]:
        """Every failure: contract-level findings first, then per-fixture mismatches."""
        found = list(self.contract_violations)
        for result in self.results:
            found.extend(
                Violation(
                    violation.code, f"{result.id}: {violation.location}", violation.detail
                )
                for violation in result.failures
            )
        return found

    @property
    def passed(self) -> bool:
        return not self.violations


def collect_versions() -> dict[str, str]:
    """Versions of the qualified interpreter and the four locked dev packages."""
    import sys

    versions = {"python": ".".join(str(part) for part in sys.version_info[:3])}
    for name in DEPENDENCY_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover - locked env
            versions[name] = "missing"
    return versions


def validate_contracts(repository_root: Path) -> Report:
    """Validate the committed contracts and fixtures under ``repository_root``."""
    report = Report(versions=collect_versions())
    contracts = repository_root / "contracts"
    fixtures = contracts / "fixtures"

    schemas, schema_violations = load_media_schemas(contracts / "media-v1")
    report.contract_violations.extend(schema_violations)

    documents: dict[str, Mapping[str, Any]] = {}
    for contract, file_name in (("device", "device-v1.yaml"), ("backend", "backend-v1.yaml")):
        path = contracts / file_name
        if not path.is_file():
            report.contract_violations.append(
                Violation(E.SPEC_PARSE_FAILED, str(path), "file absent")
            )
            continue
        try:
            documents[contract] = load_yaml(path)
        except Exception as error:  # noqa: BLE001 - any parse failure is one contract code
            report.contract_violations.append(
                Violation(E.SPEC_PARSE_FAILED, str(path), str(error).replace("\n", " "))
            )
            continue
        report.contract_violations.extend(check_openapi(contract, documents[contract]))
        report.contract_violations.extend(check_headers_contract(documents[contract], contract))

    if len(documents) == 2:
        report.contract_violations.extend(check_shared_error_envelope(documents))
        if "manifest" in schemas:
            report.contract_violations.extend(check_manifest_component(documents, schemas["manifest"]))
    report.contract_violations.extend(
        check_ota_deferral(documents.get("device", {}), contracts)
    )

    entries, index_violations = _load_index(fixtures)
    report.contract_violations.extend(index_violations)
    report.fixture_total = len(entries)

    for entry in entries:
        fixture_id = str(entry["id"])
        kind = str(entry["kind"])
        if kind == "api" and documents:
            violations = validate_api_fixture(fixtures, entry, documents, schemas)
        elif kind in {"clip", "active"} and {"frame", "manifest", "active"} <= set(schemas):
            violations = validate_media_fixture(fixtures, entry, schemas)
        elif kind == "api":
            violations = [Violation(E.SPEC_PARSE_FAILED, fixture_id, "no OpenAPI document loaded")]
        else:
            violations = [Violation(E.SCHEMA_DOCUMENT_INVALID, fixture_id, "no media schema loaded")]

        expected = str(entry["expected"])
        expected_codes = {str(code) for code in entry.get("expected_error_codes", [])}
        observed_codes = {violation.code for violation in violations}
        result = FixtureResult(
            id=fixture_id,
            kind=kind,
            contract=str(entry["contract"]),
            category=str(entry["category"]),
            expected=expected,
            expected_codes=tuple(sorted(expected_codes)),
            observed_codes=tuple(sorted(observed_codes)),
            violations=list(violations),
        )
        if expected == "valid":
            if not violations:
                pass  # the common case: a conformant vector that stayed conformant
            else:
                # Surface the real codes, not only the aggregate marker, in the report.
                result.failures.extend(violations)
                result.failures.append(
                    Violation(
                        E.FIXTURE_EXPECTED_PASS,
                        fixture_id,
                        "a passing test vector failed: "
                        + ", ".join(sorted(observed_codes))
                        + "; "
                        + "; ".join(violation.render() for violation in violations),
                    )
                )
        elif expected == "invalid":
            if not violations:
                result.failures.append(
                    Violation(
                        E.FIXTURE_EXPECTED_PASS,
                        fixture_id,
                        "a negative vector passed, so the validator cannot detect this defect",
                    )
                )
            else:
                missing = expected_codes - observed_codes
                extra = observed_codes - expected_codes
                if missing:
                    result.failures.append(
                        Violation(
                            E.FIXTURE_MISSING_CODE,
                            fixture_id,
                            "expected " + ", ".join(sorted(missing)),
                        )
                    )
                if extra:
                    result.failures.append(
                        Violation(
                            E.FIXTURE_UNEXPECTED_CODE,
                            fixture_id,
                            "unexpected " + ", ".join(sorted(extra)),
                        )
                    )
        else:
            # The index record was already reported malformed; a vector with no
            # declared outcome must never print PASS in an otherwise failing run.
            result.failures.append(
                Violation(
                    E.FIXTURE_INDEX_INVALID,
                    fixture_id,
                    f"expected {expected!r} is neither 'valid' nor 'invalid'",
                )
            )
        report.results.append(result)
        report.categories[result.category] = report.categories.get(result.category, 0) + 1
        if kind in {"clip", "active"}:
            report.media_total += 1
        else:
            report.api_total += 1

    report.contract_violations.extend(_check_unreferenced_files(fixtures, entries))
    report.contract_violations.extend(_check_regeneration(fixtures))
    return report


def _load_index(fixtures: Path) -> tuple[list[dict[str, Any]], list[Violation]]:
    """Read ``fixtures.json`` and reject any malformed or duplicated record."""
    path = fixtures / "fixtures.json"
    if not path.is_file():
        return [], [Violation(E.FIXTURE_INDEX_INVALID, str(path), "index absent")]
    try:
        document = load_json(path)
    except (ValueError, UnicodeDecodeError) as error:
        return [], [Violation(E.FIXTURE_INDEX_INVALID, str(path), str(error))]
    if not isinstance(document, dict) or document.get("v") != 1:
        return [], [Violation(E.FIXTURE_INDEX_INVALID, str(path), "must be an object with v: 1")]
    raw = document.get("fixtures")
    if not isinstance(raw, list):
        return [], [Violation(E.FIXTURE_INDEX_INVALID, str(path), "fixtures must be a list")]
    entries: list[dict[str, Any]] = []
    found: list[Violation] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            found.append(Violation(E.FIXTURE_INDEX_INVALID, str(path), "entry is not an object"))
            continue
        fixture_id = item.get("id")
        if not isinstance(fixture_id, str) or not fixture_id:
            found.append(Violation(E.FIXTURE_INDEX_INVALID, str(path), "entry without an id"))
            continue
        if fixture_id in seen:
            found.append(Violation(E.FIXTURE_DUPLICATE, fixture_id, "listed twice in fixtures.json"))
            continue
        seen.add(fixture_id)
        if item.get("expected") not in {"valid", "invalid"}:
            found.append(Violation(E.FIXTURE_INDEX_INVALID, fixture_id, "expected must be valid or invalid"))
        if not isinstance(item.get("files"), list):
            found.append(Violation(E.FIXTURE_INDEX_INVALID, fixture_id, "files must be a list"))
        if item.get("kind") not in {"clip", "active", "api"}:
            found.append(Violation(E.FIXTURE_INDEX_INVALID, fixture_id, f"unknown kind {item.get('kind')!r}"))
        entries.append(item)
    return entries, found


def _check_unreferenced_files(fixtures: Path, entries: list[dict[str, Any]]) -> list[Violation]:
    """AC-08: nothing may sit in the corpus without being an indexed test vector."""
    referenced = set()
    for entry in entries:
        media = entry.get("kind") in {"clip", "active"}
        for name in entry.get("files", []):
            # Media vectors index bare file names inside their own directory; API
            # vectors index the corpus-relative path of each wire file.
            referenced.add(f"{entry['id']}/{name}" if media else str(name))
    found: list[Violation] = []
    if not fixtures.is_dir():
        return [Violation(E.FIXTURE_FILE_MISSING, str(fixtures), "fixtures directory absent")]
    for path in sorted(fixtures.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(fixtures).as_posix()
        if relative == "fixtures.json":
            continue
        if relative not in referenced:
            found.append(
                Violation(
                    E.FIXTURE_UNREFERENCED,
                    relative,
                    "committed but not indexed as a test vector",
                )
            )
    return found


def _check_regeneration(fixtures: Path) -> list[Violation]:
    """AC-09: the committed bytes must equal freshly generated bytes, file for file."""
    found: list[Violation] = []
    regenerated = build_all()
    committed = {
        path.relative_to(fixtures).as_posix()
        for path in fixtures.rglob("*")
        if path.is_file()
    } if fixtures.is_dir() else set()
    for name in sorted(set(regenerated) - committed):
        found.append(Violation(E.GENERATOR_DRIFT, name, "the generator produces a file that is not committed"))
    for name in sorted(committed - set(regenerated)):
        found.append(Violation(E.GENERATOR_DRIFT, name, "committed but the generator does not produce it"))
    for name in sorted(set(regenerated) & committed):
        expected = regenerated[name]
        actual = (fixtures / name).read_bytes()
        if actual != expected:
            found.append(
                Violation(
                    E.GENERATOR_DRIFT,
                    name,
                    f"committed bytes differ from regenerated bytes ({len(actual)} vs {len(expected)})",
                )
            )
    return found
