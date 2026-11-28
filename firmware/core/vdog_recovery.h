/*
 * vdog portable recovery/identity core module (package 1.2, plan A2).
 *
 * Pure C11, no SDK/OS headers, host-tested; target-side reads live in
 * components/vdog_board/vdog_board_hw.c. Two jobs:
 *
 * 1) BOOT/USB recovery evidence: classify the ROM boot banner the 1.2
 *    drill prints (normal boot vs download mode vs the USB-Serial-JTAG
 *    boot path) so the Part B transcript is machine-checked instead of
 *    eyeballed. Classification is STRUCTURAL, not substring: a line is
 *    evidence only if it is a recognized ROM form ("boot:0x..(<mode>)"
 *    or the "ESP-ROM:esp32s3-usb-jtag-..." banner) whose mode token is a
 *    member of a closed set. Ordinary console prose that merely contains
 *    "download" or "basic" is UNKNOWN — never guessed (PR-review round 1).
 * 2) Sanitized identity line: the struct stores ONLY what may be logged,
 *    and text enters ONLY through validated setters (PR-review round 1):
 *    the chip model is a closed-set enum (rendered from internal constant
 *    names, never caller bytes), the board tag must pass a strict charset
 *    before it is stored (rendered with an explicit length bound), and
 *    there is deliberately no full-MAC member and no eFuse-raw member.
 *    The sanitizer is structural, not an after-the-fact mask.
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

/* Classify ONE ROM/console line. Recognized ROM forms ONLY — the two
 * forms documented in the esptool ESP32-S3 boot-mode-selection "Boot
 * Mode Message" (exact documented mode tokens, nothing else classifies):
 *   - the ROM boot word: a line containing the WORD "boot:" (a match at
 *     line start or after a non-token char — "reboot:" never matches),
 *     then optional spaces, a REQUIRED hex strap value 0xNN, optional
 *     spaces, and the COMPLETE parenthesized description validated BY
 *     MODE (round-3 review: balanced parentheses, nothing after the
 *     closing paren except trailing spaces — truncations like
 *     "boot:0x3 (DOWNLOAD" or "(DOWNLOAD_BOOT(UART0)" and appended prose
 *     like "(SPI_FAST_FLASH_BOOT failed)" are UNKNOWN; round-4 review:
 *     an inner group is not a free-form slot — the token and its shape/
 *     payload must match its own mode's documented form exactly):
 *       NORMAL:   (SPI_FAST_FLASH_BOOT) — simple form ONLY; any inner
 *                 group ("(SPI_FAST_FLASH_BOOT(failed))") is UNKNOWN
 *       DOWNLOAD: (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2)) and
 *                 (DOWNLOAD(USB/UART0)) — inner group REQUIRED with the
 *                 exact documented payload; "(DOWNLOAD)", "(DOWNLOAD())",
 *                 "(DOWNLOAD(garbage))" and payload swaps are UNKNOWN
 *     The documented unsupported modes (SPI_FLASH_BOOT,
 *     SDIO_REI_FEO_V1_BOOT, ATE_BOOT) match no form: neither normal,
 *     download nor usb-jtag -> UNKNOWN.
 *   - the USB-Serial-JTAG ROM banner, SUPPORTED SHAPE ONLY:
 *     "ESP-ROM:esp32s3-usb-jtag-<digits>" then end of line
 *     (case-insensitive; any other text carrying the marker is UNKNOWN).
 * Anything else — malformed lookalikes ("reboot: download failed",
 * "boot: download", "boot:0x3 DOWNLOAD_BOOT"), console prose, the plain
 * "ESP-ROM:esp32s3-<date>" version banner — is VDOG_BOOT_MODE_UNKNOWN.
 * NULL/empty → UNKNOWN. */
vdog_boot_mode_t vdog_recovery_classify(const char *rom_line);

/* Stable lowercase name for a boot mode (for logs/records). */
const char *vdog_boot_mode_name(vdog_boot_mode_t mode);

/* ---- sanitized identity (plan 1.2 A2, acceptance 5) --------------------- */
#define VDOG_IDENTITY_TAG_MAX 16 /* project label VDOG-<core>-<serial>   */

/* Closed set of renderable chip models: the formatter prints only these
 * internal names, never caller-supplied bytes (PR-review round 1). */
