# vdog portable-core purity gate (package 1.1; plan
# docs/plans/1.1-assignment.md §4.2). Mechanical proof that the portable core
# in firmware/core/ stays free of camera, SD, radio, RTOS and SDK headers, so
# the identical sources keep building in the host `native` test environment
# (acceptance §7.4: "camera/SD separation holds").
#
# Wiring: `extra_scripts = post:scripts/check_core_purity.py` of
# [env:vdog_xiao_sense_proto] ONLY (same wiring style as
# scripts/gen_build_meta.py). Loading it in any other environment is a hard
# error, and the `native` environment must never load it. Unlike the
# board-config gate this one reads only tracked sources, so it runs at script
# parse time (before any compilation) and on every target, including `pio
# test` build-only runs and `clean`.
#
# It scans every C/C++ (and JSON) file under firmware/core/ for forbidden
# tokens and fails the build naming file:line and the matched text. Adding a
# dependency to core/ is therefore a visible, reviewable decision, not an
# accident.
#
# Standalone (same result as the build-time run):
#   python3 firmware/scripts/check_core_purity.py
# Exit codes: 0 = clean; 1 = forbidden token found / core sources missing.

import os
import re
import sys

ENVIRONMENT = "vdog_xiao_sense_proto"
SOURCE_EXTENSIONS = frozenset((
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".in", ".json",
))
# The sources the portable core must actually consist of.
REQUIRED_FILES = (
    "vdog_core.h", "vdog_core.c", "vdog_board.h", "vdog_board.c",
    "library.json",
)

# (pattern, why it is forbidden). Matching is case-insensitive.
FORBIDDEN = (
    (re.compile(r"\besp_[a-z0-9_]+", re.IGNORECASE),
     "SDK API/symbol prefix (esp_*)"),
    (re.compile(r"\bespidf\b", re.IGNORECASE), "SDK token (espidf)"),
    # NOTE: the bare chip-name STRING (VDOG_BOARD_EXPECTED_TARGET_NAME
    # "esp32s3") is legitimate portable profile DATA, so only SDK symbols and
    # headers below are forbidden, not that literal.
    (re.compile(r"\besp_camera\b|\bcamera_", re.IGNORECASE),
     "camera driver symbol"),
    (re.compile(r"\bsdmmc[a-z0-9_]*\b", re.IGNORECASE),
     "SD/MMC host driver symbol"),
    (re.compile(r"\bsdspi[a-z0-9_]*\b", re.IGNORECASE),
     "SPI-SD driver symbol"),
    (re.compile(r"\bnvs[a-z0-9_]*\b", re.IGNORECASE), "NVS API symbol"),
    (re.compile(r"\bfreertos\b|\btaskhandle\b|\bvTask[A-Za-z]", re.IGNORECASE),
     "RTOS symbol"),
    # Case-SENSITIVE on purpose: these are FreeRTOS identifier shapes. A
    # case-insensitive read would false-positive on ordinary words such as
    # "portable" (the core is described as portable throughout).
    (re.compile(r"\bxTask[A-Za-z0-9_]*\b|\bxQueue[A-Za-z0-9_]*\b|"
                r"\bxSemaphore[A-Za-z0-9_]*\b|\bpd[A-Z][A-Za-z0-9_]*\b|"
                r"\bport[A-Z][A-Za-z0-9_]*\b|\bTickType_t\b"),
     "FreeRTOS kernel API/type symbol (xTask*/xQueue*/xSemaphore*/pd*/port*/"
     "TickType_t)"),
    # FatFs / disk-io layer (PR-review round 2, PR-R4). Also case-SENSITIVE,
    # and deliberately limited to FatFs-specific identifiers: the generic
    # FatFs typedefs BYTE/WORD/DWORD/UINT/WCHAR (and DIR) are ordinary words or
    # collide with stdio usage, so they are NOT in this list — "FILE",
    # "portable" and similar must keep scanning clean. Directory access is
    # covered by f_opendir/f_readdir instead of the bare DIR type.
    (re.compile(
        r"#[ \t]*include[ \t]*[<\"][^\">]*"
        r"(?:ff|ffconf|diskio|integer|ccsbcs)[a-z0-9_/]*\.h"
        r"[\">]", re.IGNORECASE),
     "FatFs/disk-io header (ff.h, ffconf.h, diskio.h)"),
    (re.compile(
        r"\bf_(?:mount|open|read|write|close|mkfs|opendir|readdir|unlink|"
        r"rename|stat|getfree|chmod|chdir|mkdir|sync|lseek|tell|eof|forward|"
        r"truncate|expand|getlabel|setlabel|puts|gets|putc|getc)\b"),
     "FatFs file API (f_mount/f_open/f_read/f_write/f_close/f_mkfs/"
     "f_opendir/...)"),
    (re.compile(r"\b(?:FIL|FILINFO|FATFS|FRESULT)\b"),
     "FatFs type (FIL/FILINFO/FATFS/FRESULT)"),
    (re.compile(r"\bdisk_(?:initialize|status|read|write|ioctl)\b"),
     "FatFs disk-io driver entry (disk_initialize/disk_read/disk_write/"
     "disk_ioctl)"),
    (re.compile(r"\bwifi[a-z0-9_]*\b", re.IGNORECASE), "Wi-Fi API symbol"),
    (re.compile(r"\barduino\b", re.IGNORECASE), "Arduino framework token"),
    (re.compile(
        r"#[ \t]*include[ \t]*[<\"][^\">]*"
        r"(?:esp[_\-]|espidf|esp32|freertos|sdmmc|sdspi|nvs|driver/|soc/|"
        r"hal/|rom/|lwip/|wifi|task\.h|queue\.h|semphr\.h|event_groups\.h|"
        r"timers\.h|FreeRTOS)"
        r"[^\">]*[\">]",
        re.IGNORECASE),
     "SDK/RTOS/system header"),
    (re.compile(r"#[ \t]*include[ \t]*[<\"][^\">]*(?:camera|sd_card|ffs?[py]|"
                r"esp_vfs)[^\">]*[\">]", re.IGNORECASE),
     "camera/SD/filesystem header"),
)

