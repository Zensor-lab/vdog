/*
 * vdog portable board-profile core module (package 1.1) — see vdog_board.h.
 * Deliberately free of any SDK/OS dependency so the identical file is built
 * by the host `native` environment and the ESP-IDF target component.
 *
 * This file is the single source of truth for the identity-gate SEMANTICS
 * (what counts as supported, what counts as never-configured, which field is
 * to blame). The build-time gate script only reads the build configuration
 * and compares it; it never re-decides these rules.
 */
#include "vdog_board.h"

#include <stdio.h>
#include <string.h>

#include "vdog_core.h"

/* Field behind the most recent failed call (NULL after success). Static by
 * design: the gate is used single-threaded at boot/diagnose time and from
 * host tests, exactly like the buffer semantics documented in the header. */
static const char *g_vdog_board_last_field;

static const char *const g_vdog_board_target_names[] = {
    NULL,          /* VDOG_BOARD_TARGET_UNKNOWN  */
    "esp32s3",     /* VDOG_BOARD_TARGET_ESP32S3  */
};
#define VDOG_BOARD_TARGET_NAME_COUNT                                             \
    (sizeof(g_vdog_board_target_names) / sizeof(g_vdog_board_target_names[0]))

static const char *const g_vdog_board_flash_mode_names[] = {
    NULL,   /* UNKNOWN */
    "qio",  /* QIO     */
    "dio",  /* DIO     */
    "dout", /* DOUT    */
    "qout", /* QOUT    */
};

static const char *const g_vdog_board_psram_mode_names[] = {
    NULL,  /* UNKNOWN */
    "opi", /* OPI (octal)   */
    "qspi" /* QSPI (quad)   */
};

static void remember_field(const char *field)
{
    g_vdog_board_last_field = field;
}

/* Field name table in validation order (missing-field pass walks it first). */
typedef struct {
    uint32_t bit;
    const char *name;
} vdog_board_field_desc_t;

static const vdog_board_field_desc_t g_vdog_board_fields[] = {
    {VDOG_BOARD_FIELD_TARGET, "target"},
    {VDOG_BOARD_FIELD_BOARD_ID, "board_id"},
    {VDOG_BOARD_FIELD_FLASH_SIZE, "flash_size_bytes"},
    {VDOG_BOARD_FIELD_FLASH_MODE, "flash_mode"},
    {VDOG_BOARD_FIELD_FLASH_FREQ, "flash_freq_mhz"},
    {VDOG_BOARD_FIELD_PSRAM_PRESENT, "psram_present"},
    {VDOG_BOARD_FIELD_PSRAM_SIZE, "psram_size_bytes"},
    {VDOG_BOARD_FIELD_PSRAM_MODE, "psram_mode"},
    {VDOG_BOARD_FIELD_PSRAM_SPEED, "psram_speed_mhz"},
    {VDOG_BOARD_FIELD_PARTITION_TABLE, "partition_table"},
};
#define VDOG_BOARD_FIELD_COUNT                                                   \
    (sizeof(g_vdog_board_fields) / sizeof(g_vdog_board_fields[0]))

void vdog_board_profile_init(vdog_board_profile_t *profile)
{
    if (profile == NULL) {
        return;
    }
    memset(profile, 0, sizeof(*profile));
}

vdog_board_profile_t vdog_board_expected_profile_proto(void)
{
    vdog_board_profile_t profile;

    vdog_board_profile_init(&profile);
    profile.target = VDOG_BOARD_EXPECTED_TARGET;
    profile.board_id = VDOG_BOARD_EXPECTED_BOARD_ID;
    profile.flash_size_bytes = VDOG_BOARD_EXPECTED_FLASH_SIZE_BYTES;
    profile.flash_mode = VDOG_BOARD_EXPECTED_FLASH_MODE;
    profile.flash_freq_mhz = VDOG_BOARD_EXPECTED_FLASH_FREQ_MHZ;
    profile.psram_present = VDOG_BOARD_EXPECTED_PSRAM_PRESENT;
    profile.psram_size_bytes = VDOG_BOARD_EXPECTED_PSRAM_SIZE_BYTES;
    profile.psram_mode = VDOG_BOARD_EXPECTED_PSRAM_MODE;
    profile.psram_speed_mhz = VDOG_BOARD_EXPECTED_PSRAM_SPEED_MHZ;
    profile.partition_table = VDOG_BOARD_EXPECTED_PARTITION_TABLE;
    profile.field_set = VDOG_BOARD_FIELD_ALL;
    return profile;
}

