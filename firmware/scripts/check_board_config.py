# vdog board-configuration gate (package 1.1; plan docs/plans/1.1-assignment.md
# §4.2). Build-time identity gate for the Seeed XIAO ESP32S3 prototype.
#
# FOUR independent layers must all agree, because a resolved value alone can be
# an inherited SDK default or a stale compiled-in definition (PR-review round 2,
# findings PR-R1..PR-R3):
#
#  1. SOURCE DECLARATION — every required key must be EXPLICITLY declared in
#     firmware/sdkconfig.defaults on a line equal, CHARACTER FOR CHARACTER,
#     to `CONFIG_KEY=y` (lowercase; `Y`/`1` are parsed by Kconfig but
#     ignored, silently keeping the SDK default) or `CONFIG_KEY="value"`
#     (quotes required). Raw-line validation with NO trimming: any space
#     around `=` or in the value, or leading whitespace (the pinned parser
#     matches neither anchored regex and IGNORES such a line as malformed,
#     esp_kconfiglib core.py:1512-1513 — rejecting it fail-closed is the
#     faithful behaviour), counts as undeclared (PR-R5,
#     PR-R8). Assignments sourced by ESP-IDF's `# default:` provenance
#     pragma are NOT user selections and also count as undeclared --
#     mirroring the pinned esp_kconfiglib loader's `value_is_default`
#     machine exactly: pragma is `line.strip() == "# default:"` (no
#     expression suffix), the state persists across intervening
#     comments/blanks and is consumed by the next assignment (PR-R11,
#     corrected per PR-R13); assignments inside the auto-generated
#     `# Deprecated options ...` / `# End of ...` banners are skipped
#     by kconfgen's loader and are NOT declarations either (PR-R14).
#     Offending forms report "resolved value may be an SDK default".
#  2. RESOLVED PRESENT-AND-EQUAL — the generated config/sdkconfig.json holds
#     each required key with exactly the expected value (type-strict).
#  3. COMPONENT DEFINITIONS — components/vdog_board/CMakeLists.txt declares
#     VDOG_BOARD_ID_STR == expected board id and VDOG_BOARD_PSRAM_SIZE_BYTES
#     == expected 8 MiB, validated as COMPLETE tokens (PR-R6) over ALL
#     occurrences after comment stripping (PR-N1); every occurrence must sit
#     inside a target_compile_definitions() block scoped PRIVATE (PR-R9),
#     which together with the #error guards in vdog_board_idf.c provably
#     carries these definitions into the image (PR-R2).
#  4. EFFECTIVE PARTITION TABLE — PlatformIO's board_build.partitions, the
#     resolved CONFIG_PARTITION_TABLE_CUSTOM_FILENAME and the expected CSV are
#     the same file; any mismatch names all three (PR-R3).
#
# Wiring: `extra_scripts = post:scripts/check_board_config.py` of
# [env:vdog_xiao_sense_proto] ONLY (same wiring style as
# scripts/gen_build_meta.py). Loading it in any other environment is a hard
# error, and `native` must never load it.
#
# Thin by design: this script only READS configuration sources and COMPARES
# them against the EXPECTED table below (the single source of truth for
# expected values). The DECISION LOGIC (supported vs not, missing-field vs
# wrong-value, which field is to blame) lives in the portable C validator,
# firmware/core/vdog_board.c. Keep it that way.
#
# Timing model (PlatformIO Core 6.2.0 / espressif32 8.0.0): `post:` scripts are
# parsed BEFORE SCons executes any build action, so the check is registered as a
# build post action on the AlwaysBuild `checkprogsize` alias and on
# $BUILD_DIR/${PROGNAME}.bin, mirroring scripts/gen_build_meta.py. A failure
# calls env.Exit(1) and fails the build. Layers 1/3/4 read tracked sources, so
# they are enforced whenever the gate runs, not only after a link.
#
# Test-build compatibility: `pio test` builds are redirected to
# .pio/build/vdog_xiao_sense_proto_test by scripts/test_build_isolation.py,
# where config/sdkconfig.json may be absent or partial. Following
# gen_build_meta.py's policy, no gate is registered for `__test`/`nobuild`
# command-line targets (defensively also `clean`), and a missing/partial
# sdkconfig inside a `*_test` build directory never fails.
#
# `board` note: `board` is NOT an ESP-IDF sdkconfig key. Board identity is
# observed from three sources that must agree: the PlatformIO build environment
# ($BOARD), the compiled-in VDOG_BOARD_ID_STR, and EXPECTED_BOARD. A fixture
# carrying a `board` key is compared as well.
#
# Standalone (documented override flags; negative demo in plan §5.4 and the
# PR-R regression fixtures in plan §11):
#   python3 firmware/scripts/check_board_config.py \
#       --sdkconfig <generated sdkconfig.json> --board <board-id> \
#       [--defaults firmware/sdkconfig.defaults] \
#       [--component-cmake firmware/components/vdog_board/CMakeLists.txt] \
#       [--platformio-ini firmware/platformio.ini]
# Optional paths default to the real repository files, so tampered copies can
# be exercised without touching the repo.
# Exit codes: 0 = all layers agree; 1 = gate failure (undeclared/mismatched
# key, wrong board or component definition, partition disagreement, or an
# unreadable/malformed/missing input — a source that cannot be read is never a
# pass); 2 = argparse usage error only.
#
# Debug: VDOG_GATE_DEBUG=1 prints the candidate sources probed for the
# effective PlatformIO partition option (diagnostics only; no behaviour change).

