# vdog firmware

PlatformIO project for the Seeed Studio XIAO ESP32S3 Sense prototype
(ESP-IDF framework). Environments, exact package pins and the full
command/exit-code matrix live in
[docs/toolchain.md](../docs/toolchain.md); requirements are in
[docs/specs/firmware.md](../docs/specs/firmware.md). This README covers the
project layout, how to build/test it and what the build gates enforce.

Status: package 1.2 **Part A** (BUILD/HOST evidence: memory baseline,
sanitized identity, strap gate) plus the Item #17 P1-4 health-gated OTA
check-in. Everything here is **BUILD** (cross-compile) or **HOST** (native
test) evidence. No device was connected, flashed, monitored or erased — the
1.2 Part B device session (boot-mode drill, strap evidence, owner
measurements) stays owner-gated and is parked; it needs the identified unit
and explicit authorization.

## Environments

| Environment | Framework | Purpose | Evidence level |
| --- | --- | --- | --- |
| `vdog_xiao_sense_proto` | `espidf` (platform `platformio/espressif32@8.0.0`, board `seeed_xiao_esp32s3`) | cross-build of the prototype image, build gates | **BUILD** |
| `native` | `platformio/native@1.2.1` + Unity `2.6.1` | host unit tests of the portable core in `core/` | **HOST** |

`platform_packages`, the platform/board pins and the Unity/native pins are the
package 0.2 lock matrix — frozen; changing them needs the lead (escalation, not
an edit).

## Commands (run from the repository root)

```sh
pio run -d firmware -e vdog_xiao_sense_proto                                # BUILD
pio run -d firmware -e vdog_xiao_sense_proto -t size                         # BUILD size report
pio test -d firmware -e native                                               # HOST
pio test -d firmware -e vdog_xiao_sense_proto \
    --without-uploading --without-testing                                    # BUILD-only test image
```

Report BUILD and HOST **separately**, and never describe the last command as
executed tests: it compiles and links the embedded test image and reports
`[SKIPPED]` because nothing runs on hardware. Device operations
(`upload`/`monitor`/`erase`/`run` on target, OTA on hardware, eFuse) are not
authorized in this package; see the plan's non-goals.

## Layout

