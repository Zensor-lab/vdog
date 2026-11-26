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


def test_a_derivative_certifies_the_clip_it_cites(index: list[dict]) -> None:
    """The two halves of the corpus have to agree about which clip a derivative came from.

    A ``DerivativeRecord`` names a ``(device_id, clip_id)`` pair *and* quotes the digests
    of the files it was cut from, and no validator compares those two statements: the
    crop bound resolves through the pair alone. A vector could therefore argue about one
    segment in its invariant while certifying another, and the argument would still be
    green. So every quoted digest has to be a digest the cited segment's own committed
    ``checksums.json`` certifies (AC-05, AC-06) — spelled exactly for a vector the index
    expects to be valid, and up to notation for a refused one, because an invalid record
    is allowed to get the spelling wrong (``derivative-response-200-bad-hash`` is refused
    for exactly that) while no record at all may quote a different clip's bytes. The key
    is the pair, because ``clip_id`` is scoped by ``device_id`` and the corpus commits one
    id on two devices at two different profile sizes.
    """
    certified: dict[tuple[str, str], dict[str, str]] = {}
    for entry in index:
        if entry["kind"] != "clip" or str(entry.get("expected")) != "valid":
            continue
        directory = FIXTURES / str(entry["id"])
        manifest, sidecar = directory / "manifest.json", directory / "checksums.json"
        if not manifest.is_file() or not sidecar.is_file():
            continue
        document = json.loads(manifest.read_bytes().decode("utf-8"))
        clip_id, device_id = document.get("clip_id"), document.get("device_id")
        files = json.loads(sidecar.read_bytes().decode("utf-8"))["files"]
        certified[(device_id, clip_id)] = {
            str(name): str(claim["sha256"]) for name, claim in files.items()
        }

    seen = 0
    for entry in index:
        if entry["kind"] != "api":
            continue
        path = FIXTURES / f"{entry['id']}.json"
        if not path.is_file():
            continue
        body = json.loads(path.read_bytes().decode("utf-8"))
        if not isinstance(body, dict) or not isinstance(body.get("original_hashes"), dict):
            continue
        seen += 1
        pair = (body.get("device_id"), body.get("clip_id"))
        assert pair in certified, (entry["id"], pair)
        exact = str(entry.get("expected")) == "valid"
        for name, digest in body["original_hashes"].items():
            assert name in certified[pair], (entry["id"], name)
            claimed = certified[pair][name]
            if exact:
                assert digest == claimed, (entry["id"], pair, name, digest)
            else:
                # A refused record may be refused *for* its spelling (that is one committed
                # vector's whole subject), but it may not quietly quote another clip.
                assert digest.lower() == claimed, (entry["id"], pair, name, digest)
    assert seen >= 5, seen  # the derivative records really are the ones being checked


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
        # Even here the code has to be one the clean tree never emits, so the
        # allow-list cannot hide a finding that any healthy vector already reports.
        assert code not in clean_codes or code in evidence.subject
        return
    assert code in evidence.subject, (sorted(evidence.subject), sorted(evidence.tree))


def test_the_tree_level_allow_list_is_still_earned(mutation_evidence) -> None:
    """Every admitted tree-level code must still be claimed by a corpus scenario.

    An allow-list nobody uses is a way to hide a future scenario's unattributed
    finding, so it may not outlive the scenarios that justified it.
    """
    claimed = {
        code
        for position, (group, code, _mutate) in enumerate(CORPUS_MUTATIONS)
        if group == "corpus" and f"{position}:{code}" in mutation_evidence
        and code in mutation_evidence[f"{position}:{code}"].tree
    }
    assert claimed == set(TREE_LEVEL_CORPUS_CODES), (
        sorted(TREE_LEVEL_CORPUS_CODES - claimed),
        sorted(claimed - TREE_LEVEL_CORPUS_CODES),
    )


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
    from tools.contracts.api_model import ALL_OPERATIONS

    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    for entry in document["fixtures"]:
        if not entry["files"]:
            # Only a response RFC 9110 leaves without content may ship nothing: a 204
            # (§15.3.3) states its result without a body and a HEAD (§9.3.2) answers with
            # status and headers alone. For those the absence *is* the vector; anything
            # else that ships no wire file is an index that lost a file.
            assert entry["kind"] == "api", f"{entry['id']} carries no wire file"
            bodiless = entry["status"] == 204 or ALL_OPERATIONS[entry["operation"]].is_head
            assert bodiless, f"{entry['id']} carries no wire file"
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


def test_a_ref_sibling_bound_fails_the_corpus_run(tmp_path: Path) -> None:
    """A sibling assertion the resolution path dropped kept the corpus green (round 17 F2).

    The review's mutation — ``maxLength: 1`` beside the ``setup_secret`` ``$ref``
    in ``PairRequest`` — is enforced by a standard Draft 2020-12 validator. The
    published-schema path must agree: on a temporary copy the committed 43-char
    secrets stop passing, the untouched copy stays 441 fixtures and PASS, and
    the refusal is named where a maintainer reads it.
    """
    import shutil

    import yaml

    clean = tmp_path / "clean"
    shutil.copytree(REPO_ROOT / "contracts", clean / "contracts")
    baseline = validate_contracts(clean)
    assert baseline.passed and baseline.fixture_total == 441, (
        baseline.fixture_total,
        [violation.render() for violation in baseline.violations],
    )

    broken = tmp_path / "broken"
    shutil.copytree(REPO_ROOT / "contracts", broken / "contracts")
    path = broken / "contracts" / "device-v1.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["components"]["schemas"]["PairRequest"]["properties"]["setup_secret"][
        "maxLength"
    ] = 1
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report = validate_contracts(broken)
    assert not report.passed
    assert report.violations, "the corpus must refuse the bound-violating pair bodies"
    named = [
        violation
        for violation in report.violations
        if violation.code == E.API_SCHEMA
        and violation.location.endswith(" at setup_secret")
        and "too long" in violation.detail
    ]
    assert named, [violation.render() for violation in report.violations]


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
