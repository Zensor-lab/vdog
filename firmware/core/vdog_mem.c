/*
 * vdog portable memory-baseline core module — implementation (package 1.2,
 * plan A1). Pure C11: stdio (snprintf) only, no SDK/OS calls. See
 * vdog_mem.h for the MEASURED-vs-CONFIGURED evidence contract; the fixed
 * decision order below (missing -> source -> value, each in declaration
 * order) mirrors vdog_board_validate()'s deterministic last-error model.
 */
#include <stdio.h>
#include <string.h>

#include "vdog_mem.h"

static const char *g_vdog_mem_last_field;

#define VDOG_MEM_SOURCE_COUNT 2u /* MEASURED(0) / CONFIGURED(1) */

typedef struct {
    const char *name;      /* field name reported by error_field() */
    uint32_t bit;          /* VDOG_MEM_FIELD_*                     */
    uint8_t required_src;  /* the ONLY source tag this field may carry */
} vdog_mem_field_desc_t;

/* Declaration order IS decision order (deterministic diagnosis). Fields
 * that prove DETECTED memory must be MEASURED; mode/frequency fields are
 * build configuration and must never claim to be measured (finding 2). */
static const vdog_mem_field_desc_t g_vdog_mem_fields[] = {
    {"flash_size_bytes", VDOG_MEM_FIELD_FLASH_SIZE, VDOG_MEM_SOURCE_MEASURED},
    {"flash_mode", VDOG_MEM_FIELD_FLASH_MODE, VDOG_MEM_SOURCE_CONFIGURED},
    {"flash_freq_mhz", VDOG_MEM_FIELD_FLASH_FREQ, VDOG_MEM_SOURCE_CONFIGURED},
    {"psram_present", VDOG_MEM_FIELD_PSRAM_PRESENT, VDOG_MEM_SOURCE_MEASURED},
    {"psram_size_bytes", VDOG_MEM_FIELD_PSRAM_SIZE, VDOG_MEM_SOURCE_MEASURED},
    {"psram_mode", VDOG_MEM_FIELD_PSRAM_MODE, VDOG_MEM_SOURCE_CONFIGURED},
    {"psram_speed_mhz", VDOG_MEM_FIELD_PSRAM_SPEED, VDOG_MEM_SOURCE_CONFIGURED},
};

#define VDOG_MEM_FIELD_COUNT                                                     \
    (sizeof(g_vdog_mem_fields) / sizeof(g_vdog_mem_fields[0]))

static void remember_field(const char *field) { g_vdog_mem_last_field = field; }

static const char *source_tag(vdog_mem_source_t src)
{
    return (src == VDOG_MEM_SOURCE_MEASURED) ? "measured" : "configured";
}

static const char *flash_mode_name(vdog_board_flash_mode_t mode)
{
    switch (mode) {
    case VDOG_BOARD_FLASH_MODE_QIO:
        return "qio";
    case VDOG_BOARD_FLASH_MODE_DIO:
        return "dio";
    case VDOG_BOARD_FLASH_MODE_DOUT:
        return "dout";
    case VDOG_BOARD_FLASH_MODE_QOUT:
        return "qout";
    default:
        return "unknown";
    }
}

static const char *psram_mode_name(vdog_board_psram_mode_t mode)
{
    switch (mode) {
    case VDOG_BOARD_PSRAM_MODE_OPI:
        return "opi";
    case VDOG_BOARD_PSRAM_MODE_QSPI:
        return "qspi";
    default:
        return "unknown";
    }
}

void vdog_mem_detected_init(vdog_mem_detected_t *det)
{
    if (det == NULL) {
        return;
    }
    memset(det, 0, sizeof(*det));
    /* memset already gives value=0 + field_set=0: "never probed". Sources
     * are meaningless until the matching field is set by a caller. */
}

