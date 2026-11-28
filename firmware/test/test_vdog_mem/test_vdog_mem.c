/*
 * Host (native environment) tests for the vdog portable memory-baseline
 * core (package 1.2, plan A4). Run with: pio test -d firmware -e native
 * (HOST evidence only — no device, no upload).
 *
 * These cases pin plan 1.2 acceptance 2/3: every wrong-board class named in
 * §1.2 (Plus/N16R8-shaped, quad-only PSRAM, wrong flash, no PSRAM) rejects
 * with an EXACT code + field name, the fixed decision order is missing ->
 * source -> value, and the rendered line carries per-field MEASURED /
 * CONFIGURED tags so a CONFIGURED value (e.g. OPI mode) can never print as
 * "detected" (lead finding 2).
 */
#include <string.h>

#include "unity.h"
#include "vdog_board.h"
#include "vdog_core.h"
#include "vdog_mem.h"

#define EXPECTED_MEM_LINE                                                        \
    "flash_size=8MB[measured] flash_mode=qio[configured] "                       \
    "flash_freq=80m[configured] psram=8MB[measured:init-ok] "                    \
    "psram_mode=opi[configured] psram_speed=80m[configured]"

extern int vdog_mem_cpp_smoke(void);

static vdog_mem_detected_t baseline_ok(void)
{
    vdog_mem_detected_t d;
    vdog_mem_detected_init(&d);
    d.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    d.flash_size_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_SIZE;
    d.flash_mode = VDOG_MEM_BASELINE_FLASH_MODE;
    d.flash_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_MODE;
    d.flash_freq_mhz = VDOG_MEM_BASELINE_FLASH_FREQ_MHZ;
    d.flash_freq_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_FLASH_FREQ;
    d.psram_present = VDOG_MEM_BASELINE_PSRAM_PRESENT;
    d.psram_present_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_PRESENT;
    d.psram_size_bytes = VDOG_MEM_BASELINE_PSRAM_SIZE_BYTES;
    d.psram_size_src = VDOG_MEM_SOURCE_MEASURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_SIZE;
    d.psram_mode = VDOG_MEM_BASELINE_PSRAM_MODE;
    d.psram_mode_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_MODE;
    d.psram_speed_mhz = VDOG_MEM_BASELINE_PSRAM_SPEED_MHZ;
    d.psram_speed_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.field_set |= VDOG_MEM_FIELD_PSRAM_SPEED;
    return d;
}

static void test_baseline_accepts_detected_profile(void)
{
    vdog_mem_detected_t d = baseline_ok();
    TEST_ASSERT_EQUAL_UINT32(VDOG_MEM_FIELD_ALL, d.field_set);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&d));
    TEST_ASSERT_NULL(vdog_mem_error_field());
}

