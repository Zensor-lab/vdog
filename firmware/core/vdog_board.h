/*
 * vdog portable board-profile core module (package 1.1).
 *
 * Pure C11, no SDK/OS headers: compiled for the host `native` test
 * environment (via lib_deps on core/) AND for the target as an IDF component
 * (via the components/vdog_board wrapper), exactly like vdog_core.{h,c}.
 * Keep it dependency-free: this file is the single source of truth for what
 * a "supported board" means, and the build-time gate script
 * (firmware/scripts/check_board_config.py) is only a thin reader/comparator.
 * The API is C++-consumer-safe via the extern "C" guard below.
 *
 * Explicit-field contract: every member of vdog_board_profile_t is paired
 * with a VDOG_BOARD_FIELD_* bit in `field_set`. A value that was never
 * configured stays UNSET and is reported as VDOG_ERR_BOARD_MISSING_FIELD,
 * never compared as a silently inherited default (plan 1.1 §4.1: "a missing
 * (never-configured) key is distinguishable from a wrong value").
 */
#ifndef VDOG_BOARD_H
#define VDOG_BOARD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Status codes (shared with vdog_core.h; repeated guards below) ---- */
#ifndef VDOG_OK
#define VDOG_OK 0
#endif
#ifndef VDOG_ERR_INVALID_ARG
#define VDOG_ERR_INVALID_ARG (-1)
#endif
#ifndef VDOG_ERR_BUFFER_TOO_SMALL
#define VDOG_ERR_BUFFER_TOO_SMALL (-2)
#endif

/* Board-profile specific failures (distinct from the vdog_core codes). */
#define VDOG_ERR_BOARD_MISSING_FIELD (-10)
#define VDOG_ERR_BOARD_UNSUPPORTED_TARGET (-11)
#define VDOG_ERR_BOARD_FLASH (-12)
#define VDOG_ERR_BOARD_PSRAM (-13)
#define VDOG_ERR_BOARD_PARTITIONS (-14)

/* ---- field_set bits: one per profile field (explicit-field contract) ---- */
#define VDOG_BOARD_FIELD_TARGET (1u << 0)
#define VDOG_BOARD_FIELD_BOARD_ID (1u << 1)
#define VDOG_BOARD_FIELD_FLASH_SIZE (1u << 2)
#define VDOG_BOARD_FIELD_FLASH_MODE (1u << 3)
#define VDOG_BOARD_FIELD_FLASH_FREQ (1u << 4)
#define VDOG_BOARD_FIELD_PSRAM_PRESENT (1u << 5)
#define VDOG_BOARD_FIELD_PSRAM_SIZE (1u << 6)
#define VDOG_BOARD_FIELD_PSRAM_MODE (1u << 7)
#define VDOG_BOARD_FIELD_PSRAM_SPEED (1u << 8)
#define VDOG_BOARD_FIELD_PARTITION_TABLE (1u << 9)

/* Every field the identity gate requires before a boot may be reported. */
#define VDOG_BOARD_FIELD_ALL                                                     \
    (VDOG_BOARD_FIELD_TARGET | VDOG_BOARD_FIELD_BOARD_ID |                       \
     VDOG_BOARD_FIELD_FLASH_SIZE | VDOG_BOARD_FIELD_FLASH_MODE |                 \
     VDOG_BOARD_FIELD_FLASH_FREQ | VDOG_BOARD_FIELD_PSRAM_PRESENT |              \
     VDOG_BOARD_FIELD_PSRAM_SIZE | VDOG_BOARD_FIELD_PSRAM_MODE |                 \
     VDOG_BOARD_FIELD_PSRAM_SPEED | VDOG_BOARD_FIELD_PARTITION_TABLE)

/* ---- Target ids (chip ids accepted by the gate; 0 == never configured) --- */
#define VDOG_BOARD_TARGET_UNKNOWN 0u
#define VDOG_BOARD_TARGET_ESP32S3 1u

/* ---- Flash modes (values, not Kconfig spellings) ---- */
#define VDOG_BOARD_FLASH_MODE_UNKNOWN 0u
#define VDOG_BOARD_FLASH_MODE_QIO 1u
#define VDOG_BOARD_FLASH_MODE_DIO 2u
#define VDOG_BOARD_FLASH_MODE_DOUT 3u
#define VDOG_BOARD_FLASH_MODE_QOUT 4u

/* ---- PSRAM modes: OPI == octal (OPI), QSPI == quad ---- */
#define VDOG_BOARD_PSRAM_MODE_UNKNOWN 0u
#define VDOG_BOARD_PSRAM_MODE_OPI 1u
#define VDOG_BOARD_PSRAM_MODE_QSPI 2u

typedef uint8_t vdog_board_target_t;
typedef uint8_t vdog_board_flash_mode_t;
typedef uint8_t vdog_board_psram_mode_t;

typedef struct {
    vdog_board_target_t target;        /* VDOG_BOARD_TARGET_* value        */
    const char *board_id;              /* board identity string            */
    uint32_t flash_size_bytes;         /* flash capacity, bytes            */
    vdog_board_flash_mode_t flash_mode;/* VDOG_BOARD_FLASH_MODE_*          */
    uint16_t flash_freq_mhz;           /* flash frequency, whole MHz       */
    uint8_t psram_present;             /* 0 = absent, 1 = present          */
    uint32_t psram_size_bytes;         /* PSRAM capacity, bytes            */
    vdog_board_psram_mode_t psram_mode;/* VDOG_BOARD_PSRAM_MODE_*          */
    uint16_t psram_speed_mhz;          /* PSRAM frequency, whole MHz       */
    const char *partition_table;       /* partition-table file name        */
    uint32_t field_set;                /* VDOG_BOARD_FIELD_* bitmask       */
} vdog_board_profile_t;

