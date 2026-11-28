# Validation and evidence plan

Status: updated 2026-11-21. Package 0.2 records firmware BUILD and portable
HOST evidence in [toolchain](toolchain.md); package 0.6 records the media/API
contract gate as HOST evidence in section 4; Stage 0.9 round 2 adds the CI,
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
see [toolchain](toolchain.md). The Stage 0.6 contract validator exists and runs
offline (its two commands are in the qualified-interpreter block below). The
Flutter and Rust commands remain future contracts until their packages exist. The
[Stage 0.9 release plan](plans/0.9-firmware-ci-release.md) adds real
package/installer/workflow tests without pretending absent tools passed.
Upstream board support alone is not a project build or device qualification.

```sh
pio run -d firmware -e vdog_xiao_sense_proto
pio test -d firmware -e native
pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing
flutter analyze --fatal-infos
flutter test
cargo fmt --manifest-path backend/Cargo.toml --check
cargo clippy --manifest-path backend/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path backend/Cargo.toml --locked
git diff --check
```

The Stage 0.6 media/API contract gate and the host release-tooling suite run on the
qualified CPython 3.12 through `uv` (the system `python3` here is 3.14 and is not
the qualified interpreter). The contract validator opens no sockets, reads no
environment variables and exits 0 only when every contract document, schema and
committed golden fixture matches its declared expectation
([`contracts/README.md`](../contracts/README.md)). It is **HOST** evidence only:
the validator and its suite run locally and prove that the published documents and
fixtures agree with each other, not that firmware, the Flutter app or the Rust
backend consumes them (consumer conformance is T-04):

```sh
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  python tools/validate_contracts.py            # corpus gate: 0 pass, 1 check failed, 2 validator error
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  pytest tools/contracts/tests                  # the suite that guards that gate
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  python -m tools.contracts.generate_fixtures   # rewrite contracts/fixtures from fixture_spec.py
```

The Stage 0.9 release-tooling suite uses its own locked environment:

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
`git`, `unzip`, `gh` (authenticated). **Not available here, so their checks did
not run locally and are recorded as UNVERIFIED rather than passed:** `pwsh` (so
`install.ps1` has structural/text coverage only, never an execution) and
`actionlint`/`yamllint` (so workflow linting is the structural parse and
invariant assertions in `tools/firmware/tests/test_workflows.py` plus the
executed hosted runs). The hosted workflows themselves ran on GitHub Actions
(not from this checkout) — merged `main` pushes and PRs #3–#7 triggered them;
their live results, tags, artifacts and published Releases were verified
through the `gh`/REST APIs and real asset downloads on 2026-11-28 (section 5).
No device was connected and no serial port was opened by any verification
command; CI-T15 remains deferred by decision D-17.

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

