"""Installer CLI tests (work package 0.9.5) using fake serial/esptool
adapters: no test ever touches a real port. Covers check/ports/plan/inspect/
install, consent flow, device-state classification, refusals (chip, flash
size, security, unknown layout, provisioned board), the pinned-esptool gate,
write-range restrictions, and the contract.py/install.py drift check."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tools.firmware import contract
from tools.firmware.installer import install as inst

import support


@pytest.fixture()
def installed_package(tmp_path: Path) -> tuple[Path, dict[str, bytes], dict]:
    zip_path, _sha, payload, manifest = support.package_from_build_dir(tmp_path)
    root = support.extract_zip(zip_path, tmp_path / "extract")
    return root, payload, manifest


def app(root: Path, transport=None, input_fn=lambda p: "install", **kw):
    lines: list[str] = []
    return inst.InstallerApp(
        root,
        transport=transport,
        ports_provider=kw.pop("ports_provider", lambda: []),
        input_fn=input_fn,
        out=lines.append,
        err=lines.append,
    ), lines


# ---------------------------------------------------------------------------
# Offline commands
# ---------------------------------------------------------------------------


def test_check_valid_package(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, lines = app(root)
    assert a.cmd_check() == inst.EXIT_OK
    assert any("check: OK" in line for line in lines)


def test_check_detects_tampered_package(installed_package) -> None:
    root, _payload, _manifest = installed_package
    (root / "images/firmware.bin").write_bytes(b"corrupted")
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_check()
    assert exc.value.code == inst.EXIT_PACKAGE_INVALID
    assert "sha256" in str(exc.value).lower()


def test_check_detects_missing_file(installed_package) -> None:
    root, _payload, _manifest = installed_package
    (root / "install.sh").unlink()
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_check()
    assert exc.value.code == inst.EXIT_PACKAGE_INVALID
    assert "install.sh" in str(exc.value)


def test_ports_lists_without_selecting(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, lines = app(root, ports_provider=lambda: [("/dev/cu.usbmodem1", "USB")])
    assert a.cmd_ports() == inst.EXIT_OK
    assert any("/dev/cu.usbmodem1" in line for line in lines)
    assert any("never auto-selects" in line for line in lines)


def test_plan_never_opens_port(installed_package) -> None:
    root, _payload, manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    assert a.cmd_plan(board=inst.HARDWARE_CLASS) == inst.EXIT_OK
    assert transport.calls == []
    writes = [line for line in lines if line.startswith("write: role=")]
    assert len(writes) == 4
    for image in manifest["images"]:
        assert f"0x{image['offset']:08x}" in "\n".join(lines)
    assert any("never written: NVS" in line for line in lines)
    # F4 contract in the plan output: every write keeps the board in the
    # bootloader; exactly one explicit hard-reset (read-only flash-id).
    invokes = [line for line in lines if line.startswith("invoke:")]
    write_invokes = [line for line in invokes if "write-flash" in line]
    assert len(write_invokes) == 4
    assert all("--after no-reset" in line for line in write_invokes)
    reset_invokes = [line for line in invokes if "--after hard-reset" in line]
    assert len(reset_invokes) == 1
    assert "flash-id" in reset_invokes[0]


def test_plan_rejects_unknown_board(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_plan(board="raspberry-pi")
    assert exc.value.code == inst.EXIT_USAGE


def test_dry_run_opens_nothing(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodemFAKE", inst.HARDWARE_CLASS,
        dry_run=True, confirm_replace=False,
    ) == inst.EXIT_OK
    assert transport.calls == []
    assert any("--dry-run" in line for line in lines)


# ---------------------------------------------------------------------------
# Device-state classification and installation
# ---------------------------------------------------------------------------


def _expected_write_offsets() -> list[int]:
    return [0x0, 0x8000, 0xF000, 0x20000]


def test_install_blank_factory_happy_path(installed_package) -> None:
    root, _payload, manifest = installed_package
    transport = support.FakeTransport()  # all reads erased -> factory blank
    a, lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=False,
    ) == inst.EXIT_OK
    assert [w[0] for w in transport.writes] == _expected_write_offsets()
    # every written digest matches the manifest
    by_offset = {i["offset"]: i["sha256"] for i in manifest["images"]}
    for offset, digest in transport.writes:
        assert digest == by_offset[offset]
    assert any("blank factory board" in line for line in lines)
    assert any("install: OK" in line for line in lines)
    # no erase / eFuse / force style invocations exist anywhere
    assert all("write-flash" in call or "read-flash" in call
               or "flash-id" in call or "get-security-info" in call
               or "reset" in call
               or "version" in call for call in transport.calls)


def test_install_dev_match_replaces(installed_package) -> None:
    root, payload, _manifest = installed_package
    transport = support.FakeTransport(flash_map=support.blank_device_table(payload))
    a, lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=False,
    ) == inst.EXIT_OK
    assert any("matching unprovisioned development layout" in line for line in lines)
    assert len(transport.writes) == 4


def test_consent_denied_writes_nothing(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport, input_fn=lambda p: "no")
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=False,
        )
    assert exc.value.code == inst.EXIT_REFUSED
    assert transport.writes == []
    assert any("consent not given" in str(exc.value) for _ in [0])


def test_consent_eof_writes_nothing(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()

    def raise_eof(_prompt: str) -> str:
        raise EOFError

    a, _lines = app(root, transport=transport, input_fn=raise_eof)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=False,
        )
    assert exc.value.code == inst.EXIT_REFUSED
    assert transport.writes == []


def test_confirm_replace_skips_prompt(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()

    def fail_input(_prompt: str) -> str:
        raise AssertionError("input must not be requested with --confirm-replace")

    a, lines = app(root, transport=transport, input_fn=fail_input)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=True,
    ) == inst.EXIT_OK
    assert any("--confirm-replace" in line for line in lines)
    assert len(transport.writes) == 4


def test_consent_lists_exact_ranges(installed_package) -> None:
    root, _payload, manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=False,
    )
    consent_block = "\n".join(lines)
    for image in manifest["images"]:
        assert f"0x{image['offset']:08x}" in consent_block
    assert "ABOUT TO WRITE" in consent_block


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def _install_expect(installed_package, transport, code, *match, confirm=True):
    root, _payload, _manifest = installed_package
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=confirm,
        )
    assert exc.value.code == code
    for needle in match:
        assert needle.lower() in str(exc.value).lower()
    return transport


def test_refuses_wrong_chip(installed_package) -> None:
    transport = _install_expect(
        installed_package, support.FakeTransport(chip="esp32"),
        inst.EXIT_FLASH_FAILED, "not an ESP32-S3",
    )
    assert transport.writes == []


def test_refuses_wrong_flash_size(installed_package) -> None:
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_size=4_194_304),
        inst.EXIT_REFUSED, "expected 8388608",
    )
    assert transport.writes == []


def test_refuses_secure_boot_device(installed_package) -> None:
    transport = _install_expect(
        installed_package,
        support.FakeTransport(security={"secure_boot": True, "flash_encryption": False}),
        inst.EXIT_REFUSED, "security",
    )
    assert transport.writes == []


def test_refuses_flash_encryption_device(installed_package) -> None:
    transport = _install_expect(
        installed_package,
        support.FakeTransport(security={"secure_boot": False, "flash_encryption": True}),
        inst.EXIT_REFUSED, "security",
    )
    assert transport.writes == []


def test_refuses_provisioned_board(installed_package) -> None:
    root, payload, _manifest = installed_package
    flash_map = support.blank_device_table(payload)
    flash_map[0x9000] = b"\x00\x01settings"  # NVS head populated
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "provisioned",
    )
    assert transport.writes == []


def test_refuses_provisioned_even_beyond_first_nvs_sector(installed_package) -> None:
    # Provable blankness must cover the whole NVS partition, not just sector 0.
    root, payload, _manifest = installed_package
    flash_map = support.blank_device_table(payload)
    flash_map[0x9000 + 0x1000] = b"\x01\x02paired"
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "NVS",
    )
    assert transport.writes == []


def test_partial_nvs_data_is_never_treated_as_factory_blank(installed_package) -> None:
    root, _payload, _manifest = installed_package
    # Partition table and otadata erased, but NVS sector 2 holds data.
    flash_map = {0x9000 + 0x2000: b"\xAA"}
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "never assumed blank",
    )
    assert transport.writes == []


def test_refuses_unknown_partition_layout(installed_package) -> None:
    root, payload, _manifest = installed_package
    foreign = support.make_partitions_bin(entries=[
        ("nvs", 1, 0x02, 0x9000, 0x6000),
        ("otadata", 1, 0x00, 0xF000, 0x2000),
        ("vendor_app", 0, 0x10, 0x20000, 0x300000),
    ])
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = foreign
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "does not match the qualified",
    )
    assert transport.writes == []


def test_refuses_layout_with_mismatched_sizes(installed_package) -> None:
    root, payload, _manifest = installed_package
    drifted_entries = [
        (name, type_, subtype, offset, 0x1000 if name == "app1" else size)
        for (name, type_, subtype, offset, size) in support.BASELINE_ENTRIES
    ]
    drifted = support.make_partitions_bin(entries=drifted_entries)
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = drifted
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "differs from the qualified layout",
    )
    assert transport.writes == []


def test_refuses_unreadable_partition_table(installed_package) -> None:
    root, payload, _manifest = installed_package
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = b"\x00" * 3072  # garbage: not erased, not a table
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "unreadable/unknown",
    )
    assert transport.writes == []


def test_never_assumes_blank_on_partial_erase(installed_package) -> None:
    root, payload, _manifest = installed_package
    # Partition table erased but otadata holds a live C9 sector -> unknown
    # state, must NOT be treated as factory blank.
    flash_map = {0xF000: b"\xC9" + b"\xFF" * (0x2000 - 1)}
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "never assumed blank",
    )
    assert transport.writes == []


def test_refuses_unpinned_esptool_without_port_touch(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(version="4.8.1")
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_ENVIRONMENT
    assert transport.calls == [["version"]]  # version gate first, no port ops


def test_broken_esptool_maps_to_environment_exit(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(version_fail=True)
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_ENVIRONMENT
    assert "availability check" in str(exc.value)


def test_esptool_failure_maps_to_flash_failed(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(fail_on_call=2)  # fail during security read
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert transport.writes == []


def test_read_back_mismatch_fails(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(corrupt_store=True)
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "read-back" in str(exc.value)
    # F4: verification failure must NEVER reset the board.
    assert transport.resets == []
    assert not any(call[0] == "reset" for call in transport.calls)


def test_install_sequence_writes_then_reads_then_single_reset(installed_package) -> None:
    """F4: the order is provably all writes → all read-backs → one reset."""
    root, _payload, manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=True,
    ) == inst.EXIT_OK
    ops = [call[0] for call in transport.calls]
    # exactly one reset, and it is the final operation
    assert ops.count("reset") == 1
    reset_index = ops.index("reset")
    assert reset_index == len(ops) - 1
    assert transport.resets == ["/dev/cu.usbmodem1"]
    # all four writes precede the verification reads
    write_indices = [i for i, op in enumerate(ops) if op == "write-flash"]
    assert len(write_indices) == 4
    last_write = write_indices[-1]
    # the reads between the last write and the reset are exactly the four
    # manifest ranges, in manifest order
    by_role = {i["role"]: i for i in manifest["images"]}
    expected = [(by_role[role]["offset"], by_role[role]["size"])
                for role in inst.IMAGE_ROLES]
    verify_reads = [
        (call[2], call[3])
        for call in transport.calls[last_write + 1:reset_index]
        if call[0] == "read-flash"
    ]
    assert verify_reads == expected
    # the success log claims the reset because the reset actually happened
    assert any("device was reset" in line for line in lines)


def test_reset_failure_after_verification_is_reported_without_ok(
    installed_package,
) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(fail_reset=True)
    a, lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "manual power cycle" in str(exc.value)
    assert transport.resets == []  # the reset never completed
    assert not any("install: OK" in line for line in lines)
    # all writes and verification reads still completed before the reset
    assert len(transport.writes) == 4


def test_write_failure_stops_immediately(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(fail_on_write=1)  # fail on partition table
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert [w[0] for w in transport.writes] == [0x0]
    # F4: a failure before verification means no reset was ever attempted
    assert transport.resets == []
    assert not any(call[0] == "reset" for call in transport.calls)


def test_install_requires_explicit_port(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install("", inst.HARDWARE_CLASS, dry_run=True, confirm_replace=True)
    assert exc.value.code == inst.EXIT_USAGE
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install("../dev/tty", inst.HARDWARE_CLASS, dry_run=True,
                      confirm_replace=True)
    assert exc.value.code == inst.EXIT_USAGE


def test_install_rejects_unknown_board(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install("/dev/cu.usbmodem1", "esp32-devkit", dry_run=True,
                      confirm_replace=True)
    assert exc.value.code == inst.EXIT_USAGE


# ---------------------------------------------------------------------------
# inspect: strictly read-only
# ---------------------------------------------------------------------------


def test_inspect_never_writes(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    assert a.cmd_inspect("/dev/cu.usbmodem1") == inst.EXIT_OK
    assert transport.writes == []
    ops = {call[0] for call in transport.calls}
    assert "read-flash" in ops and "flash-id" in ops and "get-security-info" in ops
    assert not any("write" in call[0] for call in transport.calls)
    assert any("state=factory-blank" in line for line in lines)


def test_inspect_reports_dev_match(installed_package) -> None:
    root, payload, _manifest = installed_package
    transport = support.FakeTransport(flash_map=support.blank_device_table(payload))
    a, lines = app(root, transport=transport)
    assert a.cmd_inspect("/dev/cu.usbmodem1") == inst.EXIT_OK
    assert any("state=dev-match" in line for line in lines)


def test_inspect_invalid_port(installed_package) -> None:
    root, _payload, _manifest = installed_package
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_inspect("")
    assert exc.value.code == inst.EXIT_USAGE


# ---------------------------------------------------------------------------
# esptool transport plumbing
# ---------------------------------------------------------------------------


class CapturedRun:
    def __init__(self, output: str) -> None:
        self.output = output
        self.argvs: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        import subprocess as sp

        self.argvs.append(list(argv))
        return sp.CompletedProcess(argv, 0, stdout=self.output, stderr="")


def test_transport_argv_vectors_are_fixed(monkeypatch) -> None:
    # VERSION-MATCHED fixture: exact esptool 5.4.0 identification output
    # (padded "Chip type:" line from __init__.py:568-572 in the pinned
    # sdist — the legacy "Chip is" form no longer appears in v5 output).
    captured = CapturedRun(
        support.esptool_540_flash_id_output()
        + "Security Information:\nFlags: 0x00\nSecure Boot: Disabled\n"
        "Flash Encryption: Disabled\n"
    )
    monkeypatch.setattr(inst.subprocess, "run", captured)
    transport = inst.EsptoolTransport(["py312", "-m", "esptool"])
    assert transport.version() == "5.4.0"
    assert transport.flash_id("/dev/ttyX") == ("esp32s3", 8_388_608)
    flags = transport.security_flags("/dev/ttyX")
    assert flags == {"secure_boot": False, "flash_encryption": False}
    assert captured.argvs[0] == ["py312", "-m", "esptool", "version"]
    head = captured.argvs[1]
    assert head[:5] == ["py312", "-m", "esptool", "--chip", "esp32s3"]
    assert "--port" in head and "/dev/ttyX" in head
    assert head[-1] == "flash-id"
    # ALL writes keep the board in the bootloader: --after no-reset.
    write = CapturedRun("Wrote 1024 bytes")
    monkeypatch.setattr(inst.subprocess, "run", write)
    transport.write_flash("/dev/ttyX", 0x8000, Path("/tmp/x.bin"))
    argv = write.argvs[0]
    assert "write-flash" in argv
    assert ["--flash-mode", "dio"] <= argv
    assert ["--flash-size", "8MB"] <= argv
    assert ["--flash-freq", "80m"] <= argv
    assert "0x8000" in argv and "/tmp/x.bin" in argv
    assert ["--after", "no-reset"] <= argv
    assert ["--after", "hard-reset"] not in argv
    # The only reset: read-only flash-id with --after hard-reset
    # (CLI form verified against the pinned 5.4.0 sdist).
    reset = CapturedRun(support.esptool_540_flash_id_output())
    monkeypatch.setattr(inst.subprocess, "run", reset)
    transport.reset("/dev/ttyX")
    reset_argv = reset.argvs[0]
    assert reset_argv[-1] == "flash-id"
    assert ["--before", "default-reset"] <= reset_argv
    assert ["--after", "hard-reset"] <= reset_argv


def test_transport_identifies_esp32s3_from_540_output(monkeypatch) -> None:
    """F3 regression: identification succeeds on the real 5.4.0 output."""
    captured = CapturedRun(support.esptool_540_flash_id_output())
    monkeypatch.setattr(inst.subprocess, "run", captured)
    transport = inst.EsptoolTransport(["esptool"])
    assert transport.flash_id("/dev/ttyX") == ("esp32s3", 8_388_608)


def test_transport_chip_line_accepts_both_identification_forms() -> None:
    """_chip_line() finds 'Chip type:' (5.x) and legacy 'Chip is' lines."""
    assert (
        inst.EsptoolTransport._chip_line(support.ESPTOOL_540_FLASH_ID_S3)
        == support.ESPTOOL_540_CHIP_LINE_S3
    )
    assert (
        inst.EsptoolTransport._chip_line("Chip is ESP32-S3 (esptool 4.x)\n")
        == "Chip is ESP32-S3 (esptool 4.x)"
    )
    assert inst.EsptoolTransport._chip_line("no identification here") == (
        "<no 'Chip type:'/'Chip is' line>"
    )


def test_transport_rejects_non_s3_output(monkeypatch) -> None:
    # F3 regression: 5.4.0-format ESP32-C3 output is still rejected.
    captured = CapturedRun(support.esptool_540_flash_id_output(
        support.ESPTOOL_540_CHIP_LINE_C3, flash_size="4MB"
    ))
    monkeypatch.setattr(inst.subprocess, "run", captured)
    transport = inst.EsptoolTransport(["esptool"])
    with pytest.raises(inst.EsptoolFailure):
        transport.flash_id("/dev/ttyX")


def test_transport_nonzero_exit_raises(monkeypatch) -> None:
    def fail(argv, **kwargs):
        import subprocess as sp

        return sp.CompletedProcess(argv, 2, stdout="", stderr="Failed to connect")

    monkeypatch.setattr(inst.subprocess, "run", fail)
    transport = inst.EsptoolTransport(["esptool"])
    with pytest.raises(inst.EsptoolFailure) as exc:
        transport.version()
    assert "Failed to connect" in str(exc.value)


def test_resolve_esptool_command_never_uses_ambient(monkeypatch) -> None:
    monkeypatch.delenv("VDOG_ESPTOOL_PYTHON", raising=False)
    assert inst.resolve_esptool_command("/opt/py312/bin/python") == [
        "/opt/py312/bin/python", "-m", "esptool"
    ]
    monkeypatch.setenv("VDOG_ESPTOOL_PYTHON", "/env/py312/bin/python")
    assert inst.resolve_esptool_command(None) == ["/env/py312/bin/python", "-m", "esptool"]
    monkeypatch.delenv("VDOG_ESPTOOL_PYTHON")

    class NoFinder:
        @staticmethod
        def find_spec(name):
            return None

    monkeypatch.setattr(inst.importlib.util, "find_spec", NoFinder.find_spec)
    with pytest.raises(inst.InstallerError) as exc:
        inst.resolve_esptool_command(None)
    assert exc.value.code == inst.EXIT_ENVIRONMENT
    assert "esptool" in str(exc.value)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def test_main_check_and_ports(installed_package) -> None:
    root, _payload, _manifest = installed_package
    outputs: list[str] = []
    assert inst.main(
        ["--package", str(root), "check"], out=outputs.append
    ) == inst.EXIT_OK
    assert inst.main(
        ["--package", str(root), "ports"],
        out=outputs.append,
        ports_provider=lambda: [("/dev/cu.usbmodemZ", "Z")],
    ) == inst.EXIT_OK


def test_main_install_dry_run_exit_ok(installed_package) -> None:
    root, _payload, _manifest = installed_package
    assert inst.main(
        ["--package", str(root), "install", "--port", "/dev/cu.usbmodemQ",
         "--board", inst.HARDWARE_CLASS, "--dry-run"],
        out=lambda m: None,
    ) == inst.EXIT_OK


def test_main_refusal_exit_code(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(flash_size=4_194_304)
    assert inst.main(
        ["--package", str(root), "install", "--port", "/dev/cu.usbmodemQ",
         "--board", inst.HARDWARE_CLASS, "--confirm-replace"],
        transport=transport,
        out=lambda m: None,
    ) == inst.EXIT_REFUSED


# ---------------------------------------------------------------------------
# Drift check: install.py's compact validators agree with contract.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,mutate,substring,_sv",
    support.MANIFEST_MUTATIONS,
    ids=[m[0] for m in support.MANIFEST_MUTATIONS],
)
def test_installer_manifest_validators_match_contract(name, mutate, substring, _sv) -> None:
    base = support.valid_manifest_doc()
    assert inst.validate_manifest(base) == []
    mutated = support.valid_manifest_doc()
    mutate(mutated)
    contract_errors = contract.validate_manifest(mutated)
    installer_errors = inst.validate_manifest(mutated)
    assert bool(contract_errors) == bool(installer_errors), (
        f"drift on mutation {name!r}: contract={contract_errors!r} "
        f"installer={installer_errors!r}"
    )


def test_installer_valid_pr_and_main_manifests() -> None:
    assert inst.validate_manifest(
        support.valid_manifest_doc(
            kind="pr", sha=support.FULL_SHA_A, pr_number=7, base_sha=support.FULL_SHA_B
        )
    ) == []
    assert inst.validate_manifest(
        support.valid_manifest_doc(kind="main", sha=support.FULL_SHA_B)
    ) == []


def test_installer_rejects_pr_base_equals_head() -> None:
    doc = support.valid_manifest_doc(
        kind="pr", sha=support.FULL_SHA_A, pr_number=7, base_sha=support.FULL_SHA_B
    )
    doc["source"]["base_sha"] = doc["source"]["sha"]
    assert contract.validate_manifest(doc), "contract must reject base==head"
    assert inst.validate_manifest(doc), "installer validator must reject base==head"


@pytest.mark.parametrize(
    "name,mutate,substring",
    support.LAYOUT_MUTATIONS,
    ids=[m[0] for m in support.LAYOUT_MUTATIONS],
)
def test_installer_layout_validators_match_contract(name, mutate, substring) -> None:
    base = support.valid_layout_doc()
    assert inst.validate_flash_layout(base) == []
    mutated = support.valid_layout_doc()
    mutate(mutated)
    assert bool(contract.validate_flash_layout(mutated)) == bool(
        inst.validate_flash_layout(mutated)
    ), f"layout drift on mutation {name!r}"


def test_installer_constants_mirror_contract() -> None:
    assert inst.ESPTOOL_VERSION == contract.TOOLCHAIN_ESPTOOL_VERSION == "5.4.0"
    assert inst.TARGET == contract.TARGET
    assert inst.EXPECTED_FLASH_BYTES == contract.EXPECTED_FLASH_BYTES
    assert inst.FLASH_MODE == contract.FLASH_MODE
    assert inst.FLASH_SIZE == contract.FLASH_SIZE
    assert inst.FLASH_FREQ == contract.FLASH_FREQ
    assert inst.REQUIRED_FILES == frozenset(contract.PACKAGE_REQUIRED_FILES)
    assert inst.SELF_EXCLUDED == frozenset(contract.PACKAGE_SELF_EXCLUDED_FROM_MANIFEST)
    assert inst.ROLE_FILES == {
        role: f"images/{name}" for role, name in contract.ROLE_BUILD_FILE.items()
    }
    assert inst.IMAGE_ROLES == contract.IMAGE_ROLES
    assert inst.PARTITION_TABLE_MAX_BYTES == contract.PARTITION_TABLE_MAX_BYTES
