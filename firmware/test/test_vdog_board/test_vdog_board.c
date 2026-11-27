/*
 * Host (native environment) tests for the vdog portable board-profile core.
 * Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases are the "unsupported board / silently defaulted setting fails
 * clearly" logic of plan 1.1 §4.1/§7.2: every failure mode pins BOTH its
 * exact error code and its exact offending field name. No device is involved.
 */
#include <string.h>

#include "unity.h"
#include "vdog_board.h"
#include "vdog_core.h"

#define EXPECTED_REPORT                                                          \
    "vdog 0.2.0-proto board=seeed_xiao_esp32s3 target=esp32s3 "                 \
    "flash=8MB-qio-80m psram=8MB-opi-80m"

void setUp(void) {}
void tearDown(void) {}

static vdog_board_profile_t expected_ok(void)
{
    return vdog_board_expected_profile_proto();
}

/* Assert the gate accepts the expected-provisional profile. */
static void test_validate_accepts_expected_profile(void)
{
    vdog_board_profile_t p = expected_ok();

    TEST_ASSERT_EQUAL_UINT32(VDOG_BOARD_FIELD_ALL, p.field_set);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_board_validate(&p));
    TEST_ASSERT_NULL(vdog_board_error_field());
}

static void test_profile_init_marks_nothing(void)
{
    vdog_board_profile_t p;

    memset(&p, 0xA5, sizeof(p));
    vdog_board_profile_init(&p);
    TEST_ASSERT_EQUAL_UINT32(0u, p.field_set);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOARD_TARGET_UNKNOWN, p.target);
    TEST_ASSERT_NULL(p.board_id);
    TEST_ASSERT_EQUAL_UINT32(0u, p.flash_size_bytes);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOARD_FLASH_MODE_UNKNOWN, p.flash_mode);
    TEST_ASSERT_EQUAL_UINT16(0u, p.flash_freq_mhz);
    TEST_ASSERT_EQUAL_UINT8(0u, p.psram_present);
    TEST_ASSERT_EQUAL_UINT32(0u, p.psram_size_bytes);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOARD_PSRAM_MODE_UNKNOWN, p.psram_mode);
    TEST_ASSERT_EQUAL_UINT16(0u, p.psram_speed_mhz);
    TEST_ASSERT_NULL(p.partition_table);
    /* Never configured != configured wrong: a blank profile is rejected as
     * missing, never as a wrong value and never accepted on defaults. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("target", vdog_board_error_field());
}

/* A never-configured key must be reported as MISSING, field by field. */
static void test_validate_rejects_each_missing_field(void)
{
    struct {
        uint32_t bit;
        const char *field;
    } cases[] = {
        {VDOG_BOARD_FIELD_TARGET, "target"},
        {VDOG_BOARD_FIELD_BOARD_ID, "board_id"},
        {VDOG_BOARD_FIELD_FLASH_SIZE, "flash_size_bytes"},
        {VDOG_BOARD_FIELD_FLASH_MODE, "flash_mode"},
        {VDOG_BOARD_FIELD_FLASH_FREQ, "flash_freq_mhz"},
        {VDOG_BOARD_FIELD_PSRAM_PRESENT, "psram_present"},
        {VDOG_BOARD_FIELD_PSRAM_SIZE, "psram_size_bytes"},
        {VDOG_BOARD_FIELD_PSRAM_MODE, "psram_mode"},
        {VDOG_BOARD_FIELD_PSRAM_SPEED, "psram_speed_mhz"},
        {VDOG_BOARD_FIELD_PARTITION_TABLE, "partition_table"},
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(10u, (unsigned)(sizeof(cases) / sizeof(cases[0])));
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        vdog_board_profile_t p = expected_ok();
        p.field_set &= ~cases[i].bit;
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_ERR_BOARD_MISSING_FIELD,
                                      vdog_board_validate(&p), cases[i].field);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(cases[i].field,
                                         vdog_board_error_field(), cases[i].field);
    }
}

/* NULL argument. */
static void test_validate_rejects_null_profile(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG, vdog_board_validate(NULL));
    TEST_ASSERT_EQUAL_STRING("profile", vdog_board_error_field());
}

/* An unknown field_set bit is a caller bug: it must be rejected and named,
 * never silently ignored (core/vdog_board.c unknown-bit branch). */
static void test_validate_rejects_unknown_field_set_bit(void)
{
    vdog_board_profile_t p = expected_ok();

    /* All real fields set + one unknown bit -> named as field_set. */
    p.field_set |= 0x80000000u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("field_set", vdog_board_error_field());

    p = expected_ok();
    p.field_set |= (VDOG_BOARD_FIELD_ALL << 1);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("field_set", vdog_board_error_field());

    /* A required field missing outranks the unknown bit: pass 1 runs first,
     * so the diagnosis is the unconfigured field, not field_set. */
    vdog_board_profile_init(&p);
    p.field_set = 0x10000000u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("target", vdog_board_error_field());
}

