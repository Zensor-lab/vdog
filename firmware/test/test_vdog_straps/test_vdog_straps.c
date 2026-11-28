/*
 * Host (native environment) tests for the vdog portable strap/reserved-pin
 * table. Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases pin plan 1.2 A2b: every table row is asserted, reserved rows
 * (GPIO0/3/45/46 + USB pair 19/20) REJECT any claim naming pin + role,
 * camera/SD candidates return PROVISIONAL for EVERY claimant — never an
 * approval —, GPIO21's unresolved SD-CS/user-LED sharing stays UNCLAIMED
 * (no row claims it as LED or as SD-CS; a claim is PROVISIONAL naming the
 * unresolved sharing), microphone rows stay DISABLED, and invalid gpio /
 * claimant inputs are named programming errors. No pin is configured.
 */
#include <string.h>

#include "unity.h"
#include "vdog_straps.h"

void setUp(void) {}
void tearDown(void) {}

/* Every row: flags exactly one verdict class, role present, gpio ascending
 * and unique, no claims above the SoC maximum. */
static void test_table_wellformed(void)
{
    const vdog_straps_row_t *rows = vdog_straps_table();
    unsigned n = vdog_straps_table_count();
    unsigned i;

    TEST_ASSERT_EQUAL_UINT(22u, n);
    for (i = 0; i < n; ++i) {
        const unsigned flags = (unsigned)rows[i].reserved +
                               (unsigned)rows[i].candidate +
                               (unsigned)rows[i].disabled;
        TEST_ASSERT_NOT_NULL_MESSAGE(rows[i].role, "row role");
        TEST_ASSERT_EQUAL_UINT_MESSAGE(1u, flags, "row verdict flags");
        TEST_ASSERT_LESS_OR_EQUAL_UINT8_MESSAGE(
            VDOG_STRAPS_GPIO_MAX, rows[i].gpio, "row gpio range");
        if (i > 0u) {
            TEST_ASSERT_GREATER_THAN_UINT8(rows[i - 1u].gpio, rows[i].gpio);
        }
    }
}

/* The claim gate agrees with the table everywhere. */
static void test_gate_agrees_with_table_everywhere(void)
{
    uint8_t gpio;

    for (gpio = 0u; gpio <= VDOG_STRAPS_GPIO_MAX; ++gpio) {
        const vdog_straps_row_t *row = vdog_straps_lookup(gpio);
        const char *role = (const char *)0x5A5A;
        vdog_straps_claim_t got =
            vdog_straps_check_claim(gpio, VDOG_STRAPS_CLAIM_GENERAL, &role);

        if (row == NULL) {
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_OK, got);
            TEST_ASSERT_NULL(role);
        } else if (row->disabled != 0u || row->reserved != 0u) {
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT, got);
            TEST_ASSERT_EQUAL_STRING(row->role, role);
        } else {
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_PROVISIONAL, got);
            TEST_ASSERT_EQUAL_STRING(row->role, role);
        }
    }
}

/* Strap pins REJECT every kind of claim, naming pin + role. */
static void test_reserved_straps_reject_all_claims(void)
{
    const uint8_t straps[] = {0u, 3u, 45u, 46u};
    const vdog_straps_claimant_t claimants[] = {
        VDOG_STRAPS_CLAIM_GENERAL, VDOG_STRAPS_CLAIM_CAMERA,
        VDOG_STRAPS_CLAIM_SD};
    size_t i;
    size_t j;

    TEST_ASSERT_EQUAL_UINT(4u, (unsigned)(sizeof(straps) / sizeof(straps[0])));
    for (i = 0; i < sizeof(straps) / sizeof(straps[0]); ++i) {
        const vdog_straps_row_t *row = vdog_straps_lookup(straps[i]);

        TEST_ASSERT_NOT_NULL(row);
        for (j = 0; j < sizeof(claimants) / sizeof(claimants[0]); ++j) {
            const char *role = NULL;
            TEST_ASSERT_EQUAL_UINT8_MESSAGE(
                VDOG_STRAPS_REJECT,
                vdog_straps_check_claim(straps[i], claimants[j], &role),
                "strap claim");
            TEST_ASSERT_NOT_NULL(role);
            TEST_ASSERT_EQUAL_STRING(row->role, role);
        }
    }

    /* The roles are the documented strap identities, pinned verbatim. */
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_BOOT,
                             vdog_straps_lookup(0u)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_JTAG,
                             vdog_straps_lookup(3u)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_VDD_SPI,
                             vdog_straps_lookup(45u)->role);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_BOOT_MODE,
                             vdog_straps_lookup(46u)->role);
}

