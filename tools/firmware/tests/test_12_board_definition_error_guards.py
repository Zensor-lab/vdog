"""Package 1.2 A7: macro-rename residual closed with a host-visible probe.

The two component definitions ``VDOG_BOARD_ID_STR`` and
``VDOG_BOARD_PSRAM_SIZE_BYTES`` reach
``firmware/components/vdog_board/vdog_board_idf.c`` as PRIVATE
``target_compile_definitions``; ``scripts/check_board_config.py`` checks
their TEXT, but a text check cannot prove the COMPILER receives them
(PRIVATE->INTERFACE silently drops them while every literal stays intact).
``vdog_board_idf.c`` therefore refuses to compile without them (``#error``
guards, PR-R9). This module pins that compile-loud behaviour:

1. TEXT layer (always runs): both ``#if !defined(...)`` / ``#error`` guards
   exist in the adapter — the guards themselves cannot be silently removed.
2. COMPILE probe (needs a built tree): takes the REAL compile command from
   ``compile_commands.json``, drops the two ``-D VDOG_BOARD_*`` flags (the
   stand-in for a deleted definition or a macro RENAME: the TU no longer
   receives them) and asserts the compile aborts; then re-adds the flags
   and asserts the compile passes. This is the m2 proof from the PR-5
   review re-homed out-of-tree per plan A7/F7(b).
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRMWARE = REPO_ROOT / "firmware"
ADAPTER = FIRMWARE / "components/vdog_board/vdog_board_idf.c"
BUILD_DIR = FIRMWARE / ".pio/build/vdog_xiao_sense_proto"
COMPILE_DB = BUILD_DIR / "compile_commands.json"
TARGET = "components/vdog_board/vdog_board_idf.c"
FLAGS = ['-DVDOG_BOARD_ID_STR="seeed_xiao_esp32s3"',
         "-DVDOG_BOARD_PSRAM_SIZE_BYTES=8388608u"]
MACROS = ("VDOG_BOARD_ID_STR", "VDOG_BOARD_PSRAM_SIZE_BYTES")


def test_error_guards_present_in_the_adapter():
    """Layer 1: the #error guards exist (rename/delete probe prerequisite)."""
    text = ADAPTER.read_text(encoding="utf-8")
    for macro in MACROS:
        assert f"#if !defined({macro})" in text, (
            f"{macro} definedness guard missing from {ADAPTER}")
        assert f'#error "vdog_board_idf.c requires {macro}' in text, (
            f"#error naming {macro} missing from {ADAPTER}")


def test_component_still_ships_the_definitions():
    """The PRIVATE target_compile_definitions block still states both."""
    cmake = (FIRMWARE / "components/vdog_board/CMakeLists.txt").read_text(
        encoding="utf-8")
    assert "${COMPONENT_LIB} PRIVATE" in cmake
    for macro in MACROS:
        assert macro in cmake


@pytest.mark.skipif(
    not COMPILE_DB.exists(),
    reason="compile_commands.json missing — run `pio run -d firmware -e "
           "vdog_xiao_sense_proto` first (out-of-tree evidence dependency)")
def test_compile_probe_missing_definitions_trips_the_error_guards():
    """Layer 2 (m2, re-homed): without the -D flags the guards must abort;
    with them the TU must compile (same flags the green build used)."""
    entry = None
    for item in json.loads(COMPILE_DB.read_text(encoding="utf-8")):
        if item.get("file", "").endswith(TARGET):
            entry = item
            break
    assert entry is not None, f"no compile_commands.json entry for {TARGET}"

    argv = shlex.split(entry.get("command") or " ".join(entry["arguments"]))
    cwd = entry.get("directory", str(BUILD_DIR))
    # -fsyntax-only: no objects written; keep the source (drop -c/-o pairs).
    argv = [a for a in argv if a != "-c"]
    while "-o" in argv:
        index = argv.index("-o")
        del argv[index:index + 2]
    argv.append("-fsyntax-only")
    base = [a for a in argv if not a.startswith("-DVDOG_BOARD_ID_STR")
            and not a.startswith("-DVDOG_BOARD_PSRAM_SIZE_BYTES")]

    without = subprocess.run(base, cwd=cwd, capture_output=True, text=True)
    assert without.returncode != 0, (
        "#error guards did not fire when the definitions were removed")
    assert any("error" in line.lower()
               for line in (without.stderr + without.stdout).splitlines())

    with_flags = subprocess.run(base + FLAGS, cwd=cwd,
                                capture_output=True, text=True)
    assert with_flags.returncode == 0, (
        "shipped PRIVATE definitions no longer compile cleanly:\n"
        + with_flags.stderr)
