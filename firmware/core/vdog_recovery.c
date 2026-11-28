/*
 * vdog portable recovery/identity core module — implementation (package
 * 1.2, plan A2). Pure C11: stdio (snprintf) only. See vdog_recovery.h for
 * the contract: classification matches recognized ROM forms against closed
 * mode-token sets (never free console text), and text enters the identity
 * struct only through validated setters (no member can hold a full MAC,
 * eFuse raw data, or unrenderable caller bytes).
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

static int is_token_char(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-';
}

static int is_hex_digit(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
           (c >= 'A' && c <= 'F');
}

/* Case-insensitive exact compare of a token slice against a lowercase
 * literal. */
static int token_ci_eq(const char *tok, size_t len, const char *lit)
{
    size_t i;
    size_t n = strlen(lit);
    if (len != n) {
        return 0;
    }
    for (i = 0; i < n; ++i) {
        if (ascii_lower(tok[i]) != lit[i]) {
            return 0;
        }
    }
    return 1;
}

static int token_in_set(const char *tok, size_t len,
                        const char *const *set, size_t count)
{
    size_t i;
    for (i = 0; i < count; ++i) {
        if (token_ci_eq(tok, len, set[i])) {
            return 1;
        }
    }
    return 0;
}

/* Case-insensitive "line starts with lowercase-literal" (literal is
 * lowercase). */
static int starts_with_ci(const char *line, const char *lit)
{
    size_t i;
    for (i = 0; lit[i] != '\0'; ++i) {
        if (ascii_lower(line[i]) != lit[i]) {
            return 0;
        }
    }
    return 1;
}

/* Case-insensitive substring search (lowercase needle); returns pointer or
 * NULL. */
static const char *find_ci(const char *haystack, const char *needle_lower)
{
    size_t n = strlen(needle_lower);
    size_t i;
    size_t j;
    for (i = 0; haystack[i] != '\0'; ++i) {
        for (j = 0; j < n; ++j) {
            if (haystack[i + j] == '\0' ||
                ascii_lower(haystack[i + j]) != needle_lower[j]) {
                break;
            }
        }
        if (j == n) {
            return haystack + i;
        }
    }
    return NULL;
}

/* Closed mode-token sets (checked in this order; disjoint today). */
static const char *const g_mode_usbjtag[] = {
    "usb_jtag", "usb-jtag", "usbjtag", "usb_jtag_serial"
};
static const char *const g_mode_download[] = {
    "download", "spi_fast_download", "basic_download", "usb_download"
};
static const char *const g_mode_normal[] = {
    "spi_fast", "spi_boot", "basic", "normal", "spi_fast_boot"
};

#define MODE_SET_COUNT(a) (sizeof(a) / sizeof((a)[0]))

static vdog_boot_mode_t mode_from_token(const char *tok, size_t len)
{
    if (token_in_set(tok, len, g_mode_usbjtag, MODE_SET_COUNT(g_mode_usbjtag))) {
        return VDOG_BOOT_MODE_USBJTAG;
    }
    if (token_in_set(tok, len, g_mode_download, MODE_SET_COUNT(g_mode_download))) {
        return VDOG_BOOT_MODE_DOWNLOAD;
    }
    if (token_in_set(tok, len, g_mode_normal, MODE_SET_COUNT(g_mode_normal))) {
        return VDOG_BOOT_MODE_NORMAL;
    }
    return VDOG_BOOT_MODE_UNKNOWN;
}

vdog_boot_mode_t vdog_recovery_classify(const char *rom_line)
{
    const char *p;
    const char *tok;
    size_t len;

    if (rom_line == NULL || rom_line[0] == '\0') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }

    /* ROM banner form: ESP-ROM:esp32s3-usb-jtag-<date>. The "esp-rom:"
     * prefix is what makes this a ROM form; the usb-jtag marker may sit
     * inside hyphen-joined banner text. */
    if (starts_with_ci(rom_line, "esp-rom:")) {
        const char *m;
        const char *rest = rom_line + 8;
        static const char *const markers[] = {"usb_jtag", "usb-jtag",
                                              "usbjtag"};
        size_t i;
        for (i = 0; i < MODE_SET_COUNT(markers); ++i) {
            m = find_ci(rest, markers[i]);
            if (m != NULL) {
                return VDOG_BOOT_MODE_USBJTAG;
            }
        }
        return VDOG_BOOT_MODE_UNKNOWN;
    }

    /* ROM boot-word form: "boot:0x..(<mode>)" (punctuation-delimited). */
    p = find_ci(rom_line, "boot:");
    if (p == NULL) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    p += 5; /* strlen("boot:") */
    while (*p != '\0' && !is_token_char(*p)) {
        ++p;
    }
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
        while (*p != '\0' && is_hex_digit(*p)) {
            ++p;
        }
        while (*p != '\0' && !is_token_char(*p)) {
            ++p;
        }
    }
    tok = p;
    while (*p != '\0' && is_token_char(*p)) {
        ++p;
    }
    len = (size_t)(p - tok);
    if (len == 0u) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    return mode_from_token(tok, len);
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

