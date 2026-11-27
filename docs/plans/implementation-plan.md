# vdog implementation plan

Status: **IN PROGRESS — 0.2 qualified; 0.9 implemented on
`opencode/0.9-ci-release`, hosted run pending**, revised 2026-11-21. This is the
master backlog, not authorization to execute every stage in one assignment. The
minimal firmware and portable host tests exist with BUILD/HOST evidence.
Recording, device operation and every hosted CI/tag/Release result are not
delivered merely by this plan or by the branch implementing it.

## Goal, background and scope

Build a low-cost open-source harness camera through three usable milestones:
standalone recorder, local Flutter app, optional self-hosted Rust processing.
Use Seeed Studio XIAO ESP32S3 Sense and **32GB FAT32 first**, retaining nominal
3.7V 1000mAh, about 1–2h per charge, China sourcing and required-kit BOM <CNY150
excluding SD/harness but including external charger. The camera is the acquired
Sense revision's sensor; current shipments may be fixed-focus OV5640/OV3660,
with OV2640 historical. No audio capture despite the onboard microphone.

Automatic offline recording is primary. The 72h retained-footage goal is
unverified on 32GB: nominal capacity permits only ~0.84Mbit/s total before
pins/headroom, so useful JPEG quality may prevent it. Report actual retention,
never silently lower image quality and obtain an explicit decision if the
combination fails. Source confidence is in [product](../specs/product.md).

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

The [hardware review](../hardware-decision-review.md) records the 2026-11-16
board/card update; [PlatformIO support](../platformio-support.md) verifies the
upstream board/framework metadata, not a project build. The new base/Sense
revision, SPI socket, sensor, 8MB flash/8MB octal PSRAM and USB/BAT wiring must
be qualified; old classic/128GB/5V-boost/SDMMC assumptions are superseded.

Keep Wi-Fi off except timed physical access; one TLS connection until qualified.
Proposed battery minimum is 1h/target 2h, unmeasured. Remove camera/unplug pack
for external charging. Stock XIAO charging hardware exists: disconnect pack
before USB service unless isolation is reviewed; no additional charge/load-sharing
function is required. The owner's below-8kg dog/chest/dry-use/basic-case choices
remain; final-fit measurements do not block host/bench work. Weather sealing and
larger-dog fit remain future validation.

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
          -> 0.6 contracts -> 0.7 bench plan + 0.8 role route
0.2 toolchain -> 0.9.1..0.9.16 PR builds + tagged main releases + installation bundle
                 (parallel to 0.6; its later checks join CI when implemented)
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

- Inputs: acquired XIAO base/Sense/sensor identities, hardware §2/8, profile and
  the upstream PlatformIO check. Board ID is `seeed_xiao_esp32s3` with ESP-IDF.
- Steps: inspect installed tools without automatic upgrades; qualify a compatible
  official platform/SDK/compiler/camera combination. Official 8.0.0 is a candidate,
  not a passed build. Set IDF flash/octal-PSRAM/USB options explicitly; Arduino
  `qio_opi`/partition defaults are not IDF configuration. Lock component versions.
- Include an early 8MB-flash budget for camera/SPI SD/HTTPS, identity/NVS and two
  signed OTA slots with headroom; do not inherit classic 4MB, N16R8 or Plus layouts.
- Outputs: version/lockfile matrix, bootstrap assignment, `vdog_xiao_sense_proto`
  and `native` definitions and working commands; freeze Flutter/Dart/OS and Rust
  compatibility separately. No framework/fork switch solely for convenience.
- Acceptance: clean minimal cross-build, explicit memory/partition config and
  actual dependencies; physical memory detection waits for 1.2. An upstream board
  entry alone is not complete. Report compatibility failure before changing scope.

### 0.3 Approve prototype electrical identity and wiring

- Inputs: actual XIAO/Sense/sensor revision and matched schematics, battery and
  32GB card; current vendor reference map is only a starting point.
- Steps: map pad/header/GPIO/net/direction/voltage/pulls/reset states, DVP/SCCB,
  SPI clock/data/CS, USB, BAT, onboard charger and control/indicator circuits.
- Reconcile current CS21/user-LED sharing and historical schematic differences;
  no heartbeat toggles a live card select. GPIO0 is BOOT, camera XCLK is separate;
  qualify button/strap gestures rather than copying the old GPIO0 prohibition.
  Keep microphone capture disabled and do not assume built-in battery telemetry.
