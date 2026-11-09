# vdog implementation plan

Status: **NOT STARTED — documentation baseline only**, revised 2026-11-09. This is the
master backlog, not authorization to execute every stage in one assignment.
This plan describes future application work. Documentation already has a
review branch and PR; no application implementation, hardware operation,
purchase or deployment has been performed.

## Goal, background and scope

Build a low-cost open-source harness camera through three usable milestones:
standalone recorder, local Flutter app, optional self-hosted Rust processing.
Use classic AI-Thinker ESP32-CAM + OV2640, a nominal 3.7V 1000mAh pack,
about 1–2h per charge, 128GB, China procurement and production BOM <CNY150
excluding card/harness. Target automatic offline recording and 72h useful rolling
footage; validate capacity/quality before committing to any custom carrier PCB. Source
confidence and exclusions are in [product](../specs/product.md). Frameworks and
many hardware choices are engineering proposals, not measured facts.

Non-goals: LTE/GPS/audio, real-time onboard EIS, hazard/poison classifier, public
multi-tenant cloud, mandatory subscription, hardware fabrication in this docs
task, or unapproved changes to cost/SoC/card priorities. Preserve agent configuration
and unrelated work. Specs do not authorize contacting suppliers or flashing devices.

Authoritative inputs:
[profile](../project-profile.md), [architecture](../architecture.md),
[decisions](../decisions.md), [hardware](../specs/hardware.md),
[firmware](../specs/firmware.md), [media](../specs/media-format.md),
[interfaces](../specs/interfaces.md), [frontend](../specs/frontend.md),
[backend](../specs/backend.md), [security](../security.md),
[validation](../validation.md). Read the linked sections for the assigned package;
never infer a missing contract from another application's implementation.

The [hardware decision review](../hardware-decision-review.md) records the
2026-11-09 owner selections and replaces the earlier S3 baseline. Keep Wi-Fi
off during normal recording; physical local access enables a timed session.
The proposed runtime pass threshold is ≥1h, with 2h as the target; neither is
measured. Exact pack/power parts and actual board memory remain gated.

Charging is external after removing the whole camera and unplugging its pack;
no onboard charging/load-sharing or concurrent charging/recording is required.
The owner's dog is below 8kg; prioritize chest mounting and dry weather. Basic
protective housing still precedes wear. Dog/chest/harness measurements gate
final fit, not host contracts or bench firmware work. Larger-dog compatibility
and weather sealing require later validation.

## Execution contract for a 256k-context coding agent

Each package below is a small assignment boundary. Normally assign one package,
or 2–3 closely related packages with the same specialist and prerequisite set.
Do not give one agent the entire backlog and rely on a long context window.
Use versioned files and commits as durable state; context size is not evidence.

Before implementation the lead follows AGENTS.md: fetch the required remote base,
create its isolated planning worktree/branch, commit a self-contained assignment
plan, release the branch, and give the developer that exact branch/base/plan commit.
For a named update use its refreshed remote counterpart. A fetch/ref failure
blocks that implementation workflow rather than permitting a stale base. The
documentation-only exception applies to this documentation delivery.

Every assignment packet must contain:

1. Package IDs, goal, requirement IDs and observable acceptance criteria.
2. Exact dependency commit(s), plan path/commit, branch, base revision and worktree.
3. Only necessary spec sections, nearby source and existing fixtures; cite paths.
4. Exact writable paths/interfaces, non-goals and prohibited scope changes.
5. Ordered steps below, test commands with working directories, and required
   evidence level (HOST/BUILD/DEVICE/FIELD/QUOTE). Record unavailable checks.
6. Exact board/revision, pin map, firmware environment, device/port and authorized
   operations for any device assignment. No implied erase/format/eFuse authority.
7. Review role, expected artifacts, handoff format and stop/escalation conditions.

Expected handoff: local commit, exact branch/worktree/plan path, changed files,
criterion-by-criterion results, command/version evidence, matching reviewer
verdict and fixes, limitations and next dependency. Update package status and
decision register. Never label build-only tests as execution or host mocks as
hardware verification. Developers do not push. Lead independently assigns the
test engineer and performs final detached review from the exact handoff commit
in its own `.worktrees/` review checkout before accepted PR delivery. Follow
AGENTS.md's complete workflow, including fresh review after fixes.

Role routing: ESP32 C++ → esp32 developer/reviewer; Rust → Rust pair; Python
tools → Python pair. Flutter/Dart has **no existing matching profile**: package
0.8 establishes a qualified route before app work; do not substitute React/TS
because the UI is an app. Hardware design needs qualified electrical/mechanical
review distinct from firmware review. Test engineer independently verifies;
reporter writes only an exact assigned report path when needed.

Suggested handoff ledger entry (populate actual values during implementation):

```text
Package: 1.5 | Status: NOT STARTED / IN PROGRESS / REVIEW / VERIFIED / BLOCKED
Dependency commits: ... | Plan commit: ... | Branch/worktree: ...
Outputs and changed interfaces: ...
Commands + results + evidence level: ...
Review verdict/findings/fixes: ...
Remaining unverified criteria and blocking decision: ...
Handoff commit: ... | Next package: ...
```

## Dependencies and milestone gates

```text
0.1 source -> 0.2 toolchain + 0.3 pins + 0.4 cost + 0.5 quality/physical rubric
          -> 0.6 contracts -> 0.7 bench plan + 0.8 role route + 0.9 CI plan
1.1..1.13 recorder -> 1.14 quality/rate -> 1.15 powerfault/retention
                 -> 1.16 host EIS experiment -> 1.17 recorder signoff
2.1..2.15 local device/app -> 2.16 local-app signoff
3.1..3.14 backend + integration -> 3.15 optional device sync -> 3.16 signoff
4.1..4.10 physical/product release (gated, not a prerequisite for host work)
```

