# Thin IDF-component wrapper so the portable board-profile module gets a
# namespaced component name ("vdog_board") while the canonical pure-C source
# stays in firmware/core/ (shared verbatim with the PlatformIO `native` test
# env via lib_deps) — mirrors components/vdog_core/CMakeLists.txt.
#
# vdog_board_idf.c is the TARGET-SIDE adapter: it turns this build's CONFIG_*
# macros into a vdog_board_profile_t. It contains no policy of its own; the
# accept/reject decision lives in core/vdog_board.c.
idf_component_register(SRCS "${CMAKE_CURRENT_LIST_DIR}/../../core/vdog_board.c"
                            "vdog_board_idf.c"
                       INCLUDE_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../core" "."
                       REQUIRES vdog_core)

# Board identity and PSRAM capacity are BUILD CONFIGURATION inputs, not
# detected hardware (plan 1.1 §4.1/§4.3; physical detection is DEVICE
# evidence for packages 1.2-1.4):
#   - VDOG_BOARD_ID_STR is the PlatformIO board id of
#     [env:vdog_xiao_sense_proto] (`board = seeed_xiao_esp32s3` in
#     firmware/platformio.ini). There is no ESP-IDF Kconfig key for the board,
#     so it is declared here explicitly. scripts/check_board_config.py
#     independently compares the build environment's $BOARD against the same
#     expected value, so the two cannot silently drift apart.
#   - VDOG_BOARD_PSRAM_SIZE_BYTES states the 8 MiB octal-PSRAM capacity the
#     prototype is built for. ESP-IDF leaves capacity to runtime detection
#     here (CONFIG_SPIRAM_TYPE_AUTO), so the adapter uses
#     CONFIG_SPIRAM_SIZE / CONFIG_SPIRAM_TYPE_* when the SDK states them and
#     this declared value otherwise; if none is present the field stays
#     UNSET and the C validator rejects the profile as
#     VDOG_ERR_BOARD_MISSING_FIELD rather than assuming 8 MiB.
# No definition here relaxes a check: an unset definition means "field not
# set", never a default.
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    VDOG_BOARD_ID_STR="seeed_xiao_esp32s3"
    VDOG_BOARD_PSRAM_SIZE_BYTES=8388608u)