- Outputs: reviewed `hardware/prototype-a/pin-map.csv`, assembly/power isolation
  diagram, identities, revision label and electrical signoff.
- Acceptance: no conflicting pins/rails/USB-pack sources, approved removable-pack
  BAT connection and recovery path. Candidate maps are not approved wiring.

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
  32GB FAT32 allocation/SPI-mount settings; current-limited power and cut/removal procedures;
  separate cross-build, build-only tests and hardware test commands.
- Outputs: actual card/preparation record and bench assignment with explicit
  flash/test/monitor scope and port; no generic destructive disk command.
- Acceptance: unsupported exFAT rejected without format; no unapproved device erase,
  battery wiring, eFuse, OTA or filesystem upload hidden inside checks.

### 0.8 Establish Flutter/Dart and hardware review ownership

- Inputs: current AGENTS/profile allowlists and stack matrix.
- Steps: lead defines qualified Flutter implementation/review ownership and
  hardware electrical/mechanical review; propose profile additions separately if
  needed, preserving existing permission/delegation semantics.
- Outputs: recorded role route and bounded app/bootstrap reviewer assignments.
- Acceptance: app work never assigned to a React role merely by name; no profile
  edits bundled into unrelated firmware work. Existing role permissions respected.

### 0.9 Build PR firmware and publish tagged installation releases

- Detailed assignment: [0.9 firmware CI and release plan](0.9-firmware-ci-release.md),
  broken into **0.9.1–0.9.16** with files, dependencies, contracts and acceptance.
- Depends: completed 0.2 firmware/host commands. Release-manifest schemas and
  tests are created here; this package need not wait for media/API work 0.6.
  Add 0.6/Flutter/backend checks when those implementations actually exist.
- PRs: build each immutable latest head SHA, including docs-only/draft PRs;
  include that head hash in build/run/artifact names. Keep stable check names.
- Main: rebuild/test the exact main push SHA after a merge, then create immutable
  `firmware-main-<sha12>` at that full SHA and publish a complete installation
  Release. No PR artifact promotion or tag/release on failed checks.
- Payload: flash images and generated offsets, manifest/version/checksums,
  cross-platform Python installer/setup wrappers, dependency lock, install guide,
  release notes and licenses. Users need no PlatformIO/source checkout to flash
  prebuilt binaries. Preserve the existing developer source-install route.
- Gates: least privilege, explicit port/consent, actual chip/layout checks,
  no default full erase/NVS overwrite/eFuse writes, retry/concurrency handling,
  no silent security downgrade. Current minimal firmware releases are prototype
  pre-releases with hardware installation and recording limitations stated.
- Outputs: the planned GitHub workflows, release/installer tools and real tests
  listed in the detailed plan; update README/profile/guide and evidence ledger.
- Acceptance after rollout: CI-T01–CI-T14 pass with HOST/BUILD/workflow evidence;
  pre-merge handoff reports live main publication pending. CI-T15 needs
  separately authorized DEVICE installation evidence. No empty/skipped checks
  presented as green validation. Writing this plan does not implement the pipeline.

## Stage 1 — standalone camera recorder

### 1.1 Bootstrap the firmware and portable core

- Depends: 0.2, 0.3, 0.6, 0.7. Writable: `firmware/`, relevant CI/profile docs.
- Steps: create pinned PlatformIO ESP-IDF structure, `vdog_xiao_sense_proto` and `native`,
  component interfaces, board selection and version reporting; add minimal host
  harness. Keep camera/SD implementations separate from portable logic.
- Acceptance: root build/host commands work; unsupported boards fail clearly;
  no silently inherited PSRAM/flash defaults. Handoff BUILD/HOST separately.

### 1.2 Bring up board, memory and recovery interface

- Depends: 1.1 plus authorized identified hardware.
- Steps: verify rails/current, module marking, flash capacity, PSRAM size/mode,
  native USB/BOOT recovery and exact XIAO/Sense GPIO setup; log sanitized identity.
- Outputs: board adapter, measurements and hardware identity record.
- Acceptance: detected memory matches actual XIAO Sense and build (documented
  baseline 8MB flash/8MB octal PSRAM, not Plus/N16R8/classic). Reproducible USB/BOOT
  recovery, correct sensor identity and no strap conflicts; no mic initialization.

