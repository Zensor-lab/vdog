/*
 * vdog portable strap/reserved-pin table — implementation (package 1.2,
 * plan A2b). Pure C11; stdio (snprintf) only. See vdog_straps.h for the
 * contract: reserved rows REJECT, candidate rows are PROVISIONAL (never an
 * approval), GPIO21 is UNCLAIMED (its SD-CS/user-LED sharing belongs to
 * 0.3/E07), microphone rows stay DISABLED (product baseline: audio dead).
 *
 * Candidate rows transcribe hardware/prototype-a/pin-map.csv, whose camera
 * and SD rows are CANDIDATE_NOT_APPROVED there; where the pin-map lists the
 * SAME GPIO as both a camera and an SD candidate (8/9/10), the row says so
 * instead of silently dropping one candidate.
 */
#include <stdio.h>
#include <string.h>

#include "vdog_straps.h"

/* Pin-map lists camera XCLK and mic SCK on GPIO40, and camera HREF and mic
 * SD on GPIO42. One row per GPIO: those rows stay CAMERA candidates (the
 * audio baseline keeps the mic dead either way), with the conflict named in
 * the role string; the pure microphone pins 39/41 carry DISABLED rows. */
#define VDOG_STRAPS_ROLE_CAM_XCLK_MIC \
    "camera XCLK (candidate); mic SCK DISABLED by product baseline"
#define VDOG_STRAPS_ROLE_CAM_SYNC_MIC \
    "camera PCLK/VSYNC/HREF (candidate); mic pin DISABLED by product baseline"
#define VDOG_STRAPS_ROLE_CAM_SCCB_SD_SPI \
    "camera SCCB/I2C + SD SPI SCK/MISO/MOSI (both candidates)"
#define VDOG_STRAPS_ROLE_CAM_SYNC_SD_SPI \
    "camera PCLK/VSYNC/HREF + SD SPI SCK/MISO/MOSI (both candidates)"
#define VDOG_STRAPS_ROLE_CAM_DATA_SD_SPI \
    "camera DVP data + SD SPI SCK/MISO/MOSI (both candidates)"
#define VDOG_STRAPS_ROLE_INVALID_GPIO "invalid-gpio"
#define VDOG_STRAPS_ROLE_INVALID_CLAIMANT "invalid-claimant"

/* gpio ascending; reserved/candidate/disabled decide the verdict:
 * disabled > reserved > candidate > no-row(OK). */
static const vdog_straps_row_t g_vdog_straps_rows[] = {
    {0u, VDOG_STRAPS_ROLE_BOOT, 1u, 0u, 0u},
    {3u, VDOG_STRAPS_ROLE_JTAG, 1u, 0u, 0u},
    {7u, VDOG_STRAPS_ROLE_CAM_SCCB, 0u, 1u, 0u},
    {8u, VDOG_STRAPS_ROLE_CAM_SCCB_SD_SPI, 0u, 1u, 0u},
    {9u, VDOG_STRAPS_ROLE_CAM_SYNC_SD_SPI, 0u, 1u, 0u},
    {10u, VDOG_STRAPS_ROLE_CAM_DATA_SD_SPI, 0u, 1u, 0u},
    {11u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {12u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {14u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {15u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {16u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {17u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {18u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    {19u, VDOG_STRAPS_ROLE_USB_DN, 1u, 0u, 0u},
    {20u, VDOG_STRAPS_ROLE_USB, 1u, 0u, 0u},
    {21u, VDOG_STRAPS_ROLE_UNCLAIMED, 0u, 1u, 0u},
    {39u, VDOG_STRAPS_ROLE_MIC, 0u, 0u, 1u},
    {40u, VDOG_STRAPS_ROLE_CAM_XCLK_MIC, 0u, 1u, 0u},
    {41u, VDOG_STRAPS_ROLE_MIC, 0u, 0u, 1u},
    {42u, VDOG_STRAPS_ROLE_CAM_SYNC_MIC, 0u, 1u, 0u},
    {45u, VDOG_STRAPS_ROLE_VDD_SPI, 1u, 0u, 0u},
    {46u, VDOG_STRAPS_ROLE_BOOT_MODE, 1u, 0u, 0u},
};

const vdog_straps_row_t *vdog_straps_table(void)
{
    return g_vdog_straps_rows;
}

unsigned vdog_straps_table_count(void)
{
    return (unsigned)(sizeof(g_vdog_straps_rows) /
                      sizeof(g_vdog_straps_rows[0]));
}

const vdog_straps_row_t *vdog_straps_lookup(uint8_t gpio)
{
    size_t i;

    for (i = 0; i < sizeof(g_vdog_straps_rows) / sizeof(g_vdog_straps_rows[0]);
         ++i) {
        if (g_vdog_straps_rows[i].gpio == gpio) {
            return &g_vdog_straps_rows[i];
        }
    }
    return NULL;
}

static vdog_straps_claim_t decide(const vdog_straps_row_t *row,
                                  const char **out_role)
{
    /* Priority: disabled audio baseline > reserved > candidate. */
    if (row->disabled != 0u) {
        if (out_role != NULL) {
            *out_role = row->role;
        }
        return VDOG_STRAPS_REJECT;
    }
    if (row->reserved != 0u) {
        if (out_role != NULL) {
            *out_role = row->role;
        }
        return VDOG_STRAPS_REJECT;
    }
    if (row->candidate != 0u) {
        if (out_role != NULL) {
            *out_role = row->role;
        }
        /* PROVISIONAL for EVERY claimant, including GENERAL: a candidate
         * reservation outranks ad-hoc reuse until 0.3/0.7 evidence resolves
         * the map. This is a marker, NEVER an approval. */
        return VDOG_STRAPS_PROVISIONAL;
    }
    if (out_role != NULL) {
        *out_role = NULL;
    }
    return VDOG_STRAPS_OK;
}

vdog_straps_claim_t vdog_straps_check_claim(uint8_t gpio,
                                            vdog_straps_claimant_t claim,
                                            const char **out_role)
{
    const vdog_straps_row_t *row;

    if (out_role != NULL) {
        *out_role = NULL;
    }
    if (gpio > VDOG_STRAPS_GPIO_MAX) {
        /* Not "an unclaimed pin": a programming error, named as such. */
        if (out_role != NULL) {
            *out_role = VDOG_STRAPS_ROLE_INVALID_GPIO;
        }
        return VDOG_STRAPS_REJECT;
    }
    if ((unsigned)claim > (unsigned)VDOG_STRAPS_CLAIM_SD) {
        if (out_role != NULL) {
            *out_role = VDOG_STRAPS_ROLE_INVALID_CLAIMANT;
        }
        return VDOG_STRAPS_REJECT;
    }
    row = vdog_straps_lookup(gpio);
    if (row == NULL) {
        /* Unclaimed by this table — NOT an approval of wiring ownership:
         * approved pin assignments are 0.3/0.7 evidence this table cannot
         * grant. */
        return VDOG_STRAPS_OK;
    }
    return decide(row, out_role);
}
