/*
 * Host (native environment) tests for the vdog portable strap/reserved-pin
 * table (package 1.2, plan A2b/A4). Run with: pio test -d firmware -e
 * native (HOST evidence only).
 *
 * Pins the desk half of "no strap conflicts": every table row, every
 * reject naming pin + role, candidates PROVISIONAL-only, GPIO21 unclaimed
 * (claim -> PROVISIONAL naming the unresolved CS21/user-LED sharing), the
 * microphone DISABLED, and invalid pins failing closed.
 */
#include <string.h>

#include "unity.h"
#include "vdog_straps.h"

extern int vdog_straps_cpp_smoke(void);

/* 26 rows: 6 reserved + 14 camera candidates + 3 SD candidates + 1
 * UNRESOLVED CS21 + 2 DISABLED mic rows. */
#define EXPECTED_TABLE_COUNT 26u

static const uint8_t g_reserved[] = {0u, 3u, 45u, 46u, 19u, 20u};
static const uint8_t g_camera[] = {15u, 17u, 18u, 16u, 14u, 12u, 11u, 48u,
                                   10u, 13u, 38u, 47u, 40u, 39u};
static const uint8_t g_sd[]     = {7u, 8u, 9u};
static const uint8_t g_mic[]    = {41u, 42u};

static void test_table_shape(void)
{
    unsigned i;
    unsigned reserved_n = 0u, camera_n = 0u, sd_n = 0u, mic_n = 0u, unclaimed_n = 0u;

    TEST_ASSERT_EQUAL_UINT32(EXPECTED_TABLE_COUNT, vdog_straps_table_count);
    for (i = 0; i < vdog_straps_table_count; ++i) {
        const vdog_straps_row_t *r = &vdog_straps_table[i];
        TEST_ASSERT_NOT_NULL(r->role);
        /* Flag combinations are exclusive; candidate+reserved together
         * would be a contradiction (a pin cannot be both). */
        TEST_ASSERT(r->reserved == 0u || r->candidate == 0u);
        TEST_ASSERT(r->disabled == 0u || r->candidate == 0u);
        if (r->reserved != 0u) {
            ++reserved_n;
        } else if (r->disabled != 0u) {
            ++mic_n;
        } else if (strcmp(r->role, VDOG_STRAPS_ROLE_UNCLAIMED) == 0) {
            ++unclaimed_n;
        } else if (strncmp(r->role, "camera ", 7u) == 0) {
            ++camera_n;
        } else if (strncmp(r->role, "SD card ", 8u) == 0) {
            ++sd_n;
        }
    }
    TEST_ASSERT_EQUAL_UINT(6u, reserved_n);
    TEST_ASSERT_EQUAL_UINT(14u, camera_n);
    TEST_ASSERT_EQUAL_UINT(3u, sd_n);
    TEST_ASSERT_EQUAL_UINT(2u, mic_n);
    TEST_ASSERT_EQUAL_UINT(1u, unclaimed_n);
}

static void test_reserved_rows_exact(void)
{
    size_t i;
    for (i = 0; i < sizeof(g_reserved) / sizeof(g_reserved[0]); ++i) {
        const vdog_straps_row_t *r = vdog_straps_lookup(g_reserved[i]);
        TEST_ASSERT_NOT_NULL_MESSAGE(r, "reserved row present");
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(1u, r->reserved, "reserved flag");
        TEST_ASSERT_EQUAL_UINT8(0u, r->candidate);
    }
    /* Roles pinned verbatim for the critical straps + USB pair. */
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_BOOT, vdog_straps_lookup(0)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_VDD_SPI,
                             vdog_straps_lookup(45)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_BOOT_MODE,
                             vdog_straps_lookup(46)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_USB, vdog_straps_lookup(19)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_USB_DN,
                             vdog_straps_lookup(20)->role);
}

static void test_claims_on_reserved_reject_every_claimant(void)
{
    size_t i, c;
    for (i = 0; i < sizeof(g_reserved) / sizeof(g_reserved[0]); ++i) {
        for (c = 0; c < 3u; ++c) {
            const char *role = NULL;
            vdog_straps_claim_t rc = vdog_straps_check_claim(
                g_reserved[i], (vdog_straps_claimant_t)c, &role);
            TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_STRAPS_REJECT, rc, "reserved reject");
            TEST_ASSERT_NOT_NULL_MESSAGE(role, "role named");
        }
    }
}

static void test_camera_sd_candidates_provisional_only(void)
{
    size_t i;
    for (i = 0; i < sizeof(g_camera) / sizeof(g_camera[0]); ++i) {
        const char *role = NULL;
        TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                              vdog_straps_check_claim(g_camera[i],
                                                      VDOG_STRAPS_CLAIM_CAMERA,
                                                      &role));
        TEST_ASSERT_NOT_NULL(role);
        TEST_ASSERT_NOT_NULL_MESSAGE(strstr(role, "candidate"),
                                     "candidate wording pinned");
    }
    for (i = 0; i < sizeof(g_sd) / sizeof(g_sd[0]); ++i) {
        const char *role = NULL;
        TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                              vdog_straps_check_claim(g_sd[i], VDOG_STRAPS_CLAIM_SD,
                                                      &role));
        TEST_ASSERT_NOT_NULL(role);
    }
}

