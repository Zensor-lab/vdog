# vdog main application component (PlatformIO maps firmware/src to the IDF
# "main" component). The camera driver is a real REQUIRES/link dependency;
# nothing here initializes camera, SD, network or radio (package 0.2 scope).
# Stage 1.1 adds the vdog_board component: board-profile adapter + portable
# identity gate (console reporting only, still no peripheral initialization).
idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES vdog_core vdog_board esp32-camera
    PRIV_REQUIRES app_update esp_system esp_timer log unity
)

# Stage 0.9 packet A: generated build-identity header directory
# (firmware/build_gen/, gitignored; written by scripts/gen_build_meta.py
# before compilation). Registered here so the CMake codemodel compile flags
# for this component always carry it, independently of the post-build SCons
# CPPPATH update in the extra script.
target_include_directories(${COMPONENT_LIB} PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/../build_gen")
