# vdog firmware — ESP-IDF project entry consumed by PlatformIO's espidf
# builder (it runs CMake directly on this directory).
#
# The IDF auto-discovers components/ (where the thin vdog_core component
# wrapper lives). Do NOT set EXTRA_COMPONENT_DIRS here: PlatformIO passes its
# own value through the CMake cache (the `src` main component) and
# overwriting it breaks main-component discovery.
cmake_minimum_required(VERSION 3.16.0)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(vdog_firmware)