/* Strings are caller-supplied, so NULL is possible even when the field bit
 * is set: that is a wrong value (empty/NULL content), not "never set". */
static int strings_equal(const char *a, const char *b)
{
    if (a == NULL || b == NULL) {
        return a == b;
    }
    return strcmp(a, b) == 0;
}

static const char *flash_mode_name(vdog_board_flash_mode_t mode)
{
    if ((size_t)mode >= sizeof(g_vdog_board_flash_mode_names) /
                           sizeof(g_vdog_board_flash_mode_names[0])) {
        return NULL;
    }
    return g_vdog_board_flash_mode_names[mode];
}

static const char *psram_mode_name(vdog_board_psram_mode_t mode)
{
    if ((size_t)mode >= sizeof(g_vdog_board_psram_mode_names) /
                           sizeof(g_vdog_board_psram_mode_names[0])) {
        return NULL;
    }
    return g_vdog_board_psram_mode_names[mode];
}

static const char *target_name(vdog_board_target_t target)
{
    if ((size_t)target >= VDOG_BOARD_TARGET_NAME_COUNT) {
        return NULL;
    }
    return g_vdog_board_target_names[target];
}

/* "8MB" for whole-MiB sizes, otherwise raw bytes ("1048576B"): the report
 * never rounds a size, so a non-MiB value can never masquerade as 8MB. */
static void format_size(char *out, size_t outsize, uint32_t bytes)
{
    if (bytes == 0u) {
        snprintf(out, outsize, "0B");
    } else if ((bytes % (1024u * 1024u)) == 0u) {
        snprintf(out, outsize, "%luMB", (unsigned long)(bytes / (1024u * 1024u)));
    } else {
        snprintf(out, outsize, "%luB", (unsigned long)bytes);
    }
}

