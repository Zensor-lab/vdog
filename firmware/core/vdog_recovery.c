/*
 * vdog portable recovery/identity core module — implementation (package
 * 1.2, plan A2). Pure C11: stdio (snprintf) only. See vdog_recovery.h for
 * the contract: classification matches COMPLETE ROM banner forms only and
 * never guesses; the identity struct is the sanitizer (no member can hold
 * a full MAC or eFuse raw data, the chip model is a closed enum, and the
 * board tag is validated at set time and re-validated with a bounded scan
 * at render time — review M-C/M-D).
 */
#include <stdio.h>
#include <string.h>

#include "vdog_recovery.h"

static char ascii_lower(char c)
{
    if (c >= 'A' && c <= 'Z') {
        return (char)(c - 'A' + 'a');
    }
    return c;
}

/* Case-insensitive ASCII prefix test against a lowercase needle. */
static int starts_with_ci(const char *s, const char *lower_prefix)
{
    size_t i;

    for (i = 0; lower_prefix[i] != '\0'; ++i) {
        if (ascii_lower(s[i]) != lower_prefix[i]) {
            return 0;
        }
    }
    return 1;
}

static int is_hex_digit(char c)
{
    return ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
            (c >= 'A' && c <= 'F'))
               ? 1
               : 0;
}

static int is_banner_word_char(char c)
{
    return ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') ||
            (c >= 'A' && c <= 'Z') || c == '_' || c == '-')
               ? 1
               : 0;
}

/* Whole-token, case-insensitive equality against a lowercase needle, with
 * hyphen normalised to '_' so the ROM's hyphenated spellings (USB-JTAG)
 * match the underscored needle (usb_jtag). The token must match the WHOLE
 * needle (review M-C: no substring matching anywhere). */
static int token_equals(const char *tok, size_t len, const char *needle)
{
    size_t i;

    for (i = 0; i < len; ++i) {
        char c = ascii_lower(tok[i]);
        char n = needle[i];

        if (c == '-') {
            c = '_'; /* hyphen/underscore spelling equivalence */
        }
        if (n == '\0' || c != n) {
            return 0;
        }
    }
    return needle[len] == '\0';
}

/* Does the banner (text between the parentheses) contain, as a WHOLE word
 * token, any of the closed-set lowercase needles below? */
static int banner_has_word(const char *banner, size_t len,
                           const char *const *words, size_t n_words)
{
    size_t i = 0u;

    while (i < len) {
        size_t start;

        while (i < len && !is_banner_word_char(banner[i])) {
            ++i;
        }
        start = i;
        while (i < len && is_banner_word_char(banner[i])) {
            ++i;
        }
        if (i > start) {
            size_t w;
            for (w = 0u; w < n_words; ++w) {
                if (token_equals(banner + start, i - start, words[w])) {
                    return 1;
                }
            }
        }
    }
    return 0;
}

static const char *const g_vdog_jtag_words[] = {
    "usb_jtag", "usb_jtag_serial", "usb_jtag_serial_boot",
    "usb_jtag_download", "usb_jtag_serial_download", "usb_serial_jtag",
    "usb_serial_jtag_boot", "usb_serial_jtag_download"
};
static const char *const g_vdog_download_words[] = {
    "download", "download_boot", "uart_download", "sdio_download",
    "usb_download", "spi_fast_download"
};
static const char *const g_vdog_normal_words[] = {
    "spi_fast_flash", "spi_fast_flash_boot", "spi_flash_boot", "spi_boot",
    "basic", "encrypted_flash_boot"
};

#define VDOG_WORD_COUNT(a) (sizeof(a) / sizeof((a)[0]))

