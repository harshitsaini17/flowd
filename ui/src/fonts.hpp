#pragma once

#include <filesystem>
#include <optional>

// The bundled Inter and JetBrains Mono (design.md "Typography"), registered
// with Pango so the overlay looks the same whatever the system has installed.
namespace flowd {

// Registers every *.woff2 in dir with the default Pango font map
// (pango_font_map_add_font_file, Pango >= 1.56) and returns how many it
// took. Each failure is logged once per process; on older Pango, or when
// none load, text falls back to the system's fonts. Call after GTK init,
// before the first layout is built.
int register_fonts(const std::filesystem::path& dir);

// <exe dir>/fonts, where the build copies the fonts (ADR 0013), with the exe
// dir from /proc/self/exe. When that directory is missing, FLOWD_FONTS_DIR
// (the installed data directory) instead; nothing when neither exists.
std::optional<std::filesystem::path> bundled_fonts_dir();

}  // namespace flowd
