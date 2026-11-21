#!/bin/sh
# =============================================================================
# vdog prebuilt-firmware setup wrapper (master plan 0.9.6).
#
# Creates or reuses an ISOLATED local installer environment (.venv-installer/
# next to this script, gitignored), installs the hash-pinned dependencies from
# requirements-installer.lock into it, and then execs the same install.py entry
# point inside that environment. Every argument is passed straight through:
#
#   ./install.sh check
#   ./install.sh ports
#   ./install.sh plan --board seeed-xiao-esp32s3-sense
#   ./install.sh inspect --port /dev/cu.usbmodem123
#   ./install.sh install --port /dev/cu.usbmodem123 --board seeed-xiao-esp32s3-sense
#   ./install.sh install --port ... --board ... --dry-run
#
# Guarantees:
#   * never installs into, modifies or discovers a "convenient" global Python:
#     the only interpreter it runs is the one inside .venv-installer/;
#   * no sudo, no administrator elevation, no copied virtual environment, and
#     no download-and-execute pipe (it only ever runs uv and its own venv);
#   * dependencies come from requirements-installer.lock installed WITH
#     --require-hashes, so a substituted wheel fails the setup;
#   * the qualified CPython 3.12 patch is selected through `uv python find`,
#     falling back to `uv python install`, and the resulting interpreter is
#     re-verified to be CPython 3.12;
#   * every path is quoted, so spaces and non-ASCII directory names work;
#   * missing prerequisites produce an actionable error and a non-zero exit.
#
# First setup downloads the pinned wheels, so it needs network access; later
# runs reuse the environment and work offline.
#
# Overrides (all optional):
#   VDOG_INSTALLER_UV         path to the uv executable to use
#   VDOG_INSTALLER_VENV_DIR   where to keep the isolated environment
#   VDOG_INSTALLER_PYTHON     which qualified CPython 3.12 to select (default
#                             below; recorded in tools/README.md)
# =============================================================================
set -eu

SCRIPT_PATH=$0
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)
INSTALL_PY="$SCRIPT_DIR/install.py"
REQUIREMENTS_LOCK="$SCRIPT_DIR/requirements-installer.lock"

VENV_DIR=${VDOG_INSTALLER_VENV_DIR:-$SCRIPT_DIR/.venv-installer}
QUALIFIED_PYTHON=${VDOG_INSTALLER_PYTHON:-3.12.12}
QUALIFIED_MINOR=3.12
VENV_PYTHON="$VENV_DIR/bin/python"
# Marker string the dependency probe runs; keep in sync with the wrapper tests.
DEP_PROBE='import esptool, serial; assert esptool.__version__ == "5.4.0"'

fail() {
    printf 'error: %s\n' "$1" >&2
    shift
    for line in "$@"; do
        printf '       %s\n' "$line" >&2
    done
    exit 2
}

# --- prerequisites ----------------------------------------------------------
if [ ! -f "$INSTALL_PY" ]; then
    fail "install.py not found beside this script in '$SCRIPT_DIR'." \
        "Extract the complete release ZIP and run the wrapper from inside the" \
        "extracted 'vdog-xiao-sense-...' directory."
fi
if [ ! -f "$REQUIREMENTS_LOCK" ]; then
    fail "requirements-installer.lock is missing from '$SCRIPT_DIR'." \
        "The bundle is incomplete; re-download it from the GitHub Release and" \
        "verify its .sha256 before installing."
fi

UV_BIN=${VDOG_INSTALLER_UV:-}
if [ -n "$UV_BIN" ] && [ ! -x "$UV_BIN" ]; then
    fail "VDOG_INSTALLER_UV points to '$UV_BIN', which is not an executable." \
        "Unset it, or point it at a working uv binary."
fi
if [ -z "$UV_BIN" ]; then
    UV_BIN=$(command -v uv 2>/dev/null || true)
fi
if [ -z "$UV_BIN" ]; then
    fail "'uv' was not found, and it is required to build the isolated installer environment." \
        "Install uv with your package manager (brew install uv, apt/pacman/dnf," \
        "winget install astral-sh.uv) or from https://docs.astral.sh/uv/," \
        "then rerun this script. Do NOT pipe a downloaded install script into a" \
        "shell; install a packaged uv instead." \
        "If uv is already installed somewhere unusual, set VDOG_INSTALLER_UV=/path/to/uv."
