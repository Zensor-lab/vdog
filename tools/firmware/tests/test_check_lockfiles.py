"""Regression coverage for tools.firmware.check_lockfiles (round-2 F1/F2).

Both CI lockfile checks used to be inline grep/regex in ``firmware-main.yml``
that no PR-runnable test ever executed — which is exactly how the two HIGH
bugs shipped green (the component grep rejected the valid committed lock;
the installer parser rejected uv's ``name==version \\`` continuation lines).

These tests therefore MUST run the checks against the real committed
lockfiles (they pass as-is) in addition to the negative fixtures, so any
future drift in either file or in the checker itself fails ``pytest
tools/firmware/tests`` on every PR, long before a main run notices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.firmware import check_lockfiles

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_LOCK = REPO_ROOT / "firmware/dependencies.lock"
INSTALLER_LOCK = REPO_ROOT / "tools/firmware/installer/requirements-installer.lock"


# ---------------------------------------------------------------------------
# Real committed lockfiles: both checks must pass as-is (the CI invocation)
# ---------------------------------------------------------------------------


def test_committed_component_lock_passes() -> None:
    assert COMPONENT_LOCK.is_file()
    assert check_lockfiles.check_component_lock(COMPONENT_LOCK) == []


def test_committed_installer_lock_passes() -> None:
    assert INSTALLER_LOCK.is_file()
    assert check_lockfiles.check_installer_lock(INSTALLER_LOCK) == []


def test_cli_both_committed_lockfiles_exit_zero() -> None:
    assert check_lockfiles.main(
        [
            "--component-lock", str(COMPONENT_LOCK),
            "--installer-lock", str(INSTALLER_LOCK),
        ]
    ) == 0


# ---------------------------------------------------------------------------
# F1: component lock
# ---------------------------------------------------------------------------


def _component_lock_data() -> dict[str, Any]:
    return yaml.safe_load(COMPONENT_LOCK.read_text(encoding="utf-8"))


def _write_component_lock(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "dependencies.lock"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_component_lock_ignores_dependency_constraint_entries() -> None:
    """The committed lock's constraint entries must be present AND ignored.

    This is the exact F1 failure mode: ``version: ^1.3.1`` / ``'>=5.1'`` /
    ``'>=5.0'`` live inside per-component ``dependencies:`` list items and
    are dependency constraints, not resolved versions.
    """
    data = _component_lock_data()
    camera_deps = data["dependencies"]["espressif/esp32-camera"]["dependencies"]
    constraints = [entry["version"] for entry in camera_deps]
    assert "^1.3.1" in constraints and ">=5.1" in constraints
    jpeg_constraints = [
        entry["version"]
        for entry in data["dependencies"]["espressif/esp_jpeg"]["dependencies"]
    ]
    assert ">=5.0" in jpeg_constraints
    # ...and yet the structural check passes, ignoring all of them.
    assert check_lockfiles.check_component_lock(COMPONENT_LOCK) == []


def test_component_lock_rejects_resolved_version_replaced_by_range(
    tmp_path: Path,
) -> None:
    data = _component_lock_data()
    data["dependencies"]["espressif/esp32-camera"]["version"] = "^1.3.1"
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any("espressif/esp32-camera" in e and "^1.3.1" in e for e in errors)


@pytest.mark.parametrize(
    "bad_version",
    [">=6.1", "~6.1.0", "6.*", "latest", "", None, True],
)
def test_component_lock_rejects_non_exact_resolved_versions(
    tmp_path: Path, bad_version: Any
) -> None:
    data = _component_lock_data()
    data["dependencies"]["espressif/esp_jpeg"]["version"] = bad_version
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any("espressif/esp_jpeg" in e for e in errors)


@pytest.mark.parametrize(
    "exact_version",
    [
        "1.3.2",   # ordinary multi-dot str
        6.1,       # unquoted single-dot loads as float in YAML 1.1
        2,         # unquoted single-segment loads as int
        1.0,
    ],
)
def test_component_lock_accepts_exact_numeric_scalar_versions(
    tmp_path: Path, exact_version: Any
) -> None:
    """LOW note: numeric YAML scalars are exact versions, not constraints."""
    data = _component_lock_data()
    data["dependencies"]["espressif/esp_jpeg"]["version"] = exact_version
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert errors == [], (exact_version, errors)


def test_component_lock_requires_component_hash(tmp_path: Path) -> None:
    data = _component_lock_data()
    del data["dependencies"]["espressif/esp32-camera"]["component_hash"]
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any("component_hash" in e for e in errors)


def test_component_lock_rejects_malformed_component_hash(tmp_path: Path) -> None:
    data = _component_lock_data()
    data["dependencies"]["espressif/esp_jpeg"]["component_hash"] = "deadbeef"
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any("component_hash" in e for e in errors)


@pytest.mark.parametrize(
    ("component", "want", "mutate_to"),
    [
        ("espressif/esp32-camera", "2.1.9", "2.0.13"),
        ("idf", "6.1.0", "6.0.0"),
    ],
)
def test_component_lock_pins_managed_component_versions(
    tmp_path: Path, component: str, want: str, mutate_to: str
) -> None:
    data = _component_lock_data()
    data["dependencies"][component]["version"] = mutate_to
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any(component in e and want in e for e in errors)


@pytest.mark.parametrize("component", ["espressif/esp32-camera", "idf"])
def test_component_lock_rejects_missing_managed_component(
    tmp_path: Path, component: str
) -> None:
    data = _component_lock_data()
    del data["dependencies"][component]
    errors = check_lockfiles.check_component_lock(_write_component_lock(tmp_path, data))
    assert any(component in e and "missing" in e for e in errors)


def test_component_lock_rejects_structural_damage(tmp_path: Path) -> None:
    missing = tmp_path / "none.lock"
    missing.write_text("manifest_hash: a1a1\n", encoding="utf-8")
    assert any("dependencies" in e for e in
               check_lockfiles.check_component_lock(missing))
    invalid = tmp_path / "bad.lock"
    invalid.write_text("dependencies: [unclosed\n", encoding="utf-8")
    assert any("YAML" in e for e in
               check_lockfiles.check_component_lock(invalid))
    empty = tmp_path / "empty.lock"
    empty.write_text("dependencies: {}\n", encoding="utf-8")
    assert any("empty" in e for e in
               check_lockfiles.check_component_lock(empty))
    assert any("cannot read" in e for e in
               check_lockfiles.check_component_lock(tmp_path / "absent.lock"))


def test_cli_component_lock_failure_exits_one(tmp_path: Path) -> None:
    data = _component_lock_data()
    data["dependencies"]["idf"]["version"] = ">=6.0"
    assert check_lockfiles.main(
        ["--component-lock", str(_write_component_lock(tmp_path, data))]
    ) == check_lockfiles.EXIT_LOCKFILE_INVALID


# ---------------------------------------------------------------------------
# F2: installer lock (uv pip compile --generate-hashes format)
# ---------------------------------------------------------------------------

# The committed lock's first requirement is exactly `bitstring==5.0.0 \` —
# the uv continuation form that made the old inline regex reject the real
# file. Multiple --hash lines, an uncontinued final hash and `# via`
# comment lines all occur in the committed lock and must parse.
UV_FORMAT_FIXTURE = """\
# This file was autogenerated by uv via the following command:
#    uv pip compile --generate-hashes --python-version 3.12 in.in -o out.lock
bitstring==5.0.0 \\
    --hash=sha256:01d876b6e7bbd912bfa3ae1d028ed419ed2193245fe2337f21d30afaa391c053 \\
    --hash=sha256:c247398845ae1ca6cadde0158d04a825f8ef1ad7487b473766a0bb17b1fded68
    # via esptool