vdog_boot_mode_t vdog_recovery_classify(const char *rom_line)
{
    const char *line = rom_line;
    const char *open;
    const char *close;
    const char *p;

    if (line == NULL || line[0] == '\0') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    /* Form anchor (review M-C): the line must BE the ROM banner
     * "boot:0x<hex> (<banner>)", optionally space-padded. Prose that only
     * CONTAINS tokens never passes this gate. */
    while (*line == ' ' || *line == '\t') {
        ++line;
    }
    if (!starts_with_ci(line, "boot:0x")) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    p = line + 7u; /* strlen("boot:0x") */
    if (*p == '\0' || !is_hex_digit(*p)) {
        return VDOG_BOOT_MODE_UNKNOWN; /* "boot:0x" alone / bad hex */
    }
    while (is_hex_digit(*p)) {
        ++p;
    }
    while (*p == ' ' || *p == '\t') {
        ++p;
    }
    if (*p != '(') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    open = p + 1u;
    close = NULL;
    for (p = open; *p != '\0'; ++p) {
        if (*p == ')') {
            close = p;
        }
    }
    if (close == NULL || close < open) {
        return VDOG_BOOT_MODE_UNKNOWN; /* unclosed banner */
    }
    /* Nothing but spaces/tabs may follow the closing parenthesis. */
    for (p = close + 1u; *p != '\0'; ++p) {
        if (*p != ' ' && *p != '\t') {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
    }

    /* Closed-set whole-word classification inside the banner, documented
     * priority JTAG > download > normal ("spi_fast_download" is a download
     * form; a JTAG-path download banner is USBJTAG, not plain DOWNLOAD). */
    if (banner_has_word(open, (size_t)(close - open), g_vdog_jtag_words,
                        VDOG_WORD_COUNT(g_vdog_jtag_words))) {
        return VDOG_BOOT_MODE_USBJTAG;
    }
    if (banner_has_word(open, (size_t)(close - open), g_vdog_download_words,
                        VDOG_WORD_COUNT(g_vdog_download_words))) {
        return VDOG_BOOT_MODE_DOWNLOAD;
    }
    if (banner_has_word(open, (size_t)(close - open), g_vdog_normal_words,
                        VDOG_WORD_COUNT(g_vdog_normal_words))) {
        return VDOG_BOOT_MODE_NORMAL;
    }
    return VDOG_BOOT_MODE_UNKNOWN; /* unrecognised banner: never guessed */
}

const char *vdog_boot_mode_name(vdog_boot_mode_t mode)
{
    switch (mode) {
    case VDOG_BOOT_MODE_NORMAL:
        return "normal";
    case VDOG_BOOT_MODE_DOWNLOAD:
        return "download";
    case VDOG_BOOT_MODE_USBJTAG:
        return "usbjtag";
    default:
        return "unknown";
    }
}

void vdog_identity_init(vdog_identity_t *id)
{
    if (id == NULL) {
        return;
    }
    memset(id, 0, sizeof(*id));
    /* Everything absent: chip model UNKNOWN, mac_valid 0, mem_valid 0,
     * board tag "". Absent parts are never rendered. */
}

void vdog_identity_set_chip_model(vdog_identity_t *id,
                                  vdog_identity_chip_t model)
{
    if (id == NULL) {
        return;
    }
    /* Closed set: an out-of-range value collapses to UNKNOWN so the render
     * vocabulary stays fixed internally (review M-D). */
    id->chip_model = (model == VDOG_IDENTITY_CHIP_ESP32S3)
                         ? VDOG_IDENTITY_CHIP_ESP32S3
                         : VDOG_IDENTITY_CHIP_UNKNOWN;
}

static const char *chip_model_name(vdog_identity_chip_t model)
{
    switch (model) {
    case VDOG_IDENTITY_CHIP_ESP32S3:
        return "esp32s3";
    default:
        return "unknown";
    }
}

static int tag_char_ok(char c)
{
    return ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '_' || c == '-')
               ? 1
               : 0;
}

static int tag_hex_digit(char c)
{
    return ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
            (c >= 'A' && c <= 'F'))
               ? 1
               : 0;
}

/* Bounded validation scan (review M-D): reads AT MOST `cap` bytes of tag
 * (never past the storage), requires NUL termination within it, charset
 * [A-Za-z0-9_-], and rejects the compact-MAC lookalike — exactly 12 hex
 * digits, the shape of a full MAC written without separators. Returns the
 * tag length (0 = absent) or -1 when invalid. */
