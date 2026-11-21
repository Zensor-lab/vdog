"""Corpus-level invariants: determinism, index integrity and the report shape.

Covers plan acceptance criteria AC-01 (the run names every fixture and category),
AC-08 (nothing ships unreferenced) and AC-09 (regeneration is byte-identical).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.contracts import errors as E
from tools.contracts.errors import CODES
from tools.contracts.validate import validate_contracts

from tools.contracts.bounds import CLOSE_REASONS

from conftest import (
    CORPUS_MUTATIONS,
    FIXTURES,
    REPO_ROOT,
    TREE_LEVEL_CORPUS_CODES,
)


@pytest.mark.parametrize(
    "index,code",
    [(i, code) for i, (_group, code, _mutate) in enumerate(CORPUS_MUTATIONS) if _group == "corpus"],
    ids=[f"{code}-{i}" for i, (_group, code, _mutate) in enumerate(CORPUS_MUTATIONS) if _group == "corpus"],
)
def test_a_broken_corpus_is_named_not_crashed(index: int, code: str, mutation_codes) -> None:
    """Decision 10: a broken corpus produces its code, never an internal error."""
    assert code in mutation_codes[f"{index}:{code}"], sorted(mutation_codes[f"{index}:{code}"])


@pytest.fixture(scope="module")
def index() -> list[dict]:
    """Every committed vector, media and API alike."""
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    return list(document["fixtures"])


def test_categories_required_by_ac06_are_present(index: list[dict]) -> None:
    """Every AC-06 category appears across the whole corpus, media and API alike."""
    categories = {entry["category"] for entry in index}
    assert {
        "range",
        "lease",
        "upload",
        "time",
        "crc",
        "hash",
        "version",
        "id",
        "boundary",
        "overflow",
        "error",
        "error-envelope",
        "pagination",
        "etag",
    } <= categories, sorted({
        "range", "lease", "upload", "time", "crc", "hash", "version", "id", "boundary",
        "overflow", "error", "error-envelope", "pagination", "etag",
    } - categories)


DOCS = REPO_ROOT


@pytest.mark.parametrize(
    "index,code",
    [(i, code) for i, (group, code, _mutate) in enumerate(CORPUS_MUTATIONS) if group == "corpus"],
    ids=[f"{code}-{i}" for i, (group, code, _mutate) in enumerate(CORPUS_MUTATIONS) if group == "corpus"],
)
def test_a_corpus_scenario_code_is_attributable(index: int, code: str, mutation_evidence, clean_codes) -> None:
    """A corpus scenario must be able to point at the vector it broke.

    Tree-level findings are admitted only for the index-integrity codes listed in
    :data:`TREE_LEVEL_CORPUS_CODES`, and a code the clean tree already emits somewhere
    must appear on the damaged vector itself. Without this, a scenario could pass on
    ``GENERATOR_DRIFT`` (which any file edit produces) or on another vector's routine
    finding, which is exactly how two earlier scenarios were falsely green.
    """
    evidence = mutation_evidence[f"{index}:{code}"]
    if code in TREE_LEVEL_CORPUS_CODES:
        assert code in evidence.tree, sorted(evidence.tree)
        return
    assert code in evidence.subject, (sorted(evidence.subject), sorted(evidence.tree))
    assert code not in clean_codes or code in evidence.subject


def test_the_docs_quote_the_actual_corpus_and_suite_counts(index: list[dict]) -> None:
    """AC-11: the plan of record and the tooling docs must not carry stale arithmetic.

    The suite size is counted from the test modules themselves, so a test added without
    updating the documents fails here however the suite was invoked.
    """
    total = len(index)
    api_total = len([entry for entry in index if entry["kind"] == "api"])
    collected = _test_function_count()
    quoted = {
        "contracts/README.md": [
            f"{total} committed golden fixtures",
            f"for all {total} vectors",
            f"The suite is {collected} test functions",
            f"(`tools/contracts/errors.py`, {len(CODES)} codes)",
        ],
        "tools/README.md": [
            f"the {total} committed golden fixtures",
            f"the {len(CODES)} registered validator diagnostics",
        ],
        "docs/plans/implementation-plan.md": [
            f"{total} committed golden fixtures",
            f"{api_total} API vectors",
        ],
    }
    for path, needles in quoted.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"{path} does not quote {needle!r}"


def test_the_readme_error_envelope_is_the_published_one() -> None:
    """A consumer implementing from the README must produce a body we accept."""
    import yaml

    document = yaml.safe_load((REPO_ROOT / "contracts" / "device-v1.yaml").read_text("utf-8"))
    required = set(document["components"]["schemas"]["ErrorBody"]["required"])
    readme = (REPO_ROOT / "contracts" / "README.md").read_text(encoding="utf-8")
    line = next(line for line in readme.splitlines() if '"error":{"code"' in line)
    for key in required:
        assert f'"{key}"' in line, f"README envelope omits the required {key}"
    assert '"details"' not in line, "the published envelope has no details member"


def _property_names(node: object, found: set[str] | None = None) -> set[str]:
    """Every property name anywhere in a schema document, including its ``$defs``."""
    names: set[str] = found if found is not None else set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(str(key) for key in properties)
        for value in node.values():
            _property_names(value, names)
    elif isinstance(node, list):
        for value in node:
            _property_names(value, names)
    return names


def _test_function_count() -> int:
    """The number of ``test_*`` functions in this suite, counted from the source."""
    total = 0
    for module in sorted((REPO_ROOT / "tools" / "contracts" / "tests").glob("test_*.py")):
        total += len(re.findall(r"^def test_", module.read_text(encoding="utf-8"), re.MULTILINE))
    return total


def test_the_readme_close_reason_vocabulary_is_the_frozen_one() -> None:
    """The README may not name a close reason the contract does not define."""
    readme = (REPO_ROOT / "contracts" / "README.md").read_text(encoding="utf-8")
    manifest = json.loads(
        (REPO_ROOT / "contracts" / "media-v1" / "manifest.schema.json").read_bytes()
    )
    fields = _property_names(manifest)
    known = set(CLOSE_REASONS) | fields | {"recovered", "close_reason", "start_utc", "v"}
    offenders: set[str] = set()
    for line in readme.splitlines():
        if "close_reason" not in line and "recovered" not in line:
            continue
        for token in re.findall(r"`([a-z_]{3,32})`", line):
            if token not in known:
                offenders.add(token)
    assert not offenders, sorted(offenders)


def test_report_passes_with_no_findings(report) -> None:
    assert report.passed, [violation.render() for violation in report.violations]


def test_index_is_self_describing() -> None:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    assert document["v"] == 1
    assert document["package"] == "0.6"
    assert document["generated_by"] == "python -m tools.contracts.generate_fixtures"
    ids = [entry["id"] for entry in document["fixtures"]]
    assert ids == sorted(ids), "fixtures.json must be sorted by id so diffs stay reviewable"
    assert len(ids) == len(set(ids)), "fixture ids are unique"
    assert len(ids) > 150, "the corpus must cover both contracts broadly"


def test_every_fixture_declares_files_that_exist() -> None:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    for entry in document["fixtures"]:
        if not entry["files"]:
            # Only a bodiless 204 response may ship nothing: its whole contract is
            # the status the validator still has to find documented.
            assert entry["status"] == 204, f"{entry['id']} carries no wire file"
            continue
        for name in entry["files"]:
            relative = f"{entry['id']}/{name}" if entry["kind"] != "api" else name
            assert (FIXTURES / relative).is_file(), f"{relative} is indexed but absent"


def test_invalid_vectors_declare_codes_and_valid_vectors_do_not() -> None:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    for entry in document["fixtures"]:
        codes = entry["expected_error_codes"]
        if entry["expected"] == "valid":
            assert codes == [], f"{entry['id']} is valid but declares {codes}"
        else:
            assert codes, f"{entry['id']} is invalid but declares no code"
            for code in codes:
                assert code in E.CODES, f"{entry['id']} declares unregistered {code}"


def test_generated_corpus_is_byte_identical_to_committed(generated: dict[str, bytes]) -> None:
    """AC-09: regenerating produces exactly the committed bytes, file for file."""
    committed = {
        path.relative_to(FIXTURES).as_posix() for path in FIXTURES.rglob("*") if path.is_file()
    }
    assert set(generated) == committed
    for name, data in generated.items():
        assert (FIXTURES / name).read_bytes() == data, f"{name} differs from generator output"


def test_generator_is_reproducible_within_a_run(generated: dict[str, bytes]) -> None:
    from tools.contracts.generate_fixtures import build_all

    assert build_all() == generated


def test_regeneration_into_another_directory_matches(generated: dict[str, bytes], tmp_path: Path) -> None:
    """AC-09 as the validator enforces it: a second output dir is byte-identical."""
    from tools.contracts.generate_fixtures import write_all

    written, unchanged = write_all(tmp_path)
    assert written == len(generated) and unchanged == 0
    for name, data in generated.items():
        assert (tmp_path / name).read_bytes() == data


def test_validator_detects_a_single_corrupted_byte(tmp_path: Path) -> None:
    """AC-09: one wrong byte in a committed fixture must fail the run with a real code."""
    import shutil

    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "fixtures" / "media" / "valid" / "baseline" / "video.mjpg"
    data = bytearray(target.read_bytes())
    # Flip one entropy byte in the middle of the second frame: the frame's CRC and
    # its JPEG decode both stop matching the committed index record.
    data[600] ^= 0x01
    target.write_bytes(bytes(data))

    report = validate_contracts(tmp_path)
    assert not report.passed
    codes = {violation.code for violation in report.violations}
    assert E.GENERATOR_DRIFT in codes, "a silent byte change must be reported as generator drift"
    assert E.FRAME_CRC_MISMATCH in codes, "the corrupted frame must fail its recorded CRC"


def test_unreferenced_committed_file_is_reported(tmp_path: Path) -> None:
    import shutil

    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    (broken / "fixtures" / "media" / "valid" / "baseline" / "extra.json").write_bytes(b"{}")

    report = validate_contracts(tmp_path)
    codes = {violation.code for violation in report.violations}
    assert E.FIXTURE_UNREFERENCED in codes


def test_duplicate_index_entry_is_reported(tmp_path: Path) -> None:
    import shutil

    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    index = broken / "fixtures" / "fixtures.json"
    document = json.loads(index.read_bytes().decode("utf-8"))
    document["fixtures"].append(dict(document["fixtures"][0]))
    index.write_bytes(json.dumps(document).encode("utf-8"))

    report = validate_contracts(tmp_path)
    codes = {violation.code for violation in report.violations}
    assert E.FIXTURE_DUPLICATE in codes


def test_report_names_every_category(report) -> None:
    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    expected = {entry["category"] for entry in document["fixtures"]}
    assert set(report.categories) == expected
    assert sum(report.categories.values()) == report.fixture_total


def test_report_covers_both_contracts_and_media(report) -> None:
    assert report.media_total == sum(
        1 for result in report.results if result.kind in {"clip", "active"}
    )
    assert report.api_total == sum(1 for result in report.results if result.kind == "api")
    assert {result.contract for result in report.results} == {
        "media-v1",
        "device-v1",
        "backend-v1",
    }


def test_report_versions_record_the_qualified_toolchain(report) -> None:
    assert report.versions["python"].startswith("3.12."), report.versions
    for name in ("jsonschema", "PyYAML", "Pillow"):
        assert report.versions[name] not in {"", "missing"}, report.versions


def test_repository_root_discovery_walks_upwards() -> None:
    from tools.contracts.cli import repository_root

    assert repository_root(str(REPO_ROOT / "tools" / "contracts")) == REPO_ROOT
