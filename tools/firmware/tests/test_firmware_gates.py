"""Firmware gate-script regression harness (1.2 §A7 carry-over F7(b), rehomed
from the lead's out-of-tree scenario drivers per plan 1.1 §12/§13 item 4).

Master plan §4.4 bars a Python test framework under ``firmware/``, so the two
build-time gates — ``firmware/scripts/check_board_config.py`` and
``firmware/scripts/check_core_purity.py`` — were exercised only by
out-of-tree drivers. This is the lead-owned replacement: CI's
``firmware-package-tests`` job now guards the gate scripts themselves, so a
future edit to either script cannot silently widen the gate.

Coverage mirrors the plan 1.1 §10/§11 PR-R regression matrix:

* ``check_board_config.py`` — the four independent layers (source
  declarations in ``sdkconfig.defaults``, resolved ``sdkconfig.json``
  present-and-equal, component ``target_compile_definitions`` provenance,
  effective partition agreement), one poisoned variant per layer, the
  unreadable/malformed/missing-input failures, the documented
  ``0 = agree / 1 = gate failure / 2 = argparse usage only`` exit contract,
  and the SCons-mode path (environment guard, ``__test``/``nobuild``/``clean``
  skip targets, post-action registration, the ``*_test`` build-dir
  tolerance, partition-source probing) against a stub SCons ``env``.
* ``check_core_purity.py`` — every banned token class (camera, SD/MMC and
  SPI-SD, RTOS/FreeRTOS, SDK/``nvs``/Wi-Fi/Arduino, FatFs/disk-io and the
  SDK-style include rules) injected into a temp copy of a clean portable
  core, the documented look-alike controls that must stay clean, scan-mode
  behaviour (recursive relative paths, extension filter, ``.pio``/``build_gen``
  pruning, required-source and missing-directory failures, the usage error)
  and the deliberate ``splitlines()`` detection superset (PR-R15).

Nothing here writes to the repository: the real tree is only READ (the CLI
override flags point at temp fixtures, and the purity script is copied into a
temp tree so its ``core/`` resolution lands on fixtures). Every case is
stdlib-only, offline and deterministic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

import support

REPO_ROOT = support.REPO_ROOT
FIRMWARE_DIR = REPO_ROOT / "firmware"
BOARD_SCRIPT = FIRMWARE_DIR / "scripts/check_board_config.py"
PURITY_SCRIPT = FIRMWARE_DIR / "scripts/check_core_purity.py"
REAL_SDKCONFIG = FIRMWARE_DIR / ".pio/build/vdog_xiao_sense_proto/config/sdkconfig.json"
SUBPROCESS_TIMEOUT = 60

ENVIRONMENT = "vdog_xiao_sense_proto"
EXPECTED_BOARD = "seeed_xiao_esp32s3"
EXPECTED_PSRAM = 8 * 1024 * 1024
EXPECTED_CSV = "partitions/vdog_8mb_two_ota.csv"

# Pinned mirror of check_board_config.EXPECTED_KEYS. This duplication is the
# point: the script header calls that table "the single source of truth for
# expected values", so the harness restates it and an independent test
# (test_gate_expected_table_is_the_pinned_one) fails if anyone edits the gate
# table without a matching review of this harness.
EXPECTED_KEYS: tuple[tuple[str, object], ...] = (
    ("IDF_TARGET", "esp32s3"),
    ("ESPTOOLPY_FLASHSIZE_8MB", True),
    ("ESPTOOLPY_FLASHMODE_QIO", True),
    ("ESPTOOLPY_FLASHFREQ_80M", True),
    ("SPIRAM", True),
    ("SPIRAM_MODE_OCT", True),
    ("SPIRAM_SPEED_80M", True),
    ("PARTITION_TABLE_CUSTOM", True),
    ("PARTITION_TABLE_CUSTOM_FILENAME", EXPECTED_CSV),
    ("ESP_CONSOLE_USB_CDC", True),
    ("ESP_CONSOLE_SECONDARY_NONE", True),
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def run_script(script: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """Run a gate script with the harness interpreter (both are stdlib-only)."""
    assert script.is_file(), f"missing gate script: {script}"
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
    )


def declaration_line(key: str, expected: object) -> str:
    """The one source-declaration form the gate honours (PR-R5/PR-R8)."""
    if isinstance(expected, bool):
        return "CONFIG_%s=%s" % (key, "y" if expected else "n")
    return 'CONFIG_%s="%s"' % (key, expected)


# ---------------------------------------------------------------------------
# check_board_config.py fixtures: a temp tree reached only through the CLI
# override flags, so the repository files are never inputs.
# ---------------------------------------------------------------------------


def baseline_defaults_text() -> str:
    lines = [
        "# fixture sdkconfig.defaults — mirrors the repository file's shape",
        "# (comments and unrelated keys must not disturb layer 1)",
        "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y",
    ]
    lines += [declaration_line(key, expected) for key, expected in EXPECTED_KEYS]
    return "\n".join(lines) + "\n"


def baseline_config(**overrides: object) -> dict[str, object]:
    config = dict(EXPECTED_KEYS)
    config.update(overrides)
    return config


BASELINE_CMAKE = """idf_component_register(SRCS "vdog_board_idf.c"
                       INCLUDE_DIRS "."
                       REQUIRES vdog_core esp_hw_support esp_psram spi_flash)

# Board identity and PSRAM capacity are build configuration inputs.
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"
    VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)
"""

BASELINE_INI = """[env:%s]
platform = platformio/espressif32@8.0.0
board = seeed_xiao_esp32s3
board_build.partitions = partitions/vdog_8mb_two_ota.csv

