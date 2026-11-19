# Thin IDF-component wrapper so the portable module gets a namespaced
# component name ("vdog_core") while the canonical pure-C sources stay in
# firmware/core/ (shared verbatim with the PlatformIO `native` test env via
# lib_deps). idf_component_register names a component after its directory.
idf_component_register(SRCS "${CMAKE_CURRENT_LIST_DIR}/../../core/vdog_core.c"
                       INCLUDE_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../core")
