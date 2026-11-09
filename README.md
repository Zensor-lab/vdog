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

**Planning and specifications only.** Firmware, the mobile app, backend, PCB and
enclosure have not been built or tested. Cost, 72-hour retention, image quality,
battery runtime and wearable suitability remain engineering gates.

The prototype direction is **classic AI-Thinker ESP32-CAM + OV2640**, a **3.7V
1000mAh battery**, and approximately **1–2 hours of recording per charge**.
Record mainly to SD and enable Wi-Fi when needed. These targets await bench
validation; the earlier S3 prototype proposal has been superseded.

The first version targets a **small dog's chest harness** (the owner's dog is
**below 8kg**), in **dry weather**. Remove the camera from the harness and unplug the battery for charging
with a separate compatible charger; there is no onboard charging requirement.
A basic protective housing is still required before wear. Weather protection is
later work and larger-dog fit needs separate checks.

The **128GB microSD** priority remains, with Chinese procurement and
a **production hardware BOM below CNY150**, excluding the SD card and harness.
This is a design target, not a quoted retail price or the cost of a one-off
development prototype.

## Planned capabilities

- Start recording automatically and keep segmented footage on microSD offline.
- Target a 72-hour rolling recording history while powered; battery endurance is
  a separate measurement.
- Use Wi-Fi for a Flutter Android/iOS app: pairing, preview, verified downloads,
  original playback and signed firmware updates.
- Optionally self-host a Rust backend for originals, MP4 exports, event
  organization and post-processing stabilization.
- Use a harness mount and mechanical damping; an IMU is optional research.

The proposed v1 has no SIM/LTE, required cloud account, audio capture or onboard
real-time stabilization. See [requirements](docs/specs/product.md) for confirmed
user priorities versus engineering proposals.

## Getting started

There is no application to install, flash or run yet. Start with the
[documentation guide](docs/README.md), then execute
[Stage 0 of the implementation plan](docs/plans/implementation-plan.md). It
qualifies the board/toolchain, wiring, card format and recording quality before
a custom PCB or full app/backend build.

The eventual owner flow is: prepare a supported card, power the camera and check
recording status, pair nearby over Wi-Fi, then review or download footage. The
storage baseline requires an explicitly prepared and tested FAT32 card;
factory-formatted 128GB exFAT support is not assumed. Prototype animal use waits
for electrical, thermal and mounting acceptance.

## Documentation

| Document | Contents |
| --- | --- |
| [Hardware decision review](docs/hardware-decision-review.md) | ESP32-CAM/battery tradeoffs, runtime calculations and remaining decisions |
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