[env:native]
platform = native
""" % ENVIRONMENT


class BoardGateTree:
    """Temp sources for the four board-gate layers plus a CLI runner.

    ``run()`` always passes every override flag, so a case exercises exactly
    the inputs it intends; ``omit`` drops flags to exercise the usage error.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.defaults = tmp_path / "sdkconfig.defaults"
        self.sdkconfig = tmp_path / "config/sdkconfig.json"
        self.cmake = tmp_path / "components/vdog_board/CMakeLists.txt"
        self.ini = tmp_path / "platformio.ini"
        self.board = EXPECTED_BOARD
        self.write_defaults(baseline_defaults_text())
        self.write_config(baseline_config())
        self.write_cmake(BASELINE_CMAKE)
        self.write_ini(BASELINE_INI)

    # -- writers ---------------------------------------------------------
    def write_defaults(self, text: str) -> None:
        self.defaults.write_text(text, encoding="utf-8")

    def edit_defaults(self, transform) -> None:
        lines = self.defaults.read_text(encoding="utf-8").split("\n")
        self.write_defaults("\n".join(transform(lines)))

    def write_config(self, config: dict[str, object]) -> None:
        self.sdkconfig.parent.mkdir(parents=True, exist_ok=True)
        self.sdkconfig.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )

    def write_config_text(self, text: str) -> None:
        self.sdkconfig.parent.mkdir(parents=True, exist_ok=True)
        self.sdkconfig.write_text(text, encoding="utf-8")

    def edit_config(self, transform) -> None:
        config = json.loads(self.sdkconfig.read_text(encoding="utf-8"))
        transform(config)
        self.write_config(config)

    def write_cmake(self, text: str) -> None:
        self.cmake.parent.mkdir(parents=True, exist_ok=True)
        self.cmake.write_text(text, encoding="utf-8")

    def write_ini(self, text: str) -> None:
        self.ini.write_text(text, encoding="utf-8")

    # -- runner ----------------------------------------------------------
    def run(
        self,
        *extra: str,
        omit: tuple[str, ...] = (),
        board: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv: list[str] = []
        if "--sdkconfig" not in omit:
            argv += ["--sdkconfig", str(self.sdkconfig)]
        if "--board" not in omit:
            argv += ["--board", board if board is not None else self.board]
        if "--defaults" not in omit:
            argv += ["--defaults", str(self.defaults)]
        if "--component-cmake" not in omit:
            argv += ["--component-cmake", str(self.cmake)]
        if "--platformio-ini" not in omit:
            argv += ["--platformio-ini", str(self.ini)]
        argv += list(extra)
        return run_script(BOARD_SCRIPT, *argv)


@pytest.fixture()
def board_tree(tmp_path: Path) -> BoardGateTree:
    return BoardGateTree(tmp_path)


# ---------------------------------------------------------------------------
# check_board_config.py SCons-mode stubs (plan 1.1 §12 F7(b): the SCons path
# was previously proven only by out-of-tree drivers)
# ---------------------------------------------------------------------------


class SconsExit(Exception):
    """Raised by the stub ``env.Exit()`` exactly as SCons aborts the build."""

    def __init__(self, code: int) -> None:
        super().__init__("SCons Exit(%s)" % code)
        self.code = code


class FakeSconsEnv:
    """The subset of the SCons environment the gate actually touches."""

    def __init__(
        self,
        project_dir: Path,
        *,
        pioenv: str = ENVIRONMENT,
        board: str | None = EXPECTED_BOARD,
        build_dir: Path | None = None,
        progname: str = "firmware",
        project_options: dict[str, str | None] | None = None,
        board_build: dict[str, str | None] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.values = {
            "$PIOENV": pioenv,
            "$BOARD": board,
            "$PROJECT_DIR": str(self.project_dir),
            "$BUILD_DIR": str(build_dir if build_dir else self.project_dir / ".pio/build" / ENVIRONMENT),
            "${PROGNAME}": progname,
        }
        self.project_options = dict(project_options or {})
        self.board_build = board_build
        self.post_actions: list[tuple[str, object]] = []
        self.project_option_calls: list[str] = []
        self.exit_codes: list[int] = []

    def subst(self, text: str) -> str:
        out = text
        for token, value in self.values.items():
            out = out.replace(token, "" if value is None else str(value))
        return out

    def Exit(self, code: int = 0) -> None:  # SCons.Script.Exit semantics
        self.exit_codes.append(code)
        raise SconsExit(code)

    def AddPostAction(self, target, action) -> None:
        self.post_actions.append((str(target), action))

    def GetProjectOption(self, name: str, default=None):
        self.project_option_calls.append(name)
        return self.project_options.get(name, default)

    def get(self, key: str, default=None):
        if key == "BOARD_BUILD":
            return self.board_build if self.board_build is not None else default
        return default


def load_board_script_as_scons(
    monkeypatch: pytest.MonkeyPatch,
    env: FakeSconsEnv,
    targets: tuple[str, ...] = (),
):
    """exec the gate the way ``ExecScript`` does.

    SCons injects ``Import`` into the module globals before parsing the extra
    script, which is exactly the switch the script's module-level dispatch
    reads (``if "Import" in globals()``), so this exercises the real SCons
    branch including the ``Import("env")`` placement fixed in F6.
    """
    scons_pkg = types.ModuleType("SCons")
    script_pkg = types.ModuleType("SCons.Script")
    script_pkg.COMMAND_LINE_TARGETS = list(targets)
    scons_pkg.Script = script_pkg
    monkeypatch.setitem(sys.modules, "SCons", scons_pkg)
    monkeypatch.setitem(sys.modules, "SCons.Script", script_pkg)
    name = "vdog_check_board_config_under_scons"
    spec = importlib.util.spec_from_file_location(name, BOARD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.Import = lambda key: setattr(module, key, env)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def scons_firmware_tree(tmp_path: Path, **overrides) -> Path:
    """A firmware/-shaped tree for SCons mode (layers 1/3/4 read tracked files)."""
    firmware = tmp_path / "firmware"
    (firmware / "components/vdog_board").mkdir(parents=True, exist_ok=True)
    (firmware / "sdkconfig.defaults").write_text(baseline_defaults_text(), encoding="utf-8")
    (firmware / "components/vdog_board/CMakeLists.txt").write_text(BASELINE_CMAKE, encoding="utf-8")
    (firmware / "platformio.ini").write_text(
        overrides.get("ini", BASELINE_INI), encoding="utf-8"
    )
    build_dir = firmware / ".pio/build/vdog_xiao_sense_proto"
    if overrides.get("config", True):
        (build_dir / "config").mkdir(parents=True, exist_ok=True)
        (build_dir / "config/sdkconfig.json").write_text(
            json.dumps(overrides.get("config", baseline_config()), indent=2) + "\n",
            encoding="utf-8",
        )
    return firmware


# ---------------------------------------------------------------------------
# check_core_purity.py fixtures: the script is COPIED into a temp tree, because
# its CLI resolves core/ relative to __file__ and takes no path flags.
# ---------------------------------------------------------------------------


CLEAN_CORE_FILES: dict[str, str] = {
    "vdog_core.h": (
        '#ifndef VDOG_CORE_H\n#define VDOG_CORE_H\nint vdog_core_version_major(void);\n'
        "#endif\n"
    ),
    "vdog_core.c": (
        '#include "vdog_core.h"\nint vdog_core_version_major(void) { return 1; }\n'
    ),
    "vdog_board.h": (
        '#ifndef VDOG_BOARD_H\n#define VDOG_BOARD_H\nint vdog_board_validate(void);\n'
        "#endif\n"
    ),
    "vdog_board.c": (
        '#include "vdog_board.h"\nint vdog_board_validate(void) { return 0; }\n'
    ),
    "library.json": '{ "name": "vdog-core", "version": "1.2.0", "headers": ["vdog_core.h"] }\n',
}


class PurityTree:
    """Temp firmware tree: copied script under scripts/, fixture core/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.core = root / "core"
        self.core.mkdir(parents=True, exist_ok=True)
        self.script = root / "scripts/check_core_purity.py"
        self.script.parent.mkdir(parents=True, exist_ok=True)
        self.script.write_text(PURITY_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

    def seed_clean(self) -> "PurityTree":
        for name, body in CLEAN_CORE_FILES.items():
            (self.core / name).write_text(body, encoding="utf-8")
        return self

    def add(self, name: str, text: str) -> str:
        """Write one core file; returns the relative path the gate reports."""
        path = self.core / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return "core/" + name.replace(os.sep, "/")

    def add_probe(self, statement: str, name: str = "vdog_probe.c") -> str:
        """Inject ``statement`` at a known line (3) of a fixture source."""
        return self.add(
            name,
            "/* purity probe */\n#include \"vdog_core.h\"\n%s\n" % statement,
        )

    def remove(self, name: str) -> None:
        (self.core / name).unlink()

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return run_script(self.script, *argv)


@pytest.fixture()
def purity_tree(tmp_path: Path) -> PurityTree:
    return PurityTree(tmp_path / "firmware").seed_clean()


# ---------------------------------------------------------------------------
# check_board_config.py — helpers for poisoning one layer at a time
# ---------------------------------------------------------------------------

_KEY_TO_EXPECTED = dict(EXPECTED_KEYS)


def defaults(transform):
    """Adapt a line-list transform into a tree-level preparation step."""
    return lambda tree: tree.edit_defaults(transform)


def replace_declaration(key: str, new_line: str):
    """Swap the one honoured declaration line for a tampered variant."""
    old = declaration_line(key, _KEY_TO_EXPECTED[key])
    return defaults(lambda lines: [new_line if line == old else line for line in lines])


def drop_declaration(key: str):
    old = declaration_line(key, _KEY_TO_EXPECTED[key])
    return defaults(lambda lines: [line for line in lines if line != old])


def insert_before_declaration(key: str, *new_lines: str):
    old = declaration_line(key, _KEY_TO_EXPECTED[key])

    def transform(lines: list[str]) -> list[str]:
        out: list[str] = []
        for line in lines:
            if line == old:
                out.extend(new_lines)
            out.append(line)
        return out

    return defaults(transform)


def append_lines(*new_lines: str):
    return defaults(lambda lines: list(lines) + list(new_lines))



DEPRECATED_BEGIN = "# Deprecated options for backward compatibility"
DEPRECATED_END = "# End of deprecated options"


# ---------------------------------------------------------------------------
# check_board_config.py — acceptance (exit 0)
# ---------------------------------------------------------------------------


def test_real_repo_baseline_accepted_by_ci_invocation() -> None:
    """The exact CI/command-record invocation from docs/toolchain.md.

    Skips only when the generated build config is absent (a clean checkout has
    no ``.pio/``), never when it disagrees — that is a gate failure.
    """
    if not REAL_SDKCONFIG.is_file():
        pytest.skip("no firmware/.pio/build/.../config/sdkconfig.json in this context")
    result = run_script(
        BOARD_SCRIPT, "--sdkconfig", str(REAL_SDKCONFIG), "--board", EXPECTED_BOARD
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 keys declared in sdkconfig.defaults" in result.stdout
    assert "agreed by all three sources" in result.stdout


def test_full_fixture_baseline_accepted(board_tree: BoardGateTree) -> None:
    """All four layers agree on the temp baseline → exit 0, one summary line."""
    result = board_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert "11 keys declared in sdkconfig.defaults" in result.stdout
    assert "board=%s (env + component definition)" % EXPECTED_BOARD in result.stdout
    assert EXPECTED_CSV in result.stdout


def test_gate_expected_table_is_the_pinned_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness mirror above must still equal the gate's single source of
    truth; editing ``EXPECTED_KEYS`` in the script is a reviewed change."""
    env = FakeSconsEnv(scons_firmware_tree(tmp_path))
    module = load_board_script_as_scons(monkeypatch, env)
    assert tuple(module.EXPECTED_KEYS) == EXPECTED_KEYS
    assert module.EXPECTED_BOARD == EXPECTED_BOARD
    assert module.EXPECTED_PSRAM_SIZE_BYTES == EXPECTED_PSRAM
    assert module.EXPECTED_PARTITION_CSV == EXPECTED_CSV


@pytest.mark.parametrize(
    "prepare",
    [
        lambda t: t.write_cmake(BASELINE_CMAKE + BASELINE_CMAKE.split("\n\n", 1)[1]),
        lambda t: t.write_ini(
            BASELINE_INI.replace(
                "board_build.partitions = partitions/vdog_8mb_two_ota.csv",
                'board_build.partitions = "./partitions/vdog_8mb_two_ota.csv"',
            )
        ),
        lambda t: append_lines(
            DEPRECATED_BEGIN,
            "CONFIG_ESPTOOLPY_FLASHFREQ_80M=n",
            DEPRECATED_END,
            "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y",
        )(t),
        lambda t: append_lines(
            "# default:",
            "# CONFIG_ESP_CONSOLE_SECONDARY_NONE is not set",
            "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y",
        )(t),
        lambda t: append_lines(
            "# default:",
            DEPRECATED_BEGIN,
            DEPRECATED_END,
            "CONFIG_ESPTOOLPY_FLASHMODE_QIO=y",
        )(t),
        lambda t: t.write_ini(
            BASELINE_INI
            + "\n[env:clone]\nboard_build.partitions = partitions/late.csv\n"
        ),
    ],
    ids=[
        "duplicated-identical-good-blocks",
        "partition-path-normalised",
        "deprecated-section-duplicate-after-end",
        "unset-marker-consumed-by-set-after",
        "marker-cleared-by-banner-assignment-after-end",
        "ini-option-shadowed-by-foreign-section",
    ],
)
def test_documented_acceptance_controls(board_tree: BoardGateTree, prepare) -> None:
    """Plan §11 controls that must stay green (h3, ./-normalisation, q3, p4,
    the marker/section edge probes, and PlatformIO's own section-scoped
    option resolution: a same-name option in a FOREIGN env section is not
    the effective value and must not trip the gate): over-rejection here
    would block builds."""
    prepare(board_tree)
    result = board_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# check_board_config.py — assertion helper
# ---------------------------------------------------------------------------


def assert_failure(
    result: subprocess.CompletedProcess[str],
    *substrings: str,
    enumerated: bool = True,
    count: int | None = None,
) -> str:
    """Exit 1 from the board gate.

    ``enumerated`` selects the two failure faces: ``_reject`` reports the
    numbered problem list (a configuration disagreement), ``_fail`` aborts on
    an input it cannot read — and an unreadable source is never a pass.
    """
    text = result.stdout + result.stderr
    assert result.returncode == 1, text
    assert "*** vdog board-config gate: ERROR:" in text, text
    if enumerated:
        assert "build configuration rejected" in text, text
        if count is not None:
            assert "(%d problem(s)" % count in text, text
    for substring in substrings:
        assert substring in text, text
    return text


def compose(*preparations):
    """Run several tree-level preparation steps in order."""

    def apply(tree: BoardGateTree) -> None:
        for preparation in preparations:
            preparation(tree)

    return apply


# ---------------------------------------------------------------------------
# check_board_config.py — layer 1: source declarations in sdkconfig.defaults
# The resolved config stays GREEN in every case, so exactly one problem is
# reported and only the declaration layer can catch it (plan §11 PR-R1/R5/R8/
# R11/R13/R14/R15 regressions).
# ---------------------------------------------------------------------------

UNDECLARED = "not declared in"
SDK_DEFAULT = "resolved value may be an SDK default"

LAYER1_CASES = [
    (
        "deleted-flashfreq-line",
        drop_declaration("ESPTOOLPY_FLASHFREQ_80M"),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED, SDK_DEFAULT),
    ),
    (
        "uppercase-Y-bool",
        replace_declaration("ESPTOOLPY_FLASHSIZE_8MB", "CONFIG_ESPTOOLPY_FLASHSIZE_8MB=Y"),
        1,
        ("CONFIG_ESPTOOLPY_FLASHSIZE_8MB: " + UNDECLARED, SDK_DEFAULT),
    ),
    (
        "space-after-equals",
        replace_declaration("ESPTOOLPY_FLASHFREQ_80M", "CONFIG_ESPTOOLPY_FLASHFREQ_80M= y"),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED,),
    ),
    (
        "tab-after-equals",
        replace_declaration("SPIRAM_MODE_OCT", "CONFIG_SPIRAM_MODE_OCT=\ty"),
        1,
        ("CONFIG_SPIRAM_MODE_OCT: " + UNDECLARED,),
    ),
    (
        "space-before-equals",
        replace_declaration("SPIRAM", "CONFIG_SPIRAM =y"),
        1,
        ("CONFIG_SPIRAM: " + UNDECLARED,),
    ),
    (
        "leading-whitespace",
        replace_declaration("ESP_CONSOLE_USB_CDC", " CONFIG_ESP_CONSOLE_USB_CDC=y"),
        1,
        ("CONFIG_ESP_CONSOLE_USB_CDC: " + UNDECLARED,),
    ),
    (
        "bool-written-as-one",
        replace_declaration("SPIRAM_SPEED_80M", "CONFIG_SPIRAM_SPEED_80M=1"),
        1,
        ("CONFIG_SPIRAM_SPEED_80M: " + UNDECLARED,),
    ),
    (
        "unquoted-string-value",
        replace_declaration(
            "PARTITION_TABLE_CUSTOM_FILENAME",
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=partitions/vdog_8mb_two_ota.csv",
        ),
        1,
        ("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME: " + UNDECLARED,),
    ),
    (
        "default-pragma-marker",
        insert_before_declaration("SPIRAM_SPEED_80M", "# default:"),
        1,
        ("CONFIG_SPIRAM_SPEED_80M: " + UNDECLARED, SDK_DEFAULT),
    ),
    (
        "pragma-persists-across-comment",
        insert_before_declaration(
            "SPIRAM_SPEED_80M", "# default:", "# unrelated provenance comment"
        ),
        1,
        ("CONFIG_SPIRAM_SPEED_80M: " + UNDECLARED,),
    ),
    (
        "commented-out-declaration",
        replace_declaration("ESPTOOLPY_FLASHMODE_QIO", "# CONFIG_ESPTOOLPY_FLASHMODE_QIO=y"),
        1,
        ("CONFIG_ESPTOOLPY_FLASHMODE_QIO: " + UNDECLARED,),
    ),
    (
        "unset-is-last-mention",
        append_lines("# CONFIG_SPIRAM is not set"),
        1,
        ("CONFIG_SPIRAM: " + UNDECLARED,),
    ),
    (
        "u2028-hides-assignment-in-comment",
        replace_declaration(
            "ESPTOOLPY_FLASHFREQ_80M",
            "# SPI clock frequency\u2028CONFIG_ESPTOOLPY_FLASHFREQ_80M=y",
        ),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED,),
    ),
    (
        "u2028-trailing-junk-on-assignment",
        replace_declaration(
            "ESPTOOLPY_FLASHFREQ_80M", "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y\u2028junk"
        ),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED,),
    ),
    (
        "last-wins-bad-duplicate",
        append_lines("CONFIG_ESPTOOLPY_FLASHFREQ_80M=1"),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED,),
    ),
    (
        "assignment-only-inside-deprecated-section",
        compose(
            drop_declaration("ESPTOOLPY_FLASHFREQ_80M"),
            append_lines(
                DEPRECATED_BEGIN,
                "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y",
                DEPRECATED_END,
            ),
        ),
        1,
        ("CONFIG_ESPTOOLPY_FLASHFREQ_80M: " + UNDECLARED, SDK_DEFAULT),
    ),
    (
        "unclosed-deprecated-begin-skips-to-eof",
        compose(
            drop_declaration("SPIRAM_MODE_OCT"),
            append_lines(DEPRECATED_BEGIN, "CONFIG_SPIRAM_MODE_OCT=y"),
        ),
        1,
        ("CONFIG_SPIRAM_MODE_OCT: " + UNDECLARED,),
    ),
]


