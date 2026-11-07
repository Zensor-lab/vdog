# Hardware specification

Status: proposed engineering baseline, 2026-11-07. No circuit, PCB, camera,
battery, SD card, enclosure, supplier price, or wearable assembly has been
validated by this documentation task. The user selected ESP32-S3 and 128GB
storage as the first priority and requested Chinese procurement pricing and a
hardware cost below CNY150 excluding the SD card and harness. Other component
choices below are proposals to make that goal testable. See [references](../references.md)
for the source conversation and primary technical sources.

## 1. Product boundary

The device records a forward/downward view from a harness mount to removable
microSD. Recording starts automatically when power is available and a supported
card is mounted. Network loss must not stop recording. Wi-Fi enables nearby
configuration, preview, download, updates, and later optional backend sync.
There is no cellular modem or SIM requirement in this baseline.

The 72-hour requirement describes the amount of recorded footage retained on
the card. It does **not** describe battery endurance, uninterrupted wear time,
or recording while the device is switched off. A three-day retention claim
requires a measured recording profile and the software retention tests.

| ID | Requirement | Verification before claiming support |
| --- | --- | --- |
| HWR-01 | Prioritize ESP32-S3 with 128GB microSD | Bring-up report identifies exact module, board revision, card model, and usable bytes |
| HWR-02 | Production hardware allocation below CNY150, excluding card and harness | Complete dated CN BOM, assembly/test/loss allowances, quantity, and supplier quotes |
| HWR-03 | Camera supports JPEG capture through a supported driver | Identified sensor/module revision produces decodable frames under sustained recording |
| HWR-04 | SD path withstands capture and qualified network workloads | Throughput, write-stall, removal, full-card, and power-cut tests |
| HWR-05 | Battery, regulation, protection, charging, and thermal design are reviewed together | Reviewed schematic and instrumented bench evidence, before wear trials |
| HWR-06 | Mount holds camera direction and permits normal movement | Recorded fit and supervised movement observations after bench acceptance |
| HWR-07 | Physical control and visible recording/error indication | Firmware and assembly tests cover startup, recording, SD error, and pairing |
| HWR-08 | Mechanical damping is baseline; IMU is optional | Mount comparison; firmware works without an IMU populated |
| HWR-09 | SD contents survive foreseeable interruption as specified by firmware recovery | Power-cut corpus and file-recovery results; filesystem corruption limitations recorded |
| HWR-10 | Public build package is reproducible | Schematics, PCB sources, BOM, assembly drawings, enclosure sources, and revision-specific pin map |

## 2. Reference architecture and procurement stages

### 2.1 Candidate module

Use **ESP32-S3-WROOM-1-N16R8** as the module candidate for the custom board.
This is a module ordering code, not the name of a bare MCU or a complete camera
board. Espressif lists 16MB Quad SPI flash and 8MB Octal SPI PSRAM for this
variant; the module includes the RF antenna and related circuitry. The module
requires a regulated 3.3V supply within its specified range. GPIO35, GPIO36,
and GPIO37 are used by its Octal PSRAM and are unavailable for peripherals.
These facts do not establish recording speed or battery life.
([H1: module datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf))

Do not substitute N16, N16R2, R16V, WROOM-2, or a look-alike module without
repeating the memory, voltage, pin, and firmware-configuration review.

### 2.2 Bench prototype

Candidate assembly:

1. DevKitC-1-form-factor board carrying the actual N16R8 module.
2. OV2640 DVP camera **module/breakout** with documented connector orientation,
   supply requirements, signal voltage, and lens; not an unidentified bare sensor.
3. 3.3V-compatible microSD socket/breakout exposing SDMMC signals, card-detect
   where available, and documented pull-ups.
4. Current-limited bench supply or the board's documented USB power input.
5. Logic analyzer/oscilloscope access, power measurement, and USB serial logs.

The exact N16R8 board supplier and revision remain an acquisition gate. The
official DevKitC-1 family has multiple memory variants, and a board sold under
that name may be a third-party layout. Photograph both sides, capture its
schematic, and check module marking before selecting firmware settings. The
official v1.0 board drives its RGB LED on GPIO48; v1.1 moves it to GPIO38.
([H2: v1.0 guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html),
[H3: v1.1 guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html))