/* The native-USB flashing/monitor path is reserved too. */
static void test_usb_pins_reject_claims(void)
{
    const char *role = NULL;

    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(19u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_USB_DN, role);
    role = NULL;
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(20u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_USB, role);
}

/* Camera candidates: PROVISIONAL for EVERY claimant — never an approval —
 * including a plain GENERAL claim (candidate reservation outranks ad-hoc
 * reuse until 0.3/0.7 evidence resolves the map). */
static void test_camera_candidates_provisional_never_approved(void)
{
    static const uint8_t cam_pins[] = {7u,  8u,  9u,  10u, 11u, 12u,
                                       14u, 15u, 16u, 17u, 18u, 40u,
                                       42u};
    size_t i;

    TEST_ASSERT_EQUAL_UINT(13u, (unsigned)(sizeof(cam_pins) /
                                           sizeof(cam_pins[0])));
    for (i = 0; i < sizeof(cam_pins) / sizeof(cam_pins[0]); ++i) {
        const vdog_straps_row_t *row = vdog_straps_lookup(cam_pins[i]);
        const char *role = NULL;
        vdog_straps_claim_t got;

        TEST_ASSERT_NOT_NULL(row);
        got = vdog_straps_check_claim(cam_pins[i], VDOG_STRAPS_CLAIM_CAMERA,
                                      &role);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_STRAPS_PROVISIONAL, got,
                                        "camera candidate claim");
        TEST_ASSERT_NOT_NULL(strstr(role, "candidate"));
        TEST_ASSERT_NOT_EQUAL(VDOG_STRAPS_OK, (int)got); /* not approved */
    }

    /* A GENERAL claim on the same pins is still PROVISIONAL, not OK. */
    {
        const char *role = NULL;
        TEST_ASSERT_EQUAL_UINT8(
            VDOG_STRAPS_PROVISIONAL,
            vdog_straps_check_claim(15u, VDOG_STRAPS_CLAIM_GENERAL, &role));
    }

    /* GPIO8/9/10 are dual candidates in the pin-map: the row says so
     * instead of silently dropping one candidate. */
    TEST_ASSERT_NOT_NULL(strstr(vdog_straps_lookup(8u)->role, "SD"));
    TEST_ASSERT_NOT_NULL(strstr(vdog_straps_lookup(9u)->role, "SD"));
    TEST_ASSERT_NOT_NULL(strstr(vdog_straps_lookup(10u)->role, "SD"));
    /* The microphone conflicts on 40/42 are named in the roles. */
    TEST_ASSERT_NOT_NULL(strstr(vdog_straps_lookup(40u)->role, "DISABLED"));
    TEST_ASSERT_NOT_NULL(strstr(vdog_straps_lookup(42u)->role, "DISABLED"));
}

/* GPIO21 is UNCLAIMED here: the row documents the unresolved SD-CS/user-LED
 * sharing, claims are PROVISIONAL, and nothing is claimed as LED or SD-CS. */
static void test_gpio21_unclaimed_with_unresolved_sharing(void)
{
    const vdog_straps_row_t *row = vdog_straps_lookup(21u);
    const char *role = NULL;

    TEST_ASSERT_NOT_NULL(row);
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_UNCLAIMED, row->role);
    TEST_ASSERT_EQUAL_UINT8(0u, row->reserved);
    TEST_ASSERT_EQUAL_UINT8(1u, row->candidate);
    TEST_ASSERT_NOT_NULL(strstr(row->role, "UNRESOLVED"));

    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_PROVISIONAL,
                            vdog_straps_check_claim(21u,
                                                    VDOG_STRAPS_CLAIM_SD,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_UNCLAIMED, role);
}

