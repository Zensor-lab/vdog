# Install a prebuilt vdog firmware release (no PlatformIO, no source clone)

This guide installs a **prebuilt** vdog firmware bundle onto a **Seeed Studio
XIAO ESP32S3 Sense** (8MB flash / 8MB octal PSRAM) from a GitHub Release. You
do **not** need PlatformIO, ESP-IDF, a compiler, or a copy of this repository.

If you want to build from source with PlatformIO instead, use the separate
[source-build guide](installation.md); it stays the documented developer route.

## What this release is — and is not

Read this before installing anything.

| Claim | Status |
| --- | --- |
| Product | vdog prototype firmware `0.2.0-proto` for the XIAO ESP32S3 Sense |
| `release_channel` | `prototype` — pre-release, published as a GitHub pre-release |
| Recording / camera / SD / Wi-Fi | **Not implemented.** The bundle does not record |
| Device OTA | **Not provided.** Installation is a USB serial install only |
| `hardware_verified` | `false` — no physical-device verification evidence yet |
| Evidence level | BUILD/HOST only: the images were cross-compiled and host-tested |
| Installed/verified on a board by CI | **No.** Device installation is a separate, still deferred gate (master plan 0.9.15: CI-T15 stays UNVERIFIED) |

This is a prototype factory/recovery **segment install**: it writes the
bootloader, partition table, initial OTA data and application ranges listed in
the bundle's own `flash/flash-layout.json`, replaces the firmware, and resets
boot selection. It may invalidate settings if the partition layout changed. It
never touches the NVS partition, the `storage` partition, the SD card, or any
security fuse, and it never runs a full-chip erase.

