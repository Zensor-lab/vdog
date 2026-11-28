/*
 * Host (native environment) tests for the vdog portable strap/reserved-pin
 * table. Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases pin plan 1.2 A2b against hardware/prototype-a/pin-map.csv
 * (re-read fresh, the CSV is the single source of truth): every table row is
 * asserted and class membership cross-checked against the CSV content,
 * reserved rows (GPIO0/3/45/46 + USB pair 19/20) REJECT any claim naming pin
 * + role, camera candidates {10..18,38,39,40,47,48} and SD candidates
 * {7,8,9} return PROVISIONAL for EVERY claimant — never an approval —,
 * GPIO21's unresolved SD-CS/user-LED sharing stays UNCLAIMED (a claim is
 * PROVISIONAL naming the unresolved sharing), microphone rows {41,42} stay
 * DISABLED, SoC-absent {22..25} + SPI-flash-bus {26..32} + octal-PSRAM-bus
 * {33..37} REJECT (review H-B; the bot's probes 22/26/33 included), and a
 * full 0..48 sweep pins that EVERY gpio has a row with the class-correct
 * verdict — the silent-OK no-row path is unreachable for valid inputs.
 * Invalid gpio / claimant inputs are named programming errors. No pin is
 * configured.
 */
#include <string.h>

#include "unity.h"
#include "vdog_straps.h"

void setUp(void) {}
void tearDown(void) {}

/* Every row: flags select exactly one verdict class (or none = documented
 * free row), role present, gpio ascending and unique, no claims above the
 * SoC maximum. 49 rows: the ESP32-S3 has GPIO0..48 and ALL are covered. */
static void test_table_wellformed(void)
{
    const vdog_straps_row_t *rows = vdog_straps_table();
    unsigned n = vdog_straps_table_count();
    unsigned i;

    TEST_ASSERT_EQUAL_UINT(49u, n);
    for (i = 0; i < n; ++i) {
        const unsigned flags = (unsigned)rows[i].reserved +
                               (unsigned)rows[i].candidate +
                               (unsigned)rows[i].disabled;
        TEST_ASSERT_NOT_NULL_MESSAGE(rows[i].role, "row role");
        TEST_ASSERT_TRUE_MESSAGE(flags <= 1u, "row verdict flags (<=1 set)");
        TEST_ASSERT_LESS_OR_EQUAL_UINT8_MESSAGE(
            VDOG_STRAPS_GPIO_MAX, rows[i].gpio, "row gpio range");
        if (i > 0u) {
            TEST_ASSERT_GREATER_THAN_UINT8(rows[i - 1u].gpio, rows[i].gpio);
        }
    }
}

/* The claim gate agrees with the table everywhere, and (review H-B) EVERY
 * gpio 0..48 has a row: the no-row path must never fire for valid inputs. */
static void test_gate_agrees_with_table_everywhere(void)
{
    uint8_t gpio;

    for (gpio = 0u; gpio <= VDOG_STRAPS_GPIO_MAX; ++gpio) {
        const vdog_straps_row_t *row = vdog_straps_lookup(gpio);
        const char *role = (const char *)0x5A5A;
        vdog_straps_claim_t got =
            vdog_straps_check_claim(gpio, VDOG_STRAPS_CLAIM_GENERAL, &role);

        TEST_ASSERT_NOT_NULL_MESSAGE(row, "every gpio 0..48 has a row");
        if (row->disabled != 0u || row->reserved != 0u) {
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT, got);
            TEST_ASSERT_EQUAL_STRING(row->role, role);
        } else if (row->candidate != 0u) {
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_PROVISIONAL, got);
            TEST_ASSERT_EQUAL_STRING(row->role, role);
        } else { /* documented free/expansion row */
            TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_OK, got);
            TEST_ASSERT_NULL(role);
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

