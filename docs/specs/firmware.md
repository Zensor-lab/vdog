# Firmware specification

Status: Seeed Studio XIAO ESP32S3 Sense / 32GB-first, updated 2026-11-20.
Nominal 3.7V 1000mAh and about 1–2h per charge, external pack charging and
on-demand Wi-Fi remain. See [hardware review](../hardware-decision-review.md),
[PlatformIO support](../platformio-support.md) and [hardware](hardware.md).
Package 0.2 supplies a minimal firmware cross-build and portable host tests;
see [toolchain evidence](../toolchain.md). Recording/peripheral behavior, upload
and device operation remain unverified.

## 1. Platform and module boundaries

Use ESP-IDF C++ through a qualified pinned PlatformIO environment, with board
`seeed_xiao_esp32s3` and environment `vdog_xiao_sense_proto`. Official platform
8.0.0 and the exact ESP-IDF/compiler/camera set have package 0.2 BUILD/HOST
qualification; acquired-board behavior still requires device checks. Preserve
small ESP-IDF C adapters and portable host logic. No silent Arduino/fork switch.
Framework/compiler/camera/board versions,
`sdkconfig`, actual 8MB flash/8MB octal PSRAM settings and partitions are release
inputs; Arduino `qio_opi` flags do not configure ESP-IDF.

Target the acquired XIAO/Sense revision and camera. Current units may have
fixed-focus OV5640 or OV3660; older OV2640 needs its own qualification. Verify
sensor detection and driver configuration; preserve media-v1 bounds and the
VGA/SVGA measurement matrix. The Sense microphone stays unused/no audio capture.
Native USB/BOOT recovery replaces the classic UART-only assumption. Do not reuse
classic camera pins, 4MB partitions, old SDMMC or external 5V-boost defaults.

| Planned component | Owns | Must not own |
| --- | --- | --- |
| `board` | Validated pins, revision identity, peripherals, power/indicator abstraction | Recording/business policy |
| `camera` | esp32-camera init/acquire/release, JPEG validation, capture timestamp | SD/HTTP writes |
| `recorder` | State supervisor, bounded queues, segment boundaries, drop accounting | Direct network transport |
| `storage` | Sole card writer, mount, sync, finalization, catalog, recovery, prune, leases | UI/HTTP authorization |
| `clock` | Boot monotonic and nullable UTC mapping with uncertainty | Changing old timestamps |
| `settings` | Versioned validated NVS settings, revision CAS, migration | Publishing secret values |
| `identity` | Unique keys/cert, token hashes, pairing window, reset | Writing secrets to SD/logs |
| `network` | Wi-Fi/AP state, HTTPS API, preview/download scheduling | Holding camera buffers across slow clients |
| `ota` | Signed image staging/validation, slot health/rollback | Unrestricted URL downloading |
| `diagnostics` | Bounded counters, status, sanitized boot/fault log | Footage, tokens or Wi-Fi password logging |

## 2. State machine and fault behavior

```text
booting -> recovering -> recording
                  \-> storage_fault / camera_fault / storage_full
recording -> shutting_down -> power off
recording -> updating -> reboot -> health check -> recording or rollback
fault -> bounded retry / card replacement -> recovering -> recording
```

Network state is orthogonal. An unconfigured or unavailable Wi-Fi connection
does not block boot, recovery or recording. Retry camera init at most three
times with bounded backoff, then expose a latched fault and low-rate recovery
attempt; do not continuously restart the entire board. Card removal closes the
writer best-effort, invalidates leases, and shows `NO_CARD`; reinsertion requires
mount/recovery before recording. A bad filesystem is never autoformatted.

Use the actual card state and first successfully persisted frames to indicate
recording. A blinking boot LED is not a recording acknowledgment. Define and
test nonambiguous LED patterns in board docs for recording, recovery, pairing,
storage/camera fault, and update; do not make color the only distinction.
The Sense SD CS and user LED may share GPIO21: no independent Blink/heartbeat
may toggle a live CS. Qualify a separate indication or arbitration for the actual
revision. GPIO0 is BOOT, not the former camera XCLK; approve its gesture/reset
behavior before using it for local access.