Schema/fixture and mock work can proceed independently after 0.6. Do not build
the entire app/backend before the recording quality/rate gate; it could conceal
a failed hardware premise. Early backend-independent FFmpeg experiments need
only captured files. Hardware design may proceed in parallel after recorder
feasibility, but all wear trials wait for the physical bench gate. Within a
stage the dependencies listed in each package override simple numeric order.

## Stage 0 — establish a reproducible, testable baseline

### 0.1 Reconcile research and freeze scope

- Inputs: product/source table, references and available user direction.
- Steps: enumerate confirmed/proposed/superseded choices; record unavailable
  earlier conversation context; select Stage 1 scope and no-network dependency.
- Outputs: updated decision register, stable PR IDs and milestone checklist.
- Acceptance: no P4/256GB/LTE/mandatory IMU silently introduced; cost is CNY and
  retention is separate from runtime. Missing source content remains unknown.

### 0.2 Qualify and lock toolchains

- Inputs: actual classic AI-Thinker ESP32-CAM PCB/chip/memory identity, hardware §2/8, project profile.
- Steps: verify installed tools without automatic upgrades; prove a compatible
  official PlatformIO/ESP-IDF/camera/compiler combination; select the original ESP32 `esp32cam` board definition
  with reviewed memory/partition settings; select Flutter/Dart/min OS/target SDK and Rust/MSRV/dependencies.
- Include an early flash-size budget for HTTPS/camera/SD plus two signed OTA
  slots: 4MB cannot inherit the earlier 16MB partition assumptions. A single
  large-app default does not qualify OTA. Preserve ESP-IDF unless separately decided.
- Outputs: version matrix, lockfile policy, firmware bootstrap assignment,
  planned `vdog_esp32cam_proto`/`native` environments and executable build commands.
- Acceptance: clean minimal cross-build with explicit flash/PSRAM settings;
  actual detected memory waits for 1.2. No arbitrary latest/fork fallback. If the
  official platform cannot support requirements, record a framework decision first.

### 0.3 Approve prototype electrical identity and wiring

- Inputs: acquired board/camera/SD schematics, hardware candidate pin table.
- Steps: map every pad/header/net/direction/rail/pull/reset; audit memory/strap/
  UART/boot/SD/flash-LED conflicts and physical-control availability; identify recovery path; review continuity/first-power plan.
- Outputs: `hardware/prototype-a/pin-map.csv`, assembly diagram, part identities
  and reviewed revision label; qualified electrical signoff.
- Reserve a reviewed physical local-access control; GPIO0 is camera XCLK after
  boot and cannot simply be a runtime button. Audit card/flash-lamp shared pins;
  no spare battery ADC or optional-IMU pins are assumed.
- Acceptance: no duplicate/reserved GPIO or unidentified camera rail; all board
  revisions explicit. Candidate docs become approved wiring only after review.

### 0.4 Build a cost evidence workbook/table

- Inputs: CNY149 engineering allocation and prototype/production separation.
- Steps: collect permitted dated CN quotes or mark quote requests pending;
  quantity/MPN/substitutes/taxes/freight/assembly/test/yield/contingency all explicit.
- Outputs: `hardware/bom.csv` plus redacted costing notes and variance to ceiling.
- Acceptance: card/harness excluded; device mount, power, battery and required
  external charger included on a stated required-kit/accessory basis, with no
  silent exclusion or double counting. Missing quotes remain UNVERIFIED; no purchase is implicit.

### 0.5 Define image-quality and physical acceptance rubrics

- Inputs: product §5 and validation §3, actual likely mounting geometry.
- Steps: choose harmless object scenes/distances/light/motion; agree readability
  scoring, coverage/drop/gap limits and frame-rate expectations before measurement;
  define thermal/mass/pack/mount criteria with qualified input. Use the actual
  below-8kg dog and chest-harness geometry as the first fit context, not an
  assumed universal weight percentage or every-small-dog requirement. Exact
  measurements precede final fit/CAD; they do not block host/bench work.
- Outputs: reproducible bench scene/test protocol and separately gated wear plan.
- Acceptance: objective enough to compare profiles without changing the standard
  after a poor result; no unsupported universal dog temperature/weight assumption.

### 0.6 Freeze media and API schemas and golden fixtures

- Inputs: complete media/API specs; no application implementation assumptions.
- Steps: create `contracts/media-v1/*.schema.json`, `contracts/device-v1.yaml`,
  `contracts/backend-v1.yaml`, synthetic valid/invalid fixtures and Python validator;
  define checksums over real tiny JPEGs, exact JSONL and manifest bytes.
- Outputs: contract files, fixtures, `tools/validate_contracts.py`, usage docs.
- Acceptance: boundary/overflow/time/CRC/hash/version/ID/errors/range/lease/upload
  cases covered; examples are valid test vectors or clearly labeled illustrative.
  OTA envelope is explicitly deferred to 2.10 rather than guessed by consumers.

### 0.7 Prepare card and bench operations safely

- Inputs: actual card models, host OS, board/port and desired authorized operations.
- Steps: document owner backup and identified-device FAT32 preparation; qualify
  128GB allocation/mount settings; current-limited power and cut/removal procedures;
  separate cross-build, build-only tests and hardware test commands.
