/*
 * C++ consumer smoke check for the vdog portable recovery/identity core
 * (package 1.2 Part A; mirrors cpp_smoke_board.cpp from package 1.1).
 *
 * This translation unit includes vdog_recovery.h from C++ and calls the
 * API through the extern "C" interface. It is compiled and LINKED into the
 * native test binary (a C test calls vdog_recovery_cpp_smoke(), so the
 * linker must resolve the C-linkage symbol across the C/C++ boundary — not
 * just a header parse), and into the embedded build-only test image. No C++
 * runtime facilities are used.
 */
#include "vdog_recovery.h"

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

extern "C" int vdog_recovery_cpp_smoke(void);

int vdog_recovery_cpp_smoke(void)
{
    char buf[256];

    /* Classification through the C++ boundary: complete ROM banner FORMS
     * classify (review M-C), prose and anything unrecognised stays
     * UNKNOWN. */
    if (vdog_recovery_classify("boot:0x27 (SPI_FAST_FLASH_BOOT)") !=
        VDOG_BOOT_MODE_NORMAL) {
        return 1;
    }
    if (vdog_recovery_classify("boot:0x8 (SPI_FAST_DOWNLOAD)") !=
        VDOG_BOOT_MODE_DOWNLOAD) {
        return 2;
    }
    if (vdog_recovery_classify("boot:0x1 (USB-JTAG/serial)") !=
        VDOG_BOOT_MODE_USBJTAG) {
        return 3;
    }
    if (vdog_recovery_classify(nullptr) != VDOG_BOOT_MODE_UNKNOWN) {
        return 4;
    }
    if (vdog_recovery_classify("download failed") != VDOG_BOOT_MODE_UNKNOWN) {
        return 13; /* prose containing tokens is not a banner */
    }
    if (!same(vdog_boot_mode_name(VDOG_BOOT_MODE_USBJTAG), "usbjtag")) {
        return 5;
    }

    /* Sanitized identity from C++: closed-set model, validated tag,
     * MAC-tail-only storage. */
    vdog_identity_t id;
    vdog_identity_init(&id);
    if (id.mac_valid != 0u || id.mem_valid != 0u ||
        id.chip_model != VDOG_IDENTITY_CHIP_UNKNOWN) {
        return 6;
    }
    if (sizeof(id.mac_tail) != 2u) {
        return 7; /* the sanitizer is structural, from C++ too */
    }
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
    if (id.chip_model != VDOG_IDENTITY_CHIP_ESP32S3) {
        return 14;
    }
    if (vdog_identity_set_board_tag(&id, "abcdef012345") !=
        VDOG_ERR_IDENTITY_TAG) {
        return 15; /* compact MAC rejected through the C++ boundary too */
    }
    if (vdog_identity_set_board_tag(&id, "proto-a1") != VDOG_OK) {
        return 16;
    }
    if (vdog_identity_format(&id, buf, sizeof(buf)) != VDOG_OK) {
        return 8;
    }
    if (!same(buf, "chip=esp32s3 rev=0.0 board=proto-a1")) {
        return 9;
    }

    /* Buffer semantics across the boundary. */
    if (vdog_identity_format(&id, buf, 4u) != VDOG_ERR_BUFFER_TOO_SMALL) {
        return 10;
    }
    if (vdog_identity_format(nullptr, buf, sizeof(buf)) !=
        VDOG_ERR_INVALID_ARG) {
        return 11;
    }
    if (vdog_identity_format(&id, nullptr, sizeof(buf)) !=
        VDOG_ERR_INVALID_ARG) {
        return 12;
    }

    return 0;
}