## 3. Scheduling, memory and capture

Start with two driver frame buffers in PSRAM and a queue of at most two frame
references, then measure. If this exceeds the actual memory/timing budget,
reduce concurrency and document the tradeoff. Every acquired frame has exactly
one owner and one return-to-driver action on success, drop, fault or shutdown.
The recorder may not hold buffers while hashing network data or waiting for an
HTTP client. Avoid whole-segment buffers.

Capture timestamps use the best validated acquisition timestamp from the pinned
driver, cross-checked against monotonic boot time. Requested FPS is not proof of
delivery. Bound frame size and inspect JPEG SOI/EOI/dimensions. Reject invalid or
oversized frames and record counters. Fix image profile at a segment boundary.
Do not change JPEG quality frame by frame to pretend to meet a constant bitrate.
Prefer profile selection based on representative tests; advertise lower quality
only as a named selected mode, not an invisible change.

The SD writer has higher service priority than preview/sync. Use actual measured
priorities/stack budgets, not hardcoded core affinity copied from another board.
Do not busy-spin or mask watchdog failures. Measure internal heap minimum,
largest free block, PSRAM usage, task stack high-water marks, queue pressure,
write-latency distribution and longest stall. Slow-card behavior must be bounded:
drop frames with visible counters and fault if progress stalls beyond the
qualified timeout. No unbounded retry or queue expansion.

## 4. Storage ownership and catalog

Mount genuine 32GB FAT32 through the Sense SPI/SDSPI socket with explicit
no-format behavior and reviewed bus/CS mapping. Use 64-bit
capacity/cumulative accounting. Only the storage coordinator mutates clip files,
catalog, active records, pin metadata and tombstones. Serialize pruning with
leases and event changes. File handles and scan page sizes are bounded.

Use [media format](media-format.md) exactly. Reserve `capture_order` durably
before opening an active clip; recovery takes the maximum reserved/finalized
value plus one. Keep an append journal of reservations/catalog operations with
bounded record length/checksum and compact it safely. Rebuild from valid
manifests when the journal is unusable, preserving corrupt material for diagnosis.
Do not use UTC or FAT modification timestamps to decide which recording is oldest.

Maintain incremental media/index SHA-256 so normal finalization does not reread
the entire clip. Startup recovery may recompute hashes in bounded chunks. A
manifest is published last. A clip is exposed only when all required files,
lengths and manifest schema validate; full CRC/hash validation is mandatory on
recovery and transfer verification. Background integrity checks yield to recording.

A healthy boot uses the committed catalog and lightweight manifest/size checks,
not a full-card rehash. Fully verify active/suspicious clips during recovery;
scan/rebuild a damaged catalog incrementally with bounded memory and visible
progress. The ≤10s boot target applies to a healthy catalog, not damaged-card
recovery. Unverified suspicious clips remain absent from downloads until checked.

## 5. Retention algorithm

Compute `pool = floor(measured_filesystem_total_bytes * 0.85)`. Count allocated
filesystem bytes for originals, indexes, manifests, active files, catalog and
pin metadata, rather than summing JPEG payload lengths alone. The remaining
15% is a free-space reserve, not a hidden protected-event pool.

Stage 1 uses the pool for rolling clips. On nominal 32GB the 85% pool is 27.2GB;
Stage 3 permits at most 2,000,000,000 protected bytes inside it, further reduced
when actual capacity/headroom requires. Pins subtract from rolling capacity.
Report the applied limit; backend quota is separate. The nominal 72h ceiling
is ~0.84Mbit/s total before pins/headroom or ~0.778Mbit/s with full 2GB protection.
Use ≤0.75Mbit/s total allocated growth as an unverified capacity-screening target,
not a proven useful JPEG mode. Measure real retention/quality first; PR-03 is not
passed unless useful recorded duration reaches 72h at the advertised pin budget.
Never silently reduce quality/FPS/resolution or advertise 72h to conceal failure.

