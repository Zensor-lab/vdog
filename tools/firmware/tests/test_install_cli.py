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
        session_backend=kw.pop("session_backend", transport),
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
    # PR-R2 contract in the plan output: one live verified connection carries
    # writes and the single reset; no per-command CLI reconnect is promised.
    invokes = [line for line in lines if line.startswith("invoke:")]
    write_invokes = [line for line in invokes if "write-flash" in line]
    assert len(write_invokes) == 4
    assert all("live verified connection" in line for line in write_invokes)
    assert not any("--after" in line for line in write_invokes)
    reset_lines = [line for line in lines
                   if line.startswith("reset: exactly one explicit hard reset")]
    assert len(reset_lines) == 1
    assert any(line.startswith("session: ONE live verified esptool 5.4.0 connection")
               for line in lines)


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
               or "reset" in call or "close" in call
               or "read-mac" in call or "connect" in call
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


# ---------------------------------------------------------------------------
# P0-1: the packaged-installer replacement gate (semantic + byte-exact)
# ---------------------------------------------------------------------------


def test_refuses_altered_subtype_with_matching_geometry_and_valid_md5(
    installed_package,
) -> None:
    """A device table with perfect geometry, erased padding and a VALID MD5
    but an altered semantic field is refused (not replaceable)."""
    root, payload, _manifest = installed_package
    for index, want_subtype in ((5, 0x81), (3, 0x00)):  # storage→fat, app0→factory
        altered = [
            (name, type_, want_subtype if i == index else subtype, offset, size)
            for i, (name, type_, subtype, offset, size) in enumerate(support.BASELINE_ENTRIES)
        ]
        table = support.make_partitions_bin(entries=altered)  # recomputes a valid MD5
        flash_map = dict(support.blank_device_table(payload))
        flash_map[0x8000] = table
        transport = _install_expect(
            installed_package, support.FakeTransport(flash_map=flash_map),
            inst.EXIT_REFUSED, "differs from the qualified layout", "subtype",
        )
        assert transport.writes == []


def test_refuses_altered_flags(installed_package) -> None:
    """Flags are a semantic field too: an ENCRYPTED-flagged entry with
    otherwise-identical geometry and a valid MD5 is refused."""
    root, payload, _manifest = installed_package
    flagged = [
        (*entry, 0x1) if entry[0] == "app0" else entry
        for entry in support.BASELINE_ENTRIES
    ]
    table = support.make_partitions_bin(entries=flagged)
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = table
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "differs from the qualified layout", "flags",
    )
    assert transport.writes == []


def test_refuses_duplicate_labels_in_device_table(installed_package) -> None:
    root, payload, _manifest = installed_package
    dup = list(support.BASELINE_ENTRIES)
    dup[2] = ("nvs", 1, 0x01, 0x11000, 0x1000)  # phy_init relabelled "nvs"
    table = support.make_partitions_bin(entries=dup)
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = table
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "unreadable/unknown", "duplicate label",
    )
    assert transport.writes == []


def test_refuses_non_erased_builder_trailer_padding(installed_package) -> None:
    """The old parser only checked the MD5 bytes; any other byte in the
    trailer slot went unnoticed. The hardened parser refuses non-erased
    padding even when the MD5 itself still validates."""
    root, payload, _manifest = installed_package
    table = bytearray(support.make_partitions_bin())
    table[6 * 32 + 5] ^= 0x01  # opaque builder-slot padding, MD5 untouched
    flash_map = dict(support.blank_device_table(payload))
    flash_map[0x8000] = bytes(table)
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "non-erased builder trailer padding",
    )
    assert transport.writes == []


def test_refuses_short_nvs_read_never_reads_as_blank(installed_package) -> None:
    """P0-1: a truncated NVS read must not pass as erased (provisioned
    boards could otherwise slip through)."""
    root, payload, _manifest = installed_package
    flash_map = dict(support.blank_device_table(payload))
    transport = _install_expect(
        installed_package,
        support.FakeTransport(flash_map=flash_map,
                              short_read_at=(0x9000, 0x6000), short_read_by=64),
        inst.EXIT_FLASH_FAILED, "expected exactly 24576",
    )
    assert transport.writes == []


