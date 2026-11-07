# Research sources and evidence boundaries

Checked on 2026-11-07. Links document technical capabilities and limitations;
they do not verify this project's performance, supplier prices, or completed
implementation. Versioned dependencies must be selected and locked during
Stage 0 rather than inferred from a moving `stable`, `latest`, or `master` URL.

## Planning conversation

[Research Dog Camera Plan](chatgpt-conversation://6aef12d8-967c-83ed-be5e-870d042384f1)
was read through the connected conversation tool. The accessible response
contained five recent user/assistant exchanges, no attachments, and no older
page cursor. Earlier requirements alluded to by those exchanges were not
available as original messages. The documentation does not invent their
contents.

The accessible user messages requested mainland-China price references,
hardware below 150 excluding SD card and harness, considered Wi-Fi-only cost,
and then prioritized ESP32-S3 with 128GB SD. The accompanying assistant replies
proposed CNY pricing, a 72-hour loop-recording goal, N16R8/OV2640 hardware,
Flutter, a Rust backend, optional IMU, and post-processing stabilization. Those
proposals are identified as an engineering baseline, rather than represented
as independently proven feasibility or explicit user approval of every detail.
Earlier assistant proposals using P4, 256GB, LTE, or a mandatory IMU do not
override the latest S3/128GB priority.

## Primary hardware and platform references

| ID | Source | What it supports; limits |
| --- | --- | --- |
| H1 | [Espressif ESP32-S3-WROOM-1/1U datasheet, v1.8](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf) | N16R8 memory arrangement, module electrical limits, unavailable PSRAM pins. Does not establish recording performance. |
| H2 | [Espressif DevKitC-1 v1.0 guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html) | Board-family setup and GPIO48 LED on v1.0. Does not validate a third-party N16R8 board. |
| H3 | [Espressif DevKitC-1 v1.1 guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html) | Revision-specific board documentation; GPIO38 LED change. Acquire the actual board schematic. |
| H4 | [Espressif esp32-camera](https://github.com/espressif/esp32-camera) | S3/OV2640 support, JPEG/PSRAM considerations, ESP-IDF integration. Pin a tested release/commit; do not copy its unrelated example pin map. |
| H5 | [ESP-IDF SDMMC host driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sdmmc_host.html) | GPIO-matrix routing, bus width and clock configuration. Board signal integrity remains unverified. |
| H6 | [ESP-IDF SD pull-up requirements](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sd_pullup_requirements.html) | SD pull-up design requirements. Review the exact socket/breakout. |
| H7 | [SD Association capacity and filesystem standards](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/) | SDXC uses exFAT by standard; 128GB is SDXC. A user-prepared FAT32 card differs from that default. |
| H8 | [ESP-IDF FatFs integration](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/fatfs.html) | Mounting, synchronization, and optional exFAT configuration. Stable resolved to v6.1 during this check; exFAT was not enabled by default and had no standard menuconfig enablement. Recheck the pinned implementation version. |
| H9 | [Espressif S3 schematic checklist](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html) | Supply design, decoupling, memory and reserved-pin considerations. The 500mA chip recommendation is not a whole-system power budget. |
| H10 | [ST LSM6DS3TR-C product information and datasheet](https://www.st.com/en/mems-and-sensors/lsm6ds3tr-c.html) | Optional six-axis IMU candidate and I²C/SPI interfaces. Does not establish camera synchronization or stabilization quality. |
| H11 | [PlatformIO ESP32-S3-DevKitC-1 board](https://docs.platformio.org/en/latest/boards/espressif32/esp32-s3-devkitc-1.html) | The named board definition is documented as N8/no PSRAM. N16R8 needs reviewed explicit memory configuration. |
| H12 | [ESP-IDF OTA documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html) | Dual application slots, OTA data, and rollback support. Does not by itself implement secure OTA for this project. |
| H13 | [ESP-IDF flash encryption](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/flash-encryption.html) | Internal-flash protection and provisioning implications. It does not encrypt removable SD recordings. |

## Primary software references

| Source | What it supports; implementation must verify |
| --- | --- |
| [Apple local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy) | iOS permission/discovery behavior; actual entitlements and OS behavior tested in app support matrix |
| [Android Wi-Fi permissions](https://developer.android.com/develop/connectivity/wifi/wifi-permissions) | Permissions vary by OS/target SDK and API used |
| [Android local-network permission](https://developer.android.com/privacy-and-security/local-network-permission) | Current target/API-dependent local-network policy; freeze SDK rather than assuming one universal permission |
| [Android Wi-Fi Network Request API](https://developer.android.com/develop/connectivity/wifi/wifi-bootstrap) | System-mediated accessory-network connection; no silent universal join guarantee |
| [Apple background strategies](https://developer.apple.com/documentation/BackgroundTasks/choosing-background-strategies-for-your-app) | OS-controlled background execution; app must not promise uninterrupted arbitrary transfers |
| [Flutter JPEG decoder](https://api.flutter.dev/flutter/dart-ui/instantiateImageCodec.html) | Image decoding primitive, not a ready-made indexed MJPEG video player |
| [Axum body limits](https://docs.rs/axum/latest/axum/extract/struct.DefaultBodyLimit.html) | Request body bound configuration; streaming extractors/routes must be tested individually |
| [SQLite atomic commit](https://sqlite.org/atomiccommit.html) | Database commit behavior; does not make DB plus external media files one atomic transaction |
| [Tokio process API](https://docs.rs/tokio/latest/tokio/process/struct.Command.html) | Subprocess invocation/lifecycle primitives; sandboxing and resource controls remain project work |
| [FFmpeg filters](https://github.com/FFmpeg/FFmpeg/blob/master/doc/filters.texi) | vidstabdetect/vidstabtransform two-pass processing; verify compiled filter availability |
| [FFmpeg licensing](https://ffmpeg.org/legal.html) | Build/dependency distribution obligations depend on configuration; repository MIT does not replace them |

## Price and measurement policy

The cost tables are engineering allocations, not newly verified Chinese-market
quotes. Historical conversation prices are not reused as current quotations.
A purchase-ready BOM must attach dated supplier evidence, quantities,
availability, tax/freight assumptions, assembly/test allowances, and the exact
part variant. No order, supplier contact, hardware test, or purchase occurred
while writing these documents.

The retention formulas are calculations based on the stated nominal capacity
and reserves. They are not measurement results. Real usable capacity, allocated
filesystem bytes, scene-dependent JPEG sizes, protected footage, and card wear
must be measured. No hardware, firmware, app, backend, image-quality, thermal,
runtime, stabilization, or animal-wear claim has been verified by this source
review.
