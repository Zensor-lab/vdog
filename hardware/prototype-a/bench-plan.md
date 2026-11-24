# Card and bench preparation (0.7)

Status: **PROCEDURE PREPARED; identified-device assignment PENDING**, 2026-11-23.
This is a preparation document. No board/port/disk is identified for operations;
no flash, format, erase, battery connection, charging or card-removal experiment
is authorized by writing it. Follow the [electrical gate](README.md) and
[recording rubric](../../docs/specs/recording-acceptance.md).

## 1. Available setup and equipment gaps

The owner can use macOS, Windows or Linux, and reports an SD card reader,
USB-C data cable and soldering tools. Choose **one actual host** for the first
record; another OS can be qualified later. Host support is not established
by the owner's willingness to use it. Record version, architecture, Python,
PlatformIO, compiler and command results; use the pinned project setup in
[installation](../../docs/installation.md) and
[toolchain](../../docs/toolchain.md), without switching framework/tool versions.
On Windows the portable `native` tests also need an available host C/C++ compiler.

Before electrical assembly, obtain access to a multimeter and qualified review
for polarity/continuity/voltage checks. Controlled power/fault work needs a
reviewed current-limited supply/source with measured limits and an approved
disconnect method. Thermal/fit work needs temperature and mass measurement.
These instruments and qualified review are **NOT CONFIRMED AVAILABLE**. They
do not block source inspection or host-only preparation.

## 2. Non-destructive host inventory

These are proposed read-only commands to run on the chosen host; none has been
executed for the owner's card/unit in this assignment. With no selected board
yet, do not infer one port from an example or auto-detection.

| Host | OS / removable storage inventory | Serial inventory |
| --- | --- | --- |
| macOS | `sw_vers`; `uname -m`; `diskutil list external physical`; then `diskutil info` on the positively identified card volume/device | `pio device list --serial --json-output` |
| Windows PowerShell | `Get-CimInstance Win32_OperatingSystem`; `Get-Disk`; `Get-Partition`; `Get-Volume` to correlate disk number, capacity and filesystem | `pio device list --serial --json-output` |
| Linux | `uname -sm`; `cat /etc/os-release`; `lsblk -o NAME,MODEL,SIZE,TRAN,FSTYPE,MOUNTPOINTS` | `pio device list --serial --json-output` |