static void test_gpio21_unclaimed_provisional(void)
{
    const vdog_straps_row_t *r = vdog_straps_lookup(21u);
    TEST_ASSERT_NOT_NULL(r);
    TEST_ASSERT_EQUAL_UINT8(0u, r->reserved); /* NO row claims it */
    TEST_ASSERT_EQUAL_UINT8(1u, r->candidate);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_UNCLAIMED, r->role);
    /* Every claimant gets PROVISIONAL naming the unresolved sharing —
     * never OK, never approval, until 0.3/E07 (Jada) resolves CS21. */
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                          vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_GENERAL,
                                                  NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                          vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_SD, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                          vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_CAMERA,
                                                  NULL));
    {
        const char *role = NULL;
        TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                              vdog_straps_check_claim(21u, VDOG_STRAPS_CLAIM_SD,
                                                      &role));
        TEST_ASSERT_NOT_NULL(strstr(role, "UNRESOLVED"));
    }
}

static void test_mic_rows_disabled_reject(void)
{
    size_t i, c;
    for (i = 0; i < sizeof(g_mic) / sizeof(g_mic[0]); ++i) {
        const vdog_straps_row_t *r = vdog_straps_lookup(g_mic[i]);
        TEST_ASSERT_NOT_NULL(r);
        TEST_ASSERT_EQUAL_UINT8(1u, r->disabled);
        for (c = 0; c < 3u; ++c) {
            const char *role = NULL;
            TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_REJECT,
                                  vdog_straps_check_claim(g_mic[i],
                                                          (vdog_straps_claimant_t)c,
                                                          &role));
            TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, role);
        }
    }
}

static void test_free_pins_ok(void)
{
    static const uint8_t free_pins[] = {1u,  2u,  4u,  5u,  6u,  22u, 23u,
                                        24u, 25u, 26u, 27u, 28u, 29u, 30u,
                                        31u, 32u, 33u, 34u, 35u, 36u, 37u,
                                        43u, 44u};
    size_t i;
    for (i = 0; i < sizeof(free_pins) / sizeof(free_pins[0]); ++i) {
        TEST_ASSERT_NULL(vdog_straps_lookup(free_pins[i]));
        TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_OK,
                              vdog_straps_check_claim(free_pins[i],
                                                      VDOG_STRAPS_CLAIM_GENERAL,
                                                      NULL));
    }
}

static void test_invalid_gpio_fails_closed(void)
{
    const char *role = NULL;
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_REJECT,
                          vdog_straps_check_claim(49u, VDOG_STRAPS_CLAIM_GENERAL,
                                                  &role));
    TEST_ASSERT_NOT_NULL(strstr(role, "invalid-gpio"));
    role = NULL;
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_REJECT,
                          vdog_straps_check_claim(255u, VDOG_STRAPS_CLAIM_SD, &role));
    TEST_ASSERT_NOT_NULL(strstr(role, "invalid-gpio"));
}

static void test_out_role_null_tolerated(void)
{
    /* All three result paths work with a NULL out_role. */
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_REJECT,
                          vdog_straps_check_claim(0u, VDOG_STRAPS_CLAIM_GENERAL,
                                                  NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_PROVISIONAL,
                          vdog_straps_check_claim(7u, VDOG_STRAPS_CLAIM_SD, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_STRAPS_OK,
                          vdog_straps_check_claim(1u, VDOG_STRAPS_CLAIM_GENERAL,
                                                  NULL));
}

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_straps_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (compile/link qualification, NEVER run in
 * package 1.2). */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_table_shape);
    RUN_TEST(test_reserved_rows_exact);
    RUN_TEST(test_claims_on_reserved_reject_every_claimant);
    RUN_TEST(test_camera_sd_candidates_provisional_only);
    RUN_TEST(test_gpio21_unclaimed_provisional);
    RUN_TEST(test_mic_rows_disabled_reject);
    RUN_TEST(test_free_pins_ok);
    RUN_TEST(test_invalid_gpio_fails_closed);
    RUN_TEST(test_out_role_null_tolerated);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_table_shape);
    RUN_TEST(test_reserved_rows_exact);
    RUN_TEST(test_claims_on_reserved_reject_every_claimant);
    RUN_TEST(test_camera_sd_candidates_provisional_only);
    RUN_TEST(test_gpio21_unclaimed_provisional);
    RUN_TEST(test_mic_rows_disabled_reject);
    RUN_TEST(test_free_pins_ok);
    RUN_TEST(test_invalid_gpio_fails_closed);
    RUN_TEST(test_out_role_null_tolerated);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
