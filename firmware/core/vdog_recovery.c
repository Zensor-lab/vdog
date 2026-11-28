/*
 * vdog portable recovery/identity core module — implementation (package
 * 1.2, plan A2). Pure C11: stdio (snprintf) only. See vdog_recovery.h for
 * the contract: classification never guesses, and the identity struct is
 * the sanitizer (no member can hold a full MAC or eFuse raw data).
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

/* Case-insensitive ASCII substring test (no <ctype.h> locale surprises). */
static int contains_ci(const char *haystack, const char *needle_lower)
{
    size_t n = strlen(needle_lower);
    size_t i;
    size_t j;

    if (haystack == NULL) {
        return 0;
    }
    for (i = 0; haystack[i] != '\0'; ++i) {
        for (j = 0; j < n; ++j) {
            if (haystack[i + j] == '\0' ||
                ascii_lower(haystack[i + j]) != needle_lower[j]) {
                break;
            }
        }
        if (j == n) {
            return 1;
        }
    }
    return 0;
}

vdog_boot_mode_t vdog_recovery_classify(const char *rom_line)
{
    if (rom_line == NULL || rom_line[0] == '\0') {
        return VDOG_BOOT_MODE_UNKNOWN;
    }
    /* Order is contractual (header): JTAG first, then any download banner
     * (covers "spi_fast_download"), then the normal-boot spellings. */
    if (contains_ci(rom_line, "usb_jtag") || contains_ci(rom_line, "usb-jtag")) {
        return VDOG_BOOT_MODE_USBJTAG;
    }
    if (contains_ci(rom_line, "download")) {
        return VDOG_BOOT_MODE_DOWNLOAD;
    }
    if (contains_ci(rom_line, "spi_fast") || contains_ci(rom_line, "spi_boot") ||
        contains_ci(rom_line, "basic")) {
        return VDOG_BOOT_MODE_NORMAL;
    }
    return VDOG_BOOT_MODE_UNKNOWN;
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
    /* Everything absent: chip model empty, mac_valid 0, mem_valid 0,
     * board tag "". Absent parts are never rendered. */
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
        written = snprintf(board_part, sizeof(board_part), " board=%s",
                           id->board_tag);
        if (written < 0 || (size_t)written >= sizeof(board_part)) {
            return VDOG_ERR_BUFFER_TOO_SMALL;
        }
    }
    written = snprintf(buf, cap, "chip=%s rev=%u.%u%s%s%s",
                       (id->chip_model[0] != '\0') ? id->chip_model : "unknown",
                       (unsigned)id->chip_major, (unsigned)id->chip_minor,
                       mem_part, mac_part, board_part);
    if (written < 0 || (size_t)written >= cap) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    return VDOG_OK;
}
