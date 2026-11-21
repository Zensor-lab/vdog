# vdog test-build environment isolation (Stage 0.9 packet A; master plan
# 0.9.3 "separate build directories" requirement).
#
# Wired as `extra_scripts = pre:scripts/test_build_isolation.py` of
# [env:vdog_xiao_sense_proto] ONLY. PlatformIO Core 6.2.0 builds embedded
# `pio test` runs into the SAME directory as normal builds
# (.pio/build/<env>/) and relinks firmware.elf/firmware.bin as the embedded
# test-runner image (verified empirically: Unity symbols present, normal
# app_main identity gone). That would let a packaging step pick up a test
# runner instead of the release app (master plan CI-T03).
#
# This pre-script (parsed BEFORE the platform build script creates any nodes,
# per platformio/builder/main.py) redirects any `pio test` / `__test` build of
# the proto environment to its own directory:
#     .pio/build/vdog_xiao_sense_proto_test/
# Normal `pio run` invocations are untouched, and the `native` environment
# never loads this script.

import os

from SCons.Script import COMMAND_LINE_TARGETS

Import("env")

ENVIRONMENT = "vdog_xiao_sense_proto"
TEST_BUILD_SUFFIX = "_test"


def main():
    if env.subst("$PIOENV") != ENVIRONMENT:
        # Defensive: must only ever be wired to the proto environment.
        return
    if "__test" not in (COMMAND_LINE_TARGETS or []):
        # Normal builds keep the default build directory.
        return
    normal_build_dir = os.path.normpath(env.subst("$BUILD_DIR"))
    test_build_dir = normal_build_dir + TEST_BUILD_SUFFIX
    env.Replace(BUILD_DIR=test_build_dir)
    print(
        "vdog test-build isolation: build dir -> %s" % test_build_dir
    )


main()