static void test_detected_init_marks_nothing(void)
{
    vdog_mem_detected_t d;
    memset(&d, 0xA5, sizeof(d));
    vdog_mem_detected_init(&d);
    TEST_ASSERT_EQUAL_UINT32(0u, d.field_set);
    /* Never probed != probed wrong: blank is MISSING, and the first field
     * in declaration order is named. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
}

static const uint32_t g_all_bits[] = {
    VDOG_MEM_FIELD_FLASH_SIZE, VDOG_MEM_FIELD_FLASH_MODE,
    VDOG_MEM_FIELD_FLASH_FREQ, VDOG_MEM_FIELD_PSRAM_PRESENT,
    VDOG_MEM_FIELD_PSRAM_SIZE, VDOG_MEM_FIELD_PSRAM_MODE,
    VDOG_MEM_FIELD_PSRAM_SPEED};
static const char *const g_all_names[] = {
    "flash_size_bytes", "flash_mode",       "flash_freq_mhz",
    "psram_present",    "psram_size_bytes", "psram_mode",
    "psram_speed_mhz"};

static void test_rejects_each_missing_field(void)
{
    size_t i;
    for (i = 0; i < 7u; ++i) {
        vdog_mem_detected_t d = baseline_ok();
        d.field_set &= ~g_all_bits[i];
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_ERR_MEM_MISSING_FIELD,
                                      vdog_mem_check_baseline(&d), g_all_names[i]);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(g_all_names[i], vdog_mem_error_field(),
                                         g_all_names[i]);
    }
}

static void test_rejects_null_detector(void)
{
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG, vdog_mem_check_baseline(NULL));
}

/* PR-review round 1 High finding: esp_flash_get_size() reports the capacity
 * from the BINARY IMAGE HEADER, so an 8 MiB image on a physical 16 MiB chip
 * must NOT be recorded as 8MB[measured]. The PHYSICAL capacity is the
 * honest MEASURED value; a header/physical mismatch is reported, naming
 * flash_size_bytes — never averaged or silently preferred. */
static void test_record_flash_size_mismatch(void)
{
    /* start from a fully-baseline set so the flash VALUE is the only
     * thing the baseline check can reject (missing fields outrank
     * values, by documented order) */
    vdog_mem_detected_t det = baseline_ok();
    /* header says 8MB (the image), the chip is physically 16MB */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 16u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
    /* the MEASURED field holds the PHYSICAL value, not the header's */
    TEST_ASSERT_EQUAL_UINT32(16u * 1024u * 1024u, det.flash_size_bytes);
    TEST_ASSERT_EQUAL_INT(VDOG_MEM_SOURCE_MEASURED, (int)det.flash_size_src);
    TEST_ASSERT(det.field_set & VDOG_MEM_FIELD_FLASH_SIZE);
    /* and the baseline check then rejects it for the right reason */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
}

static void test_record_flash_size_agree_and_failures(void)
{
    vdog_mem_detected_t det;

    /* agreeing header/physical records OK */
    memset(&det, 0xA5, sizeof(det));
    vdog_mem_detected_init(&det);
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 8u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT32(8u * 1024u * 1024u, det.flash_size_bytes);
    TEST_ASSERT_EQUAL_INT(VDOG_MEM_SOURCE_MEASURED, (int)det.flash_size_src);
    TEST_ASSERT_EQUAL_UINT8(0u, det.flash_cross_fail);

    /* a failed query (0 from either getter) leaves the field UNSET */
    memset(&det, 0xA5, sizeof(det));
    vdog_mem_detected_init(&det);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_record_flash_size(&det, 0u, 8u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT8(0u, det.field_set);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_record_flash_size(&det, 8u * 1024u * 1024u, 0u));
    TEST_ASSERT_EQUAL_UINT8(0u, det.field_set);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_record_flash_size(NULL, 8u, 8u));
}

/* Round-3 Medium finding: a failed REFRESH must never preserve earlier
 * measured evidence — record() resets the flash fields on EVERY call. */
static void test_record_flash_size_refresh_clears_stale(void)
{
    vdog_mem_detected_t det;

    /* successful first read: 8MB agreeing */
    det = baseline_ok();
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 8u * 1024u * 1024u));
    TEST_ASSERT(det.field_set & VDOG_MEM_FIELD_FLASH_SIZE);

    /* second reading FAILS (header query returned 0): the old MEASURED
     * field must be GONE, not retained */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_record_flash_size(&det, 0u, 8u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT(0u, det.field_set & VDOG_MEM_FIELD_FLASH_SIZE);
    TEST_ASSERT_EQUAL_UINT32(0u, det.flash_size_bytes);
    TEST_ASSERT_EQUAL_UINT8(0u, det.flash_cross_fail);
    /* and the baseline check now fails as MISSING, not as a stale pass */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD,
                          vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    /* physical=0 fails the same way */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_record_flash_size(&det, 8u * 1024u * 1024u, 0u));
    TEST_ASSERT_EQUAL_UINT(0u, det.field_set & VDOG_MEM_FIELD_FLASH_SIZE);

    /* a subsequent GOOD read restores the field honestly */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 8u * 1024u * 1024u));
    TEST_ASSERT(det.field_set & VDOG_MEM_FIELD_FLASH_SIZE);
    TEST_ASSERT_EQUAL_UINT32(8u * 1024u * 1024u, det.flash_size_bytes);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&det));
}

/* Round-2 Medium finding: a cross-check failure must NEVER produce
 * success-form memory logs. The bug shape was header=16MB vs
 * physical=8MB: the physical value equals the baseline, so check_baseline
 * passed and main.c printed the success "mem:" line next to a warning.
 * Sticky flash_cross_fail rules that out in BOTH directions. */