- Outputs: actual card/preparation record and bench assignment with explicit
  flash/test/monitor scope and port; no generic destructive disk command.
- Acceptance: factory exFAT rejected without format; no unapproved device erase,
  battery wiring, eFuse, OTA or filesystem upload hidden inside checks.

### 0.8 Establish Flutter/Dart and hardware review ownership

- Inputs: current AGENTS/profile allowlists and stack matrix.
- Steps: lead defines qualified Flutter implementation/review ownership and
  hardware electrical/mechanical review; propose profile additions separately if
  needed, preserving existing permission/delegation semantics.
- Outputs: recorded role route and bounded app/bootstrap reviewer assignments.
- Acceptance: app work never assigned to a React role merely by name; no profile
  edits bundled into unrelated firmware work. Existing role permissions respected.

### 0.9 Establish repository checks and contribution boundaries

- Inputs: contract validator and selected bootstrap commands.
- Steps: define CI jobs by actual component presence; document fixture privacy,
  generated-file ignores and required review/test evidence; keep agent setup in
  AGENTS, application setup in README/profile.
- Outputs: minimal CI for available checks, not green placeholder jobs.
- Acceptance: checks actually execute; missing firmware/mobile/backend tests
  remain unavailable until their bootstrap packages, not passed by an empty suite.

## Stage 1 — standalone camera recorder

### 1.1 Bootstrap the firmware and portable core

- Depends: 0.2, 0.3, 0.6, 0.7. Writable: `firmware/`, relevant CI/profile docs.
- Steps: create pinned PlatformIO ESP-IDF structure, `vdog_esp32cam_proto` and `native`,
  component interfaces, board selection and version reporting; add minimal host
  harness. Keep camera/SD implementations separate from portable logic.
- Acceptance: root build/host commands work; unsupported boards fail clearly;
  no silently inherited PSRAM/flash defaults. Handoff BUILD/HOST separately.

### 1.2 Bring up board, memory and recovery interface

- Depends: 1.1 plus authorized identified hardware.
- Steps: verify rails/current, module marking, flash capacity, PSRAM size/mode,
  UART/programming-adapter recovery and exact GPIO setup; log sanitized identity.
- Outputs: board adapter, measurements and hardware identity record.
- Acceptance: detected flash/PSRAM match the actual classic board and build
  (documented baseline 4MB flash/4MB PSRAM, not an N16R8 assumption), no strap conflicts,
  reproducible boot. Failure blocks camera/SD wiring assumptions.

### 1.3 Capture and validate bounded JPEG frames

- Depends: 1.2. Writable: camera component and host fakes/tests.
- Steps: configure OV2640 JPEG/PSRAM; acquire/timestamp/validate/release; two-buffer
  starting point; bound frame/queue sizes; expose FPS/drop/invalid/memory counters.
- Acceptance: decodable frames/dimensions; fake driver tests cover every ownership
  path including queue full, oversize, init/allocation failure and shutdown.
  Actual FPS and memory are measured, not derived from requested settings.

### 1.4 Mount and qualify the SD adapter

- Depends: 1.2, 0.7; can parallel 1.3 in separate bounded assignments.
- Steps: explicit 1-bit SDMMC, pull-up/mount settings, no-format error paths,
  64-bit capacity counters, chunked read/write/sync/truncate abstraction.
- Acceptance: real FAT32 card operations, unsupported exFAT/no card/removal/readonly
  errors; measured latency. Do not create recording files before card validation.

### 1.5 Implement indexed segment writing

- Depends: 1.3, 1.4, frozen media fixtures.
- Steps: allocate clip/capture order, persist active.json before first frame,
  append JPEG then frame record, incremental CRC/SHA, ≤1s sync cadence,
  60s/size/frame-count cutovers and empty-clip disposal.
- Outputs: writer and portable fake-filesystem fault tests.
- Acceptance: files exactly match media v1, no JPEG padding/separators, true
  capture timestamps and no whole-segment buffer. Slow writes remain bounded.

### 1.6 Finalize, publish and enumerate clips

- Depends: 1.5.
- Steps: flush/close payload/index, finalize exact hashes/counts/duration, rename
  files, publish manifest last, journal catalog, expose bounded finalized pages;
  incremental cutover without queue expansion.
- Acceptance: incomplete clips never appear; sizes/hashes/IDs fixture-validated;
  selected-profile cutover gap measured against the proposed ≤2-frame target.

### 1.7 Recover partial files and damaged catalogs

- Depends: 1.5, 1.6.
- Steps: implement active.json recovery, maximal valid index prefix, mixed-name
  states, truncation only of active files, final-original quarantine and tombstone
  replay; healthy boot avoids full-card rehash.
- Acceptance: inject faults at each write/sync/rename/catalog step; valid prefix
  or explicit quarantine, no silent original mutation, no autoformat; damaged
  recovery bounded in memory and visibly slower than healthy boot if necessary.

### 1.8 Implement rolling pruning and storage accounting

- Depends: 1.6, 1.7.
- Steps: calculate actual 85% pool/allocated bytes/headroom, oldest capture_order
  eviction, transactional tombstones, no active/pinned/leased eviction, reclaim
  accounting and full-state/resume behavior. Host-test future pin/lease rules now.
- Acceptance: simulated tiny capacity forces repeated rollover, threshold and
  integer-boundary tests pass; no deletion race or double-counted protected bytes.
  Real 72h acceptance remains 1.15.

### 1.9 Add clock mapping and settings migration

