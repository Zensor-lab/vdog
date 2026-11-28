/*
 * vdog portable recovery/identity core module (package 1.2, plan A2).
 *
 * Pure C11, no SDK/OS headers, host-tested; target-side reads live in
 * components/vdog_board/vdog_board_hw.c. Two jobs:
 *
 * 1) BOOT/USB recovery evidence: classify the ROM boot banner the 1.2
 *    drill prints (normal boot vs download mode vs the USB-Serial-JTAG
 *    boot path) so the Part B transcript is machine-checked instead of
 *    eyeballed. Unknown input is UNKNOWN — never guessed.
 * 2) Sanitized identity line: the struct stores ONLY what may be logged.
 *    There is deliberately no full-MAC member and no eFuse-raw member: the
 *    sanitizer is structural (host-pinned), not an after-the-fact mask —
 *    a full MAC can never be formatted because it can never be stored.
 */
#ifndef VDOG_RECOVERY_H
#define VDOG_RECOVERY_H

#include <stddef.h>
#include <stdint.h>

#include "vdog_mem.h" /* identity carries the same tagged memory summary */

#ifdef __cplusplus
extern "C" {
#endif

#ifndef VDOG_OK
#define VDOG_OK 0
#endif
#ifndef VDOG_ERR_INVALID_ARG
#define VDOG_ERR_INVALID_ARG (-1)
#endif
#ifndef VDOG_ERR_BUFFER_TOO_SMALL
#define VDOG_ERR_BUFFER_TOO_SMALL (-2)
#endif

/* ---- ROM boot-mode classification (plan 1.2 A2) ------------------------- */
typedef enum {
    VDOG_BOOT_MODE_UNKNOWN = 0, /* never guessed from junk                 */
    VDOG_BOOT_MODE_NORMAL,      /* executed from flash (SPI boot paths)    */
    VDOG_BOOT_MODE_DOWNLOAD,    /* ROM serial/bootloader download mode     */
    VDOG_BOOT_MODE_USBJTAG      /* USB-Serial-JTAG ROM boot banner         */
} vdog_boot_mode_t;

/* Case-insensitive substring classification of ONE ROM/console line (the
 * Part B drill records each line and its raw "boot:0x.." word verbatim;
 * this only names the state the line proves):
 *   - "usb_jtag" or "usb-jtag"          -> VDOG_BOOT_MODE_USBJTAG
 *   - "download" (any ROM download name) -> VDOG_BOOT_MODE_DOWNLOAD
 *   - "spi_fast" / "spi_boot" / "basic"  -> VDOG_BOOT_MODE_NORMAL
 *   - NULL, empty, anything else         -> VDOG_BOOT_MODE_UNKNOWN
 * "usb_jtag"/"usb-jtag" is checked FIRST so a JTAG download banner is not
 * mislabelled plain DOWNLOAD; "spi_fast_download" contains "download" and
 * therefore classifies as DOWNLOAD (checked before the "spi_fast" token). */
vdog_boot_mode_t vdog_recovery_classify(const char *rom_line);

/* Stable lowercase name for a boot mode (for logs/records). */
const char *vdog_boot_mode_name(vdog_boot_mode_t mode);

/* ---- sanitized identity (plan 1.2 A2, acceptance 5) --------------------- */
#define VDOG_IDENTITY_CHIP_MODEL_MAX 16
#define VDOG_IDENTITY_TAG_MAX 16 /* opaque caller board tag, optional     */

typedef struct {
    char chip_model[VDOG_IDENTITY_CHIP_MODEL_MAX]; /* e.g. "esp32s3"       */
    uint8_t chip_major;                            /* chip revision major  */
    uint8_t chip_minor;                            /* chip revision minor  */
    vdog_mem_detected_t mem; /* tagged baseline summary (rendered by the
                              * caller's mem line; the identity line keeps
                              * only the compact configured summary)       */
    uint8_t mem_valid;       /* 1 = mem summary was baseline-checked       */
    uint16_t mac_tail;       /* LAST TWO BYTES only (0xABCD -> 0xABCD);
                              * a full MAC cannot exist in this struct.    */
    uint8_t mac_valid;       /* 0 = MAC not read (never invented)          */
    char board_tag[VDOG_IDENTITY_TAG_MAX]; /* opaque, caller-supplied;
                                            * "" when absent               */
} vdog_identity_t;

/* Zero-init with empty strings: absent parts are never rendered. */
void vdog_identity_init(vdog_identity_t *id);

/* Decode the SDK chip-info wafer revision number and store it for display.
 * The SDK's chip-info header documents the raw field as "format MXX; where
 * M - wafer major version, XX - wafer minor version" — a DECIMAL encoding,
 * so the display pair is (mxx / 100, mxx % 100), NOT a byte split:
 * 0 -> 0.0, 2 -> 0.2, 100 -> 1.0, 101 -> 1.1 (v1.1), 201 -> 2.1. The
 * target adapter reads the raw value and calls this; the host suite
 * table-tests the decode (plan 1.2 review F-2). NULL id is a no-op. */
void vdog_identity_set_revision_mxx(vdog_identity_t *id, uint16_t mxx);

/* Compose ONE sanitized log line, e.g.
 *   "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:ab:cd board=vdog-pa-01"
 * Rules (host-pinned, plan 1.2 acceptance 5):
 *  - chip model + revision always rendered (read-only chip info);
 *  - "mem=" only when mem_valid (already baseline-checked summary — the
 *    compact configured form; the full tagged line is vdog_mem_format's
 *    job and is logged separately);
 *  - "mac=" renders the stored 16-bit tail as the last two octets with the
 *    OUI-independent mask prefix; absent when mac_valid == 0;
 *  - "board=" only when a non-empty opaque tag was supplied;
 *  - no full MAC, no eFuse raw values, no serial, no secret fields — the
 *    struct cannot even hold them.
 * Buffer/NUL semantics identical to vdog_format_version(): VDOG_OK;
 * VDOG_ERR_INVALID_ARG on NULL buf/cap==0 or NULL id; VDOG_ERR_BUFFER_TOO_SMALL
 * when the exact NUL-terminated line (including final NUL) does not fit;
 * buffer contents unspecified on error. */
int vdog_identity_format(const vdog_identity_t *id, char *buf, size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_RECOVERY_H */
