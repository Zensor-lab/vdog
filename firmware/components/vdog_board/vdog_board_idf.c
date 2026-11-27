/*
 * vdog target-side board adapter (package 1.1) — see vdog_board_idf.h.
 *
 * Reads the compile-time configuration of THIS image and marks only the
 * fields an explicit key actually states. There is no fallback value and no
 * `#else` branch anywhere: an absent key leaves the field unset, the
 * portable validator then returns VDOG_ERR_BOARD_MISSING_FIELD and
 * vdog_board_error_field() names it, which is exactly the "silently
 * inherited PSRAM/flash default" failure this package must make loud
 * (plan 1.1 §4.3, acceptance §7.3).
 *
 * This file configures NO peripheral, NO pin and NO memory: it reads
 * integers and strings that CMake already resolved.
 */
#include "vdog_board_idf.h"

/* Generated with this build (config/sdkconfig.h); every CONFIG_* test below
 * is a definedness test on purpose. */
#include "sdkconfig.h"

/* ---- structural compile-flag enforcement (PR-review round 5, PR-R9) ----
 * VDOG_BOARD_ID_STR and VDOG_BOARD_PSRAM_SIZE_BYTES arrive from the PRIVATE
 * target_compile_definitions() in this component's CMakeLists.txt. A text
 * check in scripts/check_board_config.py cannot prove the COMPILER receives
 * them (e.g. PRIVATE -> INTERFACE silently drops the defines from this
 * translation unit while every literal stays intact), so this file refuses
 * to compile without them: a scope flip or deleted definition is a hard
 * compile error, never a green gate shipping an unconfigured image. The
 * gate keeps its text layer as defence in depth. */
#if !defined(VDOG_BOARD_ID_STR)
#error "vdog_board_idf.c requires VDOG_BOARD_ID_STR from the component build (PRIVATE target_compile_definitions)"
#endif
#if !defined(VDOG_BOARD_PSRAM_SIZE_BYTES)
#error "vdog_board_idf.c requires VDOG_BOARD_PSRAM_SIZE_BYTES from the component build (PRIVATE target_compile_definitions)"
#endif

#define VDOG_BOARD_MIB (1024u * 1024u)