- Depends: 1.6.
- Steps: monotonic boot timestamps, nullable UTC/uncertainty, new segment on
  correction/profile change; versioned NVS/revision CAS and safe migration;
  durable per-card ordering independent of RTC/FAT times.
- Acceptance: forward/backward UTC changes, reboot, absent clock, interrupted
  config write and unsupported settings tests. Existing manifests unchanged.

### 1.10 Add supervisor, power and visible status

- Depends: 1.3–1.9.
- Steps: boot/recovery/record/fault/shutdown transitions, bounded init retries,
  LED/button adapter, calibrated optional battery status, low-power close,
  radio-off boot; sanitize diagnostic counters and logs. Implement only portable
  supervisor/timer hooks with fake radio/activity handlers here; reserve the
  reviewed physical-control abstraction without provisioning/auth/network/OTA.
  Real local-access activation, authenticated idle handling, ownership claims and
  transfer/update cleanup integrate in 2.2/2.3/2.6/2.11 after recorder signoff.
- Acceptance: ten healthy offline cold boots, first persisted-frame latency,
  truthful card/camera/full status, no fake battery percent; no secrets in logs.
  Radio on/off transitions must not stop recording or reuse camera GPIO0.

### 1.11 Build desktop inspection and metrics tools

- Depends: 0.6, 1.6. Writable: `tools/`, tool tests/docs only.
- Steps: validate/export frame metadata, sample JPEGs, compute duration/gaps,
  allocated growth, percentiles and hash reports; preserve source files;
  accept selected explicit paths, not arbitrary recursive destructive operations.
- Acceptance: valid/invalid fixtures, malformed huge indexes and off-by-one
  timestamps detected; deterministic sanitized summaries. No large private footage
  committed. These tools enable app-independent recorder/EIS evaluation.

### 1.12 Integrate bounded recorder scheduling

- Depends: 1.3–1.10.
- Steps: connect producer/writer/supervisor with measured priorities/stacks,
  watchdog-friendly waits and drop policy; exercise SD stalls, allocation errors,
  removal/reinsertion and repeated start/recovery cycles.
- Acceptance: no buffer leak, deadlock, unbounded growth or hidden frame losses;
  defined fault recovery; heap/PSRAM/queue/stack/stall telemetry captured.

### 1.13 Complete portable and build regression coverage

- Depends: 1.12; independent of physical soak completion.
- Steps: run meaningful writer/recovery/prune/clock/settings tests and shared
  fixtures; pinned device cross-build and embedded test build-only checks;
  integrate CI with actual commands and sanitized outputs.
- Acceptance: required checks pass on exact handoff; matching ESP32 reviewer
  approves; no claim that compiled embedded tests executed on hardware.

### 1.14 Decide camera quality, throughput and capacity feasibility

- Depends: 1.11–1.13 and rubric0.5; requires DEVICE evidence.
- Steps: measure real mixed-scene profile matrix, JPEG distributions, achieved
  FPS/gaps/blur/object visibility, SD stalls, allocated bytes/hour and power;
  project 72h with reserve/protection/headroom; choose supported/default profile.
- Acceptance: agreed readability and capture criteria plus sustainable rate
  near ≤3.0Mbit/s total. If incompatible, stop dependent feature expansion and
  present measured tradeoffs for a scope decision; no silent downgrade/SoC switch.

### 1.15 Validate power faults and real 72h retention

- Depends: 1.14, approved bench power/card procedure.
- Steps: ≥30 controlled cut cases across write/finalize/prune; inspect all prior
  data damage; run ≥72h plus enough rollover on priority 128GB card; sample files
  throughout and verify recorded duration, quality and gaps. Repeat on a second
  qualified card model before broad compatibility claims.
- Acceptance: T-05–09 evidence with actual profile/card/commit; any corruption
  documented and blocking defects fixed/re-reviewed. External bench power is
  allowed; report battery runtime separately, never infer it from this soak.

### 1.16 Run early off-device stabilization experiment

- Depends: 1.11, 1.14 samples; no app/backend required.
- Steps: collect20–30 representative consented clips, verify FFmpeg/vid.stab
  availability, use two-pass optical stabilization and matched original/export
  comparison; record crop, detail, distortion and time; Gyroflow research optional.
- Acceptance: evidence supports usefulness or rejection; originals unchanged;
  no assumption that blur/occlusion can be repaired or IMU is now required.

### 1.17 Sign off recorder milestone

- Depends: 1.13–1.16 plus relevant hardware gates.
- Steps: update build/card/profile/recovery docs, known limits and status ledger;
  matching review/fix loop, independent test-engineer checks, lead detached review.
- Acceptance: recorder criteria PR-01–03,05–06/FW-01–05 have explicit evidence;
  PR-04 production BOM remains UNVERIFIED until 4.8/HW-G5. Early quote feasibility
  is not a production-cost pass. Remaining physical/runtime gates are labeled.
  Stage 1 is usable offline with documented manual SD inspection.
  Stop here if recorder milestone is the assignment boundary.

## Stage 2 — secure local Wi-Fi and Flutter application

### 2.1 Bootstrap Flutter app, models and test doubles

- Depends: 0.2,0.6,0.8 and recorder feasibility1.14.
- Steps: create pinned app/platform projects, typed models generated/checked
  against contracts, repository interfaces, fake device and fixture loader,
  local settings DB migrations and OS secret-store adapter.
- Acceptance: analyze/unit/widget tests run; secrets absent from DB/logs; startup
  works without backend or camera. No screen implies implemented hardware status.

