/*
 * Host (native environment) tests for the vdog portable memory-baseline
 * core. Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases pin plan 1.2 A1/§A4: per-field MEASURED-vs-CONFIGURED source
 * tags (a CONFIGURED capacity NEVER satisfies the baseline, finding 2), the
 * fixed decision order (missing -> source -> value, each in declaration
 * order), the named wrong-board classes (4MB flash, no PSRAM, quad-only
 * PSRAM, Plus/N16R8-shaped 16MB), and the exact tagged render line — so a
 * configuration-only OPI can never print as detected. No device is involved.
 */
#include <string.h>

#include "unity.h"
#include "vdog_board.h"
#include "vdog_core.h"
#include "vdog_mem.h"

#define EXPECTED_MEM_LINE                                                        \
    "flash_size=8MB[measured] flash_mode=qio[configured] flash_freq=80m"         \
    "[configured] psram=8MB[measured:init-ok] psram_mode=opi[configured] "       \
    "psram_speed=80m[configured]"

void setUp(void) {}
void tearDown(void) {}

/* Fully probed detector matching the documented Sense baseline, with the
 * evidence tags the check REQUIRES: capacities/present MEASURED,
 * mode/frequency CONFIGURED (finding 2). */
static vdog_mem_detected_t expected_ok(void)
{
    vdog_mem_detected_t det;

    vdog_mem_detected_init(&det);
    det.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    det.flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    det.flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    det.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    det.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    det.psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    det.psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    det.psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    det.psram_mode = VDOG_MEM_BASELINE_PSRAM_MODE;
    det.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    det.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set = VDOG_MEM_FIELD_ALL;
    return det;
}

static void test_check_accepts_baseline_detector(void)
{
    vdog_mem_detected_t det = expected_ok();

    TEST_ASSERT_EQUAL_UINT32(VDOG_MEM_FIELD_ALL, det.field_set);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&det));
    TEST_ASSERT_NULL(vdog_mem_error_field());
}

static void test_detected_init_marks_nothing(void)
{
    vdog_mem_detected_t det;

    memset(&det, 0xA5, sizeof(det));
    vdog_mem_detected_init(&det);
    TEST_ASSERT_EQUAL_UINT32(0u, det.field_set);
    TEST_ASSERT_EQUAL_UINT32(0u, det.flash_size_bytes);
    TEST_ASSERT_EQUAL_UINT32(0u, det.psram_size_bytes);
    /* Never probed != probed as zero: a blank detector is MISSING, never
     * accepted on defaults and never reported as a wrong value. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD,
                          vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
}

/* Every field, when never probed, is named — field by field. */
static void test_check_rejects_each_missing_field(void)
{
    struct {
        uint32_t bit;
        const char *field;
    } cases[] = {
        {VDOG_MEM_FIELD_FLASH_SIZE, "flash_size_bytes"},
        {VDOG_MEM_FIELD_FLASH_MODE, "flash_mode"},
        {VDOG_MEM_FIELD_FLASH_FREQ, "flash_freq_mhz"},
        {VDOG_MEM_FIELD_PSRAM_PRESENT, "psram_present"},
        {VDOG_MEM_FIELD_PSRAM_SIZE, "psram_size_bytes"},
        {VDOG_MEM_FIELD_PSRAM_MODE, "psram_mode"},
        {VDOG_MEM_FIELD_PSRAM_SPEED, "psram_speed_mhz"},
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(7u, (unsigned)(sizeof(cases) / sizeof(cases[0])));
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        vdog_mem_detected_t det = expected_ok();
        det.field_set &= ~cases[i].bit;
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_ERR_MEM_MISSING_FIELD,
                                      vdog_mem_check_baseline(&det),
                                      cases[i].field);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(cases[i].field,
                                         vdog_mem_error_field(),
                                         cases[i].field);
    }
}

static void test_check_rejects_null_detector(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG, vdog_mem_check_baseline(NULL));
}

/* Evidence-source policy (finding 2), field by field: a capacity/present
 * tagged CONFIGURED, or a mode/frequency tagged MEASURED, is rejected as
 * SOURCE — never accepted, never demoted to a value error. */
