/*
 * Host (native environment) tests for the vdog portable recovery/identity
 * core. Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases pin plan 1.2 A2/§A4: ROM-line boot-mode classification by
 * COMPLETE banner FORM only (review M-C — prefix-anchored "boot:0x<hex>
 * (<banner>)" plus closed whole-word sets; prose that merely CONTAINS
 * tokens and truncated lookalikes stay UNKNOWN, never guessed), and the
 * sanitized identity line where the MAC appears ONLY as its last-two-octet
 * tail — the struct cannot store a full MAC, the chip model is a CLOSED
 * enum and the board tag is validated at set time and re-validated with a
 * bounded scan at render time (review M-D). No device.
 */
#include <string.h>

#include "unity.h"
#include "vdog_core.h"
#include "vdog_mem.h"
#include "vdog_recovery.h"

void setUp(void) {}
void tearDown(void) {}

/* ---- boot-mode classification (review M-C: whole forms only) -------------- */

static void test_classify_normal_boot_lines(void)
{
    /* Genuine ROM SPI-boot banners (esptool boot-mode doc forms). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x27 (SPI_FAST_FLASH_BOOT)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x2 (spi_fast_flash)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x1 (SPI_BOOT)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x5 (SPI_FLASH_BOOT)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x1 (basic)"));
    /* Leading/trailing blanks are padding, not content. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("  boot:0x27 (SPI_FAST_FLASH_BOOT) "));
}

static void test_classify_download_boot_lines(void)
{
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0xf (DOWNLOAD(USB/UART0))"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0x7 (UART_DOWNLOAD)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0x6 (SDIO_DOWNLOAD)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0x3 (DOWNLOAD)"));
    /* Documented priority: "spi_fast_download" is a DOWNLOAD form, checked
     * BEFORE the normal-boot words. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0x8 (SPI_FAST_DOWNLOAD)"));
}

static void test_classify_usb_jtag_boot_lines(void)
{
    /* USB-Serial-JTAG is checked FIRST: a JTAG-path download banner is
     * labelled USBJTAG, never plain DOWNLOAD. Hyphen spelling matches the
     * underscored word (whole-token equality after normalisation). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_USBJTAG,
                            vdog_recovery_classify("boot:0x1 (USB_JTAG)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_USBJTAG,
                            vdog_recovery_classify("boot:0x1 (USB-JTAG/serial)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_USBJTAG,
                            vdog_recovery_classify("boot:0xf (USB_SERIAL_JTAG)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_USBJTAG,
                            vdog_recovery_classify("boot:0x9 (USB_JTAG_DOWNLOAD)"));
}

static void test_classify_unknown_never_guessed(void)
{
    /* NULL/empty and unrelated prose. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify(NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify(""));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("ets Jun  2 2021 h:0"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("invalid header magic 0xffffffff"));
    /* Review M-C: prose MERELY CONTAINING tokens is not a ROM banner.
     * (Part B still records every such line verbatim; it just is not
     * classified.) */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("download failed"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot loader"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("fast pattern"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("Waiting for bit flip in download mode"));
    /* Truncated / near-miss lookalikes of the anchored form. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("spi_fas"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x27"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x2 (spi_fast_flash_boot"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0xzz (spi_fast_flash_boot)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x2 (spi_fas)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x2 (usb_jtag) trailing junk"));
    /* A well-formed banner with an UNRECOGNISED word is UNKNOWN, never a
     * guess from the nearest class. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x4 (SOMETHING_NEW)"));
}

static void test_boot_mode_names(void)
{
    TEST_ASSERT_EQUAL_STRING("unknown",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_UNKNOWN));
    TEST_ASSERT_EQUAL_STRING("normal",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_NORMAL));
    TEST_ASSERT_EQUAL_STRING("download",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_DOWNLOAD));
    TEST_ASSERT_EQUAL_STRING("usbjtag",
                             vdog_boot_mode_name(VDOG_BOOT_MODE_USBJTAG));
    /* Out-of-range values collapse to "unknown", never crash. */
    TEST_ASSERT_EQUAL_STRING("unknown",
                             vdog_boot_mode_name((vdog_boot_mode_t)42));
}

/* ---- sanitized identity ------------------------------------------------------ */

/* Identity with every part present, built through the validated setters. */
static vdog_identity_t full_identity(void)
{
    vdog_identity_t id;

    vdog_identity_init(&id);
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
    id.chip_major = 0u;
    id.chip_minor = 2u;
    id.mem.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    id.mem.flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    id.mem.flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    id.mem.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    id.mem.flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    id.mem.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    id.mem.psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    id.mem.psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    id.mem.psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    id.mem.psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    id.mem.psram_mode = VDOG_BOARD_PSRAM_MODE_OPI;
    id.mem.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    id.mem.psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    id.mem.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    id.mem.field_set = VDOG_MEM_FIELD_ALL;
    id.mem_valid = 1u;
    id.mac_tail = 0xABCDu;
    id.mac_valid = 1u;
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "proto-a1"));
    return id;
}

