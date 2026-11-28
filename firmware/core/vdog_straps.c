/*
 * vdog portable strap/reserved-pin table — implementation (package 1.2,
 * plan A2b). Pure C11; stdio (snprintf) only. See vdog_straps.h for the
 * contract: reserved rows REJECT, candidate rows are PROVISIONAL (never an
 * approval), GPIO21 is UNCLAIMED (its SD-CS/user-LED sharing belongs to
 * 0.3/E07), microphone rows stay DISABLED (CSV owner=disabled: "Do not
 * initialize microphone or drive its clock").
 *
 * EVERY candidate/disabled row below is re-derived line-by-line from
 * hardware/prototype-a/pin-map.csv (status CANDIDATE_NOT_APPROVED there),
 * citing the CSV's own function,net,soc_gpio columns per row. The CSV
 * camera set {10,11,12,13,14,15,16,17,18,38,39,40,47,48} and SD set
 * {7,8,9,21} are DISJOINT — there are no dual-candidate pins. GPIO3/45/46
 * are strap pins required by the plan (A2b) and carry no CSV candidate row
 * (GPIO3 appears in the CSV only as expansion UNASSIGNED_D2 with "audit
 * straps/debug before use"; reserved outranks expansion). Rows are pinned
 * against the CSV by test_vdog_straps.c.
 */
#include <stdio.h>
#include <string.h>

#include "vdog_straps.h"

#define VDOG_STRAPS_ROLE_INVALID_GPIO "invalid-gpio"
#define VDOG_STRAPS_ROLE_INVALID_CLAIMANT "invalid-claimant"

/* gpio ASCENDING (the host suite pins ordering + uniqueness); the flags
 * decide the verdict: disabled > reserved > candidate > no-row(OK). */
static const vdog_straps_row_t g_vdog_straps_rows[] = {
    /* pin-map: control,BOOT,0 (owner boot_recovery; strap pulls review) */
    {0u, VDOG_STRAPS_ROLE_BOOT, 1u, 0u, 0u},
    /* strap pin per plan A2b; CSV lists GPIO3 only as expansion
     * UNASSIGNED_D2 ("audit straps/debug before use") — reserved outranks */
    {3u, VDOG_STRAPS_ROLE_JTAG, 1u, 0u, 0u},
    /* ---- SD-card candidates (CSV function=sd, owner=storage,
     * CANDIDATE_NOT_APPROVED; the CSV's own note names the SPI-SD host
     * driver, spelled here without the driver symbol) ---- */
    /* pin-map: sd,SPI_SCK,7 (pad D8; verify pulls/CS at reset) */
    {7u, VDOG_STRAPS_ROLE_SD_SPI, 0u, 1u, 0u},
    /* pin-map: sd,SPI_MISO,8 (pad D9) */
    {8u, VDOG_STRAPS_ROLE_SD_SPI, 0u, 1u, 0u},
    /* pin-map: sd,SPI_MOSI,9 (pad D10) */
    {9u, VDOG_STRAPS_ROLE_SD_SPI, 0u, 1u, 0u},
    /* ---- camera candidates (CSV function=camera, owner=camera,
     * CANDIDATE_NOT_APPROVED) ---- */
    /* pin-map: camera,XCLK,10 (output; no external expansion) */
    {10u, VDOG_STRAPS_ROLE_CAM_XCLK, 0u, 1u, 0u},
    /* pin-map: camera,Y8,11 (notes: D6; preserve data ordering) */
    {11u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,Y7,12 (notes: D5; preserve data ordering) */
    {12u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,PCLK,13 (input; no external expansion) */
    {13u, VDOG_STRAPS_ROLE_CAM_SYNC, 0u, 1u, 0u},
    /* pin-map: camera,Y6,14 (notes: D4; preserve data ordering) */
    {14u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,Y2,15 (notes: D0; preserve data ordering) */
    {15u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,Y5,16 (notes: D3; preserve data ordering) */
    {16u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,Y3,17 (notes: D1; preserve data ordering) */
    {17u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: camera,Y4,18 (notes: D2; preserve data ordering) */
    {18u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
    /* pin-map: usb,USB_D_MINUS,19 (owner usb_service; preserve native USB) */
    {19u, VDOG_STRAPS_ROLE_USB_DN, 1u, 0u, 0u},
    /* pin-map: usb,USB_D_PLUS,20 (owner usb_service; preserve native USB) */
    {20u, VDOG_STRAPS_ROLE_USB, 1u, 0u, 0u},
    /* ---- GPIO21: the UNRESOLVED sharing, claimed by NOTHING here.
     * CSV lists it twice: sd,SPI_CS,21 (owner storage) AND
     * indicator,USER_LED,21 (owner storage_shared_no_independent_led,
     * "Intentional CS21 alias; no heartbeat or PWM while SD mounted").
     * The row documents the conflict; it claims the pin for neither side,
     * and claims return PROVISIONAL naming the unresolved sharing until
     * 0.3/E07 (Jada's sign-off) resolves it. ---- */
    {21u, VDOG_STRAPS_ROLE_UNCLAIMED, 0u, 1u, 0u},
    /* pin-map: camera,VSYNC,38 (input; no external expansion) */
    {38u, VDOG_STRAPS_ROLE_CAM_SYNC, 0u, 1u, 0u},
    /* pin-map: camera,SCCB_SCL,39 (output; reconcile SCCB pulls) */
    {39u, VDOG_STRAPS_ROLE_CAM_SCCB, 0u, 1u, 0u},
    /* pin-map: camera,SCCB_SDA,40 (bidirectional; reconcile SCCB pulls) */
    {40u, VDOG_STRAPS_ROLE_CAM_SCCB, 0u, 1u, 0u},
    /* ---- microphone: CSV function=microphone owner=disabled — REJECTED
     * forever ("Do not initialize microphone or drive its clock") ---- */
    /* pin-map: microphone,MIC_DATA,41 */
    {41u, VDOG_STRAPS_ROLE_MIC, 0u, 0u, 1u},
    /* pin-map: microphone,MIC_CLK,42 */
    {42u, VDOG_STRAPS_ROLE_MIC, 0u, 0u, 1u},
    /* strap pins per plan A2b (ESP32-S3 datasheet straps; no CSV row) */
    {45u, VDOG_STRAPS_ROLE_VDD_SPI, 1u, 0u, 0u},
    {46u, VDOG_STRAPS_ROLE_BOOT_MODE, 1u, 0u, 0u},
    /* pin-map: camera,HREF,47 (input; no external expansion) */
    {47u, VDOG_STRAPS_ROLE_CAM_SYNC, 0u, 1u, 0u},
    /* pin-map: camera,Y9,48 (notes: D7; preserve data ordering) */
    {48u, VDOG_STRAPS_ROLE_CAM_DATA, 0u, 1u, 0u},
};

/* GPIOs with NO row are unclaimed by this table (CSV lists some as
 * expansion UNASSIGNED_*: 1,2,4,5,6,43,44 — "audit straps/debug before
 * use"; OK from this gate is NOT an approval of ownership: approved wiring
 * is 0.3/0.7 evidence this table cannot grant). */

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