def test_refuses_short_ota_read(installed_package) -> None:
    root, payload, _manifest = installed_package
    flash_map = dict(support.blank_device_table(payload))
    transport = _install_expect(
        installed_package,
        support.FakeTransport(flash_map=flash_map,
                              short_read_at=(0xF000, 0x2000), short_read_by=16),
        inst.EXIT_FLASH_FAILED, "expected exactly 8192",
    )
    assert transport.writes == []


def test_refuses_short_read_on_the_blank_path(installed_package) -> None:
    """Even the factory-blank route requires exact reads: a truncated all-FF
    NVS read is NOT blank evidence."""
    root, _payload, _manifest = installed_package
    transport = _install_expect(
        installed_package,
        support.FakeTransport(short_read_at=(0x9000, 0x6000), short_read_by=1),
        inst.EXIT_FLASH_FAILED, "short reads are never treated as blank",
    )
    assert transport.writes == []


# ---------------------------------------------------------------------------
# P0-2: on-device otadata parsed against the pinned v6.1 layout
# ---------------------------------------------------------------------------


def test_reinstall_after_real_first_boot_succeeds(installed_package) -> None:
    """blank -> install -> first-boot (v6.1 select records) -> inspect ->
    reinstall, all through the public CLI surface."""
    root, payload, _manifest = installed_package
    transport = support.FakeTransport()
    a, lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=True,
    ) == inst.EXIT_OK
    assert transport.resets == ["/dev/cu.usbmodem1"]

    # Device now holds the written images; the first boot leaves ONE valid
    # esp_ota_select_entry_t per sector (pinned v6.1).
    transport.flash_map = dict(
        support.blank_device_table(payload, otadata=support.first_boot_otadata(1))
    )
    a2, lines2 = app(root, transport=transport)
    assert a2.cmd_inspect("/dev/cu.usbmodem1") == inst.EXIT_OK
    assert any("state=dev-match" in line for line in lines2)

    a3, lines3 = app(root, transport=transport)
    assert a3.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=True,
    ) == inst.EXIT_OK
    # The reinstall rewrote the packaged (erased) initializer over the records.
    assert len(transport.writes) == 8  # four original + four reinstall
    assert transport.flash_map[0xF000] == b"\xFF" * 0x2000


def test_refuses_corrupted_first_boot_record(installed_package) -> None:
    root, payload, _manifest = installed_package
    broken = bytearray(support.first_boot_otadata(1))
    broken[30] ^= 0xFF  # corrupt the stored crc of the sector-0 record
    flash_map = dict(support.blank_device_table(payload, otadata=bytes(broken)))
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "crc32",
    )
    assert transport.writes == []


def test_refuses_corrupted_record_with_legacy_c9_first_byte(installed_package) -> None:
    """The retired single-byte heuristic would have called this valid; strict
    v6.1 parsing must refuse it."""
    root, payload, _manifest = installed_package
    c9 = support.make_ota_data([b"\xc9" + b"\xAA" * 31, None])
    flash_map = dict(support.blank_device_table(payload, otadata=c9))
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "sector 0",
    )
    assert transport.writes == []


def test_refuses_state_outside_v61_enum(installed_package) -> None:
    root, payload, _manifest = installed_package
    record = bytearray(support.make_ota_record(2, 0x00000002))
    record[24:28] = (0x00000077).to_bytes(4, "little")  # undefined ota_state
    record[28:32] = support.esp_crc32_le(
        0xFFFFFFFF, bytes(record[0:4])).to_bytes(4, "little")  # crc now valid
    flash_map = dict(support.blank_device_table(
        payload, otadata=support.make_ota_data([bytes(record), None])))
    transport = _install_expect(
        installed_package, support.FakeTransport(flash_map=flash_map),
        inst.EXIT_REFUSED, "ota_state",
    )
    assert transport.writes == []


