"""Setup-wrapper tests for the prebuilt bundle (master plan 0.9.6 / CI-T09).

``install.sh`` must build an ISOLATED environment, install the hash-pinned
dependencies into it and only then run ``install.py`` inside it. The host has no
``pwsh``, so ``install.ps1`` gets structural coverage only and that limitation is
stated rather than hidden.

A fake ``uv`` stands in for the real one: it creates a genuine venv with the
interpreter running this suite (the qualified CPython 3.12), writes stand-in
``esptool``/``serial`` modules into that venv's own site-packages, and records
every invocation. No network, no device, no ambient interpreter.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import support

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER_DIR = REPO_ROOT / "tools/firmware/installer"
INSTALL_SH = INSTALLER_DIR / "install.sh"
INSTALL_PS1 = INSTALLER_DIR / "install.ps1"
INSTALLER_LOCK = INSTALLER_DIR / "requirements-installer.lock"

FAKE_ESPTOOL = '''"""Stand-in esptool installed by the fake uv (tests only)."""
__version__ = "5.4.0"


def main(*_a, **_k):
    raise SystemExit("fake esptool must not be executed by these tests")
'''

FAKE_SERIAL = '''"""Stand-in pyserial package installed by the fake uv (tests only)."""


def comports(*_a, **_k):
    return []
'''

FAKE_UV = """#!/bin/sh
# Minimal fake `uv` for the installer-wrapper tests. Behaviour is driven by
# FAKE_UV_* environment variables; every invocation is appended to FAKE_UV_LOG.
set -eu

if [ -n "${FAKE_UV_LOG:-}" ]; then
    printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
fi

case "$1 $2" in
    "python find")
        if [ "${FAKE_UV_FAIL_FIND:-0}" = "1" ]; then
            exit 1
        fi
        printf '%s\\n' "$FAKE_REAL_PYTHON"
        exit 0
        ;;
    "python install")
        if [ "${FAKE_UV_FAIL_INSTALL_PYTHON:-0}" = "1" ]; then
            printf 'fake uv: cannot download CPython (no network)\\n' >&2
            exit 1
        fi
        exit 0
        ;;
    "venv --python")
        # $3 is the interpreter, $4 the target directory.
        if [ "${FAKE_UV_FAIL_VENV:-0}" = "1" ]; then
            printf 'fake uv: venv creation refused\\n' >&2
            exit 1
        fi
        "${FAKE_REAL_PYTHON}" -m venv --without-pip "$4"
        exit 0
        ;;
    "pip install")
        shift 3                       # drop: pip install --python
        py="$1"; shift
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --require-hashes) REQUIRE_HASHES=1; shift ;;
                -r) LOCK="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        if [ "${FAKE_UV_FAIL_DEPS:-0}" = "1" ]; then
            printf 'fake uv: hash mismatch for a pinned wheel\\n' >&2
            exit 1
        fi
        if [ "${FAKE_UV_REQUIRE_HASHES_STRICT:-1}" = "1" ] && [ "${REQUIRE_HASHES:-0}" != "1" ]; then
            printf 'fake uv: refusing an unhashed install (wrapper bug)\\n' >&2
            exit 1
        fi
        if [ ! -f "$LOCK" ]; then
            printf 'fake uv: lockfile %s missing\\n' "$LOCK" >&2
            exit 1
        fi
        site="$("$py" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
)"
        mkdir -p "$site"
        printf '%s' "$FAKE_ESPTOOL_SRC" > "$site/esptool.py"
        mkdir -p "$site/serial"
        printf '%s' "$FAKE_SERIAL_SRC" > "$site/serial/__init__.py"
        exit 0
        ;;
    *)
        printf 'fake uv: unsupported invocation: %s\\n' "$*" >&2
        exit 64
        ;;