static void test_record_flash_size_cross_check_sticky(void)
{
    vdog_mem_detected_t det;

    /* direction 1: header BIGGER than physical (physical == baseline) */
    det = baseline_ok();
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH,
                          vdog_mem_record_flash_size(
                              &det, 16u * 1024u * 1024u, 8u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT8(1u, det.flash_cross_fail);
    TEST_ASSERT_EQUAL_UINT32(8u * 1024u * 1024u, det.flash_size_bytes);
    /* the recorded value alone WOULD pass — the sticky state rejects it */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    /* direction 2: header SMALLER than physical (value already wrong) */
    det = baseline_ok();
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 16u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT8(1u, det.flash_cross_fail);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&det));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    /* an agreeing re-record clears the sticky state */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_mem_record_flash_size(
                              &det, 8u * 1024u * 1024u, 8u * 1024u * 1024u));
    TEST_ASSERT_EQUAL_UINT8(0u, det.flash_cross_fail);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&det));
}

static void test_rejects_source_violations(void)
{
    vdog_mem_detected_t d;

    /* A "detected" claim backed by CONFIGURED is the finding-2 bypass. */
    d = baseline_ok();
    d.flash_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_present_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_present", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());

    /* Mode/frequency claiming MEASURED is equally false (no runtime
     * read-back exists for these). */
    d = baseline_ok();
    d.flash_mode_src = VDOG_MEM_SOURCE_MEASURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_mode_src = VDOG_MEM_SOURCE_MEASURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());

    /* Out-of-range tag values fail closed too. */
    d = baseline_ok();
    d.flash_freq_src = (vdog_mem_source_t)2u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_freq_mhz", vdog_mem_error_field());
}

static void test_missing_outranks_source_and_value(void)
{
    vdog_mem_detected_t d;

    /* Missing (flash_size absent) beats a source violation on it. */
    d = baseline_ok();
    d.field_set &= ~VDOG_MEM_FIELD_FLASH_SIZE;
    d.flash_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    /* Missing anywhere (psram_size) beats a wrong tag elsewhere
     * (flash_mode). */
    d = baseline_ok();
    d.field_set &= ~VDOG_MEM_FIELD_PSRAM_SIZE;
    d.flash_mode_src = VDOG_MEM_SOURCE_MEASURED;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_MISSING_FIELD, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());

    /* Source violations (flash_size) beat wrong values (psram_mode). */
    d = baseline_ok();
    d.flash_size_src = VDOG_MEM_SOURCE_CONFIGURED;
    d.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_SOURCE, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
}

static void test_rejects_flash_classes(void)
{
    vdog_mem_detected_t d;

    d = baseline_ok();
    d.flash_size_bytes = 4u * 1024u * 1024u; /* classic 4 MiB board */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    d = baseline_ok();
    d.flash_size_bytes = 16u * 1024u * 1024u; /* N16R8-shaped */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());

    d = baseline_ok();
    d.flash_mode = VDOG_BOARD_FLASH_MODE_DIO;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_mode", vdog_mem_error_field());

    d = baseline_ok();
    d.flash_freq_mhz = 40u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_freq_mhz", vdog_mem_error_field());
}

static void test_rejects_psram_classes(void)
{
    vdog_mem_detected_t d;

    d = baseline_ok();
    d.psram_present = 0u; /* no PSRAM: rejected against the Sense baseline */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_present", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_size_bytes = 16u * 1024u * 1024u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_size_bytes", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI; /* quad-only PSRAM */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_mode", vdog_mem_error_field());

    d = baseline_ok();
    d.psram_speed_mhz = 40u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_PSRAM, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("psram_speed_mhz", vdog_mem_error_field());

    /* Full Plus/N16R8-shaped report: 16 MiB flash + 8 MiB QSPI PSRAM — the
     * flash offender is reported first (declaration order). */
    d = baseline_ok();
    d.flash_size_bytes = 16u * 1024u * 1024u;
    d.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
}

static void test_format_exact_string(void)
{
    vdog_mem_detected_t d = baseline_ok();
    char buf[192];
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_format_detected(&d, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_MEM_LINE, buf);
    /* Finding 2 pinned: mode/speed render as [configured] — the line never
     * prints a mode as detected. */
    TEST_ASSERT_NOT_NULL(strstr(buf, "psram_mode=opi[configured]"));
    TEST_ASSERT_NULL(strstr(buf, "opi[measured]"));
}

