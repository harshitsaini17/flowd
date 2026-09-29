#include "backend.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>

namespace flowd {

namespace {

constexpr std::string_view kGnome = "gnome";
constexpr char kDesktopSeparator = ':';

std::optional<std::string> env_var(const char* name) {
    const char* v = std::getenv(name);
    if (!v) return std::nullopt;
    return std::string(v);
}

bool present(const std::optional<std::string>& v) { return v && !v->empty(); }

bool equals_ignore_case(std::string_view a, std::string_view b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](char x, char y) {
               return std::tolower(static_cast<unsigned char>(x)) ==
                      std::tolower(static_cast<unsigned char>(y));
           });
}

}  // namespace

Env read_env() {
    return {env_var("WAYLAND_DISPLAY"), env_var("DISPLAY"), env_var("XDG_CURRENT_DESKTOP"),
            env_var("GSK_RENDERER")};
}

bool is_gnome(std::string_view desktops) {
    while (true) {
        const auto sep = desktops.find(kDesktopSeparator);
        if (equals_ignore_case(desktops.substr(0, sep), kGnome)) return true;
        if (sep == std::string_view::npos) return false;
        desktops.remove_prefix(sep + 1);
    }
}

Decision choose_backend(const Env& env, bool layer_shell_supported) {
    if (present(env.wayland_display)) {
        // Checked before layer-shell support: GNOME has no wlr-layer-shell,
        // and even if a shim claimed one, focus could not be guaranteed.
        if (env.xdg_current_desktop && is_gnome(*env.xdg_current_desktop))
            return {Backend::Unsupported,
                    "GNOME Wayland cannot guarantee the overlay never takes keyboard focus"};
        if (!layer_shell_supported)
            return {Backend::Unsupported,
                    "the Wayland compositor does not offer wlr-layer-shell, and a normal "
                    "window could take keyboard focus"};
        return {Backend::Wayland, "Wayland with layer-shell"};
    }
    if (present(env.display)) return {Backend::X11, "X11 with override-redirect windows"};
    return {Backend::Unsupported, "neither WAYLAND_DISPLAY nor DISPLAY is set"};
}

std::optional<std::string> renderer_default(const Env& env) {
    if (env.gsk_renderer) return std::nullopt;
    return std::string(kDefaultRenderer);
}

X11Origin x11_origin(const WorkArea& wa, int left_margin, int bottom_margin, int surface_w,
                     int surface_h) {
    const int x = wa.x + left_margin;
    const int y = wa.y + wa.h - bottom_margin - surface_h;
    // std::max after std::min, not std::clamp: clamp is undefined when the
    // surface is larger than the workarea, and the top-left edge should win.
    return {std::max(wa.x, std::min(x, wa.x + wa.w - surface_w)),
            std::max(wa.y, std::min(y, wa.y + wa.h - surface_h))};
}

}  // namespace flowd
