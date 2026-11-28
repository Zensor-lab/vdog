/*
 * vdog portable recovery/identity core module (package 1.2, plan A2).
 *
 * Pure C11, no SDK/OS headers, host-tested; target-side reads live in
 * components/vdog_board/vdog_board_hw.c. Two jobs:
 *
 * 1) BOOT/USB recovery evidence: classify the ROM reset-&-boot-mode line
 *    the 1.2 drill prints, COMPLETE-LINE FORM only (normal flash boot vs
 *    download mode), and expose the reset-reason evidence (review R2-A:
 *    lead finding 1b wants the reset cause recorded). Unknown input is
 *    UNKNOWN — never guessed.
 * 2) Sanitized identity line: the struct stores ONLY what may be logged.
 *    There is deliberately no full-MAC member and no eFuse-raw member: the
 *    sanitizer is structural (host-pinned), not an after-the-fact mask —
 *    a full MAC can never be formatted because it can never be stored,
 *    and the board tag is a narrow project-issued label, never a hardware
 *    identifier (review R2-B).
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

/* ---- ROM boot-mode classification (plan 1.2 A2, reviews M-C/R2-A) -------- */
typedef enum {
    VDOG_BOOT_MODE_UNKNOWN = 0, /* never guessed from junk                 */
    VDOG_BOOT_MODE_NORMAL,      /* executed from flash (SPI boot paths)    */
    VDOG_BOOT_MODE_DOWNLOAD,    /* ROM serial/bootloader download mode     */
    VDOG_BOOT_MODE_USBJTAG      /* RESERVED: the ESP32-S3 boot-log
                                 * reference lists no USB-Serial-JTAG
                                 * banner spelling (grounded negative), so
                                 * the classifier never returns this —
                                 * kept for log vocabulary stability      */
} vdog_boot_mode_t;

/* Longest reset-cause name stored in evidence (ROM names fit; longer
 * tokens are structurally invalid, not UNRECOGNISED). */
#define VDOG_BOOT_CAUSE_MAX 23

/* State of the optional rst:0xNN (CAUSE), prefix of a ROM line. KNOWN
 * means the (VALUE, NAME) PAIR matched the core's ROM table (review
 * R3-A; ground truth per review round 5: the ESP32-S3 ROM's OWN
 * reset-reason label table, extracted from the vendor ROM ELF — path,
 * sha256 and method documented in core/vdog_recovery.c). Per value the
 * union of the extracted ROM label (the canonical stored) and the ROM
 * reset-reason header's enum spelling — e.g. 0x1 accepts "POWERON" and
 * "POWERON_RESET"; 0x9 accepts "RTCWDT_SYS_RST" (ROM label) and
 * "RTCWDT_SYS_RESET" (enum). Codes at which the ROM table carries no
 * label (indices 0/2/4/6/14, shared "N/A") have no pair and are always
 * UNRECOGNISED. A known name with the wrong value, or a known
 * value with the wrong name, is UNRECOGNISED (never "closest match");
 * the boot-mode verdict always comes from the BANNER alone. */
typedef enum {
    VDOG_BOOT_CAUSE_NONE = 0,       /* no rst: prefix on this line         */
    VDOG_BOOT_CAUSE_KNOWN,          /* (value, name) pair matched the
                                     * cited ROM table                     */
    VDOG_BOOT_CAUSE_UNRECOGNISED    /* well-formed [A-Za-z0-9_]{1,23}
                                     * token or value/name mismatch: not
                                     * named in the evidence (see below),
                                     * never vetoes the boot-mode verdict  */
} vdog_boot_cause_state_t;