vdog_board_profile_t vdog_board_profile_from_sdkconfig(void)
{
    vdog_board_profile_t profile;

    vdog_board_profile_init(&profile);

    /* ---- target chip id ---- */
#ifdef CONFIG_IDF_TARGET_ESP32S3
    profile.target = VDOG_BOARD_TARGET_ESP32S3;
    profile.field_set |= VDOG_BOARD_FIELD_TARGET;
#endif

    /* ---- board identity (no Kconfig key exists; declared by this
     * component's CMakeLists.txt and cross-checked against $BOARD by
     * scripts/check_board_config.py) ---- */
#ifdef VDOG_BOARD_ID_STR
    profile.board_id = VDOG_BOARD_ID_STR;
    profile.field_set |= VDOG_BOARD_FIELD_BOARD_ID;
#endif

    /* ---- flash size: the selected ESPTOOLPY_FLASHSIZE_* choice, whatever
     * it is, so a 4MB build is a WRONG VALUE (VDOG_ERR_BOARD_FLASH) and not
     * a missing field ---- */
#ifdef CONFIG_ESPTOOLPY_FLASHSIZE_2MB
    profile.flash_size_bytes = 2u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_SIZE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHSIZE_4MB
    profile.flash_size_bytes = 4u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_SIZE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHSIZE_8MB
    profile.flash_size_bytes = 8u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_SIZE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHSIZE_16MB
    profile.flash_size_bytes = 16u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_SIZE;
#endif

    /* ---- flash mode / frequency. NOTE: the hidden ESPTOOLPY_FLASHMODE
     * STRING stays "dio" by ESP-IDF design (esptool programs in DIO and the
     * bootloader self-upgrades); the selected bool is the configuration
     * fact, so the bools are what is read here (docs/toolchain.md §4). ---- */
#ifdef CONFIG_ESPTOOLPY_FLASHMODE_QIO
    profile.flash_mode = VDOG_BOARD_FLASH_MODE_QIO;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_MODE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHMODE_DIO
    profile.flash_mode = VDOG_BOARD_FLASH_MODE_DIO;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_MODE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHMODE_DOUT
    profile.flash_mode = VDOG_BOARD_FLASH_MODE_DOUT;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_MODE;
#endif
#ifdef CONFIG_ESPTOOLPY_FLASHMODE_QOUT
    profile.flash_mode = VDOG_BOARD_FLASH_MODE_QOUT;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_MODE;
#endif
#if defined(CONFIG_ESPTOOLPY_FLASHFREQ_80M)
    profile.flash_freq_mhz = 80u;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_FREQ;
#elif defined(CONFIG_ESPTOOLPY_FLASHFREQ_40M)
    profile.flash_freq_mhz = 40u;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_FREQ;
#elif defined(CONFIG_ESPTOOLPY_FLASHFREQ_120M)
    profile.flash_freq_mhz = 120u;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_FREQ;
#elif defined(CONFIG_ESPTOOLPY_FLASHFREQ_160M)
    profile.flash_freq_mhz = 160u;
    profile.field_set |= VDOG_BOARD_FIELD_FLASH_FREQ;
#endif

    /* ---- PSRAM presence: only an image built WITH SPIRAM support states a
     * value at all; without CONFIG_SPIRAM the field stays unset and the
     * validator rejects it as never-configured (fail loudly, §7.3) ---- */
#ifdef CONFIG_SPIRAM
    profile.psram_present = 1u;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_PRESENT;
#endif

    /* ---- PSRAM capacity. ESP-IDF detects capacity at runtime
     * (CONFIG_SPIRAM_TYPE_AUTO), so precedence is: a stated
     * CONFIG_SPIRAM_SIZE, then a pinned CONFIG_SPIRAM_TYPE_*, then the
     * capacity declared by this component for the prototype. None of them
     * present => unset => VDOG_ERR_BOARD_MISSING_FIELD, never 8MB assumed.
     * DEVICE proof of the real capacity is packages 1.2-1.4. ---- */
#if defined(CONFIG_SPIRAM_SIZE) && (CONFIG_SPIRAM_SIZE > 0)
    profile.psram_size_bytes = (uint32_t)CONFIG_SPIRAM_SIZE;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SIZE;
#elif defined(CONFIG_SPIRAM_TYPE_ESPPSRAM64)
    profile.psram_size_bytes = 8u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SIZE;
#elif defined(CONFIG_SPIRAM_TYPE_ESPPSRAM32)
    profile.psram_size_bytes = 4u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SIZE;
#elif defined(CONFIG_SPIRAM_TYPE_ESPPSRAM16)
    profile.psram_size_bytes = 2u * VDOG_BOARD_MIB;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SIZE;
#elif defined(VDOG_BOARD_PSRAM_SIZE_BYTES)
    profile.psram_size_bytes = (uint32_t)(VDOG_BOARD_PSRAM_SIZE_BYTES);
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SIZE;
#endif

    /* ---- PSRAM mode: OCT == octal (OPI) is what the Sense module carries,
     * QSPI would be a quad module and is a WRONG VALUE, not "missing" ---- */
#ifdef CONFIG_SPIRAM_MODE_OCT
    profile.psram_mode = VDOG_BOARD_PSRAM_MODE_OPI;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_MODE;
#endif
#ifdef CONFIG_SPIRAM_MODE_QUAD
    profile.psram_mode = VDOG_BOARD_PSRAM_MODE_QSPI;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_MODE;
#endif

    /* ---- PSRAM speed ---- */
#if defined(CONFIG_SPIRAM_SPEED_80M)
    profile.psram_speed_mhz = 80u;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SPEED;
#elif defined(CONFIG_SPIRAM_SPEED_40M)
    profile.psram_speed_mhz = 40u;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SPEED;
#elif defined(CONFIG_SPIRAM_SPEED_120M)
    profile.psram_speed_mhz = 120u;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SPEED;
#elif defined(CONFIG_SPIRAM_SPEED_200M)
    profile.psram_speed_mhz = 200u;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SPEED;
#elif defined(CONFIG_SPIRAM_SPEED) && (CONFIG_SPIRAM_SPEED > 0)
    profile.psram_speed_mhz = (uint16_t)CONFIG_SPIRAM_SPEED;
    profile.field_set |= VDOG_BOARD_FIELD_PSRAM_SPEED;
#endif

    /* ---- partition table: the custom file must be BOTH enabled and named;
     * a built-in table leaves the field unset and is rejected ---- */
#if defined(CONFIG_PARTITION_TABLE_CUSTOM) &&                            \
    defined(CONFIG_PARTITION_TABLE_CUSTOM_FILENAME)
    profile.partition_table = CONFIG_PARTITION_TABLE_CUSTOM_FILENAME;
    profile.field_set |= VDOG_BOARD_FIELD_PARTITION_TABLE;
#endif

    return profile;
}
