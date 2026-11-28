# Bench assignment record — Prototype A (package 1.2 Part B)

Status: **PENDING (created by package 1.2 Part A, plan A6).** This is the
bounded bench record: it exists **before** any flash, and Part B may not
begin until every wake-condition row below is recorded DONE. Only commands
that actually run are reported as DEVICE evidence (plan §6).

## 1. Unit and firmware under test

| Field | Value | Status |
| --- | --- | --- |
| Unit | owner's XIAO ESP32S3 Sense (Prototype A) | assigned |
| Unit identity | see [`hardware-identity.md`](hardware-identity.md) — markings not yet transcribed | **PENDING owner photos** |
| Firmware commit (Part A) | **the Part A main-merge commit** (filled at merge; not "957b415+1.2 tip" — lead finding 6) | PENDING merge |
| Firmware commit (Part B) | Part B branch tip at build time (filled when Part B builds) | PENDING |
| Host | this Mac: macOS 26.6.2 (25G83) arm64; PlatformIO Core 6.2.0 (`~/.local/bin/pio`); PlatformIO-bundled Python 3.12; host `python3` 3.14.6 | recorded (Part A re-confirmation 2026-11-28) |
| Power | **USB from the Mac; battery physically disconnected** | required |

## 2. Authorized operations (owner authorization, plan §1, answered 2026-11-27)

Verbatim scope: **flash + monitor over USB from the Mac; battery physically
disconnected; NO erase, eFuse, format, NVS overwrite or filesystem upload.**
Any operation beyond it is out of scope.

Concretely authorized (plan §6):

1. **The build's upload image set** — the authoritative image set and
   offsets taken from the build output's `flash_args`: bootloader, partition
   table binary, otadata/`boot_app0.bin`, and the app — **per flash_args,
   NOT "app-image only"** (lead finding 3). Writing otadata resets the OTA
   slot choice: acceptable on this prototype, must be stated in this record.
2. **Serial monitor** at 115200 (`pio device monitor`) for the recorded
   boot/recovery sessions only.
3. **Port re-identification** per the procedure in §3 below.

Forbidden (any of these = stop, escalate): `erase-flash` / any erase;
eFuse writes of any kind; formatting; NVS content overwrites; filesystem
(SPIFFS/LittleFS) upload; battery wiring or charging work; monitor use
beyond the recorded session.

## 3. Port procedure (lead finding 6)

1. `ls /dev/cu.*` **before** attaching; record the set.
2. Attach the board (battery physically disconnected); `ls /dev/cu.*`
   **after**; record the exact new `/dev/cu.usbmodem*` path.
3. **Re-identify the port after every BOOT/reset transition** — the native
   USB-Serial/JTAG path re-enumerates and the path can change.
4. All flashing/upload targets ONLY the currently recorded path; a stale
   path is re-identified first, never guessed.

## 4. Image-set overlap check (blocking)

Before flashing, cross-check the `flash_args` set against
`firmware/partitions/vdog_8mb_two_ota.csv` — nvs 0x9000–0xEFFF, otadata
0xF000–0x10FFF, phy_init 0x11000–0x11FFF, app0 0x20000, app1 0x320000:

- **No written image may overlap nvs or phy_init.**
- A `flash_args`-vs-CSV overlap is a **BLOCKING escalation — do not flash,
  report instead.**
- Record the actual esptool command line (PlatformIO verbose upload) here.

## 5. Wake conditions (ALL required before any flash — plan §6)

| # | Condition | Status |
| --- | --- | --- |
| 1 | Owner supplies board / base-board / Sense-expansion / camera+ribbon marking photos → transcribed into [`hardware-identity.md`](hardware-identity.md), revision determined | PENDING |
| 2 | USB port re-identified per §3 | PENDING (device work) |
| 3 | Part A merged to main | PENDING |
| 4 | Lead acknowledgment recorded | PENDING |

Owner physical presence is required for the BOOT-button drill.

## 6. Part B session log (only rows that ran are DEVICE evidence)

| Step | Command / observation | Result | Status |
| --- | --- | --- | --- |
| B1 attach + port record (§3) | `ls /dev/cu.*` before/after | PENDING | PENDING |
| B2 `flash_args` extract + overlap check + verbose esptool record | build at Part B tip | PENDING | PENDING |
| B2 upload | `pio run -d firmware -e vdog_xiao_sense_proto -t upload --upload-port <recorded path>` | PENDING | PENDING |
| B3 boot capture — `vdog_mem_format_detected` matches baseline + photos (tags honest) | `pio device monitor` | PENDING | PENDING |
| B3 boot capture — `vdog_identity_format` sanitized only | `pio device monitor` | PENDING | PENDING |
| B4 `boot:0x..` strap value + reset reason (normal boot), verbatim | capture | PENDING | PENDING |
| B5 USB/BOOT recovery drill ≥2 full transitions (download reached, re-flash same set, normal boot restored), port re-identified at each transition | owner presses BOOT | PENDING | PENDING |
| B6 sanitized report rows filled | [`hardware-identity.md`](hardware-identity.md) | PENDING | PENDING |

## 7. Standing UNVERIFIED (never claim)

- Rail voltages / current draw (bench equipment unconfirmed by the owner).
- GPIO21 SD-CS vs user-LED sharing: unresolved until 0.3/E07 sign-off;
  nothing in Part A or this record claims GPIO21.
- Sensor identity: deferred to package 1.3 (recorded deviation).
- Everything in §5/§6 until it actually runs.
