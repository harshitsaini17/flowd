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
  src/motion.cpp
  src/indicator_model.cpp
  src/popup_model.cpp
  src/popup_text.cpp
  src/footer.cpp
  src/theme.cpp
  src/icons.cpp
  src/backend.cpp
  src/indicator_geometry.cpp
  src/output_events.cpp
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
  tests/test_motion.cpp
  tests/test_indicator_model.cpp
  tests/test_popup_model.cpp
  tests/test_popup_text.cpp
  tests/test_footer.cpp
  tests/test_theme.cpp
  tests/test_backend.cpp
  tests/test_indicator_geometry.cpp
  tests/test_output_events.cpp
  tests/test_line_splitter.cpp
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
# (the layer-shell-link-order test checks this with readelf). That order is
# what lets it work without LD_PRELOAD.
pkg_check_modules(FLOWD_GTK REQUIRED IMPORTED_TARGET gtk4-layer-shell-0 gtkmm-4.0 gtk4-x11 x11)

# The GTK widgets and surfaces, shared by the program and the GTK tests.
set(FLOWD_GTK_LIB_SOURCES
  src/surface.cpp
  src/draw.cpp
  src/outputs.cpp
  src/indicator.cpp
  src/fonts.cpp
  src/popup.cpp
)
add_library(flowd-ui-gtk STATIC ${FLOWD_GTK_LIB_SOURCES})
target_link_libraries(flowd-ui-gtk PUBLIC flowd-ui-core PkgConfig::FLOWD_GTK)
# Where the fonts are looked for when none sit beside the binary.
include(GNUInstallDirs)
set(FLOWD_FONTS_DIR "${CMAKE_INSTALL_FULL_DATADIR}/flowd/fonts" CACHE PATH
    "Directory of the bundled fonts in an installed build")
target_compile_definitions(flowd-ui-gtk PRIVATE FLOWD_FONTS_DIR="${FLOWD_FONTS_DIR}")

set(FLOWD_GTK_SOURCES
  # GTK program sources
  src/main.cpp
  src/app.cpp
)
if(FLOWD_GTK_SOURCES)
  add_executable(flowd-ui ${FLOWD_GTK_SOURCES})
  target_link_libraries(flowd-ui PRIVATE flowd-ui-gtk)
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

  # With no display there is nothing to draw on: the program says so on
  # stdout and exits 3 before GTK init, which needs no compositor to test.
  add_test(NAME exits-without-display
    COMMAND ${CMAKE_COMMAND} -E env --unset=WAYLAND_DISPLAY --unset=DISPLAY
            $<TARGET_FILE:flowd-ui>)
  set_tests_properties(exits-without-display PROPERTIES
    PASS_REGULAR_EXPRESSION "\"event\":\"unsupported\"")
  # PASS_REGULAR_EXPRESSION ignores the exit code, so it is checked apart.
  add_test(NAME exits-without-display-code
    COMMAND sh -c "env -u WAYLAND_DISPLAY -u DISPLAY \"$1\" </dev/null >/dev/null 2>&1; test $? -eq 3"
            sh $<TARGET_FILE:flowd-ui>)

  # gtk4-layer-shell must be loaded before libwayland-client to intercept
  # GTK's surface creation without LD_PRELOAD (ADR 0003).
  find_program(FLOWD_READELF readelf)
  if(FLOWD_READELF)
    add_test(NAME layer-shell-link-order
      COMMAND ${CMAKE_COMMAND} -DREADELF=${FLOWD_READELF} -DBINARY=$<TARGET_FILE:flowd-ui>
              -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/check_link_order.cmake)
  else()
    message(STATUS "readelf not found; skipping the layer-shell link-order test")
  endif()
endif()

set(FLOWD_GTK_TESTS
  # tests that need GTK (e.g. icon path parsing)
  tests/test_icons_parse.cpp
  tests/test_surface.cpp
  tests/test_popup.cpp
)
if(FLOWD_GTK_TESTS)
  add_executable(flowd-ui-gtk-tests tests/main.cpp ${FLOWD_GTK_TESTS})
  target_link_libraries(flowd-ui-gtk-tests PRIVATE flowd-ui-gtk)
  # The design page's fonts, which the build ships next to the binary.
  target_compile_definitions(flowd-ui-gtk-tests PRIVATE
    FLOWD_TEST_FONTS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../docs/design/assets/fonts")
  add_test(NAME gtk COMMAND flowd-ui-gtk-tests)
endif()
