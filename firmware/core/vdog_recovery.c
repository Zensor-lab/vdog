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

/* Number of leading space/tab characters (usage: p += skip_spaces(p)). */
static size_t skip_spaces(const char *s)
{
    size_t n = 0u;
    while (s[n] == ' ' || s[n] == '\t') {
        ++n;
    }
    return n;
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

/* DOCUMENTED ROM descriptions (esptool boot-mode-selection "Boot Mode
 * Message", ESP32-S3) — the ONLY forms that classify, validated BY MODE
 * in vdog_recovery_classify() (round-4 review):
 *   NORMAL    (SPI_FAST_FLASH_BOOT)                      simple form only
 *   DOWNLOAD  (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))
 *             (DOWNLOAD(USB/UART0))                      exact payload
 * The documented unsupported modes (SPI_FLASH_BOOT, SDIO_REI_FEO_V1_BOOT,
 * ATE_BOOT) match nothing: neither normal, download, nor usb-jtag ->
 * UNKNOWN, and no token may borrow another mode's shape or payload. */

/* Find the next ROM boot-word marker "boot:" that is a WORD, not a
 * substring: the match must start the line or follow a non-token
 * character. This is what keeps "reboot: download failed" from ever
 * classifying (round-2 review High finding). */
static const char *find_boot_word(const char *line)
{
    const char *p = line;
    while ((p = find_ci(p, "boot:")) != NULL) {
        if (p == line || !is_token_char(p[-1])) {
            return p;
        }
        ++p;
    }
    return NULL;
}

vdog_boot_mode_t vdog_recovery_classify(const char *rom_line)
{
    const char *p;
    const char *tok;
    size_t len;
    vdog_boot_mode_t mode;

    if (rom_line == NULL || rom_line[0] == '\0') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }

    /* ROM banner form, SUPPORTED SHAPE ONLY (round-3 review: not "any
     * occurrence of the marker"): ESP-ROM:esp32s3-usb-jtag-<digits>
     * followed by end of line. The ordinary version banner
     * "ESP-ROM:esp32s3-<date>" and any prose carrying the marker stay
     * UNKNOWN. */
    if (starts_with_ci(rom_line, "esp-rom:")) {
        const char *rest = rom_line + 8; /* strlen("esp-rom:") */
        rest += skip_spaces(rest);
        if (!token_ci_eq(rest, 17u, "esp32s3-usb-jtag-")) {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
        rest += 17;
        len = 0u;
        while (*rest >= '0' && *rest <= '9') {
            ++rest;
            ++len;
        }
        if (len == 0u) {
            return VDOG_BOOT_MODE_UNKNOWN; /* no <date> digits */
        }
        rest += skip_spaces(rest);
        return (*rest == '\0') ? VDOG_BOOT_MODE_USBJTAG
                               : VDOG_BOOT_MODE_UNKNOWN;
    }

    /* ROM boot-word form, EXACTLY as documented:
     *   rst:0xNN (REASON),boot:0xNN (DESCRIPTION)
     * Round-3 review: the COMPLETE description must match — balanced
     * parentheses and nothing after them. Truncations
     * ("boot:0x3 (DOWNLOAD", "(DOWNLOAD_BOOT(UART0)", one missing close
     * paren) and prose appended after the leading token
     * ("(SPI_FAST_FLASH_BOOT failed)") are malformed lookalikes ->
     * UNKNOWN. Round-4 review: the description is then validated BY
     * MODE below — see the DOCUMENTED ROM descriptions block above. */
    p = find_boot_word(rom_line);
    if (p == NULL) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    p += 5; /* strlen("boot:") */
    p += skip_spaces(p);
    if (p[0] != '0' || (p[1] != 'x' && p[1] != 'X')) {
        return VDOG_BOOT_MODE_UNKNOWN; /* documented form carries 0xNN */
    }
    p += 2;
    len = 0u;
    while (is_hex_digit(*p)) {
        ++p;
        ++len;
    }
    if (len == 0u) {
        return VDOG_BOOT_MODE_UNKNOWN; /* "boot:0x(" is not a boot word */
    }
    p += skip_spaces(p);
    if (*p != '(') {
        return VDOG_BOOT_MODE_UNKNOWN; /* DESCRIPTION must be parenthesized */
    }
    ++p;
    tok = p;
    while (*p != '\0' && is_token_char(*p)) {
        ++p;
    }
    len = (size_t)(p - tok);
    if (len == 0u) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    /* ROUND-4 REVIEW HIGH: validate the description BY MODE — an inner
     * group is not a free-form slot that any token may carry.
     * NORMAL accepts the simple documented form only, so
     * "(SPI_FAST_FLASH_BOOT(failed))" is a malformed lookalike; each
     * DOWNLOAD variant REQUIRES its inner group with the exact
     * documented payload, so "(DOWNLOAD())", "(DOWNLOAD(garbage))" and
     * the shortened "(DOWNLOAD_BOOT(UART0))" are UNKNOWN. Tokens outside
     * the documented set never classify regardless of shape. */
    if (token_ci_eq(tok, len, "spi_fast_flash_boot")) {
        if (*p != ')') {
            return VDOG_BOOT_MODE_UNKNOWN; /* normal: simple form only */
        }
        ++p;
        mode = VDOG_BOOT_MODE_NORMAL;
    } else if (token_ci_eq(tok, len, "download_boot") ||
               token_ci_eq(tok, len, "download")) {
        const char *payload;
        size_t payload_len;
        const char *documented =
            token_ci_eq(tok, len, "download_boot")
                ? "uart0/uart1/sdio_rei_reo_v2" /* documented DOWNLOAD_BOOT */
                : "usb/uart0";                   /* documented DOWNLOAD      */
        if (*p != '(') {
            return VDOG_BOOT_MODE_UNKNOWN; /* download forms carry the group */
        }
        ++p;
        payload = p;
        while (*p != '\0' && *p != ')' && *p != '(') {
            ++p;
        }
        payload_len = (size_t)(p - payload);
        if (*p != ')' ||
            !token_ci_eq(payload, payload_len, documented)) {
            return VDOG_BOOT_MODE_UNKNOWN; /* missing/empty/undocumented */
        }
        ++p;
        if (*p != ')') {
            return VDOG_BOOT_MODE_UNKNOWN; /* outer group must close right after */
        }
        ++p;
        mode = VDOG_BOOT_MODE_DOWNLOAD;
    } else {
        return VDOG_BOOT_MODE_UNKNOWN; /* token not documented at all */
    }
    p += skip_spaces(p);
    if (*p != '\0') {
        return VDOG_BOOT_MODE_UNKNOWN; /* nothing after the closed group */
    }
    return mode;
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

/* Fixed project-label grammar for board tags (round-4 review Medium —
 * "use a project-issued label with a fixed format and a short numeric
 * suffix"). Accepted form, case-insensitive:
 *     VDOG-<core>-<serial>
 * with <core> = 1..6 alphanumeric characters and <serial> = 1..4 digits
 * (grammar maximum length 16 == VDOG_IDENTITY_TAG_MAX). Because the
 * "vdog-" literal itself carries non-hex letters, a MAC (any notation),
 * an 0x-prefixed hex blob or any other free text CANNOT pass — the
 * round-2/3 hex and separator heuristics are replaced by this grammar. */
static int tag_grammar_ok(const char *t, size_t n)
{
    static const char lit[] = "vdog-";
    size_t i;
    size_t core = 0u;
    size_t serial = 0u;

    for (i = 0; i < 5u; ++i) { /* bounded literal prefix: t may be short */
        if (i >= n || ascii_lower(t[i]) != lit[i]) {
            return 0;
        }
    }
    i = 5u;
    while (i < n && t[i] != '-') {
        char c = t[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9')) || ++core > 6u) {
            return 0;
        }
        ++i;
    }
    if (core == 0u || i >= n || t[i] != '-') {
        return 0; /* empty core or missing '-' before the serial */
    }
    ++i;
    while (i < n) {
        if (t[i] < '0' || t[i] > '9' || ++serial > 4u) {
            return 0;
        }
        ++i;
    }
    return serial >= 1u && i == n;
}

int vdog_identity_set_board_tag(vdog_identity_t *id, const char *tag)
{
    size_t n;

    if (id == NULL || tag == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    n = strlen(tag);
    if (n == 0u) {
        id->tag_len = 0u; /* clearing is always legal */
        return VDOG_OK;
    }
    if (n > VDOG_IDENTITY_TAG_MAX || !tag_grammar_ok(tag, n)) {
        /* Only the fixed project-label grammar is stored; a rejected
         * attempt never disturbs a previously valid tag. */
        return VDOG_ERR_INVALID_ARG;
    }
    memcpy(id->tag, tag, n);
    id->tag[n] = '\0'; /* fits: array is TAG_MAX+1 (terminator slot) */
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