Do not connect a Li-ion cell directly to the module's 3V3 pin, a board's 5V pin,
or USB power. Battery operation requires the reviewed power assembly in section
5. USB and battery paths must not back-feed each other.

### 2.3 Prototype versus production

The CNY150 limit is a production engineering target, not a claimed price for a
one-off DevKit, retail breakout boards, tools, or engineering services. Validate
the S3 recording profile before committing to PCB layout or tooling. A custom
board must retain the prototype's working interfaces while replacing unnecessary
development-board components. P4, H.264 hardware, larger cards, and LTE remain
alternatives requiring an explicit product decision if the S3 feasibility gate
fails; they are not silent substitutions.

## 3. Camera and signal allocation

### 3.1 Capture baseline

OV2640 is the low-cost candidate. Espressif's camera driver supports both S3 and
OV2640, provides JPEG capture, and documents the memory pressure of RGB/YUV
capture and multiple frame buffers. This specification therefore starts with
sensor JPEG output and PSRAM enabled. Sensor maximum resolution does not imply
the device can record at that resolution and a useful frame rate while writing
SD and serving Wi-Fi.
([H4: esp32-camera](https://github.com/espressif/esp32-camera))

Start the characterization matrix at 640×480 and 15fps requested rate; also
measure 800×600 at 10fps and 15fps. Report actual delivered frame rate, JPEG size
distribution, dropped frames, exposure/blur, and object visibility. This is a
test matrix, not three promised supported modes. The selected default belongs
in the approved recording profile after the capacity and image-quality gate.
Lens angle and camera tilt are selected through ground-object tests at the
actual mounting height, not from an assumed universal field of view.

### 3.2 Bench-only candidate GPIO assignment

The following is a **design proposal, not verified wiring**. No hardware has
been inspected or energized against it. The hardware owner must reconcile every
row with the acquired board schematic, module pin table, camera connector,
camera rails, SD breakout, LED revision, and firmware driver before approving
`hardware/<revision>/pin-map.csv`. A code agent must not turn this table into
wiring instructions without that review.

| Function | Proposed S3 GPIO | Notes to resolve in the board review |
| --- | --- | --- |
| Camera D0–D7 | 4, 5, 6, 7, 8, 9, 10, 11 | Match sensor Y2–Y9/data-bit naming and connector orientation |
| Camera XCLK | 12 | Configure clock through the camera driver; verify signal integrity |
| Camera PCLK | 13 | Camera output; validate clock routing and capture |
| Camera VSYNC / HREF | 14 / 15 | Inputs; do not swap frame/line sync |
| Camera SCCB SDA / SCL | 16 / 17 | Verify module pull-ups and driver bus ownership |
| Camera PWDN / RESET | 18 / 21 | Only if exposed; documented fixed levels may permit NC settings |
| SDMMC CLK / CMD / D0 | 39 / 40 / 41 | Baseline 1-bit bus; repurposes these external JTAG pins |
| SD card detect | 42 | Optional socket switch; otherwise detect I/O failure in software |
| Battery voltage sense | 1 | Divider, filtering, and calibrated ADC range reviewed separately |
| Optional IMU SDA / SCL | 2 / 47 | Separate proposed bus; no assumed sharing with SCCB |
| Recording/error indicator | Board LED on 38 **or** 48 | Select exact board revision, not both |
| User control | Unused one of 38/48, external switch | Confirm board circuitry; if unavailable revise allocation |
| Native USB D− / D+ | Reserve 19 / 20 | Preserve the approved programming/recovery path |
| UART0 TX / RX | Reserve 43 / 44 | Preserve serial logs and recovery during bring-up |
| Boot/strapping | Reserve 0, 3, 45, 46 | Do not let peripheral pull states change startup configuration |
| Module memory | Do not use 26–37 | Module-internal/unexposed memory pins; especially 35–37 on N16R8 |

Using 39–42 prevents use of the ordinary external JTAG pin set for another
purpose at the same time. Native USB Serial/JTAG or UART must remain a tested
recovery path. An optional IMU interrupt has no allocated pin in this proposal;
polling/FIFO is the initial investigation. A required interrupt or 4-bit SD bus
forces a new allocation review.

The ESP32-S3 SDMMC host supports GPIO-matrix routing and 1-bit operation. Set
the bus width explicitly rather than relying on a default that attempts a wider
bus. Begin at the supported default-speed configuration; any higher clock is a
measured board qualification step.
([H5: SDMMC host](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sdmmc_host.html))

### 3.3 Electrical review deliverables

Before first power, produce one revision-specific table with module pad, GPIO,
board header, peripheral net, direction, voltage, reset state, pull-up/down,
and connector pin. Check for duplicate nets and reserved pins. Verify camera
and SD pull-ups against their electrical requirements, including the inactive
SD data lines in 1-bit mode; do not rely on MCU internal pull-ups as a substitute
for the reviewed SD circuit.
([H6: SD pull-up requirements](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/sd_pullup_requirements.html))

Acceptance evidence must include schematic review, continuity/short checks,
current-limited first power, measured rails, camera identification, SD
identification, and simultaneous camera/SD operation. A firmware build is not
evidence that a pin map or power circuit works.

## 4. Storage and retention feasibility

### 4.1 Card and filesystem contract

Use a genuine 128GB high-endurance microSD as the priority test card. Record
manufacturer, model, capacity, card identity where available, acquisition
channel, filesystem, allocation unit, mount options, and firmware revision.
Qualify at least two actual card models before claiming broad compatibility.
Speed-class labeling alone does not establish latency under this workload.

A 128GB card is SDXC, whose standard filesystem is exFAT. ESP-IDF's FatFs
integration does not enable exFAT by default; current documentation describes
manual configuration rather than a standard menuconfig enablement path. The
initial baseline is therefore an **explicitly user-prepared and tested FAT32
card**, accepting that this differs from the SDXC default. The exact host
preparation procedure and its compatibility must be validated at Stage 0.
Factory exFAT cards must produce an unsupported-filesystem error until a
separately reviewed exFAT build is qualified.
([H7: SD capacity formats](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/),
[H8: ESP-IDF FatFs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/fatfs.html))

Never automatically format on mount failure. Card preparation is an explicit
destructive owner action on an identified removable device. Do not publish an
unguarded formatting command with an assumed disk name. Segmented recording
keeps files well below FAT32's single-file limit. Firmware must use 64-bit
capacity and cumulative-byte counters even though individual segments are small.

### 4.2 Capacity arithmetic

Use decimal GB for card advertising and bytes for implementation. A nominal
128GB card with a planning reserve of 15% leaves 108,800,000,000 bytes before
further protected-event allocations. For 72 hours:

```text
duration_seconds = 72 × 3600 = 259200
maximum_all_recording_bps = 108800000000 × 8 / 259200
                          ≈ 3358024.69 bit/s
maximum_all_recording_bytes_per_second ≈ 419753.09
```

At 15fps this is approximately 27,984 bytes per frame **including each frame's
share of indexes, manifests, filesystem allocation overhead, and other recorded
data**. It is not a JPEG payload allowance alone. Use measured allocatable
capacity and the software storage budget for the release calculation. A 3Mbps
planning profile consumes 97.2GB over 72 hours before any overhead not already
included in that bitrate. MJPEG is scene dependent; average size from a static
bench scene cannot prove walking/running retention.

When event protection uses part of the card, recalculate the rolling-recording
budget. For example, reserving another 8GB from the above pool leaves 100.8GB,
or about 3.111Mbps for all rolling-recording data over 72 hours. Protected data
must not be counted twice as free rolling capacity.

### 4.3 Storage qualification

Measure camera output and SD writes together for the approved modes. Record
mean and p95/p99 JPEG size, write latency, longest write stall, queue high-water
mark, dropped frames, total bytes per hour, free-space floor, and oldest/newest
recoverable recordings. Run a representative 72-hour powered recording test
plus enough additional recording to force rollover. Use mixed scenes including
high texture, low light, walking, and running footage or an approved bench
equivalent. Keep raw footage private unless explicitly approved for sharing.

Repeated full-card writes, removal, restart, power interruption, and worn/slow
card tests must follow the firmware recovery specification. FAT32 is not a
journaling filesystem: application commit ordering reduces some losses but
cannot guarantee immunity to filesystem or SD-controller corruption. Report
corruption honestly and preserve suspect media for diagnosis.

## 5. Power, battery, charging, and thermal design

### 5.1 Power architecture

The custom-board candidate uses a protected single-cell rechargeable pack,
charger with appropriate charge control and temperature monitoring, a defined
USB/battery power path, and regulation that maintains the approved rails across
the pack's operating range. Exact pack, charger, regulator, connectors, fuse or
current-limiting approach, current limits, and protection thresholds are not
selected yet. Select them as one reviewed circuit, not a collection of cheap
breakout modules with unknown power-path behavior.

Espressif recommends a 3.3V supply capable of at least 500mA for the S3 chip
design. That value does not include a qualified margin for the whole camera,
card, radios, regulator losses, or charging system. Size the actual system from
measured simultaneous peak load and transient behavior, with its own design
margin and decoupling review.
([H9: schematic checklist](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html))

Required bench cases are camera+SD recording, Wi-Fi transmit/download, boot,
SD write bursts, low pack voltage, USB attach/detach, charging while the system
is powered, and restart after low-voltage shutdown. Verify rail minima,
overshoot, current, regulator/charger/pack temperatures, protection behavior,
and absence of back-feed. A power-fail indication may permit an orderly flush,
but no assumed capacitor or battery reserve guarantees the final write.

### 5.2 Runtime and capacity selection

Begin with a supplier-documented pack capacity appropriate to the measured load
and wearable mass. The prior discussion mentioned larger packs as examples;
it did not establish an approved capacity. Avoid choosing 3000–5000mAh solely
to repeat that example.

```text
runtime_hours ≈ nominal_voltage_V × rated_capacity_Ah
                × usable_energy_fraction × conversion_efficiency
                / measured_average_system_power_W
```

Record all terms and then verify runtime to the approved shutdown threshold.
Report runtime separately for recording-only and Wi-Fi-heavy usage. State
charging duration, usable recording time, added mass, and whether recording
continues through USB transitions. Do not infer battery percentage linearly
from a single voltage reading.

### 5.3 Bench and wear gates

No wear trial begins before the electrical design, enclosure, mounting,
temperature measurement method, ambient conditions, and supervised trial
procedure are reviewed. The project has no validated dog-contact temperature
or universal mass limit. Establish appropriate acceptance limits with qualified
input and record them before trials; the MCU's component temperature rating is
not a wearable-contact limit.

Do not charge a prototype while attached to an animal. Stop a trial for damaged
enclosure, loose mount, rubbing, abnormal warmth, wet charging contacts, exposed
battery, or signs of discomfort. These operating conditions belong in the
eventual assembly/user guide as well as the test procedure.

## 6. Mechanical and optional sensor requirements

The enclosure must isolate the pack from screw tips and edges, restrain wiring,
retain the card, recess exposed connectors, and allow safe service access. It
must prevent direct rubbing of rigid or hot components against the wearer.
Keep the antenna clear of metal, battery shielding, and the mounting plate;
check RF performance with the completed assembly and body proximity.

The camera mount attaches to a harness; the harness purchase is excluded from
the CNY150 target, while the camera's own attachment bracket and damping pieces
are included. Test tilt adjustment, lens occlusion by fur/straps, ground view,
retention, vibration, and snag behavior. Any breakaway or retention design is a
documented mechanical decision requiring assessment of the actual assembly.
Do not claim an ingress-protection or drop rating without the applicable test.

Baseline stabilization is mechanical damping plus optional later software
processing. Do not promise that adding an IMU stabilizes recorded video.
Reserve an unpopulated footprint or documented expansion interface if it fits
the cost and space budget. LSM6DS3TR-C is a candidate 6-axis accelerometer/gyro
with I²C/SPI interfaces; verify the chosen part and electrical design before
population. Gyro-based stabilization additionally needs camera/IMU timing,
orientation, lens calibration, and a supported processing pipeline.
([H10: ST LSM6DS3TR-C](https://www.st.com/en/mems-and-sensors/lsm6ds3tr-c.html))

## 7. Cost control and manufacturing package

### 7.1 Engineering allocation

The following CNY allocations are deliberately chosen design ceilings, **not
supplier quotations, current market prices, or evidence of a manufacturable
CNY149 product**. The quantity assumption is 1,000 assembled units purchased
through the mainland China supply chain. Prototype costs and one-time design,
tooling, certification, logistics, taxes, warranty, and margin are tracked
separately. A production quote must explicitly identify which of those items
are included or excluded.

| Allocation | CNY per unit ceiling | Included scope |
| --- | ---: | --- |
| ESP32-S3-WROOM-1-N16R8 module | 33 | Module with its memory and antenna |
| Camera module and lens | 18 | Identified sensor, lens, connector/flex as needed |
| PCB and SMT assembly | 22 | Fabrication and placement, not components counted elsewhere |
| Power, charging, regulation, protection | 14 | All required ICs/passives and temperature sensing |
| Battery pack | 20 | Supplier-documented protected pack; avoid double-counting protection |
| SD socket, USB, controls, ESD, connectors | 10 | Required interfaces and protection |
| Enclosure, device mount, damping, fasteners | 12 | Camera hardware; excludes separately purchased harness |
| Factory test and expected loss allowance | 8 | Per-unit test labor and stated yield allowance |
| Unallocated contingency | 12 | Reserved for quote gaps and substitutions |
| **Total ceiling** | **149** | **Excludes microSD and harness** |

The optional IMU is not populated in this allocation. If added, it must fit
within contingency or another justified reallocation while remaining below
CNY150; removing battery protection or required tests is not an acceptable
cost reduction. If quotes exceed the ceiling, report the variance and revise
the design or obtain a product decision before claiming the target is met.

### 7.2 BOM evidence and release files

For every fitted item record reference designators, manufacturer part number,
value/package, approved alternative, quantity, supplier, dated unit price,
price-break quantity, currency, minimum order, availability, tax/freight basis,
and link or quotation identifier. Keep quotes and purchasing personal data out
of public files where necessary; publish a redacted cost summary and assumptions.

Before a hardware release, provide editable schematic and PCB sources,
ERC/DRC reports, board stack-up, Gerbers/drill files, BOM, placement data,
assembly/polarity drawings, programming/test points, revision labels, pin map,
enclosure CAD sources and printable outputs, firmware compatibility, assembly
guide, factory test procedure, and measured acceptance evidence. Exact CAD
tools and open-hardware license remain decisions to record before release.
Do not represent this specification as an existing fabrication package.

## 8. Hardware decision gates and evidence

| Gate | Required output | Blocks |
| --- | --- | --- |
| HW-G0: parts and build identity | Actual board/module/camera/card identities; locked toolchain; reviewed memory setup | Any approved wiring or hardware-supported build claim |
| HW-G1: electrical bring-up | Signed-off schematic/pin map, current-limited power evidence, rails and camera/SD identification | Sustained capture tests |
| HW-G2: recording feasibility | Useful motion footage, sustainable frame rate, capacity calculation, 72-hour retention and rollover evidence | Custom-board commitment and 72-hour claim |
| HW-G3: power and enclosure | Pack/power design, runtime, thermal and transition tests, assembled mass and mount review | Any supervised wear trial |
| HW-G4: wearable prototype | Supervised fit/movement report, ground view, retention and comfort observations | General-user prototype distribution |
| HW-G5: production readiness | Quoted BOM below CNY150, complete design package, factory test/yield evidence, product obligations assessed | Production cost or ready-to-manufacture claim |

The Stage 0 toolchain check must account for PlatformIO's documented
`esp32-s3-devkitc-1` definition being an N8 board without PSRAM, rather than
assuming it configures N16R8 correctly. Use reviewed overrides or a project
board definition; verify detected flash capacity and PSRAM on the actual unit.
Pin the PlatformIO platform, ESP-IDF, camera component, compiler, and board
definition in the implementation handoff. A move to native ESP-IDF needs a
recorded compatibility decision if the proposed PlatformIO combination fails.
([H11: PlatformIO board definition](https://docs.platformio.org/en/latest/boards/espressif32/esp32-s3-devkitc-1.html))
