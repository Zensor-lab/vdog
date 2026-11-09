# Hardware specification

Status: proposed engineering baseline, updated 2026-11-09. The user now selects
**classic AI-Thinker ESP32-CAM + OV2640**, a **nominal 3.7V 1000mAh single-cell
battery**, approximately **1–2 hours per charge**, and **recording mainly with
Wi-Fi enabled only when needed**. This replaces the earlier ESP32-S3/N16R8
priority. The 128GB card, 72-hour retained-recording goal, China procurement and
hardware BOM below CNY150 excluding SD and harness remain. No board, pack,
circuit, runtime, price or wearable assembly has been validated by these docs.

Exact genuine PCB revision and battery SKU remain selection gates. A product
sold as “ESP32-CAM” is not thereby an S3 or electrically identical to another
seller's board. Sources and legacy-document limits are in [references](../references.md).

The first wearable targets **the owner's dog, reported under 8kg, chest-mounted
on a harness in dry weather**. This is an initial fit subject, not a claimed
compatibility range for all dogs from 0–8kg. The owner removes the complete
camera from the harness, disconnects
the battery and charges that pack separately outside the camera. Recording
while charging and an onboard charger are outside this baseline. Larger-dog
fit and a later weather-protective version require separate qualification.

## 1. Product boundary and proposed acceptance

The harness-mounted device records a forward/downward view to microSD and starts
automatically when powered with a supported card. **Recording-only with the
Wi-Fi radio off is the default.** A deliberate physical local-access action
opens a time-bounded Wi-Fi session for setup, preview, download or updates;
recording continues during ordinary local access. On idle/expiry the radio
returns off. Firmware must specify the exact controls, timeout and update pause
behavior; an unreachable network must never block recording. There is no LTE,
SIM, microphone or mandatory IMU requirement.

The proposed interpretation of the user's “1–2 hours” is **at least one hour
of useful recording per charge as minimum acceptance, with two hours as the
engineering target** on the selected 1000mAh pack. Freeze recording profile,
network workload, ambient conditions and shutdown threshold before testing.
This is a proposed acceptance criterion, not measured endurance. Measure
record-only and Wi-Fi-access workloads separately.

The 72-hour requirement is footage retained **across powered sessions on the
card**. It is not 72h on one charge, continuous wear, or wall-clock coverage
while switched off. Every unpowered interval is a gap.

| ID | Requirement | Evidence before claiming support |
| --- | --- | --- |
| HWR-01 | Classic AI-Thinker ESP32-CAM + OV2640; 128GB priority | Board/sensor/card identities, chip revision and detected memory, usable card bytes |
| HWR-02 | Hardware BOM below CNY150 excluding SD and harness; external charger/accessory basis explicit | Dated CN quotes, complete kit scope, assembly/test/loss allowance, quantity and variant |
| HWR-03 | Useful sustained JPEG recording at a qualified profile | Motion readability, achieved FPS/gaps and JPEG-size distribution |
| HWR-04 | 128GB storage path withstands the qualified workload | FAT32 mount, full-capacity addressing, stalls, removal, interruption and rollover |
| HWR-05 | Protected 1S pack, keyed disconnect, reviewed switch/shutdown/5V regulation and compatible external charging | Camera power schematic, charger/pack limits, separate bench/charging tests before wear |
| HWR-06 | Chest harness mount for the owner's dog reported under 8kg, useful view and basic dry-weather protective housing | Exact dog weight/chest/harness dimensions before CAD fit; assembly measurements and approved supervised fit/movement evidence |
| HWR-07 | Physical local-access/ownership control and truthful indication | Board-specific circuit/gesture; no camera/SD/strap conflict; radio-off default verified |
| HWR-08 | Mechanical damping; optional sensors do not block recording | Mount comparison; no IMU dependency or assumed spare GPIO |
| HWR-09 | Recovery follows the firmware/media interruption contract | Controlled cuts and recovery results including earlier filesystem corruption |
| HWR-10 | Reproducible assembly/design and separate-charging package | Board/carrier/wiring, pack/charger compatibility, BOM, basic housing and service procedure |
| HWR-11 | Nominal 3.7V 1000mAh pack; proposed ≥1h minimum/2h target | Useful recording runtime to approved shutdown with pack/load/ambient identity |

