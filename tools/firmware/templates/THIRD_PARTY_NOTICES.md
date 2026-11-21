# Third-party notices

This prototype bundle writes Espressif-built binary images (first-stage
bootloader, partition table, initial OTA data, application firmware) produced
with the pinned toolchain documented in `docs/toolchain.md`:

- PlatformIO Core 6.2.0, `platformio/espressif32@8.0.0`
- ESP-IDF v6.1.0 (Apache-2.0); its component licenses apply to linked code
- esptool 5.4.0 (GPL-2.0-or-later) used as a build-time tool only
- pyserial (Python-2.0 / BSD-like) in the installer environment
- Seeed XIAO board definitions (MIT) in the PlatformIO platform package

Full license texts and the complete component list are tracked with
`firmware/dependencies.lock` and are finalized with decision D-15 before
public distribution (master plan section 4). This prototype file is a
placeholder that names the known major components; the packaging step copies
whatever notices source path is supplied.
