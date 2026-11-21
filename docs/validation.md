# Validation and evidence plan

Status: updated 2026-11-21. Package 0.2 records firmware BUILD and portable
HOST evidence in [toolchain](toolchain.md); Stage 0.9 round 2 adds the CI,
publish and prebuilt-installer HOST evidence in section 5. Device/app/backend/
recording evidence and every hosted Actions run remain unverified. Documentation
inspection supplies none of those runtime or deployment results.

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
| T-01 clean bootstrap | PR-02,13 | Pinned XIAO ESP-IDF build on clean runner; sensor/8MB flash/octal PSRAM/SPI SD config explicit, actual memory checked separately on board |
| T-02 offline auto record | PR-01,06; FW-01 | Healthy card, router/phone/backend absent; 10 cold boots, persisted-frame latency recorded |
| T-03 capture/storage | PR-03; HWR-03,04 | Mixed-scene 640×480/800×600 ×10/15FPS matrix; size, rate, stalls, memory, gaps and quality |
| T-04 media contracts | PR-05,15; FW-03 | Shared valid/invalid fixtures in C++/Dart/Rust/tools; identical CRC/hash/duration interpretation |
| T-05 partial writes | PR-05; FW-03 | Fault before/after append/sync/rename/catalog steps; valid prefix/quarantine and next recording |
| T-06 power loss | PR-05,18; HWR-09 | ≥30 controlled cuts including pack-unplug across writer/finalize/prune; automatic recording after reconnect; report earlier corruption too |
| T-07 retention | PR-03; FW-04 | Real 32GB FAT32 capture/rollover and ≥72h powered soak; record actual useful retained duration; earlier eviction is not a 72h pass; repeat at advertised ≤2GB pin budget |
| T-08 card faults | PR-10,14 | Full/pinned/leased/removal/exFAT/readonly/slow faults; truthful status, no autoformat/overwritten pin |
| T-09 clock/reset | PR-05,10 | Unknown UTC, corrections both directions, reboot/bad clock; increasing frame timestamps and distinct IDs |
| T-10 pairing | PR-07,12 | Android+iOS: denied permissions, internetless AP, stale QR, wrong pin/secret, closed window, already owned, reset |
| T-11 download | PR-07,15 | Interrupt/restart, lease expiry/prune, ETag mismatch, corrupt local bytes; verified hashes and bounded resume |
| T-12 playback | PR-07 | Short/large/gapped clips, seek/pause/background/memory pressure; bounded decoding and correct timing |
| T-13 priority | PR-01,07,17 | Radio-off default and physical timed access; no remote wake, separate claim/session timers; recording+one TLS preview/download/sync; resource shedding and expiry preserve capture |
| T-14 OTA | PR-08 | Good/bad signature/hardware/length/version, interrupted staging/power, failed boot/rollback; recording resumes |
| T-15 ingest | PR-09,15 | Repeated chunks/wrong offset/hash, expiry, restart at DB/blob steps, collision/quota; exact originals preserved |
| T-16 worker | PR-09,12 | Malformed media/decode limit/params/path, quota, timeout/cancel/restart; no orphan child/network/public files |
| T-17 EIS | PR-09,15 | 20–30 representative clips; paired original/derivative evaluation, crop/distortion/detail/time measured |
| T-18 bench | PR-11,16,18; HWR-05 | Protected 1000mAh/XIAO BAT path, proposed ≥1h/2h; peaks/cutoff/onboard regulation, keyed connector, actual-case runtime/heat, pack unplug before USB-C service; external charger compatibility despite stock onboard charger |
| T-19 wear | PR-11,19; HWR-06 | After T-18/approved procedure: actual below-8kg dog, measured chest/harness and basic case; dry-use fit/leg clearance/occlusion/ground view/comfort; no all-small-dog, larger-dog or weather-rating claim |
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
only real capture/rollover supports measured retention; a 72h claim needs actual
useful retained duration of 72h, not merely a 72h powered run. Count captured duration,
not powered-off/stalled time; report gap distribution and usability. A sparse
file spanning 72h does not prove useful coverage. Re-test at maximum advertised
protected budget (initial proposed device cap ≤2GB); pins subtract from rolling
capacity. On nominal 32GB the pool is 27.2GB: ~0.84Mbit/s for 72h before further
pins/headroom, or ~0.778Mbit/s with full 2GB pins. The 0.75Mbit/s screening target
may fail useful image quality. Compare nominal 1/2/3Mbit/s capacities (~60.4/30.2/
20.1h) with real allocated growth; do not extrapolate the former 128GB budget.
Record actual sensor and keep audio disabled. Prove SPI CS/LED arbitration and
native USB/BOOT recovery on the acquired revision; no old SDMMC/pin-map assumptions.

## 4. Working and planned check commands

The three PlatformIO commands below exist with package 0.2 BUILD/HOST evidence;
see [toolchain](toolchain.md). The contract validator, Flutter and Rust commands
remain future contracts until their packages exist. The [Stage 0.9 release plan](plans/0.9-firmware-ci-release.md)
adds real package/installer/workflow tests without pretending absent tools passed.
Upstream board support alone is not a project build or device qualification.

```sh
pio run -d firmware -e vdog_xiao_sense_proto
pio test -d firmware -e native
pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing
python3 tools/validate_contracts.py
flutter analyze --fatal-infos
flutter test
cargo fmt --manifest-path backend/Cargo.toml --check
cargo clippy --manifest-path backend/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path backend/Cargo.toml --locked
git diff --check
```

