# Project facts for implementation agents

This tracked profile holds shared facts because the starter ignores `.agent/`.
The local `.agent/PROJECT.md` points here. Operating rules remain in
[AGENTS.md](../AGENTS.md).

## Product and current state

- vdog: affordable open-source dog camera, local recording, owner-controlled
  footage, optional self-hosted processing; for owners, builders and self-hosters.
- Current state: minimal pinned firmware and portable host tests exist with
  package 0.2 BUILD/HOST evidence. Camera/SD/network runtime, app/backend and
  hardware qualification remain pending.
- Stage 0.9 is implemented on `opencode/0.9-ci-release`: PR/main firmware
  workflows with the stable checks `firmware-build`, `firmware-host-tests` and
  `firmware-package-tests`, an isolated `publish` job that creates the
  immutable `firmware-main-<sha12>` tag and a prototype pre-release, the
  `tools/firmware/publish.py` state machine, the isolated-environment
  `install.sh`/`install.ps1` setup wrappers and the prebuilt
  [installation guide](release-installation.md). See the
  [release plan](plans/0.9-firmware-ci-release.md) and
  [validation section 5](validation.md) for per-check evidence. No hosted
  Actions run, tag or Release has executed yet, and device installation
  (CI-T15) stays deferred and unverified.
- User priorities (2026-11-16): Seeed Studio XIAO ESP32S3 Sense and 32GB FAT32
  first. The acquired camera/revision is identified before configuration; current
  shipments may be fixed-focus OV5640 or OV3660, with OV2640 historical.
- Continuing choices: nominal 3.7V 1000mAh, about 1–2h, on-demand Wi-Fi,
  external charging of the unplugged pack, below-8kg owner's dog/chest harness,
  dry weather and basic protective housing. Exact fit measurements precede CAD.
- China required-kit BOM <CNY150 excluding SD/harness remains unquoted; larger
  cards are future qualification. No camera/audio feature or price is inferred.
- Baseline: segmented JPEG recording, Flutter, Rust and off-device EIS. The 72h
  retention goal is unverified on 32GB; measured useful quality/retention controls
  release claims. No automatic profile reduction to manufacture a pass.
- See [decision review](hardware-decision-review.md) and
  [PlatformIO support](platformio-support.md). The XIAO's onboard charger exists
  but is not the selected owner workflow; disconnect pack before USB servicing.

## Stack and gates

| Area | Proposed baseline | Before implementation |
| --- | --- | --- |
| Firmware | XIAO ESP32S3 Sense, ESP-IDF C++, PlatformIO board `seeed_xiao_esp32s3` | Exact base/Sense/sensor revisions, pinned compatible platform/SDK/compiler/camera, 8MB flash/8MB octal PSRAM detection, SPI SD/pin review and OTA fit |
| Power | Removable protected 3.7V 1000mAh pack through reviewed BAT input; separate charger; 1–2h goal | Actual board power/charger circuit, polarity, connector, cutoff/runtime and USB isolation; no assumed 5V boost |
| App | Flutter/Dart Android+iOS | Version pins, min OS/target SDK/plugins/test phones; qualified Dart implementation/review route |
| Backend | Rust, Axum/Tokio, SQLite, private filesystem | Rust/MSRV/crates/deployment image and quotas |
| Processing | FFmpeg with vid.stab | Build/filter/codec presence, license review, resource limits |
| Card | Genuine 32GB SDHC FAT32, Sense SPI socket | Exact models/allocation, measured bytes/latency, recovery/rollover and capacity/quality acceptance |

Wiring is **not approved**. Use hardware's candidate map only for review.
The supported PlatformIO environments now exist in `firmware/platformio.ini`:
`vdog_xiao_sense_proto` (ESP-IDF cross-build) and `native` (host tests);
package 0.2 supplied the exact platform/SDK/toolchain/camera pins and
working commands ([toolchain](toolchain.md)) and 0.3 still owes the reviewed
wiring. The current docs request identifies no authorized device/port or
flash, erase, format, OTA, or eFuse operation; package 0.2 ran no such
operation.

## Layout, commands and constraints

Future roots: `firmware/`, `app/`, `backend/`, `hardware/`, `contracts/`, `tools/`.
Requirements: `docs/specs/`; [plan](plans/implementation-plan.md). Working
commands from package 0.2 (run from repository root, verified 2026-11-19):
`pio run -d firmware -e vdog_xiao_sense_proto` (BUILD),
`pio run -d firmware -e vdog_xiao_sense_proto -t size` (BUILD size report),
`pio test -d firmware -e native` (HOST), and
`pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing`
(build-only; does not execute tests). Pinned toolchain, resolved versions,
partition budget and full command evidence: [toolchain](toolchain.md).
Remaining commands in [validation](validation.md) stay planned until their
packages exist. Stage 0.9 round 2 adds the release-tooling commands (documented
in [`tools/README.md`](../tools/README.md) and
[validation](validation.md) section 4): the host suite
`uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock
pytest tools/firmware/tests` (422 tests; qualified CPython 3.12.12 via `uv` —
the host `python3` is 3.14 and is not qualified), the offline
`python -m tools.firmware.validate_package <zip>` check, and
`python -m tools.firmware.publish ... --dry-run`, which performs no network
calls. `.github/workflows/firmware-pr.yml` and `firmware-main.yml` live on
`main` and their hosted runs, peeled tags and published pre-release assets
were verified against real GitHub data on 2026-11-28
([validation](validation.md) section 5, package 0.9 §8b); `actionlint` and
`pwsh` are absent here, so workflow linting stays the structural parse and the
Windows wrapper (`install.ps1`) remains unexecuted, and every device result
(CI-T15) stays unverified rather than passed. Official board support was
checked from upstream documentation and is now backed by a vdog cross-build
(BUILD/HOST evidence only); memory detection and all other hardware
qualification remain unperformed.

Non-secret configuration includes hardware revision, profile, SD budgets,
backend bind/database/storage/scratch roots, quotas and approved processing
presets. Define exact backend variable names during bootstrap. Tokens, Wi-Fi
passwords, TLS/signing keys and provisioning QR contents stay outside Git.

Constraints: authenticated pinned local TLS; scoped backend auth; no autoformat;
no mandatory cloud/subscription; no LTE/GPS/audio/realtime EIS in v1; shared
media/API v1; immutable originals. Existing MIT applies to covered repository
materials; review dependency/hardware distribution terms before release.

Use [decisions](decisions.md) for scope changes and AGENTS.md for specialist
review, worktrees, tests and delivery. Do not switch the user's branch. Docs-only
work needs no new worktree. Do not invent build/hardware evidence.
