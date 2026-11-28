/*
 * C++ consumer smoke check for the vdog portable memory-baseline core
 * (package 1.2, mirrors cpp_smoke_board.cpp from package 1.1): proves the
 * extern "C" linkage and enum-typed members survive a C++ translation
 * unit. Called from test_vdog_mem.c across the link boundary.
 */
#include "vdog_mem.h"

static int same(const char *a, const char *b)
{
    if (a == NULL || b == NULL) {
        return a == b;
    }
    while (*a != '\0' && *b != '\0') {
        if (*a != *b) {
            return 0;
        }
        ++a;
        ++b;
    }
    return *a == *b;
}

extern "C" int vdog_mem_cpp_smoke(void)
{
    vdog_mem_detected_t d;
    char buf[192];

    vdog_mem_detected_init(&d);
    if (vdog_mem_check_baseline(&d) != VDOG_ERR_MEM_MISSING_FIELD) {
        return 10;
    }
    if (!same(vdog_mem_error_field(), "flash_size_bytes")) {
        return 11;
    }

    d.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    d.flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_SIZE;
    d.flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    d.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
    d.flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    d.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_FREQ;
    d.psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    d.psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_PRESENT;
    d.psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    d.psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_SIZE;
    d.psram_mode = VDOG_MEM_BASELINE_PSRAM_MODE;
    d.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_MODE;
    d.psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    d.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_SPEED;
    if (vdog_mem_check_baseline(&d) != VDOG_OK) {
        return 12;
    }
    if (vdog_mem_format_detected(&d, buf, sizeof(buf)) != VDOG_OK) {
        return 13;
    }
    if (!same(buf, "flash_size=8MB[measured] flash_mode=qio[configured] "
                   "flash_freq=80m[configured] psram=8MB[measured:init-ok] "
                   "psram_mode=opi[configured] psram_speed=80m[configured]")) {
        return 14;
    }

    /* Enum-typed members accept the documented constants from C++. */
    d.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    if (vdog_mem_check_baseline(&d) != VDOG_ERR_MEM_PSRAM) {
        return 15;
    }
    if (!same(vdog_mem_error_field(), "psram_mode")) {
        return 16;
    }

    return 0;
}
