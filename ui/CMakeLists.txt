cmake_minimum_required(VERSION 3.24)
project(flowd-ui VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O2")

# CI has no GTK 4.22 or layer-shell; the core is everything worth unit-testing.
option(FLOWD_UI_CORE_ONLY "Build only the GTK-free core library and its tests" OFF)

add_compile_options(-Wall -Wextra -Wpedantic)

include(CheckIPOSupported)
check_ipo_supported(RESULT flowd_lto OUTPUT flowd_lto_error LANGUAGES CXX)

# --- core: pure logic, no GTK ------------------------------------------------
set(FLOWD_CORE_SOURCES
  # pure-logic sources
  src/protocol.cpp
  src/placement.cpp
  src/position_store.cpp
  src/meter.cpp
)
add_library(flowd-ui-core STATIC ${FLOWD_CORE_SOURCES} src/version.hpp)
set_target_properties(flowd-ui-core PROPERTIES LINKER_LANGUAGE CXX)
target_include_directories(flowd-ui-core PUBLIC src)
target_include_directories(flowd-ui-core SYSTEM PUBLIC third_party)

enable_testing()
set(FLOWD_CORE_TESTS
  tests/test_smoke.cpp
  # core unit tests
  tests/test_protocol.cpp
  tests/test_placement.cpp
  tests/test_position_store.cpp
  tests/test_meter.cpp
)
add_executable(flowd-ui-tests tests/main.cpp ${FLOWD_CORE_TESTS})
target_link_libraries(flowd-ui-tests PRIVATE flowd-ui-core)
add_test(NAME core COMMAND flowd-ui-tests)

if(FLOWD_UI_CORE_ONLY)
  return()
endif()

# --- flowd-ui: the GTK program -----------------------------------------------
find_package(PkgConfig REQUIRED)
# gtk4-layer-shell first, so its NEEDED entry precedes libwayland-client's
# (the build checks this with readelf). That order is what lets it work without LD_PRELOAD.
pkg_check_modules(FLOWD_GTK REQUIRED IMPORTED_TARGET gtk4-layer-shell-0 gtkmm-4.0 gtk4-x11 x11)

set(FLOWD_GTK_SOURCES
  # GTK program sources
)
if(FLOWD_GTK_SOURCES)
  add_executable(flowd-ui ${FLOWD_GTK_SOURCES})
  target_link_libraries(flowd-ui PRIVATE flowd-ui-core PkgConfig::FLOWD_GTK)
  target_link_options(flowd-ui PRIVATE -Wl,--no-as-needed $<$<CONFIG:Release>:-s>)
  if(flowd_lto)
    set_property(TARGET flowd-ui PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
  endif()
  # Fonts live next to the binary (ADR 0013). The woff2 files are the design
  # page's own copies; Pango >= 1.56 loads them as they are.
  add_custom_command(TARGET flowd-ui POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
            ${CMAKE_CURRENT_SOURCE_DIR}/../docs/design/assets/fonts
            $<TARGET_FILE_DIR:flowd-ui>/fonts)
endif()

set(FLOWD_GTK_TESTS
  # tests that need GTK (e.g. icon path parsing)
)
if(FLOWD_GTK_TESTS)
  add_executable(flowd-ui-gtk-tests tests/main.cpp ${FLOWD_GTK_TESTS})
  target_link_libraries(flowd-ui-gtk-tests PRIVATE flowd-ui-core PkgConfig::FLOWD_GTK)
  add_test(NAME gtk COMMAND flowd-ui-gtk-tests)
endif()
