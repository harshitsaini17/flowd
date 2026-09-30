#pragma once

#include <gtkmm/window.h>

#include <optional>
#include <string>
#include <vector>

#include "backend.hpp"
#include "placement.hpp"

// The GTK side of backend.hpp: turning a Gtk::Window into a surface that can
// never take keyboard focus, as a layer surface on Wayland or an
// override-redirect window on X11 (ADR 0003, ADR 0013).
namespace flowd {

// Layer-shell anchor edges, combinable with |.
enum class Edges : unsigned {
    // Not "None": Xlib defines None as a macro, and X11 code includes both.
    NoEdge = 0,
    Left = 1u << 0,
    Right = 1u << 1,
    Top = 1u << 2,
    Bottom = 1u << 3,
};

constexpr Edges operator|(Edges a, Edges b) {
    return Edges(static_cast<unsigned>(a) | static_cast<unsigned>(b));
}
constexpr bool has(Edges set, Edges e) {
    return (static_cast<unsigned>(set) & static_cast<unsigned>(e)) != 0;
}

// Distances from the anchored output edges, in logical px.
struct Margins {
    int left = 0, right = 0, top = 0, bottom = 0;
};

// Sets GSK_RENDERER to kDefaultRenderer unless the user already set it. On
// X11 it then also sets GDK_DISABLE=gl (unless set), since GDK there creates
// a GL context even for the cairo renderer, which maps ~16 MB of driver
// state. Must run before Gtk::Application is created: GTK reads both only at
// display open and first realize.
void apply_env_defaults(Backend backend);

// Sets GDK_BACKEND to the backend choose_backend() picked, so GDK opens the
// display the surface code expects (with both WAYLAND_DISPLAY and DISPLAY
// set, GDK's own order could differ). Call before GTK init; Unsupported
// leaves it alone. Returns the user's own, different value it replaced, for
// the caller to log.
std::optional<std::string> pin_gdk_backend(Backend backend);

// Why GDK's default display is not the kind backend needs, or nothing when it
// is. Call after GTK init: a mismatch means the focus checks would run
// against the wrong windowing system.
std::optional<std::string> display_mismatch(Backend backend);

// True when the running compositor offers wlr-layer-shell. Needs an open
// display, so call it after GTK init.
bool layer_shell_supported();

// Makes win a layer surface: namespace ns, OVERLAY layer, keyboard mode NONE,
// exclusive zone 0, the given anchors and margins. Call before win is
// realized. Afterwards the result is read back, and when win is not a layer
// surface or its keyboard mode is not NONE, why_not says so and this returns
// false; the caller must then not show win (ADR 0003).
bool make_overlay_surface(Gtk::Window& win, const char* ns, Edges anchors, Margins margins,
                          std::optional<std::string>& why_not);

// Updates the margins of a window already set up by make_overlay_surface,
// e.g. the indicator's left margin while it is dragged.
void set_overlay_margins(Gtk::Window& win, Margins margins);

// X11 overlay windows. override-redirect keeps the window manager from ever
// managing (and so focusing) the window, and WM_HINTS input=False tells
// anything that looks that it takes no keyboard input (ADR 0013).
//
// Show these windows only with show_x11_overlay() (set_visible(true)), never
// Gtk::Window::present(): in GTK4 present() calls gdk_toplevel_focus, which
// sends _NET_ACTIVE_WINDOW and XSetInputFocus and so takes the focus the
// overlay must never have.

// Makes win an overlay window: override-redirect plus WM_HINTS input=False,
// read back from the X server afterwards. Realizes win if it is not yet, and
// re-applies and re-verifies both on every later realize (each one is a new
// X window) and the hint on every map (GDK rewrites WM_HINTS when mapping).
// Returns false with why_not set when win is not on an X11 display, an X
// error occurs, or the read-back disagrees; win must then not be shown.
// Calling it again on the same window is safe and adds no handlers.
bool make_x11_overlay(Gtk::Window& win, std::optional<std::string>& why_not);

// Shows a window set up by make_x11_overlay, without asking for focus.
// Refuses, returning false, when its current X window has not passed the
// read-back.
bool show_x11_overlay(Gtk::Window& win);

// Moves an override-redirect window the way LEFT|BOTTOM anchors and margins
// would place a layer surface, kept inside monitor's workarea. GTK4 has no
// public move call, so this uses XMoveWindow. Returns false when win is not
// realized on X11 or the X server reports an error.
bool place_x11_overlay(Gtk::Window& win, const Glib::RefPtr<Gdk::Monitor>& monitor,
                       int left_margin, int bottom_margin);

// Limits pointer input to rects, given relative to the content inside the
// surface's shadow padding (so each is offset by pad). An empty vector means
// no input at all: every click falls through to the window below. win must
// be realized.
void set_input_region(Gtk::Window& win, const std::vector<Gdk::Rectangle>& rects,
                      int pad = kSurfacePad);

}  // namespace flowd
