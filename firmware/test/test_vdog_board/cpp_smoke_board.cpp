/*
 * C++ consumer smoke check for the vdog portable board-profile core
 * (package 1.1, mirrors test_vdog_core/cpp_smoke.cpp from package 0.2).
 *
 * This translation unit includes vdog_board.h from C++ and calls the API
 * through the extern "C" interface. It is compiled and LINKED into the
 * native test binary (a C test calls vdog_board_cpp_smoke(), so the linker
 * must resolve the C-linkage symbol across the C/C++ boundary — not just a
 * header parse), and into the embedded build-only test image.
 * No C++ runtime facilities are used, so no extra runtime library is
 * required on either side.
 */
#include "vdog_board.h"

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

} // namespace

extern "C" int vdog_board_cpp_smoke(void);

int vdog_board_cpp_smoke(void)
{
    vdog_board_profile_t profile = vdog_board_expected_profile_proto();
    char buf[160];

    /* The expected-provisional profile is fully marked and accepted. */
    if (profile.field_set != VDOG_BOARD_FIELD_ALL) {
        return 1;
    }
    if (vdog_board_validate(&profile) != VDOG_OK) {
        return 2;
    }
    if (vdog_board_error_field() != nullptr) {
        return 3;
    }

    /* Report from C++: exact text and exact-fit behaviour. */
    if (vdog_board_report(&profile, buf, sizeof(buf)) != VDOG_OK) {
        return 4;
    }
    if (!same(buf, "vdog 0.2.0-proto board=seeed_xiao_esp32s3 target=esp32s3 "
                   "flash=8MB-qio-80m psram=8MB-opi-80m")) {
        return 5;
    }
    if (vdog_board_report(&profile, buf, 16u) != VDOG_ERR_BUFFER_TOO_SMALL) {
        return 6;
    }
    if (vdog_board_report(&profile, nullptr, sizeof(buf)) !=
        VDOG_ERR_INVALID_ARG) {
        return 7;
    }

    /* Explicit-field semantics from C++: unset is missing, never defaulted. */
    vdog_board_profile_t blank;
    vdog_board_profile_init(&blank);
    if (blank.field_set != 0u) {
        return 8;
    }
    if (vdog_board_validate(&blank) != VDOG_ERR_BOARD_MISSING_FIELD) {
        return 9;
    }
    if (!same(vdog_board_error_field(), "target")) {
        return 10;
    }

    /* Wrong octal-PSRAM mode must be the PSRAM code naming psram_mode. */
    profile = vdog_board_expected_profile_proto();
    profile.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    if (vdog_board_validate(&profile) != VDOG_ERR_BOARD_PSRAM) {
        return 11;
    }
    if (!same(vdog_board_error_field(), "psram_mode")) {
        return 12;
    }
    if (vdog_board_report(&profile, buf, sizeof(buf)) != VDOG_ERR_BOARD_PSRAM) {
        return 13;
    }

    /* Enum-typed members accept the documented constants from C++. */
    profile = vdog_board_expected_profile_proto();
    profile.flash_mode = VDOG_BOARD_FLASH_MODE_DIO;
    if (vdog_board_validate(&profile) != VDOG_ERR_BOARD_FLASH) {
        return 14;
    }
    if (!same(vdog_board_error_field(), "flash_mode")) {
        return 15;
    }

    return 0;
}
