"""Make the repository root importable so ``tools.contracts`` resolves when
pytest is invoked as ``pytest tools/contracts/tests`` from the repo root."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Mapping
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
#: own code, never crash and never stay silent. ``mutation_codes`` runs them once and
#: the corpus, document and code-registry tests assert against that evidence.


def _drop_indexed_file(fixtures: Path, name: str) -> None:
    (fixtures / name).unlink()


def _write_headers(fixtures: Path, name: str, data: bytes) -> None:
    (fixtures / name).write_bytes(data)


def _write_stray_clip_file(fixtures: Path) -> None:
    (fixtures / "media" / "valid" / "baseline" / "stray.bin").write_bytes(b"not declared\n")


def _set_index_field(field: str, value: object) -> Callable[[Path], None]:
    """Change one field of one API entry so a single integrity rule has to speak."""

    def mutate(fixtures: Path) -> None:
        name = field.removeprefix("set_")
        path = fixtures / "fixtures.json"
        document = json.loads(path.read_bytes().decode("utf-8"))
        for item in document["fixtures"]:
            if item["kind"] != "api":
                continue
            if name == "status" and item["direction"] != "response":
                continue
            item[name] = value
            break
        path.write_bytes(json.dumps(document).encode("utf-8"))

    return mutate


def _set_entry_field(fixture_id: str, field: str, value: object) -> Callable[[Path], None]:
    def mutate(fixtures: Path) -> None:
        path = fixtures / "fixtures.json"
        document = json.loads(path.read_bytes().decode("utf-8"))
        for item in document["fixtures"]:
            if item["id"] == fixture_id:
                item[field] = value
                break
        else:  # pragma: no cover - the id is part of the committed corpus
            raise KeyError(fixture_id)
        path.write_bytes(json.dumps(document).encode("utf-8"))

    return mutate


def _duplicate_first_index_entry(fixtures: Path) -> None:
    path = fixtures / "fixtures.json"
    document = json.loads(path.read_bytes().decode("utf-8"))
    document["fixtures"].insert(0, dict(document["fixtures"][0]))
    path.write_bytes(json.dumps(document).encode("utf-8"))


def _corrupt_device_yaml(fixtures: Path) -> None:
    (fixtures.parent / "device-v1.yaml").write_text("openapi: [unclosed\n  broken", encoding="utf-8")


def _drop_error_schema(fixtures: Path) -> None:
    _edit_device_yaml(fixtures, lambda document: document["components"]["schemas"].pop("Error"))


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


def _device_yaml(mutate: Callable[[dict], None]) -> Callable[[Path], None]:
    return lambda fixtures: _edit_device_yaml(fixtures, mutate)


CORPUS_MUTATIONS: Final[tuple[tuple[str, str, Callable[[Path], None]], ...]] = (
    # The corpus itself: a vector, its file or its index record is wrong.
    (
        "corpus",
        "FIXTURE_FILE_MISSING",
        lambda r: (r / "media" / "valid" / "baseline" / "frames.jsonl").unlink(),
    ),
    (
        "corpus",
        "FIXTURE_FILE_MISSING",
        lambda r: _drop_indexed_file(r, "backend/invalid/clip-detail-response-missing-version.json"),
    ),
    (
        "corpus",
        "API_SCHEMA",
        lambda r: _write_headers(
            r, "backend/invalid/clips-page-request-cursor-too-long.headers.json", b"[1,2]\n"
        ),
    ),
    ("corpus", "CLIP_FILE_UNEXPECTED", _write_stray_clip_file),
    ("corpus", "FIXTURE_INDEX_INVALID", _set_index_field("set_expected", "maybe")),
    ("corpus", "API_DIRECTION_MISMATCH", _set_index_field("set_direction", "sideways")),
    ("corpus", "API_DIRECTION_MISMATCH", _set_index_field("set_contract", "device-v1")),
    ("corpus", "API_OPERATION_UNKNOWN", _set_index_field("set_operation", "device.nope")),
    ("corpus", "API_STATUS_UNDOCUMENTED", _set_index_field("set_status", 418)),
    ("corpus", "FIXTURE_DUPLICATE", _duplicate_first_index_entry),
    (
        "corpus",
        "FIXTURE_MISSING_CODE",
        _set_entry_field("media/invalid/frame-crc-mismatch", "expected_error_codes",
                         ["FRAME_SEQ_NOT_CONSECUTIVE"]),
    ),
    (
        "corpus",
        "FIXTURE_UNEXPECTED_CODE",
        _set_entry_field("media/invalid/frame-crc-mismatch", "expected_error_codes",
                         ["FRAME_SEQ_NOT_CONSECUTIVE"]),
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
    ("documents", "SCHEMA_DOCUMENT_INVALID", _drop_frame_schema),
    (
        "documents",
        "SPEC_COMPONENT_DRIFT",
        _device_yaml(lambda d: d["components"]["schemas"]["ManifestFile"]["properties"]["bytes"].__setitem__("maximum", 1024)),
    ),
    ("documents", "SPEC_SECURITY_MISSING", _device_yaml(lambda d: d["paths"]["/status"]["get"].__setitem__("security", []))),
    (
        "documents",
        "SPEC_STATUS_MISSING",
        _device_yaml(lambda d: d["paths"]["/clips/{clip_id}/files/{name}"]["get"]["responses"].pop("416")),
    ),
    (
        "documents",
        "SPEC_STATUS_UNDOCUMENTED",
        _device_yaml(lambda d: d["paths"]["/status"]["get"]["responses"].__setitem__("418", {"description": "teapot"})),
    ),
    ("documents", "OTA_SCHEMA_PRESENT", _ship_ota_schema),
    ("documents", "OTA_DEFERRAL_MISSING", _device_yaml(lambda d: d["paths"]["/ota"]["post"].pop("x-deferred"))),
)


def _report_codes(report: Report) -> set[str]:
    codes = {violation.code for violation in report.contract_violations}
    for result in report.results:
        codes |= {violation.code for violation in result.violations}
        codes |= {violation.code for violation in result.failures}
    return codes


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


@pytest.fixture(scope="session")
def mutation_codes(tmp_path_factory) -> dict[str, set[str]]:
    """Every code the broken copies of the tree actually produced, keyed by scenario."""
    observed: dict[str, set[str]] = {}
    for position, (_group, code, mutate) in enumerate(CORPUS_MUTATIONS):
        root = tmp_path_factory.mktemp(f"mutation{position}")
        shutil.copytree(CONTRACTS, root / "contracts")
        mutate(root / "contracts" / "fixtures")
        observed[f"{position}:{code}"] = _report_codes(validate_contracts(root))
    observed.update(_status_ceiling_codes(tmp_path_factory.mktemp("ceiling")))
    return observed


@pytest.fixture(scope="session")
def report() -> Report:
    """The full validation report for the committed corpus."""
    return validate_contracts(REPO_ROOT)


@pytest.fixture(scope="session")
def results_by_id(report: Report) -> dict[str, object]:
    return {result.id: result for result in report.results}
