# Project facts for implementation agents

This tracked profile holds shared facts because the starter ignores `.agent/`.
The local `.agent/PROJECT.md` points here. Operating rules remain in
[AGENTS.md](../AGENTS.md).

## Product and current state

- vdog: affordable open-source dog camera, local recording, owner-controlled
  footage, optional self-hosted processing; for owners, builders and self-hosters.
- Current state: agent starter and documentation only. No firmware/app/backend,
  application dependencies, CI or hardware designs. No application checks passed.
- User priorities: ESP32-S3 +128GB; China procurement; hardware below CNY150
  excluding SD/harness. See product spec for decision confidence.
- Baseline: Wi-Fi only, automatic segmented MJPEG, target 72h retained footage
  while powered, Flutter app and Rust backend, off-device EIS, optional IMU.

## Stack and gates

| Area | Proposed baseline | Before implementation |
| --- | --- | --- |
| Firmware | WROOM-1-N16R8, ESP-IDF C++, PlatformIO | Exact board revision, platform/framework/compiler/camera versions, N16R8 memory setup, pins and partitions |
| App | Flutter/Dart Android+iOS | Version pins, min OS/target SDK/plugins/test phones; qualified Dart implementation/review route |
| Backend | Rust, Axum/Tokio, SQLite, private filesystem | Rust/MSRV/crates/deployment image and quotas |
| Processing | FFmpeg with vid.stab | Build/filter/codec presence, license review, resource limits |
| Card | Genuine 128GB, prepared FAT32 | Actual models, preparation/allocation size, latency/corruption qualification |

Wiring is **not approved**. Use hardware's candidate map only for review. No
supported PlatformIO environments exist yet; planned names are `vdog_s3_proto`
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
