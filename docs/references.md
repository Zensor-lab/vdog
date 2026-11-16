# Research sources and evidence boundaries

Hardware/platform sources rechecked on **2026-11-16**; the app/backend sources
below were reviewed on 2026-11-07 unless separately noted. A documentation check
is not a firmware build, model inference, live delegation or hardware test.
Pin exact platform/framework/component/board revisions during Stage 0; moving
`stable`, `latest`, `main`, `develop` and `master` pages are discovery inputs.

## Conversation provenance and current direction

[Research Dog Camera Plan](chatgpt-conversation://6aef12d8-967c-83ed-be5e-870d042384f1)
was read through the connected tool on 2026-11-07. It exposed five recent
user/assistant exchanges, no attachments and no older cursor. Earlier original
requirements alluded to there were unavailable; these docs do not invent them.

The accessible history requested CN procurement, hardware below 150 excluding
SD/harness and initially S3/128GB. Assistant proposals supplied 72h loop storage,
Flutter/Rust, optional IMU and off-device EIS; they were not measurement results.
On 2026-11-09 the user chose classic AI-Thinker ESP32-CAM/OV2640, nominal 3.7V
1000mAh/about 1–2h, recording mainly with Wi-Fi when needed, unmounting/unplugging
for external pack charging, chest mounting on their dog reported below 8kg and
dry-weather-first use. Those physical/power/use constraints continue to apply.

On **2026-11-16**, the user selects **Seeed Studio XIAO ESP32S3 Sense and 32GB
first** and asks for PlatformIO verification. This supersedes classic-board
memory/pins/power assumptions and 128GB-first qualification. The initial useful
retention duration is measured; **72h is a stretch feasibility gate**, not a
32GB product promise. The ≥1h minimum/2h runtime target remains an explicit
engineering interpretation, not a tested claim. Exact dog/chest/harness data
precedes fit; below 8kg is not a universal 0–8kg compatibility rating. Weather
sealing/larger-dog fit are later work; basic protective housing precedes wear.

The XIAO has an onboard charger, but the owner-selected workflow continues to
charge the disconnected pack outside the camera. Disconnect BAT before USB-C
service rather than pretending the onboard charging circuit does not exist.
Card capacity, board family, sensor shipment and price claims are kept separate
from project qualification.

## Primary hardware/platform sources for the active XIAO baseline

| ID | Primary source | Supported facts and limitations |
| --- | --- | --- |
| H1 | [Seeed Sense SKU 113991115 product sheet](https://files.seeedstudio.com/Bazaar/product_pdf/113991115.pdf) | 8MB flash/8MB PSRAM, Sense peripherals and 32GB FAT. PDF updated 2026-11-11 still names OV3660; current wiki records a later/overlapping camera transition. Its international display price is not a CN quote. |
| H2 | [Seeed XIAO ESP32S3 getting started](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) |Current sensor transition: OV2640 historical, OV3660 then fixed-focusOV5640; shipments may vary. Battery/USB capability and Sense/base/Plus distinction. Demo/power figures do not establish vdog runtime. |
| H3 | [PlatformIO Seeed XIAO ESP32S3](https://docs.platformio.org/en/latest/boards/espressif32/seeed_xiao_esp32s3.html) | Board ID `seeed_xiao_esp32s3`,8MB flash, ESP-IDF and Arduino framework listings. Base-target compatibility evidence, not Sense peripheral initialization or a build result. |
| H4 | [PlatformIO board manifest](https://raw.githubusercontent.com/platformio/platform-espressif32/develop/boards/seeed_xiao_esp32s3.json) | ESP32-S3 target, 8MB declaration; `qio_opi`/partition defaults underArduino. Explicit ESP-IDF configuration and detected PSRAM remain gates. |
| H5 | [Espressif esp32-camera](https://github.com/espressif/esp32-camera) | S3/sensor support, JPEG/PSRAM/buffering and optional S2/S3 PSRAM DMA. Does not prove simultaneous camera/SD/TLS quality. |
| H6 | [ESP-IDF S3 OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html) | Two app slots/OTA data, validation and rollback. Exact signed image/partition fit must be built and tested. |
| H7 | [Espressif default8MB Arduino table](https://raw.githubusercontent.com/espressif/arduino-esp32/master/tools/partitions/default_8MB.csv) | Two app slots in the upstream example; not a tested vdog ESP-IDF table. |
| H8 | [ESP-IDF S3 HTTPS server](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/protocols/esp_https_server.html) | TLS server support and socket/handshake resource considerations; workload remains unmeasured. |
| H9 | [Seeed Sense pin multiplexing](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/) | Camera/mic/SPI table: SD 7/8/9/CS21 in current guide. Reconcile actual PCB/expansion schematic before wiring; no automatic free pins. |
| H10 | [Espressif camera_pins.h](https://raw.githubusercontent.com/espressif/arduino-esp32/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h) | `CAMERA_MODEL_XIAO_ESP32S3` map, distinct from classic AI-Thinker. Pin reference only; selected firmware remains ESP-IDF. |
| H11 | [ESP-IDF S3 SDSPI driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sdspi_host.html) | SPI-bus/card/CS setup; onboard Sense slot is not the earlier classic 1-bit SDMMC layout. |
| H12 | [Seeed Sense microSD guide](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/) | Vendor documents up to 32GB and FAT32 preparation. Does not establish vdog soak/retention or larger-card support. |
| H13 | [SD Association capacity/formats](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/) | 32GB SDHC/FAT32 versus larger SDXC/exFAT. Capacity arithmetic remains separate from video feasibility. |
| H14 | [ESP-IDF S3 FatFs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/fatfs.html) | Mount/sync/allocation configuration; stable resolved to v6.1.1. Project rejects mount failures without autoformat. |
| H15 | [Seeed Sense base schematic V1.51, 2026-06-11](https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/new-res/202003753_XIAO%20ESP32S3%20Sense_V1.51_SCH_260611.pdf) | ESP32-S3R8, 8MB flash, BAT/VBUS regulation/charger and USB design. Match acquired revision; pack disconnection before USB preserves selected external-charge workflow. |
| H16 | [Seeed OSHW-XIAO-Series repository](https://github.com/Seeed-Studio/OSHW-XIAO-Series) | Official resource/project hub. Some archived documents still describeOV2640; choose current matched design files and record per-artifact licenses. |
| H17 | [Seeed expansion schematic v1.2, 2026-08-10](https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/XIAO_ESP32S3_Exp_Board_v1.2_SCH_PDF_260810.pdf) | Revision-specific Sense expansion hardware resource; reconcile connector/net/CS/LED ownership against current guide and physical board. |
| H18 | [Seeed camera usage](https://wiki.seeedstudio.com/xiao_esp32s3_camera_usage/) | Current examples use SD.begin(21); upstream examples are source references, not production recording/security implementations. |
| H19 | [Seeed microphone usage](https://wiki.seeedstudio.com/xiao_esp32s3_sense_mic/) | Microphone belongs to Sense expansion. vdog intentionally leaves it disabled; presence is not permission to record audio. |

### Revision/source conflicts and historical material

Current Seeed pin tables identify both user LED and SD CS as GPIO21. Storage owns
that signal until acquired-board/revision review establishes a different valid
arrangement; a status task must not independently blink it. Older schematic/
connector interpretations may differ, so compare matching base/expansion files
and actual continuity before approving the pin map. No speculative CS substitution
or solder modification is authorized by the documentation.

The official OSHW repository's older getting-started text still names OV2640,
while the current wiki names OV3660/OV5640 and the current SKU PDF names OV3660.
Record the shipped sensor and driver rather than treating these pages as a
single fixed bill of materials. Bare XIAO, Sense and Plus are not interchangeable.

The [classic AI-Thinker archival specification](https://lemariva.com/storage/app/media/uploaded-files/ESP32-CAM%20Product%20Specification.pdf),
[classic V1.6 schematic](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32_CAM_V1.6.pdf)
and [S3 WROOM-1 module datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)
are historical alternatives only, not current XIAO pin/memory/power sources.
Legacy Ai-Thinker document URLs redirected to its homepage when checked on
2026-11-09; that limitation does not apply to the current official Seeed links.

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

The 32GB retention formulas and 1000mAh runtime scenarios are calculations from
explicit nominal capacities, reserves and hypothetical efficiencies. They are
not measurement results. Real usable capacity, allocated
filesystem bytes, scene-dependent JPEG sizes, protected footage, and card wear
must be measured. No hardware, firmware, app, backend, image-quality, thermal,
runtime, stabilization, or animal-wear claim has been verified by this source
review.