@pytest.mark.parametrize(
    "prepare,count,substrings",
    [case[1:] for case in LAYER1_CASES],
    ids=[case[0] for case in LAYER1_CASES],
)
def test_layer1_source_declarations_rejected(
    board_tree: BoardGateTree, prepare, count: int, substrings: tuple[str, ...]
) -> None:
    """An inherited/invisible SDK default can never satisfy the gate."""
    prepare(board_tree)
    assert_failure(board_tree.run(), *substrings, count=count)


# ---------------------------------------------------------------------------
# check_board_config.py — layer 2: resolved sdkconfig.json present-and-equal
# (type-strict), board identity, and the unusable-input faces.
# ---------------------------------------------------------------------------


def poison_config(key: str, value: object):
    return lambda tree: tree.write_config(baseline_config(**{key: value}))


def remove_config_key(key: str):
    def prepare(tree: BoardGateTree) -> None:
        config = baseline_config()
        del config[key]
        tree.write_config(config)

    return prepare


LAYER2_CASES = [
    (
        "key-absent-is-not-a-default",
        remove_config_key("IDF_TARGET"),
        1,
        ("IDF_TARGET: expected 'esp32s3' but the key is ABSENT",),
    ),
    (
        "flash-size-4mb",
        poison_config("ESPTOOLPY_FLASHSIZE_8MB", False),
        1,
        ("ESPTOOLPY_FLASHSIZE_8MB: expected True, got False",),
    ),
    (
        "flash-mode-string-y-not-bool",
        poison_config("ESPTOOLPY_FLASHMODE_QIO", "y"),
        1,
        ("ESPTOOLPY_FLASHMODE_QIO: expected True, got 'y'",),
    ),
    (
        "flash-mode-disabled",
        poison_config("ESPTOOLPY_FLASHMODE_QIO", False),
        1,
        ("ESPTOOLPY_FLASHMODE_QIO: expected True, got False",),
    ),
    (
        "flash-freq-int-one-not-bool",
        poison_config("ESPTOOLPY_FLASHFREQ_80M", 1),
        1,
        ("ESPTOOLPY_FLASHFREQ_80M: expected True, got 1",),
    ),
    (
        "flash-freq-40m",
        poison_config("ESPTOOLPY_FLASHFREQ_80M", False),
        1,
        ("ESPTOOLPY_FLASHFREQ_80M: expected True, got False",),
    ),
    (
        "target-esp32-not-s3",
        poison_config("IDF_TARGET", "esp32"),
        1,
        ("IDF_TARGET: expected 'esp32s3', got 'esp32'",),
    ),
    (
        "psram-quad-not-octal",
        poison_config("SPIRAM_MODE_OCT", False),
        1,
        ("SPIRAM_MODE_OCT: expected True, got False",),
    ),
    (
        "psram-disabled",
        poison_config("SPIRAM", False),
        1,
        ("SPIRAM: expected True, got False",),
    ),
    (
        "console-secondary-not-none",
        poison_config("ESP_CONSOLE_SECONDARY_NONE", False),
        1,
        ("ESP_CONSOLE_SECONDARY_NONE: expected True, got False",),
    ),
    (
        "json-array-instead-of-object",
        lambda tree: tree.write_config_text("[]\n"),
        2,
        ("sdkconfig.json must contain a JSON object, got list",),
    ),
    (
        "json-scalar-instead-of-object",
        lambda tree: tree.write_config_text("42\n"),
        2,
        ("must contain a JSON object, got int",),
    ),
]


