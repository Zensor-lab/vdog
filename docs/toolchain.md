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
| `tool-ninja` | **range `>=1.7.1,<2`** (the one host-resolved package, 2026-11-21 — see the exception note below): resolves to **1.13.2** on this darwin host, **1.7.1** on linux_x86_64 CI (registry publishes no linux_x86_64 build above 1.7.1) | build system |
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
darwin_x86_64/darwin_arm64 only, 1.10.2 linux_aarch64/arm, 1.9.0
darwin+windows, 1.7.1 linux_x86_64 only. No single exact version therefore
covers both this darwin host (0.2 qualification) and the `ubuntu-24.04` CI
runner, so `tool-ninja` is the ONE host-resolved package:
`platformio/tool-ninja@>=1.7.1,<2` — darwin resolves 1.13.2 (the
0.2-qualified version, confirmed unchanged here by `pio pkg list`),
linux_x86_64 CI resolves 1.7.1. This is the documented CI-host exception,
parallel in spirit to the range-resolved IDF Python layer (§7); every
other package above remains exactly pinned.

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
Unity pin and the exact pins (`platformio/espressif32@8.0.0`, `==2.1.9`)
are the reproducibility contract.

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