def test_check_rejects_prebaked_packaged_ota_initializer(tmp_path: Path) -> None:
    """install.py check refuses a package whose ota_data_initial.bin carries
    pre-baked records — even perfectly self-consistent, re-signed ones."""
    zip_path, _sha, payload, _manifest = support.package_from_build_dir(tmp_path)
    payload = dict(payload)
    payload["images/ota_data_initial.bin"] = support.first_boot_otadata(1)
    payload = support.with_resolved_hashes(payload)
    forged = support.rezip(tmp_path / "forged.zip", payload)
    import zipfile

    with zipfile.ZipFile(forged) as archive:
        archive.extractall(tmp_path / "out")
    root = next(iter((tmp_path / "out").iterdir()))
    a, _lines = app(root)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_check()
    assert exc.value.code == inst.EXIT_PACKAGE_INVALID
    assert "fully erased" in str(exc.value)


# ---------------------------------------------------------------------------
# P1-1: one verified download session; port identity is never followed
# ---------------------------------------------------------------------------


def test_install_uses_exactly_one_session_establishing_reset(
    installed_package,
) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    a, _lines = app(root, transport=transport)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
        dry_run=False, confirm_replace=True,
    ) == inst.EXIT_OK
    # classification (flash-id + security + 3 reads) + 4 writes + 4 verify
    # reads + the single reset: only the FIRST operation may reset.
    assert transport.befores[0] == "default-reset"
    assert set(transport.befores[1:]) == {"no-reset"}
    assert transport.befores.count("default-reset") == 1
    assert transport.befores[-1] == "no-reset"  # the final --after hard-reset step
    assert len(transport.resets) == 1


def test_mid_session_port_loss_stops_writes_and_never_resets(
    installed_package,
) -> None:
    """The port vanishing mid-operation (native USB re-enumeration) aborts
    with no reset and never continues on another path."""
    root, _payload, _manifest = installed_package
    # calls so far when the port dies: version, flash-id, read-mac, connect,
    # table and otadata reads — abort as the NVS classification read starts.
    transport = support.FakeTransport(drop_port_after=6)
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "disappeared mid-session" in str(exc.value)
    assert transport.writes == []      # stopped before any write completed
    assert transport.resets == []      # a lost port is never reset through


def test_mid_session_port_loss_after_writes_stops_before_reset(
    installed_package,
) -> None:
    root, _payload, _manifest = installed_package
    # calls so far when the port dies: version, flash-id, read-mac, connect,
    # 3 classify reads, 2 writes — abort as the third write attempts to start.
    transport = support.FakeTransport(drop_port_after=9)
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "disappeared mid-session" in str(exc.value)
    assert len(transport.writes) == 2  # no writes continued past the loss
    assert transport.resets == []      # NEVER reset after an interrupted write


def test_inspect_port_identity_loss_is_reported(installed_package) -> None:
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(drop_port_after=2)
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_inspect("/dev/cu.usbmodem1")
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "disappeared mid-session" in str(exc.value)


def test_installer_constants_mirror_contract_ota_and_partition_fields() -> None:
    """P0-1/P0-2 mirror-lockstep: the installer's compact copies match the
    contract authority exactly."""
    assert inst.CSV_SUBTYPE_CODES == contract.CSV_SUBTYPE_CODES
    assert inst.OTA_IMG_STATE_NAMES == contract.OTA_IMG_STATE_NAMES
    assert inst.OTA_SELECT_ENTRY_SIZE == contract.OTA_SELECT_ENTRY_SIZE
    assert inst.OTA_DATA_SECTOR_SIZE == contract.OTA_DATA_SECTOR_SIZE
    for sample in (b"", b"\x01\x02\x03\x04", bytes(range(256))):
        assert inst.esp_ota_crc32(sample) == contract.esp_ota_crc32(sample)
    # the same on-device image is accepted/refused identically by both layers
    good = support.first_boot_otadata(9)
    assert contract.validate_ota_data_records(good) == []
    inst.require_ota_data_records(good)  # must not raise
    bad = bytearray(good)
    bad[31] ^= 0xFF
    assert contract.validate_ota_data_records(bytes(bad))
    with pytest.raises(inst.InstallerError):
        inst.require_ota_data_records(bytes(bad))


