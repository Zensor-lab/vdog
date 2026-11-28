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
identity: chip=esp32s3 rev=<major>.<minor> mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:<second-to-last-octet>:<last-octet>
```

(Exact strings are host-pinned by `test_vdog_mem` / `test_vdog_recovery`.
`mac=` renders the stored 16-bit tail as its two octets in MAC order
(0x5e6f → `5e:6f`), OUI masked; the board tag is omitted until
section 1 records a unit label.)

### 2.1 OTA self-test check-in (Item #17 P1-4; firmware behaviour record)

With `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` (on in the proto environment)
every boot ends with exactly ONE OTA line from `firmware/src/main.c`:

```text
ota=confirmed (board+memory health gate passed)
ota=not-confirmed (board_ok=<yes|no> memory_ok=<yes|no>) — rollback NOT cancelled
```

The decision is the pure host-tested rule `vdog_ota_should_confirm()`
(`firmware/core/vdog_recovery.c`, pinned by `test_vdog_recovery`): the
rollback check-in happens ONLY when BOTH the board-identity verdict
(`vdog_board_validate`) and the memory-baseline verdict
(`vdog_mem_check_baseline`) passed. An unhealthy image leaves rollback armed,
and the bootloader marks the pending-verify entry `ABORTED` on the next
reset and reverts to the last valid slot (pinned ESP-IDF 6.1.0
`bootloader_utility.c`, source-verified — host evidence; the live transcript
below is PENDING).

Two OTA-metadata facts are recorded here so the Part B session reads its
console correctly (both verified against the pinned toolchain sources, not
yet observed on the device):

1. **First boot initializes OTA metadata.** The table is factory-less
   (app0/app1 = `ota_0`/`ota_1`). With otadata in its erased (all-0xFF)
   state the IDF 6.1.0 bootloader logs "No factory image, trying OTA 0" and
   `set_actual_ota_seq()` writes `ota_seq=1`, `IMG_VALID` + CRC into the
   otadata[0] sector (`bootloader_utility.c`, source-verified). The release
   installer already writes that otadata itself at flash time, so this
   self-initialization is what the plain esptool path relies on.
2. **Flashing erases the sectors it touches.** esptool 5.4.0 erases exactly
   the region each written image covers (rounded to flash erase blocks)
   before programming — "Flash will be erased from … to …" — and a full
   chip erase happens only with the opt-in `--erase-all`; otadata content
   survives unless an image explicitly includes it (`loader.py` /
   `cmds.py`, source-verified).

| Row | Value | Tag | Status |
| --- | --- | --- | --- |
| `ota=` line (verbatim) | `PENDING` | health-gated check-in; `yes/no` verdicts verbatim | PENDING |
| `mem:` line (verbatim) | `PENDING` | MEASURED + CONFIGURED per field | PENDING |
| `identity:` line (verbatim) | `PENDING` | chip info read-only; MAC tail only | PENDING |
| Boot-mode drill transcript | `PENDING` | per-line `boot:0x..` word + `vdog_recovery_classify` result; each line recorded verbatim | PENDING |
| Strap evidence (finding 1b) | `PENDING` | `boot:0x..` values + reset reason for each of: power-on, BOOT-held download entry, BOOT release, reset button | PENDING |
| Reset reason | `PENDING` | `esp_reset_reason()` wording recorded in the transcript | PENDING |
| Port identity (finding 6) | `PENDING` | exact `/dev/cu.usbmodem*` path per attach **and re-identified after every BOOT/reset transition** | PENDING |

Rules (from the plan; restated here so a Part B transcript can be checked
against them):

1. Rails/current come only from the bounded owner-performed measurements in
   §3 — the agent never measures, and nothing may be claimed before the
   owner records a reading.
2. No GPIO21 claim: SD-CS vs user-LED sharing stays unresolved until
   0.3/E07 (Jada's sign-off) is recorded here.
3. The microphone stays uninitialized; no audio row may ever appear.
4. Any sensor probing is 1.3 work, not Part B of this package.

## 3. Electrical checks (bounded, OWNER-performed — plan §6 step 6)

Equipment confirmed by the lead on 2026-11-28: a multimeter and an inline
USB-C power meter. The **owner performs every measurement** and supplies the
readings; the agent never probes, wires or handles meter leads and never
claims a value it did not receive from the owner. Power stays USB from the
Mac with the **battery physically disconnected**; the inline meter sits on
that existing Mac-USB path. These rows become DEVICE evidence only once the
owner records them — until then they are PENDING and the topic stays
unverified.

| Measurement | Instrument | Reading | Meter ID / timestamp | Status |
| --- | --- | --- | --- | --- |
| USB supply current — normal boot | inline USB-C power meter | `PENDING` | PENDING | PENDING |
| USB supply current — idle after boot | inline USB-C power meter | `PENDING` | PENDING | PENDING |
| 3V3 rail voltage | multimeter | `PENDING` | PENDING | PENDING |

An out-of-range reading (3V3 far from 3.3 V nominal, or current behaving
like a short/brownout) stops the session: record verbatim, escalate — do not
continue flashing or monitoring past that point.
