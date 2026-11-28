# Bench assignment — package 1.2 Part B (device half)

Status: **GATED — not started.** Every row below is the bounded authorization
for ONE future session on the owner's hardware. This package's Part A made
**zero** device claims; no DEVICE evidence exists anywhere in the 1.2 tree.
This session may begin only when ALL wake conditions in §1 are recorded here
(plus the lead's release of the reviewed Part A commit).

## 1. Wake conditions (record all, with date + who)

| Condition | Source | Status |
| --- | --- | --- |
| Board marking photos delivered (0.3 check 1: base board, Sense side, camera/ribbon, flash + PSRAM markings) | owner | PENDING |
| Port re-identified at operation time (see §4 procedure — a previously recorded path is never trusted) | operator (this bot) | PENDING |
| Lead released the reviewed Part A commit for device work | Team Leading developer | PENDING |
| `docs/hardware-identity.md` §1 rows transcribed from the photos | operator | PENDING |

## 2. Unit and host

| Field | Value |
| --- | --- |
| Unit | owner's Seeed XIAO ESP32S3 Sense (unit identity PENDING photos; acceptance baseline 8 MB flash / 8 MB octal PSRAM — NOT Plus / N16R8 / classic) |
| Firmware commit | the **Part A main-merge commit** (PR merge SHA) **plus the Part B tip** used for the session (lead finding 6 — not "957b415+1.2 tip") |
| Host | this Mac: macOS 26.6.2 (25G83), arm64; PlatformIO Core 6.2.0; bundled Python 3.12; host python3 3.14.6 |
| Power | **USB from the Mac only; battery physically disconnected** before the first attach |

## 3. Authorized operations (exactly these, nothing else)

1. Upload of the **build's flash_args image set** — bootloader, partition
   table, otadata/boot_app0 and app, taken from
   `firmware/.pio/build/vdog_xiao_sense_proto/flash_args` at session time
   (true upload set, plan §6 B2; NOT "app-image only"). Before flashing,
   perform the **partition overlap check** from that same set.
2. Serial monitor at **115200** for the recorded session only (boot lines,
   `mem:` / `identity:` / board lines, boot-mode drill transcript including
   each raw `boot:0x..` word and reset reason).
3. Port re-identification (procedure §4) as required by 1 and 2.

## 4. Forbidden

- `erase` / `erase-flash` / any flash erase of any region.
- eFuse writes of any kind (no read of raw eFuse values into logs either).
- Format of any filesystem; NVS overwrite; filesystem upload.
- Any battery wiring or charging operation (battery stays disconnected).
- Monitor sessions beyond the recorded one; any operation on a port path
  that was not re-identified for that transition.

## 5. Port procedure (finding 6 — re-identify after EVERY transition)

Native USB re-enumerates on every BOOT/reset transition, so a recorded path
expires at the next transition. Procedure per attach **and** per BOOT/reset
transition:

1. `ls /dev/cu.*` before attaching (or before the transition),
2. `ls /dev/cu.*` after,
3. record the exact `/dev/cu.usbmodem*` path delta in the session record,
4. flashing/monitoring targets ONLY that recorded path; anything else
   (including a previously recorded path) is out of scope.

## 6. Session record (filled by the Part B session, never before)

| Field | Value |
| --- | --- |
| Date / operator | PENDING |
| Firmware commit pair (merge + tip) | PENDING |
| Port path per transition (each BOOT/reset step) | PENDING |
| flash_args image set + overlap-check result | PENDING |
| Boot transcript summary (`vdog_recovery_classify` per line, `boot:0x..`, reset reason) | PENDING |
| `mem:` / `identity:` lines (verbatim) → transcribed to hardware-identity.md §2 | PENDING |
| Recovery drill outcome (USB/BOOT → download mode reproducible?) | PENDING |
| Rails/current | **UNVERIFIED — not authorized** (no confirmed multimeter/current-limited supply; plan §7) |
| GPIO21 / SD-CS vs user-LED | **not claimed** (0.3/E07 pending, Jada's sign-off) |
| Microphone | **never initialized** (product baseline) |
