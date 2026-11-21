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