/* ---- sanitized identity (A2, acceptance 5) ------------------------------ */

static const char *const g_chip_names[] = {"unknown", "esp32s3"};
#define CHIP_NAME_COUNT (sizeof(g_chip_names) / sizeof(g_chip_names[0]))

void vdog_identity_init(vdog_identity_t *id)
{
    if (id == NULL) {
        return;
    }
    memset(id, 0, sizeof(*id));
    /* chip VDOG_IDENTITY_CHIP_UNKNOWN, rev 0.0, mem/mac/tag absent. Absent
     * parts are never rendered. */
}

int vdog_identity_set_chip_model(vdog_identity_t *id, const char *model)
{
    if (id == NULL || model == NULL || model[0] == '\0') {
        if (id != NULL) {
            id->chip = VDOG_IDENTITY_CHIP_UNKNOWN;
        }
        return VDOG_ERR_INVALID_ARG;
    }
    if (token_ci_eq(model, strlen(model), "esp32s3")) {
        id->chip = VDOG_IDENTITY_CHIP_ESP32S3;
        return VDOG_OK;
    }
    /* Closed set: unlisted text is rejected and never stored or echoed. */
    id->chip = VDOG_IDENTITY_CHIP_UNKNOWN;
    return VDOG_ERR_INVALID_ARG;
}

void vdog_identity_set_revision(vdog_identity_t *id, uint16_t sdk_revision)
{
    if (id == NULL) {
        return;
    }
    /* IDF reports revision as decimal major*100 + minor. */
    id->chip_major = (uint8_t)(sdk_revision / 100u);
    id->chip_minor = (uint8_t)(sdk_revision % 100u);
}

int vdog_identity_set_board_tag(vdog_identity_t *id, const char *tag)
{
    size_t n;
    size_t i;

    if (id == NULL || tag == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    n = strlen(tag);
    if (n == 0u) {
        id->tag_len = 0u; /* clearing is always legal */
        return VDOG_OK;
    }
    if (n > VDOG_IDENTITY_TAG_MAX) {
        return VDOG_ERR_INVALID_ARG;
    }
    for (i = 0; i < n; ++i) {
        char c = tag[i];
        int ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                 (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-';
        if (!ok) {
            return VDOG_ERR_INVALID_ARG;
        }
    }
    memcpy(id->tag, tag, n);
    id->tag[n] = '\0';
    id->tag_len = (uint8_t)n;
    return VDOG_OK;
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
        written = snprintf(mem_part, sizeof(mem_part),
                           " mem=%luMB-flash/%luMB-psram[%s-configured]",
                           (unsigned long)(id->mem.flash_size_bytes /
                                           (1024u * 1024u)),
                           (unsigned long)(id->mem.psram_size_bytes /
                                           (1024u * 1024u)),
                           (id->mem.psram_mode == VDOG_BOARD_PSRAM_MODE_OPI)
                               ? "opi"
                               : "?");
        if (written < 0 || (size_t)written >= sizeof(mem_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    mac_part[0] = '\0';
    if (id->mac_valid != 0u) {
        /* Structural sanitizer: only the stored 16-bit tail can ever be
         * rendered — the last two octets, OUI masked. */
        written = snprintf(mac_part, sizeof(mac_part),
                           " mac=**:**:**:**:%02x:%02x",
                           (unsigned)((id->mac_tail >> 8) & 0xFFu),
                           (unsigned)(id->mac_tail & 0xFFu));
        if (written < 0 || (size_t)written >= sizeof(mac_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    board_part[0] = '\0';
    if (id->tag_len != 0u) {
        /* Bounded render: the setter guaranteed charset + length, and the
         * explicit precision keeps even a corrupted tag_len from reading
         * past the array. */
        int bound = (id->tag_len <= VDOG_IDENTITY_TAG_MAX)
                        ? (int)id->tag_len
                        : VDOG_IDENTITY_TAG_MAX;
        written = snprintf(board_part, sizeof(board_part), " board=%.*s", bound,
                           id->tag);
        if (written < 0 || (size_t)written >= sizeof(board_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    written = snprintf(buf, cap, "chip=%s rev=%u.%u%s%s%s",
                       ((unsigned)id->chip < CHIP_NAME_COUNT)
                           ? g_chip_names[(unsigned)id->chip]
                           : "unknown",
                       (unsigned)id->chip_major, (unsigned)id->chip_minor,
                       mem_part, mac_part, board_part);
    if (written < 0 || (size_t)written >= cap) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    return VDOG_OK;
}
