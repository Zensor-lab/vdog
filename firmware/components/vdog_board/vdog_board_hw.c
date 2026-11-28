/*
 * vdog target-side memory/recovery adapter — implementation (package 1.2,
 * plan A3). Read-only SDK queries only; decision logic stays in the
 * portable modules. Follows the 1.1 adapter discipline: every CONFIGURED
 * field is set ONLY from an explicit CONFIG_* macro (no #else branches, so
 * an unset key stays "field not set"); MEASURED fields are set ONLY from
 * successful chip queries.
 */
#include <string.h>

#include "esp_chip_info.h"
#include "esp_err.h"
#include "esp_flash.h"
#include "esp_mac.h"
#ifdef CONFIG_SPIRAM
#include "esp_psram.h" /* referenced only inside the CONFIG_SPIRAM block below */
#endif

#include "vdog_board_hw.h"

vdog_mem_detected_t vdog_mem_detected_from_sdkconfig(void)
{
    vdog_mem_detected_t det;
    vdog_mem_detected_init(&det);

#ifdef CONFIG_ESPTOOLPY_FLASHMODE_QIO
    det.flash_mode = VDOG_BOARD_FLASH_MODE_QIO;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
#elif defined(CONFIG_ESPTOOLPY_FLASHMODE_DIO)
    det.flash_mode = VDOG_BOARD_FLASH_MODE_DIO;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
#elif defined(CONFIG_ESPTOOLPY_FLASHMODE_DOUT)
    det.flash_mode = VDOG_BOARD_FLASH_MODE_DOUT;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
#elif defined(CONFIG_ESPTOOLPY_FLASHMODE_QOUT)
    det.flash_mode = VDOG_BOARD_FLASH_MODE_QOUT;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
#endif
    /* No #else: no flash mode key means "field not set", never a guess. */

#ifdef CONFIG_ESPTOOLPY_FLASHFREQ_80M
    det.flash_freq_mhz = 80u;
    det.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_FREQ;
#elif defined(CONFIG_ESPTOOLPY_FLASHFREQ_40M)
    det.flash_freq_mhz = 40u;
    det.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_FLASH_FREQ;
#endif

#ifdef CONFIG_SPIRAM_MODE_OCT
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_OPI;
    det.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_PSRAM_MODE;
#elif defined(CONFIG_SPIRAM_MODE_QUAD)
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    det.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_PSRAM_MODE;
#endif

#ifdef CONFIG_SPIRAM_SPEED_80M
    det.psram_speed_mhz = 80u;
    det.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_PSRAM_SPEED;
#elif defined(CONFIG_SPIRAM_SPEED_40M)
    det.psram_speed_mhz = 40u;
    det.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set |= VDOG_MEM_FIELD_PSRAM_SPEED;
#endif

    /* flash_size / psram_present / psram_size are MEASURED fields: never
     * stated from configuration here (finding 2). */
    return det;
}