### 2.2 Implement device provisioning and physical ownership

- Depends: 1.17,0.6, authorized provisioning scope.
- Steps: unique cert/key/QR/AP/setup secret, phone-token hashes, 120s window,
  ALREADY_OWNED, revocation and deliberate reset gestures; private factory artifacts.
- Acceptance: wrong secret/closed window/owned/reset/last-token cases and no
  default credential; no production eFuse writes included. Document physical risk.

### 2.3 Implement pinned HTTPS and device control routes

- Depends: 2.2,1.9/1.10.
- Steps: bounded server/session config, auth on all routes, capabilities/status/
  settings/time, revision conflict/errors, mDNS hint and sanitized logs.
- Initially allow one TLS connection total; pause preview before a control or
  download uses it. Qualify any concurrency expansion against recording and heap.
- Acceptance: good and wrong certificate/token/body/rate cases; offline recording
  continues during reconnect/auth failure; capabilities only advertise working features.

### 2.4 Implement phone permissions, QR and Wi-Fi pairing

- Depends: 2.1–2.3.
- Steps: instruct physical local-access activation first (no radio-off remote
  wake/discovery), then platform conditional permissions, QR validation, OS AP join/manual
  fallback, cert pin before secret, ownership claim and secure token storage;
  discover same ID/pin on router/hotspot without silent network takeover.
- Acceptance: real Android+iOS deny/grant/internetless/stale QR/revoked/owned
  cases; accessible recovery UI and no accept-all certificate workaround.

### 2.5 Implement device dashboard and truthful catalog

- Depends: 2.3,2.4.
- Steps: status polling with backoff, state/fault/card/time uncertainty display,
  cursor catalog, source/local/backend availability distinction and pagination.
- Acceptance: no-card/full/recovery/unknown-clock/offline fixtures; no library
  item claimed downloaded simply because present on SD. Bound list memory.

### 2.6 Implement leases and Range serving on firmware

- Depends: 1.8,2.3.
- Steps: serialize lease/prune, two-lease limit,5min TTL/renewal pressure checks,
  one transfer, bounded read chunks/ETag/Range/If-Match; expiry abort and close.
- Acceptance: active prune races, denial/expiry during response, malformed ranges,
  storage pressure and auth; no open connection can hold a clip indefinitely.

### 2.7 Implement resumable verified phone downloads

- Depends: 2.5,2.6.
- Steps: exact manifest retrieval, local quota reservation, temp files, per-file
  checkpoints, lease renewal, Range+If-Match resume, complete SHA validation,
  atomic local completion and cancellation/restart cleanup.
- Acceptance: every interrupt phase, expired lease/410, wrong ETag/hash, disk full
  and process restart; only all-files-verified bundles enter playable library.

### 2.8 Implement indexed original JPEG playback

- Depends: 2.1,2.7,media fixtures.
- Steps: isolate index parser, bounds/CRC checks, timestamp binary search, bounded
  random reads/decode,≤3 decoded images, play/pause/seek/dispose and gap indicators.
- Acceptance: timing/drops/seek/background/memory-pressure fixtures on Android+iOS;
  no dependence on native AVI/MJPEG support or backend transcode for original review.

### 2.9 Implement preview and recording priority

- Depends: 2.3,2.5,qualified recorder metrics.
- Steps: one-client≤2FPS authenticated multipart preview, no slow-client camera
  ownership, app stale-frame age and stop/retry flow, workload shedding.
- Acceptance: recording+preview and recording+download stay within qualified
  recording metrics; shed preview first. Display/live drops are not captured-frame drops.

### 2.10 Freeze OTA envelope and trust policy

- Depends: 0.2,1.17; before OTA implementation.
- Steps: prove dual slots fit measured classic-board flash (documented 4MB) with
  actual signed-binary sizes and headroom; if not, block OTA for a scope decision.
  Select SDK-supported signed
  image/envelope encoding and exact signature coverage, hardware/version/key IDs,
  update power preconditions, key custody and development test-key separation.
- Outputs: `contracts/ota-v1.json`, partition/trust docs, positive/negative vectors.
- Acceptance: qualified security/ESP32 review; no custom crypto or unapproved
  production security-state changes. API spec's deferred encoding now resolved.

### 2.11 Implement OTA staging and rollback on device

- Depends: 2.3,2.10.
- Steps: close recording, bounded streamed inactive-slot write/verification,
  staging timeout/cancel/reject recovery, reboot health validation and SDK rollback.
- Acceptance: all T-14 negative/power/failed-boot cases; pre-reboot failure resumes
  current recording; identity/settings/card preserved; no unsigned image activated.

### 2.12 Implement app settings, clock and OTA UI

- Depends: 2.4,2.5,2.11.
- Steps: supported-profile controls, CAS conflicts, write-only Wi-Fi secrets,
  reconnect after network changes, UTC confidence, signed-update compatibility,
  pause warning/progress/reconnect/rollback result and recovery instructions.
- Acceptance: stale settings not blindly retried, secrets never redisplayed,
  failed update not reported complete, device auth revalidated after reboot.

### 2.13 Implement local library lifecycle and accessibility

- Depends: 2.7,2.8.
- Steps: local-only deletion/confirmation, quota/temp cleanup, local status DB
  migrations, screen-reader labels, text scaling, noncolor fault cues, localization
  scaffolding (proposed English/Simplified Chinese).
- Acceptance: local deletion never deletes SD/backend, no background completion
  guarantee contrary to OS restrictions, essential states accessible on test phones.

### 2.14 Integrate mobile lifecycle and offline recovery

