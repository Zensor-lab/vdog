# Decision and open-question register

Status as of 2026-11-16. **Confirmed** means visible user direction; **baseline**
means a proposed engineering choice; **gated** requires evidence before dependent
implementation. Record new evidence and rationale here without copying chat logs.

| ID | Status | Decision / question | Owner and resolution point |
| --- | --- | --- | --- |
| D-01 | Confirmed | China procurement, CNY costs, below 150 excluding SD/harness | Hardware quote package 0.4; clarify BOM versus retail before manufacturing commitment |
| D-02 | Confirmed, revised | XIAO ESP32S3 Sense and 32GB-first replace classic AI-Thinker/128GB | Owner direction 2026-11-16; actual base/Sense/sensor/card identity at 0.3/1.2 |
| D-03 | Baseline | Wi-Fi only; no LTE/GPS | Lead; reconsider only by scope change |
| D-04 | Gated | XIAO Sense revision, shipped sensor/lens and 8MB flash/8MB octal PSRAM | Identify OV5640/OV3660 transition or qualified legacy sensor; review SPI/CS/LED/control pins, not classic wiring |
| D-05 | Gated | 72h useful retained footage remains a goal, unverified on 32GB | 27.2GB nominal pool allows ~0.84Mbit/s before pins/headroom; quality and real retention evidence required |
| D-06 | Baseline | Flutter app, Rust backend | Freeze toolchain/dependencies at 0.2; no React app substituted |
| D-07 | Upstream support verified; project unqualified | PlatformIO board seeed_xiao_esp32s3 lists ESP-IDF and Arduino | Candidate official platform 8.0.0; freeze SDK/compiler/camera/config and prove build; finding a board entry does not close 0.2 |
| D-08 | Baseline revised | Genuine 32GB SDHC FAT32 on Sense SPI socket; no autoformat | Actual card/model/allocation/rollover; larger/exFAT cards separately qualified |
| D-09 | Baseline | Concatenated JPEG + indexed timestamps + immutable manifest | Versioned media v1 contract and golden fixtures before recorder/player |
| D-10 | Baseline | Device HTTPS with QR-pinned unique certificate and physical pairing window | Provisioning usability/security spike before app implementation |
| D-11 | Baseline | Off-device two-pass vid.stab EIS, originals retained | Twenty to thirty representative clips; reject if detail is degraded |
| D-12 | Confirmed target, gated implementation | Nominal 3.7V 1000mAh, about 1–2h per charge | Protected pack through qualified XIAO BAT/power circuit, removable connector, external charger, USB isolation and measured runtime/heat |
| D-13 | Gated | Final recording profile and quality rubric | Agree ground-object readability evaluation in 0.5; do not lower quality silently |
| D-14 | Gated | Mobile minimum OS versions and required test devices | 0.2 platform-support matrix based on actual plugins/devices |
| D-15 | Gated | Public distribution license choices for new hardware/design and third-party codecs | Review existing LICENSE and third-party notices before first public artifact release |
| D-16 | Baseline | Backend initially receives app-uploaded clips; direct device sync later | Device sync only after storage/CPU/power regression evidence |
| D-17 | Baseline | Manual event marking; no automatic hazard classifier | Optional IMU impact research is distinct from validated danger detection |
| D-18 | Gated | Signed dual OTA slots in detected XIAO flash, trust keys and provisioning | Baseline 8MB is not Plus/N16R8; actual image/identity/NVS budgets and rollback tests |
| D-19 | Confirmed policy, proposed timers | Mainly SD recording; Wi-Fi off until physical local access | 300s authenticated-idle/15min absolute cap proposed; no remote wake; 120s claim independent |
| D-20 | Confirmed workflow | Remove whole camera, unplug battery and charge separately | Stock board has onboard charger; disconnect pack before USB service unless isolation is reviewed; no added charge/load-sharing function required; charger remains in kit cost |
| D-21 | Confirmed target, gated fit | Owner's dog below 8kg, chest harness mount | Exact weight/chest/harness measurements before fit signoff; larger dogs require separate geometry/angle checks |
| D-22 | Confirmed scope | Dry-weather prototype; weather protection later | Basic electronics/pack protective housing still required before wear; no waterproof/IP claim |
| D-23 | Proposed engineering budget | Scale local protected clips to ≤2,000,000,000 bytes for 32GB | Inside 85% pool, never additional free storage; smaller safe limit allowed and reported; backend quota independent |

The [current hardware review](hardware-decision-review.md) and
[PlatformIO check](platformio-support.md) record the 2026-11-16 update. Earlier
N16R8 and classic AI-Thinker choices are historical; neither is an active fallback
to substitute without a decision. Inherited 128GB/8GB protection/3Mbit/s capacity
assumptions and classic 5V-boost/SDMMC wiring are superseded.

No question here blocks writing documentation. Hardware purchase, PCB fabrication,
public deployment and device operations need their own concrete implementation
scope and, where required by AGENTS.md, an identified authorized device/port.

## Change procedure

1. Cite the affected requirement and evidence showing why the baseline fails.
2. List alternatives with cost, performance, privacy and compatibility effects.
3. The lead resolves cross-stack changes; record explicit user direction when
   changing confirmed cost, SoC, card priority or product scope.
4. Update contracts, fixtures, affected specs, implementation packages and tests
   together. Introduce migration/version handling for already-written files.

An unavailable test is `UNVERIFIED`; a measured failure is a failed gate. Neither
becomes a pass because another stage can proceed independently.
