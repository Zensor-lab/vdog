/*
 * Host (native environment) tests for the vdog portable recovery/identity
 * core. Run with: pio test -d firmware -e native   (HOST evidence only)
 *
 * These cases pin plan 1.2 A2/§A4 as corrected by reviews M-C/R2-A and
 * M-D/R2-B: the classifier accepts ONLY the COMPLETE documented ROM-line
 * forms (esptool ESP32-S3 "Boot Mode Selection", Boot Log / Boot Mode
 * Message) — optional "rst:0xNN (CAUSE)," prefix plus "boot:0xNN (BANNER)"
 * whose banner WHOLE-matches the closed supported set
 * (SPI_FAST_FLASH_BOOT -> normal; DOWNLOAD(USB/UART0) and
 * DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2) -> download). The doc's
 * unsupported spellings (SPI_FLASH_BOOT, SDIO_REI_FEO_V1_BOOT, ATE_BOOT),
 * prose in the parentheses ("download failed"), lookalikes
 * (SPI_FAST_FLASH_BOOTT, "SPI_FAST_FLASH_BOOT extra") and structurally
 * broken prefixes stay UNKNOWN — never guessed; the reset cause is exposed
 * through vdog_recovery_classify_boot() (lead finding 1b) and the old
 * entry point is a documented wrapper. Identity: closed-set chip model,
 * narrow "vdg-" project label (never a hardware identifier — no MAC
 * spelling stores or renders), MAC-tail-only storage. No device.
 */
#include <string.h>

#include "unity.h"
#include "vdog_core.h"
#include "vdog_mem.h"
#include "vdog_recovery.h"

void setUp(void) {}
void tearDown(void) {}

/* ---- documented ROM-line forms (review R2-A) ----------------------------- */

#define ROM_POWERON_NORMAL "rst:0x1 (POWERON_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)"
#define ROM_RTCWDT_NORMAL "rst:0x9 (RTCWDT_SYS_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)"
#define ROM_DOC_DOWNLOAD \
    "rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))"
#define ROM_USB_DOWNLOAD "rst:0x1 (POWERON_RESET),boot:0x0 (DOWNLOAD(USB/UART0))"
#define ROM_BARE_NORMAL "boot:0x3 (SPI_FAST_FLASH_BOOT)"