Before starting a segment maintain within-pool headroom for two maximum allocated
complete bundles, including payload/index/manifest/active metadata, cluster-rounding,
catalog growth and a qualified margin. 512MiB covers only the two payloads and
is insufficient as the complete threshold. A smaller workload-specific bound
requires separate explicit qualification. Evict
oldest eligible finalized clips by `capture_order` until the threshold holds.
Never evict active, protected or leased clips. Create a deletion tombstone,
remove the catalog entry, delete its files and replay interrupted deletion on
boot. Account space only after the filesystem reports it reclaimed.

If nothing is evictable, deny new leases and pins, shed transfer/preview work,
close the active segment safely when headroom is exhausted, enter `storage_full`
and expose `NO_EVICTABLE_SPACE`. Resume automatically after leases expire or the
owner unpins/frees space. Never silently overwrite protected clips. The app shows
the resulting coverage gap. No deletion endpoint for arbitrary original clips
is required in v1; rolling pruning and explicit card maintenance cover that scope.

## 6. Power, settings and time

The owner removes the camera and unplugs its pack for external charging.
The XIAO physically has an onboard charger: disconnect the pack before USB
service unless isolation is reviewed; firmware must not claim that charging is
physically disabled by this policy. Qualify the BAT input/onboard regulation,
connector, switch/cutoff and peaks rather than inheriting a 5V boost. Battery
removal is a power-loss case: test recovery/auto-record on reconnection. Use an
approved shutdown action if available; never assume a final flush after unplug.
No owner-facing in-camera charge state machine is required. Battery voltage or
percentage stays unavailable without a reviewed measurement/calibration path.

Shutdown/low-power indications trigger best-effort close/sync and an explicit
state. A hardware power switch may remove power abruptly, so recovery remains
required. Firmware thresholds derive from the approved power circuit and battery,
not an assumed universal voltage. ADC battery reporting is calibrated and optional.
Do not implement a percentage gauge before pack characterization.

NVS configuration includes schema version, profile ID, settings revision,
network configuration and identity references. Reject invalid values before
writing. Use migration tests, atomic commit semantics and recovery defaults that
do not erase ownership or reset to a public password. Keep card files usable
across compatible firmware updates. Persist only needed counters to limit flash
wear; high-rate metrics remain RAM/host telemetry.

Use monotonic microseconds internally. UTC is unknown on cold boot until an
accepted source exists. When UTC mapping changes, close the current segment and
begin another; retain old manifests. No recording wait for SNTP. Clock uncertainty
is recorded and the app must not imply a reliable timeline when UTC is absent.

## 7. Networking and local ownership, Stage 2

Implement [interfaces](interfaces.md) after the core recorder passes its gate.
Start with Wi-Fi off and record to SD. A deliberate physical action on a
qualified control opens local access using the unique-credential SoftAP or a
previously configured station network. No remote wake/discovery is possible
while off. Qualify the chosen local-access control against the XIAO BOOT/strap,
SD CS/LED and expansion wiring; no inherited classic-board button assignment.

Proposed local-access limits are 300s since last authenticated activity and a
15min absolute cap. Accepted authenticated traffic, including an active transfer,
resets only the idle timer. Expiry closes streams/handles, turns off Wi-Fi and
keeps recording; reopening requires physical action. Checkpoint/resume transfers.
An in-progress OTA must complete its bounded validation/reboot path or safely
cancel/resume recording before radio shutdown; never abandon an update state.

An unowned device also opens a separate 120s ownership-claim window. Existing
owners use their stored token without reclaiming. Pairing success does not end
an active local-access session. Record states visibly; no universal setup AP or
BLE provisioning is required.

Limit HTTPS sessions, body sizes, timeouts and allocations. Limit preview to
one client and 2FPS, copy/release a frame promptly, and stop preview under writer
pressure. Downloads read finalized files in bounded chunks through the storage
scheduler. A five-minute lease prevents prune races; deny renewal when necessary
and return the documented lease/eviction errors. Wi-Fi reconnect backoff yields
to capture; app reconnection does not reset the recorder.