esac
"""


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class Bundle:
    """An extracted release bundle plus the fake-uv environment."""

    def __init__(self, root: Path, *, zip_path: Path, bin_dir: Path) -> None:
        self.root = root
        self.zip_path = zip_path
        self.bin_dir = bin_dir
        self.uv_log = bin_dir / "uv.log"

    def invocations(self) -> list[str]:
        if not self.uv_log.is_file():
            return []
        return self.uv_log.read_text(encoding="utf-8").splitlines()

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"VDOG_INSTALLER_UV", "VDOG_INSTALLER_VENV_DIR",
                           "VDOG_INSTALLER_PYTHON", "VIRTUAL_ENV"}
        }
        env["PATH"] = f"{self.bin_dir}:/bin:/usr/bin"
        env["FAKE_REAL_PYTHON"] = sys.executable
        env["FAKE_UV_LOG"] = str(self.uv_log)
        env["FAKE_ESPTOOL_SRC"] = FAKE_ESPTOOL
        env["FAKE_SERIAL_SRC"] = FAKE_SERIAL
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run(self, *args: str, **env_overrides: str | None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/sh", str(self.root / "install.sh"), *args],
            cwd=self.root,
            env=self.env(**env_overrides),
            capture_output=True,
            text=True,
            timeout=180,
        )

    @property
    def venv(self) -> Path:
        return self.root / ".venv-installer"


@pytest.fixture
def bundle(tmp_path: Path) -> Bundle:
    """A real packaged release ZIP, extracted, with the wrappers under test."""
    zip_path, _digest, _payload, manifest = support.package_from_build_dir(
        tmp_path / "build"
    )
    root = tmp_path / "bundle"
    root.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(root)
    extracted = next(p for p in root.iterdir() if p.is_dir())
    # Move the bundle to a stable path and refresh the wrappers from the working
    # tree, so the test exercises the current script text in every case.
    target = tmp_path / "extracted"
    extracted.rename(target)
    for name in ("install.sh", "install.ps1", "install.py", "requirements-installer.lock"):
        shutil.copy2(INSTALLER_DIR / name, target / name)
    assert manifest["build_id"] == "local"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(FAKE_UV, encoding="utf-8")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return Bundle(target, zip_path=zip_path, bin_dir=bin_dir)


# ---------------------------------------------------------------------------
# First setup: isolated environment, then install.py inside it
# ---------------------------------------------------------------------------


def test_first_setup_creates_the_isolated_env_and_runs_install_py(bundle: Bundle) -> None:
    result = bundle.run("check")
    assert result.returncode == 0, result.stderr
    assert bundle.venv.is_dir()
    assert (bundle.venv / "bin" / "python").is_file()
    # The environment is inside the bundle, not in a cache or a temp dir.
    assert str(bundle.venv).startswith(str(bundle.root))
    # install.py ran and reported a valid bundle.
    assert "OK" in result.stdout or "valid" in result.stdout.lower()

    invocations = bundle.invocations()
    assert any(inv.startswith("python find") for inv in invocations)
    assert any(inv.startswith("venv --python") for inv in invocations)
    install = [inv for inv in invocations if inv.startswith("pip install")]
    assert len(install) == 1, invocations
    assert "--require-hashes" in install[0]
    assert "requirements-installer.lock" in install[0]
    assert str(bundle.venv / "bin" / "python") in install[0]


def test_setup_is_reused_and_not_reinstalled(bundle: Bundle) -> None:
    first = bundle.run("check")
    assert first.returncode == 0, first.stderr
    installs_before = [i for i in bundle.invocations() if i.startswith("pip install")]

    second = bundle.run("plan", "--board", "seeed-xiao-esp32s3-sense")
    assert second.returncode == 0, second.stderr
    installs_after = [i for i in bundle.invocations() if i.startswith("pip install")]
    assert len(installs_after) == len(installs_before), "the env must be reused"


def test_arguments_pass_through_and_exit_status_propagates(bundle: Bundle) -> None:
    ok = bundle.run("plan", "--board", "seeed-xiao-esp32s3-sense")
    assert ok.returncode == 0, ok.stderr
    # The four validated segments are install.py's output, not the wrapper's.
    for needle in ("bootloader", "partitions", "ota_data", "firmware"):
        assert needle in ok.stdout, needle

    # An unsupported board reaches install.py (proof of pass-through) and its
    # non-zero status reaches the caller (proof the wrapper does not mask it).
    bogus = bundle.run("plan", "--board", "totally-wrong-board")
    assert bogus.returncode != 0
    assert "unsupported --board" in (bogus.stdout + bogus.stderr)

    dry = bundle.run("install", "--port", "/tmp/vdog-fake-serial-port",
                     "--board", "seeed-xiao-esp32s3-sense", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "nothing was executed and no port was opened" in dry.stdout

    failing = bundle.run("inspect", "--port", "/tmp/vdog-fake-serial-port",
                         "--board", "seeed-xiao-esp32s3-sense")
    assert failing.returncode != 0, "a real failure must not be masked by the wrapper"


def test_unknown_subcommand_reports_the_installer_usage(bundle: Bundle) -> None:
    result = bundle.run("definitely-not-a-command")
    assert result.returncode != 0
    assert "usage" in (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Prerequisite failures are actionable, never silent
# ---------------------------------------------------------------------------


def test_missing_uv_stops_with_an_actionable_message(bundle: Bundle) -> None:
    # Without the fake uv on PATH the wrapper must stop, not guess.
    env = bundle.env()
    env["PATH"] = "/bin:/usr/bin"
    result = subprocess.run(
        ["/bin/sh", str(bundle.root / "install.sh"), "check"],
        cwd=bundle.root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 2
    stderr = result.stderr
    assert "uv" in stderr and "docs.astral.sh/uv" in stderr
    assert "VDOG_INSTALLER_UV" in stderr
    assert not bundle.venv.exists(), "no environment may be created without uv"


def test_bogus_vdog_installer_uv_is_refused(bundle: Bundle) -> None:
    result = bundle.run("check", VDOG_INSTALLER_UV=str(bundle.bin_dir / "no-such-uv"))
    assert result.returncode == 2
    assert "VDOG_INSTALLER_UV" in result.stderr
    assert "not an executable" in result.stderr


def test_unusable_interpreter_is_reported_not_bypassed(bundle: Bundle) -> None:
    result = bundle.run("check", FAKE_UV_FAIL_FIND="1", FAKE_UV_FAIL_INSTALL_PYTHON="1")
    assert result.returncode == 2
    assert "CPython" in result.stderr
    assert "VDOG_INSTALLER_PYTHON" in result.stderr
    assert not bundle.venv.exists()


def test_dependency_install_failure_is_not_swallowed(bundle: Bundle) -> None:
    result = bundle.run("check", FAKE_UV_FAIL_DEPS="1")
    assert result.returncode == 2
    stderr = result.stderr
    assert "requirements-installer.lock" in stderr
    assert "network" in stderr.lower()
    assert "unofficial source" in stderr, "must refuse any fallback to an ambient esptool"


def test_partial_environment_is_not_silently_repaired(bundle: Bundle) -> None:
    bundle.venv.mkdir()
    result = bundle.run("check")
    assert result.returncode == 2
    assert "partial" in result.stderr or "not a directory" in result.stderr
    assert "VDOG_INSTALLER_VENV_DIR" in result.stderr


def test_venv_dir_override_is_honoured(bundle: Bundle, tmp_path: Path) -> None:
    elsewhere = tmp_path / "else where" / "installer env"
    result = bundle.run("check", VDOG_INSTALLER_VENV_DIR=str(elsewhere))
    assert result.returncode == 0, result.stderr
    assert (elsewhere / "bin" / "python").is_file()
    assert not bundle.venv.exists()


def test_spaces_and_non_ascii_paths_work(tmp_path: Path) -> None:
    root = tmp_path / "release bun дле ¥ 🐕"
    root.mkdir(parents=True)
    zip_path, _digest, _payload, _manifest = support.package_from_build_dir(
        tmp_path / "build"
    )
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(root)
    extracted = next(p for p in root.iterdir() if p.is_dir())
    target = root / "vdog 包 0.2.0-proto"
    extracted.rename(target)
    for name in ("install.sh", "install.py", "requirements-installer.lock"):
        shutil.copy2(INSTALLER_DIR / name, target / name)
    bin_dir = tmp_path / "uv bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(FAKE_UV, encoding="utf-8")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    bundle = Bundle(target, zip_path=zip_path, bin_dir=bin_dir)
    result = bundle.run("check")
    assert result.returncode == 0, result.stderr
    assert (target / ".venv-installer" / "bin" / "python").is_file()


# ---------------------------------------------------------------------------
# Structural invariants of both wrappers (the ps1 cannot be executed here)
# ---------------------------------------------------------------------------


def test_install_sh_never_uses_global_python_elevation_or_pipes() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    forbidden = [
        "sudo ", "curl ", "wget ", "| sh", "|sh", "| bash",
        "--break-system-packages", "pip install esptool", "python3 install.py",
        "rm -rf", "esptool.py write_flash", "--erase",
    ]
    for needle in forbidden:
        assert needle not in text, f"install.sh must never contain {needle!r}"
    required = [
        "--require-hashes",
        "requirements-installer.lock",
        '"$VENV_PYTHON" "$INSTALL_PY" "$@"',
        "VDOG_INSTALLER_UV",
        "VDOG_INSTALLER_VENV_DIR",
        "VDOG_INSTALLER_PYTHON",
        ".venv-installer",
        "set -eu",
    ]
    for needle in required:
        assert needle in text, f"install.sh must contain {needle!r}"
    # Every expansion is quoted: a bare $@ or unquoted path would break on spaces.
    assert ' "$@"' in text
    assert "$@" not in text.replace('"$@"', "")


def test_install_ps1_structural_invariants_without_pwsh() -> None:
    """`pwsh` is not installed on this host, so install.ps1 is NOT executed.

    These assertions are the only local evidence for the Windows wrapper; the
    real Windows run remains CI-T09 pending, not passed.
    """
    if shutil.which("pwsh") or shutil.which("powershell"):  # pragma: no cover
        pytest.skip("a real PowerShell run is covered elsewhere")
    text = INSTALL_PS1.read_text(encoding="utf-8")
    required = [
        ".venv-installer",
        "Scripts\\python.exe",
        "--require-hashes",
        "requirements-installer.lock",
        "$InstallPy",
        "@args",
        "VDOG_INSTALLER_UV",
        "VDOG_INSTALLER_VENV_DIR",
        "VDOG_INSTALLER_PYTHON",
        "Set-StrictMode",
        "$ErrorActionPreference = 'Stop'",
        "exit $LASTEXITCODE",
    ]
    for needle in required:
        assert needle in text, f"install.ps1 must contain {needle!r}"
    for needle in ("sudo", "curl ", "wget ", "iex", "Invoke-WebRequest", "Start-Process",
                   "--break-system-packages", "--erase"):
        assert needle not in text, f"install.ps1 must never contain {needle!r}"
    # Argument arrays, never a reconstructed command string.
    assert "& $UvBin @" in text
    assert "& $VenvPython $InstallPy @args" in text


def test_wrappers_are_shipped_in_the_package(tmp_path: Path) -> None:
    """The ZIP the user extracts really contains these two scripts."""
    zip_path, _digest, payload, _manifest = support.package_from_build_dir(tmp_path / "b")
    with zipfile.ZipFile(zip_path) as archive:
        names = {i.filename.split("/", 1)[1] for i in archive.infolist() if not i.is_dir()}
    assert {"install.sh", "install.ps1", "install.py", "requirements-installer.lock"} <= names
    for member in ("install.sh", "install.ps1"):
        with zipfile.ZipFile(zip_path) as archive:
            packed = archive.read(next(
                i.filename for i in archive.infolist() if i.filename.endswith("/" + member)
            ))
        assert packed == (INSTALLER_DIR / member).read_bytes()
    assert payload  # the fixture really produced a bundle
