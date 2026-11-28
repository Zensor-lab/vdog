/*
 * vdog portable strap/reserved-pin table — implementation (package 1.2,
 * plan A2b). Const data + pure lookups only: nothing here configures,
 * drives, enables or claims a pin. See vdog_straps.h for the contract.
 */
#include <stddef.h>

#include "vdog_straps.h"

#define ROW_BOOT(gpio, role_str) {(uint8_t)(gpio), (role_str), 1u, 0u, 0u}
#define ROW_CAND(gpio, role_str) {(uint8_t)(gpio), (role_str), 0u, 1u, 0u}
#define ROW_MIC(gpio, role_str) {(uint8_t)(gpio), (role_str), 0u, 0u, 1u}

const vdog_straps_row_t vdog_straps_table[] = {
    /* Strap / reserved first: these are the rejects that must never be
     * bypassed by a candidate match (the table is scanned in order). */
    ROW_BOOT(0, VDOG_STRAPS_ROLE_BOOT),
    ROW_BOOT(3, VDOG_STRAPS_ROLE_JTAG),
    ROW_BOOT(45, VDOG_STRAPS_ROLE_VDD_SPI),
    ROW_BOOT(46, VDOG_STRAPS_ROLE_BOOT_MODE),
    ROW_BOOT(19, VDOG_STRAPS_ROLE_USB),
    ROW_BOOT(20, VDOG_STRAPS_ROLE_USB_DN),
    /* Camera candidates (mirrors hardware/prototype-a/pin-map.csv rows;
     * candidate = provisional, never approval). */
    ROW_CAND(15, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(17, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(18, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(16, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(14, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(12, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(11, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(48, VDOG_STRAPS_ROLE_CAM_DATA),
    ROW_CAND(10, VDOG_STRAPS_ROLE_CAM_XCLK),
    ROW_CAND(13, VDOG_STRAPS_ROLE_CAM_SYNC),
    ROW_CAND(38, VDOG_STRAPS_ROLE_CAM_SYNC),
    ROW_CAND(47, VDOG_STRAPS_ROLE_CAM_SYNC),
    ROW_CAND(40, VDOG_STRAPS_ROLE_CAM_SCCB),
    ROW_CAND(39, VDOG_STRAPS_ROLE_CAM_SCCB),
    /* SD SPI candidates. */
    ROW_CAND(7, VDOG_STRAPS_ROLE_SD_SPI),
    ROW_CAND(8, VDOG_STRAPS_ROLE_SD_SPI),
    ROW_CAND(9, VDOG_STRAPS_ROLE_SD_SPI),
    /* GPIO21: SD CS21 vs user-LED. Intentionally UNCLAIMED — one candidate
     * row whose role text names the unresolved sharing; claiming it returns
     * PROVISIONAL with that role until 0.3/E07 resolves it. */
    ROW_CAND(21, VDOG_STRAPS_ROLE_UNCLAIMED),
    /* Microphone: DISABLED by the product baseline (no audio capture).
     * Claim -> REJECT; no initialization ever. */
    ROW_MIC(41, VDOG_STRAPS_ROLE_MIC),
    ROW_MIC(42, VDOG_STRAPS_ROLE_MIC),
};

const unsigned vdog_straps_table_count =
    (unsigned)(sizeof(vdog_straps_table) / sizeof(vdog_straps_table[0]));

const vdog_straps_row_t *vdog_straps_lookup(uint8_t gpio)
{
    unsigned i;
    for (i = 0; i < vdog_straps_table_count; ++i) {
        if (vdog_straps_table[i].gpio == gpio) {
            return &vdog_straps_table[i];
        }
    }
    return NULL;
}

vdog_straps_claim_t vdog_straps_check_claim(uint8_t gpio,
                                            vdog_straps_claimant_t claim,
                                            const char **out_role)
{
    const vdog_straps_row_t *row;

    (void)claim; /* every claimant meets the same table for now */

    if (out_role != NULL) {
        *out_role = NULL;
    }
    if (gpio > 48u) { /* ESP32-S3 package GPIO range */
        if (out_role != NULL) {
            *out_role = "invalid-gpio (ESP32-S3 GPIO range 0..48)";
        }
        return VDOG_STRAPS_REJECT;
    }
    row = vdog_straps_lookup(gpio);
    if (row == NULL) {
        return VDOG_STRAPS_OK;
    }
    if (out_role != NULL) {
        *out_role = row->role;
    }
    if (row->disabled != 0u || row->reserved != 0u) {
        return VDOG_STRAPS_REJECT;
    }
    return VDOG_STRAPS_PROVISIONAL; /* candidate row: never approval */
}