# ---------------------------------------------------------------------------
# PR-R2: classification, consent, writes and verification on ONE connection
# ---------------------------------------------------------------------------


def test_same_path_device_swap_after_preflight_writes_nothing(
    installed_package,
) -> None:
    """A different ESP32-S3 taking the same path after the preflight probe
    is caught by the MAC pin the live connection must reproduce — abort
    with zero writes, never a reset."""
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport(
        preflight_mac="aa:bb:cc:dd:ee:ff", swap_mac="11:22:33:44:55:66",
    )
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_REFUSED
    assert "same-path device swap" in str(exc.value)
    assert transport.writes == []
    assert transport.resets == []


def test_identity_and_classification_precede_consent(installed_package) -> None:
    """Consent is only ever asked AFTER the single connection was opened and
    identity-verified and classification completed — on that same
    connection — and before it, nothing was written."""
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    seen: dict[str, object] = {}

    def input_fn(prompt: str) -> str:
        seen["writes_at_consent"] = list(transport.writes)
        seen["ops_at_consent"] = [call[0] for call in transport.calls]
        return "install"

    a, _lines = app(root, transport=transport, input_fn=input_fn)
    assert a.cmd_install(
        "/dev/cu.usbmodem1", inst.HARDWARE_CLASS, dry_run=False, confirm_replace=False,
    ) == inst.EXIT_OK
    assert seen["writes_at_consent"] == []
    ops = seen["ops_at_consent"]
    assert "connect" in ops and "read-mac" in ops
    assert ops.index("connect") < len(ops)  # connection opened before consent
    assert transport.calls[-2][0] == "reset"  # single reset, then close


def test_short_read_back_aborts_without_reset(installed_package) -> None:
    """A verification read shorter than the range is fatal — never treated
    as matching — and the board is NOT reset."""
    root, payload, _manifest = installed_package
    pt_size = len(payload["images/partitions.bin"])
    transport = support.FakeTransport(
        short_read_at=(0x8000, pt_size), short_read_by=64,
        short_read_when="after_writes",
    )
    a, _lines = app(root, transport=transport)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "expected exactly" in str(exc.value)
    assert transport.resets == []


def test_transport_read_mac_argv(monkeypatch) -> None:
    captured = CapturedRun(
        support.esptool_540_flash_id_output() + "\nMAC: AA:BB:CC:DD:EE:FF\n"
    )
    monkeypatch.setattr(inst.subprocess, "run", captured)
    transport = inst.EsptoolTransport(["esptool"])
    transport.flash_id("/dev/ttyX")  # establish the preflight session
    assert transport.read_mac("/dev/ttyX") == "aa:bb:cc:dd:ee:ff"
    argv = captured.argvs[-1]
    assert argv[-1] == "read-mac"
    assert _pair(argv, "--before", "no-reset")  # inside the established session


# ---------------------------------------------------------------------------
# PR-R2b: production esptool session backend, offline against the REAL
# library semantics (read_mac BASE_MAC-only, display-string flash size,
# flash_crypt_cnt parity) — the round-2 review reproduced these offline and
# these tests must keep passing against that behavior.
# ---------------------------------------------------------------------------


def _backend(**module_kw) -> tuple[inst.EsptoolSessionBackend, support.FakeEsptoolModule]:
    module = support.FakeEsptoolModule(**module_kw)
    return inst.EsptoolSessionBackend(esptool_module=module), module


def test_backend_connect_reads_identity_with_library_semantics() -> None:
    backend, module = _backend()
    record = backend.connect("/dev/ttyX", expect={})
    assert record == {"chip": "esp32s3", "flash_bytes": 8_388_608,
                      "mac": "00:11:22:33:44:55",
                      "secure_boot": False, "flash_encryption": False}
    assert module.detect_calls[0]["connect_mode"] == "default-reset"