/* ---- Provisional expected profile for [env:vdog_xiao_sense_proto] ----
 * These values are BUILD CONFIGURATION (firmware/sdkconfig.defaults,
 * firmware/platformio.ini, firmware/partitions/vdog_8mb_two_ota.csv), not
 * detected hardware. Physical flash capacity, octal-PSRAM detection and the
 * XIAO/Sense revision stay DEVICE evidence for packages 1.2-1.4. */
#define VDOG_BOARD_EXPECTED_TARGET VDOG_BOARD_TARGET_ESP32S3
#define VDOG_BOARD_EXPECTED_TARGET_NAME "esp32s3"
#define VDOG_BOARD_EXPECTED_BOARD_ID "seeed_xiao_esp32s3"
#define VDOG_BOARD_EXPECTED_FLASH_SIZE_BYTES (8u * 1024u * 1024u)
#define VDOG_BOARD_EXPECTED_FLASH_MODE VDOG_BOARD_FLASH_MODE_QIO
#define VDOG_BOARD_EXPECTED_FLASH_FREQ_MHZ 80u
#define VDOG_BOARD_EXPECTED_PSRAM_PRESENT 1u
#define VDOG_BOARD_EXPECTED_PSRAM_SIZE_BYTES (8u * 1024u * 1024u)
#define VDOG_BOARD_EXPECTED_PSRAM_MODE VDOG_BOARD_PSRAM_MODE_OPI
#define VDOG_BOARD_EXPECTED_PSRAM_SPEED_MHZ 80u
#define VDOG_BOARD_EXPECTED_PARTITION_TABLE "partitions/vdog_8mb_two_ota.csv"

/* ---- PROVISIONAL pin note (reference only — this module drives NOTHING) --
 * Wiring is NOT approved (plan 1.1 §1/§3, hardware/prototype-a/pin-map.csv is
 * CANDIDATE_NOT_APPROVED for every row, and package 0.3 still owes the
 * reviewed wiring). Nothing in package 1.1 configures, drives or reads a
 * GPIO, and this header carries no pin numbers at all. The two facts recorded
 * here exist so the board profile is not mistaken for a pin map:
 *   - pin-map.csv lists SPI_CS (function `sd`) and USER_LED (function
 *     `indicator`) BOTH on GPIO21 ("Intentional CS21 alias"); that sharing is
 *     UNRESOLVED and blocks any indicator/peripheral work until 0.3/0.7.
 *   - Any future pin use must come from the approved map, not from this file.
 * ------------------------------------------------------------------------- */

/* Zeroed profile with NO field set: start here and mark each field you set. */
void vdog_board_profile_init(vdog_board_profile_t *profile);

/* The expected-provisional profile above, fully marked, ready to validate. */
vdog_board_profile_t vdog_board_expected_profile_proto(void);

/* Identity gate. Returns VDOG_OK only when EVERY required field is set and
 * every value equals the expected-provisional profile.
 *   VDOG_ERR_INVALID_ARG            profile == NULL
 *   VDOG_ERR_BOARD_MISSING_FIELD    a required field was never configured
 *   VDOG_ERR_BOARD_UNSUPPORTED_TARGET target or board id is not the
 *                                   supported prototype
 *   VDOG_ERR_BOARD_FLASH            flash size / mode / freq mismatch
 *   VDOG_ERR_BOARD_PSRAM            PSRAM presence / size / mode / speed
 *   VDOG_ERR_BOARD_PARTITIONS       partition-table name mismatch
 * Decision order is fixed so host tests can pin it: argument check, then ALL
 * missing-field checks, then value checks, each in declaration order (a
 * missing field therefore always outranks a wrong value).
 * vdog_board_error_field() names the field behind the LAST call. */
int vdog_board_validate(const vdog_board_profile_t *profile);

/* Field name behind the most recent vdog_board_validate()/
 * vdog_board_report() failure ("profile"/"buf" for argument errors), or NULL
 * when the last call succeeded or nothing has been validated yet. The string
 * is static; it is valid until the next call of either function and the
 * accessor is intended for single-threaded boot-time/diagnostic use. */
const char *vdog_board_error_field(void);

/* Compose the boot report from a profile, after running it through the
 * gate. On success buf holds exactly
 *   "vdog <MAJOR.MINOR.PATCH-SUFFIX> board=<id> target=esp32s3
 *    flash=8MB-qio-80m psram=8MB-opi-80m"
 * (NUL-terminated), built from the VDOG_VERSION_* constants of vdog_core.h.
 * Buffer/NUL semantics are identical to vdog_format_version(): the buffer
 * contents are unspecified on error.
 *   VDOG_OK
 *   VDOG_ERR_INVALID_ARG          profile == NULL or buf == NULL
 *   VDOG_ERR_BUFFER_TOO_SMALL     bufsize cannot hold the string + NUL
 *   plus every vdog_board_validate() code (a rejected profile is never
 *   reported, so a bad board can never print a healthy-looking line). */
int vdog_board_report(const vdog_board_profile_t *profile, char *buf,
                      size_t bufsize);

#ifdef __cplusplus
}
#endif

#endif /* VDOG_BOARD_H */