@pytest.mark.parametrize(
    "prepare,count,substrings",
    [case[1:] for case in LAYER2_CASES],
    ids=[case[0] for case in LAYER2_CASES],
)
def test_layer2_resolved_config_rejected(
    board_tree: BoardGateTree, prepare, count: int, substrings: tuple[str, ...]
) -> None:
    prepare(board_tree)
    assert_failure(board_tree.run(), *substrings, count=count)


@pytest.mark.parametrize(
    "text,substrings",
    [
        ("{ 'IDF_TARGET': 'esp32s3',,, }\n", ("is not valid JSON",)),
        ("", ("is not valid JSON",)),
        ("   ", ("is not valid JSON",)),
    ],
    ids=["trailing-commas", "empty-file", "whitespace-only"],
)
def test_malformed_sdkconfig_json_is_a_gate_failure(
    board_tree: BoardGateTree, text: str, substrings: tuple[str, ...]
) -> None:
    """A config that cannot be parsed aborts the gate — never a silent pass."""
    board_tree.write_config_text(text)
    assert_failure(board_tree.run(), *substrings, enumerated=False)


def test_missing_sdkconfig_file_is_a_gate_failure(board_tree: BoardGateTree) -> None:
    board_tree.sdkconfig.unlink()
    assert_failure(
        board_tree.run(), "cannot read sdkconfig:", "does not exist", enumerated=False
    )