static void test_classify_normal_documented_lines(void)
{
    /* The reviewer's exact round-2 probe (was UNKNOWN under the old
     * line-start anchor; now classifies). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_POWERON_NORMAL));
    /* Hard-reset style cause still classifies the banner. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_RTCWDT_NORMAL));
    /* No rst: prefix at all (banner-only line). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_BARE_NORMAL));
    /* Case-insensitive + hyphen/underscore-equivalent whole match. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x3 (spi_fast_flash_boot)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x3 (SPI-FAST-FLASH-BOOT)"));
    /* Leading/trailing blanks are padding; a blank between hex and "(" is
     * the one documented inter-field gap. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("  boot:0x3 (SPI_FAST_FLASH_BOOT) "));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify("boot:0x3  (SPI_FAST_FLASH_BOOT)"));
}

static void test_classify_download_documented_lines(void)
{
    /* The esptool doc line VERBATIM (reviewer: previously UNKNOWN). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify(ROM_DOC_DOWNLOAD));
    /* BOOT-button download via the USB/UART0 spelling. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify(ROM_USB_DOWNLOAD));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0xf (DOWNLOAD(USB/UART0))"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify("boot:0x3 (download_boot(uart0/uart1/sdio_rei_reo_v2))"));
}

/* The doc's UNSUPPORTED modes and every near-miss are UNKNOWN — the
 * banner must EQUAL a closed-set spelling, whole. */
static void test_classify_unsupported_and_lookalikes_unknown(void)
{
    static const char *const junk[] = {
        /* Documented-unsupported modes (never "closest class"). */
        "boot:0x5 (SPI_FLASH_BOOT)",
        "boot:0x1 (SDIO_REI_FEO_V1_BOOT)",
        "boot:0x2 (ATE_BOOT)",
        /* Truncated / extended / decorated lookalikes. */
        "boot:0x3 (SPI_FAST_FLASH_BOOTT)",
        "boot:0x3 (SPI_FAST_FLASH)",        /* the M-C-era acceptance gone  */
        "boot:0x8 (SPI_FAST_FLASH_BOOT extra)",
        "boot:0x0 (download failed)",       /* prose inside parens          */
        "boot:0x3 (DOWNLOAD)",
        "boot:0x7 (UART_DOWNLOAD)",
        "boot:0x6 (SDIO_DOWNLOAD)",
        "boot:0x8 (SPI_FAST_DOWNLOAD)",
        "boot:0x1 (SPI_BOOT)",
        "boot:0x1 (basic)",
        /* USB-JTAG has NO documented S3 spelling: the reserved enum is
         * never returned from the classifier. */
        "boot:0x1 (USB_JTAG)",
        "boot:0x1 (USB-JTAG/serial)",
        "boot:0xf (USB_SERIAL_JTAG)",
        "boot:0x9 (USB_JTAG_DOWNLOAD)",
        /* Structural lookalikes of the anchored form. */
        "spi_fas",
        "boot:0x",
        "boot:0x27",
        "boot:0x3 (SPI_FAST_FLASH_BOOT",                    /* unclosed      */
        "boot:0x3(SPI_FAST_FLASH_BOOT",                     /* unclosed tail */
        "boot:0x3 (SPI_FAST_FLASH_BOOT )",                  /* inner blank   */
        "boot:0xzz (SPI_FAST_FLASH_BOOT)",
        "boot:0x100 (SPI_FAST_FLASH_BOOT)",                 /* 3 hex digits  */
        "boot:0x3 (SPI_FAST_FLASH_BOOT)trailing",
        "boot:0x3 (SPI_FAST_FLASH BOOT)",                   /* space inside  */
        "xboot:0x3 (SPI_FAST_FLASH_BOOT)"
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(28u, (unsigned)(sizeof(junk) / sizeof(junk[0])));
    for (i = 0; i < sizeof(junk) / sizeof(junk[0]); ++i) {
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_MODE_UNKNOWN,
                                        vdog_recovery_classify(junk[i]), junk[i]);
    }
}

/* Prose merely CONTAINING tokens, and rst-only lines (no boot part). */
static void test_classify_prose_and_rst_only_unknown(void)
{
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(NULL));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify(""));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, vdog_recovery_classify("   "));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("download failed"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot loader"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("fast pattern"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("Waiting for bit flip in download mode"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("ets Jun  8 2016 00:22:57"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("Invalid header 0x3fffffb0 at 0x3c0000"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("rst:0x1 (POWERON_RESET)"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("rst:0x1 (POWERON_RESET),"));
}

/* Documented line-ending policy (header): trailing CR/LF/blanks stripped
 * at entry — CRLF, LF and bare-CR captures classify identically; an inner
 * newline (not trailing) is junk. */
static void test_classify_line_ending_policy(void)
{
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_POWERON_NORMAL "\r\n"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_POWERON_NORMAL "\n"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_POWERON_NORMAL "\r"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD,
                            vdog_recovery_classify(ROM_USB_DOWNLOAD "\r\n"));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL,
                            vdog_recovery_classify(ROM_BARE_NORMAL "\n \t"));
    /* A newline mid-line is NOT a trailing terminator: UNKNOWN. */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN,
                            vdog_recovery_classify("boot:0x3 (SPI_FAST_FLASH_BOOT)\nmore"));
}

/* The rst: prefix is all-or-nothing: a structurally broken prefix makes
 * the WHOLE line UNKNOWN even when the boot banner is perfect (review
 * R2-A). */
