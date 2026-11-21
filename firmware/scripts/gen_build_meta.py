# vdog build-identity generator (Stage 0.9 packet A; master plan 0.9.2
# firmware side, contract: docs/plans/0.9-round1-assignment.md).
#
# Wired EXCLUSIVELY as `extra_scripts = post:scripts/gen_build_meta.py` of
# [env:vdog_xiao_sense_proto] in platformio.ini. The `native` environment must
# never load this script (it hard-fails if wired anywhere else).
#
# Timing model (PlatformIO Core 6.2.0 / espressif32 8.0.0):
#   - `post:` scripts are parsed AFTER the main build script but still BEFORE
#     SCons executes any build action. The generated header is therefore
#     written here at parse time, so the IDF "main" component (src/main.c)
#     always sees a fresh firmware/build_gen/vdog_build_id.h during
#     compilation, even on a clean build.
#   - The vdog-build-metadata-v1 JSON is written by an AddPostAction on the
#     application image, so it is (re)generated only at the end of a
#     SUCCESSFUL normal build. `pio test` (`__test` targets) and `nobuild`
#     never (re)write it, keeping the release artifact's identity tied to a
#     successful normal `pio run`.
#
# Input handling contract (hard requirements):
#   - VDOG_SOURCE_SHA: accepted only as a full 40-hex object ID; any other
#     non-empty value is a hard build failure. Unset/empty => "local".
#   - VDOG_BUILD_ID: accepted only as [A-Za-z0-9._-]{1,64}; anything else is
#     a hard build failure. Unset/empty => "local".
#   - No environment value is ever emitted raw as C-preprocessor or shell
#     text: every emitted token is re-validated against the safe character
#     class immediately before writing, and any violation aborts generation.

import json
import os
import re
import sys

from SCons.Script import COMMAND_LINE_TARGETS

Import("env")

PROJECT_DIR = os.path.normpath(env.subst("$PROJECT_DIR"))
BUILD_GEN_DIR = os.path.join(PROJECT_DIR, "build_gen")
HEADER_PATH = os.path.join(BUILD_GEN_DIR, "vdog_build_id.h")
METADATA_PATH = os.path.join(PROJECT_DIR, ".vdog-build-metadata.json")
CORE_HEADER_PATH = os.path.join(PROJECT_DIR, "core", "vdog_core.h")

# vdog-build-metadata-v1 contract constants (0.9 round-1 assignment).
SCHEMA = "vdog-build-metadata-v1"
ENVIRONMENT = "vdog_xiao_sense_proto"
EXPECTED_PLATFORM = "platformio/espressif32@8.0.0"
EXPECTED_PLATFORM_VERSION = "8.0.0"
IDF_VERSION = "v6.1.0"
EXPECTED_ESPIDF_PACKAGE = "4.60100.0"  # framework-espidf pin resolving to IDF v6.1.0
ESPTOOL_VERSION = "5.4.0"
EXPECTED_ESPTOOL_PACKAGE = "2.50400.0"  # tool-esptool pin resolving to esptool 5.4.0
EXPECTED_VERSION = "0.2.0-proto"  # must match core/vdog_core.h

_FULL_SHA_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")
_BUILD_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
_SHA12_RE = re.compile(r"\A[0-9a-fA-F]{12}\Z")
# Single safe class for every token emitted into C or JSON: no quotes,
# backslashes, whitespace, %, $ or control characters can ever reach a
# preprocessor token or a shell.
_SAFE_EMIT_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


def _fail(message):
    # repr() of a bounded slice: never echo unbounded raw environment text.
    sys.stderr.write("*** vdog build-metadata: ERROR: %s\n" % message)
    sys.stderr.flush()
    env.Exit(1)


def _safe_input_desc(raw):
    return "length=%d repr=%r" % (len(raw), raw[:80])


