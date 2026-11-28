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
#include <stdio.h>
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
    /* "POWERON_RESET" is the accepted rtc.h/esptool-doc ALIAS of value 1;
     * the structured name is the canonical ROM print "POWERON" (R3-A/R3-B). */
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("POWERON", ev.cause_name);
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

    /* Download line carries its cause too (alias spelling -> canonical). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_USB_DOWNLOAD, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_DOWNLOAD, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("POWERON", ev.cause_name);

    /* UNRECOGNISED cause: well-formed token with no (value, name) pair in
     * the cited table — the boot-mode verdict still stands (cause vocab
     * never vetoes), and the token is NOT copied into the evidence
     * (review R3-B): the structured name is "" with every byte zero. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (SOMETHING_NEW),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value); /* parsed value recorded    */
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));
}

/* Review R3-A: the ROM's OWN printed spellings classify KNOWN — the
 * old table wrongly demanded the rtc.h enum names. Round 5: the
 * spellings are now the ESP32-S3 ROM's own label table extracted from
 * the vendor ROM ELF (provenance in core/vdog_recovery.c); published
 * captures (partitions_ota README, boot-log docs) corroborate. */
static void test_boot_evidence_rom_printed_aliases(void)
{
    vdog_boot_evidence_t ev;

    /* examples/system/ota/partitions_ota/README.md verbatim. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(1u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("POWERON", ev.cause_name);

    /* rst:0xc (RTC_SW_CPU_RST) — ROM label differs from rtc.h enum name
     * (RTC_SW_CPU_RESET); both accepted, canonical is the label. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(12u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("RTC_SW_CPU_RST", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xc (RTC_SW_CPU_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("RTC_SW_CPU_RST", ev.cause_name);

    /* Round-5 reconciliation: the S3 ROM prints DSLEEP at 5 (the old
     * "C-series only" note was WRONG for this ROM); the rtc.h enum
     * DEEPSLEEP_RESET stays accepted and stores the label. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x5 (DSLEEP),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(5u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("DSLEEP", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x5 (DEEPSLEEP_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(5u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("DSLEEP", ev.cause_name);

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x16 (USB_JTAG_CHIP_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(22u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("USB_JTAG_CHIP_RESET", ev.cause_name);

    /* ROM label at 0x10 is RTCWDT_RTC_RST (extracted); the enum/published
     * RTCWDT_RTC_RESET form stays accepted (alias). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x10 (RTCWDT_RTC_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(16u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("RTCWDT_RTC_RST", ev.cause_name);

    /* Case-insensitivity of the pair match (documented). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (poweron),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("POWERON", ev.cause_name);
}

/* Review R3-A: KNOWN requires VALUE <-> NAME agreement. A known name
 * with the wrong value, or a known value with the wrong name, is
 * UNRECOGNISED — and the boot verdict still comes from the banner. */
static void test_boot_evidence_pair_mismatch(void)
{
    vdog_boot_evidence_t ev;

    /* The bot's probe: 0xf (POWERON_RESET) — POWERON_RESET is known (at
     * 0x1) but value 15 pairs with BROWNOUT_RST (ROM label) /
     * RTCWDT_BROWN_OUT_RESET (enum). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xf (POWERON_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(15u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));

    /* The bot's probe: 0x1 (RTC_SW_CPU_RST) — known name, wrong value. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (RTC_SW_CPU_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);

    /* Wrong-value spellings of the OTHER alias form too. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (RTC_SW_CPU_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xc (POWERON),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);

    /* Value outside the table entirely (0x22=34): UNRECOGNISED. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x22 (INTRUSION_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);

    /* Review round 4: the shortened ROM-print aliases pair ONLY with
     * their own value — each bot probe form against a wrong value is
     * UNRECOGNISED (verdict still from the banner), never "closest". */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x3 (TG0WDT_SYS_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x7 (RTC_SW_SYS_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x8 (TG0WDT_SYS_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x12 (RTC_SW_SYS_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);

    /* Round-5 ROM-table audit: RTCWDT_SYS_RST at 9 IS a ROM label (it was
     * wrongly pinned OUT on the publication hunt) — now KNOWN, canonical
     * is the label. RTCWDT_BROWN_OUT_RST at 0xf stays UNRECOGNISED: the
     * extracted label is BROWNOUT_RST and the enum is
     * RTCWDT_BROWN_OUT_RESET — this invented shortening is neither. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x9 (RTCWDT_SYS_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(9u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("RTCWDT_SYS_RST", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xf (RTCWDT_BROWN_OUT_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    /* Codes where the ROM table carries no label (shared "N/A" at
     * indices 0/2/4/6/14) never pair — even with a real label's token. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x2 (POWERON),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xe (EFUSE_RST),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
}

/* grep-style substring search over the RAW evidence bytes. */
static const unsigned char *ev_find_bytes(const vdog_boot_evidence_t *ev,
                                          const char *needle)
{
    const unsigned char *b = (const unsigned char *)ev;
    const size_t n = sizeof(*ev);
    const size_t m = strlen(needle);
    size_t i;
    size_t j;

    for (i = 0; i + m <= n; ++i) {
        for (j = 0; j < m; ++j) {
            if (b[i + j] != (unsigned char)needle[j]) {
                break;
            }
        }
        if (j == m) {
            return b + i;
        }
    }
    return NULL;
}

/* Review R3-B(a): a synthetic full MAC as the cause token must not
 * escape into the structured result — boot verdict stands, cause
 * UNRECOGNISED, cause_name empty, and the raw bytes appear NOWHERE in
 * the evidence struct. (The verbatim token lives only in the caller's
 * raw transcript, kept outside this API by the Part B drill.) */
static void test_boot_evidence_cause_privacy_mac_token(void)
{
    vdog_boot_evidence_t ev;

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (001122334455),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "001122334455"),
                             "MAC-shaped cause must not appear in evidence");
    /* Also with separators inside the token charset (A-F0-9 + _ stays): */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (AABB_CC_DD_EE_FF),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_NULL(ev_find_bytes(&ev, "AABB"));
}

/* Review round 4 (re-grounded round 5): the shortened watchdog/system
 * ROM prints classify KNOWN with the canonical stored. They are the
 * ESP32-S3 ROM's OWN labels at 0x3/0x7/0x8/0x10/0x12, extracted from
 * the vendor ROM ELF (path+sha256+method in core/vdog_recovery.c); the
 * published captures corroborate (Seeed XIAO ESP32-S3 capture #10588
 * for 0x3, the ESP-Techpedia watchdog doc "Common LOG" for 0x7/0x8,
 * esp-idf issue #14243 (board ESP32-S3-WROOM-1, IDF version v5.1.2)
 * for 0x12, community issue #6980 (S3-DevKitC-1) for the 0x10 short
 * form). The rtc.h enum spellings stay
 * accepted; the STORED name is always the entry's canonical primary and
 * the input alias bytes appear nowhere in the evidence struct. */
static void test_boot_evidence_watchdog_rom_aliases(void)
{
    vdog_boot_evidence_t ev;

    /* 0x3 (RTC_SW_SYS_RST) — the vdog board's own capture (#10588). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x3 (RTC_SW_SYS_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(3u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("RTC_SW_SYS_RST", ev.cause_name);
    /* Enum alias accepted, canonical stored, alias bytes not stored. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x3 (RTC_SW_SYS_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("RTC_SW_SYS_RST", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "RTC_SW_SYS_RESET"),
                             "input alias bytes must not be stored");

    /* 0x7 / 0x8 — ESP-Techpedia watchdog doc "Common LOG" lines. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x7 (TG0WDT_SYS_RST),boot:0xc (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(7u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("TG0WDT_SYS_RST", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x8 (TG1WDT_SYS_RST),boot:0xc (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(8u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("TG1WDT_SYS_RST", ev.cause_name);
    /* Enum _RESET spellings stay accepted (union rule), canonical stored
     * and the input bytes never land in the struct. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x7 (TG0WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("TG0WDT_SYS_RST", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "TG0WDT_SYS_RESET"),
                             "input alias bytes must not be stored");
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x8 (TG1WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("TG1WDT_SYS_RST", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "TG1WDT_SYS_RESET"),
                             "input alias bytes must not be stored");

    /* 0x12 (SUPER_WDT_RST) — verbatim capture line from espressif/esp-idf
     * issue #14243 (boot:0x2a is free-form hex under the banner rule). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x12 (SUPER_WDT_RST),boot:0x2a (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(18u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("SUPER_WDT_RST", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x12 (SUPER_WDT_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("SUPER_WDT_RST", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "SUPER_WDT_RESET"),
                             "input alias bytes must not be stored");

    /* 0x10: the extracted ROM LABEL is the short RTCWDT_RTC_RST (canonical);
     * the enum/published RTCWDT_RTC_RESET form stays accepted as alias. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x10 (RTCWDT_RTC_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(16u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("RTCWDT_RTC_RST", ev.cause_name);
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x10 (RTCWDT_RTC_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("RTCWDT_RTC_RST", ev.cause_name);
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "RTCWDT_RTC_RESET"),
                             "input alias bytes must not be stored");
    /* Case-insensitivity of the new aliases (documented rule). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x7 (tg0wdt_sys_rst),boot:0xc (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("TG0WDT_SYS_RST", ev.cause_name);
}

/* Review round 5: fixtures GENERATED from the extracted ROM label table
 * (24 entries at vaddr 0x3ff18e10 of esp32s3_rev0_rom.elf, sha256
 * c0ce0f33...7dd34cfd — provenance in core/vdog_recovery.c). The 19
 * named entries below are the non-"N/A" rows exactly as extracted
 * (index: ROM label, rtc.h enum). Per row: the complete captured-style
 * line with the ROM label classifies KNOWN and stores the label; the
 * rtc.h enum spelling classifies KNOWN storing the LABEL with the enum
 * input bytes nowhere in the evidence struct; and pairing the value
 * with another row's label (wrong name) is UNRECOGNISED with the whole
 * cause_name buffer zero — verdict still from the banner. */
static void test_boot_evidence_rom_table_generated(void)
{
    static const struct {
        unsigned v;
        const char *label; /* extracted ROM print (canonical) */
        const char *e;     /* rtc.h enum spelling, NULL when equal */
    } t[] = {
        { 1u, "POWERON",             "POWERON_RESET" },
        { 3u, "RTC_SW_SYS_RST",      "RTC_SW_SYS_RESET" },
        { 5u, "DSLEEP",              "DEEPSLEEP_RESET" },
        { 7u, "TG0WDT_SYS_RST",      "TG0WDT_SYS_RESET" },
        { 8u, "TG1WDT_SYS_RST",      "TG1WDT_SYS_RESET" },
        { 9u, "RTCWDT_SYS_RST",      "RTCWDT_SYS_RESET" },
        {10u, "INTRUSION_RST",       "INTRUSION_RESET" },
        {11u, "TG0WDT_CPU_RST",      "TG0WDT_CPU_RESET" },
        {12u, "RTC_SW_CPU_RST",      "RTC_SW_CPU_RESET" },
        {13u, "RTCWDT_CPU_RST",      "RTCWDT_CPU_RESET" },
        {15u, "BROWNOUT_RST",        "RTCWDT_BROWN_OUT_RESET" },
        {16u, "RTCWDT_RTC_RST",      "RTCWDT_RTC_RESET" },
        {17u, "TG1WDT_CPU_RST",      "TG1WDT_CPU_RESET" },
        {18u, "SUPER_WDT_RST",       "SUPER_WDT_RESET" },
        {19u, "GLITCH_RTC_RST",      "GLITCH_RTC_RESET" },
        {20u, "EFUSE_RST",           "EFUSE_RESET" },
        {21u, "USB_UART_CHIP_RESET", NULL },
        {22u, "USB_JTAG_CHIP_RESET", NULL },
        {23u, "POWER_GLITCH_RESET",  NULL }
    };
    const size_t n = sizeof(t) / sizeof(t[0]);
    vdog_boot_evidence_t ev;
    char line[96];
    size_t i;

    TEST_ASSERT_EQUAL_UINT(19u, (unsigned)n); /* all named table rows   */

    for (i = 0; i < n; ++i) {
        /* (a) ROM label pair -> KNOWN, canonical stored. */
        sprintf(line, "rst:0x%x (%s),boot:0x8 (SPI_FAST_FLASH_BOOT)",
                t[i].v, t[i].label);
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_OK, vdog_recovery_classify_boot(
            line, &ev), line);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_MODE_NORMAL,
                                        (uint8_t)ev.boot_mode, line);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_CAUSE_KNOWN,
                                        (uint8_t)ev.cause_state, line);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE((uint8_t)t[i].v, ev.rst_value, line);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(t[i].label, ev.cause_name, line);

        /* (b) enum alias pair -> KNOWN, LABEL stored, enum bytes absent. */
        if (t[i].e != NULL) {
            sprintf(line, "rst:0x%x (%s),boot:0x8 (SPI_FAST_FLASH_BOOT)",
                    t[i].v, t[i].e);
            TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_OK, vdog_recovery_classify_boot(
                line, &ev), line);
            TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_CAUSE_KNOWN,
                                            (uint8_t)ev.cause_state, line);
            TEST_ASSERT_EQUAL_STRING_MESSAGE(t[i].label, ev.cause_name, line);
            TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, t[i].e),
                                     "input alias bytes must not be stored");
        }

        /* (c) wrong-name pair (another row's label) -> UNRECOGNISED,
         * whole buffer zero, banner verdict intact. */
        sprintf(line, "rst:0x%x (%s),boot:0x8 (SPI_FAST_FLASH_BOOT)",
                t[i].v, t[(i + 1u) % n].label);
        TEST_ASSERT_EQUAL_INT_MESSAGE(VDOG_OK, vdog_recovery_classify_boot(
            line, &ev), line);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_MODE_NORMAL,
                                        (uint8_t)ev.boot_mode, line);
        TEST_ASSERT_EQUAL_UINT8_MESSAGE(VDOG_BOOT_CAUSE_UNRECOGNISED,
                                        (uint8_t)ev.cause_state, line);
        TEST_ASSERT_EQUAL_STRING_MESSAGE("", ev.cause_name, line);
        TEST_ASSERT_EACH_EQUAL_CHAR_MESSAGE('\0', ev.cause_name,
                                            sizeof(ev.cause_name), line);
    }
}

