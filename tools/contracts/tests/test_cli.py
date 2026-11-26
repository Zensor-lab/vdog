"""The CLI contract (AC-01, plan decision 10).

``tools/validate_contracts.py`` takes no arguments, prints a deterministic summary,
and exits 0 only when every check passed, 1 when a check failed and 2 when the
validator itself could not run.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.contracts import cli

from conftest import REPO_ROOT


def test_cli_exits_zero_on_the_committed_corpus(capsys) -> None:
    assert cli.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == cli.BANNER
    assert lines[-1] == "RESULT: PASS"


def test_cli_names_every_fixture_and_category(capsys) -> None:
    import json

    assert cli.main([]) == 0
    output = capsys.readouterr().out
    document = json.loads(
        (REPO_ROOT / "contracts" / "fixtures" / "fixtures.json").read_bytes().decode("utf-8")
    )
    for entry in document["fixtures"]:
        assert f" {entry['id']} " in output, entry["id"]
    for category in {entry["category"] for entry in document["fixtures"]}:
        assert f"category {category}:" in output, category


def test_cli_output_is_deterministic(capsys) -> None:
    assert cli.main([]) == 0
    first = capsys.readouterr().out
    assert cli.main([]) == 0
    assert capsys.readouterr().out == first


def test_cli_records_the_qualified_toolchain(capsys) -> None:
    assert cli.main([]) == 0
    output = capsys.readouterr().out
    for name in ("python", "jsonschema", "PyYAML", "Pillow"):
        assert f"{name} " in output, name


def test_cli_refuses_arguments(capsys) -> None:
    assert cli.main(["--help"]) == 2
    assert "no arguments" in capsys.readouterr().err


def test_cli_reports_two_when_the_corpus_is_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 2
    assert "contracts not found" in capsys.readouterr().err


def test_cli_reports_two_on_an_internal_fault(monkeypatch, capsys) -> None:
    def explode(_root: Path):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "validate_contracts", explode)
    assert cli.main([]) == 2
    assert "validator internal error" in capsys.readouterr().err


def test_cli_exits_one_when_a_check_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "fixtures" / "media" / "valid" / "clock-phone" / "manifest.json"
    target.write_bytes(target.read_bytes().replace(b'"source":"phone"', b'"source":"phones"'))

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert "CLOCK_SOURCE_UNKNOWN_VALUE" in output


def test_cli_exits_one_when_a_committed_schema_is_invalid(tmp_path: Path, monkeypatch, capsys) -> None:
    """A schema whose keyword is nonsense is a failed check, never a validator crash.

    ``check_schema`` raises ``SchemaError`` for that, which is not the ``ValidationError``
    the diagnostic path used to catch: uncaught, this same tree exits 2 with "validator
    internal error" instead of reporting the file it cannot accept.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "media-v1" / "frame-record.schema.json"
    data = target.read_text(encoding="utf-8")
    assert '"maximum": 2097152' in data, "the frame size bound is what this corrupts"
    target.write_text(data.replace('"maximum": 2097152', '"maximum": "huge"', 1), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert "SCHEMA_DOCUMENT_INVALID" in output
    assert "validator internal error" not in output


def test_cli_exits_one_when_a_committed_schema_refers_nowhere(tmp_path: Path, monkeypatch, capsys) -> None:
    """A schema whose keywords are valid but whose ``$ref`` points at nothing is exit 1 too.

    The metaschema cannot catch this: ``$ref`` is valid as a URI-reference whatever it
    points at, and the failure only surfaces when the pointer is resolved while
    validating. Without the resolution check in ``load_media_schemas`` the ``KeyError``
    escapes through ``iter_errors`` to the CLI's catch-all, which reports a validator
    internal error and exits 2 for what is a broken contract file.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "media-v1" / "manifest.schema.json"
    data = target.read_text(encoding="utf-8")
    assert '"$ref": "#/$defs/index_file_entry"' in data, "the index entry pointer is what this corrupts"
    target.write_text(
        data.replace('"$ref": "#/$defs/index_file_entry"', '"$ref": "#/$defs/index_file_entrry"', 1),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert "SCHEMA_DOCUMENT_INVALID" in output
    assert "validator internal error" not in output


@pytest.mark.parametrize("root", ["[]", "null", "true"])
@pytest.mark.parametrize(
    "file_name",
    ["frame-record.schema.json", "manifest.schema.json", "active-record.schema.json"],
    ids=["frame", "manifest", "active"],
)
def test_cli_exits_one_when_a_media_schema_root_is_not_an_object(
    tmp_path: Path, monkeypatch, capsys, file_name: str, root: str
) -> None:
    """A media schema whose root is not an object is a finding, not an `AttributeError`.

    `[]` and `true` are legal 2020-12 schemas (an array of schemas, a boolean schema),
    so the metaschema lets them through and `null` fails only the metaschema; what all
    three have in common is that the first `.get` on them raises. Uncaught, that is the
    CLI's catch-all reporting "validator internal error" and exit 2 for what is a
    broken contract file. The refusal also withholds the document, so the vectors that
    need it say so instead of pretending to have been checked.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    (broken / "media-v1" / file_name).write_text(root, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert "SCHEMA_DOCUMENT_INVALID" in output
    assert file_name in output, "the finding has to name the file it refused"
    assert "no media schema loaded" in output, "vectors must report the missing schema"
    assert "validator internal error" not in output


@pytest.mark.parametrize("root", ["[1, 2]", "true"])
def test_cli_exits_one_when_an_openapi_root_is_not_a_mapping(
    tmp_path: Path, monkeypatch, capsys, root: str
) -> None:
    """A YAML contract that parses but is not a mapping is exit 1, not a crash.

    `[1, 2]` and `true` are valid YAML, so nothing raises on load; `check_openapi` is
    the first thing to treat the result as a document and would raise on its first
    `.get`. That reaches the CLI's catch-all as exit 2 for a contract file that is
    simply not an OpenAPI document.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    (broken / "device-v1.yaml").write_text(root, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert "SPEC_PARSE_FAILED" in output
    assert "device-v1.yaml" in output, "the finding has to name the file it refused"
    assert "validator internal error" not in output


def test_cli_exits_one_on_a_dangling_download_206_ref(tmp_path: Path, monkeypatch, capsys) -> None:
    """Round 14 finding 1: a dangling download 206 is a finding, never exit 2.

    The media-type comparison followed the operation table's promised statuses
    through an unguarded response read, so pointing the committed inline 206 of
    `GET /clips/{clip_id}/files/{name}` at a nonexistent component raised
    ``KeyError`` out of the whole report and the CLI printed "validator internal
    error" with exit 2. The all-response scan already names the unreadable node;
    the CLI owes the user that finding at exit 1 instead.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "backend-v1.yaml"
    data = target.read_text(encoding="utf-8")
    start = data.index("  /clips/{clip_id}/files/{name}:\n    get:\n")
    block = "        '206':\n          description: Requested single byte range.\n"
    at = data.index(block, start)
    end = data.index("        '401':\n", at)
    target.write_text(
        data[:at]
        + "        '206':\n          $ref: '#/components/responses/NoSuchPartial'\n"
        + data[end:],
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RESULT: FAIL" in output
    assert "SPEC_COMPONENT_DRIFT" in output
    assert "GET /clips/{clip_id}/files/{name}" in output
    assert "responses/206" in output
    assert "validator internal error" not in output


def test_cli_exits_one_when_an_unbound_error_status_drops_its_error_body(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Round 15 P3-1: a description-only getClip 404 is a finding, never a pass.

    The document checker asked the schema-binding question only of the statuses
    the operation table binds a schema to, so the review's mutation — ``GET
    /clips/{clip_id}``' 404 reduced to a bare description while the fixture
    side still validates that status against the shared ``Error`` envelope —
    certified ``RESULT: PASS`` with zero findings. The envelope gate now names
    it at the status, and the CLI owes the user exit 1.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "backend-v1.yaml"
    data = target.read_text(encoding="utf-8")
    start = data.index("  /clips/{clip_id}:\n    get:\n")
    block = "        '404':\n          $ref: '#/components/responses/NotFound'\n"
    at = data.index(block, start)
    end = data.index("        '410':\n", at)
    target.write_text(
        data[:at]
        + "        '404':\n          description: Resource was never known.\n"
        + data[end:],
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RESULT: FAIL" in output
    assert "SPEC_STRUCTURE_MISSING" in output
    assert "GET /clips/{clip_id}" in output
    assert "responses/404" in output
    assert "Error envelope" in output
    assert "validator internal error" not in output


def test_cli_exits_one_on_scalar_content_in_a_listed_206(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Round 15 item 4: a scalar ``content`` earns a finding, never exit 2.

    The media-type comparison ran ``set(response.get("content", {}))`` and the
    binding read tested ``"application/json" in content`` — both raise over a
    scalar member, and the CLI called the merely-broken document a "validator
    internal error" with exit 2. The shape refusal is the honest verdict.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "backend-v1.yaml"
    data = target.read_text(encoding="utf-8")
    start = data.index("  /clips/{clip_id}/files/{name}:\n    get:\n")
    block = "        '206':\n          description: Requested single byte range.\n"
    at = data.index(block, start)
    end = data.index("        '401':\n", at)
    chunk = data[at:end]
    scalar = chunk.replace(
        "          content:\n"
        "            application/octet-stream:\n"
        "              schema:\n"
        "                type: string\n"
        "                format: binary\n",
        "          content: 5\n",
    )
    assert scalar != chunk, "the download 206 content block moved"
    target.write_text(data[:at] + scalar + data[end:], encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RESULT: FAIL" in output
    assert "SPEC_STRUCTURE_MISSING" in output
    assert "GET /clips/{clip_id}/files/{name}" in output
    assert "responses/206 content" in output
    assert "is int, not a media-type map" in output
    assert "validator internal error" not in output


def test_cli_exits_one_when_a_response_header_key_is_declared_twice(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Round 14 finding 3: a duplicate literal key dies at the parser, exit 1.

    ``yaml.safe_load`` kept only the last of the two literal ``Upload-Offset:``
    entries, so a second same-spelling entry in the upload HEAD's 200 headers
    — invisible to every check that reads a loaded mapping — certified with
    zero findings. The loader refuses the collision on the parse tree, and
    ``validate_contracts`` turns that into ``SPEC_PARSE_FAILED`` naming the
    file, never an exit-2 internal error.
    """
    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / "backend-v1.yaml"
    data = target.read_text(encoding="utf-8")
    needle = (
        "          headers:\n"
        "            Upload-Offset:\n"
        "              $ref: '#/components/headers/UploadOffset'\n"
        "            Upload-Length:\n"
    )
    duplicate = (
        "          headers:\n"
        "            Upload-Offset:\n"
        "              $ref: '#/components/headers/UploadOffset'\n"
        "            Upload-Offset:\n"
        "              $ref: '#/components/headers/UploadOffset'\n"
        "            Upload-Length:\n"
    )
    assert data.count(needle) == 1, "the headUploadFile 200 headers block moved"
    target.write_text(data.replace(needle, duplicate), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RESULT: FAIL" in output
    assert "SPEC_PARSE_FAILED" in output
    assert "backend-v1.yaml" in output
    assert "validator internal error" not in output


def test_the_documented_entry_script_runs_as_a_process() -> None:
    """The shim is what the validation ledger names, so it must work standalone."""
    completed = subprocess.run(
        [sys.executable, "tools/validate_contracts.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines()[-1] == "RESULT: PASS"


def _broken_yaml_document(tmp_path: Path, kind: str, mutate) -> Path:
    """Copy the contract tree and rewrite one OpenAPI document through ``mutate``."""
    import yaml

    from tools.contracts.schema_docs import load_yaml

    broken = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "contracts", broken)
    target = broken / f"{kind}-v1.yaml"
    document = load_yaml(target)
    mutate(document)
    target.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("kind", ["device", "backend"])
def test_cli_exits_one_when_components_is_not_a_container(
    kind: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """A declared ``components: null`` is a document failure, never exit 2.

    Every component reader did ``document.get("components", {})`` and then
    ``.get`` on the result — which is ``None.get`` for a document that
    declares the container as null, so the CLI died as "validator internal
    error" exit 2 (the round-18 deferred R1-F7). The malformed container is
    now named once at ``components`` and every reader treats it as empty, so
    the named findings it implies fire and the run reports like any other
    failed check.
    """
    root = _broken_yaml_document(tmp_path, kind, lambda document: document.__setitem__("components", None))
    monkeypatch.chdir(root)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "validator internal error" not in captured.err
    assert "RESULT: FAIL" in captured.out
    assert f"SPEC_STRUCTURE_MISSING: components: components is NoneType, not a component container" in captured.out
    # The findings an empty container implies still fire (the envelope gate
    # and the security gate read what the document no longer defines).
    assert "reusable envelope missing" in captured.out


def test_cli_exits_one_when_schemas_is_not_a_container(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Sub-containers answer the same question: unusable reads as empty.

    ``components.schemas: null`` used to explode the same way one level
    deeper. The schemas map is now read through the same guard, so the
    named "reusable envelope missing" finding appears instead of a crash.
    """

    def break_schemas(document: dict) -> None:
        document["components"]["schemas"] = None

    root = _broken_yaml_document(tmp_path, "device", break_schemas)
    monkeypatch.chdir(root)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "validator internal error" not in captured.err
    assert "RESULT: FAIL" in captured.out
    assert "reusable envelope missing" in captured.out
