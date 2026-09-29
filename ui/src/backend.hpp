#pragma once

#include <optional>
#include <string>
#include <string_view>

// Which display backend flowd-ui may use, decided from the environment alone.
// No GTK here, so every branch is unit-tested; the GTK side lives in surface.hpp.
namespace flowd {

// The environment variables the choice depends on. An empty value is treated
// the same as an unset one.
struct Env {
    std::optional<std::string> wayland_display, display, xdg_current_desktop, gsk_renderer;
};

enum class Backend {
    Wayland,      // layer-shell surfaces
    X11,          // override-redirect windows
    Unsupported,  // no surface can be guaranteed never to take focus
};

struct Decision {
    Backend backend;
    std::string reason;  // why, for the log and the `unsupported` event
};

// The renderer flowd-ui asks GSK for when the user has not picked one. Cairo
// keeps the process inside the 40 MB memory budget (ADR 0013); GL and Vulkan
// renderers map several MB of driver state each.
constexpr const char* kDefaultRenderer = "cairo";

// Reads the variables above from the process environment.
Env read_env();

// True when one of XDG_CURRENT_DESKTOP's ':'-separated tokens is "gnome",
// ignoring case, so "ubuntu:GNOME" matches and "GNOME-Flashback" does not.
bool is_gnome(std::string_view xdg_current_desktop);

// ADR 0003 and 0013: on Wayland only a layer surface with keyboard mode NONE
// is acceptable, never a normal toplevel, and GNOME Wayland is always refused.
// Without Wayland, an X display means override-redirect windows.
Decision choose_backend(const Env& env, bool layer_shell_supported);

// kDefaultRenderer unless GSK_RENDERER is set, in which case the user's
// choice stands and nothing is returned.
std::optional<std::string> renderer_default(const Env& env);

// A monitor's X11 workarea in root-window coordinates.
struct WorkArea {
    int x, y, w, h;
};

struct X11Origin {
    int x, y;
};

// The top-left root position of a surface_w x surface_h window placed like a
// LEFT|BOTTOM-anchored layer surface: left margin from the workarea's left
// edge, bottom margin above its bottom edge. X11 has no anchors, so the
// window is moved here with XMoveWindow instead. The result is clamped so the
// window stays inside the workarea (the top-left edge wins when it is larger
// than the workarea), as a compositor keeps a layer surface on its output.
X11Origin x11_origin(const WorkArea& wa, int left_margin, int bottom_margin, int surface_w,
                     int surface_h);

}  // namespace flowd
