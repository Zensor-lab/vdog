/*
 * Host (native environment) tests for the vdog portable recovery/identity
 * core (package 1.2, plan A4). Run with: pio test -d firmware -e native
 * (HOST evidence only).
 *
 * Pins plan 1.2 acceptance 5: the boot classifier accepts ONLY recognized
 * ROM forms whose mode token is in the closed sets (console prose that
 * merely contains "download"/"basic" stays UNKNOWN — PR-review round 1),
 * the revision decodes as major*100+minor, and the identity line can only
 * ever render setter-validated, closed-set content — no full MAC, no eFuse
 * raw values, no caller-controlled text.
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

/* ---- boot-mode classification (A2, documented ROM forms only — round 2) - */

static void test_classify_never_guesses(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(""));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("hello world"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("ets Jul 29 2019 12:21:46"));
    /* Prose containing the magic words is NOT a ROM boot form. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("download failed"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("basic settings loaded"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("Download Mode"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("usb_jtag download mode"));
    /* Round-2 High finding: "reboot:" contains "boot:" as a SUBSTRING —
     * word-boundary matching keeps this UNKNOWN. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("reboot: download failed"));
    /* Malformed lookalikes: the documented form is boot:0xNN (DESCRIPTION)
     * — missing hex, missing parentheses, or empty DESCRIPTION fail. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot: download"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x3 DOWNLOAD_BOOT"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x(DOWNLOAD_BOOT(UART0))"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x3()"));
    /* "boot:" preceded by a token character is not a word start. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "Aboot:0x3 (SPI_FAST_FLASH_BOOT)"));
    /* Documented UNSUPPORTED modes: neither normal, download, nor
     * usb-jtag -> UNKNOWN (exact-token closed sets). */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "rst:0x8 (RCONS),boot:0x1 (SPI_FLASH_BOOT)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x2 (ATE_BOOT)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "boot:0x4 (SDIO_REI_FEO_V1_BOOT)"));
    /* Invented tokens stay out too (round 2: documented tokens ONLY). */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x2(not_a_mode)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x13(spi_fast)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("booting from flash"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("ESP-ROM:esp32s3-20210327"));
}

static void test_classify_normal(void)
{
    /* The documented normal-boot line, verbatim form. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify(
                              "rst:0x3 (POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("boot:0x13 (SPI_FAST_FLASH_BOOT)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("boot:0x13(spi_fast_flash_boot)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify("BOOT:0x13 (SPI_FAST_FLASH_BOOT)"));
}

static void test_classify_download(void)
{
    /* The documented download-mode line, verbatim (round-2 probe). */
    TEST_ASSERT_EQUAL_INT(
        VDOG_BOOT_MODE_DOWNLOAD,
        vdog_recovery_classify(
            "rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))"));
    /* DOWNLOAD(USB/UART0): token is the word before the first inner '('. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify("boot:0x2 (DOWNLOAD(USB/UART0))"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify("boot:0x02(download_boot)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify(
                              "rst:0x1 (BOR_RESET),boot:0x3f (DOWNLOAD_BOOT(UART0))"));
}

static void test_classify_usb_jtag(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify(
                              "ESP-ROM:esp32s3-usb-jtag-20211025"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_USBJTAG,
                          vdog_recovery_classify(
                              "esp-rom:esp32s3-usb-jtag-20211025"));
    /* SUPPORTED SHAPE ONLY (round-3 review): marker prose without the
     * documented banner shape stays UNKNOWN. */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "ESP-ROM:esp32s3-usb-jtag download"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("ESP-ROM:esp32s3-usb-jtag"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "ESP-ROM:esp32s3-usb-jtag-20211025 extra"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "ESP-ROM:prefix esp32s3-usb-jtag-20211025"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("ESP-ROM:esp32s3-20210327"));
    /* Not documented inside boot-words: a usb_jtag token WITHOUT a ROM
     * banner form is not classified (round 2). */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x2(usb_jtag)"));
}

/* Round-3 High finding: truncated or malformed descriptions must never
 * become recovery evidence — the COMPLETE supported description matches,
 * including balanced parentheses and nothing after them. */
static void test_classify_rejects_truncation_and_prose(void)
{
    /* truncations of each valid form */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x3 (DOWNLOAD"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x3 (SPI_FAST_FLASH_BOOT"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2"));
    /* only one of the two closing parens present */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "boot:0x3 (DOWNLOAD_BOOT(UART0)"));
    /* prose appended after the leading token */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "boot:0x8 (SPI_FAST_FLASH_BOOT failed)"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify("boot:0x3 (DOWNLOAD more text)"));
    /* prose appended after the closed group */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_UNKNOWN,
                          vdog_recovery_classify(
                              "boot:0x3 (SPI_FAST_FLASH_BOOT) followed by junk"));
    /* the un-truncated forms still classify (positive control) */
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_DOWNLOAD,
                          vdog_recovery_classify(
                              "boot:0x3 (DOWNLOAD_BOOT(UART0))"));
    TEST_ASSERT_EQUAL_INT(VDOG_BOOT_MODE_NORMAL,
                          vdog_recovery_classify(
                              "boot:0x3 (SPI_FAST_FLASH_BOOT)  ")); /* trailing spaces OK */
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

/* ---- sanitized identity (A2, acceptance 5 — setter-only text) ----------- */

