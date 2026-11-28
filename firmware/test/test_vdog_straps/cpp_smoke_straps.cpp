/*
 * C++ consumer smoke check for the vdog portable strap/reserved-pin table
 * (package 1.2, mirrors cpp_smoke_board.cpp). extern "C" linkage proof for
 * vdog_straps.{h,c}.
 */
#include "vdog_straps.h"

extern "C" int vdog_straps_cpp_smoke(void)
{
    const char *role = 0;

    if (vdog_straps_check_claim(0u, VDOG_STRAPS_CLAIM_GENERAL, &role) !=
        VDOG_STRAPS_REJECT) {
        return 10;
    }
    if (role == 0) {
        return 11;
    }
    if (vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_SD, &role) !=
        VDOG_STRAPS_PROVISIONAL) {
        return 12;
    }
    if (vdog_straps_check_claim(1u, VDOG_STRAPS_CLAIM_GENERAL, 0) !=
        VDOG_STRAPS_OK) {
        return 13;
    }
    if (vdog_straps_check_claim(41u, VDOG_STRAPS_CLAIM_GENERAL, &role) !=
        VDOG_STRAPS_REJECT) {
        return 14; /* microphone stays dead */
    }
    if (vdog_straps_check_claim(255u, VDOG_STRAPS_CLAIM_GENERAL, 0) !=
        VDOG_STRAPS_REJECT) {
        return 15;
    }
    return 0;
}
