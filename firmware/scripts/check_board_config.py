# vdog board-configuration gate (package 1.1; plan docs/plans/1.1-assignment.md
# §4.2). Build-time identity gate for the Seeed XIAO ESP32S3 prototype:
# after a successful build it re-reads the generated sdkconfig and asserts
# that every required key is PRESENT and EQUAL to the expected value, so no
# PSRAM/flash/console/partition setting can be silently inherited from a
# default (acceptance §7.3).
#
# Wiring: `extra_scripts = post:scripts/check_board_config.py` of
# [env:vdog_xiao_sense_proto] ONLY (same wiring style as
# scripts/gen_build_meta.py). Loading it in any other environment is a hard
# error, and the `native` environment must never load it.
#
# Thin by design: this script only READS the configuration and COMPARES it
# against the EXPECTED table below. The DECISION LOGIC (what "supported"
# means, missing-field vs wrong-value, which field is to blame) lives in the
# portable C validator, firmware/core/vdog_board.c — the single source of
# truth for semantics. Keep it that way.
#
# Timing model (PlatformIO Core 6.2.0 / espressif32 8.0.0): `post:` scripts
# are parsed BEFORE SCons executes any build action, so the check cannot run
# inline; it is registered as a build post action on the AlwaysBuild
# `checkprogsize` alias (fires on every successful default build, cache
# included) and on $BUILD_DIR/${PROGNAME}.bin (the last action of a default
# build), mirroring scripts/gen_build_meta.py. A failure calls env.Exit(1),
# which fails the build with a non-zero exit code.
#
# Test-build compatibility: `pio test` builds of this environment are
# redirected to .pio/build/vdog_xiao_sense_proto_test by the pre-script
# scripts/test_build_isolation.py, where config/sdkconfig.json may be absent
# or partial. This script therefore follows the SAME policy as
# gen_build_meta.py: it registers no gate for `__test`/`nobuild` command-line
# targets (and, defensively, for `clean`), and additionally never fails on a
# missing/partial sdkconfig inside a `*_test` build directory.
#
# `board` note: `board` is NOT an ESP-IDF sdkconfig key. The board identity is
# observed from the PlatformIO build environment ($BOARD, i.e. the
# `board = seeed_xiao_esp32s3` line of firmware/platformio.ini). If a fixture
# does carry a `board` key it is compared as well, so neither source can be
# silently wrong.
#
# Standalone (documented override, used by the negative demo in plan §5.4):
#   python3 firmware/scripts/check_board_config.py \
#       --sdkconfig <path-to-sdkconfig.json> --board <board-id>
# Exit codes: 0 = every required key present and equal; 1 = gate failure;
# 2 = usage / unreadable or malformed fixture.

import argparse
import json
import os
import sys

ENVIRONMENT = "vdog_xiao_sense_proto"
EXPECTED_BOARD = "seeed_xiao_esp32s3"
TEST_BUILD_SUFFIX = "_test"

# Skip the gate for these command-line targets (gen_build_meta.py policy).
SKIP_TARGETS = frozenset(("__test", "nobuild", "clean"))

# REQUIRED sdkconfig keys and their expected values. Absent key != default:
# absence is its own failure. Booleans are compared type-strictly so 1/"y"
# can never satisfy `True`.
EXPECTED_KEYS = (
    ("IDF_TARGET", "esp32s3"),
    ("ESPTOOLPY_FLASHSIZE_8MB", True),
    ("ESPTOOLPY_FLASHMODE_QIO", True),
    ("ESPTOOLPY_FLASHFREQ_80M", True),
    ("SPIRAM", True),
    ("SPIRAM_MODE_OCT", True),
    ("SPIRAM_SPEED_80M", True),
    ("PARTITION_TABLE_CUSTOM", True),
    ("PARTITION_TABLE_CUSTOM_FILENAME", "partitions/vdog_8mb_two_ota.csv"),
    ("ESP_CONSOLE_USB_CDC", True),
    ("ESP_CONSOLE_SECONDARY_NONE", True),
)

_PREFIX = "*** vdog board-config gate:"

# Set to the SCons environment when running under PlatformIO; None in
# standalone CLI mode (selects env.Exit(1) vs sys.exit(1)).
_SCONS_ENV = None


def _fail(message, code=1):
    sys.stderr.write("%s ERROR: %s\n" % (_PREFIX, message))
    sys.stderr.flush()
    if _SCONS_ENV is not None:
        _SCONS_ENV.Exit(code)
    sys.exit(code)


