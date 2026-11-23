# Hardware specification

Status: proposed engineering baseline, updated 2026-11-16. The user selects
**Seeed Studio XIAO ESP32S3 Sense with a 32GB-first microSD**. This replaces the
classic AI-Thinker ESP32-CAM/OV2640 and 128GB-first choices. Keep the confirmed
nominal 1S 3.7V 1000mAh removable pack, approximately 1–2h runtime, radio-off
recording with Wi-Fi on demand, external disconnected-pack charging, and
required-kit cost goal below CNY150 excluding card and harness. Hardware,
performance, runtime and cost remain unverified; source inspection is not a build.

The first wearable fits the owner's dog reported **under 8kg**, chest-mounted
on its harness, in dry weather. Exact dog weight/chest/harness measurements
precede CAD fit. This is not a universal 0–8kg suitability claim. A basic
protective housing and pack restraint precede any wear; larger-dog fit and a
weather-protective version need separate qualification.

## Prototype preparation update (2026-11-23)

The owner selects **OV5640** on the XIAO ESP32-S3 Sense and **daytime ground
objects at 0.5–1 m** as the first readability goal. The stock Sense fixed-focus
module is the reference; exact purchased module/PCB revisions remain unverified.
A 32GB SDHC/FAT32 card may be chosen by brand later; each actual model still
requires qualification. The owner selects LiPo chemistry but has not selected
or purchased an exact battery or charger. Retain the protected nominal 1S 3.7V
1000mAh removable-pack baseline and require a matched external charger; an
arbitrary charger is not approved by this choice.

[Prototype A preparation](../../hardware/prototype-a/README.md) contains the
candidate pin map, power/service diagram and electrical closure record.
The [recording acceptance draft](recording-acceptance.md) proposes measurable
scene/scoring limits for owner and qualified physical review; those numeric
limits are not yet accepted. The [bench plan](../../hardware/prototype-a/bench-plan.md)
records host/card identification and future operation boundaries. macOS,
Windows and Linux are acceptable host choices; actual host versions and executed
results remain to be recorded. Card reader, USB-C data cable and soldering tools
are reported available; measurement equipment is not confirmed.

These are preparation artifacts for 0.3/0.5/0.7, not electrical signoff, a frozen
rubric or card/device qualification. They do not modify package 0.6 contracts.

## 1. Product boundary and evidence

Power-on recording is automatic when a qualified FAT32 card is available.
Recording-only with Wi-Fi/BLE off is default. A deliberate physical local-access
action opens a timed Wi-Fi session; ordinary preview/download access must yield
to continuous recording. On idle/expiry the radio returns off. Recording must
not wait for a router, phone or backend. OTA is an explicitly announced pause.
There is no LTE, audio recording or required IMU.

The proposed interpretation of “about 1–2h” remains **≥1h useful recording per
charge as minimum acceptance, with 2h the engineering target**, using the same
qualified profile. Measure record-only and a defined timed-Wi-Fi workload,
ambient and shutdown reserve separately. These are proposed acceptance values,
not measured endurance.

The supported retained duration on 32GB will be **measured and published**.
72 recorded hours remains an **unverified engineering target**, not a supported
retention promise. A working 32GB loop alone cannot pass that target.
Do not reduce useful image quality/FPS invisibly to obtain that number. Retention
is footage across powered sessions, not 72h battery life or coverage while off.

