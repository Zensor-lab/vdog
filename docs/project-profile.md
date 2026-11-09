# Project facts for implementation agents

This tracked profile holds shared facts because the starter ignores `.agent/`.
The local `.agent/PROJECT.md` points here. Operating rules remain in
[AGENTS.md](../AGENTS.md).

## Product and current state

- vdog: affordable open-source dog camera, local recording, owner-controlled
  footage, optional self-hosted processing; for owners, builders and self-hosters.
- Current state: agent starter and documentation only. No firmware/app/backend,
  application dependencies, CI or hardware designs. No application checks passed.
- User priorities (2026-11-09): classic AI-Thinker ESP32-CAM + OV2640, nominal
  3.7V 1000mAh battery, about 1–2h per charge; mainly SD recording with Wi-Fi
  when needed. 128GB/China procurement/<CNY150 excluding SD/harness remain.
  See [decision review](hardware-decision-review.md); S3 is now an alternative.
- Confirmed use: chest harness for the owner's small dog reported below 8kg,
  dry weather; exact weight/chest/harness measurements before final fit. Remove the
  whole camera, unplug pack and charge externally; no onboard charge/load sharing.
  Basic protective housing before wear; weather sealing and larger-dog fit later.
- Baseline: Wi-Fi only, automatic segmented MJPEG, target 72h retained footage
  while powered, Flutter app and Rust backend, off-device EIS, optional IMU.

## Stack and gates

| Area | Proposed baseline | Before implementation |
| --- | --- | --- |
| Firmware | Classic AI-Thinker ESP32-CAM + OV2640, ESP-IDF C++, PlatformIO | Exact PCB/chip revision, platform/framework/compiler/camera versions, detected flash/PSRAM, classic pin map, dual-slot OTA fit |
| Power | Removable protected 3.7V 1000mAh 1S pack, regulation; separate external charger; target 1–2h | Exact pack/charger ratings, keyed connector/polarity, regulator/shutdown, measured load/runtime |
| App | Flutter/Dart Android+iOS | Version pins, min OS/target SDK/plugins/test phones; qualified Dart implementation/review route |
| Backend | Rust, Axum/Tokio, SQLite, private filesystem | Rust/MSRV/crates/deployment image and quotas |
| Processing | FFmpeg with vid.stab | Build/filter/codec presence, license review, resource limits |
| Card | Genuine 128GB, prepared FAT32 | Actual models, preparation/allocation size, latency/corruption qualification |

Wiring is **not approved**. Use hardware's candidate map only for review. No
supported PlatformIO environments exist yet; planned names are `vdog_esp32cam_proto`
and `native`. Before firmware delegation, package 0.2 supplies exact versions/
environments and 0.3 supplies reviewed wiring. The current docs request identifies
no authorized device/port or flash, erase, format, OTA, or eFuse operation.

## Layout, commands and constraints

Future roots: `firmware/`, `app/`, `backend/`, `hardware/`, `contracts/`, `tools/`.
Requirements: `docs/specs/`; [plan](plans/implementation-plan.md). Planned commands
are in [validation](validation.md); currently only documentation/Git inspection
exists. Update this file with working install/build/test commands after bootstrap.

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
