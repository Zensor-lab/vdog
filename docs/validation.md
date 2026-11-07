# Validation and evidence plan

Status: no application or hardware validation has run. Documentation inspection
does not verify firmware, app, backend, cost, model inference or live delegation.

## 1. Evidence levels and record format

Report separately: **DOC** (spec/link/consistency inspection), **HOST** (portable
unit/contract/integration tests), **BUILD** (cross-compilation/static checks),
**DEVICE** (electronic hardware), **FIELD** (approved supervised wear/scene tests),
and **QUOTE** (dated procurement evidence). None substitutes for another. Use
`PASS`, `FAIL`, `UNVERIFIED` per criterion; independent test-engineer outcomes
follow AGENTS.md: `VERIFIED`, `REWORK REQUIRED`, `UNVERIFIED`.

Evidence includes requirement/package ID, exact commit, command/exit result,
tool versions, OS, board/revision/port, card model/filesystem/usable bytes,
profile, power conditions, start/end time, expected/observed result, artifact
hashes, failures and limits. Do not publish secrets or private raw imagery.

## 2. Acceptance matrix

| Test | Requirements | Procedure and pass evidence |
| --- | --- | --- |
| T-01 clean bootstrap | PR-02,13 | Pinned build on clean runner; memory configuration checked separately on board |
| T-02 offline auto record | PR-01,06; FW-01 | Healthy card, router/phone/backend absent; 10 cold boots, persisted-frame latency recorded |
| T-03 capture/storage | PR-03; HWR-03,04 | Mixed-scene 640×480/800×600 ×10/15FPS matrix; size, rate, stalls, memory, gaps and quality |
| T-04 media contracts | PR-05,15; FW-03 | Shared valid/invalid fixtures in C++/Dart/Rust/tools; identical CRC/hash/duration interpretation |
| T-05 partial writes | PR-05; FW-03 | Fault before/after append/sync/rename/catalog steps; valid prefix/quarantine and next recording |
| T-06 power loss | PR-05; HWR-09 | ≥30 controlled cuts across writer/finalize/prune under approved bench setup; report earlier corruption too |
| T-07 retention | PR-03; FW-04 | ≥72h powered capture plus multiple evictions on real 128GB card; inspect/play samples across window |
| T-08 card faults | PR-10,14 | Full/pinned/leased/removal/exFAT/readonly/slow faults; truthful status, no autoformat/overwritten pin |
| T-09 clock/reset | PR-05,10 | Unknown UTC, corrections both directions, reboot/bad clock; increasing frame timestamps and distinct IDs |
| T-10 pairing | PR-07,12 | Android+iOS: denied permissions, internetless AP, stale QR, wrong pin/secret, closed window, already owned, reset |
| T-11 download | PR-07,15 | Interrupt/restart, lease expiry/prune, ETag mismatch, corrupt local bytes; verified hashes and bounded resume |
| T-12 playback | PR-07 | Short/large/gapped clips, seek/pause/background/memory pressure; bounded decoding and correct timing |
| T-13 priority | PR-01,07 | Recording+preview/download and later sync; recording metrics stay within qualified envelope |
| T-14 OTA | PR-08 | Good/bad signature/hardware/length/version, interrupted staging/power, failed boot/rollback; recording resumes |
| T-15 ingest | PR-09,15 | Repeated chunks/wrong offset/hash, expiry, restart at DB/blob steps, collision/quota; exact originals preserved |
| T-16 worker | PR-09,12 | Malformed media/decode limit/params/path, quota, timeout/cancel/restart; no orphan child/network/public files |
| T-17 EIS | PR-09,15 | 20–30 representative clips; paired original/derivative evaluation, crop/distortion/detail/time measured |
| T-18 bench | PR-11; HWR-05 | Power transitions, pack/runtime/mass/thermal/charging/enclosure; limits documented before wear |
| T-19 wear | PR-11; HWR-06 | Only after T-18/procedure approval: fit, occlusion, ground view, movement/comfort; no universal suitability claim |
| T-20 cost/release | PR-04,13; HWR-02,10 | Complete fitted BOM/assembly/test/loss/contingency quotes, editable design and reproducible build manifest |
| T-21 restore | PR-09,12 | Restore DB+blobs on clean host; verify originals/events/token policy/job recovery |

These are initial engineering minimums, not reliability certification. Expand
failed tests to investigate; repeat passing tests only after relevant changes
or for an unresolved concern.

## 3. Quality and retention methodology

Before testing choose a repeatable scene rubric: harmless ground objects,
distance/size/contrast, mounting height/angle, lighting, movement and an
owner-agreed readability criterion. Start with controlled bench motion. Label
recognizable frames and failures due to blur, occlusion, compression, exposure
or dropped capture. Smooth-looking playback is insufficient and does not prove
hazard detection.

Compute allocated bytes per recorded second for media/index/manifests/catalog.
Report average and scene-window peaks, JPEG-size and SD-latency percentiles,
actual usable/free capacity and protected bytes. Arithmetic screens profiles;
only the real 72h/rollover run supports retention. Count captured duration,
not powered-off/stalled time; report gap distribution and usability. A sparse
file spanning 72h does not prove useful coverage. Re-test at maximum advertised
protected budget; pins subtract from rolling capacity.

## 4. Planned checks after bootstrap

These are **future command contracts**, not runnable checks in today's starter.
Package 0.2 creates/verifies them and updates exact versions/environments.

```sh
pio run -d firmware -e vdog_s3_proto
pio test -d firmware -e native
pio test -d firmware -e vdog_s3_proto --without-uploading --without-testing
python3 tools/validate_contracts.py
flutter analyze --fatal-infos
flutter test
cargo fmt --manifest-path backend/Cargo.toml --check
cargo clippy --manifest-path backend/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path backend/Cargo.toml --locked
git diff --check
```

Run Flutter commands from `app/`; others from repository root. The embedded
build-only test command does not execute tests. `pio test` without those flags
may upload; use only the plan's identified authorized device/port.

## 5. CI and milestone signoff

CI runs schemas/fixtures, portable tests, pinned firmware build, Flutter
analyze/tests and Rust checks once implemented. Hardware/mobile-device/field
gates require separate evidence. Keep large recordings, secrets, build outputs
and local DBs out of Git; use small synthetic fixtures and sanitized metrics.

Independent review checks exact handoff diffs/claims. Test engineer runs checks
without fixes; lead resolves missing evidence using AGENTS.md's isolated final
review workflow for implementation. Documentation delivery itself has no
implementation handoff commit, push, PR, device run or deployment.