int vdog_mem_record_flash_size(vdog_mem_detected_t *det,
                               uint32_t header_size_bytes,
                               uint32_t physical_size_bytes)
{
    if (det == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    /* Round-3 review Medium: a REFRESH must never preserve earlier
     * evidence. Clear the flash fields FIRST — every exit path below
     * leaves either the new values or an honest UNSET, never a stale
     * MEASURED field from a previous successful read. */
    det->flash_size_bytes = 0u;
    det->flash_size_src = 0u; /* meaningless while UNSET (same as init)   */
    det->field_set &= ~VDOG_MEM_FIELD_FLASH_SIZE;
    det->flash_cross_fail = 0u;
    if (header_size_bytes == 0u || physical_size_bytes == 0u) {
        /* A failed query leaves the field UNSET (never guessed): the
         * baseline check then reports VDOG_ERR_MEM_MISSING_FIELD. */
        return VDOG_ERR_INVALID_ARG;
    }
    /* The PHYSICAL capacity is the MEASURED truth; the header value only
     * cross-checks it (PR-review round 1 High finding). */
    det->flash_size_bytes = physical_size_bytes;
    det->flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    det->field_set |= VDOG_MEM_FIELD_FLASH_SIZE;
    if (header_size_bytes != physical_size_bytes) {
        det->flash_cross_fail = 1u; /* sticky: keeps check_baseline rejecting
                                     * this set (round-2 review)          */
        remember_field("flash_size_bytes");
        return VDOG_ERR_MEM_FLASH;
    }
    det->flash_cross_fail = 0u; /* agreeing record clears an earlier fail */
    return VDOG_OK;
}

/* One pass over the field table; returns the offending descriptor or NULL.
 * phase 0: any field whose bit is absent; phase 1: any field whose tag is
 * not the required one (including an out-of-range tag); caller stops at the
 * first hit, so missing outranks source outranks value. */
static const vdog_mem_field_desc_t *first_offender(
    const vdog_mem_detected_t *det, int phase)
{
    size_t i;
    for (i = 0; i < VDOG_MEM_FIELD_COUNT; ++i) {
        const vdog_mem_field_desc_t *f = &g_vdog_mem_fields[i];
        vdog_mem_source_t src;
        if ((det->field_set & f->bit) == 0u) {
            if (phase == 0) {
                return f;
            }
            continue; /* absent fields were already reported in phase 0 */
        }
        if (phase != 1) {
            continue;
        }
        switch (f->bit) {
        case VDOG_MEM_FIELD_FLASH_SIZE: src = det->flash_size_src; break;
        case VDOG_MEM_FIELD_FLASH_MODE: src = det->flash_mode_src; break;
        case VDOG_MEM_FIELD_FLASH_FREQ: src = det->flash_freq_src; break;
        case VDOG_MEM_FIELD_PSRAM_PRESENT: src = det->psram_present_src; break;
        case VDOG_MEM_FIELD_PSRAM_SIZE: src = det->psram_size_src; break;
        case VDOG_MEM_FIELD_PSRAM_MODE: src = det->psram_mode_src; break;
        default: src = det->psram_speed_src; break;
        }
        if ((unsigned)src >= VDOG_MEM_SOURCE_COUNT || src != f->required_src) {
            return f;
        }
    }
    return NULL;
}

/* Value comparisons against the documented baseline, declaration order.
 * Each named wrong-board class lands in exactly one bucket: 4 MiB flash ->
 * flash_size_bytes; no PSRAM -> psram_present; wrong usable size ->
 * psram_size_bytes; quad-only PSRAM / Plus-N16R8-shaped reports ->
 * psram_mode/psram_size_bytes; non-QIO/80m -> flash_mode/flash_freq_mhz. */
static const vdog_mem_field_desc_t *first_mismatch(
    const vdog_mem_detected_t *det)
{
    /* Sticky cross-check failure outranks the bare value comparison: a set
     * whose header/physical capacities disagreed stays REJECTED (flash
     * class, field flash_size_bytes) even when the recorded physical value
     * happens to equal the baseline (round-2 review). */
    if (det->flash_cross_fail != 0u) {
        return &g_vdog_mem_fields[0];
    }
    if (det->flash_size_bytes != VDOG_MEM_BASELINE_FLASH_SIZE_BYTES) {
        return &g_vdog_mem_fields[0];
    }
    if (det->flash_mode != VDOG_MEM_BASELINE_FLASH_MODE) {
        return &g_vdog_mem_fields[1];
    }
    if (det->flash_freq_mhz != VDOG_MEM_BASELINE_FLASH_FREQ_MHZ) {
        return &g_vdog_mem_fields[2];
    }
    if (det->psram_present != VDOG_MEM_BASELINE_PSRAM_PRESENT) {
        return &g_vdog_mem_fields[3];
    }
    if (det->psram_size_bytes != VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES) {
        return &g_vdog_mem_fields[4];
    }
    if (det->psram_mode != VDOG_MEM_BASELINE_PSRAM_MODE) {
        return &g_vdog_mem_fields[5];
    }
    if (det->psram_speed_mhz != VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ) {
        return &g_vdog_mem_fields[6];
    }
    return NULL;
}

int vdog_mem_check_baseline(const vdog_mem_detected_t *det)
{
    const vdog_mem_field_desc_t *offender;

    g_vdog_mem_last_field = NULL;
    if (det == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }
    offender = first_offender(det, 0); /* missing (never probed) first */
    if (offender != NULL) {
        remember_field(offender->name);
        return VDOG_ERR_MEM_MISSING_FIELD;
    }
    offender = first_offender(det, 1); /* evidence-source violations next */
    if (offender != NULL) {
        remember_field(offender->name);
        return VDOG_ERR_MEM_SOURCE;
    }
    offender = first_mismatch(det); /* values against the baseline last */
    if (offender != NULL) {
        remember_field(offender->name);
        return (offender->bit & (VDOG_MEM_FIELD_PSRAM_PRESENT |
                                 VDOG_MEM_FIELD_PSRAM_SIZE |
                                 VDOG_MEM_FIELD_PSRAM_MODE |
                                 VDOG_MEM_FIELD_PSRAM_SPEED)) != 0u
                   ? VDOG_ERR_MEM_PSRAM
                   : VDOG_ERR_MEM_FLASH;
    }
    return VDOG_OK;
}

const char *vdog_mem_error_field(void) { return g_vdog_mem_last_field; }

/* The success line is derived ONLY from values the baseline check just
 * equalled, each with its evidence tag rendered per field (finding 2): a
 * mode/frequency can only ever print [configured], so no log line can
 * present "opi" as detected. */
int vdog_mem_format_detected(const vdog_mem_detected_t *det, char *buf,
                             size_t cap)
{
    int rc;
    int written;

    if (buf == NULL || cap == 0u) {
        return VDOG_ERR_INVALID_ARG;
    }
    rc = vdog_mem_check_baseline(det); /* never renders a rejected set */
    if (rc != VDOG_OK) {
        return rc;
    }
    /* det is known non-NULL and fully baseline-equal here. */
    written = snprintf(
        buf, cap,
        "flash_size=%luMB[%s] flash_mode=%s[%s] flash_freq=%um[%s] "
        "psram=%luMB[%s:init-ok] psram_mode=%s[%s] psram_speed=%um[%s]",
        (unsigned long)(det->flash_size_bytes / (1024u * 1024u)),
        source_tag(det->flash_size_src),
        flash_mode_name(det->flash_mode), source_tag(det->flash_mode_src),
        (unsigned)det->flash_freq_mhz, source_tag(det->flash_freq_src),
        (unsigned long)(det->psram_size_bytes / (1024u * 1024u)),
        source_tag(det->psram_size_src),
        psram_mode_name(det->psram_mode), source_tag(det->psram_mode_src),
        (unsigned)det->psram_speed_mhz, source_tag(det->psram_speed_src));
    if (written < 0 || (size_t)written >= cap) {
        return VDOG_ERR_BUFFER_TOO_SMALL;
    }
    return VDOG_OK;
}