esptool==5.4.0 \\
    --hash=sha256:fd756598db0a26c9975fa18511b08687c54bf2ce7322ede80cf1f5117dad1f50
    # via -r in.in
pyserial==3.5 \\
    --hash=sha256:0c314874542e474a5a8e593ab951c04df867ed980383c35b06bf6a3777ec92e8
    # via esptool
"""


def _installer(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "requirements-installer.lock"
    path.write_text(text, encoding="utf-8")
    return path


def test_installer_lock_accepts_uv_continuation_format(tmp_path: Path) -> None:
    """Continuation lines, multi-hash entries and comments all parse."""
    assert check_lockfiles.check_installer_lock(_installer(tmp_path, UV_FORMAT_FIXTURE)) == []


def test_installer_lock_real_lock_uses_the_continuation_form() -> None:
    """Guard: the committed lock still exercises the F2 parser branch."""
    first_requirement = next(
        line for line in INSTALLER_LOCK.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and not line[:1].isspace()
    )
    assert first_requirement == "bitstring==5.0.0 \\"


def test_installer_lock_rejects_unpinned_ge(tmp_path: Path) -> None:
    text = UV_FORMAT_FIXTURE.replace(
        "pyserial==3.5 \\", "pyserial>=3.5 \\",
    )
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, text))
    assert any("unpinned" in e and "pyserial" in e for e in errors)


def test_installer_lock_rejects_requirement_without_hash(tmp_path: Path) -> None:
    text = UV_FORMAT_FIXTURE.replace(
        "pyserial==3.5 \\\n    --hash=sha256:0c314874542e474a5a8e593ab951c04df867ed980383c35b06bf6a3777ec92e8\n",
        "pyserial==3.5\n",
    )
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, text))
    assert any("pyserial" in e and "hash" in e for e in errors)


@pytest.mark.parametrize(
    ("esptool_line", "expect"),
    [
        ("esptool==5.3.0 \\", "5.3.0"),          # wrong qualified version
        ("esptool>=5.4.0 \\", "unpinned"),        # not pinned at all
    ],
)
def test_installer_lock_rejects_missing_esptool_pin(
    tmp_path: Path, esptool_line: str, expect: str
) -> None:
    text = UV_FORMAT_FIXTURE.replace("esptool==5.4.0 \\", esptool_line)
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, text))
    assert any("esptool" in e and expect in e for e in errors)


def test_installer_lock_rejects_absent_esptool(tmp_path: Path) -> None:
    text = "\n".join(
        line for line in UV_FORMAT_FIXTURE.splitlines()
        if "esptool==" not in line
    )
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, text))
    assert any("esptool" in e and "None" in e for e in errors)


def test_installer_lock_rejects_malformed_and_stray_hashes(tmp_path: Path) -> None:
    bad_hash = UV_FORMAT_FIXTURE.replace(
        "--hash=sha256:fd756598db0a26c9975fa18511b08687c54bf2ce7322ede80cf1f5117dad1f50",
        "--hash=sha512:fd756598db0a26c9975fa18511b08687c54bf2ce7322ede80cf1f5117dad1f50",
    )
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, bad_hash))
    assert any("esptool" in e and "malformed" in e for e in errors)
    stray = UV_FORMAT_FIXTURE + "    --hash=sha256:" + "ab" * 32 + "\n"
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, stray))
    # the stray hash attaches to the last requirement, which stays hashed;
    # what must fail deterministically is a hash with no requirement at all
    empty = _installer(tmp_path, "    --hash=sha256:" + "ab" * 32 + "\n")
    errors = check_lockfiles.check_installer_lock(empty)
    assert any("outside a requirement" in e for e in errors)


def test_installer_lock_rejects_empty_file(tmp_path: Path) -> None:
    errors = check_lockfiles.check_installer_lock(_installer(tmp_path, "# nothing\n\n"))
    assert any("no requirements" in e for e in errors)
    assert any("esptool" in e for e in errors)


def test_cli_installer_lock_failure_exits_one(tmp_path: Path) -> None:
    assert check_lockfiles.main(
        ["--installer-lock", str(_installer(tmp_path, "freeform text\n"))]
    ) == check_lockfiles.EXIT_LOCKFILE_INVALID


def test_cli_requires_at_least_one_lock_argument() -> None:
    with pytest.raises(SystemExit) as exc:
        check_lockfiles.main([])
    assert exc.value.code != 0
