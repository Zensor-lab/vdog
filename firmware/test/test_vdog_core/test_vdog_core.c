/*
 * Host (native environment) tests for the vdog portable core module.
 * Run with: pio test -d firmware -e native   (HOST evidence only)
 */
#include <string.h>

#include "unity.h"
#include "vdog_core.h"

void setUp(void) {}
void tearDown(void) {}

static void test_format_version_exact(void)
{
    char buf[64];
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_format_version(buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("vdog 0.2.0-proto", buf);
}

static void test_format_version_exact_fit(void)
{
    /* Exactly strlen("vdog 0.2.0-proto") + 1 must succeed. */
    const size_t exact = strlen("vdog 0.2.0-proto") + 1u;
    char buf[64];
    memset(buf, 0xAA, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_format_version(buf, exact));
    TEST_ASSERT_EQUAL_STRING("vdog 0.2.0-proto", buf);
}

static void test_format_version_rejects_small_and_null(void)
{
    char buf[16];
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_format_version(buf, 5));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_BUFFER_TOO_SMALL,
                          vdog_format_version(buf, 0));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG, vdog_format_version(NULL, 64));
}

static void test_version_pack_roundtrip(void)
{
    uint32_t packed = 0xDEADBEEFu;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_version_pack(2u, 3u, 7u, &packed));
    TEST_ASSERT_EQUAL_UINT32((2u << 16) | (3u << 8) | 7u, packed);
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_version_pack(1u, 2u, 3u, NULL));
}

static void test_version_compare_ordering(void)
{
    uint32_t v_old, v_new;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_version_pack(0u, 2u, 0u, &v_old));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_version_pack(0u, 10u, 0u, &v_new));
    TEST_ASSERT_EQUAL_INT(-1, vdog_version_compare(v_old, v_new));
    TEST_ASSERT_EQUAL_INT(1, vdog_version_compare(v_new, v_old));
    TEST_ASSERT_EQUAL_INT(0, vdog_version_compare(v_old, v_old));
    /* 0.2.0 (proto) must sort below any 1.x release */
    uint32_t v_1_0_0;
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_version_pack(1u, 0u, 0u, &v_1_0_0));
    TEST_ASSERT_EQUAL_INT(-1, vdog_version_compare(v_old, v_1_0_0));
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (`pio test -e vdog_xiao_sense_proto
 * --without-uploading --without-testing`): PlatformIO excludes src/main.c
 * from __test builds, ESP-IDF's esp_system provides main(), and FreeRTOS
 * calls app_main(). These tests are NEVER executed at package 0.2 — no
 * upload, no run — this entry point only proves compile/link qualification.
 * Host execution is `pio test -e native` (HOST evidence). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_format_version_exact);
    RUN_TEST(test_format_version_exact_fit);
    RUN_TEST(test_format_version_rejects_small_and_null);
    RUN_TEST(test_version_pack_roundtrip);
    RUN_TEST(test_version_compare_ordering);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_format_version_exact);
    RUN_TEST(test_format_version_exact_fit);
    RUN_TEST(test_format_version_rejects_small_and_null);
    RUN_TEST(test_version_pack_roundtrip);
    RUN_TEST(test_version_compare_ordering);
    return UNITY_END();
}
#endif