typedef enum {
    VDOG_IDENTITY_CHIP_UNKNOWN = 0, /* default; renders "unknown"         */
    VDOG_IDENTITY_CHIP_ESP32S3      /* renders "esp32s3"                  */
} vdog_identity_chip_t;

typedef struct {
    vdog_identity_chip_t chip; /* closed set, setter-validated           */
    uint8_t chip_major;        /* decoded via vdog_identity_set_revision */
    uint8_t chip_minor;
    vdog_mem_detected_t mem; /* tagged baseline summary (rendered by the
                              * caller's mem line; the identity line keeps
                              * only the compact configured summary)       */
    uint8_t mem_valid;       /* 1 = mem summary was baseline-checked       */
    uint16_t mac_tail;       /* LAST TWO BYTES only (0xABCD -> 0xABCD);
                              * a full MAC cannot exist in this struct.    */
    uint8_t mac_valid;       /* 0 = MAC not read (never invented)          */
    char tag[VDOG_IDENTITY_TAG_MAX + 1]; /* valid only when tag_len > 0;
                                          * bytes were charset-validated by
                                          * the setter; +1 = terminator slot
                                          * (round-2 review: the old 16-byte
                                          * array overflowed on a valid
                                          * 16-char tag)                */
    uint8_t tag_len;         /* 0 = absent (never rendered)                */
} vdog_identity_t;

/* Zero-init: chip UNKNOWN, rev 0.0, no mem, no mac, no tag. */
void vdog_identity_init(vdog_identity_t *id);

/* Chip model from the closed set, by name. Returns VDOG_OK and stores the
 * enum on an exact (case-insensitive) whitelist hit ("esp32s3"); returns
 * VDOG_ERR_INVALID_ARG and clears to UNKNOWN for NULL or anything outside
 * the set — unlisted text can never be echoed by the formatter. */
int vdog_identity_set_chip_model(vdog_identity_t *id, const char *model);

/* SDK chip-info revision is decimal major*100+minor (PR-review round 1:
 * byte-splitting rendered 102 as 0.102). Decode with /100 and %100:
 * 0 -> 0.0, 2 -> 0.2, 102 -> 1.2, 202 -> 2.2. */
void vdog_identity_set_revision(vdog_identity_t *id, uint16_t sdk_revision);

/* Board tag: FIXED PROJECT-LABEL GRAMMAR (round-4 review — callers cannot
 * smuggle a MAC, an 0x-prefixed hex blob or free text into the identity
 * line). Stored ONLY if it matches, case-insensitively:
 *     VDOG-<core>-<serial>
 * with <core> = 1..6 alphanumeric characters and <serial> = 1..4 digits
 * (maximum length 16 == VDOG_IDENTITY_TAG_MAX, so "0x020000000001",
 * "0200.0000.0001", "1a2b3c4d5e6f" and old free-text labels like "dev.01"
 * are all rejected). Accepted examples: "vdog-pa-01", "VDOG-PA-7". An
 * empty string clears it (VDOG_OK, tag_len 0); NULL or anything outside
 * the grammar returns VDOG_ERR_INVALID_ARG and leaves the previous value
 * untouched. The boot path keeps the tag empty anyway. */
int vdog_identity_set_board_tag(vdog_identity_t *id, const char *tag);

/* Compose ONE sanitized log line, e.g.
 *   "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:ab:cd board=vdog-pa-01"
 * Rules (host-pinned, plan 1.2 acceptance 5):
 *  - chip model rendered from the closed-set enum + revision as decoded by
 *    the setter;
 *  - "mem=" only when mem_valid (and only if it still passes the same
 *    baseline check the standalone line requires);
 *  - "mac=" renders the stored 16-bit tail as the last two octets with the
 *    OUI-independent mask prefix; absent when mac_valid == 0;
 *  - "board=" renders the setter-validated tag with an explicit length
 *    bound; absent when tag_len == 0;
 *  - no full MAC, no eFuse raw values, no serial, no caller-controlled
 *    format strings anywhere.
 * Buffer/NUL semantics identical to vdog_format_version(): VDOG_OK;
 * VDOG_ERR_INVALID_ARG on NULL buf/cap==0 or NULL id; VDOG_ERR_BUFFER_TOO_SMALL
 * when the exact NUL-terminated line (including final NUL) does not fit;
 * buffer contents unspecified on error. */
int vdog_identity_format(const vdog_identity_t *id, char *buf, size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_RECOVERY_H */