int vdog_mem_read_detected(vdog_mem_detected_t *det)
{
    uint32_t header_bytes = 0u;
    uint32_t physical_bytes = 0u;
    int failed = VDOG_OK;
    esp_err_t header_err;
    esp_err_t physical_err;

    if (det == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }

    /* NULL selects the default flash-chip instance. esp_flash.h's @param
     * wording covers chips "initialised via esp_flash_init()", which the
     * ROM bootloader / SDK bring-up have already done for the default chip
     * before app_main runs — so we pass NULL (the same default-chip object
     * the SDK's own tests query), never an uninitialised handle. Review
     * F-3: this is the ROM/bring-up inout contract, not a documented
     * NULL-substitution in the get_size @param text.
     *
     * Review H-A — the two queries answer DIFFERENT questions:
     * esp_flash_get_size() returns the IMAGE-HEADER capacity after IDF
     * bring-up (an 8 MiB image on a 16 MiB N16R8-shaped chip reports 8
     * MiB — trusting it would defeat the wrong-board rejection), while
     * esp_flash_get_physical_size() detects the REAL chip size from its
     * ID (installed esp_flash.h:75: "If you want to get the real size of
     * the chip, please call esp_flash_get_physical_size instead"). The
     * MEASURED field is fed ONLY by the physical query; the header value
     * is recorded as honest informational data by the portable helper. */
    header_err = esp_flash_get_size(NULL, &header_bytes);
    physical_err = esp_flash_get_physical_size(NULL, &physical_bytes);
    if (vdog_mem_set_flash_sizes(
            det, (header_err == ESP_OK) ? header_bytes : 0u,
            (physical_err == ESP_OK) ? physical_bytes : 0u) != VDOG_OK) {
        /* Physical (chip-ID) query failed: flash_size stays UNSET so the
         * baseline check reports MISSING, never header-as-fact. */
        failed = VDOG_ERR_MEM_FLASH;
    }

#ifdef CONFIG_SPIRAM
    /* PSRAM init success + usable size. esp_psram_get_size() reports the
     * bytes actually initialized for use (0 when absent) — this is the
     * indirect proof the build's OPI claim had to be read from config; the
     * size itself is MEASURED. Compiled only when the image is built WITH
     * SPIRAM (1.1 #ifdef discipline): without CONFIG_SPIRAM the fields stay
     * UNSET and the portable check fails loudly as MISSING, never 0-as-
     * fact; this also keeps the adapter from referencing the PSRAM helper
     * in builds where the SDK does not provide it. */
    {
        size_t psram_bytes = esp_psram_get_size();
        det->psram_size_bytes = (uint32_t)psram_bytes;
        det->psram_size_src = VDOG_MEM_SOURCE_MEASURED;
        det->field_set |= VDOG_MEM_FIELD_PSRAM_SIZE;
        det->psram_present = (psram_bytes > 0u) ? 1u : 0u;
        det->psram_present_src = VDOG_MEM_SOURCE_MEASURED;
        det->field_set |= VDOG_MEM_FIELD_PSRAM_PRESENT;
    }
#endif

    return failed;
}

void vdog_identity_read_esp(vdog_identity_t *id)
{
    esp_chip_info_t info;
    uint8_t mac[6];

    if (id == NULL) {
        return;
    }
    esp_chip_info(&info); /* read-only chip identity */
    /* Closed-set model (review M-D): the SDK enum maps onto the portable
     * enum; anything unrecognised renders "unknown" and no caller string
     * can ever reach the identity line. */
    vdog_identity_set_chip_model(
        id, (info.model == CHIP_ESP32S3) ? VDOG_IDENTITY_CHIP_ESP32S3
                                         : VDOG_IDENTITY_CHIP_UNKNOWN);
    /* Wafer revision is DECIMAL MXX (major*100 + minor) per the installed
     * esp_hw_support/include/esp_chip_info.h:53 — the portable helper does
     * the /100 %100 split (review F-2: a byte split would render S3 v1.1,
     * raw 101, as 0.101 in the record Part B transcribes). */
    vdog_identity_set_revision_mxx(id, info.revision);

    /* Public helper API only (no eFuse raw reads): the factory-burned base
     * MAC eFuse read through esp_read_mac, of which ONLY the last two bytes
     * are kept — a full MAC never persists in memory we control. */
    if (esp_read_mac(mac, ESP_MAC_EFUSE_FACTORY) == ESP_OK) {
        id->mac_tail = (uint16_t)(((uint16_t)mac[4] << 8) | (uint16_t)mac[5]);
        id->mac_valid = 1u;
    } else {
        id->mac_valid = 0u; /* never invented */
    }
    /* mem/mem_valid/board_tag stay as provided: the CALLER decides whether
     * a baseline-checked summary may be rendered, and the board tag is an
     * owner-supplied opaque label from hardware-identity.md (Part B). */
}