def test_unreadable_sdkconfig_file_is_a_gate_failure(board_tree: BoardGateTree) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("mode bits do not deny the root user")
    board_tree.sdkconfig.chmod(0o000)
    try:
        assert_failure(
            board_tree.run(), "cannot read sdkconfig", enumerated=False
        )
    finally:
        board_tree.sdkconfig.chmod(0o644)


@pytest.mark.parametrize(
    "board,substring",
    [
        (
            "esp32-s3-devkitc-1",
            "board (build environment $BOARD): expected 'seeed_xiao_esp32s3', "
            "got 'esp32-s3-devkitc-1'",
        ),
        (
            "seeed_xiao_esp32c3",
            "board (build environment $BOARD): expected 'seeed_xiao_esp32s3', "
            "got 'seeed_xiao_esp32c3'",
        ),
    ],
    ids=["foreign-board-id", "wrong-family-board-id"],
)
def test_board_identity_rejected_by_environment_argument(
    board_tree: BoardGateTree, board: str, substring: str
) -> None:
    """A foreign board id can never pass, whatever the config says."""
    assert_failure(board_tree.run(board=board), substring, count=1)


def test_board_key_in_resolved_config_must_agree(board_tree: BoardGateTree) -> None:
    """A fixture carrying a ``board`` key is compared as well (script header)."""
    board_tree.edit_config(lambda config: config.update({"board": "esp32-s3-devkitc-1"}))
    assert_failure(
        board_tree.run(),
        "board (sdkconfig.json board key): expected 'seeed_xiao_esp32s3', "
        "got 'esp32-s3-devkitc-1'",
        count=1,
    )


