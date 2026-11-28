# Prototype firmware installation

This guide builds and uploads the minimal vdog prototype to a **Seeed Studio
XIAO ESP32S3 Sense** (8MB flash / 8MB octal PSRAM). It is not for other ESP32
boards or the XIAO ESP32S3 Plus.

The current firmware logs its version and links the camera driver, but does
not initialize the camera, record to SD, or provide Wi-Fi/app features.
The build passed on 2026-11-20; upload and runtime operation have not yet been
verified in this guide. See the [toolchain matrix](toolchain.md) for dependency
pins and earlier BUILD/HOST evidence.

## Two ways to install

| | Prebuilt release bundle | Source build (this page) |
| --- | --- | --- |
| For | Testers installing a shipped prototype | Developing and building the firmware |
| Needed on the host | Python 3.12 + [`uv`](https://docs.astral.sh/uv/) | PlatformIO Core 6.2.0 + Python 3.12, a compiler toolchain, a clone of this repository |
| Where the images come from | A GitHub Release ZIP built and validated by CI from one exact commit | `pio run` on your machine |
| How the board is written | `install.py` via `install.sh` / `install.ps1`, four validated segments | PlatformIO's `upload` target |
| Guide | [Prebuilt release installation](release-installation.md) | the rest of this page |

Follow [Prebuilt release installation](release-installation.md) to download a
CI-built bundle, verify its `.sha256`, and install it with the bundled wrapper.
That route needs no PlatformIO, no ESP-IDF and no source clone, and it is the
route the [Stage 0.9 pipeline](plans/0.9-firmware-ci-release.md) produces: an
immutable `firmware-main-<sha12>` tag, a pre-release with the validated ZIP,
its external digest, `INSTALL.md`, `RELEASE_NOTES.md`,
`THIRD_PARTY_NOTICES.md` and `manifest.json`. Pull-request builds are
development artifacts (14-day retention), not releases.

Everything below stays the documented **source-build** route for development.
Both routes install the same four segments and neither provides device OTA or a
recording feature; the firmware logs its version and links the camera driver,
but does not initialize the camera, record to SD, or provide Wi-Fi/app features.

## 1. Prepare the computer and board

- Use PlatformIO Core **6.2.0** with **Python 3.12**. The pinned ESP-IDF 6.1
  requires Python 3.10 or later; Python 3.9 is unsuitable.
- Use a USB-C cable that supports data.
- Disconnect the battery pack before USB servicing, following the project's
  [power policy](specs/firmware.md#6-power-settings-and-time).
- Run the commands below from the repository root.

If PlatformIO is not installed and you use `uv`, install it with:

```sh
uv tool install --python 3.12 platformio==6.2.0
pio --version
```

The first build downloads the pinned SDK, compiler packages and Python
dependencies, so it needs network access and can take several minutes.

## 2. Build the firmware

```sh
pio run -d firmware -e vdog_xiao_sense_proto
```

Wait for `[SUCCESS]`. The generated application image is
`firmware/.pio/build/vdog_xiao_sense_proto/firmware.bin`.
Building does not write anything to the board.

## 3. Upload over USB

Connect the XIAO to the computer, then run:

```sh
pio run -d firmware -e vdog_xiao_sense_proto -t upload
```

This builds as needed and writes the firmware and supporting images to the
connected board. It replaces its existing firmware. Use PlatformIO's upload
target rather than copying `firmware.bin` onto a USB drive.

PlatformIO tries to detect the port automatically. If detection fails or
several boards are connected, list the ports:

```sh
pio device list
```

On macOS, select the XIAO's `/dev/cu.usbmodem...` port and substitute it below:

```sh
pio run -d firmware -e vdog_xiao_sense_proto -t upload --upload-port /dev/cu.usbmodemXXXX
```

`XXXX` is a placeholder. On Windows, use the corresponding `COM` port instead.
Close any serial monitor using that port before uploading.

## 4. Enter download mode if needed

Try uploading normally first. If no port appears or upload stays at
`Connecting...`, use the two buttons on the XIAO base board:

1. Keep USB connected.
2. Press and hold **BOOT**.
3. While holding BOOT, press and release **RESET**.
4. Release **BOOT**.
5. Run `pio device list` again, then repeat the upload command with the
   current port. The port can change when entering download mode.

Alternatively, hold BOOT while connecting USB, then release BOOT.
These steps follow [Seeed's XIAO ESP32S3 upload recovery instructions](https://wiki.seeedstudio.com/noport_upload_fails/).
After a successful upload, press RESET once with BOOT released if the program
does not start.

## 5. Check startup output

Open a serial monitor at the configured 115200 baud, using the current port:

```sh
pio device monitor --port /dev/cu.usbmodemXXXX --baud 115200
```

Press RESET with BOOT released to capture startup messages. The current source
logs `vdog firmware ... (0.2 proto build)`, the build identity line
`build identity: build_id=... source_sha=...` (for a source build without CI
context that reads `build_id=local source_sha=local`), the Stage 1.1 board
profile line `board: vdog 0.2.0-proto board=seeed_xiao_esp32s3 target=esp32s3
flash=8MB-qio-80m psram=8MB-opi-80m`, the Stage 1.2 memory baseline line
`mem: flash_size=8MB[measured] flash_mode=qio[configured] flash_freq=80m[configured]
psram=8MB[measured:init-ok] psram_mode=opi[configured] psram_speed=80m[configured]`,
the sanitized identity line `identity: chip=esp32s3 rev=0.2
mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:<xx>:<xx>` (MAC tail
only), and `esp32-camera linked: yes`. These are expected messages from the
source, not a recorded device test result; they do not prove camera capture or
SD recording. Exit the monitor with Ctrl+C.

## Troubleshooting the Python environment

If CMake reports `No module named 'idf_component_manager'`, inspect the Python
used by PlatformIO and its IDF environment. On macOS/Linux:

```sh
head -n 1 "$(command -v pio)"
~/.platformio/penv/.espidf-6.1.0/bin/python --version
```

If PlatformIO uses Python 3.9, reinstall the same Core version under Python 3.12:

```sh
uv tool install --python 3.12 platformio==6.2.0 --force --reinstall
```

With no build running, move the incomplete IDF environment to an unused backup
name, then rebuild so PlatformIO recreates it and installs its dependencies:

```sh
mv ~/.platformio/penv/.espidf-6.1.0 ~/.platformio/penv/.espidf-6.1.0.backup
pio run -d firmware -e vdog_xiao_sense_proto
```

Choose a different backup name if that destination already exists. These paths
assume the default PlatformIO core directory.

On Apple silicon, changing from Intel Python to native ARM Python may trigger
large compiler downloads. During the 2026-11-20 repair, those downloads failed
with `IncompleteRead`; Python 3.12.13 for Intel macOS under Rosetta successfully
reused the already installed Intel toolchains. That workaround used:

```sh
uv python install cpython-3.12.13-macos-x86_64-none --no-bin
uv tool install --python "$HOME/.local/share/uv/python/cpython-3.12.13-macos-x86_64-none/bin/python3.12" platformio==6.2.0 --force --reinstall
```

Use this only when intentionally reusing Intel packages on a Mac with Rosetta;
it is not required for a normal native ARM installation.

Command reference: [PlatformIO run/upload options](https://docs.platformio.org/en/latest/core/userguide/cmd_run.html).
