# Product requirements

Status: implementation baseline revised 2026-11-09. Requirement IDs below are
stable; acceptance requires recorded evidence under [validation](../validation.md).

## 1. Purpose and motivation

vdog is an affordable, repairable, harness-mounted dog camera. It records the
dog's surroundings locally so an owner can review what happened during a walk,
including objects near the ground. Useful original footage, reliable storage,
and affordable ownership take priority over resolution labels or feature count.

The open-source goal is to let owners inspect how recording and retention work,
assemble and repair devices, adapt mounts, and keep control of their footage.
Basic recording and local review must not depend on a vendor account, paid
subscription, or an operating hosted service. This is the project motivation
derived from the research discussion; it is not a claim that the camera prevents
injury, identifies poison, or guarantees incident evidence.

## 2. Source and decision confidence

Source: [Research Dog Camera Plan](chatgpt-conversation://6aef12d8-967c-83ed-be5e-870d042384f1).
The connected reader returned five recent user/assistant turns, with no older
cursor and no attachments. Earlier requirements referenced inside those replies
were unavailable. They are not silently reconstructed here.

The owner's 2026-11-09 follow-up selected classic AI-Thinker ESP32-CAM + OV2640,
nominal 3.7V 1000mAh battery, about 1–2h per charge and mainly SD recording with
Wi-Fi when needed. This supersedes the S3 direction. See the
[hardware decision review](../hardware-decision-review.md) for evidence and gates.
The same-day follow-up confirms separate charging of the unplugged battery after
removing the whole camera, chest mounting for the owner's small dog reported
below 8kg, and dry-weather-first use. A later weather-protective enclosure is a separate revision.

| Classification | Decision | Treatment |
| --- | --- | --- |
| Explicit user direction | Develop/procure in China; use Chinese prices | CNY is the cost unit; obtain supplier quotes in Stage 0 |
| Explicit user direction | Price below 150 excluding SD card and harness | Interpret as production hardware BOM < CNY150, as the discussion did; retail price is not validated |
| Latest explicit user direction | Classic AI-Thinker ESP32-CAM + OV2640, nominal 3.7V 1000mAh, about 1–2h per charge | Exact board/pack and measured runtime remain gated |
| Continuing user priority | 128GB SD first priority | Card qualification and retention target remain unchanged |
| Latest explicit user direction | Mainly SD recording; Wi-Fi when needed | Radio off by default; physical local-access session |
| Latest explicit user direction | Remove camera and unplug pack for external charging | No onboard charging/load-sharing or record-while-charging requirement |
| Latest explicit user direction | Small dog first, chest harness mount, dry weather | Actual fit measured before wear; basic housing required; weather sealing later |
| User question / assistant proposal | Wi-Fi only, no SIM | v1 engineering baseline; cellular excluded from current implementation |
| Superseded baseline | S3-WROOM-1-N16R8 prototype | Alternative only; its pins/memory settings do not apply to ESP32-CAM |
| Assistant proposal | Automatic recording, 72h rolling retention | Primary engineering acceptance target, subject to image-quality/capacity gate |
| Assistant proposal | Flutter app then Rust backend | Proposed software architecture used in these specifications |
| Assistant proposal retained | Mechanical damping; off-device EIS; IMU optional | Baseline; no real-time onboard EIS |
| Superseded proposals | P4 first, 256GB first, mandatory IMU, cellular in Stage 3, higher BOM | Not v1 requirements; alternatives need a recorded decision |

## 3. Users and principal journeys

- Owner: inserts a prepared card, powers the camera, confirms recording status,
  wears it on a suitable harness, and reviews/downloads recordings afterward.
- DIY builder: follows a versioned BOM, wiring and enclosure instructions;
  verifies memory, storage, power, and recording before supervised use.
- Self-hosting owner: optionally sends selected clips to their own backend,
  creates playable exports, tries stabilization, and marks important events.
- Maintainer: can reproduce builds, run simulated faults, trace requirements to
  tests, and issue a signed update without breaking stored footage.

## 4. Requirements

| ID | Requirement | Acceptance anchor |
| --- | --- | --- |
| PR-01 | Start recording automatically with a valid card, independent of Wi-Fi/app/backend | Bench boot and offline tests |
| PR-02 | Use classic AI-Thinker ESP32-CAM + OV2640 with a genuine 128GB microSD as the first prototype | Exact board/memory/card evidence; no inherited S3 pin map |
| PR-03 | Preserve a rolling target of 72 hours of captured footage at an accepted quality profile | Full retention soak, not a capacity extrapolation alone |
| PR-04 | Required hardware-kit BOM < CNY150 excluding card and harness, including external charger | Dated itemized quotes, quantity, explicit accessory basis and contingency |
| PR-05 | Record in bounded segments; recover finalized footage after power loss | Media and fault tests |
| PR-06 | No network required for recording; Wi-Fi range limits remote features | Offline and reconnect tests |
| PR-07 | Flutter app pairs locally, shows truthful status/preview, downloads/resumes, and plays originals | Android and iOS device acceptance |
| PR-08 | Authenticated, signed, hardware-compatible OTA with recovery | Negative update and rollback tests |
| PR-09 | Optional Rust backend stores originals, produces exports, and runs post-processing EIS | Job and integrity acceptance |
| PR-10 | Retention, faults, download state, events, and storage exhaustion must be visible | Firmware/app state fixtures |
| PR-11 | Physical fit, battery/power design, and thermal behavior pass bench gates before animal use | Hardware evidence and release checklist |
| PR-12 | Footage and credentials remain owner-controlled; no public media endpoint or default password | Security validation |
| PR-13 | Publish reproducible source, build/setup docs, BOM and design artifacts as available | Release manifest and license review |
| PR-14 | An event pin cannot silently overwrite another pin or silently disable new recording | Quota and storage-full tests |
| PR-15 | Preserve original footage; stabilized/transcoded outputs are separate derivatives | Hash and metadata tests |
| PR-16 | Use nominal 3.7V 1000mAh and target about 1–2h per charge | Proposed minimum 1h/target 2h useful recording; actual pack/load/runtime measured |
| PR-17 | Record with Wi-Fi off by default; enable it through physical local access | No remote-wake assumption; recording survives radio/session transitions |
| PR-18 | Charge the unplugged removable pack externally after taking camera off harness | Compatible separate charger; no onboard charging; unplug/reconnect/recovery tests |
| PR-19 | Design first for the owner's below-8kg dog's chest harness in dry weather | Exact measurements, fit/ground view and basic housing before wear; no universal small/large-dog or weather-rating claim |

## 5. Performance and capacity targets

Initial measurement profile: JPEG, 640×480 at nominal 15 FPS; compare 800×600
and reduced frame rates only through the feasibility matrix. These are proposed
test profiles, not proven ESP32-CAM capabilities. Resolution/FPS/JPEG quality are fixed
within a segment and included in its manifest. Do not advertise 720p/1080p or a
constant bitrate before measurement.

128GB means 128,000,000,000 nominal bytes. With 15% reserved, the theoretical
recording pool is 108,800,000,000 bytes. For 259,200 seconds (72h):

```text
maximum average total recording rate = pool_bytes * 8 / 259200
                                     = 3,358,024 bit/s (about 3.36 Mbit/s)
at 15 FPS, video-only upper bound      = about 27,984 bytes/JPEG
```

Filesystem allocation, frame indexes, manifests and variability consume part of
that budget. Use the smaller measured filesystem capacity rather than nominal
card capacity in real calculations. At Stage 3, up to 8,000,000,000 bytes of the
pool may hold protected clips; the nominal rolling remainder is then 100.8GB,
or approximately 3.11 Mbit/s. Start with a **3.0 Mbit/s total rolling-write target**
including metadata and allocation overhead. This leaves only limited margin and
must be validated against real high-motion scenes. More protected footage or a
smaller measured card can reduce the rolling window further.

The 72h target describes retained **recorded duration while powered**. It is not
72h of battery runtime, nor 72h of wall-clock coverage across power-off periods.
The selected nominal pack is 1000mAh at 3.7V; runtime targets about 1–2h and is
unmeasured. No device mass, water-resistance rating, low-light performance,
or breed-size suitability has been established. Small-dog-first is a design
priority, not proof that the same mount fits larger dogs. Weight, chest geometry,
harness strap spacing, assembled mass, camera angle and movement need measurement.
Dry-weather-first does not authorize bare electronics during wear: the basic
housing must restrain the pack, isolate electronics and secure connectors before
field use. Later weather sealing requires new thermal and ingress validation.

Proposed firmware targets: boot to first recorded frame ≤10s on a healthy card;
60s segments; periodic payload/index sync ≤1s; finalized segment cutover gap
≤2 nominal frame periods under bench load. Measure and document all misses.
Power failure can damage FAT metadata beyond the last sync; the sync interval
is not a guarantee that loss is limited to one second.

## 6. v1 exclusions

No LTE/SIM/GPS, microphone/audio, screen, speaker, always-on live cloud stream,
real-time onboard EIS, autonomous hazard/poison diagnosis, mandatory IMU,
automatic emergency dispatch, or vendor subscription. BLE is not required for
v1 setup. On-demand low-rate Wi-Fi preview must yield to recording. Notifications
are optional Stage 3 functionality while connectivity exists.

If ESP32-CAM cannot meet the quality/capacity/runtime/OTA gate, report the measured failure and
offer explicit tradeoffs (quality/FPS/retention/card size/SoC/cost). Do not quietly
weaken the requirement, switch to P4, or claim that smooth stabilized video
restores blurred or missing detail.