# ---------------------------------------------------------------------------
# check_board_config.py — layer 3: component compile-definition provenance
# (PR-R2/R6/R9 + PR-N1 comment stripping / all-occurrences + PR-R15 lexer
# model). Each case rewrites only components/vdog_board/CMakeLists.txt.
# ---------------------------------------------------------------------------


def defs_block(scope: str, board_token: str, psram_token: str) -> str:
    tail = "" if scope == "PRIVATE" else ""
    return (
        "target_compile_definitions(${COMPONENT_LIB} %s\n"
        "    VDOG_BOARD_ID_STR=%s\n"
        "    VDOG_BOARD_PSRAM_SIZE_BYTES=%s)\n" % (scope, board_token, psram_token)
    ) + tail


LAYER3_CASES = [
    (
        "foreign-board-id-token",
        defs_block("PRIVATE", '"esp32-s3-devkitc-1"', "8388608u"),
        1,
        ("VDOG_BOARD_ID_STR", "expected '\"seeed_xiao_esp32s3\"', got '\"esp32-s3-devkitc-1\"'"),
    ),
    (
        "board-id-token-without-quotes",
        defs_block("PRIVATE", "seeed_xiao_esp32s3", "8388608u"),
        1,
        ("VDOG_BOARD_ID_STR", "got 'seeed_xiao_esp32s3'"),
    ),
    (
        "board-id-token-extended",
        defs_block("PRIVATE", '"seeed_xiao_esp32s3x"', "8388608u"),
        1,
        ("VDOG_BOARD_ID_STR", "got '\"seeed_xiao_esp32s3x\"'"),
    ),
    (
        "psram-4mb",
        defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "4194304u"),
        1,
        ("VDOG_BOARD_PSRAM_SIZE_BYTES", "expected 8388608, got '4194304u'"),
    ),
    (
        "psram-expression-not-literal",
        defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "8388608u/2u"),
        1,
        (
            "got '8388608u/2u'; not a complete unsigned-decimal literal "
            "(expression characters are passed to the compiler verbatim)",
        ),
    ),
    (
        "psram-hidden-u2028-in-token",
        defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "8388608u\u2028u"),
        1,
        ("VDOG_BOARD_PSRAM_SIZE_BYTES", "not a complete unsigned-decimal literal"),
    ),
    (
        "definitions-public-scoped",
        defs_block("PUBLIC", '"seeed_xiao_esp32s3"', "8388608u"),
        2,
        (
            "target_compile_definitions() must be scoped PRIVATE, found PUBLIC",
        ),
    ),
    (
        "definitions-interface-scoped",
        defs_block("INTERFACE", '"seeed_xiao_esp32s3"', "8388608u"),
        2,
        ("must be scoped PRIVATE, found INTERFACE",),
    ),
    (
        "definitions-unscoped",
        defs_block("", '"seeed_xiao_esp32s3"', "8388608u"),
        2,
        ("must be scoped PRIVATE, found no PRIVATE keyword",),
    ),
    (
        "definitions-outside-any-block",
        'set(VDOG_DEFS VDOG_BOARD_ID_STR="seeed_xiao_esp32s3" '
        'VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)\n',
        2,
        ("occurrence(s) outside any target_compile_definitions() block",),
    ),
    (
        "definitions-only-in-comments",
        '# target_compile_definitions(${COMPONENT_LIB} PRIVATE\n'
        '#     VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"\n'
        '#     VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)\n',
        2,
        (
            "VDOG_BOARD_ID_STR: not defined in",
            "VDOG_BOARD_PSRAM_SIZE_BYTES: not defined in",
        ),
    ),
    (
        "second-tampered-block-hides-behind-good-one",
        BASELINE_CMAKE
        + "\n# scratch override (the compiler would take this last -D)\n"
        + defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "4194304u"),
        1,
        ("expected 8388608, got '4194304u'", "(2 occurrence(s), 1 wrong)"),
    ),
    (
        "hex-literal-passed-verbatim",
        BASELINE_CMAKE
        + "\n" + defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "0x800000"),
        1,
        (
            "expected 8388608, got '0x800000'",
            "not a complete unsigned-decimal literal",
        ),
    ),
    (
        "hidden-u2028-between-command-and-paren",
        BASELINE_CMAKE
        + "\ntarget_compile_definitions\u2028(${COMPONENT_LIB} PRIVATE\n"
        '    VDOG_BOARD_ID_STR="esp32-s3-devkitc-1"\n'
        "    VDOG_BOARD_PSRAM_SIZE_BYTES=4194304u)\n",
        4,
        (
            "expected '\"seeed_xiao_esp32s3\"', got '\"esp32-s3-devkitc-1\"'",
            "expected 8388608, got '4194304u'",
            "VDOG_BOARD_ID_STR",
            "VDOG_BOARD_PSRAM_SIZE_BYTES",
            "outside any target_compile_definitions() block",
        ),
    ),
]


@pytest.mark.parametrize(
    "text,count,substrings",
    [case[1:] for case in LAYER3_CASES],
    ids=[case[0] for case in LAYER3_CASES],
)
def test_layer3_component_definitions_rejected(
    board_tree: BoardGateTree, text: str, count: int, substrings: tuple[str, ...]
) -> None:
    """A compile flag the compiler never receives, or does not receive as
    stated, is a build failure — not a warning."""
    board_tree.write_cmake(text)
    assert_failure(board_tree.run(), *substrings, count=count)


