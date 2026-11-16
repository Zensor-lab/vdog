# Project facts for implementation agents

This tracked profile holds shared facts because the starter ignores `.agent/`.
The local `.agent/PROJECT.md` points here. Operating rules remain in
[AGENTS.md](../AGENTS.md).

## Product and current state

- vdog: affordable open-source dog camera, local recording, owner-controlled
  footage, optional self-hosted processing; for owners, builders and self-hosters.
- Current state: agent starter and documentation only. No firmware/app/backend,
  application dependencies, CI or hardware designs. No application checks passed.
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

Wiring is **not approved**. Use hardware's candidate map only for review. No
supported PlatformIO environments exist yet; planned names are `vdog_xiao_sense_proto`
and `native`. Before firmware delegation, package 0.2 supplies exact versions/
environments and 0.3 supplies reviewed wiring. The current docs request identifies
no authorized device/port or flash, erase, format, OTA, or eFuse operation.

## Layout, commands and constraints

Future roots: `firmware/`, `app/`, `backend/`, `hardware/`, `contracts/`, `tools/`.
Requirements: `docs/specs/`; [plan](plans/implementation-plan.md). Planned commands
are in [validation](validation.md); currently only documentation/Git inspection
exists. Update this file with working install/build/test commands after bootstrap.
Official board support has been checked from upstream documentation; no vdog
cross-build, memory detection or hardware qualification has been performed.

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
