cmake_minimum_required(VERSION 3.20)
project(tubeviz_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET
    libavformat
    libavcodec
    libavutil
    libswscale
)

option(TUBEVIZ_WITH_PLACEBO "Enable libplacebo/Vulkan integration when available" ON)
if(TUBEVIZ_WITH_PLACEBO)
    pkg_check_modules(PLACEBO QUIET IMPORTED_TARGET libplacebo)
endif()

add_executable(tubeviz-native-render
    src/main.cpp
    src/manifest.cpp
    src/decoder.cpp
    src/effects.cpp
    src/renderer.cpp
)

target_include_directories(tubeviz-native-render PRIVATE include)
target_link_libraries(tubeviz-native-render PRIVATE PkgConfig::FFMPEG)

target_compile_options(tubeviz-native-render PRIVATE
    -Wall -Wextra -Wpedantic
)

if(PLACEBO_FOUND)
    target_link_libraries(tubeviz-native-render PRIVATE PkgConfig::PLACEBO)
    target_compile_definitions(tubeviz-native-render PRIVATE TUBEVIZ_HAVE_PLACEBO=1)
    message(STATUS "libplacebo found: ${PLACEBO_VERSION}; Phase-2 GPU hooks enabled")
else()
    message(STATUS "libplacebo not found; building Phase-1 native FFmpeg renderer")
endif()

install(TARGETS tubeviz-native-render RUNTIME DESTINATION bin)
