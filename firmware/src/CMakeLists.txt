# vdog main application component (PlatformIO maps firmware/src to the IDF
# "main" component). The camera driver is a real REQUIRES/link dependency;
# nothing here initializes camera, SD, network or radio (package 0.2 scope).
idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES vdog_core esp32-camera
    PRIV_REQUIRES app_update esp_system esp_timer log unity
)
