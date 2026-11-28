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

/* Classify ONE ROM/console line by COMPLETE boot-banner form only (plan 1.2
 * review M-C): the input must BE a ROM boot banner, not merely contain a
 * token somewhere. Accepted form (per the esptool/ESP32-S3 boot-mode docs,
 * lines the ROM actually prints):
 *
 *     [spaces] boot:0x<hex> [spaces] ( <banner> ) [spaces]
 *
 * Inside the parentheses the banner is split into WORD tokens (alphanumeric
 * and '_', hyphen normalised to '_') and each WHOLE token is compared
 * case-insensitively against closed sets:
 *   - usb_jtag / usb_jtag_serial / usb_serial_jtag (and their *_boot /
 *     *_download compounds) -> VDOG_BOOT_MODE_USBJTAG
 *   - download / download_boot / uart_download / sdio_download /
 *     usb_download / spi_fast_download -> VDOG_BOOT_MODE_DOWNLOAD
 *   - spi_fast_flash / spi_fast_flash_boot / spi_flash_boot / spi_boot /
 *     basic / encrypted_flash_boot     -> VDOG_BOOT_MODE_NORMAL
 * Word priority (documented, checked in this order): a banner carrying both
 * a JTAG word and a download word is USBJTAG; "spi_fast_download" is a
 * download form, not a normal-boot form. Anything else — prose merely
 * CONTAINING tokens ("download failed", "boot loader", "fast pattern"),
 * truncated lookalikes ("spi_fas", bare "boot:0x", missing/unclosed
 * parentheses, non-hex after "boot:0x") — is VDOG_BOOT_MODE_UNKNOWN.
 * Verbatim-everything stance (Part B, plan §6 B4/B5): the drill transcript
 * records EVERY raw line as captured; this classifier only NAMES the state
 * a recognised banner proves and never replaces or filters the record. */
vdog_boot_mode_t vdog_recovery_classify(const char *rom_line);

/* Stable lowercase name for a boot mode (for logs/records). */
const char *vdog_boot_mode_name(vdog_boot_mode_t mode);

/* ---- sanitized identity (plan 1.2 A2, acceptance 5) --------------------- */
/* Review M-D: the renderable identity text is CLOSED, not caller-fed.
 * VDOG_ERR_IDENTITY_TAG names a rejected board-tag set attempt. */
#define VDOG_ERR_IDENTITY_TAG (-24)

/* The only chip models this module can ever render (target is ESP32-S3;
 * anything the adapter does not recognise stays UNKNOWN and renders as
 * "unknown"). There is deliberately NO caller-supplied model string. */
typedef enum {
    VDOG_IDENTITY_CHIP_UNKNOWN = 0,
    VDOG_IDENTITY_CHIP_ESP32S3 = 1
} vdog_identity_chip_t;

#define VDOG_IDENTITY_TAG_MAX 16 /* opaque caller board tag INCLUDING its
                                  * NUL; optional, "" when absent          */

typedef struct {
    vdog_identity_chip_t chip_model; /* closed set (M-D), set ONLY via
                                      * vdog_identity_set_chip_model()      */
    uint8_t chip_major;              /* chip revision major                 */
    uint8_t chip_minor;              /* chip revision minor                 */
    vdog_mem_detected_t mem; /* tagged baseline summary (rendered by the
                              * caller's mem line; the identity line keeps
                              * only the compact configured summary)       */
    uint8_t mem_valid;       /* 1 = mem summary was baseline-checked       */
    uint16_t mac_tail;       /* LAST TWO BYTES only (0xABCD -> 0xABCD);
                              * a full MAC cannot exist in this struct.    */
    uint8_t mac_valid;       /* 0 = MAC not read (never invented)          */
    char board_tag[VDOG_IDENTITY_TAG_MAX]; /* opaque, set ONLY via
                              * vdog_identity_set_board_tag(); "" absent.
                              * Reading it raw is not part of the contract:
                              * only the formatter interprets it, after its
                              * own bounded re-validation.                  */
} vdog_identity_t;

/* Zero-init with empty/UNKNOWN defaults: absent parts are never rendered. */
void vdog_identity_init(vdog_identity_t *id);

/* Set the closed-set chip model (the target adapter maps the SDK's
 * read-only chip-info query result onto this). An out-of-range value is
 * stored as UNKNOWN — the render vocabulary is fixed internally, so no
 * caller string can ever reach the log (review M-D: a compact MAC typed as
 * a "model" is impossible). NULL id is a no-op. */
void vdog_identity_set_chip_model(vdog_identity_t *id,
                                  vdog_identity_chip_t model);

/* Validate-then-store the opaque board tag (label, never an identifier).
 * Returns VDOG_OK and stores the tag when valid; VDOG_ERR_INVALID_ARG when
 * id is NULL; VDOG_ERR_IDENTITY_TAG when the content is unacceptable —
 * then the stored tag is UNCHANGED (never half-set, never rendered):
 *   - not NUL-terminated within VDOG_IDENTITY_TAG_MAX bytes (a bounded
 *     scan reads at most that many bytes — an unterminated array can
 *     neither be stored nor cause an out-of-bounds render);
 *   - any character outside [A-Za-z0-9_-] (no ':', '.', spaces, control);
 *   - compact-MAC lookalike: exactly 12 hex digits ([0-9a-fA-F]{12}) —
 *     the shape of a full MAC written without separators. Combined with
 *     the tail-only storage this is what "structurally cannot emit a MAC"
 *     actually means: there is no setter, field or render path that can
 *     carry more than a validated short label. NULL or "" clears the tag
 *     (absent: "board=" is then omitted). Valid length is 1..15 chars. */
int vdog_identity_set_board_tag(vdog_identity_t *id, const char *tag);

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
 *  - chip model + revision always rendered; the model is the closed-set
 *    enum printed from fixed internal names (never a caller buffer),
 *    "unknown" for anything unrecognised;
 *  - "mem=" only when mem_valid (already baseline-checked summary — the
 *    compact configured form; the full tagged line is vdog_mem_format's
 *    job and is logged separately);
 *  - "mac=" renders the stored 16-bit tail as the last two octets with the
 *    OUI-independent mask prefix; absent when mac_valid == 0;
 *  - "board=" only when a VALIDATED opaque tag is present: the formatter
 *    re-validates it with a bounded scan (charset + termination) and
 *    prints it only via a precision-bounded conversion — raw unvalidated
 *    bytes can never reach the line (review M-D);
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