Read-only command reference: [PlatformIO device list](https://docs.platformio.org/en/latest/core/userguide/device/cmd_list.html).
For inventory, correlate before/after insertion plus label/model/capacity, and
distinguish a whole disk from its partition/volume. Recheck identity after any
reconnection; path names and serial ports can change. Keep unrelated disks and
personal serial numbers out of committed logs. Listing a port does not prove
board revision, sensor, memory size or permission to write it.

## 3. Card preparation and qualification record

The baseline is **genuine 32GB SDHC, FAT32**, no brand selected. See
[Seeed's reference](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/).
It does not certify arbitrary brands or every 32GB-labelled card. Exact model
selection can wait until the card is available. No larger-card/exFAT support
is added by this assignment.

| Field | Current value / evidence required |
| --- | --- |
| Card label/model/source | PENDING owner identification |
| Advertised / measured usable bytes | 32GB advertised target / UNVERIFIED actual |
| Existing contents and backup | UNKNOWN; owner confirms backup and whether contents may be replaced |
| Reader model and actual host | PENDING |
| Whole-disk + partition/volume identifiers | PENDING; re-identify at operation time |
| Filesystem / allocation unit bytes | FAT32 intended / actual filesystem and cluster size UNVERIFIED |
| Preparation tool/version/settings/date/operator | PENDING |
| Read/write/capacity verification | PENDING separately bounded operation and evidence; do not silently overwrite contents |
| Firmware commit / SPI settings | PENDING later storage-adapter implementation |
| Capacity/latency/fault evidence | UNVERIFIED |

Order for a future owner-approved card operation:

1. Identify the exact card and backup existing contents; record backup verified
   or an explicit statement that nothing must be preserved.
2. Record tool/version and selected disk/volume, filesystem and allocation
   settings; present the concrete target before any format/full-capacity write.
3. If FAT32 is already healthy, do not format merely because this plan exists.
   If preparation is needed, obtain target-specific approval; no generic
   destructive disk command is provided here. Verify FAT32 and actual cluster
   size afterward, and safely eject before inserting into an unpowered board.
4. Leave filesystem allocation and SPI parameters **unqualified** until tested
   with that actual card and implemented adapter. Start from settings supported
   by the pinned ESP-IDF, log clock, bus width/mode, DMA, transaction size, file
   handle limits and mount settings; a host-prepared card alone proves none.
5. The later firmware must reject absent/unsupported/exFAT/corrupt cards
   without automatic formatting. Record write/sync latency, removal/readonly/
   full faults, mount/recovery outcomes and sanitised evidence in Stage 1.4/1.15.
   Broad compatibility requires more than one actual model.

## 4. Host/build checks versus device operations

From the repository root on a configured host, these existing commands do not
upload to hardware (a first run may download dependencies):

```sh
pio --version
pio run -d firmware -e vdog_xiao_sense_proto
pio run -d firmware -e vdog_xiao_sense_proto -t size
pio test -d firmware -e native
pio test -d firmware -e vdog_xiao_sense_proto --without-uploading --without-testing
git diff --check
```

Report cross-compilation as **BUILD**, native test execution as **HOST**, and
the final embedded command as build-only with no device test execution. Do not
run embedded `pio test` without both no-upload/no-test flags as a host check.
The current minimal firmware does not implement camera capture, card mounting
or recording, so flashing it cannot qualify those features. Cross-platform
command descriptions are not evidence these checks passed on all three OSes.

Flash/monitor directions live in [installation](../../docs/installation.md);
execute them only under a later filled and authorized assignment below, with
explicit port selection. This preparation invokes none of those operations.
Never copy a vendor LED-blink example into a recording image using shared CS21.

## 5. Future identified bench assignment

Fill this before any device work; scope may be approved in small increments.

| Field | Required record | Current status |
| --- | --- | --- |
| Unit and revisions | Base/expansion/OV5640 identity; electrical diagram and pin-map revision | PENDING |
| Host/port | OS/arch/tool versions; before/after serial inventory and exact current port | PENDING |
| Card | Exact model/ID, filesystem/allocation and preparation record | PENDING |
| Image | Exact firmware commit/bundle/hash, expected startup output and feature availability | PENDING |
| Power | USB or approved bench source, pack physically disconnected, equipment/current limits | PENDING |
| Allowed operations | Explicit list: e.g. flash selected image, monitor, BOOT/reset recovery; duration and stop conditions | NONE AUTHORIZED |
| Card writes/faults | Exact test files/ranges, backup/disposal, removal/power-cut schedule and containment | NONE AUTHORIZED |
| Battery work | Selected pack/charger, approved circuit and independent review | NONE AUTHORIZED |
| Results | Date/operator, expected vs actual, logs/hashes, failures and reviewer | UNVERIFIED |

Start on the bench with pack disconnected. After electrical review, controlled
power checks precede camera/SDSPI load. Never disconnect or insert an SD card
while powered except in a specifically approved fault test. For normal handling,
request orderly shutdown, remove power and then remove the card. The minimal
prototype currently offers no recorder shutdown command; document that feature
availability rather than inventing one. Use no full flash erase, NVS overwrite,
filesystem upload, eFuse or OTA operations unless separately scoped.

Later controlled-cut tests need an exact operation schedule, approved source
and disconnect method, cloned/synthetic data, a recovery/inspection plan and
reviewed limits. Preserve failures; FAT/card-controller damage may extend to
earlier data despite sync. Do not automatically format to hide corruption.
Wear remains outside this bench assignment and behind the physical gate.

## 6. Closure

0.7 remains incomplete until actual card/preparation and the identified,
bounded bench assignment are recorded, including qualified allocation/mount
settings when their implementation is available. Long recording/rollover/fault
results belong to their later Stage 1 gates; this procedure does not claim them.
