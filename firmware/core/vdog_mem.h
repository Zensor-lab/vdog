/*
 * vdog portable memory-baseline core module (package 1.2, plan A1).
 *
 * Pure C11, no SDK/OS headers: compiled for the host `native` test
 * environment (via lib_deps on core/) AND for the target as part of the
 * "vdog_board" IDF component (components/vdog_board wrapper), exactly like
 * vdog_board.{h,c} / vdog_core.{h,c}. Keep it dependency-free: this file is
 * the single source of truth for what "the memory this firmware was built
 * for, as actually detected" means; the target-side reads live in
 * components/vdog_board/vdog_board_hw.c and nothing here touches an SDK.
 *
 * Evidence honesty (plan 1.2 lead finding 2 — the whole point of this
 * module): EVERY field carries a source tag.
 *   MEASURED   — obtained from the chip at runtime (flash chip size, PSRAM
 *                init success + usable size). Only these support a
 *                "detected" claim.
 *   CONFIGURED — obtained from the image's own build configuration (flash
 *                mode/frequency, PSRAM octal-mode/speed). These prove only
 *                that the image was BUILT that way; the octal-mode match is
 *                shown indirectly, by PSRAM initializing at all. A
 *                CONFIGURED value can never satisfy a detected claim, and
 *                vdog_mem_format_detected() renders the tag per field so a
 *                log line can never present "opi" as if it were measured.
 *
 * Explicit-field contract (same discipline as vdog_board_profile_t): every
 * member is paired with a VDOG_MEM_FIELD_* bit in `field_set`; a value that
 * was never probed stays UNSET and is reported as VDOG_ERR_MEM_MISSING_FIELD,
 * never compared as a silently inherited default.
 */
#ifndef VDOG_MEM_H
#define VDOG_MEM_H

#include <stddef.h>
#include <stdint.h>

#include "vdog_board.h" /* shared value vocabulary: flash/psram modes */