import argparse
import json
import os
import re
import sys

ENVIRONMENT = "vdog_xiao_sense_proto"
EXPECTED_BOARD = "seeed_xiao_esp32s3"
EXPECTED_PSRAM_SIZE_BYTES = 8 * 1024 * 1024
TEST_BUILD_SUFFIX = "_test"

SKIP_TARGETS = frozenset(("__test", "nobuild", "clean"))

# REQUIRED keys and expected values (single source of truth). An absent
# resolved key is its own failure; booleans compare type-strictly so 1/"y" can
# never satisfy True. Every one of these must ALSO be declared in
# sdkconfig.defaults (layer 1).
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
EXPECTED_PARTITION_CSV = dict(EXPECTED_KEYS)["PARTITION_TABLE_CUSTOM_FILENAME"]

COMPONENT_CMAKE_RELPATH = os.path.join("components", "vdog_board",
                                       "CMakeLists.txt")

# Layer 3 captures the ENTIRE definition token (PR-R6): everything after '='
# up to whitespace or the closing paren. Validation is full-token, never a
# leading-prefix capture, so `=8388608u/2u` (the compiler receives the whole
# expression) cannot masquerade as the expected literal.
_COMPONENT_BOARD_RE = re.compile(r"VDOG_BOARD_ID_STR\s*=\s*([^\s)]+)")
_COMPONENT_PSRAM_RE = re.compile(
    r"VDOG_BOARD_PSRAM_SIZE_BYTES\s*=\s*([^\s)]+)")
# Full target_compile_definitions(...) blocks (post comment-strip) for the
# PRIVATE-scope provenance check (PR-R9); definition tokens never contain
# parentheses, so [^()]* safely captures a block body.
_COMPILE_DEFS_BLOCK_RE = re.compile(
    r"target_compile_definitions\s*\(([^()]*)\)", re.DOTALL)
# A complete unsigned-decimal literal with optional C integer suffixes.
_PSRAM_LITERAL_RE = re.compile(r"\A[0-9]+[uUlL]*\Z")
# CMake comments run from '#' to end of line (PR-N1): a commented-out
# definition must never count as a definition, in either direction.
_CMAKE_COMMENT_RE = re.compile(r"#.*")

_PREFIX = "*** vdog board-config gate:"

# firmware/ directory, resolved per mode. NEVER at import time: SCons runs
# extra scripts via ExecScript, where __file__ is undefined (same reason
# gen_build_meta.py avoids it). _scons_main() sets it from $PROJECT_DIR,
# _cli_main() from __file__.
FIRMWARE_DIR = None