static void test_classify_rst_prefix_structure(void)
{
    static const char *const broken[] = {
        "rst:0x1 (POWERON_RESET)boot:0x3 (SPI_FAST_FLASH_BOOT)",  /* no comma   */
        "rst:0x (POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)",  /* no digits  */
        "rst:0x100 (POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", /* 3 digits */
        "rst:0x1 (POWER ON),boot:0x3 (SPI_FAST_FLASH_BOOT)",      /* space      */
        "rst:0x1 (),boot:0x3 (SPI_FAST_FLASH_BOOT)",              /* empty      */
        "rst:0x1 (POWERON-RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", /* hyphen     */
        "rst:0x1 (POWERON_RESET,,boot:0x3 (SPI_FAST_FLASH_BOOT)", /* stray ,    */
        "rst:0x1 POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)",  /* no (       */
        "rst:0x1 (AAAAAAAAAAAAAAAAAAAAAAAA),boot:0x3 (SPI_FAST_FLASH_BOOT)" /* 24 */
    };
    size_t i;

    TEST_ASSERT_EQUAL_UINT(9u, (unsigned)(sizeof(broken) / sizeof(broken[0])));
    for (i = 0; i < sizeof(broken) / sizeof(broken[0]); ++i) {
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_MODE_UNKNOWN,
                                        vdog_recovery_classify(broken[i]),
                                        broken[i]);
    }
}

/* ---- reset-cause evidence (review R2-A, lead finding 1b) ------------------ */

static void test_boot_evidence_poweron_verbatim(void)
{
    vdog_boot_evidence_t ev;

    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_POWERON_NORMAL, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("POWERON_RESET", ev.cause_name);
    /* The wrapper agrees with the extended entry point (same parse). */
    TEST_ASSERT_EQUAL_UINT8((uint8_t)ev.boot_mode,
                            (uint8_t)vdog_recovery_classify(ROM_POWERON_NORMAL));
}

static void test_boot_evidence_cause_states(void)
{
    vdog_boot_evidence_t ev;

    /* No prefix: NONE, nothing recorded. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_BARE_NORMAL, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(0u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);

    /* Two-digit reset values (ROM prints 1..2 hex digits). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x15 (USB_UART_CHIP_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(21u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("USB_UART_CHIP_RESET", ev.cause_name);

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x17 (POWER_GLITCH_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(23u, ev.rst_value);

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xf (RTCWDT_BROWN_OUT_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(15u, ev.rst_value);

    /* Download line carries its cause too. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_USB_DOWNLOAD, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("POWERON_RESET", ev.cause_name);

    /* UNRECOGNISED cause: well-formed token not in the RESET_REASON set —
     * the boot-mode verdict still stands (cause vocab never vetoes), and
     * the name is kept VERBATIM for the transcript cross-check. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (SOMETHING_NEW),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("SOMETHING_NEW", ev.cause_name);
}

/* Evidence commit discipline + argument contracts. */
static void test_boot_evidence_arg_contracts(void)
{
    vdog_boot_evidence_t ev;

    /* NULL out is the invalid-arg case. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_recovery_classify_boot(ROM_BARE_NORMAL, NULL));

    /* NULL line: OK with cleared UNKNOWN evidence. */
    memset(&ev, 0xA5, sizeof(ev));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(NULL, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);

    /* init clears a dirty struct. */
    memset(&ev, 0xA5, sizeof(ev));
    vdog_boot_evidence_init(&ev);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(0u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);

    /* NO HALF CLAIMS: a recognized rst: prefix with an unrecognized
     * banner yields fully cleared evidence (the line proves nothing). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (POWERON_RESET),boot:0x3 (SPI_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_UNKNOWN, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(0u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
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

/* ---- sanitized identity (reviews M-D / R2-B) ------------------------------ */

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
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-001"));
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
        "mac=**:**:**:**:ab:cd board=vdg-001",
        buf);
}

/* THE sanitizer proof (plan 1.2 acceptance 5): the struct stores ONLY a
 * 16-bit tail, and the line can only ever contain the last two octets. */
static void test_identity_mac_storage_cannot_hold_a_full_mac(void)
{
    vdog_identity_t id = full_identity();
    char buf[256];

    TEST_ASSERT_EQUAL_UINT(2u,
                           (unsigned)sizeof(((vdog_identity_t *)0)->mac_tail));

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

    /* An out-of-range enum value collapses to the fixed "unknown"
     * spelling — never a caller string. */
    vdog_identity_set_chip_model(&id, (vdog_identity_chip_t)99);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("chip=unknown rev=0.0", buf);
    TEST_ASSERT_EQUAL_UINT8((uint8_t)VDOG_IDENTITY_CHIP_UNKNOWN,
                            (uint8_t)id.chip_model);

    /* NULL id is a documented no-op. */
    vdog_identity_set_chip_model(NULL, VDOG_IDENTITY_CHIP_ESP32S3);
}

