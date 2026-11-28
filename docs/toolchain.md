# vdog toolchain qualification and version lock — package 0.2

Status: **Stage 0 package 0.2 BUILD/HOST evidence, 2026-11-19.** Produced by
`firmware/` (branch `opencode/0.2-toolchains`) via
[plan 0.2](plans/0.2-toolchain-qualification.md). This is the lock/version
matrix that package 1.1 inherits. **No device was connected, flashed,
monitored or erased for any claim here** — see "Evidence scope and deferred
device verification" at the end.

## 1. OS/runner and host tool inventory

| Item | Value | How observed |
| --- | --- | --- |
| OS/runner | macOS 26.6.2 (build 25G83), Apple silicon (arm64) | `sw_vers` |
| PlatformIO Core | **6.2.0** (`~/.local/bin/pio`, uv-managed tool env) | `pio --version` |
| PlatformIO bundled Python | 3.12 (uv tool env under `~/.local/share/uv/tools/platformio`) | shebang of `pio` |
| Host Python 3 | 3.14.6 (`/opt/homebrew/bin/python3`) — not used by PlatformIO itself | `python3 --version` |
| git | 2.50.1 (Apple Git-155) | `git --version` |
| Standalone ESP-IDF | not installed — PlatformIO's `framework-espidf` package is the SDK | inventory |
| Rust/cargo | not installed | `which cargo rustc` (2026-11-19) |
| Network | `api.registry.platformio.org`, `dl.registry.platformio.org`, `components.espressif.com`, PyPI, GitHub all reachable; the legacy `dl.platformio.org` mirror is unused by Core 6.2 | package downloads succeeded (2026-11-19) |

No global tool was installed or upgraded to obtain this baseline; all
packages were fetched into `~/.platformio` by PlatformIO itself.

## 2. Resolved dependency matrix (`pio pkg list -d firmware -e vdog_xiao_sense_proto`, 2026-11-19)