def _same(expected, actual):
    """Type-strict equality: True must not be satisfied by 1 or "y"."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, type(expected)) and actual == expected
    return type(actual) is type(expected) and actual == expected


def evaluate(config, observed_board):
    """Return a list of human-readable failures (empty list == gate passes).

    `config` is the parsed sdkconfig.json mapping; `observed_board` is the
    board id from the build environment (may be None when unavailable)."""
    failures = []

    if not isinstance(config, dict):
        return ["sdkconfig.json must contain a JSON object, got %s"
                % type(config).__name__]

    for key, expected in EXPECTED_KEYS:
        if key not in config:
            failures.append(
                "%s: expected %r but the key is ABSENT (never configured "
                "\u2014 absent is not a default)" % (key, expected)
            )
            continue
        actual = config[key]
        if not _same(expected, actual):
            failures.append(
                "%s: expected %r, got %r" % (key, expected, actual)
            )

    # Board identity: the sdkconfig fixture (if it carries one) AND the build
    # environment must both agree with the expected board id.
    observed = []
    if "board" in config:
        observed.append(("sdkconfig.json board key", config["board"]))
    observed.append(("build environment $BOARD", observed_board))
    for source, actual in observed:
        if not _same(EXPECTED_BOARD, actual):
            failures.append(
                "board (%s): expected %r, got %r" % (source, EXPECTED_BOARD,
                                                     actual)
            )
    return failures


def load_sdkconfig(path):
    if not os.path.isfile(path):
        _fail("cannot read sdkconfig: %s does not exist" % path)
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except OSError as exc:
        _fail("cannot read sdkconfig %s: %s" % (path, exc))
    except ValueError as exc:
        _fail("sdkconfig %s is not valid JSON: %s" % (path, exc))


def run_check(sdkconfig_path, observed_board, board_source):
    """Compare one generated sdkconfig against EXPECTED_KEYS; exit non-zero
    with the offending keys named on any mismatch."""
    config = load_sdkconfig(sdkconfig_path)
    failures = evaluate(config, observed_board)
    if failures:
        sys.stderr.write(
            "%s ERROR: build configuration rejected "
            "(%d problem(s), %s, board from %s):\n"
            % (_PREFIX, len(failures), sdkconfig_path, board_source)
        )
        for item in failures:
            sys.stderr.write("%s   - %s\n" % (_PREFIX, item))
        sys.stderr.flush()
        if _SCONS_ENV is not None:
            _SCONS_ENV.Exit(1)
        sys.exit(1)
    print(
        "vdog board-config gate: %d required keys present and equal + board=%s"
        " (%s)" % (len(EXPECTED_KEYS), EXPECTED_BOARD, sdkconfig_path)
    )
    return 0


# ---------------------------------------------------------------------------
# SCons / PlatformIO entry point
# ---------------------------------------------------------------------------

def _gate_action(source, target, env):  # SCons calls post actions with these
    build_dir = os.path.normpath(env.subst("$BUILD_DIR"))
    sdkconfig_path = os.path.join(build_dir, "config", "sdkconfig.json")
    board = env.subst("$BOARD") or None
    if not os.path.isfile(sdkconfig_path) and build_dir.endswith(
            TEST_BUILD_SUFFIX):
        # Defence in depth alongside the __test skip below: a redirected test
        # build (scripts/test_build_isolation.py) may legitimately have no or
        # a partial config, and the release gate must not fire there.
        print(
            "vdog board-config gate: skipped (test build dir %s has no "
            "config/sdkconfig.json)" % build_dir
        )
        return
    run_check(sdkconfig_path, board, "$BOARD of [env:%s]" % ENVIRONMENT)


def _scons_main():
    global _SCONS_ENV

    from SCons.Script import COMMAND_LINE_TARGETS

    Import("env")  # injected into module globals by SCons
    _SCONS_ENV = env

    if env.subst("$PIOENV") != ENVIRONMENT:
        _fail(
            "check_board_config.py may only be wired to [env:%s] (loaded in "
            "%r)" % (ENVIRONMENT, env.subst("$PIOENV"))
        )

    command_targets = set(COMMAND_LINE_TARGETS or [])
    skipped = command_targets & SKIP_TARGETS
    if skipped:
        # Same policy as scripts/gen_build_meta.py: test/nobuild/clean runs
        # never (re)validate the release configuration, so the redirected
        # `pio test` build directory can never break `pio test`.
        print(
            "vdog board-config gate: skipped (targets: %s)"
            % ", ".join(sorted(skipped))
        )
        return

    # Registered, not executed: see the timing model in the header.
    env.AddPostAction("checkprogsize", _gate_action)
    env.AddPostAction(env.subst("$BUILD_DIR/${PROGNAME}.bin"), _gate_action)


# ---------------------------------------------------------------------------
# Standalone entry point (documented override flag)
# ---------------------------------------------------------------------------

def _cli_main(argv):
    parser = argparse.ArgumentParser(
        prog="check_board_config.py",
        description="Compare a generated ESP-IDF sdkconfig.json against the "
                    "vdog %s expected board configuration." % ENVIRONMENT,
    )
    parser.add_argument("--sdkconfig", required=True,
                        help="path to a generated config/sdkconfig.json")
    parser.add_argument("--board", required=True,
                        help="board id to compare (PlatformIO board id, "
                             "e.g. seeed_xiao_esp32s3)")
    args = parser.parse_args(argv)
    return run_check(os.path.normpath(args.sdkconfig), args.board,
                     "--board argument")


if "Import" in globals():
    # Executed by SCons as an extra script.
    _scons_main()
else:
    # Plain interpreter: standalone/CLI mode.
    sys.exit(_cli_main(sys.argv[1:]))
