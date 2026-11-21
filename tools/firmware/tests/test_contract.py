"""Contract validator tests: manifest/layout/build-metadata acceptance, the
JSON-Schema cross-check (contract.py and contracts/*.schema.json must accept
and reject the same fixtures), partition table and ESP image parsers, and
path safety. Covers master plan work packages 0.9.1/0.9.4 acceptance."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.firmware import contract
from tools.firmware.contract import ContractError

import support

REPO_ROOT = support.REPO_ROOT
SCHEMA_PATH = REPO_ROOT / "contracts" / "firmware-release-v1.schema.json"

jsonschema = pytest.importorskip("jsonschema", reason="dev lock provides jsonschema")


def schema_errors(doc: object) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [err.message for err in validator.iter_errors(doc)]


# ---------------------------------------------------------------------------
# Schema file itself and the acceptance side
# ---------------------------------------------------------------------------


def test_schema_file_is_valid_draft2020_12() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    "doc",
    [
        support.valid_manifest_doc(),
        support.valid_manifest_doc(
            kind="pr", sha=support.FULL_SHA_A, pr_number=7, base_sha=support.FULL_SHA_B
        ),
        support.valid_manifest_doc(kind="main", sha=support.FULL_SHA_B),
    ],
    ids=["local", "pr", "main"],
)
def test_valid_manifest_accepted_by_contract_and_schema(doc: dict) -> None:
    assert contract.validate_manifest(doc) == []
    assert schema_errors(doc) == []


def test_valid_flash_layout_accepted() -> None:
    assert contract.validate_flash_layout(support.valid_layout_doc()) == []


def test_non_dict_documents_rejected() -> None:
    assert contract.validate_manifest([])
    assert contract.validate_flash_layout(None)
    assert contract.validate_build_metadata("x")


# ---------------------------------------------------------------------------
# Mutation corpus: contract always rejects; schema-visible ones rejected by
# both (the "accept/reject the same fixtures" cross-check).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,mutate,substring,schema_visible",
    support.MANIFEST_MUTATIONS,
    ids=[m[0] for m in support.MANIFEST_MUTATIONS],
)
def test_manifest_mutations_rejected(
    name: str, mutate, substring: str, schema_visible: bool
) -> None:
    doc = support.valid_manifest_doc()
    mutate(doc)
    errors = contract.validate_manifest(doc)
    assert errors, f"contract accepted mutation {name!r}"
    assert any(substring.lower() in e.lower() for e in errors), (
        f"mutation {name!r}: no error mentions {substring!r} in {errors}"
    )
    s_errors = schema_errors(doc)
    if schema_visible:
        assert s_errors, f"schema accepted mutation {name!r} that it must reject"


@pytest.mark.parametrize(
    "name,mutate,substring",
    support.LAYOUT_MUTATIONS,
    ids=[m[0] for m in support.LAYOUT_MUTATIONS],
)
def test_flash_layout_mutations_rejected(name: str, mutate, substring: str) -> None:
    doc = support.valid_layout_doc()
    mutate(doc)
    errors = contract.validate_flash_layout(doc)
    assert errors, f"contract accepted layout mutation {name!r}"
    assert any(substring.lower() in e.lower() for e in errors)


def test_pr_identity_rules() -> None:
    doc = support.valid_manifest_doc(
        kind="pr", sha=support.FULL_SHA_A, pr_number=7, base_sha=support.FULL_SHA_B
    )
    assert contract.validate_manifest(doc) == []
    bad = copy.deepcopy(doc)
    bad["source"]["base_sha"] = bad["source"]["sha"]
    assert any("differ" in e for e in contract.validate_manifest(bad))
    bad2 = copy.deepcopy(doc)
    bad2["build_id"] = "main-" + support.SHA_A_12
    assert any("build_id" in e for e in contract.validate_manifest(bad2))
    bad3 = copy.deepcopy(doc)
    bad3["tag"] = "firmware-main-" + support.SHA_A_12
    assert any("tag" in e for e in contract.validate_manifest(bad3))


def test_main_identity_rules() -> None:
    doc = support.valid_manifest_doc(kind="main", sha=support.FULL_SHA_B)
    assert contract.validate_manifest(doc) == []
    no_tag = copy.deepcopy(doc)
    no_tag["tag"] = None
    assert any("tag" in e for e in contract.validate_manifest(no_tag))
    wrong_tag = copy.deepcopy(doc)
    wrong_tag["tag"] = "firmware-main-000000000000"
    assert any("tag" in e for e in contract.validate_manifest(wrong_tag))
    wrong_id = copy.deepcopy(doc)
    wrong_id["build_id"] = "pr-1-" + support.FULL_SHA_B[:12]
    assert any("build_id" in e for e in contract.validate_manifest(wrong_id))


# ---------------------------------------------------------------------------
# vdog-build-metadata-v1 (consumed contract)
# ---------------------------------------------------------------------------


def _meta(**overrides: object) -> dict:
    doc = {
        "schema": "vdog-build-metadata-v1",
        "firmware_version": "0.2.0-proto",
        "source_sha": "local",
        "build_id": "local",
        "environment": "vdog_xiao_sense_proto",
        "platform": "platformio/espressif32@8.0.0",
        "idf_version": "v6.1.0",
        "esptool_version": "5.4.0",
    }
    doc.update(overrides)
    return doc


def test_build_metadata_accepts_valid() -> None:
    assert contract.validate_build_metadata(_meta()) == []
    assert contract.validate_build_metadata(
        _meta(source_sha=support.FULL_SHA_A, build_id=f"pr-7-{support.SHA_A_12}")
    ) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_sha": ""},
        {"source_sha": "abc123"},
        {"source_sha": support.FULL_SHA_A.upper()},
        {"build_id": ""},
        {"build_id": "has space"},
        {"build_id": "x" * 65},
        {"environment": "other_env"},
        {"esptool_version": "4.8.1"},
        {"firmware_version": "0.3.0"},
        {"schema": "vdog-build-metadata-v0"},
    ],
    ids=[
        "empty-sha", "short-sha", "upper-sha", "empty-build-id", "space-build-id",
        "long-build-id", "env", "esptool", "version", "schema",
    ],
)
def test_build_metadata_rejects_invalid(overrides: dict) -> None:
    assert contract.validate_build_metadata(_meta(**overrides))


# ---------------------------------------------------------------------------
# Partition table CSV + binary (formats verified against the 0.2 baseline)
# ---------------------------------------------------------------------------


def test_repo_partition_csv_parses_to_baseline() -> None:
    text = (REPO_ROOT / "firmware/partitions/vdog_8mb_two_ota.csv").read_text(
        encoding="utf-8"
    )
    entries = contract.parse_partition_csv(text, where="repo csv")
    assert entries == support.BASELINE_PARTITIONS


def test_baseline_partition_binary_parses_and_cross_checks() -> None:
    data = support.make_partitions_bin()
    entries = contract.parse_partition_table_binary(data, where="synthetic")
    expected = contract.csv_entries_to_binary_maps(support.BASELINE_PARTITIONS)
    assert entries == expected
    assert (
        contract.cross_check_partition_set(
            support.BASELINE_PARTITIONS, entries, where="x"
        )
        == []
    )


def test_partition_binary_rejects_corrupt_md5() -> None:
    data = support.make_partitions_bin(corrupt_md5=True)
    with pytest.raises(ContractError) as exc:
        contract.parse_partition_table_binary(data, where="x")
    assert any("MD5 trailer" in e for e in exc.value.errors)


def test_partition_binary_rejects_nonzero_flags() -> None:
    data = bytearray(support.make_partitions_bin())
    data[28] = 0x01  # flags field of first entry
    with pytest.raises(ContractError) as exc:
        contract.parse_partition_table_binary(bytes(data), where="x")
    assert any("flags" in e or "MD5" in e for e in exc.value.errors)


def test_partition_binary_rejects_tail_garbage() -> None:
    data = bytearray(support.make_partitions_bin())
    data[0x100] = 0x00  # beyond the first free slot: must be erased
    with pytest.raises(ContractError) as exc:
        contract.parse_partition_table_binary(bytes(data), where="x")
    assert any("non-erased" in e for e in exc.value.errors)


def test_partition_binary_rejects_wrong_size() -> None:
    with pytest.raises(ContractError):
        contract.parse_partition_table_binary(b"\xFF" * 3071, where="x")


def test_partition_binary_rejects_entry_past_flash() -> None:
    entries = [("huge", 1, 0x02, 0x9000, 0x8000000)]
    with pytest.raises(ContractError) as exc:
        contract.parse_partition_table_binary(
            support.make_partitions_bin(entries), where="x"
        )
    assert any("exceeds flash" in e for e in exc.value.errors)


def test_cross_check_detects_divergence() -> None:
    entries = contract.parse_partition_table_binary(
        support.make_partitions_bin(), where="x"
    )
    other = [dict(e) for e in support.BASELINE_PARTITIONS]
    other[3]["size"] = 0x100000  # app0 shrunk only in the CSV
    errors = contract.cross_check_partition_set(other, entries, where="x")
    assert errors and any("app0" in e for e in errors)


def test_partition_csv_rejects_garbage() -> None:
    for bad in (
        "",
        "nvs, data, bogus, 0x9000, 0x6000,",
        "nvs, magic, nvs, 0x9000, 0x6000,",
        "nvs, data, nvs, notahex, 0x6000,",
        "nvs, data, nvs, 0x9000, 0,",
    ):
        with pytest.raises(ContractError):
            contract.parse_partition_csv(bad, where="x")


# ---------------------------------------------------------------------------
# OTA initial data
# ---------------------------------------------------------------------------


def test_ota_data_initial_accepts_erased() -> None:
    assert contract.validate_ota_data_initial(b"\xFF" * 0x2000) == []


def test_ota_data_initial_rejects_bad_sector_and_size() -> None:
    bad = bytearray(b"\xFF" * 0x2000)
    bad[0x1000] = 0x11  # second sector: neither erased nor 0xC9
    assert any("sector 1" in e for e in contract.validate_ota_data_initial(bytes(bad)))
    assert contract.validate_ota_data_initial(b"")
    assert contract.validate_ota_data_initial(b"\xFF" * 0x1001)


# ---------------------------------------------------------------------------
# ESP image container
# ---------------------------------------------------------------------------


def test_esp_image_accepts_synthetic_app_and_bootloader() -> None:
    for kind in ("app", "bootloader"):
        header = contract.parse_esp_image(
            support.make_esp_image(kind=kind), where=kind
        )
        assert header.chip_id == 9
        assert header.segments


def test_esp_image_rejects_wrong_chip_id() -> None:
    with pytest.raises(ContractError) as exc:
        contract.parse_esp_image(support.make_esp_image(chip_id=0), where="x")
    assert any("chip_id" in e for e in exc.value.errors)


def test_esp_image_rejects_bad_magic_and_checksum() -> None:
    with pytest.raises(ContractError):
        contract.parse_esp_image(support.make_esp_image(magic=0x00), where="x")
    data = bytearray(support.make_esp_image(kind="app"))
    data[0x40] ^= 0xFF  # flip a byte inside segment data: checksum breaks
    with pytest.raises(ContractError) as exc:
        contract.parse_esp_image(bytes(data), where="x")
    assert any("checksum" in e for e in exc.value.errors)


def test_esp_image_rejects_truncation() -> None:
    data = support.make_esp_image(kind="app")
    with pytest.raises(ContractError):
        contract.parse_esp_image(data[:30], where="x")


def test_descriptor_detection() -> None:
    assert contract.find_desc_segment(support.make_esp_image(kind="app"), kind="app")
    assert contract.find_desc_segment(
        support.make_esp_image(kind="bootloader"), kind="bootloader"
    )
    raw = support.make_esp_image(kind="raw")
    assert contract.find_desc_segment(raw, kind="app") is None
    assert contract.find_desc_segment(b"\xE9\x00garbage", kind="app") is None


# ---------------------------------------------------------------------------
# Path safety (master plan section 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../escape.bin",
        "/abs/path",
        "images/../../escape",
        "images\\evil.bin",
        "C:/evil.bin",
        "a//b",
        "./a",
        "a/",
        "",
        "ключ.bin",
        "a" * 300,
    ],
)
def test_relative_package_path_rejects(bad: str) -> None:
    assert contract.validate_relative_package_path(bad, where="x")
    with pytest.raises(ContractError):
        contract.normalize_package_path(bad)


@pytest.mark.parametrize("good", ["images/firmware.bin", "flash/flash_args", "SHA256SUMS"])
def test_relative_package_path_accepts(good: str) -> None:
    assert contract.validate_relative_package_path(good, where="x") == []
    assert contract.normalize_package_path(good) == good


def test_derive_helpers() -> None:
    assert contract.derive_build_id("local", pr_number=None, sha="local") == "local"
    assert (
        contract.derive_build_id("pr", pr_number=7, sha=support.FULL_SHA_A)
        == f"pr-7-{support.SHA_A_12}"
    )
    assert contract.derive_tag("pr", support.FULL_SHA_A) is None
    assert (
        contract.derive_tag("main", support.FULL_SHA_B)
        == f"firmware-main-{support.FULL_SHA_B[:12]}"
    )
    with pytest.raises(ContractError):
        contract.derive_build_id("pr", pr_number=0, sha=support.FULL_SHA_A)
    with pytest.raises(ContractError):
        contract.short_sha("nope")