Initially allow one TLS connection total, shared between control, preview,
transfer or update. Pause preview before another action needs that slot.
Qualify later concurrency with camera+SD measurements; never remove TLS/auth
silently to fit memory or reduce power.

Provisioning fixtures use fake secrets only. Factory identity and certificate
generation requires an explicit identified device/provisioning assignment.
Without flash encryption, a determined physical attacker may extract local
identity data; do not claim otherwise. Signed OTA, TLS and local token auth do
not encrypt removable SD originals.

## 8. OTA and optional Stage 3 extensions

Plan dual OTA app slots plus OTA data, NVS and recovery needs within detected
flash (XIAO Sense documented baseline 8MB, verify on the actual unit). Prove signed-image slot fit with
headroom using the actual build before advertising OTA. A single large app
partition does not meet dual-slot rollback requirements. If it cannot fit,
report a blocked gate and obtain a scope/board decision rather than removing
signatures, TLS or rollback. Never copy classic 4MB, N16R8 or Plus partition assumptions.
OTA uses a suitably charged qualified pack or separately reviewed isolated
bench power, not an assumed in-camera charging supply. Do not invent charge
percentage telemetry; retain interruption/rollback tests for pack loss.
Implement the gated envelope and SDK
signature verification, staged update, first-boot self-test and rollback from
the API spec. Failed update must preserve camera settings, identity and SD data.

Event protection is a metadata transaction outside original manifests. Atomic
multi-clip pinning checks the quota before any clip is pinned and handles clips
already evicted. Overlapping events share reference counts and do not double-count
bytes. Backend upload acknowledgment and local pin are separate states.

Direct device-to-backend sync is optional after app upload works. Use a scoped
upload token and validated HTTPS endpoint, no self-issued global admin token.
Upload one finalized clip in bounded chunks and throttle/pause on writer
pressure, low battery or connectivity loss. Retry with HEAD offsets and verify
backend durable commit before marking synced. Never delete a clip simply because
it was uploaded; rolling/pin policies remain independent.

An optional IMU must not block recording if absent. A future data format needs
timestamps, calibration, sensor orientation, sample-rate and synchronization
tests; it is not part of media v1 or a required release deliverable.

## 9. Firmware acceptance mapping

| ID | Required tests |
| --- | --- |
| FW-01 auto recording | Healthy boot, no Wi-Fi, no phone, backend down, restart |
| FW-02 bounded capture | Queue saturation, invalid JPEG, allocation failure, SD stall, preview pressure |
| FW-03 media/recovery | Golden fixtures, partial write at each step, CRC/hash mismatch, quarantine |
| FW-04 retention | 32GB arithmetic/actual rollover and measured useful window; 72h is a separate unverified goal until real soak passes |
| FW-05 truthful status | No card, exFAT, full/pinned/leased, camera error, unknown UTC, ADC absent |
| FW-06 secure networking | Pair window, bad pin/token, replay/stale settings, network reconnect |
| FW-07 update recovery | Signature/hardware/length failure, interrupted OTA, first-boot failure/rollback |
| FW-08 power/thermal | Approved rail transitions/runtime/temperature tests on identified hardware |

Host tests, cross-compilation and hardware verification are separate evidence.
Only the last requires and can demonstrate actual peripheral behavior.

## 10. Build and installation distribution

Implementation of PR-20/PR-21 is specified by the
[Stage 0.9 CI/release plan](../plans/0.9-firmware-ci-release.md). Every PR builds
its exact head SHA with a hash-bearing build/artifact name. Successful main
builds create immutable `firmware-main-<sha12>` tags and complete installation
Releases with generated flash layouts, supporting images, manifests/checksums,
instructions and cross-platform installer scripts. The pipeline remains planned.

Keep semantic firmware version separate from source/build identity. Initial
bootstrap Releases are prototype pre-releases and do not implement recording
or signed device OTA. USB factory/recovery installation is separate from the
Stage 2 OTA contract; neither tag creation nor checksums replace signatures.