@pytest.mark.parametrize(
    "text",
    [
        BASELINE_CMAKE + "\n" + defs_block("PRIVATE", '"seeed_xiao_esp32s3"', "8388608UL"),
        BASELINE_CMAKE + "\n# VDOG_BOARD_PSRAM_SIZE_BYTES=4194304u (commented scratch)\n",
    ],
    ids=["uppercase-suffix", "commented-wrong-sibling"],
)
def test_layer3_documented_rejections_are_not_over_rejections(
    board_tree: BoardGateTree, text: str
) -> None:
    """Faithful-to-CMake acceptance: an unsigned-decimal literal with any
    suffix set equals 8 MiB, a commented-out definition is not a definition
    in either direction (PR-N1). (A HEX literal is NOT an acceptance
    control — the documented policy is a complete unsigned-DECIMAL literal;
    it is pinned as a rejection in LAYER3_CASES above.)"""
    board_tree.write_cmake(text)
    result = board_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# check_board_config.py — layer 4: effective partition-table agreement
# ---------------------------------------------------------------------------


def ini_with_partitions(value: str):
    return lambda tree: tree.write_ini(
        BASELINE_INI.replace("partitions/vdog_8mb_two_ota.csv", value)
    )


LAYER4_CASES = [
    (
        "scratch-partitions-in-ini",
        ini_with_partitions("partitions/scratch.csv"),
        1,
        (
            "partition table mismatch",
            "partitions/scratch.csv",
            "expected = 'partitions/vdog_8mb_two_ota.csv'",
            "resolved CONFIG_PARTITION_TABLE_CUSTOM_FILENAME = "
            "'partitions/vdog_8mb_two_ota.csv'",
        ),
    ),
    (
        "resolved-filename-diverges-from-ini",
        lambda tree: tree.write_config(
            baseline_config(**{"PARTITION_TABLE_CUSTOM_FILENAME": "partitions/other.csv"})
        ),
        2,
        (
            "partition table mismatch",
            "resolved CONFIG_PARTITION_TABLE_CUSTOM_FILENAME = 'partitions/other.csv'",
        ),
    ),
    (
        "ini-option-missing-entirely",
        lambda tree: tree.write_ini(
            BASELINE_INI.replace(
                "board_build.partitions = partitions/vdog_8mb_two_ota.csv\n", ""
            )
        ),
        1,
        ("partition table mismatch", "= None"),
    ),
    (
        "ini-option-in-foreign-section",
        lambda tree: tree.write_ini(
            BASELINE_INI.replace(
                "board_build.partitions = partitions/vdog_8mb_two_ota.csv\n", ""
            ).replace("[env:native]", "[env:other_board]"),
        ),
        1,
        ("partition table mismatch", "= None"),
    ),
]


@pytest.mark.parametrize(
    "prepare,count,substrings",
    [case[1:] for case in LAYER4_CASES],
    ids=[case[0] for case in LAYER4_CASES],
)
def test_layer4_partition_table_disagreement_rejected(
    board_tree: BoardGateTree, prepare, count: int, substrings: tuple[str, ...]
) -> None:
    """PlatformIO's effective option, the resolved filename and the expected
    CSV must be the same file; a mismatch names all three (PR-R3)."""
    prepare(board_tree)
    assert_failure(board_tree.run(), *substrings, count=count)


# ---------------------------------------------------------------------------
# check_board_config.py — unreadable inputs and the usage contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute,label",
    [
        ("defaults", "sdkconfig.defaults"),
        ("cmake", "component CMakeLists.txt"),
        ("ini", "platformio.ini"),
    ],
    ids=["defaults", "component-cmake", "platformio-ini"],
)
def test_missing_tracked_input_is_a_gate_failure(
    board_tree: BoardGateTree, attribute: str, label: str
) -> None:
    """Layers 1/3/4 read tracked sources: a source that cannot be read is
    never a pass (documented exit-1 face)."""
    getattr(board_tree, attribute).unlink()
    assert_failure(
        board_tree.run(), "cannot read %s" % label, "does not exist", enumerated=False
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--bogus-flag"],
        ["--sdkconfig", "x.json"],
        ["--board", EXPECTED_BOARD],
        [],
    ],
    ids=["unknown-flag", "missing-board", "missing-sdkconfig", "no-arguments"],
)
def test_usage_errors_exit_two(board_tree: BoardGateTree, argv: list[str]) -> None:
    """Exit 2 is reserved for argparse usage errors (documented contract)."""
    result = run_script(BOARD_SCRIPT, *argv)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "usage: check_board_config.py" in result.stderr
    assert "ERROR" not in result.stderr


# ---------------------------------------------------------------------------
# check_core_purity.py — banned token classes (each injected at a pinned line
# of a probe file inside a clean fixture core; the copy under scripts/ keeps
# the script's own core/ resolution pointed at the fixture tree)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement,reason",
    [
        ("esp_err_t esp_flash_begin(void);", "SDK API/symbol prefix"),
        ("camera_config_t c;", "camera driver symbol"),
        ("void sdmmc_host_init(void);", "SD/MMC host driver symbol"),
        ("int sdspi_do_send_command(void);", "SPI-SD driver symbol"),
        ("int nvs_open(const char *s);", "NVS API symbol"),
        ("/* freertos */", "RTOS symbol"),
        ("/* taskhandle */", "RTOS symbol"),
        ("void vTaskDelay(int x);", "RTOS symbol"),
        ("void xTaskCreate(void);", "FreeRTOS kernel API"),
        ("void xQueueSend(void);", "FreeRTOS kernel API"),
        ("void xSemaphoreGive(void);", "FreeRTOS kernel API"),
        ("int pdTRUE = 1;", "FreeRTOS kernel API"),
        ("int portTICK_PERIOD_MS = 1000;", "FreeRTOS kernel API"),
        ("TickType_t t;", "FreeRTOS kernel API"),
        ("int wifi_init(void);", "Wi-Fi API symbol"),
        ("int arduino = 1;", "Arduino framework token"),
        ("#include <driver/gpio.h>", "SDK/RTOS/system header"),
        ("#include <rom/uart.h>", "SDK/RTOS/system header"),
        ("#include <task.h>", "SDK/RTOS/system header"),
        ('#include "sd_card.h"', "camera/SD/filesystem header"),
        ('#include "ffpy.h"', "camera/SD/filesystem header"),
        ('#include "ff.h"', "FatFs/disk-io header"),
        ("#include <a/b/diskio.h>", "FatFs/disk-io header"),
        ("int f_mount(void *fs);", "FatFs file API"),
        ("FIL f;", "FatFs type"),
        ("int disk_initialize(unsigned char p);", "FatFs disk-io driver entry"),
    ],
)
def test_purity_banned_tokens_rejected(
    purity_tree: PurityTree, statement: str, reason: str
) -> None:
    """Every banned class fails the scan, naming file:line and the matched
    text — one finding per line is enough to fail (exit 1)."""
    relative = purity_tree.add_probe(statement)
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    text = result.stdout + result.stderr
    assert "ERROR: portable core is not dependency-free" in text
    assert "%s:3: forbidden %s" % (relative, reason) in text, text