**Unplug the battery pack before connecting USB.** The XIAO has an onboard
charger; the project power policy requires disconnecting the pack before any
USB servicing ([power policy](specs/firmware.md#6-power-settings-and-time)).

You need:

- a genuine **Seeed Studio XIAO ESP32S3 Sense** — the hardware-class
  acknowledgment in step 5 is required, because a chip ID or USB VID/PID cannot
  prove that a board is the Sense variant;
- a **data-capable** USB-C cable (charge-only cables never enumerate);
- **Python 3.12** and [`uv`](https://docs.astral.sh/uv/) on the computer. The
  setup wrapper creates its own isolated environment; it never installs into
  your global Python and never needs administrator rights. Other Python
  versions are not qualified for this bundle. A 32GB microSD card is **not**
  needed: this prototype does not record.

## 1. Download the release bundle

Two different download locations exist, and only one of them is a release.

**Releases (recommended).** Open the repository's
[Releases page](https://github.com/Zensor-lab/vdog/releases), pick the entry
titled `vdog <version> — main <sha12>`, and download:

- `vdog-xiao-sense-main-<sha12>.zip` — the complete installation bundle, and
- `vdog-xiao-sense-main-<sha12>.zip.sha256` — the external digest.

Prototype releases are marked **pre-release** and are deliberately never
flagged as "latest". The auto-generated source archive (`Source code (zip)`) is
**not** the installation bundle.

**Pull-request artifacts (development builds only).** Every PR run named
`Firmware PR #<number> @ <full-head-sha>` uploads an artifact named
`vdog-xiao-sense-pr-<number>-<head-sha12>-run<run-id>-a<attempt>`. Go to
**Actions → the run → Artifacts**. Actions gives you an **outer ZIP** that
contains the real `vdog-xiao-sense-pr-….zip`; extract the outer ZIP first, then
use the inner bundle exactly as below. Artifacts are temporary development
builds, are **retained for 14 days** and then expire, and they are not
Releases: prefer a Release for anything you keep.

Always confirm the identity you meant to install. The `<sha12>` in the file
name is the first 12 hex characters of the commit the bundle was built from.

## 2. Verify the archive, then extract

```sh
shasum -a 256 -c vdog-xiao-sense-main-<sha12>.zip.sha256    # macOS / Linux
```

Expected output:

```text
vdog-xiao-sense-main-<sha12>.zip: OK
```

On Windows PowerShell:

```powershell
Get-FileHash .\vdog-xiao-sense-main-<sha12>.zip -Algorithm SHA256
Get-Content .\vdog-xiao-sense-main-<sha12>.zip.sha256
```

The two digests must match. A checksum detects corruption; authenticity still
depends on having downloaded from this repository.

Extract it (any location; the folder is self-contained):

```sh
unzip vdog-xiao-sense-main-<sha12>.zip
cd vdog-xiao-sense-main-<sha12>
```

```powershell
Expand-Archive .\vdog-xiao-sense-main-<sha12>.zip -DestinationPath .
Set-Location .\vdog-xiao-sense-main-<sha12>
```

**Never copy `.bin` files onto the board's USB drive.** There is no such
installation method here, and doing so cannot update the bootloader, partition
table or OTA selection.

The bundle contains exactly:

```text
INSTALL.md  RELEASE_NOTES.md  VERSION.json  manifest.json  SHA256SUMS
LICENSE  THIRD_PARTY_NOTICES.md
images/     bootloader.bin  partitions.bin  ota_data_initial.bin  firmware.bin
flash/      partitions.csv  flash-layout.json  flash_args
install.py  install.sh  install.ps1  requirements-installer.lock
```

## 3. Set up the isolated installer environment

`install.sh` (macOS/Linux) or `install.ps1` (Windows) creates a private
`.venv-installer/` next to the script, installs the hash-pinned dependencies
from `requirements-installer.lock` into it (`esptool==5.4.0` + pyserial), and
then runs `install.py` inside it. First setup downloads those pinned packages,
so it **needs network access**; later runs reuse the environment and work
offline. The wrapper never modifies a system Python, never uses `sudo`, never
copies a virtual environment around, and never pipes a downloaded script into a
shell.

```sh
sh ./install.sh check           # macOS / Linux (Git Bash works on Windows too)
```

The ZIP stores files without the executable bit, so invoke the wrapper through
`sh`; run `chmod +x install.sh` once if you prefer `./install.sh`.

```powershell
# Windows: if scripts are blocked in your session, allow them for that process:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1 check

# ...or for a single run without changing any policy:
powershell -ExecutionPolicy Bypass -File .\install.ps1 check
```

If `uv` is missing the wrapper stops with an actionable message instead of
guessing. Install `uv` from your package manager or from
<https://docs.astral.sh/uv/> and rerun. Set `VDOG_INSTALLER_UV` to point at a
specific `uv` binary, `VDOG_INSTALLER_VENV_DIR` to put the environment
somewhere else, or `VDOG_INSTALLER_PYTHON` to pick a different qualified
CPython 3.12 patch.

Both wrappers accept exactly the same arguments as `install.py` and pass them
straight through, so every command below works with either of them.

## 4. Check the bundle (no port is opened)

```sh
sh ./install.sh check
```

This validates every file against `manifest.json`, `SHA256SUMS`,
`flash-layout.json`, the partition table and the image headers. It opens no
serial port and needs no board. A broken or tampered bundle fails here with a
list of what disagreed — do not continue if it fails.

## 5. Acknowledge the hardware class, then pick the port

You must confirm you hold the supported class: **Seeed Studio XIAO ESP32S3
Sense** with 8MB flash and 8MB octal PSRAM, at the board revision you were
given. This release is not validated on any other ESP32 board, and the
installer refuses a device that does not report `esp32s3` with 8MB flash.

Connect the board with the battery **unplugged**, using a data cable, then:

```sh
sh ./install.sh ports
```

Choose the port yourself; the installer never auto-selects a chip:

| System | Port you should see |
| --- | --- |
| macOS | `/dev/cu.usbmodem…` (use the `cu.…` name) |
| Linux | `/dev/ttyACM0` (sometimes `/dev/ttyUSB0`) |
| Windows | `COM…`, e.g. `COM4` — from Device Manager → Ports (COM & LPT) |

Close any serial monitor or other program holding the port. On Linux you may
need `sudo usermod -aG dialout $USER` and a re-login; do not run the installer
itself as root.

## 6. Preview what would be written

```sh
sh ./install.sh plan --board seeed-xiao-esp32s3-sense
```

`plan` prints the four validated segments with their offsets (`0x0`, `0x8000`,
`0xf000`, `0x20000`), sizes and hashes, and opens no port. Compare them with
`flash/flash-layout.json` in the same folder.

Then inspect that specific board read-only — this flashes nothing, erases
nothing and never touches eFuses:

```sh
sh ./install.sh inspect --port /dev/cu.usbmodem123  # macOS
sh ./install.sh inspect --port /dev/ttyACM0         # Linux
.\install.ps1 inspect --port COM4                   # Windows
```

`inspect` reports the chip, flash size and security state, and refuses to
continue if secure boot or flash encryption is enabled, if the layout is
unreadable/unknown, or if the board looks provisioned. There is no `--force`
option and no security bypass in this tool.

## 7. Install

Run it once with `--dry-run` first to see the exact planned invocation without
the port being opened:

```sh
sh ./install.sh install --port /dev/cu.usbmodem123 --board seeed-xiao-esp32s3-sense --dry-run
```

Then install:

```sh
sh ./install.sh install --port /dev/cu.usbmodem123 --board seeed-xiao-esp32s3-sense
```

The installer prints the ranges it will replace and asks you to type `install`
to consent. Nothing is written before that. For a scripted, non-interactive
run, give consent explicitly with `--confirm-replace`; that flag consents to
the listed firmware ranges only — it is not an erase, a layout migration or a
security override:

```sh
sh ./install.sh install --port /dev/ttyACM0 --board seeed-xiao-esp32s3-sense --confirm-replace
```

A demonstrably blank, unprovisioned development board may take the
factory-install route after confirmation. A board with an existing installation
is accepted only when its partition table matches this bundle exactly and it is
unprovisioned. Anything else is refused rather than assumed blank; paired or
provisioned devices need a separately qualified preservation route, and
app-only or OTA installs are not offered.

## 8. Confirm the startup identity

Press **RESET** (with BOOT released) and open the console at **115200** baud.
Confirm the port again — it can change:

```sh
sh ./install.sh ports
```

Any serial terminal works, for example:

```sh
python -m serial.tools.miniterm /dev/cu.usbmodem123 115200
```

Expected startup lines (the exact identity values come from *your* bundle's
`VERSION.json` / `manifest.json`; the `board:`, `mem:` and `identity:` lines
are the expected console output of the current source — `firmware/src/main.c`
— and are **not** DEVICE evidence; no device function is proven by these
lines):

```text
I (xxx) vdog: vdog firmware 0.2.0-proto (0.2 proto build)
I (xxx) vdog: build identity: build_id=main-<sha12> source_sha=<sha12>
I (xxx) vdog: board: vdog 0.2.0-proto board=seeed_xiao_esp32s3 target=esp32s3 flash=8MB-dio-80m psram=8MB-opi-80m
I (xxx) vdog: mem: flash_size=8MB[measured] flash_mode=dio[configured] flash_freq=80M[configured] psram=8MB[measured:init-ok] psram_mode=opi[configured] psram_speed=80M[configured]
I (xxx) vdog: identity: chip=ESP32-S3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:<xx>:<xx>
I (xxx) vdog: esp32-camera linked: yes
```

The `board:` line (Stage 1.1) renders this image's own board profile; the
`mem:` line (Stage 1.2) tags each field `measured` (read from the chip) or
`configured` (this build's configuration); the `identity:` line is the
sanitized chip model/revision plus the MAC tail only. A rejected board or
memory baseline prints a `board config rejected:` /
`memory check rejected:` error line instead — that is a stop, not a warning.

The line you must match is

```text
build_id=… source_sha=…
```

- for a Release it reads `build_id=main-<sha12> source_sha=<sha12>`;
- for a PR artifact it reads `build_id=pr-<number>-<sha12> source_sha=<sha12>`;
- a locally built bundle instead reads `build_id=local source_sha=local`, which
  is the explicit unpublished identity and must never be presented as a
  release.

`<sha12>` must equal the suffix of the file you downloaded and the `tag` field
in `VERSION.json`. These are expected console messages from the built image;
they do **not** prove camera capture, SD recording, radio behaviour or any
other device function — that verification is still outstanding.

## 9. If something goes wrong

| Symptom | What to do |
| --- | --- |
| No port appears, or it stops at `Connecting…` | Enter download mode: hold **BOOT**, press and release **RESET**, release **BOOT**, rerun `sh ./install.sh ports`, then rerun the install with the **current** port (it can change). Alternatively hold BOOT while plugging USB in, then release. Press **RESET** once afterwards with BOOT released. [Seeed's upload-recovery instructions](https://wiki.seeedstudio.com/noport_upload_fails/) |
| Port appears and disappears | Try another cable and another USB port; a charge-only cable is the usual cause |
| `Permission denied` opening the port (Linux) | Add yourself to the `dialout` group and re-login; do not run the installer as root |
| Port busy | Close the monitor or other program holding it, then retry |
| `esptool version … is not the qualified 5.4.0` | Rerun through `sh ./install.sh` / `.\install.ps1` so the locked environment is used, or pass `--esptool-python` to that environment's interpreter. The installer will not silently use an ambient `esptool` |
| `serial port enumeration needs the locked installer dependencies` | First setup had no network, or the environment was deleted; rerun `sh ./install.sh check` with network access |
| `check` fails on a hash | Re-download from the Release and re-verify; do not install a bundle that fails |
| Device reports the wrong chip or flash size | You have a different board or revision. Stop; this bundle is only for the XIAO ESP32S3 Sense |
| Secure boot / flash encryption is reported | Stop. This prototype route does not install onto protected devices and provides no security bypass |
| An install failed partway | Rerun the same validated command: the same four segments are re-validated before any write |
| `uv: command not found` | Install `uv`, or export `VDOG_INSTALLER_UV=/path/to/uv`, then rerun |

## 10. What the installer will never do

- no full-chip or region erase, and no erase of NVS, `storage` or the SD card;
- no eFuse programming, no secure-boot or flash-encryption change, no security
  bypass, and no generic `--force`;
- no automatic chip/board detection followed by flashing, and no writing to an
  offset outside the four validated segments;
- no global Python installation, no `sudo`/administrator elevation, no copied
  virtual environment, and no download-and-execute pipe;
- no device OTA and no recording feature — neither exists in this prototype.

To go back to a source-built image, use the
[source-build guide](installation.md) and its PlatformIO upload route.
