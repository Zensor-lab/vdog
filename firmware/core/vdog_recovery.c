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

/* Reset-cause PAIR TABLE (ground truth per review round 5): KNOWN
 * requires the parsed rst VALUE and the printed NAME to agree on one
 * entry. The authoritative vocabulary is the ESP32-S3 ROM's OWN
 * reset-reason label table: 24 entries (index = the rst:0xNN code) at
 * vaddr 0x3ff18e10 in the vendor ROM ELF esp32s3_rev0_rom.elf, Espressif
 * esp-rom-elfs release 20241011. Extracted from the INSTALLED copy
 * (~/.platformio/packages/tool-esp-rom-elfs/esp32s3_rev0_rom.elf,
 * sha256
 * c0ce0f338d1de1bdc6efbef1591779a2a42c1ab7d759d3c6ae8ae63a7dd34cfd,
 * verified byte-identical to the release asset): PT_LOAD vaddr 0x3ff18c00
 * -> file offset 0x5be10, 24 little-endian 32-bit pointers read via
 * python3/struct, strings dereferenced. ROM label table (index: print,
 * extracted 2026-11-28): 1 POWERON, 3 RTC_SW_SYS_RST, 5 DSLEEP,
 * 7 TG0WDT_SYS_RST, 8 TG1WDT_SYS_RST, 9 RTCWDT_SYS_RST, 10 INTRUSION_RST,
 * 11 TG0WDT_CPU_RST, 12 RTC_SW_CPU_RST, 13 RTCWDT_CPU_RST, 15 BROWNOUT_RST,
 * 16 RTCWDT_RTC_RST, 17 TG1WDT_CPU_RST, 18 SUPER_WDT_RST, 19 GLITCH_RTC_RST,
 * 20 EFUSE_RST, 21 USB_UART_CHIP_RESET, 22 USB_JTAG_CHIP_RESET,
 * 23 POWER_GLITCH_RESET; indices 0, 2, 4, 6 and 14 all point at one
 * shared "N/A" string: the ROM prints NO label for those codes, so they
 * get no row (any token at those values is UNRECOGNISED; no ROM code
 * there ever pairs). Per row the primary = the extracted ROM label
 * (canonical, stored on a KNOWN match) and the alias = the ROM
 * RESET_REASON enum spelling (installed framework's esp32s3 ROM
 * reset-reason header, the enum the esptool boot-log reference points
 * at) when it differs — the UNION rule, case-insensitive. Published
 * captures corroborate the labels (POWERON/RTC_SW_CPU_RST: the
 * installed partitions_ota README; RTC_SW_SYS_RST: Seeed XIAO
 * ESP32-S3 capture, community issue #10588; TG0WDT_SYS_RST/
 * TG1WDT_SYS_RST: the Espressif ESP-Techpedia watchdog doc "Common
 * LOG"; SUPER_WDT_RST: community issue #14243, ESP32-S3-WROOM-1, IDF
 * v5.1.2; RTCWDT_RTC_RST: community issue #6980, S3-DevKitC-1).
 * Round-5 RECONCILIATION: publication-hunt primaries that differ from
 * the extracted label (rounds 3/4 accepted DEEPSLEEP_RESET at 5,
 * RTCWDT_SYS_RESET at 9, INTRUSION_RESET at 10, TG0WDT_CPU_RESET at
 * 11, RTCWDT_CPU_RESET at 13, RTCWDT_BROWN_OUT_RESET at 15,
 * RTCWDT_RTC_RESET at 16, TG1WDT_CPU_RESET at 17, GLITCH_RTC_RESET at
 * 19, EFUSE_RESET at 20 — all documented rtc.h spellings with
 * published captures) now store the LABEL and keep those enum
 * spellings as aliases: both remain accepted, only the label is ever
 * stored. Earlier rounds' note that DSLEEP@5/EFUSE-family prints were
 * "C-series only" was WRONG for the S3 ROM — superseded by this
 * extraction. Mismatched pairs (name-known-but-wrong-value or
 * value-known-but-wrong-name) are UNRECOGNISED — never "closest
 * match"; the boot verdict always comes from the BANNER alone. The
 * structured cause_name stores ONLY the entry's canonical primary
 * (review R3-B): unrecognised tokens, including MAC-shaped ones, are
 * never copied into the evidence (they live only in the caller's
 * verbatim transcript, which Part B keeps outside this API). */
typedef struct {
    uint8_t value;       /* the ROM's rst:0xNN code (ROM label table idx) */
    const char *primary; /* canonical name stored on a KNOWN match        */
    const char *alias;   /* accepted alternate spelling, or NULL          */
} vdog_cause_entry_t;

