# vdog — open-source dog camera

vdog aims to make a useful dog-mounted camera affordable: record walks locally,
review what happened around the dog, and keep control of the footage without a
mandatory subscription or vendor cloud.

We want to build this in the open so owners can understand how recordings are
stored, repair their camera, adapt a harness mount, and improve the design
together. Reliable footage and accessible ownership matter more than adding
expensive features. A camera can help review an incident; it does not guarantee
that harm will be detected or prevented.

## Project status

**Early prototype.** A minimal firmware build and portable host tests are
available; camera recording, the mobile app, backend, PCB and enclosure remain
planned. Device operation, cost, 72-hour retention, image quality,
battery runtime and wearable suitability remain engineering gates.

The current prototype uses **Seeed Studio XIAO ESP32S3 Sense** and starts with
**32GB FAT32 microSD**. PlatformIO officially supports the XIAO base-board target
with ESP-IDF and Arduino; the minimal ESP-IDF build is qualified, while the
Sense peripherals still need hardware tests. See [PlatformIO support](docs/platformio-support.md).

Use the camera shipped with the acquired Sense revision after identification:
current Seeed documentation describes fixed-focus OV5640/OV3660 shipments;
OV2640 belongs to older units. The onboard microphone remains unused: v1 has
no audio recording. Nominal **3.7V 1000mAh**, approximately **1–2h per charge**,
mainly SD recording and on-demand Wi-Fi remain the targets, not measured results.

The first version targets a **small dog's chest harness** (the owner's dog is
**below 8kg**) in **dry weather**. Remove the camera and unplug the pack for a
compatible external charger. The XIAO has onboard charging hardware, but our
external-charge policy remains: disconnect the pack before USB service unless
an isolation arrangement is reviewed. Use its qualified BAT input/onboard power
path; the former AI-Thinker 5V-boost topology is not a default for this board.
Basic protective housing is required before wear. Weather protection and
larger-dog fit need later validation.

The **72h recorded-footage retention goal remains unverified on 32GB**. With
15% reserved, the nominal ceiling is only about **0.84Mbit/s total recording
writes**, before event protection/headroom. Useful high-motion JPEG quality may
not fit; measure retention and quality together and obtain a decision if the
combination fails. Never promise 72h or silently reduce image quality.

China procurement and the **required-kit BOM target below CNY150**, excluding
SD/harness but including the external charger, remain goals requiring new quotes.
The XIAO board selection has not been shown to meet that budget. Prototype cost
and retail price are separate; current allocations are not supplier quotations.

## Planned capabilities

- Start recording automatically and keep segmented footage on microSD offline.
- Measure the rolling history on 32GB; retain 72h as an unverified quality/capacity
  goal. Battery endurance is a separate measurement.
- Use Wi-Fi for a Flutter Android/iOS app: pairing, preview, verified downloads,
  original playback and signed firmware updates.
- Optionally self-host a Rust backend for originals, MP4 exports, event
  organization and post-processing stabilization.
- Use a harness mount and mechanical damping; an IMU is optional research.

The proposed v1 has no SIM/LTE, required cloud account, audio capture or onboard
real-time stabilization. See [requirements](docs/specs/product.md) for confirmed
user priorities versus engineering proposals.

## Getting started

For the minimal firmware, follow the [prototype installation guide](docs/installation.md)
for tool setup, USB upload, port selection and BOOT/RESET recovery.
For development, start with the [documentation guide](docs/README.md), then
[Stage 0 of the implementation plan](docs/plans/implementation-plan.md). It
qualifies the board/toolchain, wiring, card format and recording quality before
a custom PCB or full app/backend build.

The eventual owner flow is: prepare a supported card, power the camera and check
recording status, pair nearby over Wi-Fi, then review or download footage. The
storage baseline is a genuine 32GB FAT32 card on the Sense SPI socket; larger
cards need a separate qualification. Prototype animal use waits
for electrical, thermal and mounting acceptance.

### Firmware build

Package 0.2 qualified a pinned minimal ESP-IDF proto build for the XIAO
ESP32S3 target (qualifier: see [toolchain matrix](docs/toolchain.md)). From
the repository root with PlatformIO Core 6.2:

```sh
pio run -d firmware -e vdog_xiao_sense_proto   # cross-build (BUILD evidence)
pio run -d firmware -e vdog_xiao_sense_proto -t size
pio test -d firmware -e native                 # host tests (HOST evidence)
```

These commands compile and host-test only. This proto has no camera, SD,
network or radio runtime. USB upload instructions are in the
[installation guide](docs/installation.md); upload and device operation remain
unverified here.

## Documentation

| Document | Contents |
| --- | --- |
| [Prototype installation](docs/installation.md) | Build, USB upload, port selection, BOOT/RESET recovery and Python troubleshooting |
| [Hardware decision review](docs/hardware-decision-review.md) | XIAO Sense/32GB tradeoffs, retention/runtime calculations and decisions |
| [PlatformIO support](docs/platformio-support.md) | Verified upstream board support and the remaining build/peripheral gates |
| [Detailed implementation plan](docs/plans/implementation-plan.md) | Numbered work packages, dependencies, outputs, tests and agent handoffs |
| [Hardware specification](docs/specs/hardware.md) | Candidate parts/pins, power, card compatibility, cost allocation and production gates |
| [Firmware specification](docs/specs/firmware.md) | Capture, recovery, retention, networking and OTA |
| [Flutter frontend](docs/specs/frontend.md) | Mobile flows, permissions, transfers and indexed JPEG playback |
| [Rust backend](docs/specs/backend.md) | Ingestion, durable storage, jobs, exports and optional notifications |
| [Media format](docs/specs/media-format.md) / [API contracts](docs/specs/interfaces.md) | Shared file/wire definitions and integrity rules |
| [Architecture](docs/architecture.md) / [decisions](docs/decisions.md) | Boundaries, proposals and unresolved questions |
| [Validation](docs/validation.md) / [security](docs/security.md) | Required evidence, failure tests and owner privacy |
| [Research references](docs/references.md) | Source conversation, primary sources and evidence limits |

Contributions start with one bounded plan package and its acceptance criteria.
[AGENTS.md](AGENTS.md) holds working instructions;
[project profile](docs/project-profile.md) holds shared implementation facts.

## License

Repository source/documentation are covered by the existing [MIT license](LICENSE).
Third-party software and future hardware-design distributions require their own
applicable notices and license review.
