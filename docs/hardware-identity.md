# Hardware identity record — Prototype A (Seeed XIAO ESP32S3 Sense)

Status: **TEMPLATE (package 1.2 Part A, plan A6).** Every device-derived row
below is `PENDING` until the owner's board-marking photos (0.3 check 1) are
transcribed and the Part B drill actually runs. Part A asserts **no**
physical hardware facts: nothing in this file was read from a device, and
no row may be filled without the evidence column being satisfied. When the
sanitized device report is filled, mark each row `DONE` only if its command
actually ran in Part B (DEVICE evidence discipline, plan §6).

Related: [`bench-assignment.md`](bench-assignment.md) (authorized bench
scope), [`hardware-decision-review.md`](hardware-decision-review.md)
(documented baseline: 8 MiB flash / 8 MiB octal PSRAM — **not**
Plus/N16R8/classic), [`plans/1.2-assignment.md`](plans/1.2-assignment.md)
(§6 Part B procedure).

## 1. Unit identity — markings to transcribe from owner photos

| Item | Value | Evidence source | Status |
| --- | --- | --- | --- |
| Base board marking (silkscreen part no.) | PENDING | owner photo of board underside | PENDING |
| Sense expansion board (present? marking) | PENDING | owner photo of stack/camera side | PENDING |
| Camera module marking + ribbon orientation | PENDING | owner photo of module back + ribbon seat | PENDING |
| SPI flash package marking (die/part no.) | PENDING | owner macro photo of flash can | PENDING |
| PSRAM package marking (transcribe from owner photos) | PENDING | owner macro photo of PSRAM can | PENDING |
| Board revision determination (which XIAO Sense revision) | PENDING | determination from the photos above | PENDING |

Constraints on this table:

- The camera module identity may be recorded from **photos only** in 1.2;
  sensor probing needs camera init, which is package **1.3** (recorded
  deviation, lead finding 4 — the 1.3 plan carries "correct sensor
  identity" as acceptance).
- Flash/PSRAM markings must corroborate (or refute) the documented
  baseline; a Plus/N16R8/classic shape is an escalation, not a fill-in.
- The pin-map candidate list (`hardware/prototype-a/pin-map.csv`) is
  CANDIDATE_NOT_APPROVED and is NOT evidence for this record.

## 2. Sanitized device report — filled from the Part B capture

Rendering contracts live in the portable core and are host-pinned
(`firmware/test/test_vdog_mem/`, `test_vdog_recovery/`): the memory line
carries a per-field MEASURED-vs-CONFIGURED source tag and can never present
a configured value (e.g. OPI mode) as detected; the identity line renders
the MAC **tail only** (`mac=**:**:**:**:xx:xx`) — the struct cannot even
store a full MAC or eFuse raw data.

| Report row | Source | Expected shape | Status |
| --- | --- | --- | --- |
| `vdog_mem_format_detected` line | boot console (Part B) | `flash_size=8MB[measured] flash_mode=qio[configured] flash_freq=80m[configured] psram=8MB[measured:init-ok] psram_mode=opi[configured] psram_speed=80m[configured]` — tags rendered per field | PENDING |
| `vdog_identity_format` line | boot console (Part B) | `chip=esp32s3 rev=M.m mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:xx:xx board=<opaque tag or absent>` | PENDING |
| Boot-mode classification | capture (Part B) | `normal` / `download` / `usbjtag` / `unknown` per line, per `vdog_recovery_classify` | PENDING |
| ROM `boot:0x..` strapping value (normal boot) | capture (Part B) | verbatim ROM line text; compare vs expected normal-boot value | PENDING |
| ROM `boot:0x..` strapping value (download mode) | capture (Part B, BOOT drill) | verbatim ROM line text; compare vs expected download value | PENDING |
| Reset reason | capture (Part B) | verbatim; mismatch = stop, record verbatim, escalate | PENDING |
| Strap-conflict observation (clean boot, no brownout/reset loop) | capture (Part B) | observed; desk-side half already pinned by `core/vdog_straps` host tests | PENDING |
| No-microphone-initialization check | capture + code review (Part B) | no mic init in boot log; GPIO39/41 stay unclaimed, 40/42 camera-candidate only | PENDING |

Rules (plan §6/§7):

- Every MEASURED tag must come from a runtime chip readback (the adapter's
  read-only queries); CONFIGURED tags come from the image's own build
  configuration. Never restate a configured value as measured, in this
  table or in logs.
- Sanitized material only: no full MAC, no eFuse raw values, no serials.
- Rail voltages / current draw remain **UNVERIFIED** (bench equipment not
  confirmed by the owner) and are not rows here.

## 3. Provenance

- Filled by: PENDING (owner photos + Part B operator).
- Part A code basis: `opencode/1.2-board-bringup` (memory/recovery/strap
  core modules, adapters, host suite).
- Photo handoff obligation: owner (board marking photos, 0.3 check 1) →
  transcribed here before any Part B flash (wake condition 1, plan §6).