_PREFIX = "*** vdog core-purity:"

# Set to the SCons environment when running under PlatformIO.
_SCONS_ENV = None


def _fail(message):
    sys.stderr.write("%s ERROR: %s\n" % (_PREFIX, message))
    sys.stderr.flush()
    if _SCONS_ENV is not None:
        _SCONS_ENV.Exit(1)
    sys.exit(1)


def _scan_file(path, relative):
    """Return a list of "relative:line: reason -> text" findings."""
    findings = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except OSError as exc:
        _fail("cannot read %s: %s" % (relative, exc))
        return findings
    for number, text in enumerate(lines, start=1):
        for pattern, reason in FORBIDDEN:
            match = pattern.search(text)
            if match:
                findings.append(
                    "%s:%d: forbidden %s -> %s"
                    % (relative, number, reason, match.group(0).strip())
                )
                break  # one finding per line is enough to fail
    return findings


def check(core_dir):
    """Scan core_dir; return (scanned_files, findings)."""
    if not os.path.isdir(core_dir):
        _fail("portable core directory is missing: %s" % core_dir)

    for name in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(core_dir, name)):
            _fail("portable core source is missing: %s"
                  % os.path.join(core_dir, name))

    scanned = []
    findings = []
    for root, dirs, files in os.walk(core_dir):
        dirs[:] = sorted(d for d in dirs if d not in (".pio", "build_gen"))
        for name in sorted(files):
            if os.path.splitext(name)[1] not in SOURCE_EXTENSIONS:
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, os.path.dirname(core_dir))
            scanned.append(relative)
            findings.extend(_scan_file(path, relative))
    return scanned, findings


def _scons_main():
    global _SCONS_ENV

    Import("env")  # injected into module globals by SCons
    _SCONS_ENV = env

    if env.subst("$PIOENV") != ENVIRONMENT:
        _fail(
            "check_core_purity.py may only be wired to [env:%s] (loaded in "
            "%r)" % (ENVIRONMENT, env.subst("$PIOENV"))
        )
    core_dir = os.path.join(os.path.normpath(env.subst("$PROJECT_DIR")),
                            "core")
    scanned, findings = check(core_dir)
    if findings:
        sys.stderr.write(
            "%s ERROR: portable core is not dependency-free "
            "(%d finding(s) in %s):\n" % (_PREFIX, len(findings), core_dir)
        )
        for item in findings:
            sys.stderr.write("%s   - %s\n" % (_PREFIX, item))
        sys.stderr.flush()
        _SCONS_ENV.Exit(1)
    print(
        "vdog core-purity gate: %d portable-core files scanned, no "
        "camera/SD/RTOS/SDK tokens" % len(scanned)
    )


def _cli_main(argv):
    if argv:
        sys.stderr.write("usage: check_core_purity.py (no arguments)\n")
        return 2
    core_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
    scanned, findings = check(core_dir)
    if findings:
        sys.stderr.write(
            "%s ERROR: portable core is not dependency-free "
            "(%d finding(s) in %s):\n" % (_PREFIX, len(findings), core_dir)
        )
        for item in findings:
            sys.stderr.write("%s   - %s\n" % (_PREFIX, item))
        return 1
    print(
        "vdog core-purity gate: %d portable-core files scanned, no "
        "camera/SD/RTOS/SDK tokens" % len(scanned)
    )
    return 0


if "Import" in globals():
    # Executed by SCons as an extra script.
    _scons_main()
else:
    # Plain interpreter: standalone mode.
    sys.exit(_cli_main(sys.argv[1:]))