/* Camera candidates (CSV function=camera: camera,XCLK,10 / Y8,11 / Y7,12 /
 * PCLK,13 / Y6,14 / Y2,15 / Y5,16 / Y3,17 / Y4,18 / VSYNC,38 / SCCB_SCL,39
 * / SCCB_SDA,40 / HREF,47 / Y9,48): PROVISIONAL for EVERY claimant — never
 * an approval — including a plain GENERAL claim, with the role matching the
 * CSV net class. Review F-1 flip-cases: 13/38/47/48 are candidates (never
 * silently OK); 39 is a camera SCCB candidate (NOT a rejected mic pin). */
static void test_camera_candidates_provisional_never_approved(void)
{
    static const struct {
        uint8_t gpio;
        const char *role;
    } cam[] = {
        {10u, VDOG_STRAPS_ROLE_CAM_XCLK},  /* camera,XCLK,10   */
        {11u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y8,11 D6  */
        {12u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y7,12 D5  */
        {13u, VDOG_STRAPS_ROLE_CAM_SYNC},  /* camera,PCLK,13   */
        {14u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y6,14 D4  */
        {15u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y2,15 D0  */
        {16u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y5,16 D3  */
        {17u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y3,17 D1  */
        {18u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y4,18 D2  */
        {38u, VDOG_STRAPS_ROLE_CAM_SYNC},  /* camera,VSYNC,38  */
        {39u, VDOG_STRAPS_ROLE_CAM_SCCB},  /* camera,SCCB_SCL,39 */
        {40u, VDOG_STRAPS_ROLE_CAM_SCCB},  /* camera,SCCB_SDA,40 */
        {47u, VDOG_STRAPS_ROLE_CAM_SYNC},  /* camera,HREF,47   */
        {48u, VDOG_STRAPS_ROLE_CAM_DATA},  /* camera,Y9,48 D7  */
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(14u, (unsigned)(sizeof(cam) / sizeof(cam[0])));
    for (i = 0; i < sizeof(cam) / sizeof(cam[0]); ++i) {
        const vdog_straps_row_t *row = vdog_straps_lookup(cam[i].gpio);
        const char *role = NULL;
        vdog_straps_claim_t got;

        TEST_ASSERT_NOT_NULL(row);
        TEST_ASSERT_EQUAL_STRING(cam[i].role, row->role);
        got = vdog_straps_check_claim(cam[i].gpio, VDOG_STRAPS_CLAIM_CAMERA,
                                      &role);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_STRAPS_PROVISIONAL, got,
                                        "camera candidate claim");
        TEST_ASSERT_NOT_NULL(strstr(role, "candidate"));
        TEST_ASSERT_NOT_EQUAL(VDOG_STRAPS_OK, (int)got); /* not approved */

        /* A GENERAL claim on the same pins is still PROVISIONAL, not OK. */
        TEST_ASSERT_EQUAL_UINT8(
            VDOG_STRAPS_PROVISIONAL,
            vdog_straps_check_claim(cam[i].gpio, VDOG_STRAPS_CLAIM_GENERAL,
                                    &role));
    }
}

/* SD-card candidates (CSV sd,SPI_SCK,7 / SPI_MISO,8 / SPI_MOSI,9):
 * PROVISIONAL with the SD SPI role. Review F-1: GPIO7 is the SD SPI_SCK
 * candidate, NOT a camera SCCB pin. The CSV camera and SD sets are
 * disjoint — no row is both. */
static void test_sd_candidates_provisional(void)
{
    static const uint8_t sd[] = {7u, 8u, 9u}; /* sd,SPI_SCK/SPI_MISO/
                                                * SPI_MOSI @ 7/8/9 */
    size_t i;

    for (i = 0; i < sizeof(sd) / sizeof(sd[0]); ++i) {
        const vdog_straps_row_t *row = vdog_straps_lookup(sd[i]);
        const char *role = NULL;

        TEST_ASSERT_NOT_NULL(row);
        TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_SD_SPI, row->role);
        TEST_ASSERT_NOT_NULL(strstr(row->role, "SD card"));
        TEST_ASSERT_NULL(strstr(row->role, "camera"));
        TEST_ASSERT_EQUAL_UINT8(
            VDOG_STRAPS_PROVISIONAL,
            vdog_straps_check_claim(sd[i], VDOG_STRAPS_CLAIM_SD, &role));
        TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_SD_SPI, role);
    }
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

/* Microphone rows are DISABLED (CSV microphone,MIC_DATA,41 and
 * microphone,MIC_CLK,42, owner=disabled: "Do not initialize microphone or
 * drive its clock"). Review F-1: exactly 41 and 42 — GPIO39 is a camera
 * SCCB candidate, not a mic pin. */
static void test_microphone_rows_rejected(void)
{
    const char *role = NULL;

    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(41u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, role);
    TEST_ASSERT_NOT_NULL(strstr(role, "DISABLED"));

    role = NULL;
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(42u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    &role));
    TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, role);
}

/* Documented free/expansion rows ({1,2,4,5,6,43,44}, CSV
 * expansion,UNASSIGNED_*): a claim is OK — but NOT an approval of
 * ownership (approved wiring is 0.3/0.7 evidence this table cannot grant).
 * Review H-B: these carry explicit all-clear rows instead of relying on
 * the (now unreachable) no-row path. */
static void test_free_expansion_rows_pass_without_approval(void)
{
    static const uint8_t free_pins[] = {1u, 2u, 4u, 5u, 6u, 43u, 44u};
    size_t i;

    TEST_ASSERT_EQUAL_UINT(7u, (unsigned)(sizeof(free_pins) /
                                          sizeof(free_pins[0])));
    for (i = 0; i < sizeof(free_pins) / sizeof(free_pins[0]); ++i) {
        const vdog_straps_row_t *row = vdog_straps_lookup(free_pins[i]);
        const char *role = (const char *)0x5A5A;

        TEST_ASSERT_NOT_NULL_MESSAGE(row, "free pin has an explicit row");
        TEST_ASSERT_EQUAL_UINT8(0u, row->reserved);
        TEST_ASSERT_EQUAL_UINT8(0u, row->candidate);
        TEST_ASSERT_EQUAL_UINT8(0u, row->disabled);
        TEST_ASSERT_NOT_NULL(strstr(row->role, "expansion"));
        TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_OK,
                                vdog_straps_check_claim(free_pins[i],
                                                        VDOG_STRAPS_CLAIM_GENERAL,
                                                        &role));
        TEST_ASSERT_NULL(role); /* OK carries no role */
    }
}

/* Review H-B (the bot's host probes): SoC-absent and shared-bus pins
 * REJECT instead of returning OK. 22-25 do not exist on the ESP32-S3
 * (bonds out 0-21 and 26-48 only), 26-32 are the SPI flash bus, 33-37 the
 * octal-PSRAM bus this baseline (CONFIG_SPIRAM_MODE_OCT) uses. */
static void test_soc_absent_and_bus_pins_reject(void)
{
    static const uint8_t absent[] = {22u, 23u, 24u, 25u};
    static const uint8_t flash_bus[] = {26u, 27u, 28u, 29u, 30u, 31u, 32u};
    static const uint8_t psram_bus[] = {33u, 34u, 35u, 36u, 37u};
    const vdog_straps_claimant_t claimants[] = {
        VDOG_STRAPS_CLAIM_GENERAL, VDOG_STRAPS_CLAIM_CAMERA,
        VDOG_STRAPS_CLAIM_SD};
    size_t i;
    size_t j;

    for (i = 0; i < sizeof(absent) / sizeof(absent[0]); ++i) {
        TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_ABSENT,
                                 vdog_straps_lookup(absent[i])->role);
        for (j = 0; j < sizeof(claimants) / sizeof(claimants[0]); ++j) {
            const char *role = NULL;
            TEST_ASSERT_EQUAL_UINT8_MESSAGE(
                VDOG_STRAPS_REJECT,
                vdog_straps_check_claim(absent[i], claimants[j], &role),
                "absent GPIO claim");
            TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_ABSENT, role);
        }
    }
    for (i = 0; i < sizeof(flash_bus) / sizeof(flash_bus[0]); ++i) {
        TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_FLASH_BUS,
                                 vdog_straps_lookup(flash_bus[i])->role);
        TEST_ASSERT_EQUAL_UINT8(
            VDOG_STRAPS_REJECT,
            vdog_straps_check_claim(flash_bus[i], VDOG_STRAPS_CLAIM_SD,
                                    NULL));
    }
    for (i = 0; i < sizeof(psram_bus) / sizeof(psram_bus[0]); ++i) {
        TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_PSRAM_BUS,
                                 vdog_straps_lookup(psram_bus[i])->role);
        TEST_ASSERT_EQUAL_UINT8(
            VDOG_STRAPS_REJECT,
            vdog_straps_check_claim(psram_bus[i], VDOG_STRAPS_CLAIM_CAMERA,
                                    NULL));
    }

    /* The bot's exact round-2 probes: 22/26/33 must NOT be OK. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(22u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(26u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                            vdog_straps_check_claim(33u,
                                                    VDOG_STRAPS_CLAIM_GENERAL,
                                                    NULL));
}

static int in_set(const uint8_t *set, size_t n, uint8_t gpio)
{
    size_t i;

    for (i = 0; i < n; ++i) {
        if (set[i] == gpio) {
            return 1;
        }
    }
    return 0;
}

/* Review F-1 + H-B cross-check: the table's class MEMBERSHIP must equal
 * the documented sources exactly (sets transcribed from
 * hardware/prototype-a/pin-map.csv with their function,net,soc_gpio
 * citations, plus the ESP-IDF GPIO-reference classes): reserved =
 * plan-mandated straps (0/3/45/46) + CSV control/BOOT,0 + usb,USB_D_MINUS,19
 * + usb,USB_D_PLUS,20; candidates = CSV camera 10..18/38..40/47/48 + CSV sd
 * 7/8/9 (+ the 21 unclaimed-UNRESOLVED row); disabled = CSV microphone
 * 41/42; absent 22..25, flash bus 26..32, PSRAM bus 33..37 (ESP-IDF GPIO
 * Peripherals reference + octal-PSRAM baseline); free = CSV
 * expansion,UNASSIGNED_* {1,2,4,5,6,43,44}. No extras, no omissions. */
