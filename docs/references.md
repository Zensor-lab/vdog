# Research sources and evidence boundaries

Hardware references rechecked/updated on 2026-11-09; software references were
reviewed on 2026-11-07. Links document capabilities and limitations, not this
project's performance, supplier prices or completed implementation. Lock actual
dependencies during Stage 0 rather than inferring them from moving `stable`,
`latest`, `develop` or `master` URLs.

## Planning conversation and subsequent direction

[Research Dog Camera Plan](chatgpt-conversation://6aef12d8-967c-83ed-be5e-870d042384f1)
was read through the connected conversation tool on 2026-11-07. The accessible
response contained five recent user/assistant exchanges, no attachments and no
older cursor. Earlier requirements alluded to there were not available as
original messages; the docs do not invent their contents.

Those messages requested China pricing, hardware below 150 excluding SD and
harness, considered Wi-Fi-only cost and prioritized S3 with 128GB. Assistant
replies proposed 72h loop recording, N16R8/OV2640, Flutter/Rust, optional IMU and
off-device EIS. Those proposals were not measured feasibility.

In this repository chat on **2026-11-09**, the user replaced S3 with **classic
AI-Thinker ESP32-CAM + OV2640**, selected a **nominal 3.7V 1000mAh pack**, described
**about 1–2h runtime**, and confirmed **recording mainly, Wi-Fi only when needed**.
The active baseline has radio-off recording and deliberate time-bounded local
access. The owner then selected separate charging after removing the camera
and unplugging its pack, small-dog-first chest mounting (their dog below 8kg),
and dry-weather-first use. Basic protective housing still precedes wear; weather
sealing/larger-dog fit are later validation. No onboard charger is required. The proposed ≥1h minimum/2h target is an explicit engineering
interpretation of the request, not test evidence. Exact board/pack SKUs remain
unverified. The 128GB, 72h storage, China costing and sub-CNY150 priorities remain;
S3 is a recorded fallback. P4, larger cards, LTE or mandatory IMU are not silently
reinstated.

## Primary hardware and platform references

| ID | Source | What it supports; limits |
| --- | --- | --- |
| H1 | [AI-Thinker ESP32-CAM Product Specification V1.0, archived copy](https://lemariva.com/storage/app/media/uploaded-files/ESP32-CAM%20Product%20Specification.pdf) | Manufacturer-authored legacy document: 32Mbit flash, 4M PSRAM, 5V, old limited TF qualification and signal map. Not verification of a current board/clone, price or 128GB. |
| H2 | [ESP32_CAM V1.6 schematic, Olimex-hosted archival copy](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32_CAM_V1.6.pdf) | Design dated 2018-01-30: original ESP-32S module, AMS1117 path, camera rails, PSRAM/SD/LED nets and reset. No pack charger shown; compare actual PCB. |
| H3 | [PlatformIO AI Thinker ESP32-CAM](https://docs.platformio.org/en/latest/boards/espressif32/esp32cam.html) | `esp32cam` original ESP32/4MB definition and ESP-IDF support. Not a detected-memory or sustained-workload report. |
| H4 | [Espressif esp32-camera](https://github.com/espressif/esp32-camera) | ESP32/OV2640, JPEG/PSRAM/frame-buffer constraints; PSRAM DMA option is S2/S3-specific. Pin a tested component; unrelated WROVER example pins are not board wiring. |
| H5 | [Espressif CameraWebServer camera_pins.h](https://raw.githubusercontent.com/espressif/arduino-esp32/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h) | `CAMERA_MODEL_AI_THINKER` mapping and LED options. Pin reference only; firmware remains ESP-IDF. |
| H6 | [ESP-IDF original ESP32 SDMMC host](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/sdmmc_host.html) | Fixed slot pin mapping, explicit 1-bit width and clock. Do not apply S3 GPIO-matrix assumptions. |
| H7 | [ESP-IDF original ESP32 SD pull-ups](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/sd_pullup_requirements.html) | Pull requirements including inactive data lines and strap conflicts. Citing the guide authorizes no eFuse operation. |
| H8 | [ESP-IDF original ESP32 FatFs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/storage/fatfs.html) | Mount/sync and optional exFAT; stable resolved to v6.1. exFAT is not enabled by default and has no standard menuconfig path. Recheck pinned version. |
| H9 | [ESP-IDF original ESP32 OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html) | Two app slots plus OTA data/rollback; signed updates without hardware Secure Boot. Actual flash fit remains a gate. |
| H10 | [ESP-IDF original ESP32 HTTPS server](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_https_server.html) | HTTPS and documented socket/handshake costs; actual camera/SD/TLS concurrency needs measurement. |
| H11 | [ESP-IDF original ESP32 Secure Boot v2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/secure-boot-v2.html) | v2 requires original ESP32 revision ≥3.0; identify chip before signing/provisioning policy. |
| H12 | [PlatformIO esp32cam manifest](https://raw.githubusercontent.com/platformio/platform-espressif32/develop/boards/esp32cam.json) | 4MB declared flash and Arduino `huge_app.csv` setting; moving branch, not a locked build. |
| H13 | [Espressif Arduino huge_app partition table](https://raw.githubusercontent.com/espressif/arduino-esp32/master/tools/partitions/huge_app.csv) | One 3MiB app slot; not the required dual-slot ESP-IDF layout. |
| H14 | [Espressif ESP32 boot selection](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html) | GPIO0/GPIO2 download constraints and other straps. Classic ESP32 does not supply native S3 USB recovery. |
| H15 | [SD Association capacity/filesystem standards](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/) | 128GB is SDXC, standardized with exFAT; project-prepared FAT32 differs from that default. |

### Legacy-document and variant limits

Old `docs.ai-thinker.com/esp32-cam` and `_media/esp32/docs/esp32_cam_sch.pdf`
URLs returned the current documentation homepage on 2026-11-09 rather than the
historical documents. H1/H2 are identified archival copies of primary design
documents, not newly issued specifications. Their memory/card claims do not
verify an unspecified current SKU. Board-family documentation/listings describe
other PSRAM configurations; actual markings and detected usable memory settle
the selected unit's configuration.

The former [S3 WROOM-1 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)
matters only if that fallback is selected explicitly. Its memory/pin rules are
not wiring instructions for the current classic board.

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

The retention formulas and 1000mAh runtime scenarios are calculations from
explicit nominal capacities, reserves and hypothetical efficiencies. They are
not measurement results. Real usable capacity, allocated
filesystem bytes, scene-dependent JPEG sizes, protected footage, and card wear
must be measured. No hardware, firmware, app, backend, image-quality, thermal,
runtime, stabilization, or animal-wear claim has been verified by this source
review.