static void test_identity_init_marks_nothing(void)
{
    vdog_identity_t id;
    char buf[256];

    memset(&id, 0xA5, sizeof(id));
    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_UINT8((uint8_t)VDOG_IDENTITY_CHIP_UNKNOWN,
                            (uint8_t)id.chip_model);
    TEST_ASSERT_EQUAL_CHAR('\0', id.board_tag[0]);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mem_valid);
    TEST_ASSERT_EQUAL_UINT8(0u, id.mac_valid);
    TEST_ASSERT_EQUAL_UINT16(0u, id.mac_tail);
    /* An identity with nothing set renders only the bare chip/rev head —
     * absent parts are never fabricated. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);
}

static void test_identity_exact_line(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(
        "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] "
        "mac=**:**:**:**:ab:cd board=proto-a1",
        buf);
}

/* THE sanitizer proof (plan 1.2 acceptance 5): the struct stores ONLY a
 * 16-bit tail, and the line can only ever contain the last two octets.
 * Review M-D: the chip model is an ENUM (no caller string can reach the
 * render), and the board tag array is bounded + validated. */
static void test_identity_mac_storage_cannot_hold_a_full_mac(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];

    TEST_ASSERT_EQUAL_UINT(2u, (unsigned)sizeof(((vdog_identity_t *)0)->mac_tail));

    /* Even if a caller tried to leak the whole MAC through every member,
     * the render contains exactly the masked-tail pattern and nothing
     * resembling the first four octets. */
    id.mac_tail = 0x1A2Bu;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NOT_NULL(strstr(buf, "mac=**:**:**:**:1a:2b"));
    TEST_ASSERT_NULL(strstr(buf, "1a:2b:")); /* tail octets are the last group */

    /* The model field is the closed enum type, not a char array: there is
     * no member into which a "model" string could ever be written. */
    TEST_ASSERT_EQUAL_UINT(sizeof(vdog_identity_chip_t),
                           (unsigned)sizeof(id.chip_model));
    TEST_ASSERT_EQUAL_UINT(VDOG_IDENTITY_TAG_MAX,
                           (unsigned)sizeof(id.board_tag));
}

/* Review M-D: the render vocabulary is fixed internally. */
static void test_identity_chip_model_is_closed_set(void)
{
    vdog_identity_t id;
    char buf[64];

    vdog_identity_init(&id);
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=esp32s3 rev=0.0", buf);

    /* An out-of-range enum value (e.g. through uninitialized memory)
     * collapses to the fixed "unknown" spelling — never a caller string. */
    vdog_identity_set_chip_model(&id, (vdog_identity_chip_t)99);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);
    TEST_ASSERT_EQUAL_UINT8((uint8_t)VDOG_IDENTITY_CHIP_UNKNOWN,
                            (uint8_t)id.chip_model);

    /* NULL id is a documented no-op. */
    vdog_identity_set_chip_model(NULL, VDOG_IDENTITY_CHIP_ESP32S3);

    /* The compact MAC a caller might have "typed in as a model" is
     * impossible by construction: the setter takes an enum. */
}

/* Review M-D: the board tag is validated at SET time with a specific
 * error; rejected content is never stored and never rendered. */
