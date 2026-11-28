/*
 * vdog target-side memory/recovery adapter (package 1.2, plan A3) — IDF
 * component "vdog_board", see CMakeLists.txt in this directory.
 *
 * Thin, READ-ONLY glue around the portable modules (core/vdog_mem,
 * core/vdog_recovery, core/vdog_straps):
 *   - vdog_mem_detected_from_sdkconfig() fills the CONFIGURED fields from
 *     THIS image's build configuration (#ifdef discipline like the 1.1
 *     profile adapter: an unset key stays "field not set", never a default).
 *   - vdog_mem_read_detected() fills the MEASURED fields from the chip
 *     (flash chip size; PSRAM init success + usable size). A failed query
 *     leaves the field UNSET — the portable check reports
 *     VDOG_ERR_MEM_MISSING_FIELD rather than guessing.
 *   - vdog_identity_read_esp() fills chip model/revision and the sanitized
 *     MAC tail via public helper APIs only (esp_chip_info / esp_read_mac);
 *     it never reads eFuse raw values and never stores a full MAC.
 *
 * Like the 1.1 adapter: no policy here, no GPIO driving, no strap claims —
 * every future claim must pass vdog_straps_check_claim() and today nothing
 * claims anything; the microphone is never initialized (GPIO21 stays
 * unclaimed, see core/vdog_straps.h).
 */
#ifndef VDOG_BOARD_HW_H
#define VDOG_BOARD_HW_H

#include "vdog_mem.h"
#include "vdog_recovery.h"

#ifdef __cplusplus
extern "C" {
#endif

/* CONFIGURED summary from this image's own build configuration. Fields
 * whose Kconfig key is absent stay UNSET (never defaulted). MEASURED
 * fields are left unset here — vdog_mem_read_detected() owns those. */
vdog_mem_detected_t vdog_mem_detected_from_sdkconfig(void);

/* Overlay the MEASURED fields (flash chip size, PSRAM usable size +
 * init success) onto an existing detector. Read-only queries; a query that
 * fails leaves its field UNSET. Returns VDOG_OK if all MEASURED queries
 * succeeded, VDOG_ERR_INVALID_ARG if det is NULL, otherwise the code of
 * the first failed query (naming via vdog_mem_error_field()-style
 * last-error is NOT implied here; the caller renders from the struct). */
int vdog_mem_read_detected(vdog_mem_detected_t *det);

/* Chip model/revision + sanitized MAC tail (last two bytes only). The
 * mem/mem_valid fields are left untouched for the caller, which decides
 * whether a baseline-checked summary may be rendered. */
void vdog_identity_read_esp(vdog_identity_t *id);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_BOARD_HW_H */