| Package | Version | Role |
| --- | --- | --- |
| `platformio/espressif32` (platform) | **8.0.0** (pinned exactly in `firmware/platformio.ini`) | official platform, `engines: platformio ^6` |
| `framework-espidf` | **4.60100.0** → embedded **ESP-IDF v6.1.0** (`version.txt`, `tools/cmake/version.cmake`) | SDK |
| `toolchain-xtensa-esp-elf` | 15.2.0+20251204 (GCC 15.2.0) | C/C++ compiler for ESP32-S3 |
| `toolchain-riscv32-esp` | 15.2.0+20251204 | RISC-V toolchain (present via platform deps) |
| `toolchain-esp32ulp` | 1.23800.240113 (2.38.0) | ULP toolchain (optional dep) |
| `tool-cmake` | 3.30.2 | build system |
| `tool-ninja` | **range `>=1.7.1,<2`** (the one host-resolved package, 2026-11-21 — see the exception note below): resolves to **1.13.2** on this darwin host, **1.7.1** on linux_x86_64 CI (pending CI re-record, §7; registry publishes no linux_x86_64 build above 1.7.1) | build system |
| `tool-esptool` | 2.50400.0 (esptool v5.4.0) | image tools (used read-only for `image-info` analysis) |
| `tool-esp-rom-elfs` | 0.0.1+20241011 | ROM ELF files |
| `tool-xtensa-esp-elf-gdb` / `tool-riscv32-esp-elf-gdb` | 12.1.0+20221002 | debuggers (unused) |
| `espressif/esp32-camera` | **2.1.9 (pinned `==2.1.9`)** from the ESP Component Registry (`components.espressif.com`), `component_hash f14a6a9a5c22…f774fe` | camera driver, link-time dependency only |
| `espressif/esp_jpeg` | 1.3.2 (transitive, `^1.3.1`), `component_hash 47d19eac…76bdf` | esp32-camera dependency |
| `throwtheswitch/Unity` (native test env only) | **2.6.1 (pinned exactly)** in `[env:native] lib_deps` | HOST test framework (ESP-IDF side uses the SDK's bundled Unity via `PRIV_REQUIRES unity`) |
| Component manager | `idf-component-manager` 3.1.2 in the IDF venv (`~/.platformio/penv/.espidf-6.1.0`) | resolves `src/idf_component.yml` |

The component-manager lockfile `firmware/dependencies.lock`
(`manifest_hash a1a1e378…e566`, `target: esp32s3`, lock schema 3.0.0) is
**tracked in Git** so transitive versions are reproducible.

### PlatformIO package locking (PR-review F1)

`firmware/platformio.ini` additionally pins (with one documented host
exception, `tool-ninja`, below) **every** package this environment
resolves via `platform_packages =` with exact
`owner/name@version` strings (the platform itself otherwise resolves its
packages by range): `platformio/framework-espidf@4.60100.0`,
`platformio/toolchain-xtensa-esp-elf@15.2.0+20251204`,
`platformio/toolchain-riscv32-esp@15.2.0+20251204`,
`platformio/toolchain-esp32ulp@1.23800.240113`,
`platformio/tool-cmake@3.30.2`, `platformio/tool-ninja@>=1.7.1,<2`
(range — exception note below),
`platformio/tool-esptool@2.50400.0`,
`platformio/tool-esp-rom-elfs@0.0.1+20241011`,
`espressif/tool-xtensa-esp-elf-gdb@12.1.0+20221002`,
`espressif/tool-riscv32-esp-elf-gdb@12.1.0+20221002`, and
`platformio/tool-scons@4.41101.0` (the SCons driver the espidf builder
uses; unpinned it resolved by range `~4.41101.0`, and the exact pin is
confirmed both by the cold-install line and the resolver output — §7/§6).
`pio pkg list` (§6) now shows every package with an exact
`required:` spec (the `tool-ninja` required spec is the documented range).
The 15.2.0+20251204 toolchains are the platform's **declared optional
variant** (`optionalVersions` in platform.json; default is 14.2.0+20260121)
that resolves for ESP-IDF v6.1.0 — pinned explicitly so a cold cache cannot
substitute a different compiler. The native environment is locked too:
`platform = platformio/native@1.2.1` (registry-verified owner/version) plus
`platform_packages = platformio/tool-scons@4.41101.0`, and HOST tests use
`throwtheswitch/Unity@2.6.1` (exact pin, §2 above). GDB/ulp/rom-elfs
packages are installed-by-default platform deps and are pinned even though
debugging/ULP are unused in vdog v1.

**tool-ninja host-resolution exception (2026-11-21, live CI).** The
PlatformIO registry
(`api.registry.platformio.org/v3/packages/platformio/tool/tool-ninja`)
publishes **no `linux_x86_64` build above 1.7.1**: 1.13.2 ships
darwin_x86_64/darwin_arm64 only, 1.10.2 linux_aarch64/armv6l/armv7l/
armv8l, 1.9.0 darwin+windows, 1.7.1 linux_x86_64 only. No single exact
version therefore covers both this darwin host (0.2 qualification) and
the `ubuntu-24.04` CI runner, so `tool-ninja` is the ONE host-resolved
package: `platformio/tool-ninja@>=1.7.1,<2` — darwin resolves 1.13.2
(the 0.2-qualified version, confirmed unchanged here by `pio pkg list`),
linux_x86_64 CI resolves 1.7.1 (pending CI re-record, §7). This is the
documented CI-host exception, parallel in spirit to the range-resolved
IDF Python layer (§7); every other package above remains exactly
pinned. Disclosure: the `<2` bound admits silent in-range upgrades — a
future darwin build ≥ 1.13.3 or a linux_x86_64 build above 1.7.1 would
displace the versions observed here — so re-qualification should re-pin
the then-observed versions once the rerun fixes them.

Verification with an **empty package cache** (`PLATFORMIO_CORE_DIR=$(mktemp
-d)`, cold IDF venv + cold component-manager cache) is recorded in §7.

### esp32-camera compatibility note (ESP32-S3 + candidate sensors)

`espressif/esp32-camera` 2.1.9 declares `idf >=5.1` (satisfied by v6.1.0)
and resolved for target `esp32s3`. The compiled component bundles the
OV2640, OV3660, OV3640 and OV5640 sensor drivers (visible in the build log,
`managed_components/espressif__esp32-camera/sensors/ov*.c.o`), covering the
OV5640/OV3660 transition shipments and historical OV2640 units of
`docs/specs/hardware.md` §2.1. This is **compile/link qualification only**: no
camera runtime was executed, the acquired unit's sensor identity is not yet
recorded, and no XIAO DVP/SCCB pin map is approved (package 0.3). Driver
behaviour on the actual module remains DEVICE evidence for packages 1.2–1.4.

## 3. Board and environment definitions (`firmware/platformio.ini`)

| Environment | Purpose | Definition |
| --- | --- | --- |
| `vdog_xiao_sense_proto` | cross-build (BUILD evidence) | `platform = platformio/espressif32@8.0.0`, `board = seeed_xiao_esp32s3`, `framework = espidf`, `monitor_speed = 115200`, `board_build.partitions = partitions/vdog_8mb_two_ota.csv` |
| `native` | host tests (HOST evidence) | `platform = platformio/native@1.2.1` (exact, PR-review F1), `platform_packages = platformio/tool-scons@4.41101.0`, `lib_deps = ./core` + `throwtheswitch/Unity@2.6.1` |

These are the only firmware environments (plan §4.1). `core/` (pure C, no
IDF headers) is shared: ESP-IDF builds it via the thin
`components/vdog_core/CMakeLists.txt` wrapper; the native environment builds
the identical files via `lib_deps`.

Toolchain deviations recorded under plan §9 (documented equivalents, not
guesses):

1. **`idf_component.yml` lives at `firmware/src/`, not the project root.**
   With `idf-component-manager` 3.1.x (ESP-IDF v6.1) manifests are collected
   only per component directory containing `CMakeLists.txt` +
   `idf_component.yml`; PlatformIO registers `firmware/src` as the main
   component, so the root-level file is ignored. Its manifest `version`
   field must be full SemVer (`1.0.0`), not `1`.
2. **`unity` added to `src` `PRIV_REQUIRES`** so the embedded *build-only*
   test contract compiles/links (`test/` runner entry); linker section
   collection keeps it out of the release image (size report unchanged).
3. PlatformIO's ESP-IDF builder puts the generated sdkconfig at
   `firmware/sdkconfig.vdog_xiao_sense_proto` (ignored). Delete that file to
   force a full reconfigure after editing `sdkconfig.defaults`.

## 4. Explicit ESP-IDF configuration (`firmware/sdkconfig.defaults`)

Arduino-scope board-manifest entries (`qio_opi`, `default_8MB.csv`) were not
relied upon; every value below is set through the pinned SDK's own Kconfig
names (verified against `framework-espidf` 6.1.0 sources). **Verification
method** column states how each resolved value was checked in the build
output.

| Kconfig key | Set to | Resolved value | Verification method |
| --- | --- | --- | --- |
| `CONFIG_IDF_TARGET` | `esp32s3` | `esp32s3` | `config/sdkconfig.json` |
| `CONFIG_ESPTOOLPY_FLASHSIZE_8MB` | `y` | `ESPTOOLPY_FLASHSIZE="8MB"` | `config/sdkconfig.json`; `esptool image-info` on bootloader.bin/firmware.bin reports "Flash size: 8MB" |
| `CONFIG_ESPTOOLPY_FLASHMODE_QIO` | `y` | selected (`ESPTOOLPY_FLASHMODE_VAL=1`) | `config/sdkconfig.json`. Note: the hidden `ESPTOOLPY_FLASHMODE` string remains `dio` **by ESP-IDF design** (esptool programs in DIO; the bootloader self-upgrades to quad mode during init — see `esptool_py/Kconfig.projbuild`). Runtime quad-mode operation on hardware is DEVICE evidence (1.2) |
| `CONFIG_ESPTOOLPY_FLASHFREQ_80M` | `y` | `ESPTOOLPY_FLASHFREQ="80m"` | `config/sdkconfig.json`; `image-info` reports "Flash freq: 80m" |
| `CONFIG_SPIRAM` | `y` | `True` | `config/sdkconfig.json` |
| `CONFIG_SPIRAM_MODE_OCT` | `y` | `True` (octal/OPI PSRAM) | `config/sdkconfig.json` |
| `CONFIG_SPIRAM_SPEED_80M` | `y` | `SPIRAM_SPEED=80` | `config/sdkconfig.json` |
| `CONFIG_ESP_CONSOLE_USB_CDC` | `y` | `True` | `config/sdkconfig.json`. In v6.1.0 this selects the **ROM CDC driver on the USB-OTG port** (the XIAO USB-C; mutually exclusive with TinyUSB, which vdog does not use) — the native-USB console of the plan |
| `CONFIG_ESP_CONSOLE_SECONDARY_NONE` | `y` | `True` | `config/sdkconfig.json` |
| `CONFIG_PARTITION_TABLE_CUSTOM` | `y` | `True` | `config/sdkconfig.json` |
| `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME` | `"partitions/vdog_8mb_two_ota.csv"` | as set (matches `board_build.partitions`) | `config/sdkconfig.json`; build generated `partitions.bin` and `ota_data_initial.bin` from that CSV |
| `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` | `y` | `True` | `config/sdkconfig.json`; `src/main.c` calls `esp_ota_mark_app_valid_cancel_rollback()` (compiles/links) |

Fail-loud posture: PSRAM is enabled without
`SPIRAM_IGNORE_NOTFOUND`; flash size is explicit (no 4MB default fallback —
PlatformIO warns on mismatch with the board's `upload.flash_size`); the
custom partition filename must exist or `gen_esp32part.py` fails the build.

## 5. Partition budget — `firmware/partitions/vdog_8mb_two_ota.csv`

Measured **BUILD** sizes from this exact configuration (2026-11-19):
`firmware.bin` = **208,784 bytes** (`text 148,313 + data 60,356`; `bss`
376,865 B is RAM, not flash); `bootloader.bin` = 22,944 B.

| Region | Offset | Size | Decimal | Notes (measured vs budget) |
| --- | --- | --- | --- | --- |
| bootloader | `0x000000` | `0x8000` | 32,768 | measured 22,944 B → 9,824 B spare |
| partition table | `0x008000` | `0x0C00` | 3,072 | fixed by ESP-IDF |
| `nvs` | `0x009000` | `0x6000` | 24,576 | settings + identity/config (FW `settings`/`identity` modules) |
| `otadata` | `0x00F000` | `0x2000` | 8,192 | two 4KB sequence sectors |
| `phy_init` | `0x011000` | `0x1000` | 4,096 | RF calibration data |
| (alignment gap) | `0x012000` | `0xE000` | 57,344 | first app slot must be 64KB-aligned |
| `app0` (OTA slot A) | `0x020000` | `0x300000` | **3,145,728** | measured minimal app **208,784 B → 15.0× slot/image margin** (documented requirement ≥4×) |
| `app1` (OTA slot B) | `0x320000` | `0x300000` | **3,145,728** | equal size, both 64KB-aligned |
| `storage` (data/spiffs) | `0x620000` | `0x1E0000` | 1,966,080 | reserved headroom for future non-record data (1.875 MiB); recording lives on the SPI-SD card, not flash |
| **total** | | | `0x620000 + 0x1E0000 = 0x800000` = **8,388,608 B = exactly 8MB** |

Slot-size rationale: minimal proto image 208,784 B. The vdog app will grow
with camera+SDSPI+HTTPS/TLS, NVS and OTA APIs; 3MB slots keep ≥4× headroom
over the current build while leaving two equal slots plus NVS/otadata/
storage inside 8MB. The 1.14 recorder image must be re-measured against this
budget (plan §"measured image fitting each slot with margin"); a build-size
failure then needs a documented decision, not a silent partition shrink.
This table deliberately does not reuse the Arduino `default_8MB.csv` or any
4MB/N16R8/Plus layout.

## 6. Proven working commands (2026-11-19, macOS arm64)

Run from the repository root unless noted. Exit codes are from this
package's qualification runs.

| Command | Exit | Evidence level | Result summary |
| --- | --- | --- | --- |
| `pio --version` | 0 | HOST inventory | PlatformIO Core 6.2.0 |
| `pio run -d firmware -e vdog_xiao_sense_proto` | 0 | **BUILD** | full cross-compile incl. pinned camera component; `[SUCCESS]` (clean-checkout rerun also exit 0, §7) |
| `pio run -d firmware -e vdog_xiao_sense_proto -t size` | 0 | **BUILD** | `text 148313 / data 60356 / bss 376865` |
| `pio test -d firmware -e native` | 0 | **HOST** | `native:test_vdog_core [PASSED]` — **7 test cases, 7 succeeded**: `test_format_version_exact`, `test_format_version_exact_fit`, `test_format_version_rejects_small_and_null`, `test_version_pack_roundtrip`, `test_version_pack_bounds_and_overflow` (255/0 accepted; 256, 0x100, 65536, UINT32_MAX rejected per component — PR-review F3), `test_version_compare_ordering`, `test_cpp_smoke_linkage` (C TU calls an `extern "C"` symbol defined in `cpp_smoke.cpp`; the C↔C++ link is real — PR-review F2). Unity pinned to 2.6.1 (§2) |
| `pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing` | 0 | **BUILD-only** | `vdog_xiao_sense_proto:test_vdog_core [SKIPPED]` — the test image compiles and links (incl. the C++ TU `test/test_vdog_core/cpp_smoke.cpp`; archived `nm` proof of unmangled `T vdog_cpp_smoke` in the embedded test object — §7); **tests are not executed** (never claim execution here) |
| `pio pkg list -d firmware -e vdog_xiao_sense_proto` | 0 | lock evidence | §2 table |
| `~/.platformio/packages/tool-esptool/esptool --chip esp32s3 image-info firmware/.pio/build/vdog_xiao_sense_proto/firmware.bin` (and `bootloader.bin`) | 0 | **BUILD** (host-side image analysis; no device I/O) | "Image size: 208784 bytes / Flash size: 8MB / Flash freq: 80m"; bootloader 22,944 B. Output archived in the package 0.2 evidence bundle (`image-info-firmware.log`) alongside the build/test logs listed in the handoff; resolved flash values are independently readable from `config/sdkconfig.json` in any local build tree |
| `git diff --check` | 0 | hygiene | clean |

## 7. Reproducibility

Reproducibility was proven by fresh detached-worktree runs at the handoff
commits with no `firmware/.pio`, from that worktree's root (2026-11-19; all
logs archived in the package 0.2 evidence bundle named in the handoff):

- Clean build (`clean-rerun-build.log`): `pio run -d firmware -e
  vdog_xiao_sense_proto` **exit 0**, `[SUCCESS]` in 42 s, re-resolving
  `managed_components/` (esp32-camera 2.1.9 + esp_jpeg 1.3.2) from the
  tracked lock.
- Clean size report (`clean-rerun-size.log`): **exit 0**,
  `text 148313 / data 60344 / bss 376873`, `firmware.bin` 208,768 B at that
  commit — identical `text` and slot-fitting image vs the canonical
  208,784 B. A second archived clean build at the final handoff commit
  (`clean-rerun2-build.log`, `[SUCCESS]` 47.5 s; `ls -l` + `esptool
  image-info` byte count in `clean-rerun-image-info.log`: "Image size:
  208784 bytes / Flash size: 8MB / Flash freq: 80m") shows the image byte
  count varies per build (observed 208,768–208,784 B) with the embedded
  `esp_app_desc` build-timestamp/hash section, not configuration; both ends
  of the range keep ≥15× slot margin (§5).
- Clean host tests (`clean-rerun-native-test.log`): **exit 0**,
  `Library Manager: Installing throwtheswitch/Unity @ 2.6.1` (pin honored on
  a cold cache) and 5/5 test cases passed.

- Empty package cache (full lock verification, PR-review F1):
  `PLATFORMIO_CORE_DIR=$(mktemp -d) pio run -d firmware -e
  vdog_xiao_sense_proto` → **exit 0** (`[SUCCESS]` 305.8 s, **12 package
  installs** at exact pinned versions, cold IDF venv, cold component-manager
  cache; `emptycache-build.log`). The run's `PACKAGES:` block matches §2
  **exactly** (framework-espidf 4.60100.0/6.1.0, GCC 15.2.0+20251204
  toolchains, cmake 3.30.2, ninja 1.13.2 (this run: darwin host; see the
  ninja host-resolution exception below), esptool 2.50400.0/5.4.0, ulp
  1.23800.240113, rom-elfs 0.0.1+20241011, gdb 12.1.0+20221002 ×2). The IDF
  venv installs its Python layer from IDF's range requirements (`urllib3<2`
  → 1.26.20, `cryptography~=46.0.0` → 46.0.7, `pyparsing<4,>=3.1.0` → 3.3.3,
  `idf-component-manager~=3.1` → 3.1.2, `esp-idf-kconfig~=3.13.0` → 3.13.0,
  `pydantic~=2.12.0` → 2.12.5); that layer is range-resolved, not
  version-locked — the same requirements tree resolved identically in both
  cold runs. Follow-up in the same cold core dir:
  `pio test -d firmware -e native` → **exit 0**, `Platform Manager:
  Installing platformio/native @ 1.2.1` (exact pin honored) and 7/7 test
  cases passed (`emptycache-native-test.log`). No package resolved
  differently from the matrix.
- Second empty-cache run after pinning `tool-scons` (review round 3, N1):
  same command → **exit 0** (`[SUCCESS]` 459.96 s, 12 exact installs;
  `emptycache-build2-notes.log`). The SCons driver line is now
  `Installing platformio/tool-scons @ 4.41101.0` (was `~4.41101.0`),
  completing the exact-install coverage for every package the build pulls.
- Embedded test-object evidence (review round 3, N4): after
  `pio test -e vdog_xiao_sense_proto --without-uploading --without-testing`
  (exit 0, `[SKIPPED]`; `embedded-testbuild5-prfix.log`), the C++ test TU was
  captured from the embedded test build tree and archived —
  `embedded-cpp-smoke-object-prfix.log` holds the `ls` of `cpp_smoke.o`
  (6,344 B) plus `xtensa-esp32s3-elf-nm` output showing unmangled C linkage:
  `T vdog_cpp_smoke` with `U vdog_format_version / vdog_version_compare /
  vdog_version_pack`.

- Live CI host-resolution outcome (2026-11-21): the first live PR run of
  `.github/workflows/firmware-pr.yml` on GitHub `ubuntu-24.04`
  (run 44890089847, PR #2, `opencode/0.2-toolchains` @ 3c8cb47) passed
  `firmware-host-tests` and `firmware-package-tests`; `firmware-build`
  failed at "Build the prototype environment" with
  `UnknownPackageError: Could not find the package with
  'platformio/tool-ninja @ 1.13.2' requirements` — the exact 1.13.2 pin
  was qualified on darwin, the only platform publishing 1.13.2 builds.
  The proto environment now requires `platformio/tool-ninja@>=1.7.1,<2`
  (§2 exception note): darwin still resolves the 0.2-qualified 1.13.2
  (re-confirmed here with `pio pkg list` after the change), while
  linux_x86_64 resolution (1.7.1 per the registry) and `firmware-build`
  success on the CI host are **UNVERIFIED locally** and will be
  re-recorded from the CI rerun.

All recorded runs exit 0. The tracked `firmware/dependencies.lock`, the
Unity pin and the exact pins (`platformio/espressif32@8.0.0`, `==2.1.9`;
every `platform_packages` pin exact except the documented `tool-ninja`
host range above) are the reproducibility contract.

## 8. App/Backend deferred pins (not qualified here)

| Item | Host observation (2026-11-19) | Pin decision | Status |
| --- | --- | --- | --- |
| Flutter | 3.41.6 stable (`~/flutter_sdk/flutter`, framework rev `db50e20168`) observed on host | project pin + min OS/target SDK belong to package 2.1 | **UNVERIFIED** (no app code, no project pin) |
| Dart | 3.11.4 stable (`dart --version`, macos_arm64) | follows Flutter decision (2.1) | **UNVERIFIED** |
| Rust | **not installed** (`cargo`/`rustc` absent) | MSRV + crate pins deferred to package 3.1; no install performed to manufacture evidence | **UNVERIFIED** |
| FFmpeg + vid.stab | not exercised | deferred to packages 1.16/3.9 | **UNVERIFIED** |

## 9. Evidence scope and deferred device verification

This matrix records **BUILD** (cross-compilation) and **HOST** (native
tests) evidence only. Physical flash capacity, octal-PSRAM detection and
usable bytes, camera sensor detection, SPI-SD card behaviour, USB recovery
and boot/OTA runtime are **DEVICE** evidence for packages 1.2–1.4 against an
identified authorized unit. The upstream PlatformIO board entry alone was
**not** accepted as qualification; it was verified here by an actual
project build. No upload, monitor, erase, flash, eFuse, OTA or network
runtime operation was performed in package 0.2, and the microphone stayed
uninitialized.

## Package 1.1 addendum (append-only, 2026-11-27)

This addendum records package 1.1 (firmware bootstrap + portable board-profile
core) and **does not modify §1–§9**: the 0.2 lock matrix above is exactly what
package 1.1 inherits and re-ran green. Produced by `firmware/` on branch
`opencode/1.1-fw-bootstrap` via
[plan 1.1](plans/1.1-assignment.md). **No device was connected, flashed,
monitored or erased**, and nothing here is DEVICE evidence.

### What package 1.1 added to the firmware project

| Path | Role |
| --- | --- |
| `firmware/core/vdog_board.{h,c}` | portable pure-C11 board profile + identity gate (explicit `field_set` per field, `vdog_board_validate()`, `vdog_board_error_field()`, `vdog_board_report()`); single source of truth for the supported-configuration semantics |
| `firmware/core/library.json` | exposes both portable headers to the `native` environment (`vdog-core@1.1.0`) |
| `firmware/components/vdog_board/` | IDF component wrapper + target-side `vdog_board_profile_from_sdkconfig()` adapter (`#ifdef CONFIG_*`, so an unset key means "field not set", never an inherited default) |
| `firmware/scripts/check_board_config.py` | post-build gate: required `config/sdkconfig.json` keys present **and** equal, plus `$BOARD == seeed_xiao_esp32s3` |
| `firmware/scripts/check_core_purity.py` | post-parse gate: `firmware/core/**` stays free of SDK/RTOS/camera/SD/SPI-SD/NVS tokens and SDK-style includes |
| `firmware/test/test_vdog_board/` | 15 Unity host cases + `cpp_smoke_board.cpp` C++ consumer TU |
| `firmware/src/main.c`, `src/CMakeLists.txt` | board report / `board config rejected: … (field …)` log line; `REQUIRES vdog_board` |
| `firmware/platformio.ini` | two new `post:` entries on `[env:vdog_xiao_sense_proto]` **only** — no `platform_packages`, platform/board or Unity/native pin changed |
| `firmware/README.md` | environments, root commands, gate behaviour, BUILD/HOST discipline |

`sdkconfig.defaults` and `dependencies.lock` are **byte-identical to the 0.2
lock** (`git diff 7839610 -- firmware/sdkconfig.defaults firmware/dependencies.lock`
→ empty): no key was added or relaxed, and no dependency/version changed.

### Commands run from the repository root (macOS arm64 host, 2026-11-27)

| Command | Exit | Evidence level | Result summary |
| --- | --- | --- | --- |
| `pio --version` | 0 | host inventory | PlatformIO Core 6.2.0 |
| `pio run -d firmware -e vdog_xiao_sense_proto -t clean` | 0 | **BUILD** | `[SUCCESS]` 0.55 s |
| `pio run -d firmware -e vdog_xiao_sense_proto` (after clean) | 0 | **BUILD** | `[SUCCESS]` 45.29 s, 1105 compile actions, **0 `warning:`/`error:` lines** with `-Wall -Wextra`; `RAM 19116/327680 B`, `Flash 210413/3145728 B` (re-run after the review fixes; the first round measured 43.26 s with identical compile count and zero warnings) |
| `pio run -d firmware -e vdog_xiao_sense_proto -t size` | 0 | **BUILD** | `text 149597 / data 61124 / bss 376865`; `firmware.bin` 210,832 B (image grew by the board-report code); slot margin vs the 3 MB OTA slot stays ≈14.9× (≥4× requirement, §5) |
| `pio test -d firmware -e native` | 0 | **HOST** | `native:test_vdog_board [PASSED]` **15/15** + `native:test_vdog_core [PASSED]` **7/7** → **22 test cases: 22 succeeded, 0 failed** |
| `pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing` | 0 | **BUILD-only** | `vdog_xiao_sense_proto:test_vdog_board [SKIPPED]` and `…:test_vdog_core [SKIPPED]` — both embedded test images compile and link (incl. `cpp_smoke_board.cpp`); **no test executed** (never described as execution). Build stayed isolated in `.pio/build/vdog_xiao_sense_proto_test/` |
| `~/.platformio/packages/tool-esptool/esptool --chip esp32s3 image-info firmware/.pio/build/vdog_xiao_sense_proto/firmware.bin` | 0 | **BUILD** (host-side image analysis, no device I/O) | `Image size: 210832 bytes / Flash size: 8MB / Flash freq: 80m / Chip ID: 9 (ESP32-S3)` |
| `python3 firmware/scripts/check_core_purity.py` | 0 | host-side gate run (not an evidence level: **HOST** means the `native` Unity run only) | `5 portable-core files scanned, no camera/SD/RTOS/SDK tokens` |
| `git diff --check` | 0 | hygiene | clean |

The 0.2 command set is unchanged and still green; no new root command was
introduced, so `docs/project-profile.md` needs no command-list edit. `pio test
-e native` remains the only host harness (no Python test framework added under
`firmware/`).

**Plan command-form note:** the plan's clean step
`pio run -d firmware -e vdog_xiao_sense_proto -t run --target clean` passes two
SCons targets and SCons aborts the *clean* run with
`*** Do not know how to make File target 'run'` (**exit 1**, no build
performed). The equivalent supported form `pio run -d firmware -e
vdog_xiao_sense_proto -t clean` (exit 0, above) followed by the normal `pio
run` is what was used; the subsequent build was a genuine full rebuild (1105
compile actions) and picked up the new `components/vdog_board` component.

### Gate evidence (package 1.1 §5.4/§6)

Taxonomy note (F7): the standalone `python3 firmware/scripts/check_*.py`
invocations below are **host-side gate runs** — they show the gate logic
behaves, but they are neither a BUILD nor a HOST result. **BUILD** = the
cross-compile rows above; **HOST** = the `pio test -e native` Unity run only;
**DEVICE** = nothing here.

Green inside the BUILD above (proto environment only):

```text
vdog core-purity gate: 5 portable-core files scanned, no camera/SD/RTOS/SDK tokens
vdog board-config gate: 11 required keys present and equal + board=seeed_xiao_esp32s3
  (.../.pio/build/vdog_xiao_sense_proto/config/sdkconfig.json)   # fired on checkprogsize AND on firmware.bin
```

Negative demo on a **tampered copy** of the generated `sdkconfig.json`
(`SPIRAM_MODE_OCT` flipped `true → false` in the copy only; the built tree is
untouched):

```console
$ python3 firmware/scripts/check_board_config.py \
      --sdkconfig .../sdkconfig.tampered.json --board seeed_xiao_esp32s3
*** vdog board-config gate: ERROR: build configuration rejected (1 problem(s), .../sdkconfig.tampered.json, board from --board argument):
*** vdog board-config gate:   - SPIRAM_MODE_OCT: expected True, got False
$ echo $?
1
```

Control on the real generated file exits **0** with the "11 required keys
present and equal" line. Additional tampered fixtures (key deleted,
`SPIRAM=false`, `PARTITION_TABLE_CUSTOM_FILENAME` swapped, wrong `--board`)
each exit **1** naming every offending key with expected and actual values; a
missing fixture exits 1 naming the path. Type-strict comparison means `1` or
`"y"` cannot satisfy an expected `True`. Exit-code contract (review F3): **0**
pass, **1** gate failure *or* an unreadable/malformed/missing fixture (a config
that cannot be read is never a pass), **2** argparse usage error only —
verified: missing option → 2, unknown option → 2, malformed JSON → 1, missing
file → 1.

The purity gate's FreeRTOS coverage (review F5) was verified the same way with
scratch copies of `core/`: `xTaskCreate`, `xQueueSend`, `xSemaphoreGive`,
`pdTRUE`, `portMAX_DELAY`, `TickType_t` and `vTaskDelay` each exit **1** naming
file:line, while the real `core/` and an ordinary-prose control containing
"portable", "porting" and "pdq" stay clean (the kernel-symbol patterns are
deliberately case-sensitive so English words are not flagged).

The gates' SCons-mode behaviour was additionally exercised with a stub SCons
environment (outside the tree, no tracked file added): normal build registers
`checkprogsize` + `firmware.bin` post actions and both pass; `__test` registers
**no** gate (so `pio test` is unaffected, matching `gen_build_meta.py`'s
policy); an absent/partial `sdkconfig.json` inside a `*_test` build dir is
tolerated with a printed note; an absent `sdkconfig.json` in a *release* build
dir exits 1; a wrong `$BOARD` exits 1; loading the script in any environment
other than `vdog_xiao_sense_proto` exits 1.

### Host inventory observed for these runs

macOS 26.6.2 (build 25G83), Apple silicon `arm64` (`uname -m`); PlatformIO Core
**6.2.0** (`~/.local/bin/pio`); PlatformIO-bundled Python **3.12.12** (uv tool
env `~/.local/share/uv/tools/platformio/bin/python`); host `python3` **3.14.6**
(used only for the standalone gate invocations, never by PlatformIO). Matches
§1; nothing was installed or upgraded, and the resolved package set is still
the §2 matrix (`tool-ninja` 1.13.2 on this darwin host).

### Evidence level and DEVICE pointer

Every number above is **BUILD** (cross-compilation, host-side image analysis)
or **HOST** (native Unity) evidence. The `8MB` flash / `8MB` octal (OPI) PSRAM
values in the board report and in the gate's expected table are **build
configuration** — they come from `firmware/sdkconfig.defaults` and the
`components/vdog_board` declaration, not from the chip: `CONFIG_SPIRAM_TYPE_AUTO`
leaves real capacity to runtime detection. Physical flash capacity, octal-PSRAM
detection/usable bytes, boot-log console output and every other on-device
behaviour remain **DEVICE** evidence for packages 1.2–1.4 against an identified
authorized unit; no upload, monitor, erase or other device operation was
performed here, and no GPIO is configured or driven by any package 1.1 code.
Wiring stays unapproved (0.3/0.7 outstanding), so the only pin reference is the
`PROVISIONAL` comment block in `firmware/core/vdog_board.h`, which records that
[hardware/prototype-a/pin-map.csv](../hardware/prototype-a/pin-map.csv) is
candidate-only and that its GPIO21 SD-CS/user-LED sharing is unresolved.

### Package 1.1 addendum — PR-review round 2 (append-only, 2026-11-27)

Supersedes nothing above; records what the two gate scripts enforce **now**
after PR #5 round 2 (findings PR-R1..PR-R4, plan §10). Evidence: plan §11
"PR-review round 2 re-run" (12/12 regression cases; BUILD and HOST separate).

| Item | Behaviour after round 2 |
| --- | --- |
| `firmware/scripts/check_board_config.py` layer 1 (PR-R1) | Every `EXPECTED_KEYS` entry must be **EXPLICITLY declared** in the SOURCE `firmware/sdkconfig.defaults` (`KEY=y` / `KEY="value"`; boolean letters checked). A resolved-but-undeclared key fails the build: `… not declared in sdkconfig.defaults (resolved value may be an SDK default)`. The layer-2 resolved present-and-equal check is kept — "never silently taken from defaults" = declared **and** equal. |
| … layer 3 (PR-R2) | `components/vdog_board/CMakeLists.txt` must define `VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"` and `VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u`; mismatch or absence fails with expected-vs-actual naming the file. Single source of truth stays the script's `EXPECTED` table. |
| … layer 4 (PR-R3) | Effective partition table must agree **three ways**: PlatformIO `board_build.partitions` (SCons: `env.GetProjectOption` first — empirically the resolving source; `BOARD_BUILD['partitions']` is probed but is `None` under espressif32 8.0.0; parsed-ini fallback), resolved `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`, and the expected `partitions/vdog_8mb_two_ota.csv`; any mismatch names all three. `VDOG_GATE_DEBUG=1` prints the probed candidates. |
| … CLI override flags | `--defaults PATH`, `--component-cmake PATH`, `--platformio-ini PATH` (all default to the real repository files) allow tampered-copy fixtures without touching the repo; used by the §11 regression harness. Exit-code contract unchanged: 0 pass / 1 gate failure or unreadable input / 2 argparse usage only. |
| `firmware/scripts/check_core_purity.py` (PR-R4) | Four additional **case-sensitive** FatFs/disk-io rules: `ff.h`/`ffconf.h`/`diskio.h` (and `integer.h`/`ccsbcs.h`) includes; `f_mount/f_open/f_read/f_write/f_close/f_mkfs/f_opendir/f_readdir/…`; types `FIL/FILINFO/FATFS/FRESULT`; `disk_initialize/disk_status/disk_read/disk_write/disk_ioctl`. Generic FatFs typedefs (`BYTE/WORD/DWORD/UINT/WCHAR/DIR`) are deliberately excluded as ordinary/stdio-colliding words — `FILE` and `portable` prose stay clean; directory use is covered via `f_opendir`/`f_readdir`. |
| Evidence levels | Unchanged taxonomy: these are BUILD-time gates and host-side gate runs; still zero DEVICE evidence; `pio test -e native` (22/22) remains the only executed-test level. |

### Package 1.1 addendum — PR-review round 3 (append-only, 2026-11-27)

Supersedes nothing above; records the round-3 reviewer-note fixes to the gate
scripts (plan §10 round-3 block; evidence in §11 "PR-review round 3 re-run",
17/17 fixture cases).

| Item | Behaviour after round 3 |
| --- | --- |
| `check_board_config.py` layer 3 semantics (PR-N1) | CMake comment lines (`# …` EOL) are stripped before matching, and **every** occurrence of `VDOG_BOARD_ID_STR` / `VDOG_BOARD_PSRAM_SIZE_BYTES` must equal the expected value (finditer): zero occurrences fails (absent = field not set), and any wrong occurrence fails naming expected/got plus occurrence count — a second tampered `target_compile_definitions` block can no longer hide behind a correct first one (the compiler would take the last `-D`). Duplicate identical-good blocks pass. |
| `check_core_purity.py` FatFs API list (PR-N2) | Extended with `f_size`, `f_rewinddir`, `f_rewind`, `f_chdrive`, `f_utime`, `f_printf`, `f_fputs`, `f_findfirst`, `f_findnext` (all keep the mandatory `f_` prefix, so plain `printf`/`fputs`/`rewind`/`utimbuf` stay clean — regression control i2). |
| PR-N3 (skipped by agreement) | The header rule may over-match unrelated `*integer.h`/`*ccsbcs.h`-style includes; accepted because over-match is fail-closed and no such includes exist in `core/` — rationale in plan §12. |
| Size observation discipline | Clean-build `data`/`bss`/`firmware.bin` fluctuate by ≤16 B run-to-run (ESP-IDF metadata/padding non-determinism; `text` stable at 149597) — single-run sizes are quoted as snapshots with the observed range, never as stability claims. |

### Package 1.1 addendum — PR-review round 4 (append-only, 2026-11-27)

Supersedes nothing above; records the round-4 strict-parsing fixes to the
gate scripts (plan §10 round-4 block; §11 "PR-review round 4 re-run", 22/22
fixture cases). Root-cause pattern: never parse Kconfig/CMake semantics with
substring or lenient regexes — match COMPLETE tokens.

| Item | Behaviour after round 4 |
| --- | --- |
| `check_board_config.py` layer 1 strictness (PR-R5) | Source declarations are honoured only in the exact form Kconfig accepts: bool keys `CONFIG_KEY=y` (lowercase; `Y`/`1`/`0` are parsed by Kconfig but IGNORED ⇒ treated as undeclared), string keys `CONFIG_KEY="value"` (double quotes required, exact). Offending forms report the standard `not declared in sdkconfig.defaults (resolved value may be an SDK default)`. |
| `check_board_config.py` layer 3 full tokens (PR-R6) | Definition captures take the entire token after `=` (up to whitespace/paren, post comment-strip): PSRAM must wholly match `^[0-9]+[uUlL]*$` and equal 8388608 (expression characters fail naming the raw token — the compiler receives them verbatim), board id must be exactly `"seeed_xiao_esp32s3"` including quotes. All-occurrences checking (PR-N1) unchanged. |
| `check_core_purity.py` header rule (PR-R7) | BASENAME-anchored: `[<"](?:[dir/]*)?(ff\|ffconf\|diskio\|integer\|ccsbcs)\.h[>"]` — `esp_port/ff.h` hits, `buffer.h`/`my_effective_settings.h` stay clean. Supersedes the round-3 PR-N3 skip; §12 records the lesson. |
| Regression surface | Harness now covers a–e, f1–f5, g1–g2, h/h2/h3, i1/i2, j1/j2/j3, k1/k2, l1/l2, m1, k3a/k3b — 27/27 expected exits (driver out of tree, same location). |

### Package 1.1 addendum — PR-review round 5 (append-only, 2026-11-27)

Supersedes nothing above; records the round-5 fixes — the first STRUCTURAL
one (compile-time enforcement of compile flags) plus raw-line Kconfig syntax
and the widened header prefix class (plan §10 round-5 block; §11 "round 5
re-run", 27-case harness + compile proof).

| Item | Behaviour after round 5 |
| --- | --- |
| `check_board_config.py` layer 1 raw syntax (PR-R8) | The RAW assignment line is validated before any trimming (only trailing-WS/CRLF rstrip and whole-line-comment rejection): it must equal `CONFIG_KEY=y` (bool, lowercase) or `CONFIG_KEY="value"` (string, double-quoted) character-for-character — no spaces around `=`, no interior whitespace; duplicates judged on the LAST raw line; leading whitespace rejected fail-closed (deliberate, documented; Kconfig tolerates it, the repo file uses none). Offences report the standard undeclared message. |
| `vdog_board_idf.c` structural guards (PR-R9) | `#if !defined(VDOG_BOARD_ID_STR)` / `#if !defined(VDOG_BOARD_PSRAM_SIZE_BYTES)` `#error` guards: the adapter refuses to compile when the PRIVATE `target_compile_definitions` don't reach the compiler (PRIVATE→INTERFACE flip, deleted definitions). Compile proof: stripped-`-D` syntax-only compile with the build's own `xtensa-esp-elf-gcc` fails with both `#error`s (exit 1); with the flags it compiles (exit 0); the green BUILD proves the guards satisfied. |
| `check_board_config.py` layer 3 scope (PR-R9 belt-and-braces) | Every definition occurrence must sit inside a `target_compile_definitions()` block containing `PRIVATE` and no `INTERFACE`/`PUBLIC`; occurrences outside any such block (e.g. via `set()`) fail. |
| `check_core_purity.py` header prefixes (PR-R10) | Prefix class `(?:[^">]*/)?`: `./ff.h`, `fat-fs/diskio.h`, `a/b/c/ff.h` hit; basename stays anchored after the LAST slash so `my_ff.h`, `ffbuffer.h`, `buffer.h` stay clean. |
| Evidence levels | Unchanged taxonomy (BUILD/HOST only; zero DEVICE). The m2 syntax-only compile proof is BUILD-class evidence (compiler invocation, no device, no outputs written). |

### Package 1.1 addendum — PR-review round 6 (append-only, 2026-11-27)

Supersedes nothing above; records the round-6 layer-1 provenance fix and the
scope-wording correction (plan §10 round-6 block; §11 "round 6 re-run",
29-case harness).

| Item | Behaviour after round 6 |
| --- | --- |
| `check_board_config.py` layer 1 provenance (PR-R11) | An assignment whose PRECEDING non-blank line matches `^\s*#\s*default\b` (covers `# default:`, `# default: <expr>`, extra spaces/tabs) is ESP-IDF's own default-provenance signal — the pinned Kconfig does not count it as user selection — and therefore does NOT satisfy the explicit-declaration check; it fails with the standard `not declared ... (resolved value may be an SDK default)` message. Last-wins duplicates keep working (an unmarked later line overrides a marked earlier one). |
| Scope-check wording (PR-R12, wording only) | Corrected CMake semantics documented in `_block_scope`/`evaluate_component_definitions`: PRIVATE = target's own compilation only (policy: definitions stay local to the consuming component); PUBLIC = target AND consumers (rejected as scope creep); INTERFACE = consumers only (rejected: own compilation would silently lose the `-D`). Enforcement unchanged — all non-PRIVATE rejected; the `#error` guards enforce macro arrival at compile time regardless of scope. |
| Regression surface | Harness now covers a–e, f1–f5, g1–g2, h/h2/h3, i1/i2, j1–j3, k1/k2, k3a/k3b, l1/l2, m1, n1/n2 — 29/29 expected exits (driver out of tree, same location). |

### Package 1.1 addendum — PR-review round 7 (append-only, 2026-11-27)

Supersedes nothing above; records the round-7 parser-faithfulness rewrite
(plan §10 round-7 block; §11 "round 7 re-run", 32-case harness). Authority
for all marker semantics: the vendored loader the pinned build runs —
`esp_kconfiglib` (esp_idf_kconfig 3.13.0, ESP-IDF v6.1.0) at
`~/.platformio/penv/.espidf-6.1.0/lib/python3.12/site-packages/esp_kconfiglib/`,
driven by kconfgen via framework-espidf `tools/cmake/kconfig.cmake:211-212`
(`${python} -m kconfgen`) with `:230-237` writing the layer-2 resolved
`sdkconfig.json` (`--output json`) — i.e. the same parser sits under both
gate layers.

| Item | Behaviour after round 7 |
| --- | --- |
| `check_board_config.py` layer 1 provenance (PR-R13, mirrors PR-R11) | `last_raw_assignments()` mirrors the parser's `value_is_default` machine exactly: marker iff `line.strip() == "# default:"` (core.py:1399-1402; `constants.py:54`) — `# default: (expr)`, `#  default:`, `#default:` are ordinary comments; the flag PERSISTS across comments/blanks/malformed lines (core.py:1505-1514) and is consumed+cleared by the FIRST subsequent set (`CONFIG_([^=]+)=`, core.py:778/1416) or `is not set` (core.py:779/1506) assignment (clears core.py:1422/1440/1444/1476/1500/1520/1539/1543/1552 + loop-tail `:1610`); DEP-OP banner lines clear it (core.py:1404-1411; `constants.py:32-33`). Flagged assignment → recorded None → standard `not declared … (resolved value may be an SDK default)` failure. |
| Documented stricter deviations | `is not set` line as last mention of a required key records None (parser resolves unset there ⇒ certainly not an explicit pin; repo file contains none); exact raw-line syntax (PR-R5/R8) still decides declaredness; leading-whitespace lines match neither anchored regex (parser: malformed, marker persists) and stay fail-closed. |
| Round-6 correction | The round-6 rule ("preceding non-blank line matches `^\s*#\s*default\b`") was wrong in both directions: it let `# default:` + intervening comment + assignment PASS (parser: default → must fail; new p1 → 1, pre-fix 0) and rejected `# default: (some expr)` (parser: ordinary comment → explicit pin; n2 expectation CORRECTED to 0). |
| Regression surface | Harness now covers a–e, f1–f5, g1–g2, h/h2/h3, i1/i2, j1–j3, k1/k2, k3a/k3b, l1/l2, m1, n1, n2 (corrected), p1, p3, p4 — 32/32 expected exits (driver out of tree, same location). |

### Package 1.1 addendum — PR-review round 8 (append-only, 2026-11-27)

Supersedes nothing above; records the round-8 deprecated-section fidelity
fix (plan §10 round-8 block; §11 "round 8 re-run", 35-case harness). Same
authority chain as round 7 — kconfgen loads every `sdkconfig.defaults` via
`config.load_config(temp_file, replace=False)` (`kconfgen/core.py:559-569`)
with `load_deprecated` at its default `False` (`esp_kconfiglib/core.py:1151
-1157`), plus the F-1 comment fix (tip `a6faac8`).

| Item | Behaviour after round 8 |
| --- | --- |
| `check_board_config.py` layer 1 deprecated-section skip (PR-R14) | `last_raw_assignments()` mirrors `in_deprecated_block` (core.py:1351/1404-1411; banners `constants.py:32-33`): BEGIN/END toggle it and clear the `# default:` flag; WHILE inside, EVERY line is skipped exactly as the default-mode loader does (`if in_deprecated_block and not load_deprecated: continue`, core.py:1413-1414) — assignments inside the section are never recorded (earlier outside record survives), cannot consume the marker, and an unclosed BEGIN skips to EOF (loop-tail reset :1610 never clears `in_deprecated_block`). Marker-section edge cases documented and probe-verified (banner clears the flag; first assignment after End is a user pin). |
| F-1 (round-7 approval nit, tip `a6faac8`) | Comment-only wording fix: leading-whitespace lines are ones the pinned parser IGNORES as malformed (core.py:1512-1513) — NOT "tolerated"; fail-closed rejection is the faithful behaviour. `grep -n tolerat` on the script: no hits. |
| Regression surface | Harness now covers a–e, f1–f5, g1–g2, h/h2/h3, i1/i2, j1–j3, k1/k2, k3a/k3b, l1/l2, m1, n1, n2 (corrected), p1, p3, p4, q1, q2, q3 — 35/35 expected exits (driver out of tree, same location); q1 pre-fix bypass reproduced at a6faac8 (exit 0) before the fix. |

### Package 1.1 addendum — round-8 approval notes (append-only, 2026-11-27)

Round 8 approved (`safe to hand back`) with two non-blocking provenance
notes folded in at comment/docs level only — no behaviour change.

| Note | Content |
| --- | --- |
| INFO-1 (gate docstrings) | Provenance chain completed: kconfgen never hands the parser the raw file — `_replace_empty_assignments` (kconfgen/core.py:547-557) writes a temp file where every line is `.strip()`'d (:552) and lines ending `=` gain an `n` (:553-554), then `load_config(temp_file, replace=False)` runs on THAT. The mirror mirrors the PARSER (post-preprocessing); the preprocessing can only ever induce OVER-rejections in the gate — it strips whitespace the exact-match already rejects, its `=`-suffix completion only rescues values the strict PR-R5/PR-R8 syntax rejects anyway, and it can never create a canonical clean line or `# default:` marker the mirror misses (marker matching already strips; the transform only shortens lines or appends `n`). |
| INFO-2 (plan §12 residual) | The deprecated-NAME-mapping branches (esp_kconfiglib core.py:1428-1440, old-name→new-name set with forced marker clear at :1440) are not mirrored; effect class is over-rejection only (mirror records under the raw key; `EXPECTED` uses canonical names; layer 2 + pin scan backstop). Consciously accepted residual. |

### Package 1.1 addendum — PR-review round 9 (append-only, 2026-11-27)

Supersedes nothing above; records the round-9 line-boundary class fix
(plan §10 round-9 block; §11 "round 9 re-run", 45-case harness).

| Item | Behaviour after round 9 |
| --- | --- |
| Line model (PR-R15) | Gate line iteration mirrors the loader's universal newlines (\n/\r\n/\r ONLY — U+2028/U+2029/\v/\f/NEL are ordinary characters): `_read_text` opens with explicit `newline=None`; `_split_universal()` splits on \n and feeds the layer-1 mirror machine and the layer-4 platformio.ini fallback (configparser parity — the tool PlatformIO itself uses). NEVER `str.splitlines()` for loader-consumed text. Citations: kconfgen/core.py:547-557 (preprocessing open+iterate), esp_kconfiglib core.py:2464/2469/2533 (opens) + :1396 (parse loop). |
| CMake-facing classes (PR-R15) | Definition regexes use CMake's argument-lexer terminators (space/TAB/newline/`(`/`)`/`;`) instead of Python `\s` (which matches U+2028..\x85): `=8388608u\u2028u` now captures the full tampered token and fails the complete-literal check; hidden separators around `=` defeat the definition match. Comment EOL (`#.*`) was already \n-only — documented parity. |
| Purity scanner decision | Keeps `str.splitlines()` deliberately: finest split = detection superset (tokens/`#include`s contain no separator chars, so finer splitting cannot fragment matches; catches `;\u2028#include <ff.h>` the gcc \n-only model misses); separator-inside-token tampering defeats both scan models but fails loudly at compile/link (native build + `#error` guards). |
| Parser-truth note (r3) | `CONFIG_X=y\u2028junk` is ONE line the parser accepts via the first-character bool rule (core.py:1467-1479) — user-selected `y`; the gate's exact raw-line match still rejects (documented stricter deviation). |
| Regression surface | Harness now covers a–e, f1–f5, g1–g2, h/h2/h3, i1/i2, j1–j3, k1/k2, k3a/k3b, l1/l2, m1, n1, n2 (corrected), p1, p3, p4, q1–q3, r1, r1b ×4, r2, r3, r4, r4b, r4c — 45/45 expected exits; all six fail-open faces reproduced at exit 0 on 6c24739 before the fix. |

## Package 1.2 addendum (append-only, 2026-11-28)

Part A (desk) only — BUILD/HOST evidence. No device was connected, flashed,
monitored or erased; `docs/bench-assignment.md` records zero Part B rows and
`docs/hardware-identity.md` carries PENDING device rows. The 1.1 addendum's
`vdog-core@1.1.0` row is superseded below (append-only style: history kept).

### Host inventory re-confirmation (2026-11-28, this Mac)

| Item | Value | How observed |
| --- | --- | --- |
| OS/runner | macOS 26.6.2 (build 25G83), arm64 | `sw_vers`, `uname -m` |
| PlatformIO Core | 6.2.0 (`~/.local/bin/pio`, uv-managed tool env) | `pio --version` |
| PlatformIO bundled Python | 3.12.12 (`~/.local/share/uv/tools/platformio`) | `pio` shebang + that interpreter's `--version` |
| Host Python 3 | 3.14.6 (gate-script CLI runs only) | `python3 --version` |

### What package 1.2 added (Part A)

| Path | Role |
| --- | --- |
| `firmware/core/vdog_mem.{h,c}` | tagged memory baseline: per-field `field_set` + MEASURED/CONFIGURED source tags (finding 2); `vdog_mem_check_baseline()` rejects the Plus/N16R8-shaped, 4 MiB-flash, no-PSRAM and quad-only-PSRAM classes with code + offending field (bands -20…-23); `vdog_mem_record_flash_size()` records the PHYSICAL capacity as MEASURED and STICKILY fails the set on any header-vs-physical disagreement (`flash_cross_fail`: even a baseline-equal physical value stays rejected — a cross-check failure can never produce success-form memory logs, round-2 review); `vdog_mem_record_flash_size()` REFRESH-CLEARS (every call resets value/source/bit/cross-fail first, so a failed call leaves an honest UNSET, never a stale MEASURED field — round-3 review); `vdog_mem_format_detected()` renders `flash_size=8MB[measured] … psram_mode=opi[configured]` and can never print a CONFIGURED value as detected |
| `firmware/core/vdog_recovery.{h,c}` | ROM-form boot-mode classifier pinned to the DOCUMENTED esptool ESP32-S3 boot-log forms only: `boot:0xNN (DESCRIPTION)` at a WORD boundary (so `reboot:` never matches) with REQUIRED hex strap value and the COMPLETE description validated BY MODE — `(SPI_FAST_FLASH_BOOT)` simple form only, `(DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))`/`(DOWNLOAD(USB/UART0))` inner group with exact documented payload, nothing after the closed group (rounds 2–4 review; round-1 invented tokens retired), or the exact-shape `ESP-ROM:esp32s3-usb-jtag-<digits>` banner + structurally sanitized identity line: text enters ONLY via validated setters (closed-set chip enum, board tag restricted to the project grammar `VDOG-<core 1..6 alnum>-<serial 1..4 digits>` with a reserved terminator slot — 16-char tag overflow fixed in round 2, MAC/hex/`0x…`/free-text labels all rejected by the round-4 grammar, bounded render), SDK revision decodes as `major*100+minor` (102 → 1.2), and the struct holds only the 16-bit MAC tail (no full-MAC or eFuse-raw member exists) |
| `firmware/core/vdog_straps.{h,c}` | 42-row strap/reserved/candidate claim gate: straps GPIO0/3/45/46 + native-USB GPIO19 (D-) / GPIO20 (D+, datasheet-corrected) REJECT naming pin + role; GPIO22–25 (absent on ESP32-S3), GPIO26–32 (SPI flash bus) and GPIO33–37 (octal-PSRAM bus) are REJECT reserved rows — a pin that is not a usable GPIO never returns OK (PR-review round 1 High); camera/SD candidates return PROVISIONAL only; GPIO21 UNCLAIMED (claim → PROVISIONAL naming the unresolved SD-CS/user-LED sharing, 0.3/E07 pending); mic GPIO41/42 DISABLED → REJECT; gpio > 48 REJECT `invalid-gpio` |
| `firmware/core/library.json` | `vdog-core@1.2.0`, five exported headers (`vdog_core/vdog_board/vdog_mem/vdog_recovery/vdog_straps`) |
| `firmware/components/vdog_board/vdog_board_hw.{h,c}` | read-only target adapter: CONFIGURED fields from `CONFIG_*` `#ifdef`s (unset key = field not set), MEASURED flash capacity ONLY from `esp_flash_get_physical_size` (`esp_flash_get_size` is the image-header capacity — cross-check input to `vdog_mem_record_flash_size()`, never the recorded value; PR-review round 1 High); PSRAM from `esp_psram_get_size`; identity via validated setters — closed-set chip name from `esp_chip_info` (`CHIP_ESP32S3` spelling in IDF v6.1), `/100`+`%100` revision decode, `esp_read_mac` (tail kept, full MAC discarded). No pin driving, no strap claims, no microphone init |
| `firmware/components/vdog_board/CMakeLists.txt` | SRCS += the three new core sources + `vdog_board_hw.c`; REQUIRES += `esp_hw_support esp_psram spi_flash` |
| `firmware/src/main.c` | one `mem:` + one `identity:` boot line after the 1.1 board line; rejected sets log `memory check rejected: … (field …)`; the read-phase warning distinguishes a header-vs-physical cross-check DISAGREEMENT from a query FAILURE (round-2 review — a cross-check failure is never worded as a query failure, and the sticky `flash_cross_fail` state rules out success-form lines) — the decision stays in the portable modules |
| `firmware/test/test_vdog_mem/`, `test_vdog_recovery/`, `test_vdog_straps/` | 18 + 18 + 10 host cases + three `cpp_smoke_*.cpp` consumer TUs (dual `app_main`/`main` entries: embedded runs are compile/link qualification only). Round-1 regressions pinned: header-8MB-vs-physical-16MB flash mismatch rejected naming `flash_size_bytes`; prose containing "download"/"basic" classifies UNKNOWN; SDK revision 102 renders 1.2; unlisted chip text and malformed tags rejected at the setter. Round-2 regressions pinned: documented ROM lines classify (`SPI_FAST_FLASH_BOOT`, `DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2)`, `DOWNLOAD(USB/UART0)`), malformed lookalikes stay UNKNOWN (`reboot: download failed`, `boot:0x3 DOWNLOAD_BOOT`, `boot: download`, `boot:0x()`); documented unsupported modes → UNKNOWN; maximum-accepted-length 16-char tag stores terminator in bounds; compact-MAC `1a2b3c4d5e6f`-style labels rejected; flash cross-check failure in BOTH directions keeps `check_baseline` rejecting even when the physical value alone equals the baseline (sticky `flash_cross_fail`), and an agreeing re-record clears it. Round-3 regressions pinned: truncated/partial descriptions (`boot:0x3 (DOWNLOAD`, `(DOWNLOAD_BOOT(UART0)`, unterminated inner group) and prose after the leading token (`(SPI_FAST_FLASH_BOOT failed)`, `(DOWNLOAD more text)`) or after the closed group stay UNKNOWN; the usb-jtag banner requires the full documented shape `esp32s3-usb-jtag-<digits>` with nothing after it; a flash `record` with a 0 input clears any earlier MEASURED flash field (no stale-evidence retention) and the baseline then reports MISSING. Round-4 regressions pinned: descriptions validated BY MODE — `(SPI_FAST_FLASH_BOOT(failed))` and `(SPI_FAST_FLASH_BOOT(USB/UART0))` never NORMAL, `(DOWNLOAD)`, `(DOWNLOAD())`, `(DOWNLOAD(garbage))`, `(DOWNLOAD_BOOT)`, shortened `(DOWNLOAD_BOOT(UART0))` and cross-mode payload swaps never DOWNLOAD, while the verbatim documented forms stay NORMAL/DOWNLOAD; board tags accept ONLY the project grammar `VDOG-<core 1..6 alnum>-<serial 1..4 digits>` (case-insensitive) — `0x020000000001`, `0200.0000.0001`, `1a-2b-3c-4d-5e-6f`, `1a2b3c4d5e6f`, free text (`dev.01`, `dev01`) and malformed `vdog-*` shapes all rejected, `vdog-pa-01`/`VDOG-PA-1`/grammar-max `vdog-abc123-4321` accepted with the terminator in bounds |

### Part A command record (repository root, this host)

| Command | Exit | Recorded result |
| --- | --- | --- |
| `pio run -d firmware -e vdog_xiao_sense_proto` | 0 | SUCCESS; **0** `warning:` lines; both gate registrations fired (purity: "11 portable-core files scanned, no camera/SD/RTOS/SDK tokens"; board-config line printed by BOTH post actions) |
| `pio run -d firmware -e vdog_xiao_sense_proto -t size` | 0 | text 153573 / data 63156 / bss 376829 (dec 593558) — round-4 snapshot: **equal section sizes** to the round-3 revision. (Not a code-balance coincidence: the Part A boot path never calls the classifier or the board-tag setter, so those functions are absent from the linked app in BOTH revisions — verified by `nm` on `firmware.elf` — and gc-sections drops them; binary hashes differ between local builds, as expected. They qualify via the native suite and the embedded compile/link run until the Part B drill wires the boot path to call them); slot margin vs the 3 MB OTA slot still ≫4× |
| `pio test -d firmware -e native` | 0 | **68/68** (22 inherited + 18 mem + 18 recovery + 10 straps), 0 failed |
| `pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing` | 0 | all 5 suites `[SKIPPED]` — compile/link only, never executed |
| `python3 firmware/scripts/check_core_purity.py` (standalone) | 0 | 11 core files scanned |
| `python3 firmware/scripts/check_board_config.py --sdkconfig …/config/sdkconfig.json --board seeed_xiao_esp32s3` | 0 | 11 keys present-and-equal, board agreed by all three sources |
| same, with `ESPTOOLPY_FLASHMODE_QIO` poisoned to `"y"` | 1 | "build configuration rejected (1 problem(s))" — type-strict compare holds |
| same, bad usage (`--bogus-flag` / missing required args) | 2 | argparse usage error, documented contract |

### F6 (1.1 carry-over) resolution

`Import("env")` stays INSIDE `_scons_main()` in both gate scripts —
documented INTENTIONAL variant of `gen_build_meta.py`'s module-level import
(the gate scripts are dual-mode: SCons extra script + CLI imported by the
tools/firmware harness; a module-level SCons import would raise outside a
build). Rationale comments sit at the import sites in both scripts; the
CLI exit-code contract above re-verified unchanged (0/1/2).

### F7(b) (1.1 carry-over) — LANDED on `main` (2026-11-28, Item #17 PR B)

The two out-of-tree scenario drivers are re-homed as
`tools/firmware/tests/test_firmware_gates.py` (123 cases): 31 for
`check_board_config.py` — acceptance of the real repo baseline via the
CI invocation, one poisoned variant per layer of the four-layer agreement
(source declarations, resolved config, component definitions, effective
partition table), the documented over-rejection controls, unreadable/
missing/malformed inputs, the `0 = agree / 1 = gate failure / 2 = usage`
exit contract, and the SCons-mode path (environment guard, `__test`/
`nobuild`/`clean` skip targets, post-action registration, `*_test`
build-dir tolerance) against a stub SCons `env`; 92 for
`check_core_purity.py` — every banned token class injected into a clean
fixture core with its file:line reason, the documented look-alike
controls (basename-anchored FatFs headers, `esp32s3` literal, generic
typedefs), the PR-R15 `splitlines()` U+2028 detection superset, prune/
extension/required-source scan modes and the usage exit. The CI
`firmware-package-tests` job (uv-locked) now guards both gate scripts, so
a future edit can never silently widen them. The earlier deferral reason
— unmerged `opencode/0.9-*` branches owning `tools/firmware/tests` — was
mooted by the Stage 0.9 closure (PR #8 `5d314c8`); the harness lives on
`main` — `uv run --python 3.12 --with-requirements
tools/firmware/requirements-dev.lock pytest tools/firmware/tests` now runs
the full tool suite including these gate-script cases.

### Macro-rename residual (A7 probe, recorded)

Host `cc -fsyntax-only` on `vdog_board_idf.c` (stub `sdkconfig.h`, core
includes): neither `VDOG_BOARD_ID_STR` nor `VDOG_BOARD_PSRAM_SIZE_BYTES`
defined → 2 `#error`s; only one defined → exactly 1; both defined → clean.
Renaming either macro is compile-loud; no further guard needed in Part A.

### Part B scope update (2026-11-28, lead equipment confirmation)

The owner confirmed a **multimeter** and an **inline USB-C power meter**, so
rails/current moved from UNVERIFIED to a **gated owner-performed DEVICE
step** (plan §6 step 6): USB supply current at boot/idle via the inline
meter and 3V3 via the multimeter, with the owner handling all probes and
recording readings into `docs/hardware-identity.md` §3 (all rows PENDING).
Power stays USB from the Mac with the battery physically disconnected; no
other electrical measurement, no erase/eFuse/format/NVS-overwrite/filesystem
upload, and no monitor beyond the recorded session remain in force. No
measurement has been performed as of this commit — Part B is still gated on
board marking photos, operation-time port re-identification and the lead's
release of the reviewed Part A commit.

### Driver arbitration (2026-11-28, recorded per append-only policy)

A second member session drove the same Part A in `.worktrees/1.2-impl`
(branch `opencode/1.2-board-bringup`, now `9f27f96`, clean, never pushed, no
PR), beginning by overwriting in-progress files here at 01:10–01:14 UTC.
The lead could not answer the arbitration question (turn ended), so the
package owner ruled: **single driver = this branch; PR #6 at `23f53d4` is
the only reviewable Part A change** (pushed, 4/4 CI, reviewer tasked). The
other tree is frozen for handoff only; its F7(b) re-home of the gate scenario
drivers stays on `opencode/1.2-board-bringup` as the 0.9 merge-window
follow-up (the plan's 0.9-pending guard excludes it from this PR). Both
collision states remain preserved at `tmp/opencode/1.2-collision-20261128/`
for byte comparison. Ruling communicated in-thread (msg_416a06b416e2) and to
the other session with a freeze request (msg_903c3a320897).