def _firmware_dir_from_script():
    """Resolve firmware/ from the script location (CLI mode only)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_path(*parts):
    """Path inside firmware/; FIRMWARE_DIR must be resolved by the caller."""
    return os.path.join(FIRMWARE_DIR, *parts)


# Set to the SCons environment under PlatformIO; None in CLI mode (selects
# env.Exit(1) vs sys.exit(1)).
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


def _rel(path):
    """Repo-relative path for messages; absolute when outside firmware/."""
    if FIRMWARE_DIR is None:
        return os.path.abspath(path)
    absolute = os.path.abspath(path)
    if absolute == FIRMWARE_DIR or absolute.startswith(FIRMWARE_DIR + os.sep):
        return os.path.relpath(absolute, FIRMWARE_DIR)
    return absolute


def _read_text(path, label):
    if not os.path.isfile(path):
        _fail("cannot read %s: %s does not exist" % (label, path))
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return fp.read()
    except OSError as exc:
        _fail("cannot read %s %s: %s" % (label, path, exc))


def _norm_path(value):
    """Normalize a partition-table path for comparison."""
    if value is None:
        return None
    text = str(value).strip().strip("\"'").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


# ---------------------------------------------------------------------------
# Layer 1: source declarations in sdkconfig.defaults (PR-R1)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mirrors of the pinned parser's provenance state machine (PR-review round 7,
# PR-R13).  Authority: the Kconfig loader the pinned build ACTUALLY runs --
# ESP-IDF v6.1.0's `esp_kconfiglib` fork of kconfiglib (esp_idf_kconfig
# 3.13.0), installed at
#   ~/.platformio/penv/.espidf-6.1.0/lib/python3.12/site-packages/esp_kconfiglib/
# kconfgen drives it from the CMake configure step (framework-espidf
# tools/cmake/kconfig.cmake:211-212 `${python} -m kconfgen`, :230-237
# `--output json ${build}/config/sdkconfig.json`), so this is both the
# `# default:` semantics we must honour AND the tool that produced the
# layer-2 resolved sdkconfig.json.  All citations below are into that
# package (file:line as installed).
# ---------------------------------------------------------------------------

_KCONFIG_DEFAULT_PRAGMA = "# default:"  # esp_kconfiglib/constants.py:54
_KCONFIG_SET_RE = re.compile(r"\ACONFIG_([^=]+)=(.*)", re.ASCII)            # core.py:778 set_match
_KCONFIG_UNSET_RE = re.compile(r"\A# CONFIG_([^ ]+) is not set", re.ASCII)  # core.py:779 unset_match
_KCONFIG_DEP_BEGIN = "# Deprecated options for backward compatibility"       # constants.py:32
_KCONFIG_DEP_END = "# End of deprecated options"                              # constants.py:33


def last_raw_assignments(text):
    """{CONFIG_KEY: LAST raw assignment line, or None} -- a faithful mirror
    of the pinned parser's assignment-area state machine (PR-review round 7,
    PR-R13; deprecated-section handling added round 8, PR-R14).

    A value of None means "this mention is NOT an explicit user
    declaration"; it can never satisfy evaluate_source_declarations' exact
    match, and the standard 'not declared ... (resolved value may be an SDK
    default)' message reports it.

    MODE. The pinned loader reaches this machine through kconfgen's
    defaults-file loop -- kconfgen/core.py:559-569 calls
    `config.load_config(temp_file, replace=False)` WITHOUT load_deprecated,
    whose default is False (esp_kconfiglib/core.py:1151-1157; documented
    :1220; dispatched :1267 -> _load_config :1291). This function mirrors
    THAT mode; the load_deprecated=True paths (core.py:1420-1423,
    :1518-1521) are unreachable for sdkconfig.defaults files.

    The machine mirrors `value_is_default` and `in_deprecated_block` in
    esp_kconfiglib/core.py (Kconfig._load_config loop):

      * lines are rstrip()'d only (core.py:1398);
      * the flag is set iff a line equals the pragma EXACTLY after strip():
        `line.strip() == "# default:"` (core.py:1399-1402; pragma
        constants.py:54).  `# default: (some expr)`, `#  default:` and
        `#default:` are therefore ORDINARY comments and the assignment
        below them stays an explicit pin (the round-6 n2 expectation was
        wrong and is corrected);
      * the banner lines `# Deprecated options for backward compatibility`
        and `# End of deprecated options` (constants.py:32-33) toggle
        `in_deprecated_block` (core.py:1404-1411; init False :1351) AND
        clear the marker flag (:1406/:1410);
      * WHILE in the block (default mode), the loader skips EVERY line --
        `if in_deprecated_block and not load_deprecated: continue`
        (core.py:1413-1414).  Assignments there are never processed, so
        they are NOT user selections: never recorded here (an earlier
        outside record survives untouched), and they cannot consume the
        marker.  Edge behaviour, all parser-faithful: a marker before the
        opening banner is cleared by it (:1406) and one INSIDE the section
        (the marker test at :1399-1402 runs before the skip, so it does
        set the flag) is cleared by the closing banner (:1410) -- either
        way the first assignment AFTER `# End of deprecated options` is a
        user pin; an unclosed opening banner skips to EOF, because the
        loop-tail reset (:1610) clears only value_is_default, never
        in_deprecated_block (fail-closed, same as the parser);
      * the flag PERSISTS across comments, blank and malformed lines --
        they `continue` at core.py:1505-1514 without touching it -- so
        `# default:` + `# any comment` + `CONFIG_X=y` is still a
        default-sourced assignment (round 6's immediate-preceding-line
        check let this through: fail-open bypass);
      * the FIRST subsequent assignment (outside any deprecated section)
        consumes and clears the flag, on every code path: set lines
        (anchored `CONFIG_([^=]+)=`, core.py:778/1416) and `is not set`
        lines (core.py:779/1506) clear it at core.py:1422/1440/1444/1476/
        1500/1520/1539/1543/1552 and via the unconditional loop-tail reset
        at core.py:1610.

    Documented deviations from the parser, all STRICTER (fail-closed):
      * an `is not set` line records None for its key -- the parser's
        last-mention-wins resolves the symbol to unset there (core.py:1516
        ff.), so the key is certainly not an explicit pin once that line
        is the last mention (the repo file contains no such lines);
      * exact raw-line syntax (PR-R5/PR-R8) still decides declaredness: a
        set line the parser would accept loosely (`CONFIG_X =y`,
        `CONFIG_X=yes`) is recorded for last-wins bookkeeping but fails
        the exact match;
      * a leading-whitespace line matches neither anchored regex (the
        parser warns "ignoring malformed line", core.py:1512-1513, and
        the marker PERSISTS across it); we likewise never record such a
        line, so it stays fail-closed as before."""
    last = {}
    value_is_default = False       # core.py:1394
    in_deprecated_block = False    # core.py:1351
    for raw in text.splitlines():
        line = raw.rstrip()  # parser rstrips too: core.py:1398
        if line and line.strip() == _KCONFIG_DEFAULT_PRAGMA:  # core.py:1399-1402
            value_is_default = True
            continue
        if line and line.strip() == _KCONFIG_DEP_BEGIN:  # core.py:1404-1407
            in_deprecated_block = True
            value_is_default = False
            continue
        if line and line.strip() == _KCONFIG_DEP_END:  # core.py:1408-1411
            in_deprecated_block = False
            value_is_default = False
            continue
        if in_deprecated_block:
            # Default mode (load_deprecated=False): the loader skips every
            # line of the section (core.py:1413-1414) -- see docstring.
            continue
        m = _KCONFIG_SET_RE.match(line)  # core.py:1416, regex at :778
        if m:
            # Flag set => the parser records this as default-sourced, not
            # user-selected (core.py:1561/1577 ff.): never an explicit pin.
            last["CONFIG_" + m.group(1)] = None if value_is_default else line
            value_is_default = False  # consumes the marker: core.py:1610 et al.
            continue
        m = _KCONFIG_UNSET_RE.match(line)  # core.py:1506, regex at :779
        if m:
            last["CONFIG_" + m.group(1)] = None  # stricter: last mention unset
            value_is_default = False  # unset assignments consume too
            continue
        # comment / blank / malformed line: state PERSISTS (core.py:1505-1514)
    return last


def _required_declaration_line(key, expected):
    """The ONE assignment-line form that is honoured as written:
    `CONFIG_<KEY>=y|n` or `CONFIG_<KEY>="value"`.

    STRICT raw syntax (PR-R5 + PR-R8): no space before OR after `=`, no
    interior whitespace in the value, lowercase bool letter, double quotes
    required. Deliberate decision on leading whitespace: such a line
    matches neither anchored regex and the pinned parser ignores it as
    malformed ("ignoring malformed line",
    esp_kconfiglib core.py:1512-1513), so rejecting it fail-closed is the
    faithful behaviour (and the simplest exact rule; the repository file
    uses no leading whitespace) — documented here and in plan §10/§12.
    Anything else (uppercase `Y`, `=1`, `KEY= y`, `KEY =y`, …) behaves like
    an absent line and must be reported as undeclared."""
    if isinstance(expected, bool):
        value = "y" if expected else "n"
    else:
        value = '"%s"' % expected
    return "CONFIG_%s=%s" % (key, value)


def evaluate_source_declarations(defaults_path):
    """Every required key must be EXPLICITLY declared in sdkconfig.defaults
    on a line equal, CHARACTER FOR CHARACTER, to the only honoured form
    (strict; PR-R1 + PR-R5 + PR-R8).

    A key absent there — or present only in a form Kconfig ignores, such as
    `KEY=Y` or `KEY= y` (Kconfig reads these as no assignment and resolves
    the SDK default) — may simply be an ESP-IDF default, which acceptance
    §7.3 forbids; it is reported with the standard undeclared message."""
    last = last_raw_assignments(
        _read_text(defaults_path, "sdkconfig.defaults"))
    where = _rel(defaults_path)
    failures = []
    for key, expected in EXPECTED_KEYS:
        name = "CONFIG_%s" % key
        if last.get(name) != _required_declaration_line(key, expected):
            failures.append(
                "%s: not declared in %s (resolved value may be an SDK default)"
                % (name, where))
    return failures


# ---------------------------------------------------------------------------
# Layer 2: resolved sdkconfig.json present-and-equal + board identity
# ---------------------------------------------------------------------------

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


def evaluate_resolved(config, observed_board):
    """Failures for the resolved config and the build-environment board."""
    if not isinstance(config, dict):
        return ["sdkconfig.json must contain a JSON object, got %s"
                % type(config).__name__]

    failures = []
    for key, expected in EXPECTED_KEYS:
        if key not in config:
            failures.append(
                "%s: expected %r but the key is ABSENT (never configured "
                "\u2014 absent is not a default)" % (key, expected))
            continue
        actual = config[key]
        if not _same(expected, actual):
            failures.append("%s: expected %r, got %r" % (key, expected, actual))

    observed = []
    if "board" in config:
        observed.append(("sdkconfig.json board key", config["board"]))
    observed.append(("build environment $BOARD", observed_board))
    for source, actual in observed:
        if not _same(EXPECTED_BOARD, actual):
            failures.append("board (%s): expected %r, got %r"
                            % (source, EXPECTED_BOARD, actual))
    return failures


# ---------------------------------------------------------------------------
# Layer 3: component compile definitions actually built in (PR-R2)
# ---------------------------------------------------------------------------

def _block_scope(body):
    """None when the block is scoped PRIVATE; else a label for the problem
    (PR-review round 5, PR-R9; wording corrected in round 6, PR-R12).

    CMake semantics: PRIVATE applies definitions to the target's OWN
    compilation only (our policy: definitions stay local to the component
    that consumes them); PUBLIC applies to the target AND its consumers;
    INTERFACE applies to CONSUMERS ONLY. All three non-PRIVATE scopes are
    rejected by this check: the adapter must receive the macros via its OWN
    compilation, and only PRIVATE keeps that fact local to the consuming
    component — the compile-time backstop for "did the macros actually
    arrive" is the #error guard in vdog_board_idf.c regardless of scope."""
    if re.search(r"\bINTERFACE\b", body):
        return "INTERFACE"
    if re.search(r"\bPUBLIC\b", body):
        return "PUBLIC"
    if not re.search(r"\bPRIVATE\b", body):
        return "no PRIVATE keyword"
    return None


