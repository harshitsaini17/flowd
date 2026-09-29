#include "surface.hpp"

#include <gdkmm/monitor.h>
#include <gdkmm/surface.h>
#include <gtk4-layer-shell.h>

#include <cairomm/region.h>

#include <iostream>

#include "backend.hpp"

// Xlib last: it defines macros such as None, Bool and Status that clash with
// C++ headers included after it.
#include <gdk/x11/gdkx.h>

namespace flowd {

namespace {

constexpr const char* kLogPrefix = "flowd-ui: ";
// ADR 0013: an overlay never reserves space; windows keep their full size.
constexpr int kExclusiveZone = 0;

void log_error(const std::string& msg) { std::cerr << kLogPrefix << msg << '\n'; }

void apply_margins(GtkWindow* w, Margins m) {
    gtk_layer_set_margin(w, GTK_LAYER_SHELL_EDGE_LEFT, m.left);
    gtk_layer_set_margin(w, GTK_LAYER_SHELL_EDGE_RIGHT, m.right);
    gtk_layer_set_margin(w, GTK_LAYER_SHELL_EDGE_TOP, m.top);
    gtk_layer_set_margin(w, GTK_LAYER_SHELL_EDGE_BOTTOM, m.bottom);
}

// The gdk_x11_* accessors are deprecated since GTK 4.18 (the X11 backend is
// on its way out) but are still the only way to reach the Xlib window, so the
// warnings are silenced here and only here.
G_GNUC_BEGIN_IGNORE_DEPRECATIONS

struct XTarget {
    Display* dpy;
    Window xid;
    int scale;  // X11 works in device pixels, GTK in logical ones
};

std::optional<XTarget> x_target(Gtk::Window& win) {
    auto surface = win.get_surface();
    if (!surface) return std::nullopt;
    GdkSurface* s = surface->gobj();
    if (!GDK_IS_X11_SURFACE(s)) return std::nullopt;
    Display* dpy = gdk_x11_display_get_xdisplay(gdk_surface_get_display(s));
    const Window xid = gdk_x11_surface_get_xid(s);
    if (!dpy || xid == 0) return std::nullopt;
    return XTarget{dpy, xid, gdk_surface_get_scale_factor(s)};
}

// WM_HINTS input=False: the ICCCM way to say "never give this keyboard focus".
bool set_no_input_hint(const XTarget& t) {
    XWMHints hints{};
    hints.flags = InputHint;
    hints.input = False;
    if (!XSetWMHints(t.dpy, t.xid, &hints)) return false;
    return XFlush(t.dpy) != 0;
}

WorkArea workarea(const Glib::RefPtr<Gdk::Monitor>& monitor) {
    GdkMonitor* m = monitor->gobj();
    GdkRectangle r{};
    if (GDK_IS_X11_MONITOR(m))
        gdk_x11_monitor_get_workarea(m, &r);
    else
        gdk_monitor_get_geometry(m, &r);
    return {r.x, r.y, r.width, r.height};
}

G_GNUC_END_IGNORE_DEPRECATIONS

}  // namespace

void apply_env_defaults() {
    if (!g_setenv("GSK_RENDERER", kDefaultRenderer, FALSE))
        log_error("could not set GSK_RENDERER; GTK picks its default renderer");
}

bool layer_shell_supported() { return gtk_layer_is_supported(); }

bool make_overlay_surface(Gtk::Window& win, const char* ns, Edges anchors, Margins margins,
                          std::optional<std::string>& why_not) {
    GtkWindow* w = win.gobj();
    if (!gtk_layer_is_supported()) {
        why_not = "the compositor does not offer wlr-layer-shell";
        return false;
    }
    gtk_layer_init_for_window(w);
    gtk_layer_set_namespace(w, ns);
    gtk_layer_set_layer(w, GTK_LAYER_SHELL_LAYER_OVERLAY);
    gtk_layer_set_keyboard_mode(w, GTK_LAYER_SHELL_KEYBOARD_MODE_NONE);
    gtk_layer_set_anchor(w, GTK_LAYER_SHELL_EDGE_LEFT, has(anchors, Edges::Left));
    gtk_layer_set_anchor(w, GTK_LAYER_SHELL_EDGE_RIGHT, has(anchors, Edges::Right));
    gtk_layer_set_anchor(w, GTK_LAYER_SHELL_EDGE_TOP, has(anchors, Edges::Top));
    gtk_layer_set_anchor(w, GTK_LAYER_SHELL_EDGE_BOTTOM, has(anchors, Edges::Bottom));
    apply_margins(w, margins);
    gtk_layer_set_exclusive_zone(w, kExclusiveZone);
    // A compositor's close request (e.g. on output removal) unmaps the window
    // instead of leaving a dead surface; the app decides whether to recreate.
    gtk_layer_set_respect_close(w, TRUE);

    // ADR 0003: trust what the library reports, not what was asked for.
    if (!gtk_layer_is_layer_window(w)) {
        why_not = std::string("window '") + ns + "' did not become a layer surface";
        return false;
    }
    if (gtk_layer_get_keyboard_mode(w) != GTK_LAYER_SHELL_KEYBOARD_MODE_NONE) {
        why_not = std::string("layer surface '") + ns + "' keyboard mode is not NONE";
        return false;
    }
    return true;
}

void set_overlay_margins(Gtk::Window& win, Margins margins) {
    if (!gtk_layer_is_layer_window(win.gobj())) {
        log_error("set_overlay_margins on a window that is not a layer surface");
        return;
    }
    apply_margins(win.gobj(), margins);
}

bool make_x11_overlay(Gtk::Window& win) {
    const auto t = x_target(win);
    if (!t) {
        log_error("override-redirect needs a realized window on an X11 display");
        return false;
    }
    XSetWindowAttributes attrs{};
    attrs.override_redirect = True;
    if (!XChangeWindowAttributes(t->dpy, t->xid, CWOverrideRedirect, &attrs)) {
        log_error("XChangeWindowAttributes(override_redirect) failed");
        return false;
    }
    if (!set_no_input_hint(*t)) {
        log_error("XSetWMHints(input=False) failed");
        return false;
    }
    // GDK writes its own WM_HINTS (input=True) when it shows a surface, so
    // the hint is set again once the window is mapped.
    win.signal_map().connect([&win] {
        if (const auto m = x_target(win); !m || !set_no_input_hint(*m))
            log_error("XSetWMHints(input=False) after map failed");
    });
    return true;
}

bool place_x11_overlay(Gtk::Window& win, const Glib::RefPtr<Gdk::Monitor>& monitor,
                       int left_margin, int bottom_margin) {
    const auto t = x_target(win);
    if (!t || !monitor) {
        log_error("place_x11_overlay needs a realized X11 window and a monitor");
        return false;
    }
    const X11Origin o =
        x11_origin(workarea(monitor), left_margin, bottom_margin, win.get_surface()->get_height());
    if (!XMoveWindow(t->dpy, t->xid, o.x * t->scale, o.y * t->scale)) {
        log_error("XMoveWindow failed");
        return false;
    }
    if (!XFlush(t->dpy)) {
        log_error("XFlush after XMoveWindow failed");
        return false;
    }
    return true;
}

void set_input_region(Gtk::Window& win, const std::vector<Gdk::Rectangle>& rects, int pad) {
    auto surface = win.get_surface();
    if (!surface) {
        log_error("set_input_region on a window that is not realized");
        return;
    }
    // An empty region, not a null one: null would mean "the whole surface".
    auto region = Cairo::Region::create();
    for (const auto& r : rects)
        region->do_union(Cairo::RectangleInt{r.get_x() + pad, r.get_y() + pad, r.get_width(),
                                             r.get_height()});
    surface->set_input_region(region);
}

}  // namespace flowd