- Depends: 2.4–2.13.
- Steps: foreground/background/network switches, AP no-internet, app force-close,
  token revocation/reset/cert replacement and simultaneous recorder load.
- Acceptance: T-10–14 matrix with real OS versions/devices; no lost queue state,
  plaintext credentials, stale successful status or recorder network dependency.

### 2.15 Complete app/device automation and user setup guide

- Depends: 2.14.
- Steps: contract/fake-server/widget/integration tests and firmware regressions,
  documented build/install/platform setup; pairing/download/play/update walkthrough.
- Acceptance: working commands/CI, qualified Flutter and ESP32 reviews for their
  respective changes, known OS/background limitations stated with primary sources.

### 2.16 Sign off local-app milestone

- Depends: 2.15.
- Steps: independent tests and lead detached review from exact handoff, update
  README/profile/decision ledger and record permission/OTA/retention regressions.
- Acceptance: PR-07,08,10,12 plus unchanged recorder criteria explicitly evidenced;
  nearby owner can review originals with no backend. Stop at this milestone if assigned.

## Stage 3 — optional Rust self-hosted storage and processing

### 3.1 Bootstrap service, worker and deployment configuration

- Depends: 0.2,0.6,1.14. Writable: backend and its CI/docs.
- Steps: pinned Rust workspace, Axum/Tokio layers, validated configuration,
  localhost defaults, private storage/scratch roots, SQLite migrations, health
  endpoints and deployment example with persistent volumes/no secret defaults.
- Acceptance: format/clippy/test and startup/invalid-config/readiness tests;
  source structure/API/domain/storage/worker separate. Deployment is not automatic.

### 3.2 Implement scoped token auth and device registration

- Depends: 3.1.
- Steps: one-time admin bootstrap CLI, hashed random tokens, owner/device-upload
  scopes, revoke, device registration, per-resource authorization and rate limits.
- Acceptance: no unauthenticated media/public signup; scoped camera cannot list
  others or submit jobs. Backend registration never grants local camera ownership.

### 3.3 Implement database/blob transaction model

- Depends: 3.1,media contract.
- Steps: upload reservations/offsets, clips/files, events/pins, jobs/attempts and
  derivatives tables/indexes; DB migration/rollback policy; staged-file publication
  journal and boot reconciliation, path/symlink defenses.
- Acceptance: crash tests at DB/blob boundaries, no visible clip missing files,
  no unknown file deleted by cleanup and original identity collision enforced.

### 3.4 Implement resumable upload initialization and chunks

- Depends: 3.2,3.3.
- Steps: decode bounded manifest_base64url preserving bytes, validate declared
  quota/device/schema, Idempotency-Key, PATCH1MiB checksum/offset, HEAD authoritative
  offsets, sync-before-ack, expiry/cancel/restart reconciliation.
- Acceptance: duplicate/ambiguous response/wrong offset/hash/body size/reservation
  race/expiry tests; no arbitrary archive or filename accepted.

### 3.5 Validate and commit originals

- Depends: 3.4,shared fixtures.
- Steps: stream file hashes, bounded index and JPEG decoding/CRC/dimensions/time
  checks in isolated validator, exact lengths, durable publication/dedup, quarantine.
- Acceptance: T-04/T-15 hostile/corrupt fixture matrix; commit only after validation,
  retries return one identity; all three original files byte-identical to source.

### 3.6 Implement catalog and authorized retrieval

- Depends: 3.5.
- Steps: device-scoped clip catalogs, unknown UTC/recovery flags, Range/ETag,
  correct content types, owner auth and backend availability metadata.
- Acceptance: pagination/eviction/error cases, cross-scope denial, no public static
  directory, originals streamed with bounded memory and verified source hashes.

### 3.7 Integrate app self-hosted upload flow

- Depends: 2.16,3.2–3.6; qualified Flutter route.
- Steps: HTTPS base URL/owner token secure configuration, device registration,
  upload only locally verified originals, persistent offsets/HEAD resume, network
  choice while moving from camera AP to internet, truthful durable commit status.
- Acceptance: backend outage/auth/quota/cancel/restart never blocks local review;
  local camera token never sent to server; whole-file equality after resumed ingest.

### 3.8 Implement durable job lifecycle

- Depends: 3.3,3.5.
- Steps: approved type/preset schema, dedup key, queue/one-worker lease/heartbeat,
  cancel_requested, interrupted recovery, bounded retry attempts and typed failures.
- Acceptance: kill/restart/cancel at each transition, no duplicate output/success
  before durable validation, exact wire states and no fabricated progress.

### 3.9 Implement sandboxed timestamp-aware MP4 export

- Depends: 3.8,FFmpeg build/license verification and golden timing fixtures.
- Steps: bounded private frame extraction, argv-only FFmpeg concat input with real
  durations, allowlisted codecs/presets, nonroot/no network/resources/timeouts,
  output validation/hash/metadata and authorized derivative retrieval.
- Acceptance: mobile-playable H.264 MP4 on support matrix, timing tolerance from
  media spec, no upscaling/invented source FPS, original hashes unchanged;
  malformed input cannot escape sandbox or leave children/scratch indefinitely.

### 3.10 Implement two-pass optical stabilization

- Depends: 3.9 and early experiment1.16.
- Steps: capability-check vidstabdetect/vidstabtransform, fixed approved parameters,
  analysis artifacts private, transform + MP4 output, crop/filter/version metadata,
  no_IMU preset and explicit unsupported-filter errors.