| ID | Requirement | Required evidence |
| --- | --- | --- |
| HWR-01 | XIAO ESP32S3 Sense, shipped supported camera, 32GB-first card | Actual base/expansion/camera revisions, chip and detected memory, card usable capacity |
| HWR-02 | Required hardware kit below CNY150 excluding SD and harness | Dated CN full-kit quote including pack, external charger, housing, assembly/test and contingency |
| HWR-03 | Useful sustained JPEG recording at a qualified profile | Motion readability, actual FPS/gaps, sizes, resource and write-growth measurements |
| HWR-04 | 32GB FAT32 SDSPI recording with measured retention | Mount/full-capacity/latency/rollover/interruption evidence; 72h separately marked stretch |
| HWR-05 | Protected removable 1S pack, reviewed BAT service path and external charger | Polarity, isolation from USB charging, cutoff/current/thermal and external-charge evidence |
| HWR-06 | Chest mount for owner's dog reported under 8kg; basic dry-weather housing | Actual dog/chest/harness and assembly measurements, supervised fit/movement |
| HWR-07 | Intentional physical local access and truthful recording/fault indication | GPIO/LED/SD/boot conflict review and recording-under-access tests |
| HWR-08 | Mechanical damping; optional sensors do not block recording | Mount observations; no required IMU; onboard microphone disabled |
| HWR-09 | Recover from interruption without automatic formatting | Controlled cuts/unplug/recovery corpus, including earlier filesystem corruption |
| HWR-10 | Reproducible applicable assembly/design package | Exact purchased-board references, carrier/wiring, housing, firmware compatibility and service guide |
| HWR-11 | Nominal 3.7V 1000mAh, proposed ≥1h minimum/2h target | Useful recording runtime to approved shutdown on identified pack/load/ambient |

## 2. Board, camera and PlatformIO identity

### 2.1 Acquire the complete Sense assembly