def test_purity_one_finding_per_line(purity_tree: PurityTree) -> None:
    """Two banned tokens on ONE line produce exactly one finding (documented
    break): the fail-closed decision does not need exhaustive enumeration."""
    purity_tree.add_probe("FIL f; int disk_initialize(unsigned char p);")
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "(1 finding(s) in " in result.stdout + result.stderr


def test_purity_reports_every_poisoned_file(purity_tree: PurityTree) -> None:
    """The scan is not first-strike: all poisoned files are reported before
    the single exit-1."""
    first = purity_tree.add_probe("int nvs_open(const char *s);", "vdog_a.c")
    second = purity_tree.add_probe("int wifi_init(void);", "vdog_b.c")
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    text = result.stdout + result.stderr
    assert "(2 finding(s) in " in text
    assert "%s:3: forbidden NVS API symbol" % first in text
    assert "%s:3: forbidden Wi-Fi API symbol" % second in text


# ---------------------------------------------------------------------------
# check_core_purity.py — documented look-alike controls (must stay CLEAN)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "/* portable pure-C11 module */",
        "int printf(const char *fmt, ...);",
        "unsigned int DWORD = 2;",
        "const char *chip = \"esp32s3\";",
        '#include "buffer.h"',
        '#include "my_ff.h"',
        '#include "ffbuffer.h"',
        '#include "buffer_impl.h"',
        '#include "my_effective_settings.h"',
        "void my_rewind(void);",
    ],
    ids=[
        "portable-word",
        "stdio-printf",
        "generic-dword",
        "chip-name-literal",
        "buffer-h",
        "my-ff-h",
        "ffbuffer-h",
        "buffer-impl-h",
        "effective-settings-h",
        "rewind-not-f-rewind",
    ],
)
def test_purity_look_alikes_stay_clean(
    purity_tree: PurityTree, statement: str
) -> None:
    """PR-R7/PR-R10 basename-anchoring and the deliberate generic-typedef
    exclusions: these look-alikes must NOT be flagged (over-rejection would
    block legitimate portable-core words and stdio usage)."""
    purity_tree.add_probe(statement)
    result = purity_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_purity_u2028_smuggling_is_a_detection_superset(
    purity_tree: PurityTree,
) -> None:
    """PR-R15 decision pinned: str.splitlines() over-splitting catches a
    #include smuggled after U+2028 (one line to gcc, two split-lines to the
    scanner) — the deliberate SUPERSET over the compiler's line model."""
    purity_tree.add_probe("junk;\u2028#include <ff.h>")
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "forbidden FatFs/disk-io header" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# check_core_purity.py — scan modes, required sources and the usage contract
# ---------------------------------------------------------------------------


def test_purity_clean_fixture_scans_all_required_sources(
    purity_tree: PurityTree,
) -> None:
    result = purity_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert "5 portable-core files scanned" in result.stdout


def test_purity_subdirectory_findings_use_relative_paths(
    purity_tree: PurityTree,
) -> None:
    relative = purity_tree.add_probe("int nvs_open(const char *s);",
                                     "sub/nested.c")
    assert relative == "core/sub/nested.c"
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "core/sub/nested.c:3: forbidden NVS API symbol" in (
        result.stdout + result.stderr
    )


def test_purity_prunes_pio_and_build_gen_trees(purity_tree: PurityTree) -> None:
    """Generated trees are not core sources: a forbidden token inside
    .pio/ or build_gen/ must not fail the scan (documented pruning)."""
    purity_tree.add_probe("int nvs_open(const char *s);", ".pio/gen.c")
    purity_tree.add_probe("int wifi_init(void);", "build_gen/gen.h")
    result = purity_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_purity_extension_filter(purity_tree: PurityTree) -> None:
    """Non-source extensions are skipped; .json IS scanned (library.json is
    a required core source)."""
    purity_tree.add("notes.md", "int esp_camera_init(void);\n")
    result = purity_tree.run()
    assert result.returncode == 0, result.stdout + result.stderr
    purity_tree.add("library.json", '{ "comment": "esp_camera_init" }\n')
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "core/library.json:1: forbidden" in result.stdout + result.stderr


def test_purity_missing_core_directory_fails(purity_tree: PurityTree) -> None:
    shutil.rmtree(purity_tree.core)
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "portable core directory is missing" in result.stdout + result.stderr


@pytest.mark.parametrize("missing", ["vdog_core.h", "vdog_core.c",
                                     "vdog_board.h", "vdog_board.c",
                                     "library.json"])
def test_purity_missing_required_source_fails(purity_tree: PurityTree,
                                              missing: str) -> None:
    """The REQUIRED_FILES set is the gate's own floor — deleting any core
    source is a failure, not a smaller scan."""
    purity_tree.remove(missing)
    result = purity_tree.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "portable core source is missing" in result.stdout + result.stderr


def test_purity_usage_errors_exit_two(purity_tree: PurityTree) -> None:
    """CLI contract: no arguments; anything else is usage exit 2 (distinct
    from gate failure exit 1)."""
    result = purity_tree.run("--sdkconfig", "x")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "usage: check_core_purity.py (no arguments)" in result.stderr
    assert "ERROR" not in result.stderr