static vdog_identity_t baseline_identity(void)
{
    vdog_identity_t id;
    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_chip_model(&id, "esp32s3"));
    vdog_identity_set_revision(&id, 2u); /* 0*100+2 -> 0.2 */
    fill_baseline_mem(&id.mem);
    id.mem_valid = 1u;
    id.mac_tail = 0xABCDu;
    id.mac_valid = 1u;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdog-pa-01"));
    return id;
}

static void test_identity_init_zeroes(void)
{
    vdog_identity_t id;
    memset(&id, 0xA5, sizeof(id));
    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mac_valid);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mem_valid);
    TEST_ASSERT_EQUAL_UINT8(0u, id.tag_len);
    TEST_ASSERT_EQUAL_INT(VDOG_IDENTITY_CHIP_UNKNOWN, id.chip);
}

static void test_chip_model_closed_set(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_chip_model(&id, "esp32s3"));
    TEST_ASSERT_EQUAL_INT(VDOG_IDENTITY_CHIP_ESP32S3, id.chip);
    /* Case-insensitive acceptance of the whitelisted name. */
    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_chip_model(&id, "ESP32S3"));
    /* Unlisted text is REJECTED and clears to the closed-set "unknown" —
     * it can never be echoed (PR-review round 1 Medium finding). */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_chip_model(
                              &id, "esp32s3\"; DROP TABLE"));
    TEST_ASSERT_EQUAL_INT(VDOG_IDENTITY_CHIP_UNKNOWN, id.chip);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_chip_model(&id, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_IDENTITY_CHIP_UNKNOWN, id.chip);
}

static void test_revision_decimal_decode(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);
    vdog_identity_set_revision(&id, 0u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);

    vdog_identity_set_revision(&id, 2u); /* SDK 0.2 */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.2", buf);

    /* PR-review round 1 Medium finding: byte-split rendered 102 as 0.102. */
    vdog_identity_set_revision(&id, 102u); /* SDK 1.2 */
    TEST_ASSERT_EQUAL_UINT8(1u, id.chip_major);
    TEST_ASSERT_EQUAL_UINT8(2u, id.chip_minor);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=1.2", buf);

    vdog_identity_set_revision(&id, 202u); /* SDK 2.2 */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=2.2", buf);
}

static void test_board_tag_validator(void)
{
    vdog_identity_t id;
    char buf[256];
    char long17[18];
    static const char max16[] = "abcdefghijklmnop"; /* 'p' is non-hex */
    static const char hex12[] = "1a2b3c4d5e6f";     /* compact MAC    */
    static const char hex16[] = "0123456789abcdef";

    memset(long17, 'a', 17);
    long17[17] = '\0';

    vdog_identity_init(&id);
    /* Round-2 Medium findings: BOTH MAC spellings rejected — the
     * colon-delimited form via the charset, the delimiter-free compact
     * MAC (and any pure-hex label) via the hex rule. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "1a:2b:3c:4d:5e:6f"));
    TEST_ASSERT_EQUAL_UINT8(0u, id.tag_len);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, hex12));
    TEST_ASSERT_EQUAL_UINT8(0u, id.tag_len);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, hex16));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "deadbeef"));
    /* Round-3 Medium: separator-normalized MAC shapes — dots/dashes are
     * legal in the charset, so strip . _ - and reject bare 48/64-bit hex
     * addresses. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "0200.0000.0001"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "1a-2b-3c-4d-5e-6f"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "0200.0000.0000.0001"));
    /* non-MAC-shaped labels with the same separators remain legal */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "dev.01"));
    TEST_ASSERT_EQUAL_UINT8(6u, id.tag_len);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "bad%tag"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "%s%s%s%n"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, long17));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, NULL));
    /* Round-2 Medium (overflow): the MAXIMUM accepted length must store 16
     * bytes AND its terminator inside the array. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, max16));
    TEST_ASSERT_EQUAL_UINT8(16u, id.tag_len);
    TEST_ASSERT_EQUAL_UINT(17u, sizeof(id.tag)); /* +1 terminator slot    */
    TEST_ASSERT_EQUAL_CHAR('\0', id.tag[16]);    /* terminator in bounds */
    TEST_ASSERT_EQUAL_STRING(max16, id.tag);
    /* A valid tag set earlier survives a rejected attempt (unchanged). */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(&id, "no spaces ok"));
    TEST_ASSERT_EQUAL_STRING(max16, id.tag);
    /* Legitimate opaque labels (contain a non-hex letter or separator). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdog-pa-01"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0 board=vdog-pa-01", buf);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "dev01"));
    /* Clearing is legal. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, ""));
    TEST_ASSERT_EQUAL_UINT8(0u, id.tag_len);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
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
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_chip_model(&id, "esp32s3"));
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
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_chip_model(&id, "esp32s3"));
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
    RUN_TEST(test_classify_never_guesses);
    RUN_TEST(test_classify_normal);
    RUN_TEST(test_classify_download);
    RUN_TEST(test_classify_usb_jtag);
    RUN_TEST(test_classify_rejects_truncation_and_prose);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_zeroes);
    RUN_TEST(test_chip_model_closed_set);
    RUN_TEST(test_revision_decimal_decode);
    RUN_TEST(test_board_tag_validator);
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
    RUN_TEST(test_classify_never_guesses);
    RUN_TEST(test_classify_normal);
    RUN_TEST(test_classify_download);
    RUN_TEST(test_classify_usb_jtag);
    RUN_TEST(test_classify_rejects_truncation_and_prose);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_zeroes);
    RUN_TEST(test_chip_model_closed_set);
    RUN_TEST(test_revision_decimal_decode);
    RUN_TEST(test_board_tag_validator);
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