| Test | Status | Evidence (hosted verification executed live 2026-11-28 against real GitHub data on `Zensor-lab/vdog`; local structural rows retained) |
| --- | --- | --- |
| CI-T01 no path filters | PASS (HOST structural + LIVE) | `tests/test_workflows.py` asserts neither workflow declares `on.*.paths`; live: every PR from #3 through #7 started all three firmware checks, including docs-only heads (`5171bee` on PR #6, `23697ca` on PR #5 — run `46108373780` / `46056456774`, each three jobs `success`) |
| CI-T02 PR builds head SHA | PASS (LIVE) | successive PR #6 heads produced distinct hash-named artifacts — `vdog-xiao-sense-pr-6-4e7ee9e1a5ba-run46107610827-a1` (191,394 B) and `vdog-xiao-sense-pr-6-5171bee6a77c-run46108373780-a1` (191,390 B) — each `jobs[].head_sha` equals the exact head; the "Validate and record PR source identity" step `success` in every `firmware-build` |
| CI-T03 complete hash-named package | PASS (LIVE) | hosted `firmware-build` ran "Export, package and validate the installation ZIP", "Run the packaged installer's offline check (never opens a port)" and "Upload the complete hash-named bundle" — all `success` on runs `46108373780` (PR) and `46134420714` (main); the downloaded published bundle's `plan` lists all four segments at `0x0`/`0x8000`/`0xf000`/`0x20000` |
| CI-T04 stable check names | PASS (LIVE) | GitHub jobs API returned exactly `firmware-build`, `firmware-host-tests`, `firmware-package-tests` (plus `publish` on main), byte-identical across every PR and main run observed |
| CI-T05 main rebuild from source | PASS (LIVE) | main run `46134420714` built the exact triggering SHA `afd6c5354dbc8c1ea6472b0163255617600d50ba`; `publish` only "Download this run's validated bundle" (own `run-id`); no `download-artifact` outside `publish` (step lists + structural test) |
| CI-T06 exact tested SHA tag | PASS (LIVE) | `git ls-remote` peel: `refs/tags/firmware-main-afd6c5354dbc^{}` → `afd6c5354dbc8c1ea6472b0163255617600d50ba`; `firmware-main-957b415da46c^{}` → `957b415da46c2cfd9b068838bb5fb8c799a283a8`; no force/update/delete path (adapter + tests) |
| CI-T07 manifest agrees | PASS (LIVE) | downloaded `manifest.json`/`VERSION.json`: `source.kind=main`, `source.sha` = the full tested SHA, `tag=firmware-main-afd6c5354dbc`, `ci.run_id=46134420714`, `ci.attempt=1`, `release_channel=prototype`, `hardware_verified=false`; Release body prints the same tag/SHA/run/toolchain |
| CI-T08 assets + digest downloadable | PASS (LIVE) | all six assets of `firmware-main-afd6c5354dbc` downloaded 2026-11-28: `vdog-xiao-sense-main-afd6c5354dbc.zip` (192,991 B, sha256 `c8361043b6ebfbb1…d40dda`), `.sha256`, `manifest.json`, `INSTALL.md`, `RELEASE_NOTES.md`, `THIRD_PARTY_NOTICES.md`; `shasum -a 256 -c` on the shipped digest OK and all six digests match GitHub's server-side asset digests |
| CI-T09 wrappers set up isolated env | PARTIAL — macOS PASS (LIVE), Windows UNVERIFIED | real `sh ./install.sh check` against the published ZIP on this macOS host created `.venv-installer` (CPython 3.12.12, 18 hash-locked packages incl. `esptool==5.4.0`, `pyserial==3.5`), exit 0; `install.sh plan --board seeed-xiao-esp32s3-sense` exit 0; offline fast path (`PATH=/bin:/usr/bin`) exit 0. **Windows `pwsh` not installed here — `install.ps1` has never executed on any host; remains unverified** |
| CI-T10 idempotent rerun | PASS (HOST) | same-SHA rerun, two rapid SHAs, interrupted upload, foreign published manifest and missing asset tested against the fake adapter; live corroboration: six independent main SHAs each produced exactly one tag + one prerelease, no mixed attempts |
| CI-T11 prerelease, never latest | PASS (LIVE) | release `461470805`: `prerelease=true`, `draft=false`, `target_commitish` = exact full SHA, title `vdog 0.2.0-proto — main afd6c5354dbc`; `GET /releases/latest` → 404 (nothing flagged latest); notes/guide/manifest agree with the exact SHA/tag/run |
| CI-T12 least privilege | PASS (HOST structural + LIVE) | top level and every build job `contents: read`; only `publish` gets `contents: write` + `actions: read`; actions pinned to full SHAs; no `pull_request_target`/`workflow_run`/`workflow_dispatch`; live: repo Actions settings `default_workflow_permissions=read`, `can_approve_pull_request_reviews=false`; every observed run event was `push` or `pull_request` only |
| CI-T13 concurrency | PASS (LIVE) | PR group cancels superseded heads: run `46100912142` (PR #6 @ `9e41b45`) `cancelled` at 03:04:49Z when head `1ef6189` pushed at 03:04:31Z; main groups per SHA with `cancel-in-progress: false` — all six main runs completed independently, none cancelled |
| CI-T14 artifact ZIP downloadable | PASS (LIVE) | outer ZIP fetched 2026-11-28 via the artifacts API `archive_download_url` (191,390 B), `unzip -t` clean; inner `vdog-xiao-sense-pr-6-5171bee6a77c.zip` verified against its shipped `.sha256` (`b9436ded…f479cd: OK`); extracted `install.py check` exit 0 (`check: OK — manifest, layout, 4 images, hashes, partition table and headers all consistent`) and `plan --board seeed-xiao-esp32s3-sense` exit 0 with "never written: NVS, phy_init, storage, SD card, security fuses" |
| CI-T15 real device install | UNVERIFIED (deferred) | out of scope by decision D-17; needs the identified authorized unit/port and DEVICE evidence (awaiting separately authorized hardware) |

Structural rows are asserted by `tools/firmware/tests/test_workflows.py`, adapter
rows by `test_publish.py`, wrapper rows by `test_install_wrappers.py`. The
authoritative hosted gate — the first real PR runs and the first real main
publication — was executed and independently re-verified live on 2026-11-28
(50+ `firmware-pr` runs on the workflow-era PR branches of PRs #3/#5/#6/#7
and `hardware-preflight`, all `success` except the observed concurrency cancel
and two pre-merge bring-up runs on `opencode/0.2-toolchains`; six
`firmware-main` runs
`44908002249`/`44935853821`/`45383711985`/`45999492912`/`46084351267`/
`46134420714` with matching peeled tags and six prereleases; commands and
digests as per rows above). Still not executed anywhere: `install.ps1` on
Windows (no `pwsh` here), `actionlint`/`yamllint`, and CI-T15 device
installation.

CI runs available portable tests and the pinned normal firmware build, then
schemas/fixtures, Flutter and Rust checks when their implementations exist. Hardware/mobile-device/field
gates require separate evidence. Keep large recordings, secrets, build outputs
and local DBs out of Git; use small synthetic fixtures and sanitized metrics.

Independent review checks exact handoff diffs/claims. Test engineer runs checks
without fixes; lead resolves missing evidence using AGENTS.md's isolated final
review workflow for implementation. A documentation commit/PR is not application,
device or deployment evidence.
