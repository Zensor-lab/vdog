/*
 * vdog portable core module (package 0.2).
 *
 * Pure C11, no ESP-IDF headers: compiled for the host `native` test
 * environment (via lib_deps) AND for the target as an IDF component
 * (via the components/vdog_core wrapper). Keep it dependency-free.
 * The API is C++-consumer-safe via the extern "C" guard below.
 */
#ifndef VDOG_CORE_H
#define VDOG_CORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define VDOG_VERSION_MAJOR 0u
#define VDOG_VERSION_MINOR 2u
#define VDOG_VERSION_PATCH 0u
#define VDOG_VERSION_SUFFIX "proto"

/* Largest value accepted for a single version component (uint8_t payload
 * fields inside the 24-bit packed form). */
#define VDOG_VERSION_COMPONENT_MAX 255u

/* vdog_core status codes */
#define VDOG_OK 0
#define VDOG_ERR_INVALID_ARG (-1)
#define VDOG_ERR_BUFFER_TOO_SMALL (-2)

/* Pack a semantic version into (major<<16)|(minor<<8)|patch.
 * Parameters are deliberately widened (uint32_t): callers passing values
 * above 255 (including 256, 0x100, 65536, etc.) are REJECTED with
 * VDOG_ERR_INVALID_ARG before any packing — no silent narrowing to 8 bits.
 * Returns VDOG_OK, or VDOG_ERR_INVALID_ARG if packed_out is NULL or any
 * component exceeds VDOG_VERSION_COMPONENT_MAX. */
int vdog_version_pack(uint32_t major, uint32_t minor, uint32_t patch,
                      uint32_t *packed_out);

/* Three-way comparison of packed versions: -1, 0, 1. */
int vdog_version_compare(uint32_t a, uint32_t b);

/* Format the build version as "vdog MAJOR.MINOR.PATCH-SUFFIX" (e.g.
 * "vdog 0.2.0-proto") into buf of size bufsize (NUL-terminated on success).
 * Returns VDOG_OK; VDOG_ERR_INVALID_ARG for NULL arguments;
 * VDOG_ERR_BUFFER_TOO_SMALL if bufsize cannot hold the string + NUL.
 * The buffer contents are unspecified on error. */
int vdog_format_version(char *buf, size_t bufsize);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_CORE_H */
