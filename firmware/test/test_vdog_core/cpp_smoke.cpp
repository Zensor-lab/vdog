/*
 * C++ consumer smoke check for the vdog portable core (PR-review F2).
 *
 * This translation unit includes vdog_core.h from C++ and calls the API
 * through the extern "C" interface. It is compiled and LINKED into the
 * native test binary (a C test calls vdog_cpp_smoke(), so the linker must
 * resolve the C-linkage symbol across the C/C++ boundary — not just a
 * header parse), and into the embedded build-only test image.
 * No C++ runtime facilities are used, so no extra runtime library is
 * required on either side.
 */
#include "vdog_core.h"

extern "C" int vdog_cpp_smoke(void);

int vdog_cpp_smoke(void)
{
    uint32_t packed = 0u;
    char buf[64];

    if (vdog_version_pack(1u, 2u, 3u, &packed) != VDOG_OK) {
        return 1;
    }
    if (packed != ((1u << 16) | (2u << 8) | 3u)) {
        return 2;
    }
    /* Widened API: out-of-range must be rejected from C++ as well. */
    if (vdog_version_pack(256u, 0u, 0u, &packed) != VDOG_ERR_INVALID_ARG) {
        return 3;
    }
    if (vdog_version_compare(packed, packed) != 0) {
        return 4;
    }
    if (vdog_format_version(buf, sizeof(buf)) != VDOG_OK) {
        return 5;
    }
    if (buf[0] != 'v' || buf[1] != 'd' || buf[2] != 'o' || buf[3] != 'g') {
        return 6;
    }
    return 0;
}