def test_backend_flash_encryption_is_crypt_cnt_parity_not_a_flag_bit() -> None:
    # Regression (PR-R2): bit 1 of flags is SECURE_BOOT_AGGRESSIVE_REVOKE
    # and must NOT read as flash encryption; encryption is odd bit parity
    # of flash_crypt_cnt, exactly as esptool's own checks compute it.
    revoked = support.FakeEspConnection(security={"flags": 0x2, "flash_crypt_cnt": 0})
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=revoked))
    record = backend.connect("/dev/ttyX", expect={})
    assert record["flash_encryption"] is False and record["secure_boot"] is False
    encrypted = support.FakeEspConnection(
        security={"flags": 0x1, "flash_crypt_cnt": 0b0000_0111})
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=encrypted))
    record = backend.connect("/dev/ttyX", expect={})
    assert record["flash_encryption"] is True and record["secure_boot"] is True


def test_backend_refuses_when_mac_unavailable() -> None:
    no_mac = support.FakeEspConnection(mac=None)
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=no_mac))
    with pytest.raises(inst.EsptoolFailure, match="no BASE_MAC"):
        backend.connect("/dev/ttyX", expect={})


def test_backend_blocks_esptool_reconnect_reopen() -> None:
    """esptool's error-recovery closes and REOPENS the port; the backend
    denies any reopen after connect so a retry can never address a
    different board on the same path."""
    backend, module = _backend()
    backend.connect("/dev/ttyX", expect={})
    with pytest.raises(inst.EsptoolFailure, match="never reconnects"):
        module.esp.open()  # what esptool's reconnect would call


def test_backend_pins_the_api_interpreter_version() -> None:
    """The --esptool_python override pins only the CLI subprocess; the API
    backend must independently refuse any interpreter whose esptool build
    is not the qualified 5.4.0."""
    for bad in ("4.9.9", None):
        backend, _module = _backend(version=bad)
        with pytest.raises(inst.EsptoolFailure, match="not the qualified"):
            backend.connect("/dev/ttyX", expect={})


def test_backend_rejects_unusable_flash_size() -> None:
    backend, _module = _backend(flash_size="Unknown")
    with pytest.raises(inst.EsptoolFailure, match="cannot detect flash size"):
        backend.connect("/dev/ttyX", expect={})


def test_backend_initializes_flash_from_fresh_rom() -> None:
    """PR-R3 P0: a fresh detect_chip leaves the ROM loader; connect() must
    replicate the pinned CLI — upload the stub, attach SPI flash when the
    loader is still ROM, configure flash parameters — all BEFORE the first
    flash read, on the same verified connection, reopen guard in force."""
    rom = support.FakeEspConnection(is_stub=False)
    module = support.FakeEsptoolModule(esp=rom, stub_upload_returns_rom=True)
    backend = inst.EsptoolSessionBackend(esptool_module=module)
    backend.connect("/dev/ttyX", expect={})
    assert module.stub_uploads == 1
    assert rom.attachments == [0]                 # ROM fallback attaches flash
    assert rom.params_configured == [inst.FLASH_SIZE]
    rom.read_flash(0x8000, 0xC00)                 # first layout read
    order = rom.calls + []                        # calls recorded in order
    seq = [c for c in rom.calls]
    assert seq.index("run_stub") < seq.index("flash_spi_attach(0)")
    assert seq.index("flash_spi_attach(0)") < seq.index("set_flash_params(8MB)")
    with pytest.raises(inst.EsptoolFailure, match="never reconnects"):
        rom.open()                                # guard still in force


def test_backend_loaded_stub_skips_rom_attach_but_still_sets_params() -> None:
    rom = support.FakeEspConnection(is_stub=False)
    module = support.FakeEsptoolModule(esp=rom)   # stub upload succeeds
    backend = inst.EsptoolSessionBackend(esptool_module=module)
    backend.connect("/dev/ttyX", expect={})
    assert rom.attachments == []                  # stub manages attachment
    assert rom.params_configured == [inst.FLASH_SIZE]


def test_backend_wrong_chip_reports_name_without_crash() -> None:
    """PR-R3: the wrong-chip branch used to format the name after clearing
    the connection (AttributeError on None)."""
    c3 = support.FakeEspConnection(chip_name="ESP32-C3")
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=c3))
    with pytest.raises(inst.EsptoolFailure, match="not an ESP32-S3: 'ESP32-C3'"):
        backend.connect("/dev/ttyX", expect={})
    assert c3.closed == 1


