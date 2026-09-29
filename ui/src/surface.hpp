#pragma once

#include <gtkmm/window.h>

#include <optional>
#include <string>
#include <vector>

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

// Sets GSK_RENDERER to kDefaultRenderer unless the user already set it. Must
// run before Gtk::Application is created: GTK picks its renderer when the
// first surface is realized and reads the variable only then.
void apply_env_defaults();

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

// Makes win an override-redirect window with WM_HINTS input=False, so no
// window manager maps, decorates or focuses it. Call after win is realized and
// before it is mapped. Returns false, with the reason logged, when win is not
// on an X11 display or an Xlib call fails; the caller must then not show win.
bool make_x11_overlay(Gtk::Window& win);

// Moves an override-redirect window the way LEFT|BOTTOM anchors and margins
// would place a layer surface, inside monitor's workarea. GTK4 has no public
// move call, so this uses XMoveWindow. Returns false when win is not realized
// on X11 or the move fails.
bool place_x11_overlay(Gtk::Window& win, const Glib::RefPtr<Gdk::Monitor>& monitor,
                       int left_margin, int bottom_margin);

// Limits pointer input to rects, given relative to the content inside the
// surface's shadow padding (so each is offset by pad). An empty vector means
// no input at all: every click falls through to the window below. win must
// be realized.
void set_input_region(Gtk::Window& win, const std::vector<Gdk::Rectangle>& rects,
                      int pad = kSurfacePad);

}  // namespace flowd