static void test_table_membership_matches_pin_map_csv(void)
{
    static const uint8_t csv_camera[] = {10u, 11u, 12u, 13u, 14u, 15u, 16u,
                                         17u, 18u, 38u, 39u, 40u, 47u, 48u};
    static const uint8_t csv_sd[] = {7u, 8u, 9u};
    static const uint8_t csv_mic_disabled[] = {41u, 42u};
    static const uint8_t reserved_pins[] = {0u, 3u, 19u, 20u, 45u, 46u};
    static const uint8_t absent_pins[] = {22u, 23u, 24u, 25u};
    static const uint8_t flash_bus_pins[] = {26u, 27u, 28u, 29u, 30u, 31u,
                                             32u};
    static const uint8_t psram_bus_pins[] = {33u, 34u, 35u, 36u, 37u};
    static const uint8_t free_pins[] = {1u, 2u, 4u, 5u, 6u, 43u, 44u};
    const vdog_straps_row_t *rows = vdog_straps_table();
    unsigned n = vdog_straps_table_count();
    unsigned i;
    unsigned n_reserved = 0u;
    unsigned n_candidate = 0u;
    unsigned n_disabled = 0u;
    unsigned n_free = 0u;

#define IN_SET(s) in_set((s), sizeof(s) / sizeof((s)[0]), rows[i].gpio)

    for (i = 0; i < n; ++i) {
        const unsigned flags = (unsigned)rows[i].reserved +
                               (unsigned)rows[i].candidate +
                               (unsigned)rows[i].disabled;
        int classes = 0;

        n_reserved += rows[i].reserved;
        n_candidate += rows[i].candidate;
        n_disabled += rows[i].disabled;
        n_free += (flags == 0u) ? 1u : 0u;

        /* Every row sits in EXACTLY one documented class set. */
        classes += IN_SET(csv_camera) || IN_SET(csv_sd) ||
                   (rows[i].gpio == 21u);
        classes += IN_SET(csv_mic_disabled);
        classes += IN_SET(reserved_pins) || IN_SET(absent_pins) ||
                   IN_SET(flash_bus_pins) || IN_SET(psram_bus_pins);
        classes += IN_SET(free_pins);
        TEST_ASSERT_EQUAL_UINT_MESSAGE(1u, (unsigned)classes,
                                       "row sits in exactly one class set");

        if (rows[i].disabled != 0u) {
            TEST_ASSERT_TRUE_MESSAGE(IN_SET(csv_mic_disabled),
                                     "disabled row not CSV mic");
            TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_MIC, rows[i].role);
        } else if (rows[i].reserved != 0u) {
            if (IN_SET(absent_pins)) {
                TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_ABSENT,
                                         rows[i].role);
            } else if (IN_SET(flash_bus_pins)) {
                TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_FLASH_BUS,
                                         rows[i].role);
            } else if (IN_SET(psram_bus_pins)) {
                TEST_ASSERT_EQUAL_STRING(VDOG_STRAPS_ROLE_PSRAM_BUS,
                                         rows[i].role);
            } else {
                TEST_ASSERT_TRUE_MESSAGE(IN_SET(reserved_pins),
                                         "reserved row not plan/CSV");
            }
        } else if (rows[i].candidate != 0u) {
            TEST_ASSERT_TRUE_MESSAGE(
                IN_SET(csv_camera) || IN_SET(csv_sd) ||
                    rows[i].gpio == 21u,
                "candidate row not CSV camera/sd/21");
            if (IN_SET(csv_camera)) {
                TEST_ASSERT_NOT_NULL(strstr(rows[i].role, "camera"));
                TEST_ASSERT_NULL(strstr(rows[i].role, "SD"));
            }
            if (IN_SET(csv_sd)) {
                TEST_ASSERT_NOT_NULL(strstr(rows[i].role, "SD card"));
                TEST_ASSERT_NULL(strstr(rows[i].role, "camera"));
            }
            if (rows[i].gpio == 21u) {
                TEST_ASSERT_NOT_NULL(strstr(rows[i].role, "UNRESOLVED"));
            }
        } else { /* free row */
            TEST_ASSERT_TRUE_MESSAGE(IN_SET(free_pins),
                                     "all-clear row not CSV expansion set");
            TEST_ASSERT_NOT_NULL(strstr(rows[i].role, "expansion"));
        }
        /* The camera and SD candidate sets are disjoint in the CSV: no row
         * may carry both halves in its role. */
        if (IN_SET(csv_camera) && IN_SET(csv_sd)) {
            TEST_FAIL_MESSAGE("camera/sd sets must be disjoint");
        }
    }

    /* Class totals: 6 plan/CSV reserved + 4 absent + 7 flash + 5 PSRAM =
     * 22 reserved; 14 camera + 3 SD + GPIO21 = 18 candidates; 2 mic; 7
     * free; total 49 = every gpio 0..48. */
    TEST_ASSERT_EQUAL_UINT(22u, n_reserved);
    TEST_ASSERT_EQUAL_UINT(18u, n_candidate); /* 14 cam + 3 sd + GPIO21 */
    TEST_ASSERT_EQUAL_UINT(2u, n_disabled);
    TEST_ASSERT_EQUAL_UINT(7u, n_free);
    TEST_ASSERT_EQUAL_UINT(49u, n);

    /* Spot-pin the reviewer-probed flips (round 1 F-1): the pins that were
     * missing/wrong before answer from the table now. */
    {
        static const uint8_t must_be_provisional[] = {13u, 38u, 39u, 40u, 47u,
                                                      48u};
        size_t j;
        for (j = 0; j < sizeof(must_be_provisional) /
                      sizeof(must_be_provisional[0]);
             ++j) {
            TEST_ASSERT_EQUAL_UINT8_MESSAGE(
                VDOG_STRAPS_PROVISIONAL,
                vdog_straps_check_claim(must_be_provisional[j],
                                        VDOG_STRAPS_CLAIM_GENERAL, NULL),
                "CSV candidate must not return OK");
        }
        TEST_ASSERT_EQUAL_UINT8(VDOG_STRAPS_REJECT,
                                vdog_straps_check_claim(42u,
                                                        VDOG_STRAPS_CLAIM_GENERAL,
                                                        NULL));
    }