### 1.3 Capture and validate bounded JPEG frames

- Depends: 1.2. Writable: camera component and host fakes/tests.
- Steps: detect/configure the actual Sense sensor (current OV5640/OV3660,
  legacy OV2640 only if separately qualified), JPEG/PSRAM and reviewed camera map;
  respect media-v1 bounds. Acquire/timestamp/validate/release; two-buffer
  starting point; bound frame/queue sizes; expose FPS/drop/invalid/memory counters.
- Acceptance: decodable frames/dimensions; fake driver tests cover every ownership
  path including queue full, oversize, init/allocation failure and shutdown.
  Actual FPS and memory are measured, not derived from requested settings.

### 1.4 Mount and qualify the SD adapter

- Depends: 1.2, 0.7; can parallel 1.3 in separate bounded assignments.
- Steps: explicit Sense SPI/SDSPI bus and reviewed CS/pulls/LED arbitration,
  32GB FAT32 mount, no-format error paths,
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
  32GB measured-retention/72h-goal acceptance remains 1.15.

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
  Radio transitions must not stop recording; do not toggle SPI CS for status
  indication, and qualify the XIAO BOOT/control gesture independently of camera.

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

### 1.14 Decide image quality and 32GB capacity feasibility

- Depends: 1.11–1.13 and rubric0.5; requires DEVICE evidence.
- Steps: measure real mixed-scene profile matrix, JPEG distributions, achieved
  FPS/gaps/blur/object visibility, SD stalls, allocated bytes/hour and power;
  report actual 32GB useful retention, allocate 85% pool/≤2GB protection and
  complete-bundle headroom. Screen 72h at ≤0.75Mbit/s total allocated growth.
- Acceptance: agreed readability/capture/rate evidence, not a presumed 0.75Mbit/s
  supported mode. A 72h pass additionally needs useful footage within capacity;
  if incompatible, document the unmet goal and obtain a scope/storage/profile
  decision before full milestone signoff/claims. No automatic quality/FPS reduction.

### 1.15 Validate 32GB rollover, power faults and the 72h goal

- Depends: 1.14, approved bench power/card procedure.
- Steps: ≥30 controlled cut cases across write/finalize/prune; inspect all prior
  data damage; run ≥72h plus enough rollover on priority 32GB card; measure the
  actual retained duration (earlier overwrite is an unmet 72h target). Sample files
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
- Acceptance: recorder criteria PR-01–02,05–06/FW-01–05 have explicit evidence;
  PR-03 has an explicit measured verdict: a working 32GB loop is not a 72h pass.
  If PR-03 is unmet, full milestone verification requires a scope decision;
  any accepted limited prototype handoff states its actual retention and limits.
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
- Steps: prove dual slots fit actual XIAO Sense flash (documented 8MB) with
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
  2GB-or-smaller cap inside pool, quota/evicted errors; server event association distinct
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
  dependency. Skip with a recorded decision if XIAO Sense resources do not permit it.

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
  connector/strain relief, reviewed switch/shutdown and XIAO BAT/onboard-regulator/
  undervoltage path (no default external 5V boost),
  and compatible separate charger. Stock onboard charger exists but is not the
  owner workflow; disconnect pack before USB service unless isolation is reviewed.
  No added charging/load-sharing feature. Prevent accidental charging/back-feed.
- Acceptance: schematic/pack/charger compatibility, polarity, peak/cutoff and
  disconnect/reconnect review; external charger included in kit cost; runtime/
  mass/cost recorded. No recording-while-charging implementation required.

### 4.2 Design carrier or integration assembly after feasibility

- Depends:1.17,4.1,quotes0.4.
- Steps: retain the qualified XIAO/Sense/sensor assembly; design a carrier or
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
  reporting radio-off and timed-radio workloads separately on the XIAO BAT input. This is the proposed
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
- Steps: extend 0.9's versioned release/install bundle for the accepted product
  revision; retain tested package-only and clean-clone install routes, card prep, assembly, pairing,
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

## Current Stage 0 status — audited 2026-11-20

**Stage 0 is not complete.** The owner-facing product choices and written scope
are settled; package 0.2 has BUILD/HOST evidence and remaining preflight work is
incomplete. Documentation review does not replace the outputs below.