def evaluate_component_definitions(cmake_path):
    """EVERY definition in the component CMakeLists.txt must equal EXPECTED.

    Matching happens after CMake comments (# ... EOL) are stripped, and every
    occurrence is checked (finditer), not just the first: CMake/the compiler
    ultimately take the LAST -D definition, so a second tampered block must
    never hide behind a correct first one (PR-review round 3, PR-N1). Each
    occurrence is validated as a COMPLETE token (PR-review round 4, PR-R6):
    the board id token must be exactly "seeed_xiao_esp32s3" (quotes part of
    the token), the PSRAM token must be a full unsigned-decimal literal
    (optional u/l suffixes) equal to the expected capacity — a partial
    capture of an expression like 8388608u/2u (which the compiler receives
    in full) is never accepted. Finally, each occurrence must sit inside a
    target_compile_definitions() block scoped PRIVATE (PR-R9; CMake
    semantics per PR-R12: PRIVATE = target's own compilation only — our
    policy, definitions stay local to the consuming component; PUBLIC =
    target AND consumers, rejected as scope creep; INTERFACE = consumers
    only, rejected because our own compilation would lose the -D while the
    literals stay in the file). Definitions outside any such block (e.g.
    smuggled through set()) never reach the compiler at all. Either way
    the structural backstop is the #error guard in vdog_board_idf.c."""
    text = _CMAKE_COMMENT_RE.sub("", _read_text(cmake_path,
                                                "component CMakeLists.txt"))
    where = _rel(cmake_path)
    failures = []

    blocks = [(m.start(), m.end(), m.group(1))
              for m in _COMPILE_DEFS_BLOCK_RE.finditer(text)]

    def _check_provenance(name, matches):
        seen_bodies = []
        outside = 0
        for m in matches:
            body = None
            for start, end, block_body in blocks:
                if start < m.start() < end:
                    body = block_body
                    break
            if body is None:
                outside += 1
            elif body not in seen_bodies:
                seen_bodies.append(body)
        if outside:
            failures.append(
                "%s (%s): %d occurrence(s) outside any "
                "target_compile_definitions() block (compile-flag provenance "
                "unverified; these must be PRIVATE compile definitions)"
                % (name, where, outside))
        for body in seen_bodies:
            scope = _block_scope(body)
            if scope is not None:
                failures.append(
                    "%s (%s): target_compile_definitions() must be scoped "
                    "PRIVATE, found %s in block %r"
                    % (name, where, scope, " ".join(body.split())))

    board_ms = list(_COMPONENT_BOARD_RE.finditer(text))
    board_token = '"%s"' % EXPECTED_BOARD
    board_values = [m.group(1) for m in board_ms]
    if not board_values:
        failures.append(
            "VDOG_BOARD_ID_STR: not defined in %s (the image would carry no "
            "board id; expected %r)" % (where, board_token))
    else:
        wrong = [v for v in board_values if v != board_token]
        if wrong:
            failures.append(
                "VDOG_BOARD_ID_STR (%s): expected %r, got %r (%d "
                "occurrence(s), %d wrong)" % (where, board_token, wrong[0],
                                              len(board_values), len(wrong)))
        _check_provenance("VDOG_BOARD_ID_STR", board_ms)

    psram_ms = list(_COMPONENT_PSRAM_RE.finditer(text))
    psram_tokens = [m.group(1) for m in psram_ms]
    if not psram_tokens:
        failures.append("VDOG_BOARD_PSRAM_SIZE_BYTES: not defined in %s "
                        "(expected %d)" % (where, EXPECTED_PSRAM_SIZE_BYTES))
    else:
        def _psram_ok(token):
            return (_PSRAM_LITERAL_RE.match(token)
                    and int(re.sub(r"[uUlL]", "", token))
                    == EXPECTED_PSRAM_SIZE_BYTES)
        wrong = [t for t in psram_tokens if not _psram_ok(t)]
        if wrong:
            detail = ""
            if not _PSRAM_LITERAL_RE.match(wrong[0]):
                detail = ("; not a complete unsigned-decimal literal "
                          "(expression characters are passed to the "
                          "compiler verbatim)")
            failures.append(
                "VDOG_BOARD_PSRAM_SIZE_BYTES (%s): expected %d, got %r%s "
                "(%d occurrence(s), %d wrong)"
                % (where, EXPECTED_PSRAM_SIZE_BYTES, wrong[0], detail,
                   len(psram_tokens), len(wrong)))
        _check_provenance("VDOG_BOARD_PSRAM_SIZE_BYTES", psram_ms)
    return failures


