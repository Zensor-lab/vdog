/*
 * vdog portable core module (package 0.2) — see vdog_core.h.
 * Deliberately free of ESP-IDF and OS dependencies so the identical file is
 * built by the host `native` environment and the ESP-IDF target component.
 */
#include "vdog_core.h"

#include <stdio.h>

#define VDOG_VERSION_STRING_PREFIX "vdog "
#define VDOG_VERSION_DIGITS "%u.%u.%u"

int vdog_version_pack(uint32_t major, uint32_t minor, uint32_t patch,
                      uint32_t *packed_out)
{
    if (packed_out == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    /* Validate BEFORE packing on widened parameters: out-of-range values
     * (256, 0x100, 65536, ...) are rejected instead of silently narrowed
     * to the 8-bit fields of the packed form. */
    if (major > VDOG_VERSION_COMPONENT_MAX ||
        minor > VDOG_VERSION_COMPONENT_MAX ||
        patch > VDOG_VERSION_COMPONENT_MAX) {
        return VDOG_ERR_INVALID_ARG;
    }
    *packed_out = (major << 16) | (minor << 8) | patch;
    return VDOG_OK;
}

int vdog_version_compare(uint32_t a, uint32_t b)
{
    if (a < b) {
        return -1;
    }
    if (a > b) {
        return 1;
    }
    return 0;
}

int vdog_format_version(char *buf, size_t bufsize)
{
    int written;

    if (buf == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    if (bufsize == 0u) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }

    written = snprintf(buf, bufsize,
                       VDOG_VERSION_STRING_PREFIX VDOG_VERSION_DIGITS "-"
                       VDOG_VERSION_SUFFIX,
                       (unsigned)VDOG_VERSION_MAJOR,
                       (unsigned)VDOG_VERSION_MINOR,
                       (unsigned)VDOG_VERSION_PATCH);
    if (written < 0) {
        return VDOG_ERR_INVALID_ARG;
    }
    if ((size_t)written >= bufsize) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    return VDOG_OK;
}