static void test_format_exact_fit(void)
{
    vdog_mem_detected_t d = baseline_ok();
    char buf[192];
    size_t need = strlen(EXPECTED_MEM_LINE);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_format_detected(&d, buf, need + 1u));
    TEST_ASSERT_EQUAL_STRING(EXPECTED_MEM_LINE, buf);
}

static void test_format_too_small_and_null(void)
{
    vdog_mem_detected_t d = baseline_ok();
    char buf[192];
    size_t need = strlen(EXPECTED_MEM_LINE);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_mem_format_detected(&d, buf, need));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(&d, NULL, sizeof(buf)));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(&d, buf, 0u));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_mem_format_detected(NULL, buf, sizeof(buf)));
}

static void test_format_refuses_rejected_sets(void)
{
    vdog_mem_detected_t d = baseline_ok();
    char buf[160];
    const char poison = '\x7a';
    memset(buf, poison, sizeof(buf));

    d.flash_size_bytes = 4u * 1024u * 1024u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH,
                          vdog_mem_format_detected(&d, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("flash_size_bytes", vdog_mem_error_field());
    /* The rejected set is never rendered: buffer untouched (the documented
     * "returns the check's code without touching buf" path). */
    TEST_ASSERT_EQUAL_UINT8((uint8_t)poison, (uint8_t)buf[0]);
    TEST_ASSERT_EQUAL_UINT8((uint8_t)poison, (uint8_t)buf[sizeof(buf) - 1u]);
}

static void test_error_field_cleared_by_success(void)
{
    vdog_mem_detected_t d = baseline_ok();
    d.flash_size_bytes = 4u * 1024u * 1024u;
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_MEM_FLASH, vdog_mem_check_baseline(&d));
    TEST_ASSERT_NOT_NULL(vdog_mem_error_field());
    d.flash_size_bytes = VDOG_MEM_BASELINE_FLASH_SIZE_BYTES;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_mem_check_baseline(&d));
    TEST_ASSERT_NULL(vdog_mem_error_field());
}

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_mem_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (compile/link qualification, NEVER run in
 * package 1.2 — same policy as the 1.1 suites). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_baseline_accepts_detected_profile);
    RUN_TEST(test_detected_init_marks_nothing);
    RUN_TEST(test_rejects_each_missing_field);
    RUN_TEST(test_rejects_null_detector);
    RUN_TEST(test_record_flash_size_mismatch);
    RUN_TEST(test_record_flash_size_agree_and_failures);
    RUN_TEST(test_record_flash_size_cross_check_sticky);
    RUN_TEST(test_record_flash_size_refresh_clears_stale);
    RUN_TEST(test_rejects_source_violations);
    RUN_TEST(test_missing_outranks_source_and_value);
    RUN_TEST(test_rejects_flash_classes);
    RUN_TEST(test_rejects_psram_classes);
    RUN_TEST(test_format_exact_string);
    RUN_TEST(test_format_exact_fit);
    RUN_TEST(test_format_too_small_and_null);
    RUN_TEST(test_format_refuses_rejected_sets);
    RUN_TEST(test_error_field_cleared_by_success);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_baseline_accepts_detected_profile);
    RUN_TEST(test_detected_init_marks_nothing);
    RUN_TEST(test_rejects_each_missing_field);
    RUN_TEST(test_rejects_null_detector);
    RUN_TEST(test_record_flash_size_mismatch);
    RUN_TEST(test_record_flash_size_agree_and_failures);
    RUN_TEST(test_record_flash_size_cross_check_sticky);
    RUN_TEST(test_record_flash_size_refresh_clears_stale);
    RUN_TEST(test_rejects_source_violations);
    RUN_TEST(test_missing_outranks_source_and_value);
    RUN_TEST(test_rejects_flash_classes);
    RUN_TEST(test_rejects_psram_classes);
    RUN_TEST(test_format_exact_string);
    RUN_TEST(test_format_exact_fit);
    RUN_TEST(test_format_too_small_and_null);
    RUN_TEST(test_format_refuses_rejected_sets);
    RUN_TEST(test_error_field_cleared_by_success);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