# ---------------------------------------------------------------------------
# Layer 4: effective partition table agreement across the three sources (R3)
# ---------------------------------------------------------------------------

def parse_platformio_partitions(text, environment=ENVIRONMENT):
    """board_build.partitions of [env:<environment>] in platformio.ini text."""
    section = "env:%s" % environment
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = (line[1:-1].strip() == section)
            continue
        if not inside or not line or line[0] in ";#":
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == "board_build.partitions":
                return value.strip()
    return None


def platformio_partitions_from_env(env):
    """(label, value) for the effective board_build.partitions option.

    Tries the PlatformIO project-option accessor first, then the merged
    BOARD_BUILD board-manifest dict, then the ini file on disk."""
    candidates = []
    try:
        candidates.append(("platformio.ini [env:%s] board_build.partitions "
                           "(GetProjectOption)" % ENVIRONMENT,
                           env.GetProjectOption("board_build.partitions",
                                                None)))
    except Exception:  # pragma: no cover - defensive: API availability
        pass
    board_build = env.get("BOARD_BUILD") or {}
    if isinstance(board_build, dict):
        candidates.append(("BOARD_BUILD['partitions']",
                           board_build.get("partitions")))
    ini_path = os.path.join(os.path.normpath(env.subst("$PROJECT_DIR")),
                            "platformio.ini")
    if os.path.isfile(ini_path):
        candidates.append(("parsed %s" % _rel(ini_path),
                           parse_platformio_partitions(
                               _read_text(ini_path, "platformio.ini"))))
    if os.environ.get("VDOG_GATE_DEBUG"):
        sys.stderr.write("%s debug: partition candidates %r\n"
                         % (_PREFIX, [(label, value)
                                       for label, value in candidates]))
        sys.stderr.flush()
    for label, value in candidates:
        if value:
            return (label, str(value))
    return ("no board_build.partitions found", None)


