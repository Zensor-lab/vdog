"""Make the repository root importable so ``tools.contracts`` resolves when
pytest is invoked as ``pytest tools/contracts/tests`` from the repo root."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.contracts.generate_fixtures import build_all  # noqa: E402
from tools.contracts.validate import Report, validate_contracts  # noqa: E402

FIXTURES = REPO_ROOT / "contracts" / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def generated() -> dict[str, bytes]:
    """The corpus as the generator produces it right now (built once per session)."""
    return build_all()


def synthetic_media_entry(
    root: Path,
    name: str,
    files: dict[str, bytes],
    sparse: Mapping[str, int] | None = None,
    kind: str = "clip",
) -> dict:
    """Write an ad-hoc media vector that is too large to commit and index it.

    ``sparse`` names files that only have to be *long*: they are written as their
    committed prefix followed by a seek, so proving a megabyte bound does not have to
    fill a disk with megabytes.
    """
    relative = f"media/invalid/{name}"
    directory = root / relative
    directory.mkdir(parents=True)
    for file_name, data in files.items():
        target = directory / file_name
        total = (sparse or {}).get(file_name)
        if total is None:
            target.write_bytes(data)
            continue
        with target.open("wb") as handle:
            handle.write(data)
            handle.truncate(total)
    return {
        "id": relative,
        "kind": kind,
        "category": "boundary",
        "expected": "invalid",
        "expected_error_codes": [],
        "files": sorted(files),
        "invariant": "AC-02 size bound exercised in a temporary directory",
    }


def baseline_files() -> dict[str, bytes]:
    """The committed baseline bytes, before any synthetic bound is applied."""
    from tools.contracts.fixture_spec import media_fixtures
    from tools.contracts.generate_fixtures import build_media

    fixture = next(item for item in media_fixtures() if item.id == "media/valid/baseline")
    return dict(build_media(fixture).files())


@pytest.fixture(scope="session")
def oversized_codes(tmp_path_factory) -> set[str]:
    """Codes the size bounds produce; these vectors are megabytes and stay uncommitted."""
    from tools.contracts.bounds import CLIP_FILE_NAMES, MAX_INDEX_BYTES, MAX_PAYLOAD_BYTES
    from tools.contracts.media_validate import validate_media_fixture
    from tools.contracts.openapi_check import load_media_schemas

    schemas, violations = load_media_schemas(REPO_ROOT / "contracts" / "media-v1")
    assert not violations
    root = tmp_path_factory.mktemp("oversized") / "contracts" / "fixtures"
    payload_name, index_name = CLIP_FILE_NAMES[0], CLIP_FILE_NAMES[1]
    codes: set[str] = set()

    entry = synthetic_media_entry(
        root,
        "payload-too-large",
        baseline_files(),
        sparse={payload_name: MAX_PAYLOAD_BYTES + 1},
    )
    codes.update(violation.code for violation in validate_media_fixture(root, entry, schemas))

    index_files = baseline_files()
    first_line = index_files[index_name].split(b"\n")[0]
    index_files[index_name] = first_line[:-1] + b',"pad":"' + b"x" * MAX_INDEX_BYTES + b'"}\n'
    entry = synthetic_media_entry(root, "index-too-large", index_files)
    codes.update(violation.code for violation in validate_media_fixture(root, entry, schemas))
    return codes


#: --- Broken-copy scenarios ---------------------------------------------------
#: Each scenario is a *detection* test: the validator has to name the defect with its
#: own code, never crash and never stay silent. A mutator returns the id of the vector
#: it damaged, so the evidence is attributed to that vector instead of to "somewhere in
#: the run" — a code some unrelated negative vector already produces cannot satisfy a
#: scenario. A mutator that returns ``None`` damaged the tree as a whole (a contract
#: document, the index), and ``test_a_tree_level_scenario_code_is_never_routine`` then
#: proves the code is one the clean tree never emits.

Mutator = Callable[[Path], "str | None"]


def _drop_indexed_file(name: str, subject: str) -> Mutator:
    def mutate(fixtures: Path) -> str:
        (fixtures / name).unlink()
        return subject

    return mutate


def _drop_sidecar(name: str, subject: str) -> Mutator:
    """Delete a header sidecar the contract requires, leaving the body in place.

    The vector then claims to be conformant while omitting a header the operation
    demands, which is the case a validator must not read as "no headers to check".
    """

    def mutate(fixtures: Path) -> str:
        (fixtures / name).unlink()
        return subject

    return mutate


def _write_stray_clip_file(fixtures: Path) -> str:
    (fixtures / "media" / "valid" / "baseline" / "stray.bin").write_bytes(b"not declared\n")
    return "media/valid/baseline"


def _write_headers(fixtures: Path, name: str, data: bytes, subject: str) -> str:
    (fixtures / name).write_bytes(data)
    return subject


def _replace_file(name: str, data: bytes, subject: str) -> Mutator:
    """Overwrite one committed wire file, so a scenario can change *how many* defects
    a vector carries without changing which codes it declares."""

    def mutate(fixtures: Path) -> str:
        (fixtures / name).write_bytes(data)
        return subject

    return mutate


def _set_index_field(field: str, value: object) -> Mutator:
    """Change one field of one API entry so a single integrity rule has to speak."""

    def mutate(fixtures: Path) -> str:
        name = field.removeprefix("set_")
        path = fixtures / "fixtures.json"
        document = json.loads(path.read_bytes().decode("utf-8"))
        for item in document["fixtures"]:
            if item["kind"] != "api":
                continue
            if name == "status" and item["direction"] != "response":
                continue
            item[name] = value
            path.write_bytes(json.dumps(document).encode("utf-8"))
            return str(item["id"])
        raise AssertionError("no API vector available to mutate")  # pragma: no cover

    return mutate


def _set_entry_field(fixture_id: str, field: str, value: object) -> Mutator:
    def mutate(fixtures: Path) -> str:
        path = fixtures / "fixtures.json"
        document = json.loads(path.read_bytes().decode("utf-8"))
        for item in document["fixtures"]:
            if item["id"] == fixture_id:
                item[field] = value
                break
        else:  # pragma: no cover - the id is part of the committed corpus
            raise KeyError(fixture_id)
        path.write_bytes(json.dumps(document).encode("utf-8"))
        return fixture_id

    return mutate


def _duplicate_first_index_entry(fixtures: Path) -> str:
    path = fixtures / "fixtures.json"
    document = json.loads(path.read_bytes().decode("utf-8"))
    first = dict(document["fixtures"][0])
    document["fixtures"].insert(0, first)
    path.write_bytes(json.dumps(document).encode("utf-8"))
    return str(first["id"])


def _corrupt_device_yaml(fixtures: Path) -> None:
    (fixtures.parent / "device-v1.yaml").write_text("openapi: [unclosed\n  broken", encoding="utf-8")


def _drop_frame_schema(fixtures: Path) -> None:
    (fixtures.parent / "media-v1" / "frame-record.schema.json").write_text("{ nope", encoding="utf-8")


def _ship_ota_schema(fixtures: Path) -> None:
    (fixtures.parent / "ota-v1.json").write_text(
        '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}',
        encoding="utf-8",
    )


def _edit_device_yaml(fixtures: Path, mutate: Callable[[dict], None]) -> None:
    path = fixtures.parent / "device-v1.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _device_yaml(mutate: Callable[[dict], None]) -> Mutator:
    def run(fixtures: Path) -> None:
        _edit_device_yaml(fixtures, mutate)

    return run


def _edit_backend_yaml(fixtures: Path, mutate: Callable[[dict], None]) -> None:
    path = fixtures.parent / "backend-v1.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _backend_yaml(mutate: Callable[[dict], None]) -> Mutator:
    def run(fixtures: Path) -> None:
        _edit_backend_yaml(fixtures, mutate)

    return run


def _drop_error_schema(fixtures: Path) -> None:
    _edit_device_yaml(fixtures, lambda document: document["components"]["schemas"].pop("Error"))


CORPUS_MUTATIONS: Final[tuple[tuple[str, str, Mutator], ...]] = (
    # The corpus itself: a vector, its file or its index record is wrong.
    (
        "corpus",
        "FIXTURE_FILE_MISSING",
        _drop_indexed_file("media/valid/baseline/frames.jsonl", "media/valid/baseline"),
    ),
    (
        "corpus",
        "FIXTURE_FILE_MISSING",
        _drop_indexed_file(
            "backend/invalid/clip-detail-response-missing-version.json",
            "backend/invalid/clip-detail-response-missing-version",
        ),
    ),
    (
        "corpus",
        "API_SCHEMA",
        lambda r: _write_headers(
            r,
            "backend/invalid/clips-page-request-cursor-too-long.headers.json",
            b"[1,2]\n",
            "backend/invalid/clips-page-request-cursor-too-long",
        ),
    ),
    ("corpus", "CLIP_FILE_UNEXPECTED", _write_stray_clip_file),
    # A required header that is simply absent is a finding, not "nothing to check":
    # both the response and the request side have to say so.
    (
        "corpus",
        "HEADER_MISSING",
        _drop_sidecar(
            "backend/valid/upload-head-response-200.headers.json",
            "backend/valid/upload-head-response-200",
        ),
    ),
    (
        "corpus",
        "HEADER_MISSING",
        _drop_sidecar(
            "backend/valid/upload-patch-request-valid.headers.json",
            "backend/valid/upload-patch-request-valid",
        ),
    ),
    ("corpus", "FIXTURE_INDEX_INVALID", _set_index_field("expected", "maybe")),
    ("corpus", "API_DIRECTION_MISMATCH", _set_index_field("direction", "sideways")),
    ("corpus", "API_DIRECTION_MISMATCH", _set_index_field("contract", "device-v1")),
    ("corpus", "API_OPERATION_UNKNOWN", _set_index_field("operation", "device.nope")),
    ("corpus", "API_STATUS_UNDOCUMENTED", _set_index_field("status", 418)),
    ("corpus", "FIXTURE_DUPLICATE", _duplicate_first_index_entry),
    # Three declared findings have to be three *distinct* defects: restoring one of the
    # three absent headers leaves the code set intact and can only be caught by count.
    (
        "corpus",
        "FIXTURE_MISSING_CODE",
        _replace_file(
            "device/invalid/clip-file-response-missing-required-headers.headers.json",
            json.dumps(
                {"Content-Length": "1024", "ETag": '"' + "a" * 64 + '"'},
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n",
            "device/invalid/clip-file-response-missing-required-headers",
        ),
    ),
    (
        "corpus",
        "FIXTURE_MISSING_CODE",
        _set_entry_field(
            "media/invalid/frame-crc-mismatch", "expected_error_codes", ["FRAME_SEQ_NOT_CONSECUTIVE"]
        ),
    ),
    (
        "corpus",
        "FIXTURE_UNEXPECTED_CODE",
        _set_entry_field(
            "media/invalid/frame-crc-mismatch", "expected_error_codes", ["FRAME_SEQ_NOT_CONSECUTIVE"]
        ),
    ),
    (
        "corpus",
        "FIXTURE_EXPECTED_PASS",
        _set_entry_field("media/invalid/frame-crc-mismatch", "expected", "valid"),
    ),
    # The contract documents: unparseable, missing a piece, or claiming more than
    # interfaces.md assigns.
    ("documents", "SPEC_PARSE_FAILED", _corrupt_device_yaml),
    ("documents", "SPEC_STRUCTURE_MISSING", _drop_error_schema),
    # A required request input weakened to optional is as much a document defect as a
    # missing component: the chunk body and the checksum header are the two inputs whose
    # absence the fixture validator alone would have to refuse.
    (
        "documents",
        "SPEC_STRUCTURE_MISSING",
        _backend_yaml(
            lambda d: d["paths"]["/uploads/{id}/files/{name}"]["patch"]["requestBody"].__setitem__(
                "required", False
            )
        ),
    ),
    (
        "documents",
        "SPEC_STRUCTURE_MISSING",
        _backend_yaml(
            lambda d: d["components"]["parameters"]["UploadChecksum"].__setitem__("required", False)
        ),
    ),
    # Round 11: the three gate gaps the review reproduced — the spec-pinned query
    # dropped from a clip route, a promised response header flipped to optional, and a
    # parameter `$ref` pointing at a component the document never defines.
    (
        "documents",
        "SPEC_STRUCTURE_MISSING",
        _backend_yaml(
            lambda d: d["paths"]["/clips/{clip_id}"]["get"].__setitem__(
                "parameters",
                [
                    parameter
                    for parameter in d["paths"]["/clips/{clip_id}"]["get"]["parameters"]
                    if parameter.get("$ref") != "#/components/parameters/DeviceIdQuery"
                ],
            )
        ),
    ),
    (
        "documents",
        "SPEC_STRUCTURE_MISSING",
        _backend_yaml(
            lambda d: d["components"]["headers"]["UploadOffset"].__setitem__("required", False)
        ),
    ),
    (
        "documents",
        "SPEC_COMPONENT_DRIFT",
        _backend_yaml(
            lambda d: d["paths"]["/clips/{clip_id}/files/{name}"]["get"].__setitem__(
                "parameters",
                [
                    {"$ref": "#/components/parameters/RangeMissing"}
                    if parameter.get("$ref") == "#/components/parameters/Range"
                    else parameter
                    for parameter in d["paths"]["/clips/{clip_id}/files/{name}"]["get"]["parameters"]
                ],
            )
        ),
    ),
    ("documents", "SCHEMA_DOCUMENT_INVALID", _drop_frame_schema),
    (
        "documents",
        "SPEC_COMPONENT_DRIFT",
        _device_yaml(
            lambda d: d["components"]["schemas"]["ManifestFile"]["properties"]["bytes"].__setitem__(
                "maximum", 1024
            )
        ),
    ),
    (
        "documents",
        "SPEC_SECURITY_MISSING",
        _device_yaml(lambda d: d["paths"]["/status"]["get"].__setitem__("security", [])),
    ),
    (
        "documents",
        "SPEC_STATUS_MISSING",
        _device_yaml(lambda d: d["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"].pop("416")),
    ),
    (
        "documents",
        "SPEC_STATUS_UNDOCUMENTED",
        _device_yaml(
            lambda d: d["paths"]["/status"]["get"]["responses"].__setitem__("418", {"description": "teapot"})
        ),
    ),
    ("documents", "OTA_SCHEMA_PRESENT", _ship_ota_schema),
    (
        "documents",
        "OTA_DEFERRAL_MISSING",
        _device_yaml(lambda d: d["paths"]["/ota"]["post"].pop("x-deferred")),
    ),
)


def _report_codes(report: Report) -> set[str]:
    """Every code the run emitted, vector findings and contract findings alike."""
    codes = {violation.code for violation in report.contract_violations}
    for result in report.results:
        codes |= {violation.code for violation in result.violations}
        codes |= {violation.code for violation in result.failures}
    return codes


def _codes_by_subject(report: Report) -> dict[str | None, set[str]]:
    """Codes grouped by the vector that produced them, with ``None`` for tree findings.

    Grouping is what makes scenario evidence attributable: a code an unrelated negative
    vector emits on purpose cannot be credited to the defect a scenario introduced.
    """
    grouped: dict[str | None, set[str]] = {
        None: {violation.code for violation in report.contract_violations}
    }
    for result in report.results:
        bucket = grouped.setdefault(result.id, set())
        bucket |= {violation.code for violation in result.violations}
        bucket |= {violation.code for violation in result.failures}
    return grouped


def _status_ceiling_codes(target: Path) -> dict[str, set[str]]:
    """A status put in both the table and the document must still be refused."""
    from tools.contracts.api_model import ALL_OPERATIONS

    operation = ALL_OPERATIONS["device.get_status"]
    shutil.copytree(CONTRACTS, target / "contracts")
    path = target / "contracts" / "device-v1.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["paths"]["/status"]["get"]["responses"]["418"] = {"description": "teapot"}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    # The table and the document must say the same thing, so the scenario teaches the
    # ceiling rule a documented status. The entry is saved and restored verbatim: a
    # leaked 418 would silently change every other scenario in the session.
    assert 418 not in operation.error_codes, "418 is documented; pick an undocumented status"
    saved = dict(operation.error_codes)
    operation.error_codes[418] = ("MALFORMED_REQUEST",)
    try:
        report = validate_contracts(target)
    finally:
        operation.error_codes.clear()
        operation.error_codes.update(saved)
    assert operation.error_codes == saved
    return {f"{len(CORPUS_MUTATIONS)}:SPEC_STATUS_NOT_ALLOWED": _report_codes(report)}


#: Codes a corpus scenario may prove through a *tree-level* finding rather than one on
#: the damaged vector, because damaging ``fixtures.json`` is what those scenarios do.
#: Kept small on purpose: ``GENERATOR_DRIFT`` is emitted for any file edit, so admitting
#: it would let a corpus scenario pass on unrelated damage.
TREE_LEVEL_CORPUS_CODES: Final[frozenset[str]] = frozenset(
    {"FIXTURE_DUPLICATE", "FIXTURE_INDEX_INVALID"}
)


@dataclass(frozen=True)
class ScenarioEvidence:
    """What a broken copy produced, split by where the finding was attributed."""

    #: Codes the damaged vector itself reported: the only evidence a corpus scenario
    #: may rely on, except for the index-integrity codes in TREE_LEVEL_CORPUS_CODES.
    subject: frozenset[str]
    #: Codes the run reported against the tree as a whole (contract findings).
    tree: frozenset[str]

    # Deliberately no ``__contains__``: a union membership test would re-admit the
    # free-riding this split exists to prevent, so callers have to name the bucket.


@pytest.fixture(scope="session")
def mutation_evidence(tmp_path_factory, report: Report) -> dict[str, ScenarioEvidence]:
    """The attributed evidence behind :func:`mutation_codes`, per bucket."""
    clean = _codes_by_subject(report)
    observed: dict[str, ScenarioEvidence] = {}
    for position, (_group, code, mutate) in enumerate(CORPUS_MUTATIONS):
        root = tmp_path_factory.mktemp(f"evidence{position}")
        shutil.copytree(CONTRACTS, root / "contracts")
        subject = mutate(root / "contracts" / "fixtures")
        damaged = _codes_by_subject(validate_contracts(root))
        observed[f"{position}:{code}"] = ScenarioEvidence(
            subject=frozenset(damaged.get(subject, set()) - clean.get(subject, set())),
            tree=frozenset(damaged.get(None, set()) - clean.get(None, set())),
        )
    return observed


@pytest.fixture(scope="session")
def mutation_codes(
    mutation_evidence: dict[str, ScenarioEvidence], tmp_path_factory
) -> dict[str, set[str]]:
    """Every code the broken copies actually produced, keyed by scenario.

    Evidence is attributed: a vector scenario has to produce its code on that very
    vector, and the finding set is the *difference* from the clean tree, so an
    unrelated vector's routine finding can never stand in for the defect under test.
    """
    observed = {
        key: set(evidence.subject) | set(evidence.tree)
        for key, evidence in mutation_evidence.items()
    }
    observed.update(_status_ceiling_codes(tmp_path_factory.mktemp("ceiling")))
    return observed


@pytest.fixture(scope="session")
def clean_codes(report: Report) -> set[str]:
    """Every code the committed tree emits, expected findings on negatives included."""
    return _report_codes(report)


@pytest.fixture(scope="session")
def report() -> Report:
    """The full validation report for the committed corpus."""
    return validate_contracts(REPO_ROOT)


@pytest.fixture(scope="session")
def results_by_id(report: Report) -> dict[str, object]:
    return {result.id: result for result in report.results}
