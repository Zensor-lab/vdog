/*
 * vdog portable recovery/identity core module — implementation (package
 * 1.2, plan A2). Pure C11: stdio (snprintf) only. See vdog_recovery.h for
 * the contracts: the classifier matches COMPLETE ROM-line forms only
 * (review R2-A — anchored "rst:0xNN (CAUSE),boot:0xNN (BANNER)" with the
 * banner WHOLE-matching a closed set from the esptool ESP32-S3 boot-log
 * reference) and never guesses; the identity struct is the sanitizer
 * (reviews M-D/R2-B — closed-set chip model, narrow vdg- project label,
 * bounded re-validation at render time, no member can hold a full MAC).
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

/* Case-insensitive ASCII compare of the first n bytes of s against a
 * lowercase needle (no <ctype.h> locale surprises). */
static int starts_with_ci_n(const char *s, size_t len, const char *needle)
{
    size_t n = strlen(needle);
    size_t i;

    if (len < n) {
        return 0;
    }
    for (i = 0; i < n; ++i) {
        if (ascii_lower(s[i]) != needle[i]) {
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

static unsigned hex_val(char c)
{
    if (c >= '0' && c <= '9') {
        return (unsigned)(c - '0');
    }
    return (unsigned)(ascii_lower(c) - 'a' + 10);
}

static int is_blank(char c)
{
    return (c == ' ' || c == '\t') ? 1 : 0;
}

static size_t skip_blank(const char *s, size_t i, size_t end)
{
    while (i < end && is_blank(s[i])) {
        ++i;
    }
    return i;
}

/* Parse "0x" + exactly 1..2 hex digits at s[i]; returns the new index and
 * the value, or (size_t)-1 when malformed. */
static size_t parse_hex12(const char *s, size_t i, size_t end, unsigned *out)
{
    size_t digits;

    if (!(i + 1u < end && s[i] == '0' && (s[i + 1u] == 'x' || s[i + 1u] == 'X'))) {
        return (size_t)-1;
    }
    i += 2u;
    digits = i;
    while (i < end && is_hex_digit(s[i])) {
        ++i;
    }
    if (i - digits < 1u || i - digits > 2u) {
        return (size_t)-1; /* ROM values fit in 8 bits: 1..2 digits only */
    }
    {
        size_t k;
        unsigned v = 0u;
        for (k = digits; k < i; ++k) {
            v = v * 16u + hex_val(s[k]);
        }
        *out = v;
    }
    return i;
}

static int is_cause_char(char c)
{
    return ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') ||
            (c >= 'A' && c <= 'Z') || c == '_')
               ? 1
               : 0;
}

/* ---- closed banner sets: EXACTLY the esptool ESP32-S3 boot-log reference
 * ("Boot Mode Selection", Boot Log / Boot Mode Message) list. Whole-banner
 * equality (case-insensitive, hyphen/underscore equivalent), never
 * substrings. SPI_FLASH_BOOT / SDIO_REI_FEO_V1_BOOT / ATE_BOOT are listed
 * there as UNSUPPORTED boot modes and are deliberately absent: they
 * classify UNKNOWN, never "closest class". */
static const char *const g_vdog_normal_banners[] = {
    "spi_fast_flash_boot"
};
static const char *const g_vdog_download_banners[] = {
    "download(usb/uart0)",
    "download_boot(uart0/uart1/sdio_rei_reo_v2)"
};

/* Whole-banner equality against one lowercase needle, with hyphen
 * normalised to '_' on the INPUT side (the ROM's hyphenated spellings
 * match the underscored needle). */
static int banner_equals(const char *banner, size_t len, const char *needle)
{
    size_t i;

    for (i = 0; i < len; ++i) {
        char c = ascii_lower(banner[i]);
        char n = needle[i];

        if (c == '-') {
            c = '_';
        }
        if (n == '\0' || c != n) {
            return 0;
        }
    }
    return needle[len] == '\0';
}

static int banner_in_set(const char *banner, size_t len,
                         const char *const *set, size_t n)
{
    size_t k;

    for (k = 0; k < n; ++k) {
        if (banner_equals(banner, len, set[k])) {
            return 1;
        }
    }
    return 0;
}

/* Reset-cause names of the ROM RESET_REASON enum (installed framework's
 * ROM reset-reason header for this target; the esptool boot-log reference
 * points at exactly this enum for the rst:0xNN (REASON) mapping). A name
 * here is CAUSE_KNOWN; any other well-formed token is UNRECOGNISED but
 * never vetoes the boot-mode verdict. */
static const char *const g_vdog_cause_names[] = {
    "poweron_reset",
    "rtc_sw_sys_reset",
    "deepsleep_reset",
    "tg0wdt_sys_reset",
    "tg1wdt_sys_reset",
    "rtcwdt_sys_reset",
    "intrusion_reset",
    "tg0wdt_cpu_reset",
    "rtc_sw_cpu_reset",
    "rtcwdt_cpu_reset",
    "rtcwdt_brown_out_reset",
    "rtcwdt_rtc_reset",
    "tg1wdt_cpu_reset",
    "super_wdt_reset",
    "glitch_rtc_reset",
    "efuse_reset",
    "usb_uart_chip_reset",
    "usb_jtag_chip_reset",
    "power_glitch_reset"
};

static int cause_is_known(const char *name, size_t len)
{
    size_t k;
    size_t n = sizeof(g_vdog_cause_names) / sizeof(g_vdog_cause_names[0]);

    for (k = 0; k < n; ++k) {
        if (banner_equals(name, len, g_vdog_cause_names[k])) {
            return 1; /* banner_equals' hyphen fold is harmless here */
        }
    }
    return 0;
}

void vdog_boot_evidence_init(vdog_boot_evidence_t *out)
{
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    out->boot_mode = VDOG_BOOT_MODE_UNKNOWN;
    out->cause_state = VDOG_BOOT_CAUSE_NONE;
}

/* Parse the already right-trimmed line s[0..end). Evidence commits ONLY on
 * full-form success; on any miss it stays cleared (no half claims). */
static vdog_boot_mode_t classify_line(const char *s, size_t end,
                                      vdog_boot_evidence_t *ev)
{
    size_t i = skip_blank(s, 0, end);
    vdog_boot_cause_state_t cause_state = VDOG_BOOT_CAUSE_NONE;
    uint8_t rst_value = 0u;
    char cause_name[VDOG_BOOT_CAUSE_MAX + 1u];
    const char *open;
    const char *close;
    size_t banner_len;
    size_t j;

    cause_name[0] = '\0';

    /* Optional "rst:0xNN (CAUSE)," prefix — structurally exact or the
     * WHOLE line is UNKNOWN (review R2-A). */
    if (starts_with_ci_n(s + i, end - i, "rst:")) {
        unsigned val = 0u;
        size_t cause_start;
        size_t cause_len;

        i += 4u; /* strlen("rst:") */
        i = parse_hex12(s, i, end, &val);
        if (i == (size_t)-1) {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
        i = skip_blank(s, i, end);
        if (i >= end || s[i] != '(') {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
        ++i;
        cause_start = i;
        while (i < end && is_cause_char(s[i])) {
            ++i;
        }
        cause_len = i - cause_start;
        if (i >= end || s[i] != ')') {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
        ++i;
        if (i >= end || s[i] != ',') {
            return VDOG_BOOT_MODE_UNKNOWN;
        }
        ++i;
        if (cause_len < 1u || cause_len > VDOG_BOOT_CAUSE_MAX) {
            return VDOG_BOOT_MODE_UNKNOWN; /* empty/oversized: malformed */
        }
        memcpy(cause_name, s + cause_start, cause_len);
        cause_name[cause_len] = '\0';
        rst_value = (uint8_t)val;
        cause_state = cause_is_known(cause_name, cause_len)
                          ? VDOG_BOOT_CAUSE_KNOWN
                          : VDOG_BOOT_CAUSE_UNRECOGNISED;
    }

    i = skip_blank(s, i, end);
    if (!starts_with_ci_n(s + i, end - i, "boot:")) {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    i += 5u; /* strlen("boot:") */
    {
        unsigned boot_val = 0u;
        i = parse_hex12(s, i, end, &boot_val);
        if (i == (size_t)-1) {
            return VDOG_BOOT_MODE_UNKNOWN; /* "boot:0x" alone / bad hex */
        }
    }
    i = skip_blank(s, i, end);
    if (i >= end || s[i] != '(') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    open = s + i + 1u;
    close = NULL;
    for (j = (size_t)(open - s); j < end; ++j) {
        if (s[j] == ')') {
            close = s + j; /* keep the LAST close: the documented
                            * DOWNLOAD_BOOT spelling itself contains
                            * "(UART0/UART1/...)" */
        }
    }
    if (close == NULL) {
        return VDOG_BOOT_MODE_UNKNOWN; /* unclosed banner */
    }
    banner_len = (size_t)(close - open);
    for (j = (size_t)(close - s) + 1u; j < end; ++j) {
        if (!is_blank(s[j])) {
            return VDOG_BOOT_MODE_UNKNOWN; /* junk after ")" */
        }
    }

    if (banner_in_set(open, banner_len, g_vdog_normal_banners,
                      sizeof(g_vdog_normal_banners) /
                          sizeof(g_vdog_normal_banners[0]))) {
        ev->boot_mode = VDOG_BOOT_MODE_NORMAL;
    } else if (banner_in_set(open, banner_len, g_vdog_download_banners,
                             sizeof(g_vdog_download_banners) /
                                 sizeof(g_vdog_download_banners[0]))) {
        ev->boot_mode = VDOG_BOOT_MODE_DOWNLOAD;
    } else {
        return VDOG_BOOT_MODE_UNKNOWN; /* closed set only, never guessed */
    }
    /* Full-form success: commit the evidence. */
    ev->cause_state = cause_state;
    ev->rst_value = rst_value;
    memcpy(ev->cause_name, cause_name, sizeof(ev->cause_name));
    return ev->boot_mode;
}

int vdog_recovery_classify_boot(const char *rom_line,
                                vdog_boot_evidence_t *out)
{
    size_t end;

    if (out == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    vdog_boot_evidence_init(out);
    if (rom_line == NULL) {
        return VDOG_OK; /* UNKNOWN, cleared */
    }
    /* Documented line-ending policy (header): strip trailing CR/LF and
     * blanks at entry, so CRLF/LF/bare lines classify identically. */
    end = strlen(rom_line);
    while (end > 0u && (rom_line[end - 1u] == '\r' ||
                        rom_line[end - 1u] == '\n' ||
                        is_blank(rom_line[end - 1u]))) {
        --end;
    }
    (void)classify_line(rom_line, end, out);
    if (out->boot_mode == VDOG_BOOT_MODE_UNKNOWN) {
        vdog_boot_evidence_init(out); /* unrecognized: no half claims */
    }
    return VDOG_OK;
}

vdog_boot_mode_t vdog_recovery_classify(const char *rom_line)
{
    vdog_boot_evidence_t ev;

    (void)vdog_recovery_classify_boot(rom_line, &ev);
    return ev.boot_mode; /* documented wrapper (header) */
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

/* ---- sanitized identity (reviews M-D / R2-B) ------------------------------ */

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

static int tag_is_alnum(char c)
{
    return ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9'))
               ? 1
               : 0;
}

static int tag_is_body_char(char c)
{
    return (tag_is_alnum(c) || c == '_') ? 1 : 0;
}

static int tag_is_hex_digit(char c)
{
    return ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
            (c >= 'A' && c <= 'F'))
               ? 1
               : 0;
}

/* Bounded validation scan (reviews M-D/R2-B): reads AT MOST `cap` bytes of
 * tag (never past the storage). Accepts ONLY the narrow project-label
 * format vdg-[A-Za-z0-9_]{1,11} (prefix case-insensitive; canonical
 * spelling is lowercase) AND rejects the MAC skeleton: with every
 * non-alphanumeric removed and a leading "0x"/"0X" removed ('x' IS
 * alphanumeric, so the prefix needs its own step), exactly 12 hex digits
 * is rejected — no MAC spelling in any grouping can be stored or rendered.
 * Returns the tag length (0 = absent) or -1 when invalid. */
static int tag_validate(const char *tag, size_t cap)
{
    size_t i;
    size_t n;
    char skeleton[VDOG_IDENTITY_TAG_MAX];
    size_t m = 0u;

    for (i = 0u; i < cap; ++i) {
        if (tag[i] == '\0') {
            break;
        }
    }
    if (i >= cap) {
        return -1; /* no NUL within capacity: unterminated */
    }
    n = i;
    if (n < 5u || n > 15u) {
        return -1; /* "vdg-" + 1..11 body chars inside the 16-byte field */
    }
    if (!(ascii_lower(tag[0]) == 'v' && ascii_lower(tag[1]) == 'd' &&
          ascii_lower(tag[2]) == 'g' && tag[3] == '-')) {
        return -1; /* mandatory vdg- prefix (case-insensitive) */
    }
    for (i = 4u; i < n; ++i) {
        if (!tag_is_body_char(tag[i])) {
            return -1; /* body charset [A-Za-z0-9_] only */
        }
    }
    for (i = 0u; i < n; ++i) {
        if (tag_is_alnum(tag[i])) {
            skeleton[m++] = tag[i];
        }
    }
    if (m >= 2u && skeleton[0] == '0' &&
        (ascii_lower(skeleton[1]) == 'x')) {
        size_t k;
        for (k = 2u; k < m; ++k) {
            skeleton[k - 2u] = skeleton[k];
        }
        m -= 2u;
    }
    if (m == 12u) {
        size_t j;
        int all_hex = 1;
        for (j = 0u; j < 12u; ++j) {
            if (!tag_is_hex_digit(skeleton[j])) {
                all_hex = 0;
                break;
            }
        }
        if (all_hex != 0) {
            return -1; /* MAC skeleton in any spelling: never stored,
                        * never rendered */
        }
    }
    return (int)n;
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
    /* Validated content only, bounded copy that always NUL-terminates
     * (validated length <= 15 into the 16-byte field). */
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
        /* Defense in depth (reviews M-D/R2-B): even a struct whose tag
         * bypassed the setter is RE-VALIDATED with the same bounded scan
         * (termination + vdg- format + MAC-skeleton rule) before anything
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
