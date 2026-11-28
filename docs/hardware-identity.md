# Hardware identity record — prototype A (package 1.2)

Status: **template (Part A)**. Every device-derived row is `PENDING` until
the owner supplies the board marking photos (0.3 check 1) and the bench
transcript is recorded (package 1.2 Part B, gated by
[bench-assignment.md](bench-assignment.md)). Nothing in this file may be
transcribed into a claim of physical verification before that.

Evidence tags follow the `vdog_mem` contract (plan 1.2 lead finding 2):
**MEASURED** = read from the chip at runtime; **CONFIGURED** = the image's
own build configuration (proves only how the image was built); **PHOTO** =
transcribed from an owner-supplied marking photo; **PENDING** = not yet
recorded. A CONFIGURED value can never be reported as detected.

## 1. Unit identity

| Item | Value | Source | Status |
| --- | --- | --- | --- |
| Unit tag (opaque label) | `PENDING` | owner photo of silk/label | PENDING |
| Base board marking | `PENDING` | owner photo (bottom silk) | PENDING |
| Sense expansion board | `PENDING` | owner photo (camera/ribbon presence) | PENDING |
| Camera module + ribbon | `PENDING` | owner photo; sensor probing is **1.3** (deviation recorded in implementation-plan §1.2) | PENDING |
| Flash part marking | `PENDING` | owner photo (can be read via `esp_flash_read_id` only in a Part B session) | PENDING |
| PSRAM marking | `PENDING` | owner photo — must distinguish the documented XIAO ESP32S3 Sense (8 MB flash / 8 MB **octal** PSRAM) from **Plus / N16R8 / classic** variants | PENDING |
| Board revision determination | `PENDING` | silk + `esp_chip_info` revision (Part B) | PENDING |

The acceptance baseline for Stage 1 is **8 MB flash / 8 MB octal (OPI)
PSRAM** — not the ESP32-S3 Sense **Plus**, not an **N16R8** package, not a
classic quad-PSRAM board. `vdog_mem_check_baseline()` rejects
Plus/N16R8-shaped, 4 MiB-flash, no-PSRAM and quad-only-PSRAM reports with a
specific code + field (host-proven, plan 1.2 acceptance 2).

## 2. Sanitized device report (filled by the Part B session)

The boot console emits the two lines below per boot (`firmware/src/main.c`,
after the 1.1 board line). They are the ONLY identity data this firmware
logs: the identity struct is structurally unable to hold a full MAC, eFuse
raw values or serial numbers.

```text
mem: flash_size=8MB[measured] flash_mode=qio[configured] flash_freq=80m[configured] psram=8MB[measured:init-ok] psram_mode=opi[configured] psram_speed=80m[configured]
identity: chip=esp32s3 rev=<major>.<minor> mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:<tail-lo>:<tail-hi>
```

(Exact strings are host-pinned by `test_vdog_mem` / `test_vdog_recovery`.
`mac=` renders only the last two bytes; the board tag is omitted until
section 1 records a unit label.)

| Row | Value | Tag | Status |
| --- | --- | --- | --- |
| `mem:` line (verbatim) | `PENDING` | MEASURED + CONFIGURED per field | PENDING |
| `identity:` line (verbatim) | `PENDING` | chip info read-only; MAC tail only | PENDING |
| Boot-mode drill transcript | `PENDING` | per-line `boot:0x..` word + `vdog_recovery_classify` result; each line recorded verbatim | PENDING |
| Strap evidence (finding 1b) | `PENDING` | `boot:0x..` values + reset reason for each of: power-on, BOOT-held download entry, BOOT release, reset button | PENDING |
| Reset reason | `PENDING` | `esp_reset_reason()` wording recorded in the transcript | PENDING |
| Port identity (finding 6) | `PENDING` | exact `/dev/cu.usbmodem*` path per attach **and re-identified after every BOOT/reset transition** | PENDING |

Rules (from the plan; restated here so a Part B transcript can be checked
against them):

1. No rail-voltage or current-draw row may be completed — the bench has no
   confirmed multimeter/current-limited supply (UNVERIFIED, plan §7).
2. No GPIO21 claim: SD-CS vs user-LED sharing stays unresolved until
   0.3/E07 (Jada's sign-off) is recorded here.
3. The microphone stays uninitialized; no audio row may ever appear.
4. Any sensor probing is 1.3 work, not Part B of this package.
