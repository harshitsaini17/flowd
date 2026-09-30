#include "fonts.hpp"

#include <pango/pangocairo.h>

#include <algorithm>
#include <iostream>
#include <set>
#include <string>
#include <system_error>
#include <vector>

namespace flowd {

namespace {

constexpr const char* kLogPrefix = "flowd-ui: ";
constexpr const char* kFontExt = ".woff2";
constexpr const char* kFontsDirName = "fonts";
constexpr const char* kSelfExe = "/proc/self/exe";
// Where an installed build keeps them, set by CMake (FLOWD_FONTS_DIR).
#ifdef FLOWD_FONTS_DIR
constexpr const char* kInstalledFontsDir = FLOWD_FONTS_DIR;
#else
constexpr const char* kInstalledFontsDir = "";
#endif

// Once per distinct message: a respawned session re-registers the same
// files, and one line per broken file is enough.
void log_once(const std::string& msg) {
    static std::set<std::string> seen;
    if (!seen.insert(msg).second) return;
    std::cerr << kLogPrefix << msg << '\n';
}

}  // namespace

int register_fonts(const std::filesystem::path& dir) {
#if PANGO_VERSION_CHECK(1, 56, 0)
    std::error_code ec;
    std::filesystem::directory_iterator it(dir, ec);
    if (ec) {
        log_once("no bundled fonts at " + dir.string() + " (" + ec.message() +
                 "); using system fonts");
        return 0;
    }
    std::vector<std::filesystem::path> files;
    for (const auto& entry : it) {
        if (entry.path().extension() == kFontExt && entry.is_regular_file(ec))
            files.push_back(entry.path());
    }
    // A stable order, so the same file wins if two ever declare one family.
    std::sort(files.begin(), files.end());

    // The font map GTK's widgets draw with.
    PangoFontMap* map = pango_cairo_font_map_get_default();
    int added = 0;
    for (const auto& f : files) {
        GError* err = nullptr;
        if (pango_font_map_add_font_file(map, f.c_str(), &err)) {
            ++added;
            continue;
        }
        log_once("could not register font " + f.string() + ": " +
                 (err ? err->message : "unknown error"));
        if (err) g_error_free(err);
    }
    return added;
#else
    (void)dir;
    log_once("Pango is older than 1.56 and cannot load bundled fonts; using system fonts");
    return 0;
#endif
}

std::optional<std::filesystem::path> bundled_fonts_dir() {
    std::error_code ec;
    const auto exe = std::filesystem::read_symlink(kSelfExe, ec);
    if (!ec) {
        auto beside = exe.parent_path() / kFontsDirName;
        if (std::filesystem::is_directory(beside, ec)) return beside;
    } else {
        log_once(std::string("cannot read ") + kSelfExe + ": " + ec.message());
    }
    // An installed build keeps its fonts under the data directory instead.
    const std::filesystem::path installed = kInstalledFontsDir;
    if (!installed.empty() && std::filesystem::is_directory(installed, ec)) return installed;
    log_once("no bundled fonts beside the executable or at " + installed.string() +
             "; using system fonts");
    return std::nullopt;
}

}  // namespace flowd