| Path | Owns |
| --- | --- |
| `core/` | portable pure-C11 modules, no SDK/OS headers, C++-consumer-safe: `vdog_core.{h,c}` (semantic version), `vdog_board.{h,c}` (board profile + identity gate), and since 1.2 `vdog_mem.{h,c}` (memory baseline with per-field MEASURED/CONFIGURED evidence tags), `vdog_recovery.{h,c}` (boot-mode classifier + structurally sanitized identity line — MAC tail only + the pure OTA-confirm health gate), `vdog_straps.{h,c}` (strap/reserved/candidate claim gate; GPIO21 stays unclaimed, microphone disabled). Built by `native` via `lib_deps` **and** by the target through the component wrappers |
| `components/vdog_core/`, `components/vdog_board/` | thin IDF-component wrappers (`idf_component_register`) that expose `core/` under a namespaced component name; `components/vdog_board/vdog_board_idf.c` is the target-side adapter that turns `CONFIG_*` macros into a profile; `vdog_board_hw.{h,c}` (1.2) is the read-only memory/identity adapter (chip queries only, no pin driving, no strap claims, no microphone init) |
| `src/` | IDF `main` component (`main.c`, `idf_component.yml` with the pinned camera dependency) |
| `test/test_vdog_core/`, `test/test_vdog_board/`, `test/test_vdog_mem/`, `test/test_vdog_recovery/`, `test/test_vdog_straps/` | Unity host tests + C++ consumer smoke TUs (71 host cases since 1.2 + Item #17 P1-4, PR-review rounds 1–4 included); `pio test -e native` is the only host harness — the embedded `--without-uploading --without-testing` run is compile/link qualification only (`[SKIPPED]`, never execution) |
| `scripts/` | build-time generators and gates (below) |
| `partitions/vdog_8mb_two_ota.csv` | custom 8MB two-slot OTA table (matches `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`) |
| `sdkconfig.defaults` | explicit ESP-IDF configuration; keys may be added, never relaxed |
| `build_gen/`, `.pio/`, `.vdog-build-metadata.json`, `sdkconfig.<env>` | generated, gitignored |

Module boundary per [docs/specs/firmware.md §1](../docs/specs/firmware.md):
the `board` module owns validated pins, revision identity, peripherals and the
power/indicator abstraction — never recording/business policy. Semantic version
stays separate from source/build identity: `core/vdog_core.h` owns the
`MAJOR.MINOR.PATCH-SUFFIX`, `scripts/gen_build_meta.py` owns the source SHA and
build id.

## Build gates (proto environment only)

`[env:vdog_xiao_sense_proto]` wires four extra scripts; none of them may ever
be wired into `native`. Three of them (`gen_build_meta.py`,
`check_core_purity.py`, `check_board_config.py`) hard-fail the build if they
are ever loaded in another environment; `test_build_isolation.py` instead
returns silently (a no-op) when its `$PIOENV` is not the proto environment —
its own defensive guard from package 0.9, not a gate:

| Script | When | Fails the build when |
| --- | --- | --- |
| `scripts/test_build_isolation.py` | pre | — (redirects `pio test`/`__test` builds to `.pio/build/vdog_xiao_sense_proto_test` so a test runner can never relink the release images) |
| `scripts/gen_build_meta.py` | post (parse time + build post actions) | `VDOG_SOURCE_SHA`/`VDOG_BUILD_ID` are malformed, or the resolved platform/packages drift from the pinned matrix; emits the gitignored metadata JSON + `build_gen/vdog_build_id.h` |
| `scripts/check_core_purity.py` | post (parse time, every target) | any file in `core/` contains an SDK/RTOS/camera/SD/SPI-SD/NVS token or an SDK-style `#include` — mechanical proof the portable core stays host-buildable |
| `scripts/check_board_config.py` | post (build post actions, after a successful build) | any of the **four agreement layers** disagrees: (1) a required key is not character-for-character declared in `sdkconfig.defaults`, (2) the generated `config/sdkconfig.json` lacks it or holds a different value (type-strict), (3) `components/vdog_board/CMakeLists.txt` definitions drift from the expected board id / PSRAM size, or (4) the effective partition table (PlatformIO `board_build.partitions` + resolved `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME` + the expected CSV) is not the same file; or `$BOARD` is not `seeed_xiao_esp32s3` |

The board gate is the loud half of "no silently inherited PSRAM/flash
defaults". A resolved value alone can be an inherited SDK default or a stale
compiled-in definition, so FOUR independent layers must all agree (source
declaration, resolved config, component definitions, effective partition
table — see the script header). It checks these keys present-and-equal: `IDF_TARGET`,
`ESPTOOLPY_FLASHSIZE_8MB`, `ESPTOOLPY_FLASHMODE_QIO`, `ESPTOOLPY_FLASHFREQ_80M`,
`SPIRAM`, `SPIRAM_MODE_OCT`, `SPIRAM_SPEED_80M`, `PARTITION_TABLE_CUSTOM`,
`PARTITION_TABLE_CUSTOM_FILENAME`, `ESP_CONSOLE_USB_CDC`,
`ESP_CONSOLE_SECONDARY_NONE`, plus `board == seeed_xiao_esp32s3` (observed from
`$BOARD` — `board` is a PlatformIO board id, not an ESP-IDF Kconfig key).
A failure prints every offending key with expected and actual values and exits
non-zero.

Both gates also run standalone (documented override for
evidence/reproduction):

```sh
python3 firmware/scripts/check_core_purity.py
python3 firmware/scripts/check_board_config.py \
    --sdkconfig firmware/.pio/build/vdog_xiao_sense_proto/config/sdkconfig.json \
    --board seeed_xiao_esp32s3
```

Tampering a **copy** of the generated `sdkconfig.json` (for example flipping
`SPIRAM_MODE_OCT` to `false`) and pointing the script at it must exit non-zero
naming the key — that negative demo is recorded with exit codes in
[docs/toolchain.md](../docs/toolchain.md) ("Package 1.1 addendum").

The gate follows `gen_build_meta.py`'s policy for redirected test builds: it
registers nothing for `__test`/`nobuild`/`clean` command-line targets and never
fails on a missing or partial `sdkconfig.json` inside a `*_test` build
directory, so `pio test` embedded builds stay unaffected.

## Board identity gate (host-tested logic)

`core/vdog_board.{h,c}` is the single source of truth for what "supported
board" means; the Python gate only reads and compares. Every profile field is
paired with a `field_set` bit, so:

- a key that was never configured → `VDOG_ERR_BOARD_MISSING_FIELD` (checked
  before any value comparison, so missing always outranks wrong);
- a wrong chip/board → `VDOG_ERR_BOARD_UNSUPPORTED_TARGET`;
- wrong flash size/mode/frequency → `VDOG_ERR_BOARD_FLASH`;
- wrong PSRAM presence/size/mode/speed (including "declared absent") →
  `VDOG_ERR_BOARD_PSRAM`;
- wrong partition table → `VDOG_ERR_BOARD_PARTITIONS`;
- `vdog_board_error_field()` names the offending field for the log line.

`vdog_board_report()` composes the boot line only from a **validated** profile:

```text
vdog 0.2.0-proto board=seeed_xiao_esp32s3 target=esp32s3 flash=8MB-qio-80m psram=8MB-opi-80m
```

`src/main.c` logs that line (or `board config rejected: <reason> (field
<name>)`) in addition to the package 0.2 version/build-identity lines. The
flash/PSRAM numbers are **build configuration** from `sdkconfig.defaults` and
the component definition, not detected hardware — actual capacity and octal
PSRAM detection are DEVICE evidence for packages 1.2–1.4.

## OTA self-test check-in (health-gated, Item #17 P1-4)

With rollback enabled (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`) every boot
ends with exactly ONE OTA line:

```text
ota=confirmed (board+memory health gate passed)
ota=not-confirmed (board_ok=<yes|no> memory_ok=<yes|no>) — rollback NOT cancelled
```

The SDK "mark app valid, cancel rollback" call runs ONLY when the portable
rule `vdog_ota_should_confirm()` (`core/vdog_recovery.c`) says so: BOTH the
board-identity verdict (`vdog_board_validate`) and the memory-baseline
verdict (`vdog_mem_check_baseline`) must be healthy — no partial credit,
NULL fails closed. An unhealthy image leaves rollback armed so the
bootloader reverts it on the next reset instead of the device staying on a
known-bad image. The rule is host-pinned by three `test_vdog_recovery`
cases; the target-side call site stays in `src/main.c` (the rest of the OTA
evidence record, incl. first-boot otadata initialization and flash-erase
behaviour, is in [docs/hardware-identity.md §2.1](../docs/hardware-identity.md)).

## No pins, no peripherals, no camera/SD code

Nothing in this package configures or drives a GPIO, mounts a card, touches
the camera at runtime or initializes the microphone. The only pin text is the
`PROVISIONAL` comment block in `core/vdog_board.h`, which records that
[hardware/prototype-a/pin-map.csv](../hardware/prototype-a/pin-map.csv) is
candidate-only (`CANDIDATE_NOT_APPROVED`, wiring not approved) and that its
GPIO21 SD-CS/user-LED sharing is **unresolved**. `check_core_purity.py` keeps
`core/` free of camera/SD code mechanically.