static int tag_validate(const char *tag, size_t cap)
{
    size_t i;

    for (i = 0u; i < cap; ++i) {
        if (tag[i] == '\0') {
            break;
        }
        if (!tag_char_ok(tag[i])) {
            return -1;
        }
    }
    if (i >= cap) {
        return -1; /* no NUL within capacity: unterminated */
    }
    if (i == 12u) {
        size_t j;
        int all_hex = 1;
        for (j = 0u; j < 12u; ++j) {
            if (!tag_hex_digit(tag[j])) {
                all_hex = 0;
                break;
            }
        }
        if (all_hex != 0) {
            return -1; /* compact-MAC lookalike: never stored, never sent */
        }
    }
    return (int)i;
}

int vdog_identity_set_board_tag(vdog_identity_t *id, const char *tag)
{
    if (id == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    if (tag == NULL || tag[0] == '\0') {
        id->board_tag[0] = '\0'; /* absent: "board=" omitted */
        return VDOG_OK;
    }
    if (tag_validate(tag, VDOG_IDENTITY_TAG_MAX) < 0) {
        return VDOG_ERR_IDENTITY_TAG; /* stored tag left UNCHANGED */
    }
    /* Validated content only, bounded copy that always NUL-terminates. */
    strcpy(id->board_tag, tag);
    return VDOG_OK;
}

void vdog_identity_set_revision_mxx(vdog_identity_t *id, uint16_t mxx)
{
    if (id == NULL) {
        return;
    }
    /* DECIMAL MXX (see header): wafer major = mxx/100, minor = mxx%100.
     * A byte split would render S3 v1.1 (raw 101) as the nonsense 0.101. */
    id->chip_major = (uint8_t)(mxx / 100u);
    id->chip_minor = (uint8_t)(mxx % 100u);
}

int vdog_identity_format(const vdog_identity_t *id, char *buf, size_t cap)
{
    char mem_part[64];
    char mac_part[32];
    char board_part[VDOG_IDENTITY_TAG_MAX + 16];
    int written;

    if (id == NULL || buf == NULL || cap == 0u) {
        return VDOG_ERR_INVALID_ARG;
    }
    mem_part[0] = '\0';
    if (id->mem_valid != 0u) {
        /* "Never render a rejected set": a mem summary renders only if it
         * passes the same baseline check the standalone line requires. */
        if (vdog_mem_check_baseline(&id->mem) != VDOG_OK) {
            return VDOG_ERR_INVALID_ARG;
        }
        written = snprintf(
            mem_part, sizeof(mem_part), " mem=%luMB-flash/%luMB-psram[%s-configured]",
            (unsigned long)(id->mem.flash_size_bytes / (1024u * 1024u)),
            (unsigned long)(id->mem.psram_size_bytes / (1024u * 1024u)),
            (id->mem.psram_mode == VDOG_BOARD_PSRAM_MODE_OPI) ? "opi" : "?");
        if (written < 0 || (size_t)written >= sizeof(mem_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    mac_part[0] = '\0';
    if (id->mac_valid != 0u) {
        /* Structural sanitizer: only the stored 16-bit tail can ever be
         * rendered — the last two octets, OUI masked. */
        written = snprintf(mac_part, sizeof(mac_part), " mac=**:**:**:**:%02x:%02x",
                           (unsigned)((id->mac_tail >> 8) & 0xFFu),
                           (unsigned)(id->mac_tail & 0xFFu));
        if (written < 0 || (size_t)written >= sizeof(mac_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    board_part[0] = '\0';
    if (id->board_tag[0] != '\0') {
        /* Defense in depth (review M-D): even a struct whose tag bypassed
         * the setter is RE-VALIDATED with a bounded scan before anything
         * is printed, and printed only via a precision-bounded conversion
         * of the validated length. Invalid bytes are omitted, never sent. */
        const int tag_len = tag_validate(id->board_tag, VDOG_IDENTITY_TAG_MAX);

        if (tag_len > 0) {
            written = snprintf(board_part, sizeof(board_part), " board=%.*s",
                               tag_len, id->board_tag);
            if (written < 0 || (size_t)written >= sizeof(board_part)) {
                return VDOG_ERR_BUFFER_TOO_SMALL;
            }
        }
    }
    written = snprintf(buf, cap, "chip=%s rev=%u.%u%s%s%s",
                       chip_model_name(id->chip_model),
                       (unsigned)id->chip_major, (unsigned)id->chip_minor,
                       mem_part, mac_part, board_part);
    if (written < 0 || (size_t)written >= cap) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    return VDOG_OK;
}