#undef IN_SET
}

/* Review H-B: full 0..48 sweep — every gpio has a row AND the gate returns
 * the class-correct verdict; the no-row/OK path is unreachable for valid
 * inputs (only gpio > 48 rejects as a programming error, pinned elsewhere).
 */
static void test_full_sweep_covers_every_gpio(void)
{
    static const uint8_t candidates[] = {7u,  8u,  9u,  10u, 11u, 12u,
                                         13u, 14u, 15u, 16u, 17u, 18u,
                                         21u, 38u, 39u, 40u, 47u, 48u};
    static const uint8_t rejects_real[] = {
        0u,  3u,  19u, 20u, 22u, 23u, 24u, 25u, 26u, 27u, 28u,
        29u, 30u, 31u, 32u, 33u, 34u, 35u, 36u, 37u, 41u, 42u,
        45u, 46u};
    static const uint8_t free_only[] = {1u, 2u, 4u, 5u, 6u, 43u, 44u};
    uint8_t gpio;

    for (gpio = 0u; gpio <= VDOG_STRAPS_GPIO_MAX; ++gpio) {
        const vdog_straps_row_t *row = vdog_straps_lookup(gpio);
        const vdog_straps_claimant_t claimants[] = {
            VDOG_STRAPS_CLAIM_GENERAL, VDOG_STRAPS_CLAIM_CAMERA,
            VDOG_STRAPS_CLAIM_SD};
        size_t c;
        vdog_straps_claim_t want;

        TEST_ASSERT_NOT_NULL_MESSAGE(row, "table must cover every gpio");

        if (in_set(candidates, sizeof(candidates) / sizeof(candidates[0]),
                   gpio)) {
            want = VDOG_STRAPS_PROVISIONAL;
        } else if (in_set(rejects_real,
                          sizeof(rejects_real) / sizeof(rejects_real[0]),
                          gpio)) {
            want = VDOG_STRAPS_REJECT;
        } else if (in_set(free_only, sizeof(free_only) / sizeof(free_only[0]),
                          gpio)) {
            want = VDOG_STRAPS_OK;
        } else {
            TEST_FAIL_MESSAGE("gpio in no expected class");
            return;
        }
        for (c = 0; c < sizeof(claimants) / sizeof(claimants[0]); ++c) {
            TEST_ASSERT_EQUAL_UINT8_MESSAGE(
                want, vdog_straps_check_claim(gpio, claimants[c], NULL),
                "sweep verdict must match class");
        }
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
                            vdog_straps_check_claim(44u,
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
    RUN_TEST(test_sd_candidates_provisional);
    RUN_TEST(test_gpio21_unclaimed_with_unresolved_sharing);
    RUN_TEST(test_microphone_rows_rejected);
    RUN_TEST(test_free_expansion_rows_pass_without_approval);
    RUN_TEST(test_soc_absent_and_bus_pins_reject);
    RUN_TEST(test_table_membership_matches_pin_map_csv);
    RUN_TEST(test_full_sweep_covers_every_gpio);
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
    RUN_TEST(test_sd_candidates_provisional);
    RUN_TEST(test_gpio21_unclaimed_with_unresolved_sharing);
    RUN_TEST(test_microphone_rows_rejected);
    RUN_TEST(test_free_expansion_rows_pass_without_approval);
    RUN_TEST(test_soc_absent_and_bus_pins_reject);
    RUN_TEST(test_table_membership_matches_pin_map_csv);
    RUN_TEST(test_full_sweep_covers_every_gpio);
    RUN_TEST(test_invalid_inputs_are_named);
    RUN_TEST(test_out_role_optional);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