def test_backend_requires_complete_security_report() -> None:
    incomplete = support.FakeEspConnection(security={"flags": 0})  # no counter!
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=incomplete))
    with pytest.raises(inst.EsptoolFailure, match="security report incomplete"):
        backend.connect("/dev/ttyX", expect={})
    malformed = support.FakeEspConnection(
        security={"flags": "zero", "flash_crypt_cnt": 0})
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=malformed))
    with pytest.raises(inst.EsptoolFailure, match="security report malformed"):
        backend.connect("/dev/ttyX", expect={})


@pytest.mark.parametrize(
    "security",
    [
        {"flags": 0.5, "flash_crypt_cnt": 0},      # int(0.5) == 0: coercion
        {"flags": 0, "flash_crypt_cnt": 0.5},      #  would silently read 0
        {"flags": True, "flash_crypt_cnt": 0},     # bool is an int subclass
        {"flags": 0, "flash_crypt_cnt": False},    # True/False are not reports
        {"flags": "0", "flash_crypt_cnt": 0},      # digits are not integers
    ],
    ids=["flags-float", "counter-float", "flags-bool", "counter-bool",
         "flags-string"],
)
def test_backend_rejects_non_integer_security_fields(security) -> None:
    """PR B P2: strict field types — a float/bool/string security report is
    malformed and refused, never coerced (0.5 must not read as 0, True must
    not read as 1, "0" must not read as unprotected)."""
    esp = support.FakeEspConnection(security=security)
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=esp))
    with pytest.raises(inst.EsptoolFailure, match="security report malformed"):
        backend.connect("/dev/ttyX", expect={})
    assert esp.closed >= 1


def test_install_refuses_incomplete_security_with_zero_writes(installed_package) -> None:
    """Through the public CLI: unknown protection state is never treated as
    unprotected — zero writes, zero resets."""
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()  # preflight mac == backend mac
    esp = support.FakeEspConnection(security={"flags": 0})
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=esp))
    a, _lines = app(root, transport=transport, session_backend=backend)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "security report incomplete" in str(exc.value)
    assert transport.writes == [] and esp.writes == []
    assert transport.resets == [] and esp.resets == 0


def test_native_transfer_errors_get_installer_codes(installed_package) -> None:
    """PR-R3 P1: native esptool/pyserial exceptions must surface as the
    CLI's failure codes — never a traceback — with the session closed and
    no reset after a failed write."""
    root, _payload, _manifest = installed_package
    transport = support.FakeTransport()
    esp = support.FakeEspConnection()
    esp.fail_write = RuntimeError("simulated pyserial OSError")
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=esp))
    a, _lines = app(root, transport=transport, session_backend=backend)
    with pytest.raises(inst.InstallerError) as exc:
        a.cmd_install(
            "/dev/cu.usbmodem1", inst.HARDWARE_CLASS,
            dry_run=False, confirm_replace=True,
        )
    assert exc.value.code == inst.EXIT_FLASH_FAILED
    assert "RuntimeError" in str(exc.value)
    assert esp.resets == 0 and transport.resets == []
    assert esp.closed >= 1


def test_native_reset_error_becomes_power_cycle_guidance() -> None:
    """A native failure in the single reset still maps to the installer's
    reset-failure message and code, not a traceback."""
    esp = support.FakeEspConnection()
    esp.fail_reset = OSError("device disappeared")
    backend = inst.EsptoolSessionBackend(
        esptool_module=support.FakeEsptoolModule(esp=esp))
    backend.connect("/dev/ttyX", expect={})
    with pytest.raises(inst.EsptoolFailure, match="manual power cycle"):
        backend.reset("/dev/ttyX")


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
    # exactly one reset; the connection close follows it as the last op
    assert ops.count("reset") == 1
    reset_index = ops.index("reset")
    assert ops[-1] == "close"
    assert reset_index == len(ops) - 2
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