/* Review R2-B: NO MAC spelling stores — exact 12-hex, 0x-prefixed, and
 * every grouping whose non-alnum-stripped form is 12 hex digits. */
static void test_identity_board_tag_mac_spellings_rejected(void)
{
    static const char *const macs[] = {
        "abcdef012345",   /* exact 12-hex (the M-D case)                */
        "ABCDEF012345",
        "aabbccddeeff",
        "AABBCCDDEEFF",   /* uppercase compact                          */
        "0x001122334455", /* 0x-prefixed (accepted by the old validator) */
        "0X001122334455",
        "001122-334455",  /* hyphen-grouped (accepted by the old one)   */
        "00:11:22:33:44:55",
        "0011.2233.4455",
        "vdg-0x001122334455" /* even behind the label prefix: MAC shape */
    };
    vdog_identity_t id;
    size_t i;

    vdog_identity_init(&id);
    TEST_ASSERT_EQUAL_UINT(10u, (unsigned)(sizeof(macs) / sizeof(macs[0])));
    for (i = 0; i < sizeof(macs) / sizeof(macs[0]); ++i) {
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_ERR_IDENTITY_TAG,
                                      vdog_identity_set_board_tag(&id, macs[i]),
                                      macs[i]);
        TEST_ASSERT_EQUAL_CHAR('\0', id.board_tag[0]); /* never half-stored */
    }
}

/* Review R2-B: the narrow project-label format vdg-[A-Za-z0-9_]{1,11}. */
static void test_identity_board_tag_format(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);

    /* Accepted labels (prefix case-insensitive; body [A-Za-z0-9_]). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-001"));
    TEST_ASSERT_EQUAL_STRING("vdg-001", id.board_tag);
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "vdg-PrototypeA"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "VDG-001"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-a"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-A_1"));
    /* 15-char boundary: "vdg-" + 11 body chars fits (NUL in the 16th). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_identity_set_board_tag(&id, "vdg-AbCdEfGhIj1"));
    TEST_ASSERT_EQUAL_UINT(15u, strlen(id.board_tag));

    /* Rejected shapes — including what the OLD validator wrongly accepted
     * or the old tests wrongly used ("proto-a1": no project prefix). */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "proto-a1"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg001"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg--"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-a b"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-a.b"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-a:b"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-a/b"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "xvdg-001"));
    /* Too long for the field (body 12, no room for the NUL). */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "vdg-AbCdEfGhIj12"));
    /* Unterminated array within capacity: bounded scan, no store, no OOB
     * read. */
    {
        char unterminated[VDOG_IDENTITY_TAG_MAX];
        /* All 16 bytes non-NUL (15 chars + the 16th), so the bounded
         * scan must run to capacity and reject — no OOB read. */
        memcpy(unterminated, "vdg-AbCdEfGhIjk", 15u);
        unterminated[15] = 'l';
        TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                              vdog_identity_set_board_tag(&id, unterminated));
    }

    /* A rejected set attempt leaves the previously valid tag UNCHANGED. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-keepme"));
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_IDENTITY_TAG,
                          vdog_identity_set_board_tag(&id, "no spaces here"));
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NOT_NULL(strstr(buf, "board=vdg-keepme"));

    /* NULL/"" clear the tag; the board= section then disappears. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, NULL));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, ""));
    /* NULL id is the invalid-arg case. */
    TEST_ASSERT_EQUAL_INT(VDOG_ERR_INVALID_ARG,
                          vdog_identity_set_board_tag(NULL, "vdg-001"));
}

/* Reviews M-D/R2-B defense in depth: bytes that bypassed the setter (raw
 * struct writes) are still never rendered — the formatter re-validates
 * with the same bounded scan and omits an invalid tag entirely. */
