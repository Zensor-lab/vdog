/*
 * vdog portable strap/reserved-pin table (package 1.2, plan A2b — lead
 * finding 1a). Pure C11, host-tested; this is the desk half of "no strap
 * conflicts": EVERY future pin claim must pass vdog_straps_check_claim(),
 * and no Part A code (including main.c) claims any pin.
 *
 * The table mirrors hardware/prototype-a/pin-map.csv as candidate
 * information only — the candidate map is CANDIDATE_NOT_APPROVED and this
 * module approves nothing:
 *   - STRAP rows (GPIO0 BOOT, GPIO3, GPIO45, GPIO46) and the native-USB
 *     pair (GPIO19/GPIO20) reject any claim, naming pin + role.
 *   - camera / SD candidate rows return PROVISIONAL, never approval.
 *   - GPIO21 (SD-CS vs user-LED sharing) is DELIBERATELY UNCLAIMED here:
 *     no row claims it as LED, no row claims it as SD-CS; a claim returns
 *     PROVISIONAL naming the unresolved sharing, to be resolved by 0.3/E07
 *     (Jada's sign-off), not by this table.
 *   - SoC-impossible and shared-bus rows REJECT (plan 1.2 review H-B):
 *     GPIO22-25 do not exist on the ESP32-S3 (only GPIO0-21 and GPIO26-48
 *     are bonded out), GPIO26-32 form the SPI flash bus, and GPIO33-37
 *     form the octal-PSRAM bus this baseline's module uses. A claim on
 *     any of them is REJECTED with the reason as the role.
 * With those rows the table covers EVERY GPIO 0..48: the no-row path is
 * unreachable for valid inputs and can no longer hand out a silent OK.
 */
#ifndef VDOG_STRAPS_H
#define VDOG_STRAPS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Result of asking "may this GPIO be claimed by function <claim>?" */
typedef enum {
    VDOG_STRAPS_OK = 0,   /* documented free/expansion row: claim -> OK    */
    VDOG_STRAPS_REJECT,   /* reserved/bus/absent/disabled: pin + role      */
    VDOG_STRAPS_PROVISIONAL /* candidate row: provisional, NEVER approval  */
} vdog_straps_claim_t;

/* ---- claimant validation bound (plan 1.2 A2b) ---- */
#define VDOG_STRAPS_GPIO_MAX 48u /* ESP32-S3 has GPIO0..GPIO48; higher is a
                                  * programming error, not "unclaimed"     */

/* What wants the pin (plan 1.2 A2b). */
typedef enum {
    VDOG_STRAPS_CLAIM_GENERAL = 0,
    VDOG_STRAPS_CLAIM_CAMERA,
    VDOG_STRAPS_CLAIM_SD
} vdog_straps_claimant_t;

/* Row roles (stable strings for logs; the reject/PROVISIONAL messages
 * name these verbatim). */
#define VDOG_STRAPS_ROLE_BOOT "BOOT strap (download-mode entry)"
#define VDOG_STRAPS_ROLE_JTAG "JTAG-select strap pin"
#define VDOG_STRAPS_ROLE_VDD_SPI "VDD_SPI strap pin"
#define VDOG_STRAPS_ROLE_BOOT_MODE "boot-mode strap pin"
#define VDOG_STRAPS_ROLE_USB "native USB DP (host re-enumeration)"
#define VDOG_STRAPS_ROLE_USB_DN "native USB DM (host re-enumeration)"
#define VDOG_STRAPS_ROLE_CAM_DATA "camera DVP data (candidate)"
#define VDOG_STRAPS_ROLE_CAM_XCLK "camera XCLK (candidate)"
#define VDOG_STRAPS_ROLE_CAM_SYNC "camera PCLK/VSYNC/HREF (candidate)"
#define VDOG_STRAPS_ROLE_CAM_SCCB "camera SCCB/I2C (candidate)"
#define VDOG_STRAPS_ROLE_SD_SPI "SD card SPI SCK/MISO/MOSI (candidate)"
#define VDOG_STRAPS_ROLE_MIC "onboard microphone (DISABLED by product baseline)"
#define VDOG_STRAPS_ROLE_UNCLAIMED "GPIO21 SD-CS/user-LED sharing UNRESOLVED (no claim)"
#define VDOG_STRAPS_ROLE_ABSENT "absent GPIO (ESP32-S3 bonds out only GPIO0-21/26-48)"
#define VDOG_STRAPS_ROLE_FLASH_BUS "SPI flash bus (shared with the onboard flash chip)"
#define VDOG_STRAPS_ROLE_PSRAM_BUS "octal PSRAM bus (shared with the onboard PSRAM)"
#define VDOG_STRAPS_ROLE_EXPANSION "expansion GPIO (CSV UNASSIGNED; audit straps/debug before use)"

/* Table row for host-side pinning (plan 1.2 A4: "every row" is asserted).
 * Exactly one of reserved/candidate/disabled set => that verdict class;
 * all three clear => documented free/expansion row, claim -> OK. */
typedef struct {
    uint8_t gpio;
    const char *role;   /* one of the VDOG_STRAPS_ROLE_* strings          */
    uint8_t reserved;   /* 1 = strap/USB-reserved: claim -> REJECT        */
    uint8_t candidate;  /* 1 = camera/SD candidate: claim -> PROVISIONAL  */
    uint8_t disabled;   /* 1 = mic rows: must stay uninitialized forever  */
} vdog_straps_row_t;

/* The whole const table, for host-side pinning of EVERY row (plan 1.2 A4).
 * Function accessors (not extern objects): the host suite asserts rows,
 * statuses, roles and gpio ordering against these. */
const vdog_straps_row_t *vdog_straps_table(void);
unsigned vdog_straps_table_count(void);

/* Look up a row (NULL when the table has no row for this GPIO). */
const vdog_straps_row_t *vdog_straps_lookup(uint8_t gpio);

/* The claim gate. Returns REJECT on strap/USB-reserved pins and PROVISIONAL
 * on camera/SD candidates (naming the role via out_role, when non-NULL);
 * OK otherwise. A claim on GPIO21 returns PROVISIONAL naming the
 * unresolved SD-CS/user-LED sharing (the CSV lists sd,SPI_CS,21 AND
 * indicator,USER_LED,21) — this table NEVER claims or approves it. The
 * microphone rows (microphone,MIC_DATA,41 and microphone,MIC_CLK,42, CSV
 * owner=disabled) are DISABLED: a claim is REJECTED with the disabled role
 * (the product baseline keeps audio dead). SoC-impossible GPIO22-25, the
 * SPI flash bus 26-32 and the octal-PSRAM bus 33-37 REJECT with the reason
 * as their role (review H-B). The table carries a row for EVERY gpio
 * 0..48, so the no-row/OK path is unreachable for valid inputs; the
 * documented free/expansion rows ({1,2,4,5,6,43,44}) return OK with a NULL
 * role — OK is never an approval of ownership. Out-param may be NULL.
 * Invalid gpio (> VDOG_STRAPS_GPIO_MAX) is REJECT naming "invalid-gpio";
 * an out-of-range claimant is REJECT naming "invalid-claimant". */
vdog_straps_claim_t vdog_straps_check_claim(uint8_t gpio,
                                            vdog_straps_claimant_t claim,
                                            const char **out_role);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_STRAPS_H */
