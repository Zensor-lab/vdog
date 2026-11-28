"""Package 1.2 A7/F7(b): the 1.1 §12 gate scenario drivers, re-homed (out-of-
tree drivers -> this committed pytest module; NEW file, no pre-existing
``tools/firmware/**`` file edited — the 0.9 branches own those).

This is the 45-case parser-fidelity regression surface for the two firmware
build gates (``firmware/scripts/check_board_config.py`` and
``firmware/scripts/check_core_purity.py``): tampered COPIES of
``sdkconfig.defaults`` / the component ``CMakeLists.txt`` /
``platformio.ini`` / poisoned core files are run against the gates via the
documented CLI override flags (board cases) or an in-process SCons stub
(purity cases), so the repository files are never touched. Every expected
exit code matches the round-9-corrected harness from package 1.1
(docs/plans/1.1-assignment.md §12; docs/toolchain.md round-9 block) —
including the PR-R13/R14/R15 classes (``# default:`` marker persistence,
deprecated-banner skipping, universal-newline line model, CMake lexer
terminators) and the PR-R7/R10 basename-anchored FatFs header classes.

F6 (1.1 §12 carry-over, documented intentional variant): unlike
``gen_build_meta.py`` (module-level ``Import("env")``), both gate scripts
call ``Import("env")`` INSIDE their ``_scons_main()``. That is intentional
— the scripts double as standalone CLI tools and must not perform SCons
Import at import time — and behavioural parity with the module-level form
is proven here: the purity driver injects a stub through the SAME
``Import`` name the scripts use, exactly as SCons does at parse time.

The board-config scenarios need the resolved build configuration
(``.pio/build/.../sdkconfig.json``); when it is absent (e.g. a fresh clone
without a firmware build) those cases skip rather than false-fail.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRMWARE = REPO_ROOT / "firmware"
GATE = FIRMWARE / "scripts" / "check_board_config.py"
PURITY = FIRMWARE / "scripts" / "check_core_purity.py"
REAL_SDKCONFIG = (FIRMWARE / ".pio/build/vdog_xiao_sense_proto/config"
                  / "sdkconfig.json")
REAL_DEFAULTS = FIRMWARE / "sdkconfig.defaults"
REAL_CMAKE = FIRMWARE / "components/vdog_board/CMakeLists.txt"
REAL_INI = FIRMWARE / "platformio.ini"
CORE = FIRMWARE / "core"

KEY_LINE = "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y"
DEP_BEGIN = "# Deprecated options for backward compatibility"
DEP_END = "# End of deprecated options"
GOOD_BLOCK = ('target_compile_definitions(${COMPONENT_LIB} PRIVATE\n'
              '    VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"\n'
              '    VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)')
SEPS = [("U2028", "\u2028"), ("U2029", "\u2029"), ("VT", "\x0b"),
        ("FF", "\x0c"), ("NEL", "\x85")]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_gate(tmp_path: Path, **overrides: object) -> int:
    """Run check_board_config.py against the given inputs; return exit code."""
    argv = [sys.executable, str(GATE), "--sdkconfig",
            str(overrides.pop("_sdkconfig")),
            "--board", str(overrides.pop("_board", "seeed_xiao_esp32s3"))]
    for flag, path in overrides.items():
        argv += ["--" + flag.lstrip("_").replace("_", "-"), str(path)]
    return subprocess.run(argv, capture_output=True, text=True).returncode


def write_defaults(tmp_path: Path, mutate) -> Path:
    path = tmp_path / "sdkconfig.defaults"
    path.write_text(mutate(read(REAL_DEFAULTS)), encoding="utf-8")
    return path


def write_cmake(tmp_path: Path, mutate) -> Path:
    path = tmp_path / "CMakeLists.txt"
    path.write_text(mutate(read(REAL_CMAKE)), encoding="utf-8")
    return path


def write_ini(tmp_path: Path, mutate) -> Path:
    path = tmp_path / "platformio.ini"
    path.write_text(mutate(read(REAL_INI)), encoding="utf-8")
    return path


def base_removed(text: str) -> str:
    """REAL_DEFAULTS with the KEY_LINE removed (banner fixtures re-add it)."""
    assert KEY_LINE + "\n" in text
    return text.replace(KEY_LINE + "\n", "")


# ---------------------------------------------------------------------------
# Board-config gate scenarios (tampered copies; expected exit codes per 1.1
# §12 round-9 corrections — do not "fix" an expectation without re-deriving
# it from the parser truth cited in docs/toolchain.md).
# ---------------------------------------------------------------------------

GATE_SCENARIOS = [
    # id, expected exit, builder(tmp) -> run_gate kwargs
    ("a-flashfreq-undeclared", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: "\n".join(
            line for line in s.splitlines()
            if "CONFIG_ESPTOOLPY_FLASHFREQ_80M" not in line) + "\n"))),
    ("b-oct-undeclared", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: "\n".join(
            line for line in s.splitlines()
            if "CONFIG_SPIRAM_MODE_OCT" not in line) + "\n"))),
    ("c-foreign-board", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            'VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"',
            'VDOG_BOARD_ID_STR="esp32-s3-devkitc-1"')))),
    ("d-psram-bytes", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u",
            "VDOG_BOARD_PSRAM_SIZE_BYTES=4194304u")))),
    ("e-other-partitions", 1, lambda t: dict(
        _platformio_ini=write_ini(t, lambda s: s.replace(
            "board_build.partitions = partitions/vdog_8mb_two_ota.csv",
            "board_build.partitions = partitions/other.csv")))),
    # PR-N1: last -D wins in CMake; comment blindness must not hide a value.
    ("h-double-psram", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s +
            "\n# added later by mistake\n"
            "target_compile_definitions(${COMPONENT_LIB} PRIVATE\n"
            "    VDOG_BOARD_PSRAM_SIZE_BYTES=4194304u)\n"))),
    ("h2-commented-board", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            GOOD_BLOCK,
            '# VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"\n'
            'target_compile_definitions(${COMPONENT_LIB} PRIVATE\n'
            '    VDOG_BOARD_ID_STR="esp32-s3-devkitc-1"\n'
            '    VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)')))),
    ("h3-duplicated-good-control", 0, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s + "\n" + GOOD_BLOCK +
                                     "\n"))),
    # PR-R5/R6: strict assignment syntax + complete-literal capture.
    ("j1-uppercase-Y", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "CONFIG_ESPTOOLPY_FLASHFREQ_80M=Y")))),
    ("j2-expr-token", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u",
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u/2u")))),
    ("j3-id-trailing", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            'VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"',
            'VDOG_BOARD_ID_STR="seeed_xiao_esp32s3x"')))),
    # PR-R8: whitespace after '=' means "no assignment" to Kconfig.
    ("l1-space-after-eq", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "CONFIG_ESPTOOLPY_FLASHFREQ_80M= y")))),
    ("l2-tab-after-eq", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "CONFIG_ESPTOOLPY_FLASHFREQ_80M=\ty")))),
    # PR-R9: PRIVATE->INTERFACE silently drops the -D flags from the TU.
    ("m1-interface-scope", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            "${COMPONENT_LIB} PRIVATE", "${COMPONENT_LIB} INTERFACE")))),
    # PR-R11/R13: ESP-IDF provenance marker semantics.
    ("n1-default-marker", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "# default:\n" + KEY_LINE)))),
    # R7-correction (PR-R13): '# default: (expr)' is NOT the pragma
    # (parser requires strip() == "# default:") -> ordinary comment -> pin.
    ("n2-default-expr-control", 0, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "# default: (some expr)\n" + KEY_LINE)))),
    ("p1-marker-across-comment", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE,
            "# default:\n# SPI clock frequency\n" + KEY_LINE)))),
    ("p3-unset-last-mention", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE,
            KEY_LINE + "\n# CONFIG_ESPTOOLPY_FLASHFREQ_80M is not set")))),
    ("p4-unset-consumes-marker-control", 0, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE,
            "# default:\n# CONFIG_ESPTOOLPY_FLASHFREQ_80M is not set\n"
            + KEY_LINE)))),
    # PR-R14: loader skips the auto-generated deprecated-options banner pair.
    ("q1-assignment-in-deprecated-section", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: base_removed(s) + "\n"
                                 + DEP_BEGIN + "\n" + KEY_LINE + "\n"
                                 + DEP_END + "\n"))),
    ("q2-assignment-after-end-control", 0, lambda t: dict(
        _defaults=write_defaults(t, lambda s: base_removed(s) + "\n"
                                 + DEP_BEGIN + "\n" + DEP_END + "\n"
                                 + KEY_LINE + "\n"))),
    ("q3-inside-and-after-control", 0, lambda t: dict(
        _defaults=write_defaults(t, lambda s: base_removed(s) + "\n"
                                 + DEP_BEGIN + "\n" + KEY_LINE + "\n"
                                 + DEP_END + "\n" + KEY_LINE + "\n"))),
    # PR-R15: loader universal newlines (\n/\r\n/\r only) and CMake lexer.
    *[
        ("r1-comment-" + tag + "-assignment-one-line", 1,
         (lambda sep: lambda t: dict(
             _defaults=write_defaults(
                 t, lambda s: s.replace(KEY_LINE,
                                        "# SPI clock frequency" + sep
                                        + KEY_LINE))))(sep))
        for tag, sep in SEPS
    ],
    ("r2-comment-newline-assignment-control", 0, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, "# SPI clock frequency\n" + KEY_LINE)))),
    ("r3-assign-U2028-junk", 1, lambda t: dict(
        _defaults=write_defaults(t, lambda s: s.replace(
            KEY_LINE, KEY_LINE + "\u2028junk")))),
    ("r4-psram-U2028-merged-tail", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u",
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u\u2028u")))),
    ("r4b-board-U2028-merged-tail", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            'VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"',
            'VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"\u2028x')))),
    ("r4c-U2028-hidden-around-eq", 1, lambda t: dict(
        _component_cmake=write_cmake(t, lambda s: s.replace(
            "VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u",
            "VDOG_BOARD_PSRAM_SIZE_BYTES\u2028=8388608u")))),
    # Controls: all-real-files clean pass and the wrong-board CLI control.
    ("g1-control-all-real", 0, lambda t: dict()),
    ("g2-control-wrong-board", 1, lambda t: dict(_board="esp32-s3-devkitc-1")),
]


@pytest.mark.skipif(
    not REAL_SDKCONFIG.exists(),
    reason="resolved sdkconfig.json missing — run `pio run -d firmware -e "
           "vdog_xiao_sense_proto` first (out-of-tree evidence dependency)")
@pytest.mark.parametrize(
    "scenario", GATE_SCENARIOS, ids=[s[0] for s in GATE_SCENARIOS])
def test_board_gate_scenario(scenario, tmp_path):
    _, expected, builder = scenario
    overrides = builder(tmp_path)
    assert run_gate(tmp_path, _sdkconfig=REAL_SDKCONFIG, **overrides) == \
        expected


# ---------------------------------------------------------------------------
# Core purity gate: SCons-stub in-process driver (same technique as the
# out-of-tree harness; the stubbed Import injection also documents the F6
# module-level-vs-function-level variant noted in this module docstring).
# ---------------------------------------------------------------------------

class _StubEnv:
    def __init__(self, project_dir: str):
        self.project_dir = project_dir

    def subst(self, text: str) -> str:
        if text == "$PIOENV":
            return "vdog_xiao_sense_proto"
        if text == "$PROJECT_DIR":
            return self.project_dir
        raise AssertionError(text)

    def Exit(self, code: int):  # noqa: N802 - SCons env API shape
        raise SystemExit(code)


def run_purity(project_dir: Path) -> int:
    """Exec check_core_purity.py's SCons path against project_dir."""
    saved = {name: sys.modules.get(name)
             for name in ("SCons", "SCons.Script")}
    sys.modules["SCons"] = types.ModuleType("SCons")
    mod = types.ModuleType("SCons.Script")
    mod.COMMAND_LINE_TARGETS = []
    sys.modules["SCons.Script"] = mod
    try:
        env = _StubEnv(str(project_dir))
        globals_dict = {"__name__": "check_core_purity",
                        "__file__": str(PURITY)}
        globals_dict["Import"] = lambda name: globals_dict.__setitem__(
            name, env)
        src = PURITY.read_text(encoding="utf-8")
        try:
            exec(compile(src, str(PURITY), "exec"), globals_dict)
        except SystemExit as exc:
            return 0 if exc.code is None else int(exc.code)
        return 0
    finally:
        for name, module in saved.items():
            if module is None:
                del sys.modules[name]
            else:
                sys.modules[name] = module


