/*
 * vdog firmware — package 0.2 minimal qualified bootstrap, extended by
 * package 1.1 with the board-identity gate and version/board reporting.
 *
 * Purpose: prove the pinned ESP-IDF toolchain cross-builds for the Seeed
 * XIAO ESP32S3 Sense target, that the portable core module builds inside the
 * IDF component graph, and that the pinned camera driver links as a real
 * dependency. NO camera, SD, network or radio runtime is initialized here;
 * the microphone stays untouched. Device evidence (upload/boot/PSRAM
 * detection) is deferred to packages 1.2-1.4.
 */
#include <stddef.h>

#include "esp_err.h"
#include "esp_log.h"
#include "esp_ota_ops.h"

/* Link-time qualification of the pinned espressif/esp32-camera component:
 * referencing a public symbol keeps the driver in the image without ever
 * calling it at runtime in this package. */
#include "esp_camera.h"

#include "vdog_core.h"
#include "vdog_board.h"
#include "vdog_board_idf.h"

/* Generated before compilation by firmware/scripts/gen_build_meta.py from
 * validated VDOG_SOURCE_SHA/VDOG_BUILD_ID inputs (gitignored; on the
 * environment CPPPATH and the IDF "main" component include path). */
#include "vdog_build_id.h"

static const char *TAG = "vdog";

/* Human-readable name for a board-gate code, for the boot log only: the
 * DECISION and the offending field name come from the portable validator
 * (core/vdog_board.c), never from here. */
static const char *vdog_board_error_name(int code)
{
    switch (code) {
    case VDOG_ERR_BOARD_MISSING_FIELD:
        return "field never configured";
    case VDOG_ERR_BOARD_UNSUPPORTED_TARGET:
        return "unsupported target/board";
    case VDOG_ERR_BOARD_FLASH:
        return "flash configuration";
    case VDOG_ERR_BOARD_PSRAM:
        return "PSRAM configuration";
    case VDOG_ERR_BOARD_PARTITIONS:
        return "partition table";
    case VDOG_ERR_INVALID_ARG:
        return "invalid argument";
    default:
        return "unknown error";
    }
}

typedef esp_err_t (*vdog_camera_deinit_fn_t)(void);
static volatile vdog_camera_deinit_fn_t vdog_camera_deinit_ref =
    esp_camera_deinit;

void app_main(void)
{
    char version[64];

    if (vdog_format_version(version, sizeof(version)) == VDOG_OK) {
        ESP_LOGI(TAG, "vdog firmware %s (0.2 proto build)", version);
    } else {
        ESP_LOGE(TAG, "version formatting failed");
    }

    /* Stage 0.9 packet A: build identity alongside the version, so console
     * evidence ties a booting image to its source SHA and CI build ID. */
    ESP_LOGI(TAG, "build identity: build_id=%s source_sha=%s",
             VDOG_BUILD_ID_STR, VDOG_SOURCE_SHA_SHORT);

    /* Stage 1.1: board identity gate. The profile comes from THIS image's own
     * configuration (components/vdog_board) and the portable validator in
     * core/vdog_board.c decides whether it is the supported prototype
     * configuration; an unset key is reported as "field never configured"
     * instead of being silently defaulted. Console evidence only — no device
     * was connected for this package, and this still initializes NO
     * peripheral, pin, card, camera or microphone. */
    {
        vdog_board_profile_t board = vdog_board_profile_from_sdkconfig();
        char board_report[128];
        const int board_rc = vdog_board_report(&board, board_report,
                                               sizeof(board_report));

        if (board_rc == VDOG_OK) {
            ESP_LOGI(TAG, "board: %s", board_report);
        } else {
            const char *field = vdog_board_error_field();
            ESP_LOGE(TAG, "board config rejected: %s (field %s)",
                     vdog_board_error_name(board_rc),
                     (field != NULL) ? field : "unspecified");
        }
    }

    /* Compile/link proof only: never invoked at runtime in 0.2. */
    ESP_LOGI(TAG, "esp32-camera linked: %s",
             (vdog_camera_deinit_ref != NULL) ? "yes" : "no");

#if CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
    /* SDK rollback support is compiled in (sdkconfig.defaults); a proto
     * build with no health check marks itself valid so a reboot cannot
     * strand the prototype in a rollback loop. */
    esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_ota_mark_app_valid_cancel_rollback: %s",
                 esp_err_to_name(err));
    }
#endif
}
