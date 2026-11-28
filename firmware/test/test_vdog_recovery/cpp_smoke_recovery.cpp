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

    if (vdog_recovery_classify(
            "rst:0x3 (POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)") !=
        VDOG_BOOT_MODE_NORMAL) {
        return 10;
    }
    if (vdog_recovery_classify("boot:0x2 (DOWNLOAD(USB/UART0))") !=
        VDOG_BOOT_MODE_DOWNLOAD) {
        return 11;
    }
    if (vdog_recovery_classify("reboot: download failed") !=
        VDOG_BOOT_MODE_UNKNOWN) {
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

    /* Validated setters compile and behave from C++ too (round 1). */
    if (vdog_identity_set_chip_model(&id, "esp32s3") != VDOG_OK) {
        return 17;
    }
    if (vdog_identity_set_chip_model(&id, "esp32") != VDOG_ERR_INVALID_ARG) {
        return 18;
    }
    (void)vdog_identity_set_chip_model(&id, "esp32s3");
    vdog_identity_set_revision(&id, 102u); /* 1.2, not 0.102 */
    if (vdog_identity_set_board_tag(&id, "vdog-cpp-1") != VDOG_OK) {
        return 19;
    }
    if (vdog_identity_set_board_tag(&id, "bad tag!") != VDOG_ERR_INVALID_ARG) {
        return 20;
    }
    if (vdog_identity_format(&id, buf, sizeof(buf)) != VDOG_OK) {
        return 21;
    }
    if (!same(buf, "chip=esp32s3 rev=1.2 mac=**:**:**:**:00:ff board=vdog-cpp-1")) {
        return 22;
    }
    return 0;
}