int vdog_board_validate(const vdog_board_profile_t *profile)
{
    size_t i;

    if (profile == NULL) {
        remember_field("profile");
        return VDOG_ERR_INVALID_ARG;
    }

    /* Pass 1 — never-configured keys. A missing key is NEVER treated as a
     * default: it fails here, before any value comparison (plan 1.1 §7.3). */
    for (i = 0; i < VDOG_BOARD_FIELD_COUNT; ++i) {
        if ((profile->field_set & g_vdog_board_fields[i].bit) == 0u) {
            remember_field(g_vdog_board_fields[i].name);
            return VDOG_ERR_BOARD_MISSING_FIELD;
        }
    }
    if ((profile->field_set & ~VDOG_BOARD_FIELD_ALL) != 0u) {
        /* Unknown bit = caller bug; surface it as a missing/unknown field. */
        remember_field("field_set");
        return VDOG_ERR_BOARD_MISSING_FIELD;
    }

    /* Pass 2 — values, in declaration order, against the expected-
     * provisional profile. First mismatch wins (deterministic diagnosis). */
    if (profile->target != VDOG_BOARD_EXPECTED_TARGET ||
        target_name(profile->target) == NULL) {
        remember_field("target");
        return VDOG_ERR_BOARD_UNSUPPORTED_TARGET;
    }
    if (!strings_equal(profile->board_id, VDOG_BOARD_EXPECTED_BOARD_ID)) {
        remember_field("board_id");
        return VDOG_ERR_BOARD_UNSUPPORTED_TARGET;
    }
    if (profile->flash_size_bytes != VDOG_BOARD_EXPECTED_FLASH_SIZE_BYTES) {
        remember_field("flash_size_bytes");
        return VDOG_ERR_BOARD_FLASH;
    }
    if (profile->flash_mode != VDOG_BOARD_EXPECTED_FLASH_MODE ||
        flash_mode_name(profile->flash_mode) == NULL) {
        remember_field("flash_mode");
        return VDOG_ERR_BOARD_FLASH;
    }
    if (profile->flash_freq_mhz != VDOG_BOARD_EXPECTED_FLASH_FREQ_MHZ) {
        remember_field("flash_freq_mhz");
        return VDOG_ERR_BOARD_FLASH;
    }
    if (profile->psram_present != VDOG_BOARD_EXPECTED_PSRAM_PRESENT) {
        remember_field("psram_present");
        return VDOG_ERR_BOARD_PSRAM;
    }
    if (profile->psram_size_bytes != VDOG_BOARD_EXPECTED_PSRAM_SIZE_BYTES) {
        remember_field("psram_size_bytes");
        return VDOG_ERR_BOARD_PSRAM;
    }
    if (profile->psram_mode != VDOG_BOARD_EXPECTED_PSRAM_MODE ||
        psram_mode_name(profile->psram_mode) == NULL) {
        remember_field("psram_mode");
        return VDOG_ERR_BOARD_PSRAM;
    }
    if (profile->psram_speed_mhz != VDOG_BOARD_EXPECTED_PSRAM_SPEED_MHZ) {
        remember_field("psram_speed_mhz");
        return VDOG_ERR_BOARD_PSRAM;
    }
    if (!strings_equal(profile->partition_table,
                       VDOG_BOARD_EXPECTED_PARTITION_TABLE)) {
        remember_field("partition_table");
        return VDOG_ERR_BOARD_PARTITIONS;
    }

    remember_field(NULL);
    return VDOG_OK;
}

const char *vdog_board_error_field(void)
{
    return g_vdog_board_last_field;
}

int vdog_board_report(const vdog_board_profile_t *profile, char *buf,
                      size_t bufsize)
{
    int written;
    char flash_size[16];
    char psram_size[16];
    const char *target;
    const char *flash_mode;
    const char *psram_mode;

    if (profile == NULL) {
        remember_field("profile");
        return VDOG_ERR_INVALID_ARG;
    }
    if (buf == NULL) {
        remember_field("buf");
        return VDOG_ERR_INVALID_ARG;
    }
    if (bufsize == 0u) {
        remember_field("buf");
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }

    /* A profile the gate rejects is never printable as a healthy line. */
    {
        const int rc = vdog_board_validate(profile);
        if (rc != VDOG_OK) {
            return rc;
        }
    }

    /* All names are non-NULL here: validate() accepted the values. */
    target = target_name(profile->target);
    flash_mode = flash_mode_name(profile->flash_mode);
    psram_mode = psram_mode_name(profile->psram_mode);
    format_size(flash_size, sizeof(flash_size), profile->flash_size_bytes);
    format_size(psram_size, sizeof(psram_size), profile->psram_size_bytes);

    written = snprintf(buf, bufsize,
                       "vdog %u.%u.%u-%s board=%s target=%s "
                       "flash=%s-%s-%um psram=%s-%s-%um",
                       (unsigned)VDOG_VERSION_MAJOR,
                       (unsigned)VDOG_VERSION_MINOR,
                       (unsigned)VDOG_VERSION_PATCH,
                       VDOG_VERSION_SUFFIX,
                       profile->board_id,
                       target,
                       flash_size,
                       flash_mode,
                       (unsigned)profile->flash_freq_mhz,
                       psram_size,
                       psram_mode,
                       (unsigned)profile->psram_speed_mhz);
    if (written < 0) {
        remember_field("buf");
        return VDOG_ERR_INVALID_ARG;
    }
    if ((size_t)written >= bufsize) {
        remember_field("buf");
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    remember_field(NULL);
    return VDOG_OK;
}