static void test_identity_render_never_emits_unvalidated_bytes(void)
{
    vdog_identity_t id;
    char buf[256];

    vdog_identity_init(&id);
    vdog_identity_set_chip_model(&id, VDOG_IDENTITY_CHIP_ESP32S3);

    /* Every MAC spelling smuggled straight into the array: not rendered. */
    memcpy(id.board_tag, "0x001122334455", 15u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_NULL(strstr(buf, "001122334455"));

    memcpy(id.board_tag, "001122-334455", 14u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_NULL(strstr(buf, "001122"));

    memcpy(id.board_tag, "AABBCCDDEEFF", 13u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));
    TEST_ASSERT_NULL(strstr(buf, "AABBCCDDEEFF"));

    memcpy(id.board_tag, "abcdef012345", 13u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));

    /* Unterminated garbage: bounded scan, no crash, nothing rendered. */
    memset(id.board_tag, 'v', sizeof(id.board_tag));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));

    /* Format violation (missing prefix / space): same omission. */
    memcpy(id.board_tag, "ok tag", 7u);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NULL(strstr(buf, "board="));

    /* Positive control: the SAME formatter renders a setter-validated tag. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_set_board_tag(&id, "vdg-ok1"));
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_identity_format(&id, buf, sizeof(buf)));
    TEST_ASSERT_NOT_NULL(strstr(buf, "board=vdg-ok1"));
}

/* Review F-2: the SDK chip-info revision is DECIMAL MXX (major*100 + minor,
 * the SDK chip-info header wording). Table-pinned decode: a byte split
 * would render S3 v1.1 (raw 101) as the nonsense 0.101. */
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
        "board=vdg-001",
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
        "mac=**:**:**:**:ab:cd board=vdg-001";
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
    RUN_TEST(test_classify_normal_documented_lines);
    RUN_TEST(test_classify_download_documented_lines);
    RUN_TEST(test_classify_unsupported_and_lookalikes_unknown);
    RUN_TEST(test_classify_prose_and_rst_only_unknown);
    RUN_TEST(test_classify_line_ending_policy);
    RUN_TEST(test_classify_rst_prefix_structure);
    RUN_TEST(test_boot_evidence_poweron_verbatim);
    RUN_TEST(test_boot_evidence_cause_states);
    RUN_TEST(test_boot_evidence_arg_contracts);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_marks_nothing);
    RUN_TEST(test_identity_exact_line);
    RUN_TEST(test_identity_mac_storage_cannot_hold_a_full_mac);
    RUN_TEST(test_identity_chip_model_is_closed_set);
    RUN_TEST(test_identity_board_tag_mac_spellings_rejected);
    RUN_TEST(test_identity_board_tag_format);
    RUN_TEST(test_identity_render_never_emits_unvalidated_bytes);
    RUN_TEST(test_identity_revision_mxx_decode);
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
    RUN_TEST(test_classify_normal_documented_lines);
    RUN_TEST(test_classify_download_documented_lines);
    RUN_TEST(test_classify_unsupported_and_lookalikes_unknown);
    RUN_TEST(test_classify_prose_and_rst_only_unknown);
    RUN_TEST(test_classify_line_ending_policy);
    RUN_TEST(test_classify_rst_prefix_structure);
    RUN_TEST(test_boot_evidence_poweron_verbatim);
    RUN_TEST(test_boot_evidence_cause_states);
    RUN_TEST(test_boot_evidence_arg_contracts);
    RUN_TEST(test_boot_mode_names);
    RUN_TEST(test_identity_init_marks_nothing);
    RUN_TEST(test_identity_exact_line);
    RUN_TEST(test_identity_mac_storage_cannot_hold_a_full_mac);
    RUN_TEST(test_identity_chip_model_is_closed_set);
    RUN_TEST(test_identity_board_tag_mac_spellings_rejected);
    RUN_TEST(test_identity_board_tag_format);
    RUN_TEST(test_identity_render_never_emits_unvalidated_bytes);
    RUN_TEST(test_identity_revision_mxx_decode);
    RUN_TEST(test_identity_absent_parts);
    RUN_TEST(test_identity_refuses_rejected_mem_set);
    RUN_TEST(test_identity_buffer_semantics);
    RUN_TEST(test_cpp_smoke_linkage);
    return UNITY_END();
}
#endif