## 2. Selected board class, memory and build gates

### 2.1 Classic board identity

The legacy AI-Thinker specification describes an ESP32-CAM with 32Mbit flash
(4MB), external 4M PSRAM, camera connector, SD socket and 5V input. This is a
historical V1.0 document, not proof of components on a current listing.
PlatformIO's `esp32cam` definition also identifies original ESP32 and 4MB flash.
Require actual chip/flash/PSRAM identification and a boot report; do not carry
forward the S3's 16MB flash/8MB PSRAM assumptions. Seller claims of other PSRAM
sizes need their own evidence.
([H1: manufacturer specification, archived copy](https://lemariva.com/storage/app/media/uploaded-files/ESP32-CAM%20Product%20Specification.pdf),
[H3: PlatformIO board](https://docs.platformio.org/en/latest/boards/espressif32/esp32cam.html))

Record listing/SKU, maker/PCB revision, photographs of both sides, module and
memory markings, OV2640/flex identity/orientation, schematic match, detected
chip revision/flash/usable PSRAM, and programming adapter. A working camera
demo does not qualify recording, secure networking, OTA or 128GB retention.

### 2.2 Bench assembly and firmware

Start with the ready-made ESP32-CAM and verified OV2640, qualified card,
appropriate programming adapter and current-limited bench power. The original
board uses UART programming, not S3 native USB recovery. Identify an ESP32-CAM-MB
base or USB-equipped variant separately; a USB connector does not establish a
charger. Use 3.3V UART logic and a reviewed power supply rather than assuming a
USB-UART adapter can supply camera/SD/radio peaks.
Programming or sustained bench power is a separate service mode, with the pack
disconnected or an explicitly reviewed isolation arrangement; it must not
back-feed the battery. It is not a camera battery-charging interface.

Keep **PlatformIO + ESP-IDF C++** as the firmware proposal. Planned environments
are `vdog_esp32cam_proto` and `native`, created and pinned at package 0.2. Pin
platform, ESP-IDF, compiler, camera component, memory settings, board definition
and partition table. Do not switch to Arduino because a demonstration uses it.
No project/toolchain was created by this update.

Espressif's driver supports original ESP32 and OV2640. Above small JPEG modes
it requires PSRAM; more frame buffers increase memory/CPU pressure. Its PSRAM
DMA option is for S2/S3, not original ESP32. Measure this recorder's actual
internal heap, usable PSRAM, capture buffers and transfer buffers.
([H4: esp32-camera](https://github.com/espressif/esp32-camera))

### 2.3 Flash, TLS and signed OTA feasibility

Plan against verified flash size, ordinarily 4MB for this class, rather than the
superseded 16MB layout. Build the actual recorder plus HTTPS, authorization,
settings and signed OTA. Derive two application slots, OTA data, NVS/key/config
and diagnostics from measured binary sizes/alignment with update headroom. If
two qualified images do not fit, report the failure; do not silently remove
rollback or TLS.

PlatformIO's `esp32cam` manifest names `huge_app.csv` under its **Arduino**
configuration. That upstream table has one 3MiB application slot, so it is not
a dual-slot rollback shortcut for the required ESP-IDF design.
([H12: board manifest](https://raw.githubusercontent.com/platformio/platform-espressif32/develop/boards/esp32cam.json),
[H13: huge_app table](https://raw.githubusercontent.com/espressif/arduino-esp32/master/tools/partitions/huge_app.csv),
[H9: ESP-IDF OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html))

HTTPS and signed OTA are supported on original ESP32; the board's age alone
does not rule them out. ESP-IDF documents roughly 40KB RAM per SSL socket and a
potentially multi-second handshake. Qualify a small bounded connection count
against camera/SD operation. Identify chip revision before selecting the
signing/provisioning path: Secure Boot v2 on original ESP32 starts at revision
3.0. Signed update verification without hardware Secure Boot is a separate SDK
path. No eFuse changes are implied.
([H10: HTTPS server](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_https_server.html),
[H11: ESP32 Secure Boot v2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/secure-boot-v2.html),
[H9: signed OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html#secure-ota-updates-without-secure-boot))

S3 is a **fallback requiring a recorded decision** if flash, useful image quality,
simultaneous load or runtime fails. It is not the active board/pin map/memory
configuration and must not be substituted automatically.

## 3. Camera, SD and physical controls

### 3.1 Capture characterization

Use sensor JPEG and enabled PSRAM. Start with 640×480 at requested 15fps;
compare 640×480 and 800×600 at 10/15fps. These are test points, not guaranteed
modes. Record actual FPS/gaps/drops, exposure/blur, JPEG sizes, power and object
readability. Maximum sensor resolution does not establish recording speed.
Keep quality/resolution/FPS fixed inside a segment and record the profile.

Select lens/flex and mounting angle through harmless ground-object scenes at
the actual height. Damping and later off-device EIS cannot restore missing
source detail or an obstructed view.

### 3.2 Classic reference connections

This summarizes the classic V1.6 design and Espressif's
`CAMERA_MODEL_AI_THINKER` mapping. It is **not approved wiring** for an
uninspected board. Confirm PCB/schematic, connector orientation, supplies,
reset states and attached circuitry. Never reuse the earlier S3 candidate map.
([H2: V1.6 schematic, archived copy](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32_CAM_V1.6.pdf),
[H5: Espressif camera map](https://raw.githubusercontent.com/espressif/arduino-esp32/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h))

| Function | Classic reference GPIO | Constraint |
| --- | --- | --- |
| Camera D0–D7 | 5, 18, 19, 21, 36, 39, 34, 35 | Match sensor order; several pins are input-only |
| Camera XCLK | 0 | Also boot strap; not a runtime pairing button |
| Camera PCLK / VSYNC / HREF | 22 / 25 / 23 | Camera timing inputs |
| Camera SCCB SDA / SCL | 26 / 27 | Camera control; no assumed general shared I²C bus |
| Camera power control | 32 | Reference power switching; verify driver PWDN behavior |
| Camera RESET | No GPIO in reference map (`-1`) | Do not invent a spare reset net |
| SD slot 1 CLK / CMD / D0 | 14 / 15 / 2 | Baseline explicitly selects 1-bit SDMMC |
| SD D1 / D2 / D3 | 4 / 12 / 13 | Still physically connected to socket in 1-bit mode |
| White flash LED | 4 | Shared SD D1; baseline lamp disabled |
| Small status LED | 33 | Verify polarity, accessibility and PCB |
| UART0 TX / RX | 1 / 3 | Preserve programming/logging/recovery; 3.3V logic |
| External PSRAM | 16 / 17 plus memory bus | Do not assume GPIO16/17 are free |
| Battery ADC / IMU / user button | No approved assignment | Complete conflict/pull/strap review required |

Original ESP32 SDMMC uses fixed data/clock/command pins per slot, unlike S3's
GPIO-matrix bus. Slot 1 uses 14/15/2/4/12/13 as above. Explicit 1-bit mode avoids
using D1/flash LED for data, but does not disconnect the socket, remove required
pulls, or make unused lines automatically safe for other devices. Start at a
qualified default clock; higher speed needs actual signal/load evidence.
([H6: ESP32 SDMMC host](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/sdmmc_host.html))

Review GPIO12 flash-voltage strapping and GPIO2 download-mode requirements
against the actual card/pulls. GPIO0 goes low at reset for UART download and
must be released for normal boot/camera clock. The reference reset switch
resets the chip rather than providing an independent readable app button.
Physical local-access, pairing and ownership-reset gestures/circuits therefore
need a board-specific design. Do not attach them to GPIO0 during capture or
burn eFuses to resolve ordinary bring-up conflicts.
([H7: SD pull-ups/straps](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/sd_pullup_requirements.html),
[H14: boot selection](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html))

### 3.3 Required electrical/control review

Produce `hardware/prototype-a/pin-map.csv` with pad/header/GPIO/net/direction,
voltage, reset state, pulls and connector pin. Audit memory/straps/camera/SD,
LEDs, recovery and controls. Confirm actual board pull-ups rather than blindly
adding resistors to the old schematic. Distinguish recording, fault and timed
Wi-Fi states without enabling the high-current lamp.

Physical local-access and ownership controls remain mandatory workflow gates;
a specific external circuit or intentional reset/power gesture must be reviewed
for recording/recovery impact. Battery telemetry may remain unavailable until
a suitable measurement path exists. No extra button, ADC or IMU is assigned
merely because a pin is exposed. Optional IMU expansion is not a baseline need.

Before power: schematic match, continuity/short checks, approved input/current
limit, connector orientation and recovery. Then measure rails and identify
camera/card/memory before simultaneous tests. A build proves none of these
physical facts. With no local-access action, verify the radio remains off
through boot/recovery/recording and there is no waiting for a router or phone.

## 4. 128GB storage and 72-hour retention

### 4.1 Filesystem and capacity

Use genuine 128GB high-endurance microSD first. Record model/acquisition,
filesystem/allocation unit, usable bytes and firmware. Qualify at least two
actual models before broad compatibility claims. Branding/speed class does not
establish write-stall latency.

The legacy manufacturer's smaller TF-card claim is **not evidence of 128GB
support**, nor proof that larger cards cannot work through a modern driver.
Qualify this board/firmware/card with mount, full-capacity addressing, sustained
recording, rollover and recovery before advertising 128GB. Selecting classic
ESP32-CAM does not implicitly reduce the card requirement.
([H1: legacy qualification](https://lemariva.com/storage/app/media/uploaded-files/ESP32-CAM%20Product%20Specification.pdf))

128GB is SDXC, standardized with exFAT. The baseline remains explicitly
user-prepared/tested FAT32 because ESP-IDF does not enable exFAT by default;
current docs describe manual FatFs configuration without a standard menuconfig
path. FAT32 preparation differs from the SDXC default. Package 0.7 qualifies
the host procedure/allocation. Factory exFAT produces an unsupported-filesystem
error until a separate exFAT build is qualified. **Never autoformat on failure.**
([H15: SD capacity formats](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/),
[H8: ESP32 FatFs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/storage/fatfs.html))

Preparation is an explicit destructive owner action after backup on an
identified removable device, not a command with an assumed host disk name.
Segments stay below FAT32's single-file limit. Use 64-bit capacity/cumulative
accounting even though individual segments are small.

### 4.2 Arithmetic and qualification

```text
nominal_card_bytes = 128000000000
planning_pool_bytes = nominal_card_bytes × 0.85 = 108800000000
72h_seconds = 259200
maximum_all_recording_bps = 108800000000 × 8 / 259200 ≈ 3358024.69
at 15fps: ≈27984 bytes/frame including its share of all recording overhead
```

This is arithmetic, not measured capacity or a JPEG-only allowance. Account
allocated media/index/manifest/catalog/active bytes and complete-bundle
headroom using actual capacity. A 3.0Mbps **total allocated recording-growth**
target consumes 97.2GB/72h. Stage 3's 8GB protection comes from inside the pool:
the nominal 100.8GB rolling remainder allows about 3.111Mbps before additional
headroom. Never count protected footage as free rolling capacity.

Measure mixed scenes/high texture/low light and controlled walking/running
motion or approved bench equivalent. Report JPEG mean/p95/p99, actual FPS/gaps,
SD latency/longest stall, queue/heap/PSRAM, allocated bytes/hour and recoverable
coverage. A static bench scene cannot prove useful 72-hour retention.

A qualified external bench supply may run the ≥72h soak plus rollover. That
proves storage behavior, not 1000mAh endurance. Also test multiple battery
sessions and recharge/off gaps. Follow media/firmware interruption tests; FAT32
and card-controller behavior mean fsync/rename cannot guarantee damage is
limited to the last second. Preserve suspect data and report earlier corruption.

## 5. 3.7V 1000mAh pack and power system

### 5.1 Proposed topology

Use nominal **1S 3.7V 1000mAh rechargeable pack**. Verify chemistry, full-charge/
cutoff limits, protection, continuous/peak discharge, connector polarity,
dimensions/mass and temperature sensing from the exact supplier datasheet.
Capacity does not specify safe peak current; not every “3.7V” pack has identical
charging limits.

The classic V1.6 schematic shows **5V input → AMS1117 → 3.3V**, plus camera
rails, and no battery charger. Verify actual-board regulator substitutions.
The prototype uses the protected pack through a keyed service connector and
reviewed switch/shutdown/boost-converter arrangement to the board's regulated
5V input. Charging occurs only after the pack is disconnected and removed
from the camera, using a compatible external charger. This topology does not
specify approved wiring, a converter, a connector or a charger SKU.
([H2: power schematic](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32_CAM_V1.6.pdf))

```text
Recording, pack installed:
protected 1S 3.7V 1000mAh pack -> keyed service connector
    -> reviewed switch/shutdown + 5V regulation -> ESP32-CAM 5V input

Charging, camera removed from harness and pack disconnected/removed:
approved supply -> compatible external 1S charger -> protected pack

Programming/bench power is a separate reviewed mode, not a charging path.
```

Define converter/current limits, undervoltage shutdown, pack protection,
connector polarity/keying/retention, contact exposure, switch placement,
temperature qualification and fault handling. Review the separate charger's
chemistry, voltage/current and temperature/protection requirements against the
exact pack. No onboard charging circuit, USB charge input or concurrent
charge/load-sharing function is required.

Service procedure: remove the complete camera from the harness, use its
approved shutdown/power-off procedure, unplug the pack by its keyed connector,
then remove and charge the pack separately outside the camera. Power off before
unplugging; this reduces avoidable interruption but does not guarantee the last
write survives. Reconnect only after charging is complete and the charger is
disconnected. Pack restraint and connector access must support this procedure
without pulling cell wires or exposing contacts to a short.

Keep programming/bench power separate from charging. Disconnect the pack before
using an external camera supply unless a specific isolation arrangement is
reviewed and tested. Do not tie USB/bench and pack sources together or assume
the board regulates reverse current into the pack. Abrupt unplug, switch cut
and protection cutoff remain firmware/media recovery test cases.

**Do not connect the cell directly to 3V3, 5V or USB.** Its nominal 3.7V is not
regulated 3.3V/5V and its voltage changes over a cycle. Feeding the 5V/LDO path
directly also does not guarantee maintained rails through discharge. Regulated
3.3V input or regulator bypass would be a separately reviewed redesign.

### 5.2 Energy estimate and acceptance

Use energy rather than comparing battery mAh with current at another voltage.
This illustration uses **hypothetical** 80% usable pack energy and 85%
conversion efficiency to board input; neither is measured:

```text
nominal_energy = 3.7V × 1.0Ah = 3.7Wh
example_energy_at_board_input = 3.7Wh × 0.80 × 0.85 = 2.516Wh
example_runtime_hours = 2.516Wh / average_board_input_power_W
```

| Hypothetical average board-input power | Calculated example runtime |
| --- | ---: |
| 1.0W | 2.52h |
| 1.5W | 1.68h |
| 2.0W | 1.26h |

These are scenarios, **not ESP32-CAM load measurements or a runtime guarantee**.
Under these assumptions two hours requires about ≤1.26W average at board input.
Efficiency, aging, cutoff reserve, radio duty, SD, regulator loss and temperature
change the result. If measuring battery-side power, do not apply converter loss
a second time.

Size parts for measured simultaneous peaks at boot, camera/SD bursts, radio
transmit/download and TLS handshake. Verify droop/overshoot, pack/converter
currents, shutdown/restart and temperature. The white flash lamp stays off;
illumination requires a separate load/runtime/image-quality review. Record-only
measurements must verify Wi-Fi is actually off; short access sessions are a
separate workload, not grounds to promise continuous Wi-Fi runtime.

Charge the disconnected pack with its approved external charger, install it
after charger disconnection, run the qualified profile to controlled
shutdown and verify the files/useful recording duration. Repeat representative
record-only and timed-Wi-Fi workloads. Report charge duration, measured energy
if tested, shutdown reserve, mass, ambient and achieved runtime. Proposed
minimum is ≥1h; 2h remains a target until demonstrated. A miss requires a
reported tradeoff, not an invisible reduction of image quality/FPS.

### 5.3 Thermal, transitions and wear

Camera bench cases include boot, recording, Wi-Fi/TLS/download, SD bursts,
low-voltage/converter shutdown and restart, orderly pack disconnection and
controlled abrupt unplug. Test programming/bench supply only with the pack
disconnected or qualified isolation, verifying no back-feed. Qualify external
charger/pack compatibility, temperatures and completion separately; there is no
simultaneous charging/recording test requirement. Verify truthful power status.
Low-voltage warning permits best-effort flush only; abrupt pack cutoff still
requires interruption recovery.

Before wear, qualified review approves pack/circuit/basic housing/chest mount,
ambient, temperature method and contact/mass limits for the actual small dog.
Mass, dimensions, clearance and chest geometry remain measured decision inputs;
these docs invent no numeric limits. Component ratings are not contact limits.
Never charge while worn or with the pack inside the camera. Stop for abnormal
warmth, damage, rubbing, exposed pack, wet contacts, loose mount or discomfort.

## 6. Mechanical design, production approach and expansion

Use the ready-made board first. A reviewed carrier/power board may add the pack
system, service connectors and physical controls. A custom ESP32 camera PCB is
optional after feasibility/cost justify it; a custom S3 PCB is not required.
Define compatibility for each purchased board/carrier revision.

**A basic non-weather-rated protective housing is required before any wear
trial**, even though a weather-protective enclosure is deferred. It restrains
pack/wires, prevents screw/edge contact with the cell, retains SD, recesses
connectors and permits safe pack removal for separate charging. Separate
rigid/hot parts from wearer contact. Preserve antenna clearance and test the
enclosed assembly near the body. Do not wear exposed electronics or an
unrestrained pack while waiting for the later enclosure version.

The first fit target is the owner's dog reported **under 8kg**. Record its exact
weight, chest dimensions and harness dimensions before CAD fit decisions; do
not treat the reported upper bound as a universal 0–8kg compatibility claim.
Measure the complete assembly's mass, dimensions, chest clearance, mount
position, tilt and movement against that actual harness/dog before acceptance;
target limits are pending those measurements and qualified review. Larger-dog compatibility is future
work requiring its own harness geometry, view and movement checks, not an
automatic inference from the first mount.

Camera bracket/damping count in the BOM; the separately purchased harness does
not. Check tilt/ground view/fur/strap occlusion, movement, rubbing, retention
and snag behavior. Initial use is **dry weather only**. A later protective
weather version requires separate ingress/thermal/RF/mount qualification; do
not claim rain, water, IP/drop/breakaway or universal-size suitability from
the first housing.

Damping and off-device optical processing are baseline. A manufactured ESP32-CAM
board has no required new IMU footprint. Optional IMU/ADC/button expansion needs
pin/pull/power/timing/cost review and must not block recording if absent. A gyro
alone does not stabilize footage: timing, lens calibration, orientation and a
supported processing pipeline would still be required.

## 7. Cost and release artifacts

### 7.1 Unquoted engineering allocation

These are **design ceilings**, not current CN prices or proof of a CNY149
product. State procurement quantity (planning reference: 1,000 assemblies),
quote prototypes separately, and track engineering/tooling/certification/
logistics/taxes/packaging/warranty/margin outside this base allocation with
explicit quote inclusions.

| Allocation | CNY/unit ceiling | Scope / avoid double counting |
| --- | ---: | --- |
| Complete ESP32-CAM + verified OV2640 | 40 | MCU/memory/socket/onboard regulator/camera connector/LEDs included |
| Protected 1S 3.7V 1000mAh pack | 20 | Identify included protection and temperature sensing |
| Compatible external charger and pack service parts | 18 | Initial kit includes charger allocation, keyed disconnect and required pack-service/protection additions not already counted |
| 5V regulation and supporting components | 10 | Qualified converter/decoupling/enable/shutdown |
| Carrier/wiring/service/controls/ESD additions | 13 | Needed off-board interfaces/PCB/assembly, no onboard charger or duplicate SD/regulator |
| Basic protective housing, chest bracket, damping and fasteners | 16 | Dry-weather device hardware and pack restraint, excludes harness purchase |
| Assembly, factory test and yield allowance | 12 | Whole assembly labor/test; no duplicate fitted-carrier labor |
| Unallocated contingency | 20 | Quote gaps/substitutions/revision allowance |
| **Total ceiling** | **149** | **Excludes SD and harness** |

Programming tools/instruments are development costs. If a programmer base stays
in the wearable, include per-unit cost/mass/power; otherwise document recovery
access. Optional sensors need reviewed reallocation. Do not remove pack
protection or required tests to meet a price target.

The initial CNY149 allocation retains an external-charger allowance; moving
charging outside the camera is **not a claimed price saving**. If sold or built
as a kit, identify the compatible charger and include its per-kit cost. A future
owner-supplied/reused or separately sold charger requires an explicit accessory
and total-cost basis; do not silently exclude it from the sub-CNY150 comparison.
Count connector/protection/service parts once across the pack/charger/carrier
lines. A future weather enclosure has its own cost revision, not a current rating.

### 7.2 Cost evidence and public package

Record part number/variant, quantity, maker, alternatives, supplier, quote date,
price break/minimum order, currency, tax/freight basis, availability and quote
identifier. The complete purchased board is one line with included parts, not
also a camera/SD/regulator charged again. Redact personal purchasing data and
secret provisioning materials.

Release actual board identity/schematic reference, approved wiring/pin map,
editable carrier sources if any, BOM/cost evidence, carrier ERC/DRC/fabrication/
placement where applicable, housing CAD/printable outputs, pack/connector
polarity, separate external-charger compatibility and charging/removal guide,
small-dog chest-mount fit record, dry-weather limits, programming/recovery,
factory test, firmware compatibility and limitations.
Check vendor-design redistribution rights. A carrier does not establish that
the purchased board's internal design is an open-hardware release artifact.

## 8. Hardware gates

| Gate | Required output | Blocks |
| --- | --- | --- |
| HW-G0: identity/resource budget | Actual PCB/OV2640/card/pack, pinned ESP-IDF build, detected chip/memory; two-slot/TLS feasibility | Supported-board/security/wiring claims |
| HW-G1: electrical bring-up | Reviewed power/control map, current-limited rails, camera/card/UART evidence | Sustained hardware capture |
| HW-G2: recording/storage | Useful motion profile/rate/gap/power; 128GB addressing, actual 72h/rollover | 128GB/72h claim and production commitment |
| HW-G3: battery/housing | Reviewed protected 1000mAh disconnect/switch/5V path and separate charger; ≥1h proposed minimum/2h target; unplug/recovery/thermal; basic housing/pack restraint and measured small-dog chest fit | Supervised dry-weather wear |
| HW-G4: wearable prototype | Approved actual-assembly small-dog chest fit/movement/view/comfort report, dry-weather use only | General-user distribution within that tested scope; no larger-dog/weather claim |
| HW-G5: production | Quoted BOM <CNY150 with explicit charger/kit basis, applicable design package, pilot test/yield and product obligations | Production-cost/manufacturing-ready claim |

HOST/build work may precede a physical unit but cannot pass detection or DEVICE/
FIELD criteria. Board revision, protected pack/compatible external charger,
keyed disconnect/switch/converter, physical control and measured chest-mount
limits remain concrete package 0.2–0.7/4.1 decisions. If a gate fails, report
measurements and obtain an explicit scope decision.