- Acceptance:20–30 clip evaluation for visibility/crop/distortion, comparison
  against plain transcode, originals preserved; EIS rejected/degraded visibly
  when unsupported or harmful. No promise to recover blur/occlusion.

### 3.11 Implement manual events and protected local storage

- Depends: 1.8,2.3,3.6 for device/backend; additionally 2.16 for the Flutter UI.
  Use separate bounded ESP32/Rust/app assignments.
- Steps: atomic1–10clip device pin by event UUID, overlap reference counts,
  8GB cap inside pool, quota/evicted errors; server event association distinct
  from device acknowledgment; app offline-pending/manual-event UI.
- Acceptance: quota races/no partial pin/no double count, unpin overlaps, all
  pinned/leased full-state; retention re-tested at maximum advertised protection.
  Automatic impact/danger detection remains excluded.

### 3.12 Implement optional notifications

- Depends: 3.8,3.11.
- Steps: select one owner-opted transport and threat model, store credentials
  securely, durable outbox/dedup/backoff/expiry, generic messages and delivery state.
- Acceptance: outage/retry/duplicate handling and opted-off behavior; labels only
  manual event/job state, no assertion of danger or guaranteed offline delivery.
  Provider-specific implementation needs its own concrete contract/assignment.

### 3.13 Add operator lifecycle, quotas and backup/restore

- Depends: 3.4–3.12.
- Steps: upload/scratch/global quotas, free-floor admission, abandoned cleanup,
  configurable original/derivative retention with protected metadata, consistent
  DB/blob backup, restore, token rotation and safe logs/metrics.
- Acceptance: diskfull/readonly/restart/restore tests, no quota bypass by many
  reservations, no orphan original deletion, end-to-end restored hashes/events/jobs.

### 3.14 Integrate app jobs, derivatives and backend tests

- Depends: 3.7–3.13.
- Steps: typed polling/backoff/cancel, download derivatives and source linkage,
  distinguish original/stabilized/transcoded UI, rebuild-on-restart states;
  add API integration/adversarial tests and selfhost quickstart.
- Acceptance: T-15–17/T-21 with real supported phone playback; app local features
  work with backend down. Qualified Rust/Flutter reviews and working CI.

### 3.15 Add optional direct device sync only after a resource gate

- Depends: 3.14 and new qualified simultaneous-load measurements.
- Steps: only within an owner-opened local-access session, opt-in HTTPS endpoint/
  scoped upload token, finalized-file lease and same
  resumable protocol, one bounded transfer, backoff/throttling/low-power pause,
  durable ack metadata outside original files.
- Acceptance: recording remains within qualified FPS/gap/heap/power limits under
  reconnect/upload; no admin token on device, no deletion-on-upload, no v1
  dependency. Skip with a recorded decision if ESP32-CAM resources do not permit it.

### 3.16 Sign off self-hosted processing milestone

- Depends: 3.14;3.15 only if enabled.
- Steps: independent host/integration/device regressions, exact-commit detached
  review, update deployment/backup/privacy/filter/license docs and limitations.
- Acceptance: PR-09/12/14/15 with evidence; no mandatory vendor service;
  original preservation and truthful processing states demonstrated.

## Stage 4 — wearable hardware and public release

### 4.1 Select removable pack, regulation and external charger

- Depends:1.14 measured load and0.5 physical limits.
- Steps: choose exact protected nominal 3.7V 1000mAh pack, keyed service
  connector/strain relief, reviewed switch/shutdown/regulator/undervoltage path,
  and compatible separate charger. No onboard charging/load sharing. Separate
  programming/bench supply from pack charging and prevent back-feed.
- Acceptance: schematic/pack/charger compatibility, polarity, peak/cutoff and
  disconnect/reconnect review; external charger included in kit cost; runtime/
  mass/cost recorded. No recording-while-charging implementation required.

### 4.2 Design carrier or integration assembly after feasibility

- Depends:1.17,4.1,quotes0.4.
- Steps: retain the qualified ESP32-CAM/OV2640 assembly; design a carrier or
  documented wiring assembly for power/control/recovery if needed, with antenna
  clearance, connector/test points and revision labels. Review schematic/layout/
  ERC/DRC for any carrier. A bare-MCU replacement is a separate scope decision.
- Acceptance: complete fabrication review and CNY variance; separate explicit
  fabrication decision. A code build does not qualify a PCB.

### 4.3 Design enclosure, mount and damping

- Depends:0.5,4.1/4.2 geometry.
- Steps: create a basic dry-use housing and chest mount for the actual below-8kg
  dog/harness measurements: insulated electronics, restrained removable pack,
  secured connector, strain relief, rounded contact surfaces, lens angle/clearance,
  antenna space and thermal path. Make pack disconnection serviceable off-harness.
- Acceptance: CAD/assembly review and basic housing before wear. Weather sealing
  is later work; no IP/drop/breakaway rating. Larger dogs need separate geometry/
  angle/fit tests. Harness excluded, device housing/mount/damping included in BOM.

### 4.4 Bring up revised electronics

- Depends:approved fabrication4.2 and identified authorized prototype.
- Steps: continuity/short/current-limited rails, camera/card/USB/memory, programming
  and recovery, revised board adapter and compatibility identity.
- Acceptance: hardware review plus repeat T-02–09/T-13/T-14 as affected; regression
  evidence before wear. Do not reuse base-board success as carrier-board verification.

### 4.5 Characterize runtime and thermal behavior