/* Review round 5: MAC-shaped cause refusal on NEWLY admitted values —
 * boot verdict stands, cause UNRECOGNISED, name empty, token bytes
 * nowhere in the evidence (privacy unchanged by the coverage growth). */
static void test_boot_evidence_cause_privacy_new_values(void)
{
    vdog_boot_evidence_t ev;

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x13 (001122334455),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(19u, ev.rst_value);
    TEST_ASSERT_EQUAL_STRING("", ev.cause_name);
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));
    TEST_ASSERT_NULL_MESSAGE(ev_find_bytes(&ev, "001122334455"),
                             "MAC-shaped cause must not appear in evidence");

    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0xb (AABB_CC_DD_EE_FF),boot:0x8 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(11u, ev.rst_value);
    TEST_ASSERT_NULL(ev_find_bytes(&ev, "AABB"));
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));
}

/* Review R3-B(b): stale stack bytes. A cause line then a boot-only line
 * into the SAME struct must leave the whole cause_name buffer zero (not
 * just up to the NUL), and a dirty struct must enter fully cleared. */
static void test_boot_evidence_no_stale_bytes(void)
{
    vdog_boot_evidence_t ev;

    /* 1. A KNOWN cause line populates the canonical name (0x9 input is
     * the rtc.h enum alias; the stored canonical is the ROM label). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x9 (RTCWDT_SYS_RESET),boot:0x3 (SPI_FAST_FLASH_BOOT)", &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_KNOWN, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_STRING("RTCWDT_SYS_RST", ev.cause_name);

    /* 2. ...then a boot-only line over the SAME struct: the old bug left
     * nonzero bytes behind the NUL. Entire buffer must be zero. */
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_BARE_NORMAL, &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_MODE_NORMAL, (uint8_t)ev.boot_mode);
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);
    TEST_ASSERT_EQUAL_UINT8(0u, ev.rst_value);
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));

    /* 3. A UNRECOGNISED token after a KNOWN name leaves nothing behind
     * either (bot probe pattern: successive calls into one struct). */
    TEST_ASSERT_EQUAL_INT(VDOG_OK, vdog_recovery_classify_boot(
        "rst:0x1 (SECRET_MAC_001122334455),boot:0x3 (SPI_FAST_FLASH_BOOT)",
        &ev));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_UNRECOGNISED,
                            (uint8_t)ev.cause_state);
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));
    TEST_ASSERT_NULL(ev_find_bytes(&ev, "SECRET_MAC"));

    /* 4. Dirty struct at the entry point: cleared before filling. */
    memset(&ev, 0xA5, sizeof(ev));
    TEST_ASSERT_EQUAL_INT(VDOG_OK,
                          vdog_recovery_classify_boot(ROM_BARE_NORMAL, &ev));
    TEST_ASSERT_EACH_EQUAL_CHAR('\0', ev.cause_name, sizeof(ev.cause_name));
    TEST_ASSERT_EQUAL_UINT8(VDOG_BOOT_CAUSE_NONE, (uint8_t)ev.cause_state);
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
    RUN_TEST(test_boot_evidence_rom_printed_aliases);
    RUN_TEST(test_boot_evidence_watchdog_rom_aliases);
    RUN_TEST(test_boot_evidence_rom_table_generated);
    RUN_TEST(test_boot_evidence_cause_privacy_new_values);
    RUN_TEST(test_boot_evidence_pair_mismatch);
    RUN_TEST(test_boot_evidence_cause_privacy_mac_token);
    RUN_TEST(test_boot_evidence_no_stale_bytes);
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
    RUN_TEST(test_boot_evidence_rom_printed_aliases);
    RUN_TEST(test_boot_evidence_watchdog_rom_aliases);
    RUN_TEST(test_boot_evidence_rom_table_generated);
    RUN_TEST(test_boot_evidence_cause_privacy_new_values);
    RUN_TEST(test_boot_evidence_pair_mismatch);
    RUN_TEST(test_boot_evidence_cause_privacy_mac_token);
    RUN_TEST(test_boot_evidence_no_stale_bytes);
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