def evaluate_partitions(partition_sources, resolved_config):
    """platformio option vs resolved filename vs expected CSV (PR-R3)."""
    resolved = None
    if isinstance(resolved_config, dict):
        resolved = resolved_config.get("PARTITION_TABLE_CUSTOM_FILENAME")
    wanted = _norm_path(EXPECTED_PARTITION_CSV)
    failures = []
    for label, value in list(partition_sources):
        if _norm_path(value) != wanted:
            failures.append(
                "partition table mismatch: %s = %r | resolved "
                "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME = %r | expected = %r"
                % (label, value, resolved, EXPECTED_PARTITION_CSV))
    if _norm_path(resolved) != wanted:
        failures.append(
            "partition table mismatch: resolved "
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME = %r | expected = %r "
            "(PlatformIO option must agree too)" % (resolved,
                                                    EXPECTED_PARTITION_CSV))
    return failures


# ---------------------------------------------------------------------------
# Combined check + reporting
# ---------------------------------------------------------------------------

def collect_failures(sdkconfig_path, observed_board, defaults_path,
                     component_cmake_path, partition_sources):
    config = load_sdkconfig(sdkconfig_path)
    failures = []
    failures.extend(evaluate_source_declarations(defaults_path))
    failures.extend(evaluate_resolved(config, observed_board))
    failures.extend(evaluate_component_definitions(component_cmake_path))
    failures.extend(evaluate_partitions(partition_sources, config))
    return config, failures