static void test_identity_board_tag_validation(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);

    /* A compact 12-hex-digit MAC (with or without case play) is rejected:
     * the tag channel can never carry a MAC. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "abcdef012345"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "ABCDEF012345"));
    TEST_ASSERT_EQUAL_CHAR('\0', id.board_tag[0]); /* never half-stored */

    /* Charset [A-Za-z0-9_-] only. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "bad tag"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "bad:tag"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "tag.bin"));
    /* An 11-hex or 13-hex label is NOT the compact-MAC shape and passes
     * the charset rule. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "abcdef01234"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "abcdef0123456"));

    /* Exact-fit boundary: 15 chars (capacity 16 including NUL) is
     * valid... */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "unit-proto-a-12"));
    TEST_ASSERT_EQUAL_STRING("unit-proto-a-12", id.board_tag);
    /* ...16 chars (no room for the NUL) is not. */
    {
        char too_long[VDOG_IDENTITY_TAG_MAX + 1u];
        memset(too_long, 'x', sizeof(too_long) - 1u);
        too_long[sizeof(too_long) - 1u] = '\0'; /* 16 'x' + NUL */
        TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                              vdog_identity_set_board_tag(&id, too_long));
    }
    /* An unterminated array within capacity is rejected via the bounded
     * scan (no out-of-bounds read, no store). */
    {
        char unterminated[VDOG_IDENTITY_TAG_MAX];
        memset(unterminated, 'a', sizeof(unterminated));
        TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                              vdog_identity_set_board_tag(&id, unterminated));
    }

    /* A rejected set attempt leaves the previously valid tag UNCHANGED. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "keep-me"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "no spaces here"));
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NOT_NULL(strstr(buf, "board=keep-me"));

    /* NULL/"" clear the tag; the board= section then disappears. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, ""));
    /* NULL id is the invalid-arg case. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(NULL, "x"));
}

/* Review M-D defense in depth: bytes that bypassed the setter (raw
 * struct writes) are still never rendered — the formatter re-validates
 * with a bounded scan and omits an invalid tag entirely. */
static void test_identity_render_never_emits_unvalidated_bytes(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);

    /* Compact-MAC bytes smuggled straight into the array: not rendered. */
    memcpy(id.board_tag, "abcdef012345", 13u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_NULL(strstr(buf, "abcdef012345"));

    /* Unterminated garbage: bounded scan, no crash, nothing rendered. */
    memset(id.board_tag, 'A', sizeof(id.board_tag));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_NULL(strstr(buf, "AAAA"));

    /* Charset violation: same omission. */
    memcpy(id.board_tag, "ok tag", 7u); /* space is outside the charset */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
}

/* Review F-2: the SDK chip-info revision is DECIMAL MXX (major*100 + minor,
 * esp_chip_info.h:53 wording). Table-pinned decode (helper lives in the
 * portable core so the host suite reaches it): a byte split would render
 * S3 v1.1 (raw 101) as the nonsense 0.101. */
static void test_identity_revision_mxx_decode(void)
{
    static const struct {
        uint16_t mxx;
        uint8_t major;
        uint8_t minor;
    } cases[] = {
        {0u, 0u, 0u},   /* v0.0   */
        {2u, 0u, 2u},   /* v0.2   */
        {100u, 1u, 0u}, /* v1.0   */
        {101u, 1u, 1u}, /* v1.1   */
        {201u, 2u, 1u}, /* v2.1   */
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(5u, (unsigned)(sizeof(cases) / sizeof(cases[0])));
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        vdog_identity_t id;

        vdog_identity_init(&id);
        vdog_identity_set_revision_mxx(&id, cases[i].mxx);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(cases[i].major, id.chip_major,
                                        "MXX major");
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(cases[i].minor, id.chip_minor,
                                        "MXX minor");
    }

    /* End-to-end: the rendered line carries the decoded pair (this is the
     * chip=...rev=... field Part B transcribes into the identity record). */
    {
        vdog_identity_t id;
        char buf[64];

        vdog_identity_init(&id);
        vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
        vdog_identity_set_revision_mxx(&id, 101u);
        TEST_ASSERT_EQUAL_INT(VDOG_OK,
                              vdog_identity_format(&id, buf, sizeof(buf)));
        TEST_ASSERT_EQUAL_STRING("chip=esp32s3 rev=1.1", buf);
    }

    /* NULL is a no-op (documented). */
    vdog_identity_set_revision_mxx(NULL, 101u);
}