- Depends:4.3,4.4.
- Steps: recording-only/timed-Wi-Fi runtime, peaks, pack unplug/reconnect and
  qualified bench-power isolation, pack/regulator temperatures in actual dry-use
  housing, shutdown and optional battery calibration. Separately qualify external
  charging of the disconnected pack; no in-camera charging-under-load test.
- Acceptance: ≥1h useful recording and target 2h on the selected 1000mAh pack,
  reporting radio-off and timed-radio workloads separately. This is the proposed
  interpretation of the owner goal, not measured evidence. T-18 against prior
  agreed physical limits, measured mass/runtime
  published separately from 72h retention; no charging while worn.

### 4.6 Conduct gated supervised mounting trials

- Depends:4.5 pass and reviewed trial procedure/consent.
- Steps: first fit on the actual below-8kg dog's chest harness, then controlled
  dry-weather movement; assess ground view/fur/straps/tilt, leg clearance, rubbing,
  warmth, stability and comfort in the actual housing; stop/revise on problems.
- Acceptance: T-19 with specific assembly/dog context and qualified review;
  no unsupported claim of suitability for all dogs or three-day continuous wear.

### 4.7 Prepare factory provisioning and production test

- Depends:4.4,2.10/2.11,approved key-custody policy.
- Steps: per-unit identity/cert/QR, programming and version binding, power/camera/
  SD/radio checks, serial/lot tracking without public owner data, recovery and
  rejected-unit handling; optional irreversible security provisioning separately.
- Acceptance: small pilot yields/test duration/cost captured, no duplicated keys
  or secrets in source; repeatability demonstrated on identified units.

### 4.8 Close production BOM and design release package

- Depends:4.2–4.7,updated supplier evidence.
- Steps: all fitted parts+assembly/test/yield/contingency quotes, alternatives
  and quantities; schematic/layout/Gerber/BOM/placement/enclosure/pin/assembly
  sources; license/notices and distribution obligations reviewed.
- Acceptance: actual quoted base BOM <CNY150 or explicit failed target/decision;
  production-ready claim only after HW-G5, never inferred from CNY149 allocation.

### 4.9 Publish reproducible installation and owner documentation

- Depends:accepted software/hardware revision.
- Steps: tested clean-clone build/install, supported card prep, assembly, pairing,
  recording status, unmount/unplug/external-charge/reconnect, small-dog chest fit,
  dry-weather/basic-housing limits, privacy/storage, review/export, update/recovery,
  runtime, maintenance, backup and troubleshooting; distinguish prototype/production.
- Acceptance: another builder follows docs with no chat dependency; screenshots
  and commands match actual version; secrets/large outputs not in repository.

### 4.10 Final release review and handoff

- Depends:4.8/4.9 and scope-appropriate milestones.
- Steps: requirement/evidence audit, independent reviewer/test engineer outcomes,
  lead exact-commit detached checks, reproducible artifacts/hashes/known issues.
- Acceptance: no open confirmed defect, no absent evidence presented as pass;
  push/create PR only via lead when delivery requires it; no merge without user
  direction. Public artifact deployment/publication follows its authorized scope.

## Required check commands and documentation maintenance

Use the concrete commands and working directories in [validation §4](../validation.md).
Before each assignment, replace future-command placeholders with commands proven
by its prerequisites. If tools/hardware are missing, report `UNVERIFIED`; do not
install/update tools or flash another device to manufacture a green result.

Every package updates the relevant component setup/contracts and this ledger;
root README changes only for product/setup/usage/status. Durable new architecture
decisions go in docs/decisions, optional sanitized reports under exact assigned
`docs/tasks/<task>-report.md`. Large footage/metrics dumps stay outside Git.

## Current Stage 0 status — audited 2026-11-09

**Stage 0 is not complete.** The owner-facing product choices and written scope
are settled; technical preflight has not been demonstrated. Documentation review
and ad-hoc documentation checks do not replace the outputs below.

| Package | Status | Evidence / remaining output |
| --- | --- | --- |
| 0.1 Scope | Documented and reviewed | Product/decision records reflect the confirmed board, battery, runtime goal, Wi-Fi, external charging, chest fit and dry-weather scope |
| 0.2 Toolchains | Not qualified | Proposed stack only; no pinned compatible environments, lockfiles or minimal cross-build evidence |
| 0.3 Wiring | Candidate only | Reference pin table exists; actual PCB identity, reviewed pin-map.csv/assembly diagram and electrical signoff absent |
| 0.4 Cost | Allocation only | CNY149 ceiling exists; exact-part BOM and dated supplier quote evidence absent |
| 0.5 Acceptance rubrics | Draft | General test method exists; repeatable scenes/scoring, measurable limits and reviewed physical procedure not frozen |
| 0.6 Contracts | Written baseline only | Media/API prose exists; schemas, OpenAPI files, real golden fixtures and validator absent |
| 0.7 Card/bench | Planned, unverified | FAT32/no-autoformat policy exists; actual card/preparation and authorized identified-device bench record absent |
| 0.8 Role ownership | Not established | Flutter/Dart and qualified hardware implementation/review routing still needs a concrete recorded assignment |
| 0.9 Repository checks | Not established | Ad-hoc docs checks passed; no persistent contract validator or CI workflow exists |

The next implementation assignments are 0.2 toolchain qualification and 0.6
contract/schema/fixture work, with 0.3/0.4 actual-part and wiring/cost preparation
in parallel. Hardware-dependent acceptance waits for identified parts and an
appropriate authorized bench assignment. Stage 1–4 application/hardware work
remains unexecuted; do not report the recorder or full Stage 0 as complete.