def _validated_identity():
    """Return (source_sha, build_id) or hard-fail the build."""
    raw_sha = os.environ.get("VDOG_SOURCE_SHA", "")
    if raw_sha == "":
        source_sha = "local"
    elif _FULL_SHA_RE.match(raw_sha):
        source_sha = raw_sha
    else:
        _fail(
            "VDOG_SOURCE_SHA must be a full 40-hex object ID (got %s)"
            % _safe_input_desc(raw_sha)
        )

    raw_id = os.environ.get("VDOG_BUILD_ID", "")
    if raw_id == "":
        build_id = "local"
    elif _BUILD_ID_RE.match(raw_id):
        build_id = raw_id
    else:
        _fail(
            "VDOG_BUILD_ID must match [A-Za-z0-9._-]{1,64} (got %s)"
            % _safe_input_desc(raw_id)
        )
    return source_sha, build_id


def _checked_emit_token(token, name):
    """Last line of defense before emitting a token into C/JSON."""
    if not _SAFE_EMIT_RE.match(token):
        _fail(
            "refusing to emit %s: characters outside the validated set" % name
        )
    return token


def _source_sha_short(source_sha):
    if source_sha == "local":
        return "local"
    short = source_sha[:12]
    if not _SHA12_RE.match(short):
        _fail("VDOG_SOURCE_SHA_SHORT derivation did not yield 12 hex chars")
    return short


def _firmware_version_from_core_header():
    """Read MAJOR.MINOR.PATCH-SUFFIX from core/vdog_core.h and require it to
    match the frozen contract value."""
    try:
        with open(CORE_HEADER_PATH, "r", encoding="utf-8") as fp:
            text = fp.read()
    except OSError as exc:
        _fail("cannot read %s: %s" % (CORE_HEADER_PATH, exc))

    def _define_value(pattern, label):
        match = re.search(pattern, text)
        if not match:
            _fail("cannot find %s in core/vdog_core.h" % label)
        return match.group(1)

    major = _define_value(r"#\s*define\s+VDOG_VERSION_MAJOR\s+(\d+)u?\b",
                          "VDOG_VERSION_MAJOR")
    minor = _define_value(r"#\s*define\s+VDOG_VERSION_MINOR\s+(\d+)u?\b",
                          "VDOG_VERSION_MINOR")
    patch = _define_value(r"#\s*define\s+VDOG_VERSION_PATCH\s+(\d+)u?\b",
                          "VDOG_VERSION_PATCH")
    suffix = _define_value(
        r'#\s*define\s+VDOG_VERSION_SUFFIX\s+"([^"]*)"', "VDOG_VERSION_SUFFIX"
    )
    version = "%s.%s.%s-%s" % (major, minor, patch, suffix)
    if version != EXPECTED_VERSION:
        _fail(
            "core/vdog_core.h reports %r but the metadata contract pins %r"
            % (version, EXPECTED_VERSION)
        )
    return version


def _check_toolchain_pins():
    """Guard against platformio.ini package pins drifting away from the
    constants published in the metadata JSON."""
    try:
        platform = env.PioPlatform()
    except Exception as exc:  # defensive: metadata must not lie silently
        _fail("cannot inspect the resolved platform: %s" % exc)

    if not str(platform.name).endswith("espressif32") or (
        str(platform.version) != EXPECTED_PLATFORM_VERSION
    ):
        _fail(
            "resolved platform %s@%s does not match %s"
            % (platform.name, platform.version, EXPECTED_PLATFORM)
        )

    for package, expected, label in (
        ("framework-espidf", EXPECTED_ESPIDF_PACKAGE, "idf_version=%s" % IDF_VERSION),
        ("tool-esptool", EXPECTED_ESPTOOL_PACKAGE, "esptool_version=%s" % ESPTOOL_VERSION),
    ):
        resolved = platform.get_package_version(package)
        if resolved != expected:
            _fail(
                "%s resolved to %r but metadata declares %s"
                % (package, resolved, label)
            )


