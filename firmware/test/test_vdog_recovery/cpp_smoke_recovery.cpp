/*
 * C++ consumer smoke check for the vdog portable recovery/identity core
 * (package 1.2, mirrors cpp_smoke_board.cpp). extern "C" linkage proof for
 * vdog_recovery.{h,c}.
 */
#include "vdog_recovery.h"

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

extern "C" int vdog_recovery_cpp_smoke(void)
{
    vdog_identity_t id;
    char buf[256];

    if (vdog_recovery_classify("boot:0x13(spi_fast)") != VDOG_BOOT_MODE_NORMAL) {
        return 10;
    }
    if (vdog_recovery_classify("boot:0x02(download)") != VDOG_BOOT_MODE_DOWNLOAD) {
        return 11;
    }
    if (vdog_recovery_classify(NULL) != VDOG_BOOT_MODE_UNKNOWN) {
        return 12;
    }

    vdog_identity_init(&id);
    if (vdog_identity_format(&id, buf, sizeof(buf)) != VDOG_OK) {
        return 13;
    }
    if (!same(buf, "chip=unknown rev=0.0")) {
        return 14;
    }

    /* Enum-typed members accept the documented constants from C++. */
    id.mac_tail = 0x00ffu;
    id.mac_valid = 1u;
    if (vdog_identity_format(&id, buf, sizeof(buf)) != VDOG_OK) {
        return 15;
    }
    if (!same(buf, "chip=unknown rev=0.0 mac=**:**:**:**:00:ff")) {
        return 16;
    }
    return 0;
}
