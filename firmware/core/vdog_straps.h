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
 */
#ifndef VDOG_STRAPS_H
#define VDOG_STRAPS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Result of asking "may this GPIO be claimed by function <claim>?" */
typedef enum {
    VDOG_STRAPS_OK = 0,   /* no row claims the pin and it is not reserved  */
    VDOG_STRAPS_REJECT,   /* strap/reserved pin: naming pin + role         */
    VDOG_STRAPS_PROVISIONAL /* candidate row: provisional, NEVER approval  */
} vdog_straps_claim_t;

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
#define VDOG_STRAPS_ROLE_SD_CS "SD CS21 vs user-LED sharing UNRESOLVED"
#define VDOG_STRAPS_ROLE_MIC "onboard microphone (DISABLED by product baseline)"
#define VDOG_STRAPS_ROLE_UNCLAIMED "GPIO21 SD-CS/user-LED sharing UNRESOLVED (no claim)"

/* Table row for host-side pinning (plan 1.2 A4: "every row" is asserted). */
typedef struct {
    uint8_t gpio;
    const char *role;   /* one of the VDOG_STRAPS_ROLE_* strings          */
    uint8_t reserved;   /* 1 = strap/USB-reserved: claim -> REJECT        */
    uint8_t candidate;  /* 1 = camera/SD candidate: claim -> PROVISIONAL  */
    uint8_t disabled;   /* 1 = mic rows: must stay uninitialized forever  */
} vdog_straps_row_t;

extern const vdog_straps_row_t vdog_straps_table[];
extern const unsigned vdog_straps_table_count;

/* Look up a row (NULL when the table has no row for this GPIO). */
const vdog_straps_row_t *vdog_straps_lookup(uint8_t gpio);

/* The claim gate. Returns REJECT on strap/USB-reserved pins and PROVISIONAL
 * on camera/SD candidates (naming pin + role via the two out-params, when
 * non-NULL); OK otherwise. A claim on GPIO21 returns PROVISIONAL naming the
 * unresolved SD-CS/user-LED sharing — this table NEVER claims or approves
 * it. The microphone rows (41/42) are DISABLED: a claim is REJECTED with
 * the disabled role (the product baseline keeps audio dead). Out-params may
 * be NULL. Invalid gpio (>48 on ESP32-S3) is REJECT naming "invalid-gpio". */
vdog_straps_claim_t vdog_straps_check_claim(uint8_t gpio,
                                            vdog_straps_claimant_t claim,
                                            const char **out_role);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_STRAPS_H */