/* Wrong values (field IS set) must be a specific area error, not "missing". */
static void test_validate_rejects_unsupported_target_and_board(void)
{
    vdog_board_profile_t p = expected_ok();

    p.target = VDOG_BOARD_TARGET_UNKNOWN; /* explicitly set to a bad value */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_UNSUPPORTED_TARGET,
                          vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("target", vdog_board_error_field());

    p = expected_ok();
    p.target = 99u; /* e.g. esp32 / esp32c3 shape: not the prototype chip */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_UNSUPPORTED_TARGET,
                          vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("target", vdog_board_error_field());

    /* Unsupported BOARD (right chip, wrong board identity). */
    p = expected_ok();
    p.board_id = "espressif_esp32s3_devkitm_1";
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_UNSUPPORTED_TARGET,
                          vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("board_id", vdog_board_error_field());

    /* Empty board id is not "absent": it is a wrong value. */
    p = expected_ok();
    p.board_id = "";
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_UNSUPPORTED_TARGET,
                          vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("board_id", vdog_board_error_field());
}

static void test_validate_rejects_flash_variants(void)
{
    vdog_board_profile_t p = expected_ok();

    /* 4MB instead of 8MB: a silently inherited smaller flash fails here. */
    p.flash_size_bytes = 4u * 1024u * 1024u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_FLASH, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_board_error_field());

    p = expected_ok();
    p.flash_mode = VDOG_BOARD_FLASH_MODE_DIO; /* not the QIO prototype */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_FLASH, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_board_error_field());

    p = expected_ok();
    p.flash_mode = VDOG_BOARD_FLASH_MODE_QOUT;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_FLASH, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_board_error_field());

    p = expected_ok();
    p.flash_freq_mhz = 40u; /* 80 MHz is required */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_FLASH, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("flash_freq_mhz", vdog_board_error_field());
}

static void test_validate_rejects_psram_variants(void)
{
    vdog_board_profile_t p = expected_ok();

    /* PSRAM declared ABSENT (field set, value 0) — distinct from unset. */
    p.psram_present = 0u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_present", vdog_board_error_field());

    p = expected_ok();
    p.psram_size_bytes = 16u * 1024u * 1024u; /* N16R8-shaped, wrong */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_board_error_field());

    p = expected_ok();
    p.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI; /* quad, not octal/OPI */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_board_error_field());

    p = expected_ok();
    p.psram_speed_mhz = 40u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_speed_mhz", vdog_board_error_field());
}

static void test_validate_rejects_partitions_variant(void)
{
    vdog_board_profile_t p = expected_ok();

    p.partition_table = "partitions/default_8MB.csv"; /* not the vdog table */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PARTITIONS, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("partition_table", vdog_board_error_field());

    p = expected_ok();
    p.partition_table = "";
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PARTITIONS, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("partition_table", vdog_board_error_field());
}

/* Semantics pinned by §7.3: missing-field beats wrong-value, and the FIRST
 * field in declaration order wins so the diagnosis is deterministic. */
static void test_validate_missing_field_outranks_wrong_value(void)
{
    vdog_board_profile_t p = expected_ok();

    p.flash_size_bytes = 2u * 1024u * 1024u; /* wrong value ...            */
    p.field_set &= ~VDOG_BOARD_FIELD_PSRAM_MODE; /* ... plus missing field */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_board_error_field());

    /* Two wrong areas: the field declared earlier wins (psram_mode before
     * partition_table), and it is a value error, never "missing". */
    p = expected_ok();
    p.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    p.partition_table = "partitions/default_8MB.csv";
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_board_error_field());

    /* error_field is per-call: a later success clears it, a later failure
     * replaces it (main.c reads it immediately after its own call). */
    p = expected_ok();
    p.partition_table = "partitions/default_8MB.csv";
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PARTITIONS, vdog_board_validate(&p));
    TEST_ASSERT_EQUAL_STRING("partition_table", vdog_board_error_field());
    p.partition_table = VDOG_BOARD_EXPECTED_PARTITION_TABLE;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_board_validate(&p));
    TEST_ASSERT_NULL(vdog_board_error_field());
}