def _metadata_payload():
    source_sha, build_id = _validated_identity()
    version = _firmware_version_from_core_header()
    _check_toolchain_pins()
    return {
        "schema": SCHEMA,
        "firmware_version": version,
        "source_sha": source_sha,
        "build_id": build_id,
        "environment": ENVIRONMENT,
        "platform": EXPECTED_PLATFORM,
        "idf_version": IDF_VERSION,
        "esptool_version": ESPTOOL_VERSION,
    }


def _atomic_write(path, text):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    # Stage the temp file inside the gitignored build_gen/ directory (same
    # filesystem) so a crash between write and replace can never leave an
    # unignored generated file next to the target.
    if not os.path.isdir(BUILD_GEN_DIR):
        os.makedirs(BUILD_GEN_DIR)
    tmp_path = os.path.join(
        BUILD_GEN_DIR, os.path.basename(path) + ".tmp"
    )
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(text)
    os.replace(tmp_path, path)


def _write_header(source_sha, build_id):
    # The header is a COMPILE INPUT, not a release artifact: any proto build
    # (including `pio test`) refreshes it at parse time. The release artifact
    # pair (firmware.elf/bin <-> metadata JSON) stays consistent because both
    # are produced by the same successful default build.
    build_id_token = _checked_emit_token(build_id, "VDOG_BUILD_ID_STR")
    sha_short_token = _checked_emit_token(
        _source_sha_short(source_sha), "VDOG_SOURCE_SHA_SHORT"
    )
    content = (
        "/* Generated by firmware/scripts/gen_build_meta.py - DO NOT EDIT.\n"
        " * Sanitized vdog-build-metadata-v1 build identity for this build.\n"
        " */\n"
        "#ifndef VDOG_BUILD_ID_H\n"
        "#define VDOG_BUILD_ID_H\n"
        "\n"
        '#define VDOG_BUILD_ID_STR "%s"\n'
        '#define VDOG_SOURCE_SHA_SHORT "%s"\n'
        "\n"
        "#endif /* VDOG_BUILD_ID_H */\n"
    ) % (build_id_token, sha_short_token)
    _atomic_write(HEADER_PATH, content)


def _emit_metadata_action(source, target, env):  # SCons calls with source/target/env
    payload = _metadata_payload()
    _atomic_write(
        METADATA_PATH, json.dumps(payload, indent=2, sort_keys=False) + "\n"
    )
    print(
        "vdog build metadata: %s (build_id=%s source_sha=%s)"
        % (METADATA_PATH, payload["build_id"], payload["source_sha"])
    )


def main():
    # This script must only ever be wired to the proto firmware environment.
    if env.subst("$PIOENV") != ENVIRONMENT:
        _fail(
            "gen_build_meta.py may only be wired to [env:%s] (loaded in %r)"
            % (ENVIRONMENT, env.subst("$PIOENV"))
        )

    # Fail fast, before any long compilation, on invalid CI identity inputs.
    source_sha, build_id = _validated_identity()

    # Header first (parse time == before any build action runs): src/main.c
    # includes it unconditionally, so a clean build must find it.
    _write_header(source_sha, build_id)

    # Contract: the proto environment carries build_gen on its include path.
    # src/CMakeLists.txt registers the same directory with the IDF "main"
    # component so the codemodel-derived compile flags pick it up as well.
    env.Append(CPPPATH=[BUILD_GEN_DIR])

    command_targets = set(COMMAND_LINE_TARGETS or [])
    if command_targets & {"__test", "nobuild"}:
        # Test builds and nobuild never (re)write the release metadata.
        return

    # checkprogsize is an AlwaysBuild alias on the linked ELF that every
    # successful default build executes (even a fully cached one), so the
    # metadata JSON is regenerated at the end of EVERY successful normal
    # `pio run`, never leaving a stale identity behind.
    # Consumers must only export/package after `pio run` exits 0: the alias
    # runs before the final ElfToBin step, so treat a non-zero exit as "no
    # valid release identity for this build" (round-2 CI gating).
    env.AddPostAction("checkprogsize", _emit_metadata_action)


main()