| Package | Status | Evidence / remaining output |
| --- | --- | --- |
| 0.1 Scope | Documented and reviewed | Product/decision records reflect the confirmed board, battery, runtime goal, Wi-Fi, external charging, chest fit and dry-weather scope |
| 0.2 Toolchains | Qualified 2026-11-19 (BUILD/HOST) | `firmware/` project pinned to official `platformio/espressif32@8.0.0` (ESP-IDF v6.1.0), envs `vdog_xiao_sense_proto`/`native`, tracked lockfile, explicit 8MB/octal-PSRAM/USB-console/custom-partition Kconfig, 8MB two-slot budget from the measured image and clean cross-build + native test passes: [toolchain matrix](../toolchain.md). Physical flash/PSRAM/camera detection remains DEVICE evidence for 1.2–1.4 |
| 0.3 Wiring | **Preparation drafted; NOT APPROVED** (2026-11-23) | [Prototype A](../../hardware/prototype-a/README.md) and candidate CSV provide source/ownership/power-service records. OV5640 selected; actual PCB identities, exact pack/charger, revision-matched net/pull/reset audit, measurements and qualified electrical signoff remain absent |
| 0.4 Cost | Allocation only | CNY149 ceiling exists; exact-part BOM and dated supplier quote evidence absent |
| 0.5 Acceptance rubrics | **Draft for owner / qualified review** (2026-11-23) | [Daytime 0.5–1 m rubric](../specs/recording-acceptance.md) defines repeatable scenes, scoring and proposed numeric limits. Owner acceptance, measured geometry and qualified physical limits/procedure remain pending; rubric NOT FROZEN |
| 0.6 Contracts | **REVIEWED (HOST)** — approved on `opencode/0.6-contracts`; test engineer `VERIFIED`; Orchestrator detached review passed at `6e7717d`; PR delivery in progress | [`contracts/`](../contracts/README.md): `device-v1.yaml` and `backend-v1.yaml` (43 operations), `media-v1/` frame/manifest/active JSON Schemas, and 441 committed golden fixtures (90 media segments with 72 single-defect vectors, 351 API vectors) generated from `tools/contracts/fixture_spec.py`; offline validator plus its host suite, both qualified commands PASS locally (HOST). Consumer conformance for firmware/app/backend, CI wiring and every DEVICE claim remain absent; the OTA envelope is deliberately deferred to 2.10. Orchestrator and test engineer independently re-ran both qualified commands at `6e7717d` (validator 338 fixtures/0 findings exit 0; 322 passed, 5 skipped) and mutation-checked committed defect fixtures (HOST). Round 6 closed five contract-validator defects (exact-number parsing on the manifest path, the request sidecar judged as a request, the manifest inside a stored clip, the chunk body read as bytes, and one crop predicate), regenerated the corpus to 419 vectors and added the two diagnostics those refusals require. Round 7 closed four more validator defects — the request/answer range pairing (a `416` refusing a specifier its own `bytes */<total>` proves satisfiable, a `206` answering a request that names no `Range`, and a request sidecar that is present but empty), a record whose indexed slice is two JPEGs, a recovered `duration_us` that is not the close time §4 fixes, and a derivative crop measured against the wrong device's pixels — regenerated the corpus to 427 vectors and added the two diagnostics those refusals require (HOST). Round 8 closed four further defects — the unclamped `416` satisfiability check (RFC 9110 §14.1.2 clamps a specified end past the representation's end rather than making the range unsatisfiable), the in-scan JPEG walk that skipped COM and APPn segments instead of reading them by their length (T.81 §§B.2.1/B.2.4), a response-header `Range` echo excusing a `206` whose request sidecar omits `Range`, and transcode fixtures whose recorded output upscaled the window they cite (backend spec §7.3) — regenerated the corpus to 431 vectors and added the paired regression vectors and the progressive-comment fixture (HOST). Round 9 closed four further defects — the in-scan JPEG walk that skipped DQT and DRI between-scan segments instead of reading them by their length (T.81 §§B.2.1/B.2.4.4), an upload `204` that acknowledged a chunk without advancing `Upload-Offset` to request offset plus chunk length (interfaces.md §8 step 2), a paired `416` whose request sidecar carried no `Range` (RFC 9110 §15.5.17 refuses *a range*; a whole-file request ends in 200), and golden transcode fixtures that changed the aspect ratio of the source they cite (backend spec §7.3) — regenerated the corpus to 433 vectors and added the `UPLOAD_OFFSET_STALE` diagnostic, the stale-offset pair and the progressive-DRI fixture (HOST). The round-9 follow-up closed two LOW coverage gaps the independent verification found — the paired Range-less `416` was caught only by a unit test, so the corpus now ships `device/invalid/clip-file-response-416-no-range-sidecar`, and the `clip-detail-response-200` derivative summary was synced by nothing, so the golden-fixture ratio test now checks every valid `StoredClip` summary against its cited source and against the record sharing its `derivative_id` — regenerated the corpus to 434 vectors (HOST). Round 10 closed three further defects the full review reproduced — a receiving `GET /uploads/{id}` detail that could omit or null the 24 h `expires_at` it is required to report (interfaces.md §8 step 5), an unmounted `StorageStatus` that could still report measured totals (interfaces.md §4), and the document check that let a required request body or a required request header be weakened to optional — with the four refusal vectors, the mounted measured-zero counterexample and two document scenarios that pin them, regenerated the corpus to 439 vectors (HOST). Round 11 closed three further defects the full review reproduced — a `GET /uploads/{id}` 200 whose success schema accepted an `expired` session that interfaces.md §8 step 5 answers only with a 410, response Header Objects the contract promises on a status while the document leaves them at OpenAPI's optional default, and the document gate that scanned neither parameter `$ref` integrity, nor path-template placeholders, nor the `device_id` query interfaces.md §9 pins on every clip-keyed backend route — with the one refusal vector and three document scenarios that pin them, regenerated the corpus to 440 vectors (HOST). Round 12 closed three further defects the full review reproduced — the shared `Content-Range` component that modelled the unsatisfied `bytes */<total>` refusal form beside the granted `bytes first-last/total` grant (RFC 9110 §14.4) while the shared 416 carried no header at all, the `Content-Length` a bodyless 204 acknowledgement could still carry whatever its value (§8.6), and the document gate that certified duplicate parameter identities and case-colliding response-header names — with the Content-Range split (granted-required 206 / unsatisfied-optional 416), the 204 refusing `Content-Length`, the duplicate-declaration gate, the one refusal vector and two document scenarios that pin them, regenerated to 441 vectors (HOST). Round 14 closed three further checker notes the full review reproduced — the media-type loop whose unguarded response read turned a dangling download `206` `$ref` into an exit-2 "validator internal error" instead of the all-response scan's `SPEC_COMPONENT_DRIFT`, the declared response `headers` member that a status with no mandatory headers could ship as a non-map with zero findings (the shared 404's `headers: []`), and `yaml.safe_load` dropping a second literal `Upload-Offset:` key before the duplicate-header gate could see it, now refused by a duplicate-key-rejecting safe loader as `SPEC_PARSE_FAILED` — with unit and CLI regressions and three corpus-gate document scenarios that pin all three, the corpus untouched at 441 vectors (HOST) |
| 0.7 Card/bench | **Procedure drafted; DEVICE UNVERIFIED** (2026-11-23) | [Bench plan](../../hardware/prototype-a/bench-plan.md) separates host/build checks from future operations. Exact card/host/port, backup/preparation/allocation/mount evidence and bounded hardware authority remain pending |
| 0.8 Role ownership | Not established | Flutter/Dart and qualified hardware implementation/review routing still needs a concrete recorded assignment |
| 0.9 CI and installation releases | **IN PROGRESS** — implemented on `opencode/0.9-ci-release`; hosted run pending | [0.9.1–0.9.16](0.9-firmware-ci-release.md): both workflows, `publish.py`, isolated installer wrappers and the prebuilt guide exist with 422 host tests (BUILD/HOST). `actionlint`, `pwsh`, GitHub credentials and a device are absent, so CI-T08/T11/T14 hosted visibility and CI-T15 remain unverified; 0.9.15 (device install) is deliberately deferred |

Package 0.2 completed 2026-11-19 with BUILD/HOST evidence
([toolchain](../toolchain.md)); Stage-0 hardware-dependent acceptance still
waits for identified parts and an appropriate authorized bench assignment.
The next implementation assignments are the 0.6 cross-language consumer
conformance (C++/Dart/Rust readers over the committed
fixtures, T-04) and 0.9 PR CI/tagged installation releases, alongside 0.3/0.4
actual-part and wiring/cost preparation. Stage 1–4
application/hardware work remains unexecuted; do not report the recorder or
full Stage 0 as complete.