/* What ONE recognized ROM line proves. Valid ONLY after
 * vdog_recovery_classify_boot() recognized the FULL line form; any line
 * that is not recognized yields a fully cleared evidence (no half
 * claims). cause_name (review R3-B): populated ONLY for
 * VDOG_BOOT_CAUSE_KNOWN, and then only with the matched entry's CANONICAL
 * spelling from the cited table — never the input bytes verbatim; for
 * NONE/UNRECOGNISED the whole field is zeroed ("" with all bytes past
 * the NUL zero too, asserted by tests). A synthetic MAC typed as the
 * cause token therefore cannot escape into the structured result; the
 * ROM's raw token lives only in the caller's raw transcript, which the
 * Part B drill records verbatim OUTSIDE this API (verbatim-everything
 * stance, plan §6 B4/B5). */
typedef struct {
    vdog_boot_mode_t boot_mode;
    vdog_boot_cause_state_t cause_state;
    uint8_t rst_value; /* parsed hex whenever the rst: prefix was
                        * well-formed (KNOWN or UNRECOGNISED); 0 for NONE */
    char cause_name[VDOG_BOOT_CAUSE_MAX + 1u]; /* canonical or ""         */
} vdog_boot_evidence_t;

/* Clear evidence: UNKNOWN + NONE + rst 0 + "" cause. out NULL is a no-op
 * (caller contract; classify_boot rejects NULL with an error code). */
void vdog_boot_evidence_init(vdog_boot_evidence_t *out);

/* Classify ONE ROM/console line by COMPLETE documented ROM-line form only
 * (review R2-A). The input must BE the ROM's reset-&-boot-mode line, as
 * the esptool ESP32-S3 "Boot Mode Selection" reference documents it
 * (docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/
 * boot-mode-selection.html, "Boot Log / Boot Mode Message"):
 *
 *   [blanks] [rst:0xN (CAUSE),] [blanks] boot:0xN (BANNER) [blanks]
 *
 * - Line-ending policy: trailing CR, LF, spaces and tabs are stripped at
 *   entry (serial monitors deliver CRLF; the drill may hand over LF-only
 *   or bare lines), leading blanks are tolerated. Optional single spaces
 *   or tabs are ALSO allowed only between fields — before "rst:"/"boot:",
 *   between the hex value and its "(" — never inside "rst:0x.."/
 *   "boot:0x..", never inside a parenthesis, never after the final ")".
 * - The optional rst: prefix, when present, must be structurally exact:
 *   "rst:0x" + 1..2 hex digits (the ROM prints the 8-bit reset value) +
 *   optional blanks + "(" + CAUSE + ")" + ",". CAUSE is
 *   [A-Za-z0-9_]{1,23}; its NAME never changes the boot-mode verdict
 *   (UNRECOGNISED still classifies the banner) but a STRUCTURALLY broken
 *   prefix (bad/missing hex, missing (), missing comma, empty or
 *   oversized cause, spaces in the cause) makes the WHOLE line UNKNOWN.
 * - BANNER must EQUAL, as a whole, one spelling from the closed set below
 *   (case-insensitive ASCII; hyphen and underscore equivalent). Prose in
 *   the parentheses — even a real token plus extra words such as
 *   "SPI_FAST_FLASH_BOOT extra" or "download failed" — is UNKNOWN.
 *
 * Closed set (EXACTLY what the reference lists for ESP32-S3):
 *   SPI_FAST_FLASH_BOOT
 *       -> VDOG_BOOT_MODE_NORMAL  (the normal SPI flash boot mode)
 *   DOWNLOAD(USB/UART0)
 *   DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2)
 *       -> VDOG_BOOT_MODE_DOWNLOAD (download flashing mode, suitable for
 *          esptool; the two documented spellings name the USB/UART0 and
 *          the UART/SDIO download interfaces)
 * The reference ALSO lists SPI_FLASH_BOOT, SDIO_REI_FEO_V1_BOOT and
 * ATE_BOOT as "an unsupported boot mode has been selected" — this
 * classifier deliberately maps them to UNKNOWN (never "closest class").
 * The reference's "or similar" is NOT open-ended here: an undocumented
 * variant stays UNKNOWN and Part B's verbatim transcript keeps it for
 * human review. VDOG_BOOT_MODE_USBJTAG has no documented S3 spelling and
 * is never returned.
 *
 * Verbatim-everything stance (Part B, plan §6 B4/B5): the drill transcript
 * records EVERY raw line as captured; this classifier only NAMES the state
 * a recognised line proves and never replaces or filters the record. */
