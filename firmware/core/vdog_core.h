/*
 * vdog portable core module (package 0.2).
 *
 * Pure C11, no ESP-IDF headers: compiled for the host `native` test
 * environment (via lib_deps) AND for the target as an IDF component
 * (via EXTRA_COMPONENT_DIRS). Keep it dependency-free.
 */
#ifndef VDOG_CORE_H
#define VDOG_CORE_H

#include <stddef.h>
#include <stdint.h>

#define VDOG_VERSION_MAJOR 0u
#define VDOG_VERSION_MINOR 2u
#define VDOG_VERSION_PATCH 0u
#define VDOG_VERSION_SUFFIX "proto"

/* vdog_core status codes */
#define VDOG_OK 0
#define VDOG_ERR_INVALID_ARG (-1)
#define VDOG_ERR_BUFFER_TOO_SMALL (-2)

/* Pack a semantic version into (major<<16)|(minor<<8)|patch.
 * Returns VDOG_OK, or VDOG_ERR_INVALID_ARG if any component exceeds 255. */
int vdog_version_pack(uint8_t major, uint8_t minor, uint8_t patch,
                      uint32_t *packed_out);

/* Three-way comparison of packed versions: -1, 0, 1. */
int vdog_version_compare(uint32_t a, uint32_t b);

/* Format the build version as "vdog MAJOR.MINOR.PATCH-SUFFIX" (e.g.
 * "vdog 0.2.0-proto") into buf of size bufsize (NUL-terminated on success).
 * Returns VDOG_OK; VDOG_ERR_INVALID_ARG for NULL arguments;
 * VDOG_ERR_BUFFER_TOO_SMALL if bufsize cannot hold the string + NUL.
 * The buffer contents are unspecified on error. */
int vdog_format_version(char *buf, size_t bufsize);

#endif /* VDOG_CORE_H */