def purity_exit(tmp_path: Path, poison: str, fname: str = "poison.c") -> int:
    """Run the purity gate against a COPY of the real core plus poison file."""
    firmware = tmp_path / "firmware"
    firmware.mkdir()
    shutil.copytree(CORE, firmware / "core")
    if poison:
        (firmware / "core" / fname).write_text(poison, encoding="utf-8")
    return run_purity(firmware)


PURITY_SCENARIOS = [
    # f1–f4: FatFs symbols/headers in a core file are rejections.
    ("f1-ffh", 1, '#include "ff.h"\nFIL file;\nFRESULT rc;\n'
                  'void f(void) { f_mount(NULL, "0:/", 0); }\n'),
    ("f2-diskio", 1, 'FATFS fs;\nvoid g(void) { disk_read(0, NULL, 0, 1); }\n'),
    ("f3-diskio-h", 1, '#include <diskio.h>\n'),
    ("f4-mkfs", 1, 'void f(void) { f_mkfs("0:/", 0, 0); '
                   'f_opendir(NULL, "0:/"); }\n'),
    # f5/i2: controls — stdio/prose words stay clean.
    ("f5-control-stdio", 0, '#include <stdio.h>\n'
                            '/* The portable core uses FILE-free stdio '
                            'internally. */\n'
                            'int f_report(FILE *out);\n'
                            'typedef int my_bytes_t;\n'),
    # i1: PR-N2 f_* family; i2 control: stdio names stay clean.
    ("i1-fsize-family", 1, 'unsigned int f_size_of(void);\n'
                           'void g(void) { f_size(0); f_findfirst(0, 0, 0); '
                           'f_readdir(0, 0, 0); }\n'),
    ("i2-control-stdio-names", 0, '#include <stdio.h>\n#include <time.h>\n'
                                  'void h(FILE *f) { printf("x"); fputs("y",'
                                  ' f); rewind(f); struct utimbuf t; '
                                  '(void)t; }\n'
                                  'unsigned int size; /* plain word */\n'),
    # k1/k2/k3a/k3b: PR-R7/R10 basename-anchored header classes.
    ("k1-control-lookalike-headers", 0,
     '#ifndef BUFFER_H\n#define BUFFER_H\n'
     '#include "buffer_impl.h"\n#include "config_types.h"\n'
     '#include "my_effective_settings.h"\nint b(void);\n#endif\n'),
    ("k2-real-fatfs-headers", 1, '#include "ff.h"\n#include "esp_port/ff.h"\n'
                                 '#include <diskio.h>\n'),
    ("k3a-prefix-class", 1, '#include "./ff.h"\n#include "fat-fs/diskio.h"\n'
                            '#include "a/b/c/ff.h"\n'),
    ("k3b-control-lookalikes", 0, '#include "my_ff.h"\n#include '
                                  '"ffbuffer.h"\n'),
]


@pytest.mark.parametrize(
    "scenario", PURITY_SCENARIOS, ids=[s[0] for s in PURITY_SCENARIOS])
def test_purity_gate_scenario(scenario, tmp_path):
    _, expected, poison = scenario
    fname = "buffer.h" if scenario[0] == "k1-control-lookalike-headers" \
        else "poison.c"
    assert purity_exit(tmp_path, poison, fname) == expected


def test_purity_gate_clean_on_the_real_core(tmp_path):
    """Control: the committed core/ passes with nothing poisoned."""
    assert purity_exit(tmp_path, "") == 0
