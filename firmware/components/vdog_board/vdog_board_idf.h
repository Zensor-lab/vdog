/*
 * vdog target-side board adapter (package 1.1) — IDF component
 * "vdog_board", see CMakeLists.txt in this directory.
 *
 * Reads THIS build's ESP-IDF configuration macros into the portable
 * vdog_board_profile_t and hands it to the portable validator in
 * core/vdog_board.{h,c}. Deliberately no policy here: every field is either
 * set (and marked) from an explicit CONFIG_* key, or left unset so the
 * portable validator reports VDOG_ERR_BOARD_MISSING_FIELD — an unset key can
 * never be inherited as a default (plan 1.1 §4.3).
 *
 * No GPIO/pin driving anywhere in this package: this adapter reads build
 * configuration only. Pin references (including the unresolved GPIO21
 * SD-CS/user-LED sharing) live as PROVISIONAL comments in
 * core/vdog_board.h; the candidate map in hardware/prototype-a/pin-map.csv
 * is not approved and no pin is configured from it here.
 */
#ifndef VDOG_BOARD_IDF_H
#define VDOG_BOARD_IDF_H

#include "vdog_board.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Build a profile from the compile-time configuration of THIS firmware
 * image. Fields whose Kconfig key (or board-identity definition) is absent
 * stay UNSET in `field_set`; they are not defaulted. Validation and the
 * exact error code / offending field name come from vdog_board_validate() /
 * vdog_board_error_field(). Always returns a profile; a rejected one is
 * reported by the caller. */
vdog_board_profile_t vdog_board_profile_from_sdkconfig(void);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_BOARD_IDF_H */