def _reject(failures, context):
    sys.stderr.write(
        "%s ERROR: build configuration rejected (%d problem(s), %s):\n"
        % (_PREFIX, len(failures), context))
    for item in failures:
        sys.stderr.write("%s   - %s\n" % (_PREFIX, item))
    sys.stderr.flush()
    if _SCONS_ENV is not None:
        _SCONS_ENV.Exit(1)
    sys.exit(1)


def run_check(sdkconfig_path, observed_board, board_source, defaults_path,
              component_cmake_path, partition_sources):
    """Run all four layers; exit non-zero naming every problem."""
    config, failures = collect_failures(
        sdkconfig_path, observed_board, defaults_path, component_cmake_path,
        partition_sources)
    if failures:
        _reject(failures, "%s; board from %s; declarations from %s; component "
                         "definitions from %s"
                % (sdkconfig_path, board_source, _rel(defaults_path),
                   _rel(component_cmake_path)))
    print(
        "vdog board-config gate: %d keys declared in sdkconfig.defaults and "
        "present-and-equal in the resolved config, board=%s (env + component "
        "definition), partition table %s agreed by all three sources (%s)"
        % (len(EXPECTED_KEYS), EXPECTED_BOARD, EXPECTED_PARTITION_CSV,
           sdkconfig_path))
    return 0


# ---------------------------------------------------------------------------
# SCons / PlatformIO entry point
# ---------------------------------------------------------------------------