int vdog_recovery_classify_boot(const char *rom_line,
                                vdog_boot_evidence_t *out);

/* Compatibility wrapper (documented contract, host-pinned): returns ONLY
 * the boot-mode verdict of vdog_recovery_classify_boot() for the same
 * input; the reset-cause evidence is discarded. NULL out of evidence is
 * not possible here — same parse, same closed set, same line-ending
 * policy. NULL line -> VDOG_BOOT_MODE_UNKNOWN. */
vdog_boot_mode_t vdog_recovery_classify(const char *rom_line);

/* Stable lowercase names for a boot mode (for logs/records). */
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

#define VDOG_IDENTITY_TAG_MAX 16 /* board tag storage INCLUDING its NUL   */

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
    char board_tag[VDOG_IDENTITY_TAG_MAX]; /* project label, set ONLY via
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

/* Validate-then-store the board tag: a PROJECT-ISSUED OPAQUE LABEL, NOT A
 * HARDWARE IDENTIFIER (review R2-B). Narrow format — the tag must be
 * exactly
 *
 *     vdg-[A-Za-z0-9_]{1,11}
 *
 * i.e. the mandatory prefix "vdg-" (matched case-insensitively; the
 * canonical spelling used in records is LOWERCASE "vdg-") followed by 1 to
 * 11 characters from [A-Za-z0-9_] (no hyphens/dots/colons/spaces in the
 * body; total tag length 5..15 chars inside the 16-byte field).
 * Additionally, ANY tag whose non-alphanumeric characters are removed
 * (and a leading "0x"/"0X" then removed — 'x' is alphanumeric) is exactly
 * 12 hex digits is REJECTED: no MAC spelling (compact, 0x-prefixed,
 * hyphen/dot/colon grouped, upper or lower case) can ever be stored or
 * rendered through this channel. Together with tail-only MAC storage this
 * is what "structurally cannot emit a MAC" means.
 *
 * Returns VDOG_OK and stores the tag when valid; VDOG_ERR_INVALID_ARG
 * when id is NULL; VDOG_ERR_IDENTITY_TAG when the content is unacceptable
 * — then the stored tag is UNCHANGED (never half-set, never rendered):
 *   - not NUL-terminated within VDOG_IDENTITY_TAG_MAX bytes (a bounded
 *     scan reads at most that many bytes — an unterminated array can
 *     neither be stored nor cause an out-of-bounds render);
 *   - missing/non-lowercase-free "vdg-" prefix, empty or oversized body,
 *     any body character outside [A-Za-z0-9_];
 *   - the stripped 12-hex-digit (MAC) form above.
 * NULL or "" clears the tag (absent: "board=" is then omitted). */
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
 *   "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] mac=**:**:**:**:ab:cd board=vdg-001"
 * Rules (host-pinned, plan 1.2 acceptance 5):
 *  - chip model + revision always rendered; the model is the closed-set
 *    enum printed from fixed internal names (never a caller buffer),
 *    "unknown" for anything unrecognised;
 *  - "mem=" only when mem_valid (already baseline-checked summary — the
 *    compact configured form; the full tagged line is vdog_mem_format's
 *    job and is logged separately);
 *  - "mac=" renders the stored 16-bit tail as the last two octets with the
 *    OUI-independent mask prefix; absent when mac_valid == 0;
 *  - "board=" only when a VALIDATED vdg- label is present: the formatter
 *    RE-validates it with the same bounded scan (termination + format +
 *    MAC-skeleton rule) and prints it only via a precision-bounded
 *    conversion — raw unvalidated bytes can never reach the line (reviews
 *    M-D/R2-B, including bytes smuggled past the setter);
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