/* Unset pieces stay out of the line (never invented). */
static void test_identity_absent_parts(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];

    id.mac_valid = 0u; /* MAC never read: no mac= section at all */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(
        "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] "
        "board=proto-a1",
        buf);

    id = full_identity();
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));

    id = full_identity();
    id.mem_valid = 0u; /* mem not baseline-checked: no mem= section */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "mem="));
}

/* "Never render a rejected set": mem_valid claiming a NON-baseline memory
 * set (quad PSRAM) makes the whole line refuse with INVALID_ARG. */
static void test_identity_refuses_rejected_mem_set(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];

    id.mem.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI; /* quad-only board */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, buf, sizeof(buf)));

    /* A missing (never probed) field in the embedded detector also
     * refuses the line. */
    id = full_identity();
    id.mem.field_set &= ~VDOG_MEM_FIELD_PSRAM_SIZE;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, buf, sizeof(buf)));
}

/* Buffer/NUL semantics. */
static void test_identity_buffer_semantics(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];
    const char *expected =
        "chip=esp32s3 rev=0.2 mem=8MB-flash/8MB-psram[opi-configured] "
        "mac=**:**:**:**:ab:cd board=proto-a1";
    const size_t exact = strlen(expected) + 1u;

    memset(buf, 0xAA, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, exact));
    TEST_ASSERT_EQUAL_STRING(expected, buf);
    TEST_ASSERT_EQUAL_CHAR('\0', buf[exact - 1u]);

    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_identity_format(&id, buf, exact - 1u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_identity_format(&id, buf, 16u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, buf, 0u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(&id, NULL, sizeof(buf)));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_format(NULL, buf, sizeof(buf)));
}

/* Crosses the C/C++ link boundary: vdog_recovery_cpp_smoke() is DEFINED in
 * C++ (cpp_smoke_recovery.cpp) with extern "C" linkage and called from this
 * C TU. */
extern int vdog_recovery_cpp_smoke(void);

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_recovery_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (`pio test -e vdog_xiao_sense_proto
 * --without-uploading --without-testing`): compile/link qualification ONLY;
 * never executed in package 1.2 Part A. */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_classify_normal_boot_lines);
    RUN_TEST(test_classify_download_boot_lines);
    RUN_TEST(test_classify_usb_jtag_boot_lines);
    RUN_TEST(test_classify_unknown_never_guessed);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_marks_nothing);
    RUN_TEST(test_identity_exact_line);
    RUN_TEST(test_identity_chip_model_is_closed_set);
    RUN_TEST(test_identity_board_tag_validation);
    RUN_TEST(test_identity_render_never_emits_unvalidated_bytes);
    RUN_TEST(test_identity_revision_mxx_decode);
    RUN_TEST(test_identity_mac_storage_cannot_hold_a_full_mac);
    RUN_TEST(test_identity_absent_parts);
    RUN_TEST(test_identity_refuses_rejected_mem_set);
    RUN_TEST(test_identity_buffer_semantics);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_classify_normal_boot_lines);
    RUN_TEST(test_classify_download_boot_lines);
    RUN_TEST(test_classify_usb_jtag_boot_lines);
    RUN_TEST(test_classify_unknown_never_guessed);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_marks_nothing);
    RUN_TEST(test_identity_exact_line);
    RUN_TEST(test_identity_chip_model_is_closed_set);
    RUN_TEST(test_identity_board_tag_validation);
    RUN_TEST(test_identity_render_never_emits_unvalidated_bytes);
    RUN_TEST(test_identity_revision_mxx_decode);
    RUN_TEST(test_identity_mac_storage_cannot_hold_a_full_mac);
    RUN_TEST(test_identity_absent_parts);
    RUN_TEST(test_identity_refuses_rejected_mem_set);
    RUN_TEST(test_identity_buffer_semantics);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
