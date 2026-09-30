#include "surface.hpp"

#include <gdkmm/monitor.h>
#include <gdkmm/surface.h>
#include <gtk4-layer-shell.h>

#include <cairomm/region.h>

#include <iostream>
#include <string>
#include <string_view>

#include "backend.hpp"

#include <gdk/wayland/gdkwayland.h>

// Xlib last: it defines macros such as None, Bool and Status that clash with
// C++ headers included after it.
#include <gdk/x11/gdkx.h>

namespace flowd {

namespace {

constexpr const char* kLogPrefix = "flowd-ui: ";
// ADR 0013: an overlay never reserves space; windows keep their full size.
constexpr int kExclusiveZone = 0;

// GDK_BACKEND values.
constexpr const char* kGdkWayland = "wayland";
constexpr const char* kGdkX11 = "x11";
// GDK_DISABLE feature name (GTK >= 4.16; older GTK ignores the variable).
constexpr const char* kGdkDisableGl = "gl";

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
    GdkDisplay* gdk_display;
    Display* dpy;
    Window xid;
    int scale;  // X11 works in device pixels, GTK in logical ones
};

std::optional<XTarget> x_target(Gtk::Window& win) {
    auto surface = win.get_surface();
    if (!surface) return std::nullopt;
    GdkSurface* s = surface->gobj();
    if (!GDK_IS_X11_SURFACE(s)) return std::nullopt;
    GdkDisplay* gd = gdk_surface_get_display(s);
    Display* dpy = gdk_x11_display_get_xdisplay(gd);
    const Window xid = gdk_x11_surface_get_xid(s);
    if (!dpy || xid == 0) return std::nullopt;
    return XTarget{gd, dpy, xid, gdk_surface_get_scale_factor(s)};
}

// Sets override-redirect (the window manager never sees the window, so it
// cannot map, decorate or focus it) and WM_HINTS input=False (the ICCCM "never
// give this keyboard focus", for anything that looks anyway).
void request_x11_overlay(const XTarget& t, bool override_redirect) {
    if (override_redirect) {
        XSetWindowAttributes attrs{};
        attrs.override_redirect = True;
        XChangeWindowAttributes(t.dpy, t.xid, CWOverrideRedirect, &attrs);
    }
    XWMHints hints{};
    hints.flags = InputHint;
    hints.input = False;
    XSetWMHints(t.dpy, t.xid, &hints);
}

// Applies the requests and reads them back from the server. Xlib requests are
// asynchronous and their return values say nothing, so errors come from the
// GDK error trap (whose pop syncs with the server) and success from the
// read-back, as ADR 0003 requires for layer surfaces.
bool apply_x11_overlay(const XTarget& t, bool override_redirect, std::string& why_not) {
    gdk_x11_display_error_trap_push(t.gdk_display);
    request_x11_overlay(t, override_redirect);
    XWindowAttributes attrs{};
    const Status got_attrs = XGetWindowAttributes(t.dpy, t.xid, &attrs);
    XWMHints* hints = XGetWMHints(t.dpy, t.xid);
    const bool no_input = hints && (hints->flags & InputHint) && hints->input == False;
    if (hints) XFree(hints);
    if (const int err = gdk_x11_display_error_trap_pop(t.gdk_display); err != 0) {
        why_not = "X error " + std::to_string(err) + " while setting up the overlay window";
        return false;
    }
    if (!got_attrs || !attrs.override_redirect) {
        why_not = "the X server did not keep override-redirect on the overlay window";
        return false;
    }
    if (!no_input) {
        why_not = "the X server did not keep WM_HINTS input=False on the overlay window";
        return false;
    }
    return true;
}

// Per-window bookkeeping, attached to the GObject: the X window that passed
// the read-back (each realize makes a new one), and whether the realize and
// map handlers are already connected, so repeated calls never stack them.
struct X11OverlayState {
    Window verified_xid = 0;
    bool hooked = false;
};
constexpr const char* kX11StateKey = "flowd-x11-overlay";

X11OverlayState& x11_state(Gtk::Window& win) {
    auto* st = static_cast<X11OverlayState*>(g_object_get_data(G_OBJECT(win.gobj()), kX11StateKey));
    if (!st) {
        st = new X11OverlayState();
        g_object_set_data_full(G_OBJECT(win.gobj()), kX11StateKey, st,
                               [](gpointer p) { delete static_cast<X11OverlayState*>(p); });
    }
    return *st;
}

// Sets up and verifies the window's current X window, recording the result.
bool setup_current_x_window(Gtk::Window& win, std::string& why_not) {
    auto& st = x11_state(win);
    st.verified_xid = 0;
    const auto t = x_target(win);
    if (!t) {
        why_not = "override-redirect needs a realized window on an X11 display";
        return false;
    }
    if (!apply_x11_overlay(*t, true, why_not)) return false;
    st.verified_xid = t->xid;
    return true;
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

}  // namespace

void apply_env_defaults(Backend backend) {
    const auto renderer = renderer_default(read_env());
    // A user-picked renderer may need GL, so GL is left alone then too.
    if (!renderer) return;
    if (!g_setenv("GSK_RENDERER", renderer->c_str(), FALSE))
        log_error("could not set GSK_RENDERER; GTK picks its default renderer");
    if (backend == Backend::X11 && !g_setenv("GDK_DISABLE", kGdkDisableGl, FALSE))
        log_error("could not set GDK_DISABLE; GDK may still load GL on X11");
}

std::optional<std::string> pin_gdk_backend(Backend backend) {
    const char* name = nullptr;
    switch (backend) {
    case Backend::Wayland:
        name = kGdkWayland;
        break;
    case Backend::X11:
        name = kGdkX11;
        break;
    case Backend::Unsupported:
        return std::nullopt;
    }
    // Overwrites a user's GDK_BACKEND on purpose: the focus guarantees are
    // only checked for the backend chosen here.
    std::optional<std::string> replaced;
    const char* user = g_getenv("GDK_BACKEND");
    if (user && *user && std::string_view(user) != name) replaced = user;
    if (!g_setenv("GDK_BACKEND", name, TRUE))
        log_error(std::string("could not set GDK_BACKEND=") + name);
    return replaced;
}

std::optional<std::string> display_mismatch(Backend backend) {
    GdkDisplay* d = gdk_display_get_default();
    if (!d) return "no display is open";
    switch (backend) {
    case Backend::Wayland:
        if (GDK_IS_WAYLAND_DISPLAY(d)) return std::nullopt;
        return "GDK opened a non-Wayland display for the Wayland backend";
    case Backend::X11:
        if (GDK_IS_X11_DISPLAY(d)) return std::nullopt;
        return "GDK opened a non-X11 display for the X11 backend";
    case Backend::Unsupported:
        break;
    }
    return "no backend is usable";
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

bool make_x11_overlay(Gtk::Window& win, std::optional<std::string>& why_not) {
    auto& st = x11_state(win);
    if (!st.hooked) {
        st.hooked = true;
        // Every realize creates a new X window with none of these settings,
        // so they are applied and verified again for each one. Connected
        // after the default handler, which is what creates the X window.
        win.signal_realize().connect(
            [&win] {
                std::string why;
                if (!setup_current_x_window(win, why)) log_error(why);
            },
            true);
        // GDK rewrites WM_HINTS (input=True) when it maps a surface, so the
        // hint is set again on every map. Override-redirect is untouched by
        // mapping and already verified; a window that loses the hint is
        // hidden rather than left up.
        win.signal_map().connect(
            [&win] {
                std::string why;
                const auto t = x_target(win);
                if (t && apply_x11_overlay(*t, false, why)) return;
                log_error(t ? why : "overlay window mapped without an X11 surface");
                x11_state(win).verified_xid = 0;
                win.set_visible(false);
            },
            true);
    }
    if (!win.get_realized()) gtk_widget_realize(GTK_WIDGET(win.gobj()));
    // The realize handler has already verified the window if the call above
    // realized it; otherwise it is done here.
    const auto t = x_target(win);
    if (t && st.verified_xid == t->xid) return true;
    std::string why;
    if (setup_current_x_window(win, why)) return true;
    why_not = why;
    return false;
}

bool show_x11_overlay(Gtk::Window& win) {
    const auto t = x_target(win);
    if (!t || x11_state(win).verified_xid != t->xid) {
        log_error("refusing to show an X11 overlay window that failed its checks");
        return false;
    }
    // Not present(): GTK4 present() asks the window manager to focus the
    // window (_NET_ACTIVE_WINDOW, XSetInputFocus).
    win.set_visible(true);
    // The map handler hides the window again if GDK's rewritten hints fail
    // the check, so report what is actually on screen.
    return win.get_visible() && x11_state(win).verified_xid == t->xid;
}

bool place_x11_overlay(Gtk::Window& win, const Glib::RefPtr<Gdk::Monitor>& monitor,
                       int left_margin, int bottom_margin) {
    const auto t = x_target(win);
    if (!t || !monitor) {
        log_error("place_x11_overlay needs a realized X11 window and a monitor");
        return false;
    }
    const auto surface = win.get_surface();
    const X11Origin o = x11_origin(workarea(monitor), left_margin, bottom_margin,
                                   surface->get_width(), surface->get_height());
    gdk_x11_display_error_trap_push(t->gdk_display);
    XMoveWindow(t->dpy, t->xid, o.x * t->scale, o.y * t->scale);
    if (const int err = gdk_x11_display_error_trap_pop(t->gdk_display); err != 0) {
        log_error("X error " + std::to_string(err) + " while moving the overlay window");
        return false;
    }
    return true;
}

G_GNUC_END_IGNORE_DEPRECATIONS

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