/* Microphone rows are DISABLED (product baseline keeps audio dead). */
static void test_microphone_rows_rejected(void)
{
    const char *role = NULL;

    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(39u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, role);
    TEST_ASSERT_NOT_NULL(strstr(role, "DISABLED"));

    role = NULL;
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(41u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, role);
}

/* Pins with no row: OK — but documented as NOT an approval of ownership
 * (approved wiring is 0.3/0.7 evidence this table cannot grant). */
static void test_unclaimed_pins_pass_without_approval(void)
{
    static const uint8_t free_pins[] = {1u, 2u,  4u,  5u,  6u,  13u,
                                        22u, 23u, 38u, 43u, 44u, 47u,
                                        48u};
    size_t i;

    for (i = 0; i < sizeof(free_pins) / sizeof(free_pins[0]); ++i) {
        TEST_ASSERT_NULL_MESSAGE(vdog_straps_lookup(free_pins[i]),
                                 "pin must have no row");
        TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_OK,
                                vdog_straps_check_claim(free_pins[i],
                                                        VDOG_STRAPS_CLAIM_GENERAL,
                                                        NULL));
    }
}

/* Invalid inputs are named programming errors, never "unclaimed". */
static void test_invalid_inputs_are_named(void)
{
    const char *role = NULL;

    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(49u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING("invalid-gpio", role);

    role = NULL;
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(255u,
                                                    VDOG_STRAPS_CLAIM_CAMERA,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING("invalid-gpio", role);

    /* Out-of-range claimant on an otherwise-fine pin. */
    role = NULL;
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(
                                5u, (vdog_straps_claimant_t)7, &role));
    TEST_ASSERT_EQUAL_STRING("invalid-claimant", role);
}

/* out_role may be NULL on every path. */
static void test_out_role_optional(void)
{
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(0u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_PROVISIONAL,
                            vdog_straps_check_claim(21u,
                                                    VDOG_STRAPS_CLAIM_SD,
                                                    NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_OK,
                            vdog_straps_check_claim(22u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(49u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
}

/* Crosses the C/C++ link boundary: vdog_straps_cpp_smoke() is DEFINED in
 * C++ (cpp_smoke_straps.cpp) with extern "C" linkage and called from this
 * C TU. */
extern int vdog_straps_cpp_smoke(void);

static void test_cpp_smoke_linkage(void)
{
    TEST_ASSERT_EQUAL_INT(0, vdog_straps_cpp_smoke());
}

#ifdef CONFIG_IDF_TARGET_ESP32S3
/* Embedded build-only contract (`pio test -e vdog_xiao_sense_proto
 * --without-uploading --without-testing`): compile/link qualification ONLY;
 * never executed in package 1.2 Part A. */
void app_main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_table_wellformed);
    RUN_TEST(test_gate_agrees_with_table_everywhere);
    RUN_TEST(test_reserved_straps_reject_all_claims);
    RUN_TEST(test_usb_pins_reject_claims);
    RUN_TEST(test_camera_candidates_provisional_never_approved);
    RUN_TEST(test_gpio21_unclaimed_with_unresolved_sharing);
    RUN_TEST(test_microphone_rows_rejected);
    RUN_TEST(test_unclaimed_pins_pass_without_approval);
    RUN_TEST(test_invalid_inputs_are_named);
    RUN_TEST(test_out_role_optional);
    RUN_TEST(test_cpp_smoke_linkage);
    UNITY_END();
}
#else
int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_table_wellformed);
    RUN_TEST(test_gate_agrees_with_table_everywhere);
    RUN_TEST(test_reserved_straps_reject_all_claims);
    RUN_TEST(test_usb_pins_reject_claims);
    RUN_TEST(test_camera_candidates_provisional_never_approved);
    RUN_TEST(test_gpio21_unclaimed_with_unresolved_sharing);
    RUN_TEST(test_microphone_rows_rejected);
    RUN_TEST(test_unclaimed_pins_pass_without_approval);
    RUN_TEST(test_invalid_inputs_are_named);
    RUN_TEST(test_out_role_optional);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