#ifdef __cplusplus
extern "C" {
#endif

/* Status codes shared with vdog_core.h / vdog_board.h (guarded repeats). */
#ifndef VDOG_OK
#define VDOG_OK 0
#endif
#ifndef VDOG_ERR_INVALID_ARG
#define VDOG_ERR_INVALID_ARG (-1)
#endif
#ifndef VDOG_ERR_BUFFER_TOO_SMALL
#define VDOG_ERR_BUFFER_TOO_SMALL (-2)
#endif

/* Memory-baseline specific failures (distinct code band from the board
 * gate's -10..-14). */
#define VDOG_ERR_MEM_MISSING_FIELD (-20) /* a field was never probed/stated  */
#define VDOG_ERR_MEM_FLASH (-21)         /* detected flash contradicts baseline */
#define VDOG_ERR_MEM_PSRAM (-22)         /* detected PSRAM contradicts baseline */
#define VDOG_ERR_MEM_SOURCE (-23)        /* a "detected" claim backed by a
                                          * CONFIGURED tag (finding 2)        */

/* ---- field_set bits: one per profile field ----------------------------- */
#define VDOG_MEM_FIELD_FLASH_SIZE (1u << 0)
#define VDOG_MEM_FIELD_FLASH_MODE (1u << 1)
#define VDOG_MEM_FIELD_FLASH_FREQ (1u << 2)
#define VDOG_MEM_FIELD_PSRAM_PRESENT (1u << 3)
#define VDOG_MEM_FIELD_PSRAM_SIZE (1u << 4)
#define VDOG_MEM_FIELD_PSRAM_MODE (1u << 5)
#define VDOG_MEM_FIELD_PSRAM_SPEED (1u << 6)

/* Every field the baseline check requires before memory may be reported. */
#define VDOG_MEM_FIELD_ALL                                                       \
    (VDOG_MEM_FIELD_FLASH_SIZE | VDOG_MEM_FIELD_FLASH_MODE |                     \
     VDOG_MEM_FIELD_FLASH_FREQ | VDOG_MEM_FIELD_PSRAM_PRESENT |                  \
     VDOG_MEM_FIELD_PSRAM_SIZE | VDOG_MEM_FIELD_PSRAM_MODE |                     \
     VDOG_MEM_FIELD_PSRAM_SPEED)

/* ---- per-field evidence source tags (plan 1.2 lead finding 2) ---------- */
#define VDOG_MEM_SOURCE_MEASURED 0u  /* read from the chip at runtime       */
#define VDOG_MEM_SOURCE_CONFIGURED 1u /* the image's own build configuration */

typedef uint8_t vdog_mem_source_t;

typedef struct {
    uint32_t flash_size_bytes;     /* chip capacity (MEASURED in Part B)    */
    vdog_board_flash_mode_t flash_mode; /* build-configured QIO/DIO/...     */
    uint16_t flash_freq_mhz;       /* build-configured frequency, whole MHz */
    uint8_t psram_present;         /* 1 = PSRAM initialized (MEASURED)      */
    uint32_t psram_size_bytes;     /* usable PSRAM (MEASURED; 0 valid = no) */
    vdog_board_psram_mode_t psram_mode;  /* build-configured OPI/QSPI       */
    uint16_t psram_speed_mhz;      /* build-configured frequency, whole MHz */
    uint32_t field_set;            /* VDOG_MEM_FIELD_* bitmask              */
    vdog_mem_source_t flash_size_src;
    vdog_mem_source_t flash_mode_src;
    vdog_mem_source_t flash_freq_src;
    vdog_mem_source_t psram_present_src;
    vdog_mem_source_t psram_size_src;
    vdog_mem_source_t psram_mode_src;
    vdog_mem_source_t psram_speed_src;
} vdog_mem_detected_t;

/* ---- documented XIAO ESP32S3 Sense baseline (NOT Plus/N16R8/classic) ---
 * Same numbers as the 1.1 expected-provisional profile; these twin
 * constants document the Stage-1 acceptance baseline "8MB flash / 8MB
 * octal PSRAM". Physical values stay DEVICE evidence (plan 1.2 Part B). */
#define VDOG_MEM_BASELINE_FLASH_SIZE_BYTES (8u * 1024u * 1024u)
#define VDOG_MEM_BASELINE_FLASH_MODE VDOG_BOARD_FLASH_MODE_QIO
#define VDOG_MEM_BASELINE_FLASH_FREQ_MHZ 80u
#define VDOG_MEM_BASELINE_PSRAM_PRESENT 1u
#define VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES (8u * 1024u * 1024u)
#define VDOG_MEM_BASELINE_PSRAM_MODE VDOG_BOARD_PSRAM_MODE_OPI
#define VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ 80u

/* Zero the detector and clear field_set/sources: "never probed" is
 * distinguishable from "probed as zero". Callers then set each field WITH
 * its source tag. */
void vdog_mem_detected_init(vdog_mem_detected_t *det);

/* Compare a detector against the documented baseline.
 * Fixed decision order (so the diagnosis is deterministic): argument check
 * -> ALL missing fields (declaration order) -> ALL source violations
 * (declaration order) -> ALL value comparisons (declaration order).
 * A field required MEASURED but tagged CONFIGURED returns
 * VDOG_ERR_MEM_SOURCE naming the field: the baseline gate proves DETECTED
 * memory, so config-only proof never passes it (finding 2). The named
 * wrong-board classes (4 MiB flash, no PSRAM / wrong size, quad-only
 * PSRAM, Plus/N16R8-shaped) return VDOG_ERR_MEM_FLASH / VDOG_ERR_MEM_PSRAM
 * with vdog_mem_error_field() naming the offending field.
 * Returns VDOG_OK (vdog_mem_error_field() cleared) or the code above. */
int vdog_mem_check_baseline(const vdog_mem_detected_t *det);

/* Field name behind the last failed vdog_mem_check_baseline() call
 * (single-threaded boot/diagnostic use, same documented last-error
 * semantics as vdog_board_error_field()). NULL after success or before any
 * call. */
const char *vdog_mem_error_field(void);

/* Render one baseline line WITH per-field source tags, e.g.
 *   "flash_size=8MB[measured] flash_mode=qio[configured] flash_freq=80m[configured] psram=8MB[measured:init-ok] psram_mode=opi[configured] psram_speed=80m[configured]"
 * or "psram=none[measured:init-fail]" when PSRAM did not initialize.
 * A CONFIGURED tag always renders as [configured]: mode/speed have no
 * measured spelling here, so the string can never print a mode as
 * "detected" (host-pinned, plan 1.2 acceptance 3).
 * Like vdog_board_report(), this NEVER renders a set the baseline check
 * would reject: it runs vdog_mem_check_baseline() internally and returns
 * that check's code (missing/source/flash/psram) with vdog_mem_error_field()
 * naming the field, without touching the buffer. Buffer/NUL semantics match
 * vdog_format_version()/vdog_board_report(): VDOG_ERR_INVALID_ARG on NULL,
 * VDOG_ERR_BUFFER_TOO_SMALL when the exact NUL-terminated line (including
 * the final NUL) does not fit; buffer contents unspecified on error. */
int vdog_mem_format_detected(const vdog_mem_detected_t *det, char *buf,
                             size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_MEM_H */