The host release-tooling suite runs on the qualified CPython 3.12 through `uv`
(the system `python3` here is 3.14 and is not the qualified interpreter):

```sh
uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests
VDOG_SKIP_REAL_BUILD=1 uv run --python 3.12 \
  --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests                       # skips only the real-build group
uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock \
  python -m tools.firmware.publish --zip <bundle.zip> --expected-sha <40-hex> --dry-run
```

`--dry-run` makes no network calls and mutates nothing; the publish state machine
is otherwise covered by fake-adapter tests, not by a live GitHub run.

Commands actually available in this environment: `pio`, `uv`, `pytest`, `shasum`,
`git`, `unzip`. **Not available here, so their checks did not run locally and are
recorded as UNVERIFIED rather than passed:** `pwsh` (so `install.ps1` has
structural/text coverage only, never an execution), `actionlint`/`yamllint` (so
workflow linting is the structural parse and invariant assertions in
`tools/firmware/tests/test_workflows.py` plus the first real hosted run), and any
GitHub credential or device (no workflow, tag or Release has been executed from
this checkout).

Run Flutter commands from `app/`; others from repository root. The embedded
build-only test command does not execute tests. `pio test` without those flags
may upload; use only the plan's identified authorized device/port.

## 5. CI and milestone signoff

Stage 0.9's [CI-T01–CI-T15 matrix](plans/0.9-firmware-ci-release.md) owns PR head
identity, exact-main build/tag/release, archive integrity, installer behavior,
permissions, retry/concurrency and device-install evidence. Hosted dry runs are
HOST evidence; actual flashing needs the identified authorized unit/port and
separate DEVICE evidence.

Round 2 implemented the workflows, the publish pipeline and the real installer
wrappers on `opencode/0.9-ci-release`. The definitions stay in the master plan;
this is the evidence status of each row:

| Test | Status | Evidence on this branch / what is still missing |
| --- | --- | --- |
| CI-T01 no path filters | PASS (HOST, structural) | `tests/test_workflows.py` asserts neither workflow declares `on.*.paths` |
| CI-T02 PR builds head SHA | PASS (HOST, structural) | checkout `ref: github.event.pull_request.head.sha` + a step that fails unless `git rev-parse HEAD` equals it |
| CI-T03 complete hash-named package | PASS (HOST) | the `firmware-build` job *definition* packages, validates, uploads a 14-day artifact and runs `install.py check` on the extracted ZIP with the digest re-verified (asserted structurally); the equivalent local chain actually ran end to end — the hosted run of that job is still pending |
| CI-T04 stable check names | PASS (HOST, structural) | three job names, no variable in any `name:` |
| CI-T05 main rebuild from source | PASS (HOST, structural) | no `download-artifact` outside the publish job; publish can only reach its own `run-id` |
| CI-T06 exact tested SHA tag | PASS (HOST) | `publish.py` tags the full SHA, re-peels it, reuses only on exact match; conflict paths tested |
| CI-T07 manifest agrees | PASS (HOST) | `load_publish_inputs` validates the package and tag/title identity before any adapter call |
| CI-T08 assets + digest downloadable | UNVERIFIED (host) | asset set built from the validated ZIP and re-uploaded wholesale on repair; needs one real Release |
| CI-T09 wrappers set up isolated env | PARTIAL (HOST) | fake-`uv` tests and a real `install.sh` setup against a locally packaged ZIP pass; real Windows host run pending (no `pwsh` here) |
| CI-T10 idempotent rerun | PASS (HOST) | same-SHA rerun, two rapid SHAs, interrupted upload, foreign published manifest and missing asset tested against the fake adapter |
| CI-T11 prerelease, never latest | PASS (HOST) | `prerelease=true`, `make_latest=false`, exact title asserted; Release-page visibility needs a real publication |
| CI-T12 least privilege | PASS (HOST, structural) | top level and every build job `contents: read`; only `publish` gets `contents: write` + `actions: read`; all actions pinned to full SHAs; no `pull_request_target`/`workflow_run` |
| CI-T13 concurrency | PASS (HOST, structural) | main grouped per SHA with `cancel-in-progress: false`; PR grouped per PR number with cancellation |
| CI-T14 artifact ZIP downloadable | UNVERIFIED (host) | `if-no-files-found: error` and the embedded digest are asserted; the Actions outer-ZIP download path needs a real PR run |
| CI-T15 real device install | UNVERIFIED (deferred) | out of scope by decision D-17; needs the identified authorized unit/port and DEVICE evidence |

Structural rows are asserted by `tools/firmware/tests/test_workflows.py`, adapter
rows by `test_publish.py`, wrapper rows by `test_install_wrappers.py`. The
authoritative gate for every hosted row is the first real PR run and the first
real main publication after the Orchestrator pushes this branch; nothing here
claims a hosted run happened.

CI runs available portable tests and the pinned normal firmware build, then
schemas/fixtures, Flutter and Rust checks when their implementations exist. Hardware/mobile-device/field
gates require separate evidence. Keep large recordings, secrets, build outputs
and local DBs out of Git; use small synthetic fixtures and sanitized metrics.

Independent review checks exact handoff diffs/claims. Test engineer runs checks
without fixes; lead resolves missing evidence using AGENTS.md's isolated final
review workflow for implementation. A documentation commit/PR is not application,
device or deployment evidence.
