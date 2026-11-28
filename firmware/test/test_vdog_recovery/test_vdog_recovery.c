/*
 * Host (native environment) tests for the vdog portable recovery/identity
 * core (package 1.2, plan A4). Run with: pio test -d firmware -e native
 * (HOST evidence only).
 *
 * Pins plan 1.2 acceptance 5: boot-mode classification never guesses
 * (unknown -> UNKNOWN), and the identity line can only ever render the
 * sanitized fields the struct is physically able to hold — no full MAC, no
 * eFuse raw values, no serials.
 */
#include <string.h>

#include "unity.h"
#include "vdog_core.h"
#include "vdog_mem.h"
#include "vdog_recovery.h"

extern int vdog_recovery_cpp_smoke(void);

static void fill_baseline_mem(vdog_mem_detected_t *d)
{
    vdog_mem_detected_init(d);
    d->flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    d->flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    d->field_set |= VDOG_MEM_FIELD_FLASH_SIZE;
    d->flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    d->flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d->field_set |= VDOG_MEM_FIELD_FLASH_MODE;
    d->flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    d->flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    d->field_set |= VDOG_MEM_FIELD_FLASH_FREQ;
    d->psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    d->psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    d->field_set |= VDOG_MEM_FIELD_PSRAM_PRESENT;
    d->psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    d->psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    d->field_set |= VDOG_MEM_FIELD_PSRAM_SIZE;
    d->psram_mode = VDOG_MEM_BASELINE_PSRAM_MODE;
    d->psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d->field_set |= VDOG_MEM_FIELD_PSRAM_MODE;
    d->psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    d->psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    d->field_set |= VDOG_MEM_FIELD_PSRAM_SPEED;
}

/* ---- boot-mode classification (A2) -------------------------------------- */

static void test_classify_unknown_never_guessed(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(""));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("hello world"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("ets Jul 29 2019 12:21:46"));
}

static void test_classify_normal(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("boot:0x13(spi_fast)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("boot:0x01(spi_boot)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("boot:0x3f(basic)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("BOOT:0x13(SPI_FAST)"));
}

static void test_classify_download(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify("boot:0x02(download)"));
    /* Order pinned: an spi_fast_download banner is a DOWNLOAD first. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify("boot:0x13(spi_fast_download)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify("Download Mode"));
}

static void test_classify_usb_jtag(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify(
                              "ESP-ROM:esp32s3-usb-jtag-20211025"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify("usb_jtag_serial"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify("USB-JTAG"));
    /* JTAG wins over a download word on the same line. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify("usb_jtag download mode"));
}

static void test_boot_mode_names(void)
{
    TEST_ASSERT_EQUAL_STRING("unknown",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_UNKNOWN));
    TEST_ASSERT_EQUAL_STRING("normal", vdog_boot_mode_name(VDOG_BOOT_MODE_NORMAL));
    TEST_ASSERT_EQUAL_STRING("download",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_DOWNLOAD));
    TEST_ASSERT_EQUAL_STRING("usbjtag",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_USBJTAG));
    TEST_ASSERT_EQUAL_STRING("unknown", vdog_boot_mode_name((vdog_boot_mode_t)99));
}

/* ---- sanitized identity (A2, acceptance 5) ------------------------------ */

static vdog_identity_t baseline_identity(void)
{
    vdog_identity_t id;
    vdog_identity_init(&id);
    strcpy(id.chip_model, "esp32s3");
    id.chip_major = 0u;
    id.chip_minor = 2u;
    fill_baseline_mem(&id.mem);
    id.mem_valid = 1u;
    id.mac_tail = 0xABCDu;
    id.mac_valid = 1u;
    strcpy(id.board_tag, "vdog-pa-01");
    return id;
}

static void test_identity_init_zeroes(void)
{
    vdog_identity_t id;
    memset(&id, 0xA5, sizeof(id));
    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mac_valid);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mem_valid);
    TEST_ASSERT_EQUAL_STRING("", id.chip_model);
    TEST_ASSERT_EQUAL_STRING("", id.board_tag);
}

static void test_identity_format_exact(void)
{
    vdog_identity_t id = baseline_identity();
    char buf[256];
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(
        "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] "
        "mac=**:**:**:**:ab:cd board=vdog-pa-01",
        buf);
}

static void test_identity_format_minimal(void)
{
    vdog_identity_t id;
    char buf[256];
    vdog_identity_init(&id);
    strcpy(id.chip_model, "esp32s3");
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=esp32s3 rev=0.0", buf);

    vdog_identity_init(&id); /* empty chip model */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);
}

static void test_identity_absent_tokens_omitted(void)
{
    vdog_identity_t id;
    char buf[256];
    vdog_identity_init(&id);
    strcpy(id.chip_model, "esp32s3");
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "mem="));
    TEST_ASSERT_NULL(strstr(buf, "mac="));
    TEST_ASSERT_NULL(strstr(buf, "board="));
}

static void test_identity_mac_tail_only(void)
{
    /* From the known interface MAC 1a:2b:3c:4d:5e:6f only the LAST TWO
     * BYTES (0x5e6f) exist in the struct — the OUI bytes were never
     * carried, so they cannot leak. */
    vdog_identity_t id = baseline_identity();
    char buf[256];
    id.mac_tail = 0x5e6fu;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NOT_NULL(strstr(buf, "mac=**:**:**:**:5e:6f"));
    TEST_ASSERT_NULL(strstr(buf, "1a"));
    TEST_ASSERT_NULL(strstr(buf, "2b"));
    TEST_ASSERT_NULL(strstr(buf, "3c"));
    TEST_ASSERT_NULL(strstr(buf, "4d"));
}

static void test_identity_rejects_unchecked_mem(void)
{
    vdog_identity_t id = baseline_identity();
    char buf[256];
    id.mem.flash_size_bytes = 4u * 1024u * 1024u; /* mem_valid set but the
                                                   * set would not pass the
                                                   * baseline check */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, buf, sizeof(buf)));
}

static void test_identity_buffers(void)
{
    vdog_identity_t id = baseline_identity();
    char buf[256];
    const char *expected =
        "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] "
        "mac=**:**:**:**:ab:cd board=vdog-pa-01";
    size_t need = strlen(expected);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, need + 1u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_identity_format(&id, buf, need));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, NULL, sizeof(buf)));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, buf, 0u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(NULL, buf, sizeof(buf)));
}

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_recovery_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (compile/link qualification, NEVER run in
 * package 1.2). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_classify_unknown_never_guessed);
    RUN_TEST(test_classify_normal);
    RUN_TEST(test_classify_download);
    RUN_TEST(test_classify_usb_jtag);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_zeroes);
    RUN_TEST(test_identity_format_exact);
    RUN_TEST(test_identity_format_minimal);
    RUN_TEST(test_identity_absent_tokens_omitted);
    RUN_TEST(test_identity_mac_tail_only);
    RUN_TEST(test_identity_rejects_unchecked_mem);
    RUN_TEST(test_identity_buffers);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_classify_unknown_never_guessed);
    RUN_TEST(test_classify_normal);
    RUN_TEST(test_classify_download);
    RUN_TEST(test_classify_usb_jtag);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_zeroes);
    RUN_TEST(test_identity_format_exact);
    RUN_TEST(test_identity_format_minimal);
    RUN_TEST(test_identity_absent_tokens_omitted);
    RUN_TEST(test_identity_mac_tail_only);
    RUN_TEST(test_identity_rejects_unchecked_mem);
    RUN_TEST(test_identity_buffers);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