def _gate_action(source, target, env):  # SCons calls post actions with these
    build_dir = os.path.normpath(env.subst("$BUILD_DIR"))
    sdkconfig_path = os.path.join(build_dir, "config", "sdkconfig.json")
    board = env.subst("$BOARD") or None
    partition_sources = [platformio_partitions_from_env(env)]
    if not os.path.isfile(sdkconfig_path) and build_dir.endswith(
            TEST_BUILD_SUFFIX):
        # Defence in depth alongside the __test skip: a redirected test build
        # may legitimately lack a config, and the release gate must not fire.
        print("vdog board-config gate: skipped (test build dir %s has no "
              "config/sdkconfig.json)" % build_dir)
        return
    run_check(sdkconfig_path, board, "$BOARD of [env:%s]" % ENVIRONMENT,
              _repo_path("sdkconfig.defaults"),
              _repo_path(COMPONENT_CMAKE_RELPATH), partition_sources)


def _scons_main():
    global _SCONS_ENV, FIRMWARE_DIR

    from SCons.Script import COMMAND_LINE_TARGETS

    Import("env")  # injected into module globals by SCons
    _SCONS_ENV = env
    FIRMWARE_DIR = os.path.normpath(env.subst("$PROJECT_DIR"))

    if env.subst("$PIOENV") != ENVIRONMENT:
        _fail("check_board_config.py may only be wired to [env:%s] (loaded in "
              "%r)" % (ENVIRONMENT, env.subst("$PIOENV")))

    command_targets = set(COMMAND_LINE_TARGETS or [])
    skipped = command_targets & SKIP_TARGETS
    if skipped:
        # gen_build_meta.py policy: test/nobuild/clean runs never (re)validate
        # the release configuration, so `pio test` cannot be broken by it.
        print("vdog board-config gate: skipped (targets: %s)"
              % ", ".join(sorted(skipped)))
        return

    # Registered, not executed: see the timing model in the header.
    env.AddPostAction("checkprogsize", _gate_action)
    env.AddPostAction(env.subst("$BUILD_DIR/${PROGNAME}.bin"), _gate_action)


# ---------------------------------------------------------------------------
# Standalone entry point (documented override flags)
# ---------------------------------------------------------------------------

def _cli_main(argv):
    global FIRMWARE_DIR
    FIRMWARE_DIR = _firmware_dir_from_script()

    parser = argparse.ArgumentParser(
        prog="check_board_config.py",
        description="Compare a generated ESP-IDF sdkconfig.json, "
                    "sdkconfig.defaults, the vdog_board component "
                    "definitions and platformio.ini against the vdog %s "
                    "expected board configuration." % ENVIRONMENT)
    parser.add_argument("--sdkconfig", required=True,
                        help="path to a generated config/sdkconfig.json")
    parser.add_argument("--board", required=True,
                        help="board id to compare (PlatformIO board id, "
                             "e.g. seeed_xiao_esp32s3)")
    parser.add_argument("--defaults", default=_repo_path("sdkconfig.defaults"),
                        help="sdkconfig.defaults to require declarations from "
                             "(default: the repository file)")
    parser.add_argument("--component-cmake",
                        default=_repo_path(COMPONENT_CMAKE_RELPATH),
                        help="vdog_board component CMakeLists.txt to check "
                             "compile definitions against (default: the "
                             "repository file)")
    parser.add_argument("--platformio-ini", default=_repo_path("platformio.ini"),
                        help="platformio.ini to read the effective "
                             "board_build.partitions from (default: the "
                             "repository file)")
    args = parser.parse_args(argv)

    ini_path = os.path.normpath(args.platformio_ini)
    partition_value = parse_platformio_partitions(
        _read_text(ini_path, "platformio.ini"))
    return run_check(
        os.path.normpath(args.sdkconfig), args.board, "--board argument",
        os.path.normpath(args.defaults),
        os.path.normpath(args.component_cmake),
        [("platformio.ini [%s] board_build.partitions"
          % ("env:" + ENVIRONMENT), partition_value)])


if "Import" in globals():
    # Executed by SCons as an extra script.
    _scons_main()
else:
    # Plain interpreter: standalone/CLI mode.
    sys.exit(_cli_main(sys.argv[1:]))
