/*
 * C++ consumer smoke check for the vdog portable memory-baseline core
 * (package 1.2 Part A; mirrors cpp_smoke_board.cpp from package 1.1).
 *
 * This translation unit includes vdog_mem.h from C++ and calls the API
 * through the extern "C" interface. It is compiled and LINKED into the
 * native test binary (a C test calls vdog_mem_cpp_smoke(), so the linker
 * must resolve the C-linkage symbol across the C/C++ boundary — not just a
 * header parse), and into the embedded build-only test image. No C++
 * runtime facilities are used.
 */
#include "vdog_mem.h"

namespace {

/* Tiny local comparison so this TU needs no C++/C runtime headers at all. */
bool same(const char *a, const char *b)
{
    if (a == nullptr || b == nullptr) {
        return a == b;
    }
    while (*a != '\0' && *b != '\0') {
        if (*a != *b) {
            return false;
        }
        ++a;
        ++b;
    }
    return *a == *b && *b == '\0';
}

/* Fully probed baseline detector with required evidence tags. */
vdog_mem_detected_t ok_detector()
{
    vdog_mem_detected_t det;

    vdog_mem_detected_init(&det);
    det.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    det.flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    det.flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    det.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    det.psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    det.psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    det.psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    det.psram_mode = VDOG_MEM_BASELINE_PSRAM_MODE;
    det.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    det.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set = VDOG_MEM_FIELD_ALL;
    return det;
}

} // namespace

extern "C" int vdog_mem_cpp_smoke(void);

int vdog_mem_cpp_smoke(void)
{
    vdog_mem_detected_t det = ok_detector();
    char buf[256];

    /* Baseline accepted from C++; error_field cleared on success. */
    if (vdog_mem_check_baseline(&det) != VDOG_OK) {
        return 1;
    }
    if (vdog_mem_error_field() != nullptr) {
        return 2;
    }

    /* Exact tagged render line through the C++ boundary. */
    if (vdog_mem_format_detected(&det, buf, sizeof(buf)) != VDOG_OK) {
        return 3;
    }
    if (!same(buf, "flash_size=8MB[measured] flash_mode=qio[configured] "
                   "flash_freq=80m[configured] psram=8MB[measured:init-ok] "
                   "psram_mode=opi[configured] psram_speed=80m[configured]")) {
        return 4;
    }

    /* Buffer semantics from C++. */
    if (vdog_mem_format_detected(&det, buf, 8u) != VDOG_ERR_BUFFER_TOO_SMALL) {
        return 5;
    }
    if (vdog_mem_format_detected(&det, nullptr, sizeof(buf)) !=
        VDOG_ERR_INVALID_ARG) {
        return 6;
    }

    /* Enum-typed/uint8 members accept the documented constants from C++
     * and the source policy is enforced across the boundary: a CONFIGURED
     * PSRAM capacity never satisfies the detected baseline. */
    det = ok_detector();
    det.psram_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    if (vdog_mem_check_baseline(&det) != VDOG_ERR_MEM_SOURCE) {
        return 7;
    }
    if (!same(vdog_mem_error_field(), "psram_size_bytes")) {
        return 8;
    }
    if (vdog_mem_format_detected(&det, buf, sizeof(buf)) != VDOG_ERR_MEM_SOURCE) {
        return 9;
    }

    /* Explicit-field semantics from C++: unset is missing, never defaulted. */
    vdog_mem_detected_t blank;
    vdog_mem_detected_init(&blank);
    if (blank.field_set != 0u) {
        return 10;
    }
    if (vdog_mem_check_baseline(&blank) != VDOG_ERR_MEM_MISSING_FIELD) {
        return 11;
    }
    if (!same(vdog_mem_error_field(), "flash_size_bytes")) {
        return 12;
    }

    /* Quad-only PSRAM class from C++. */
    det = ok_detector();
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    if (vdog_mem_check_baseline(&det) != VDOG_ERR_MEM_PSRAM) {
        return 13;
    }
    if (!same(vdog_mem_error_field(), "psram_mode")) {
        return 14;
    }

    return 0;
}