static void test_check_enforces_source_policy_per_field(void)
{
    struct {
        vdog_mem_source_t wrong_tag;
        const char *field;
    } cases[] = {
        {VDOG_MEM_SOURCE_CONFIGURED, "flash_size_bytes"},
        {VDOG_MEM_SOURCE_MEASURED, "flash_mode"},
        {VDOG_MEM_SOURCE_MEASURED, "flash_freq_mhz"},
        {VDOG_MEM_SOURCE_CONFIGURED, "psram_present"},
        {VDOG_MEM_SOURCE_CONFIGURED, "psram_size_bytes"},
        {VDOG_MEM_SOURCE_MEASURED, "psram_mode"},
        {VDOG_MEM_SOURCE_MEASURED, "psram_speed_mhz"},
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(7u, (unsigned)(sizeof(cases) / sizeof(cases[0])));
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        vdog_mem_detected_t det = expected_ok();

        if (strcmp(cases[i].field, "flash_size_bytes") == 0) {
            det.flash_size_src = cases[i].wrong_tag;
        } else if (strcmp(cases[i].field, "flash_mode") == 0) {
            det.flash_mode_src = cases[i].wrong_tag;
        } else if (strcmp(cases[i].field, "flash_freq_mhz") == 0) {
            det.flash_freq_src = cases[i].wrong_tag;
        } else if (strcmp(cases[i].field, "psram_present") == 0) {
            det.psram_present_src = cases[i].wrong_tag;
        } else if (strcmp(cases[i].field, "psram_size_bytes") == 0) {
            det.psram_size_src = cases[i].wrong_tag;
        } else if (strcmp(cases[i].field, "psram_mode") == 0) {
            det.psram_mode_src = cases[i].wrong_tag;
        } else {
            det.psram_speed_src = cases[i].wrong_tag;
        }
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_ERR_MEM_SOURCE,
                                      vdog_mem_check_baseline(&det),
                                      cases[i].field);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(cases[i].field,
                                         vdog_mem_error_field(),
                                         cases[i].field);
    }
}

/* THE config-only-OPI case from plan acceptance 3: PSRAM capacity tagged
 * CONFIGURED (nothing was ever measured) is rejected as SOURCE even though
 * every VALUE matches the baseline. */
static void test_configured_psram_never_satisfies_detected(void)
{
    vdog_mem_detected_t det = expected_ok();

    det.psram_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());
}

/* An out-of-range source tag (neither MEASURED nor CONFIGURED) is a SOURCE
 * failure too — tags are validated, never defaulted. */
static void test_check_rejects_out_of_range_source_tag(void)
{
    vdog_mem_detected_t det = expected_ok();

    det.psram_mode_src = (vdog_mem_source_t)7u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());
}

/* Fixed decision order: a missing field outranks a source violation
 * outranks a wrong value, each in declaration order. */
static void test_check_decision_order(void)
{
    vdog_mem_detected_t det = expected_ok();

    /* wrong value (DIO) + source violation (configured size) + missing
     * (speed bit cleared): diagnosis is the missing speed field. */
    det.flash_mode = VDOG_BOARD_FLASH_MODE_DIO;
    det.flash_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.field_set &= ~VDOG_MEM_FIELD_PSRAM_SPEED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD,
                          vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_speed_mhz", vdog_mem_error_field());

    /* wrong value + source violation: source pass runs first and names the
     * earlier field in declaration order (flash_size_bytes). */
    det = expected_ok();
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    det.flash_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    det.flash_mode_src = VDOG_MEM_SOURCE_MEASURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    /* Two wrong values: declaration order decides (flash side before PSRAM
     * side). */
    det = expected_ok();
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    det.flash_mode = VDOG_BOARD_FLASH_MODE_DOUT;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_mem_error_field());
}

/* Named wrong-board classes on the flash side. */
static void test_check_rejects_flash_value_classes(void)
{
    vdog_mem_detected_t det = expected_ok();

    det.flash_size_bytes = 4u * 1024u * 1024u; /* the 4MB class */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    det = expected_ok();
    det.flash_size_bytes = 16u * 1024u * 1024u; /* Plus/N16R8-shaped */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    det = expected_ok();
    det.flash_mode = VDOG_BOARD_FLASH_MODE_DIO; /* quad-only flash class */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_mem_error_field());

    det = expected_ok();
    det.flash_freq_mhz = 40u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_freq_mhz", vdog_mem_error_field());
}

/* Named wrong-board classes on the PSRAM side: no-PSRAM and quad-only are
 * distinct diagnoses from a wrong capacity. */
static void test_check_rejects_psram_value_classes(void)
{
    vdog_mem_detected_t det = expected_ok();

    det.psram_present = 0u; /* measured absent: PSRAM did not init */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_present", vdog_mem_error_field());

    det = expected_ok();
    det.psram_size_bytes = 16u * 1024u * 1024u; /* N16R8-shaped capacity */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());

    det = expected_ok();
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI; /* quad-only PSRAM class */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());

    det = expected_ok();
    det.psram_mode = VDOG_BOARD_PSRAM_MODE_UNKNOWN;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());

    det = expected_ok();
    det.psram_speed_mhz = 120u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_speed_mhz", vdog_mem_error_field());
}

