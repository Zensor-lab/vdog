# PlatformIO support: XIAO ESP32S3 Sense

Checked 2026-11-16; build evidence closed 2026-11-19 (package 0.2).
**PlatformIO officially lists the XIAO ESP32S3 base board with both ESP-IDF
and Arduino support,** and package 0.2 added a real project cross-build:
see [toolchain qualification](toolchain.md). The Sense camera/SD expansion
still needs project-specific configuration and device qualification. No
upload, device test or hardware operation was performed for package 0.2 —
BUILD/HOST evidence only.

## 1. Verified upstream support

| Item | Evidence | Meaning for vdog |
| --- | --- | --- |
| Board ID | `seeed_xiao_esp32s3` | Use the XIAO base-board target, not `esp32cam` or a generic N16R8 board |
| Frameworks | Official manifest lists `espidf` and `arduino` | Keep the existing proposed ESP-IDF C++ architecture |
| Memory | Board metadata declares 8MB flash; Seeed describes Sense with 8MB PSRAM | Verify detected memory and configure octal PSRAM explicitly for the pinned SDK |
| Candidate platform | Official `platformio/espressif32` release 8.0.0 | Candidate to qualify in package 0.2; not a claim that vdog has built successfully |
| Sense peripherals | Camera, microphone and SPI microSD are expansion-specific | Board selection alone does not initialize camera/SD; microphone stays disabled |

Sources: [PlatformIO board documentation](https://docs.platformio.org/en/latest/boards/espressif32/seeed_xiao_esp32s3.html),
[release 8.0.0](https://github.com/platformio/platform-espressif32/releases/tag/v8.0.0),
[versioned board manifest](https://raw.githubusercontent.com/platformio/platform-espressif32/v8.0.0/boards/seeed_xiao_esp32s3.json).
These establish upstream metadata/support, not this project's runtime behavior.

## 2. Candidate configuration, not a completed project

The bootstrap assignment can start from this pinned platform candidate:

```ini
[env:vdog_xiao_sense_proto]
platform = platformio/espressif32@8.0.0
board = seeed_xiao_esp32s3
framework = espidf
monitor_speed = 115200
```

This snippet intentionally does not pretend to be a complete `platformio.ini`.
Package 0.2 must pin PlatformIO Core, bundled ESP-IDF/compiler/packages and the
camera component; supply the project source, reviewed `sdkconfig` defaults and
partition table; then record a real clean build. If another official platform
release is necessary, document the compatibility reason and retest. Do not add
a third-party platform fork or switch frameworks silently.

The manifest's `qio_opi` memory setting and `default_8MB.csv` are under its
**Arduino** configuration. They do not automatically configure an ESP-IDF
project. Set and verify IDF's 8MB flash and octal-PSRAM configuration using the
pinned SDK's options, alongside USB/console and signed dual-slot OTA sizing.
See [Seeed ESP-IDF setup](https://wiki.seeedstudio.com/xiao-esp32s3-freertos/)
and the [ESP-IDF v6.1 configuration reference](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-reference/kconfig-reference.html).

## 3. Sense-specific qualification

1. Inventory base/Sense PCB revisions, sensor ID, lens/flex and exact card. Current
   Seeed documentation describes OV5640 fixed-focus/OV3660 transition shipments;
   OV2640 belongs to older units. Do not hardcode the former AI-Thinker camera map.
2. Use the reviewed XIAO DVP/SCCB wiring and a pinned driver supporting the actual
   sensor. Start with the existing JPEG VGA/SVGA measurement matrix, not the
   camera's maximum megapixel mode. Media v1 bounds still apply.
3. The Sense card socket is **SPI**, not the old 1-bit SDMMC path. Seeed's current
   table gives SCK GPIO7, MISO GPIO8, MOSI GPIO9 and CS GPIO21. Reconcile actual
   revision/schematic and the GPIO21 user-LED interaction before use; do not run
   a generic Blink example against the SD chip-select line.
4. Start with a genuine **32GB FAT32** card, matching Seeed's published tutorial.
   Qualify sustained capture, latency, rollover and power-loss recovery; larger
   cards are a separate future qualification, not an assumed capability.
5. Validate the board's battery input/onboard power circuit and USB-C behavior.
   The owner still charges the unplugged pack externally. An onboard charger
   exists, so disconnect the pack before USB service unless an isolation procedure
   has been reviewed; the old external 5V boost is not a default requirement.
6. Qualify actual frame buffers, PSRAM, heap and camera+SPI SD+HTTPS scheduling.
   Keep bounded one-connection networking until tests support expansion.
7. Prove two signed OTA slots, NVS/identity and rollback fit actual 8MB flash;
   boot/record/rollback behavior still needs the identified hardware.

Sources: [Seeed getting started and revisions](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/),
[Sense microSD tutorial](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/),
[Espressif camera driver](https://github.com/espressif/esp32-camera).

## 4. Build evidence — closed by package 0.2 (2026-11-19)

Recorded in [docs/toolchain.md](toolchain.md): resolved platform
`platformio/espressif32@8.0.0` (ESP-IDF v6.1.0 via `framework-espidf
4.60100.0`), toolchain/component lock versions incl. the tracked
`firmware/dependencies.lock`, the two project environments
(`vdog_xiao_sense_proto`, `native`), explicit ESP-IDF flash-8MB/octal-PSRAM/
USB-console/partition Kconfig with verification method, the 8MB two-slot
partition budget derived from the measured minimal image, the pinned
`espressif/esp32-camera` 2.1.9 compiled as a real link-time dependency, and
the clean cross-build command results. The candidate in §2 is now the
project baseline: `pio run -d firmware -e vdog_xiao_sense_proto` and
`pio test -d firmware -e native` pass from a clean checkout (BUILD/HOST
evidence). Package 0.2 closed on this pinned/reproducible build evidence and
configuration without waiting for the later recorder or OTA implementation.

## 5. Later device qualification

Actual memory/USB recovery, camera and SPI-SD behavior are device evidence in
packages 1.2–1.4. Recording/retention and concurrent load follow in Stage 1/2;
signed OTA staging and rollback are implemented/tested in 2.10–2.11. These need
an identified authorized unit/port and cannot be prerequisites that make the
0.2 bootstrap depend on later stages.

At present (package 0.2, 2026-11-19): upstream support is **verified from
documentation**; the project cross-build and `native` host tests are
**verified as BUILD/HOST evidence** in [docs/toolchain.md](toolchain.md);
hardware behavior remains **UNVERIFIED** pending the device packages above.
Stage 0 completion still requires the remaining packages, not merely a board
entry or this configuration.