fi

# --- select the qualified CPython 3.12 --------------------------------------
PY=$("$UV_BIN" python find "$QUALIFIED_PYTHON" 2>/dev/null || true)
if [ -z "$PY" ]; then
    printf 'installer: CPython %s not found locally; installing it with uv (needs network)\n' \
        "$QUALIFIED_PYTHON" >&2
    if ! "$UV_BIN" python install "$QUALIFIED_PYTHON" >&2; then
        fail "uv could not provision CPython $QUALIFIED_PYTHON." \
            "Check network access, or pick another qualified 3.12 patch with" \
            "VDOG_INSTALLER_PYTHON (for example VDOG_INSTALLER_PYTHON=3.12)."
    fi
    PY=$("$UV_BIN" python find "$QUALIFIED_PYTHON" 2>/dev/null || true)
fi
if [ -z "$PY" ]; then
    fail "uv still cannot locate CPython $QUALIFIED_PYTHON after installation." \
        "Run '$UV_BIN python list' to see what is available, then set" \
        "VDOG_INSTALLER_PYTHON to a 3.12 interpreter."
fi

# --- create or reuse the isolated environment -------------------------------
if [ -e "$VENV_DIR" ] && [ ! -d "$VENV_DIR" ]; then
    fail "'$VENV_DIR' exists but is not a directory." \
        "Move it away, or choose another location with VDOG_INSTALLER_VENV_DIR."
fi
if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_PYTHON" ]; then
    fail "'$VENV_DIR' exists but has no usable '$VENV_PYTHON'." \
        "It is a partial or copied environment, which this wrapper will not" \
        "repair silently. Remove that directory and rerun, or point" \
        "VDOG_INSTALLER_VENV_DIR somewhere else."
fi
if [ ! -d "$VENV_DIR" ]; then
    printf 'installer: creating the isolated environment %s\n' "$VENV_DIR" >&2
    if ! "$UV_BIN" venv --python "$PY" "$VENV_DIR" >&2; then
        fail "uv could not create the isolated environment at '$VENV_DIR'." \
            "Check that the directory is writable, or set" \
            "VDOG_INSTALLER_VENV_DIR to a writable path."
    fi
fi
if [ ! -x "$VENV_PYTHON" ]; then
    fail "the environment at '$VENV_DIR' has no bin/python after setup." \
        "Remove the directory and rerun, or choose another VDOG_INSTALLER_VENV_DIR."
fi

# Never run against an interpreter that is not the qualified minor version.
RESOLVED=$("$VENV_PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
if [ "$RESOLVED" != "$QUALIFIED_MINOR" ]; then
    fail "the installer environment at '$VENV_DIR' reports Python '$RESOLVED'," \
         "but this bundle is qualified on CPython $QUALIFIED_MINOR only." \
         "Remove that directory (or set VDOG_INSTALLER_VENV_DIR) and rerun with" \
         "VDOG_INSTALLER_PYTHON set to a $QUALIFIED_MINOR interpreter."
fi

# --- install the locked dependencies with hashes ----------------------------
if ! "$VENV_PYTHON" -c "$DEP_PROBE" >/dev/null 2>&1; then
    printf 'installer: installing the pinned installer dependencies (needs network on first setup)\n' >&2
    if ! "$UV_BIN" pip install --python "$VENV_PYTHON" --require-hashes \
            -r "$REQUIREMENTS_LOCK" >&2; then
        fail "the locked installer dependencies could not be installed." \
            "First setup needs network access. If the hash check itself failed," \
            "the bundle's requirements-installer.lock was tampered with or is" \
            "incomplete: re-download the release ZIP and verify its .sha256." \
            "Never install esptool from an unofficial source into this environment."
    fi
    if ! "$VENV_PYTHON" -c "$DEP_PROBE" >/dev/null 2>&1; then
        fail "the environment still lacks the qualified esptool 5.4.0 / pyserial pair." \
            "Re-run from a clean VDOG_INSTALLER_VENV_DIR with network access;" \
            "this wrapper will not fall back to an ambient esptool."
    fi
fi

exec "$VENV_PYTHON" "$INSTALL_PY" "$@"