def _pair(argv: list[str], flag: str, value: str) -> bool:
    """True when ``flag`` is immediately followed by ``value`` (list ``<=`` is
    lexicographic comparison, NOT a sublist check — this is the real test)."""
    try:
        index = argv.index(flag)
    except ValueError:
        return False
    return index + 1 < len(argv) and argv[index + 1] == value


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
    # P1-1: the flash-id is the ONE session-establishing reset of the run.
    assert _pair(head, "--before", "default-reset")
    assert _pair(head, "--after", "no-reset")
    # All writes keep the board in the bootloader (no-reset) INSIDE the
    # established session: no further --before default-reset anywhere.
    write = CapturedRun("Wrote 1024 bytes")
    monkeypatch.setattr(inst.subprocess, "run", write)
    transport.write_flash("/dev/ttyX", 0x8000, Path("/tmp/x.bin"))
    argv = write.argvs[0]
    assert "write-flash" in argv
    assert _pair(argv, "--flash-mode", "dio")
    assert _pair(argv, "--flash-size", "8MB")
    assert _pair(argv, "--flash-freq", "80m")
    assert "0x8000" in argv and "/tmp/x.bin" in argv
    assert _pair(argv, "--after", "no-reset")
    assert _pair(argv, "--before", "no-reset"), \
        "mid-session writes must never reset into the bootloader again"
    assert not _pair(argv, "--before", "default-reset")
    # The only reset: read-only flash-id with --after hard-reset, still on the
    # verified session (CLI form verified against the pinned 5.4.0 sdist).
    reset = CapturedRun(support.esptool_540_flash_id_output())
    monkeypatch.setattr(inst.subprocess, "run", reset)
    transport.reset("/dev/ttyX")
    reset_argv = reset.argvs[0]
    assert reset_argv[-1] == "flash-id"
    assert _pair(reset_argv, "--before", "no-reset")
    assert _pair(reset_argv, "--after", "hard-reset")
    # After reset() the session is closed: a fresh operation pays exactly one
    # new session-establishing default-reset.
    assert transport.session_port is None and not transport.session_verified
    fresh = CapturedRun(support.esptool_540_flash_id_output())
    monkeypatch.setattr(inst.subprocess, "run", fresh)
    transport.flash_id("/dev/ttyX")
    assert _pair(fresh.argvs[0], "--before", "default-reset")


def test_transport_standalone_reset_keeps_default_reset(monkeypatch) -> None:
    """A transport that never established a session still resets explicitly
    via --before default-reset (standalone CLI use stays functional)."""
    reset = CapturedRun(support.esptool_540_flash_id_output())
    monkeypatch.setattr(inst.subprocess, "run", reset)
    transport = inst.EsptoolTransport(["esptool"])
    transport.reset("/dev/ttyY")
    assert _pair(reset.argvs[0], "--before", "default-reset")
    assert _pair(reset.argvs[0], "--after", "hard-reset")


def test_transport_rejects_short_reads(monkeypatch, tmp_path) -> None:
    """P0-1 transport layer: esptool producing fewer bytes than requested is
    a hard transport failure, not an erased-looking buffer."""
    class ShortReadRun:
        def __init__(self, path: Path):
            self.argvs: list[list[str]] = []
            self.path = path

        def __call__(self, argv, **_kw):
            import subprocess
            self.argvs.append(list(argv))
            if "read-flash" in argv:
                out_file = Path(argv[argv.index("read-flash") + 3])
                out_file.write_bytes(b"\xFF" * 1023)  # 1 byte short of 1024
                stdout = "Readed 1023 bytes"
            else:
                stdout = support.esptool_540_flash_id_output()
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(inst.subprocess, "run", ShortReadRun(tmp_path))
    transport = inst.EsptoolTransport(["esptool"])
    transport.flash_id("/dev/ttyZ")  # establish a session
    with pytest.raises(inst.EsptoolFailure, match="expected exactly 1024"):
        transport.read_flash("/dev/ttyZ", 0x8000, 1024)
    # The failed session is torn down — no silent continuation.
    assert transport.session_port is None and not transport.session_verified


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
