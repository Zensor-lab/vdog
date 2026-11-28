/*
 * C++ consumer smoke check for the vdog portable strap/reserved-pin table
 * (package 1.2 Part A; mirrors cpp_smoke_board.cpp from package 1.1).
 *
 * This translation unit includes vdog_straps.h from C++ and calls the API
 * through the extern "C" interface. It is compiled and LINKED into the
 * native test binary (a C test calls vdog_straps_cpp_smoke(), so the
 * linker must resolve the C-linkage symbol across the C/C++ boundary — not
 * just a header parse), and into the embedded build-only test image. No C++
 * runtime facilities are used.
 */
#include "vdog_straps.h"

extern "C" int vdog_straps_cpp_smoke(void);

int vdog_straps_cpp_smoke(void)
{
    const char *role = nullptr;

    /* Reserved strap pins reject claims from C++ too, naming the role. */
    if (vdog_straps_check_claim(0u, VDOG_STRAPS_CLAIM_GENERAL, &role) !=
        VDOG_STRAPS_REJECT) {
        return 1;
    }
    if (role == nullptr) {
        return 2; /* reject must name the pin's role */
    }

    /* Candidates answer PROVISIONAL — never OK/approved — for every
     * claimant, including GENERAL. */
    if (vdog_straps_check_claim(15u, VDOG_STRAPS_CLAIM_GENERAL, &role) !=
        VDOG_STRAPS_PROVISIONAL) {
        return 3;
    }
    if (vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_SD, nullptr) !=
        VDOG_STRAPS_PROVISIONAL) {
        return 4;
    }

    /* Microphone baseline stays dead; SoC-absent pins REJECT (review H-B);
     * documented free expansion rows pass. */
    if (vdog_straps_check_claim(41u, VDOG_STRAPS_CLAIM_GENERAL, nullptr) !=
        VDOG_STRAPS_REJECT) {
        return 5;
    }
    if (vdog_straps_check_claim(22u, VDOG_STRAPS_CLAIM_GENERAL, nullptr) !=
        VDOG_STRAPS_REJECT) {
        return 6;
    }
    if (vdog_straps_check_claim(44u, VDOG_STRAPS_CLAIM_GENERAL, nullptr) !=
        VDOG_STRAPS_OK) {
        return 10;
    }

    /* Enum-typed inputs from C++; invalid inputs named. */
    if (vdog_straps_check_claim(49u, VDOG_STRAPS_CLAIM_CAMERA, &role) !=
        VDOG_STRAPS_REJECT) {
        return 7;
    }
    const vdog_straps_row_t *rows = vdog_straps_table();
    if (rows == nullptr || vdog_straps_table_count() == 0u) {
        return 8;
    }
    if (vdog_straps_lookup(rows[0].gpio) != &rows[0]) {
        return 9;
    }

    return 0;
}