/* ---- report string: exact match, exact fit, too small, NULL ---- */
static void test_report_exact_string(void)
{
    vdog_board_profile_t p = expected_ok();
    char buf[160];

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_board_report(&p, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_REPORT, buf);
    TEST_ASSERT_NULL(vdog_board_error_field());
    /* Semantic version stays separate from build identity (spec §10): the
     * report starts with exactly the vdog_format_version() string. */
    {
        char version[64];
        const size_t vlen = strlen("vdog 0.2.0-proto");

        TEST_ASSERT_EQUAL_INT(VDOG_OK,
                              vdog_format_version(version, sizeof(version)));
        TEST_ASSERT_EQUAL_STRING("vdog 0.2.0-proto", version);
        TEST_ASSERT_EQUAL_STRING_LEN(version, buf, vlen);
        TEST_ASSERT_EQUAL_CHAR(' ', buf[vlen]);
    }
}

static void test_report_exact_fit(void)
{
    vdog_board_profile_t p = expected_ok();
    char buf[160];
    const size_t exact = strlen(EXPECTED_REPORT) + 1u;

    memset(buf, 0xAA, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_board_report(&p, buf, exact));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_REPORT, buf);
    /* Nothing past the NUL was touched by the caller-visible contract. */
    TEST_ASSERT_EQUAL_UINT8(0u, buf[exact - 1u]);
}

static void test_report_rejects_too_small_and_null(void)
{
    vdog_board_profile_t p = expected_ok();
    char buf[160];
    const size_t exact = strlen(EXPECTED_REPORT) + 1u;

    /* One byte short of the NUL, and everything below it. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_board_report(&p, buf, exact - 1u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_board_report(&p, buf, 5u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_board_report(&p, buf, 0u));

    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_board_report(&p, NULL, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("buf", vdog_board_error_field());

    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_board_report(NULL, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("profile", vdog_board_error_field());
}

/* A profile the gate rejects must never be printable as a healthy line. */
static void test_report_refuses_rejected_profile(void)
{
    vdog_board_profile_t p = expected_ok();
    char buf[160];

    p.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI; /* quad instead of octal */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_PSRAM, vdog_board_report(&p, buf,
                                                                  sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_board_error_field());

    p = expected_ok();
    p.field_set &= ~VDOG_BOARD_FIELD_PSRAM_SIZE; /* silently defaulted */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BOARD_MISSING_FIELD,
                          vdog_board_report(&p, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_board_error_field());

    /* Argument order: a NULL buffer is an argument error even for a bad
     * profile, and bufsize 0 is reported as too small before validating. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_board_report(&p, NULL, sizeof(buf)));
    p = expected_ok();
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_board_report(&p, buf, 0u));
}

/* Crosses the C/C++ link boundary: vdog_board_cpp_smoke() is DEFINED in C++
 * (cpp_smoke_board.cpp) with extern "C" linkage and called from this C TU, so
 * linking the native test binary proves the new header's guard is effective. */
extern int vdog_board_cpp_smoke(void);

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_board_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (`pio test -e vdog_xiao_sense_proto
 * --without-uploading --without-testing`): PlatformIO excludes src/main.c
 * from __test builds, ESP-IDF's esp_system provides main(), and FreeRTOS
 * calls app_main(). These tests are NEVER executed at package 1.1 — no
 * upload, no run — this entry point only proves compile/link qualification.
 * Host execution is `pio test -e native` (HOST evidence). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_validate_accepts_expected_profile);
    RUN_TEST(test_profile_init_marks_nothing);
    RUN_TEST(test_validate_rejects_each_missing_field);
    RUN_TEST(test_validate_rejects_null_profile);
    RUN_TEST(test_validate_rejects_unknown_field_set_bit);
    RUN_TEST(test_validate_rejects_unsupported_target_and_board);
    RUN_TEST(test_validate_rejects_flash_variants);
    RUN_TEST(test_validate_rejects_psram_variants);
    RUN_TEST(test_validate_rejects_partitions_variant);
    RUN_TEST(test_validate_missing_field_outranks_wrong_value);
    RUN_TEST(test_report_exact_string);
    RUN_TEST(test_report_exact_fit);
    RUN_TEST(test_report_rejects_too_small_and_null);
    RUN_TEST(test_report_refuses_rejected_profile);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_validate_accepts_expected_profile);
    RUN_TEST(test_profile_init_marks_nothing);
    RUN_TEST(test_validate_rejects_each_missing_field);
    RUN_TEST(test_validate_rejects_null_profile);
    RUN_TEST(test_validate_rejects_unknown_field_set_bit);
    RUN_TEST(test_validate_rejects_unsupported_target_and_board);
    RUN_TEST(test_validate_rejects_flash_variants);
    RUN_TEST(test_validate_rejects_psram_variants);
    RUN_TEST(test_validate_rejects_partitions_variant);
    RUN_TEST(test_validate_missing_field_outranks_wrong_value);
    RUN_TEST(test_report_exact_string);
    RUN_TEST(test_report_exact_fit);
    RUN_TEST(test_report_rejects_too_small_and_null);
    RUN_TEST(test_report_refuses_rejected_profile);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