Acquire the **Sense**, including its matching camera/microSD/microphone expansion
board and antenna, rather than assuming the bare XIAO ESP32S3 includes those
peripherals. The vendor product sheet lists 8MB flash and 8MB PSRAM; inventory
and boot-detect both. The Plus is a different variant, and the earlier N16R8
or classic 4MB-flash defaults do not apply.
([H1: Seeed product sheet](https://files.seeedstudio.com/Bazaar/product_pdf/113991115.pdf))

Camera identity is a procurement and software gate. Seeed's current wiki says
early OV2640 units were followed by OV3660 and now a transition to fixed-focus
OV5640, with either OV3660/OV5640 potentially shipped. The vendor PDF still
names OV3660. Do not promise one sensor based on the board family or reuse
OV2640-only assumptions. Record sensor ID, module/flex revision, lens/focus,
orientation and compatible driver before selecting a recording profile.
([H2: current Seeed introduction](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/))

Photograph both boards and labels; capture SKU/seller/lot, base and expansion
PCB revisions, sensor/flex/antenna identity, schematic revision, chip revision,
detected flash and usable PSRAM, and connector orientation. Changes in sensor
or assembly revision repeat camera, power, fit and capacity tests as affected.
An existing factory webcam image is not vdog firmware or evidence of its claims.

### 2.2 PlatformIO support is documented, not yet built here

The official PlatformIO board ID is **`seeed_xiao_esp32s3`**. PlatformIO lists
both Arduino and ESP-IDF frameworks. The manifest identifies ESP32-S3, 8MB flash
and PSRAM-related settings. This is compatibility evidence for the base target,
not automatic initialization of the Sense camera/SD, a project build, or
hardware verification.
([H3: PlatformIO board](https://docs.platformio.org/en/latest/boards/espressif32/seeed_xiao_esp32s3.html),
[H4: board manifest](https://raw.githubusercontent.com/platformio/platform-espressif32/develop/boards/seeed_xiao_esp32s3.json))

Preserve **PlatformIO + ESP-IDF C++**. Planned environments are
`vdog_xiao_sense_proto` and `native`; package 0.2 pins platform/framework/compiler,
board manifest, camera component, configuration and working build commands.
The manifest's `qio_opi` and default partition entry are under its Arduino
section; do not assume they configure an ESP-IDF project. Explicitly verify
8MB flash, Octal PSRAM setup, camera component and SDSPI configuration in the
pinned ESP-IDF environment. No install or build was run for this source review.

Use the native USB-C programming/recovery path with reviewed ESP-IDF USB
configuration and board-specific BOOT/reset procedure. Preserve it during pin
assignment. There is no need to carry the classic board's external UART
programmer as a required wearable component. USB service power requires pack
disconnection as specified in section 5, because the XIAO has an onboard charger.

### 2.3 Memory, HTTPS and signed OTA

Espressif's camera driver supports S3 and the candidate camera sensors and
explains JPEG/PSRAM/frame-buffer pressure. Use sensor JPEG, enabled/verified
PSRAM and bounded capture queues. S3 PSRAM DMA is an optional configuration to
qualify, not proof that capture/SD/TLS can run together without drops.
([H5: esp32-camera](https://github.com/espressif/esp32-camera))

Derive the ESP-IDF partition table from actual firmware size within detected
8MB flash: two qualified signed app slots, OTA data, NVS/identity/configuration,
recovery/diagnostic needs and headroom. Do not copy the superseded 16MB layout.
The Arduino `default_8MB.csv` demonstrates two app slots but is not a tested
vdog partition table or ESP-IDF configuration. Preserve signed-update checks
and SDK rollback; a build-size failure needs a decision, not silent removal.
([H6: SDK OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html),
[H7: upstream 8MB Arduino table](https://raw.githubusercontent.com/espressif/arduino-esp32/master/tools/partitions/default_8MB.csv))

HTTPS allocations/handshakes compete with capture and SD service. Qualify a
small bounded connection count against measured internal heap, PSRAM, latency,
FPS and power. TLS/signatures do not encrypt removable card originals. Actual
provisioning and any irreversible security state require separate identified
hardware authorization.
([H8: S3 HTTPS server](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/protocols/esp_https_server.html))

## 3. Sense peripherals, pins and controls

### 3.1 Revision-specific reference map

The following is a **reference for reconciliation, not approved new wiring**.
It follows Seeed's current pin-multiplexing guide and Espressif's XIAO camera
map. Compare the acquired base board, expansion board, connector and matching
schematics before use. Resolve any revision/document conflict; do not guess a
chip-select pin or substitute the classic SDMMC wiring.
([H9: Seeed multiplexing](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/),
[H10: Espressif XIAO camera map](https://raw.githubusercontent.com/espressif/arduino-esp32/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h))

| Function | Documented reference GPIO | Ownership/constraint |
| --- | --- | --- |
| Camera D0–D7 (Y2–Y9) | 15, 17, 18, 16, 14, 12, 11, 48 | Camera data; match acquired module and bit order |
| Camera XCLK / PCLK | 10 / 13 | Camera clocks; not classic GPIO0 XCLK |
| Camera VSYNC / HREF | 38 / 47 | Camera synchronization |
| Camera SCCB SDA / SCL | 40 / 39 | Camera control bus |
| Camera PWDN / RESET | No GPIO in upstream XIAO map (`-1`) | Verify actual expansion power/reset arrangement |
| SD SPI SCK / MISO / MOSI | 7 / 8 / 9 (D8/D9/D10) | Storage bus, not free expansion GPIO |
| SD SPI CS | 21 in current wiki/examples | Reconcile expansion revision; sole storage ownership |
| User LED | 21 in current wiki | Treat as sharing CS; do not blink/PWM independently while mounted |
| Onboard microphone DATA / CLK | 41 / 42 | Leave uninitialized; no audio capture/storage/networking |
| BOOT / reset | GPIO0 / CHIP_PU | Boot strap/reset behavior; app gesture requires review |
| USB D− / D+ | 19 / 20 | Preserve native USB service/recovery |
| UART TX / RX | 43 / 44 (D6/D7) | Optional diagnostic route, not camera/SD pins |
| Battery ADC / extra button / IMU | No approved assignment | Review actual board functions, pulls and power before adding |

Current Seeed guides/examples specify CS21 and also identify the user LED on
21. A status task must not take that GPIO from storage; even an LED demo can
select/deselect the card. Confirm actual LED/CS circuitry and document an
independent truthful indication strategy if needed. Any conflicting older
schematic labels require matching-revision/net-continuity investigation rather
than an automatic change to GPIO3 or arbitrary pin probing.

The camera, SD and microphone share the expansion assembly but not one software
owner. Microphone drivers must remain disabled, even if an example initializes
them. No microphone clock, samples, audio files or audio upload is part of v1.
No speaker/flash illumination is required. BLE likewise stays off by default.

### 3.2 SD is SPI, not the earlier 1-bit SDMMC design

Use the ESP-IDF **SDSPI** host with reviewed SCK/MISO/MOSI/CS and FatFs SD-SPI
mounting. Initialize the SPI bus and card explicitly; do not substitute
`esp_vfs_fat_sdmmc_mount()` or the classic 14/15/2 pin set. Select and qualify
clock, DMA buffers, maximum transaction size, file handles and concurrency
against card write-stall measurements. Additional SPI devices need their own
bus-sharing review and may not compromise recorder priority.
([H11: ESP-IDF S3 SDSPI](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sdspi_host.html))

### 3.3 Board and physical controls gate

Produce `hardware/prototype-a/pin-map.csv`: base/expansion revisions, module
pad/header/connector, GPIO/net, direction, voltage, reset state and pulls.
Audit camera/SD/LED/mic/USB/memory/straps, compare actual PCB to schematic, then
perform continuity/short and current-limited first-power checks. Do not reuse
DevKitC-1/N16R8/AI-Thinker maps or assign internal memory pins from bare-chip
pin counts. Select GPIO resources only after this audit.

The local-access, pairing and ownership-reset workflow requires a deliberate
physical action. Review whether a long BOOT press after startup can be safely
distinguished from download mode, or define a separate control. Reset itself
restarts recording and is not an independently readable application button.
Do not promise uninterrupted recording for a reset-based local-access gesture;
meet the firmware access requirement or record a design decision. Extra ADC,
button or IMU connections remain unassigned.

Battery telemetry is not assumed to exist merely because BAT pads exist. If
no qualified measurement path is available, report unknown battery data and
qualify cutoff/runtime externally. Define non-color-only record/error/radio
indications that remain truthful without fighting SD CS. The charge LED is not
a recording-success indicator.

## 4. 32GB-first storage and measured retention

### 4.1 Supported card baseline

Use a genuine **32GB SDHC card formatted FAT32** as the first qualification
medium. Seeed explicitly documents support up to 32GB and FAT32 preparation;
that manufacturer statement is not vdog's completed soak test. Record model,
acquisition source, identity, usable/allocated capacity, filesystem/allocation
unit, mount settings and firmware revision. Qualify at least two actual models
before broad compatibility claims. Prefer sustained-recording endurance suited
to the workload; branding/speed class does not establish latency or lifetime.
([H12: Seeed microSD guide](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/),
[H13: SD capacity/filesystem standards](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/))

Larger cards are **future compatibility work** with separate driver/filesystem,
full-capacity, latency and recovery tests; 128GB is no longer the first target.
FAT32 32GB avoids requiring SDXC exFAT support. Reject unsupported/corrupt
filesystems without automatic formatting. Preparation is an explicit owner
backup/identified-device operation, never a generic destructive host-disk command.
Use 64-bit cumulative/capacity counters and short segments under FAT32 file limits.
([H14: S3 FatFs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/fatfs.html))

### 4.2 Capacity arithmetic and the unverified 72h gate

Use decimal GB only for advertising/calculation; implementation accounts actual
allocated bytes and complete-bundle headroom. For nominal 32GB and a 15% reserve:

```text
nominal_card_bytes = 32000000000
planning_pool_bytes = 32000000000 × 0.85 = 27200000000
72h_seconds = 259200
72h_ceiling_all_recording_bps = 27200000000 × 8 / 259200 ≈ 839506.17
with_2GB_protected: rolling_pool = 25200000000
72h_ceiling_with_protection_bps ≈ 777777.78
proposed_total_rolling_growth_target = 750000 bit/s (0.75Mbit/s)
72h_at_target = 24300000000 allocated bytes before separately budgeted headroom
```

The 2GB protected-event cap is **inside** the pool, replacing the former 8GB
assumption; reduce it further if measured capacity/headroom demands. Count
payloads, indexes, manifests, catalog, active state and filesystem allocation.
The ceilings above precede additional complete-bundle headroom. At 15fps, the
no-protection ceiling allows only about 6,996 bytes/frame including overhead;
the 0.75Mbit/s proposal allows 6,250 bytes/frame. These are not proven useful
JPEG profiles, particularly for motion/texture. Do not present the arithmetic
as a supported retention claim.

Select useful quality/FPS first against the agreed scene rubric. Publish
measured expected retention and actual rollover coverage. If 72h cannot fit,
record the unmet 72h gate and offer explicit quality/retention/card
tradeoffs; do not silently lower quality, remove overhead or call sparse
frames continuous footage. Larger-card promotion requires a separate decision.

### 4.3 Qualification and interruption

Measure mixed scenes, high texture, low light and controlled walking/running
motion or approved bench equivalent: useful detail, JPEG mean/p95/p99, actual
FPS/gaps, SDSPI latency/longest stall, queue/heap/PSRAM, allocated bytes/hour and
oldest/newest recoverable coverage. Repeat under timed Wi-Fi/TLS/download load;
local access must not hide capture degradation.

Use a qualified external bench supply **with pack disconnected** for retention
soaks and forced rollover. Run long enough to demonstrate the claimed measured
window; a 72h test is required only to claim the stretch target. Repeat protected
budget tests if those features are advertised. Multiple battery sessions must
also demonstrate restart ordering and explicit off/recharge gaps.

Follow media/firmware power-cut, unplug, removal and corrupt-card procedures.
FAT32/card-controller behavior can damage earlier data despite fsync/rename;
report that honestly rather than promising a one-second loss bound. Preserve
suspect material and never format automatically to hide a failure.

## 5. Removable 3.7V 1000mAh pack and external charging

### 5.1 Use the reviewed BAT path, not an automatic 5V boost

Seeed documents battery operation on BAT pads and USB battery charging. The
linked Sense base schematic shows the onboard charger and regulation. This
board therefore differs from classic ESP32-CAM: **a new external 5V boost is
not automatically required**. Match the acquired revision, BAT polarity/range,
regulator behavior and Sense camera rail before approving its power circuit.
([H15: Sense base schematic V1.51](https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/new-res/202003753_XIAO%20ESP32S3%20Sense_V1.51_SCH_260611.pdf))

Keep the confirmed **protected nominal 1S 3.7V 1000mAh rechargeable pack** with
keyed service connector and reviewed switch/shutdown. Verify exact chemistry,
full-charge/cutoff limits, protection, continuous/peak discharge, connector
polarity, dimensions/mass and temperature requirements from supplier data.
Nominal capacity does not specify safe peak current.

```text
Recording:
protected 1S 3.7V 1000mAh pack -> keyed removable connector
    -> reviewed switch/shutdown -> approved XIAO BAT+/BAT− input
    -> verified onboard regulation -> Sense base/camera/SD

Charging, camera unmounted and pack disconnected/removed:
approved supply -> compatible external 1S charger -> protected pack

USB-C programming/bench power: pack physically disconnected.
```

The board's charger **exists**, but vdog's selected owner workflow does not use
it. No camera in-place charging or concurrent recording/charging is required.
Disconnect the pack before connecting any USB-C source for programming, logs,
power or the long retention soak. A battery switch on the wrong branch may
leave the cell connected to the onboard charger, so the approved service
connector must actually disconnect the pack from BAT. Firmware cannot be
assumed to disable charging or reverse current. A future isolated dual-source
service circuit requires a new reviewed schematic; none is implied here.

Procedure: remove the whole camera from the harness, perform approved shutdown/
power-off, unplug and remove the pack, then charge it outside the camera. Check
external charger/pack compatibility and conditions. Disconnect the charger
before reinstalling/reconnecting. Prevent wire strain, reversed connection and
contact shorting. Power-off first reduces avoidable interruption but abrupt
unplug/protection cutoff remains a mandatory recovery case.

Do not connect the pack to 3V3_OUT, USB VBUS or arbitrary GPIO. BAT compatibility
is a board-specific exception to the earlier classic-board power design, not
a rule for other boards. Document cutoff and low-voltage behavior of the actual
assembly. If measured BAT discharge compromises camera/SD rails, report a power
design issue rather than adding an unreviewed converter or changing the pack.

### 5.2 Energy and runtime evidence

Nominal energy is 3.7V × 1.0Ah = 3.7Wh. As a **hypothetical** example, 80% usable
energy after assumed cutoff/aging reserve leaves 2.96Wh; that fraction is not
measured. When average power is measured at the battery, use
`runtime_hours = usable_battery_Wh / average_battery_power_W`; do not subtract
onboard converter losses a second time. If power is measured downstream,
explicitly include measured conversion efficiency. No generic 5V-boost factor
from the superseded classic-board design is a verified XIAO value.

For illustration only, 2.96Wh permits about 2.96h at 1W, 1.97h at 1.5W or
1.48h at 2W battery-side average load. These are not XIAO measurements or runtime
guarantees. Vendor demo/sleep figures do not characterize continuous vdog
recording, its current camera/card, enclosure or timed Wi-Fi sessions.

Size protection/connectors/switches against simultaneous boot, camera/SD bursts
and radio/TLS peaks; measure rail droop/overshoot, current and temperature.
Charge externally by the approved procedure, install, record to controlled
shutdown and verify files/useful duration. Repeat radio-off and defined timed
access workloads. Report pack/charger/model, charge duration, measured energy
if tested, reserve, ambient, assembly mass and achieved runtime. Proposed ≥1h
minimum and 2h target remain gates; missed runtime cannot justify a hidden
FPS/quality reduction.

### 5.3 Power/thermal bench gate

Camera tests include boot, radio-off capture, timed Wi-Fi/TLS/download, SDSPI
bursts, low-voltage shutdown/restart, orderly pack removal and controlled abrupt
unplug. USB/native recovery tests use **pack disconnected**, checking the actual
connector/isolation procedure. Test external charger/pack temperatures and
completion separately. There is no simultaneous charging/recording test need.
Battery voltage/percentage is unknown without a reviewed measurement path.

Before wear, qualified review approves pack/circuit/basic housing/chest mount,
ambient, temperature method and contact/mass limits for the actual dog. Exact
weight/chest/harness and complete-assembly dimensions remain measurements;
these docs invent no universal numeric limits. Component ratings are not contact
limits. Never charge while worn or with the pack inside the camera. Stop for
warmth, damage, rubbing, wet contacts, loose mount or discomfort.

## 6. Mechanical design and production approach

Use the complete ready-made Sense assembly first. A reviewed small carrier or
connector assembly may provide pack disconnect, switch, physical controls and
indication without altering core board design. A custom camera PCB is optional
only after image/power/storage/cost evidence justifies it. Inventory how the
Sense expansion board is mechanically retained under movement; its connection
alone is not a qualified harness mount.

**Basic non-weather-rated protective housing and restrained pack are required
before wear.** Recess contacts, prevent screw/edge damage and strain, retain SD,
keep hot/rigid parts off the wearer, preserve antenna clearance and allow safe
pack removal. Do not postpone this basic protection until a weather version.
Vendor board dimensions are not complete wearable dimensions including lens,
antenna, pack, connector, bracket and housing; measure the complete assembly.

The first fit is the owner's under-8kg dog on its chest harness. Obtain exact
weight/chest/harness measurements before CAD fit, then assess mass, clearance,
tilting, useful ground view, fur/strap occlusion, movement/rubbing, retention
and snag behavior. Basic mounting/damping count in the BOM, harness purchase
does not. No universal size, IP, rain, drop or breakaway rating is established.
Dry weather only initially; future weather housing repeats ingress/thermal/RF/
mount checks, and larger-dog compatibility needs separate fit evidence.

The onboard microphone remains disabled. Optional IMU/ADC/button expansion
needs pin/power/timing/cost review, cannot take camera/SD/USB resources, and
must not block recording if absent. A gyro does not itself stabilize video;
timing, lens calibration and processing support would still be needed.

## 7. Cost evidence and release artifacts

### 7.1 Sub-CNY150 kit is still an unproven constraint

The complete Sense assembly may make the required kit cost difficult. Obtain
an actual mainland-China quote for the correct board/camera/antenna revision;
do not reuse the classic-board allocation or convert an international display
price into a claimed CN quote. No current CNY purchase price is asserted here.

The following **reverse-budget design ceilings**, at a stated planning quantity
of 1,000 kits, sum to CNY149. They specify what would have to be achieved, not
what suppliers offer. The CNY80 Sense line is particularly a procurement gate.
If the quote exceeds its allocation, report the full-kit variance; do not claim
the goal passed by excluding the pack, charger, housing or test allowance.

| Allocation | CNY/unit ceiling | Included scope |
| --- | ---: | --- |
| Complete XIAO ESP32S3 Sense with camera/expansion/antenna | 80 | Flash/PSRAM/socket/mic/onboard regulation and charger already included |
| Protected 1S 3.7V 1000mAh pack | 20 | Identify included protection/temperature features |
| Compatible external charger and service parts | 18 | Charger, keyed pack service and required additions not counted elsewhere |
| Carrier/wiring/switch/control/indication additions | 6 | Reviewed necessary interfaces; no automatic separate 5V boost |
| Basic housing, chest bracket, damping and fasteners | 10 | Dry-weather protective device hardware, not harness purchase |
| Assembly/test/yield allowance | 5 | Complete assembly test and losses, no duplicate fitted-board labor |
| Unallocated contingency | 10 | Quote gaps, alternatives and revision allowance |
| **Total required-kit allocation** | **149** | **Excludes SD and harness only from this comparison** |

Prototype/retail orders are quoted separately. Track quantity, tax/freight,
engineering, tooling, certification, packaging, warranty and margin explicitly.
An owner-supplied/shared external charger requires a clear accessory and total
cost basis; it is not silently free. Count purchased Sense components once.
Removing a former boost requirement is not proof of any net cost saving.

### 7.2 Evidence and release package

For fitted items record SKU/MPN/revision, quantity, manufacturer, alternatives,
supplier/date, price break/minimum order, currency, tax/freight/availability and
quote identifier. Preserve personal-data/provisioning secrecy. Release board/
expansion/camera identities and source links, reviewed pin map/service wiring,
carrier sources/DRC/fabrication data if present, housing CAD/print files,
external charger compatibility/removal guide, assembly/polarity, programming/
recovery, supported card/profile/retention/runtime, fit evidence and limitations.

Seeed provides design resources and an OSHW repository. Record the exact files,
versions and applicable license/attribution instead of assuming every resource
shares one license. The project publishes its own carrier/housing work where
available; purchasing the Sense is not evidence that vdog authored its design.
([H16: Seeed OSHW repository](https://github.com/Seeed-Studio/OSHW-XIAO-Series),
[H17: expansion schematic](https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/XIAO_ESP32S3_Exp_Board_v1.2_SCH_PDF_260810.pdf))

## 8. Hardware gates

| Gate | Required output | Blocks |
| --- | --- | --- |
| HW-G0: identity/build | Actual Sense base/expansion/camera/card/pack; pinned PlatformIO ESP-IDF; flash/PSRAM/USB/dual-slot checks | Supported-board/build/resource claims |
| HW-G1: electrical | Revision-matched pins, CS/LED ownership, microphone off, BAT/USB service isolation, measured rails and camera/SDSPI | Sustained hardware capture and approved service wiring |
| HW-G2: image/storage | Useful scene profile, actual 32GB allocated growth/retention/rollover; explicit 72h stretch result; scaled protected budget | Any advertised retention duration or larger-card claim |
| HW-G3: battery/housing | Protected pack/BAT/switch/disconnect/external charger; ≥1h proposed minimum/2h target, thermal/unplug/recovery/basic housing and measured chest fit | Supervised dry-weather wear |
| HW-G4: wearable | Actual under-8kg owner's dog fit/view/movement/comfort evidence | Distribution within tested scope; no broad size/weather claim |
| HW-G5: production cost | Dated complete-kit quote, design resources and pilot test/yield; below CNY150 passes cost, otherwise report the failed target | Claimed cost compliance or production readiness |

Documented PlatformIO support is DOC evidence. Compile/host tests, actual unit
verification and approved field trials are separate. No build, model inference,
flash, USB connection, battery operation, purchase, or wear test occurred in
this documentation update. Missing evidence remains UNVERIFIED.