/* error_field is per-call state: success clears it, failure replaces it. */
static void test_error_field_is_per_call(void)
{
    vdog_mem_detected_t det = expected_ok();

    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());
    det = expected_ok();
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&det));
    TEST_ASSERT_NULL(vdog_mem_error_field());
}

/* ---- tagged render line: exact string, never a rejected set, buffers ---- */
static void test_format_exact_string(void)
{
    vdog_mem_detected_t det = expected_ok();
    char buf[256];

    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_mem_format_detected(&det, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_MEM_LINE, buf);
    /* The render can never print a configured mode as detected. */
    TEST_ASSERT_NOT_NULL(strstr(buf, "psram_mode=opi[configured]"));
    TEST_ASSERT_NULL(strstr(buf, "psram_mode=opi[measured"));
    TEST_ASSERT_NULL(vdog_mem_error_field());
}

static void test_format_exact_fit(void)
{
    vdog_mem_detected_t det = expected_ok();
    char buf[256];
    const size_t exact = strlen(EXPECTED_MEM_LINE) + 1u;

    memset(buf, 0xAA, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_format_detected(&det, buf, exact));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_MEM_LINE, buf);
    TEST_ASSERT_EQUAL_CHAR('\0', buf[exact - 1u]);
}

static void test_format_refuses_rejected_set_without_touching_buffer(void)
{
    vdog_mem_detected_t det = expected_ok();
    char buf[256];

    det.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    memset(buf, 0xAA, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM,
                          vdog_mem_format_detected(&det, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());
    TEST_ASSERT_EQUAL_UINT8(0xAAu, (uint8_t)buf[0]); /* buffer untouched */

    /* config-only capacity: no line at all, not even a tagged one. */
    det = expected_ok();
    det.psram_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE,
                          vdog_mem_format_detected(&det, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());
}

static void test_format_rejects_too_small_and_null(void)
{
    vdog_mem_detected_t det = expected_ok();
    char buf[256];
    const size_t exact = strlen(EXPECTED_MEM_LINE) + 1u;

    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_mem_format_detected(&det, buf, exact - 1u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_mem_format_detected(&det, buf, 8u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(&det, buf, 0u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(&det, NULL, sizeof(buf)));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(NULL, buf, sizeof(buf)));
}

/* Crosses the C/C++ link boundary: vdog_mem_cpp_smoke() is DEFINED in C++
 * (cpp_smoke_mem.cpp) with extern "C" linkage and called from this C TU. */
extern int vdog_mem_cpp_smoke(void);

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_mem_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (`pio test -e vdog_xiao_sense_proto
 * --without-uploading --without-testing`): compile/link qualification ONLY;
 * these are never executed in package 1.2 Part A (no upload, no run). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_check_accepts_baseline_detector);
    RUN_TEST(test_detected_init_marks_nothing);
    RUN_TEST(test_check_rejects_each_missing_field);
    RUN_TEST(test_check_rejects_null_detector);
    RUN_TEST(test_check_enforces_source_policy_per_field);
    RUN_TEST(test_configured_psram_never_satisfies_detected);
    RUN_TEST(test_check_rejects_out_of_range_source_tag);
    RUN_TEST(test_check_decision_order);
    RUN_TEST(test_check_rejects_flash_value_classes);
    RUN_TEST(test_check_rejects_psram_value_classes);
    RUN_TEST(test_error_field_is_per_call);
    RUN_TEST(test_format_exact_string);
    RUN_TEST(test_format_exact_fit);
    RUN_TEST(test_format_refuses_rejected_set_without_touching_buffer);
    RUN_TEST(test_format_rejects_too_small_and_null);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_check_accepts_baseline_detector);
    RUN_TEST(test_detected_init_marks_nothing);
    RUN_TEST(test_check_rejects_each_missing_field);
    RUN_TEST(test_check_rejects_null_detector);
    RUN_TEST(test_check_enforces_source_policy_per_field);
    RUN_TEST(test_configured_psram_never_satisfies_detected);
    RUN_TEST(test_check_rejects_out_of_range_source_tag);
    RUN_TEST(test_check_decision_order);
    RUN_TEST(test_check_rejects_flash_value_classes);
    RUN_TEST(test_check_rejects_psram_value_classes);
    RUN_TEST(test_error_field_is_per_call);
    RUN_TEST(test_format_exact_string);
    RUN_TEST(test_format_exact_fit);
    RUN_TEST(test_format_refuses_rejected_set_without_touching_buffer);
    RUN_TEST(test_format_rejects_too_small_and_null);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