static const vdog_cause_entry_t g_vdog_causes[] = {
    {1u,  "POWERON",             "POWERON_RESET"},           /* ROM label / enum  */
    {3u,  "RTC_SW_SYS_RST",      "RTC_SW_SYS_RESET"},
    {5u,  "DSLEEP",              "DEEPSLEEP_RESET"},
    {7u,  "TG0WDT_SYS_RST",      "TG0WDT_SYS_RESET"},
    {8u,  "TG1WDT_SYS_RST",      "TG1WDT_SYS_RESET"},
    {9u,  "RTCWDT_SYS_RST",      "RTCWDT_SYS_RESET"},
    {10u, "INTRUSION_RST",       "INTRUSION_RESET"},
    {11u, "TG0WDT_CPU_RST",      "TG0WDT_CPU_RESET"},
    {12u, "RTC_SW_CPU_RST",      "RTC_SW_CPU_RESET"},
    {13u, "RTCWDT_CPU_RST",      "RTCWDT_CPU_RESET"},
    {15u, "BROWNOUT_RST",        "RTCWDT_BROWN_OUT_RESET"},
    {16u, "RTCWDT_RTC_RST",      "RTCWDT_RTC_RESET"},
    {17u, "TG1WDT_CPU_RST",      "TG1WDT_CPU_RESET"},
    {18u, "SUPER_WDT_RST",       "SUPER_WDT_RESET"},
    {19u, "GLITCH_RTC_RST",      "GLITCH_RTC_RESET"},
    {20u, "EFUSE_RST",           "EFUSE_RESET"},
    {21u, "USB_UART_CHIP_RESET", NULL},                       /* label == enum     */
    {22u, "USB_JTAG_CHIP_RESET", NULL},
    {23u, "POWER_GLITCH_RESET",  NULL}
};

/* Plain case-insensitive whole-string equality (no hyphen folding: reset
 * cause spellings contain only [A-Za-z0-9_]). */
static int name_equals_ci(const char *tok, size_t len, const char *name)
{
    size_t i;

    for (i = 0; i < len; ++i) {
        if (name[i] == '\0' || ascii_lower(tok[i]) != ascii_lower(name[i])) {
            return 0;
        }
    }
    return name[len] == '\0';
}

/* Pair-matched lookup: returns the entry's canonical name ONLY when the
 * parsed value and the printed token agree on one entry (union of the
 * value's documented spellings), else NULL. */
static const char *cause_lookup(unsigned value, const char *tok, size_t len)
{
    size_t k;
    size_t n = sizeof(g_vdog_causes) / sizeof(g_vdog_causes[0]);

    for (k = 0; k < n; ++k) {
        if (g_vdog_causes[k].value != (uint8_t)value) {
            continue;
        }
        if (name_equals_ci(tok, len, g_vdog_causes[k].primary)) {
            return g_vdog_causes[k].primary;
        }
        if (g_vdog_causes[k].alias != NULL &&
            name_equals_ci(tok, len, g_vdog_causes[k].alias)) {
            return g_vdog_causes[k].primary;
        }
        return NULL; /* right value, wrong name: mismatch is NOT nearest */
    }
    return NULL; /* wrong value: wrong-name pairs never match by name */
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
    const char *cause_canonical = NULL;
    /* Whole array zero-initialized (review R3-B): the match token is a
     * scratch buffer that is NEVER committed to the evidence; only the
     * table's canonical spelling ever reaches cause_name. */
    char cause_tok[VDOG_BOOT_CAUSE_MAX + 1u] = { '\0' };
    const char *open;
    const char *close;
    size_t banner_len;
    size_t j;

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
        memcpy(cause_tok, s + cause_start, cause_len);
        cause_tok[cause_len] = '\0'; /* scratch only: never committed */
        rst_value = (uint8_t)val;
        cause_canonical = cause_lookup(val, cause_tok, cause_len);
        cause_state = (cause_canonical != NULL) ? VDOG_BOOT_CAUSE_KNOWN
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
    /* Full-form success: commit the evidence (review R3-B: the struct was
     * fully cleared at the entry point; cause_name is explicitly
     * zero-filled here too, and ONLY the canonical table spelling is
     * written — bytes after the NUL are always zero, and an unrecognised
     * token (even a MAC-shaped one) can never land in the struct). */
    ev->cause_state = cause_state;
    ev->rst_value = rst_value;
    memset(ev->cause_name, 0, sizeof(ev->cause_name));
    if (cause_state == VDOG_BOOT_CAUSE_KNOWN) {
        memcpy(ev->cause_name, cause_canonical, strlen(cause_canonical));
    }
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
