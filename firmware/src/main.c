/*
 * vdog firmware — package 0.2 minimal qualified bootstrap.
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

static const char *TAG = "vdog";

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
