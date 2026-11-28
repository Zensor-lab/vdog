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
#include "esp_psram.h"

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
    esp_flash_t *flash;
    uint32_t size = 0u;
    int failed = VDOG_OK;

    if (det == NULL) {
        return VDOG_ERR_INVALID_ARG;
    }

    /* IDF v6.1 exposes the default chip pointer directly (esp_flash.h:
     * extern esp_flash_t *esp_flash_default_chip); the getter used by older
     * SDKs is not part of this pinned framework's public headers. */
    flash = esp_flash_default_chip;
    if (flash != NULL && esp_flash_get_size(flash, &size) == ESP_OK) {
        det->flash_size_bytes = size;
        det->flash_size_src = VDOG_MEM_SOURCE_MEASURED;
        det->field_set |= VDOG_MEM_FIELD_FLASH_SIZE;
    } else {
        /* Query failed honestly: leave UNSET (missing beats invented). */
        failed = VDOG_ERR_MEM_FLASH;
    }

    /* PSRAM init success + usable size. esp_psram_get_size() reports the
     * bytes actually initialized for use (0 when absent/disabled under the
     * CONFIGURED mode) — this is the indirect proof the build's OPI claim
     * had to be read from config; the size itself is MEASURED. */
    {
        size_t psram_bytes = esp_psram_get_size();
        det->psram_size_bytes = (uint32_t)psram_bytes;
        det->psram_size_src = VDOG_MEM_SOURCE_MEASURED;
        det->field_set |= VDOG_MEM_FIELD_PSRAM_SIZE;
        det->psram_present = (psram_bytes > 0u) ? 1u : 0u;
        det->psram_present_src = VDOG_MEM_SOURCE_MEASURED;
        det->field_set |= VDOG_MEM_FIELD_PSRAM_PRESENT;
    }

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
    /* Enum spelling in this pinned framework is esp_chip_model_t::
     * CHIP_ESP32S3 (the ESP_CHIP_MODEL_* alias set is not present in
     * esp_chip_info.h of IDF v6.1). */
    if (info.model == CHIP_ESP32S3) {
        strcpy(id->chip_model, "esp32s3");
    } else {
        strcpy(id->chip_model, "unknown");
    }
    id->chip_major = (uint8_t)(info.revision >> 8);
    id->chip_minor = (uint8_t)(info.revision & 0xFF);

    /* Public helper API only (no eFuse raw reads); ONLY the last two bytes
     * are kept, so a full MAC never exists in memory we control. */
    if (esp_read_mac(mac, ESP_MAC_WIFI_STA) == ESP_OK) {
        id->mac_tail = (uint16_t)(((uint16_t)mac[4] << 8) | (uint16_t)mac[5]);
        id->mac_valid = 1u;
    } else {
        id->mac_valid = 0u; /* never invented */
    }
    /* mem/mem_valid/board_tag stay as provided: the CALLER decides whether
     * a baseline-checked summary may be rendered, and the board tag is an
     * owner-supplied opaque label from hardware-identity.md (Part B). */
}
