# Decision and open-question register

Status as of 2026-11-07. **Confirmed** means visible user direction; **baseline**
means a proposed engineering choice; **gated** requires evidence before dependent
implementation. Record new evidence and rationale here without copying chat logs.

| ID | Status | Decision / question | Owner and resolution point |
| --- | --- | --- | --- |
| D-01 | Confirmed | China procurement, CNY costs, below 150 excluding SD/harness | Hardware quote package 0.4; clarify BOM versus retail before manufacturing commitment |
| D-02 | Confirmed | ESP32-S3 and 128GB SD first priority | Firmware/hardware feasibility 1.1–1.8 |
| D-03 | Baseline | Wi-Fi only; no LTE/GPS | Lead; reconsider only by scope change |
| D-04 | Baseline | WROOM-1-N16R8 + OV2640; IMU footprint unpopulated | Exact board revision/pin table/quotes at 0.3, then bench verification |
| D-05 | Gated | 72h useful MJPEG retention | Data/quality matrix and 72h soak; never accept math alone |
| D-06 | Baseline | Flutter app, Rust backend | Freeze toolchain/dependencies at 0.2; no React app substituted |
| D-07 | Gated | PlatformIO ESP-IDF on selected N16R8 board | Prove flash/PSRAM/camera/SD; record exact versions and memory overrides |
| D-08 | Baseline | Preprepared FAT32 128GB; no automatic formatting | exFAT separately gated; owner must back up before card preparation |
| D-09 | Baseline | Concatenated JPEG + indexed timestamps + immutable manifest | Versioned media v1 contract and golden fixtures before recorder/player |
| D-10 | Baseline | Device HTTPS with QR-pinned unique certificate and physical pairing window | Provisioning usability/security spike before app implementation |
| D-11 | Baseline | Off-device two-pass vid.stab EIS, originals retained | Twenty to thirty representative clips; reject if detail is degraded |
| D-12 | Gated | Battery capacity/runtime, total mass, fit, enclosure and heat limits | Electrical/mechanical design and bench evidence before any animal use |
| D-13 | Gated | Final recording profile and quality rubric | Agree ground-object readability evaluation in 0.5; do not lower quality silently |
| D-14 | Gated | Mobile minimum OS versions and required test devices | 0.2 platform-support matrix based on actual plugins/devices |
| D-15 | Gated | Public distribution license choices for new hardware/design and third-party codecs | Review existing LICENSE and third-party notices before first public artifact release |
| D-16 | Baseline | Backend initially receives app-uploaded clips; direct device sync later | Device sync only after storage/CPU/power regression evidence |
| D-17 | Baseline | Manual event marking; no automatic hazard classifier | Optional IMU impact research is distinct from validated danger detection |
| D-18 | Gated | Exact flash partitions, OTA trust-key custody and manufacturing provisioning | Measured firmware sizes; two OTA slots and NVS budget before OTA work |

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
