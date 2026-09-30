#include <doctest/doctest.h>

#include <gtk4-layer-shell.h>
#include <gtkmm/init.h>
#include <gtkmm/window.h>

#include <cstdlib>
#include <cstring>
#include <optional>
#include <string>

#include "backend.hpp"
#include "surface.hpp"

using namespace flowd;

namespace {

// Restores one environment variable when the test ends.
struct EnvGuard {
    const char* name;
    std::optional<std::string> saved;
    explicit EnvGuard(const char* n) : name(n) {
        if (const char* v = std::getenv(n)) saved = v;
    }
    ~EnvGuard() {
        if (saved)
            setenv(name, saved->c_str(), 1);
        else
            unsetenv(name);
    }
};

}  // namespace

TEST_CASE("surface: the cairo renderer is set only when the user chose none") {
    EnvGuard guard("GSK_RENDERER");
    EnvGuard disable("GDK_DISABLE");
    REQUIRE(unsetenv("GSK_RENDERER") == 0);
    REQUIRE(unsetenv("GDK_DISABLE") == 0);
    apply_env_defaults(Backend::Wayland);
    REQUIRE(std::getenv("GSK_RENDERER") != nullptr);
    CHECK(std::strcmp(std::getenv("GSK_RENDERER"), kDefaultRenderer) == 0);
    // GL stays available on Wayland.
    CHECK(std::getenv("GDK_DISABLE") == nullptr);

    REQUIRE(setenv("GSK_RENDERER", "gl", 1) == 0);
    apply_env_defaults(Backend::X11);
    CHECK(std::strcmp(std::getenv("GSK_RENDERER"), "gl") == 0);
    // The user's GL renderer keeps GL.
    CHECK(std::getenv("GDK_DISABLE") == nullptr);
}

TEST_CASE("surface: X11 with the cairo default also disables GL, unless the user set it") {
    EnvGuard guard("GSK_RENDERER");
    EnvGuard disable("GDK_DISABLE");
    REQUIRE(unsetenv("GSK_RENDERER") == 0);
    REQUIRE(unsetenv("GDK_DISABLE") == 0);
    apply_env_defaults(Backend::X11);
    REQUIRE(std::getenv("GDK_DISABLE") != nullptr);
    CHECK(std::strcmp(std::getenv("GDK_DISABLE"), "gl") == 0);

    REQUIRE(unsetenv("GSK_RENDERER") == 0);
    REQUIRE(setenv("GDK_DISABLE", "vulkan", 1) == 0);
    apply_env_defaults(Backend::X11);
    CHECK(std::strcmp(std::getenv("GDK_DISABLE"), "vulkan") == 0);
}

TEST_CASE("surface: anchor edges combine and test independently") {
    constexpr Edges e = Edges::Left | Edges::Bottom;
    CHECK(has(e, Edges::Left));
    CHECK(has(e, Edges::Bottom));
    CHECK_FALSE(has(e, Edges::Right));
    CHECK_FALSE(has(e, Edges::Top));
    CHECK_FALSE(has(Edges::NoEdge, Edges::Left));
}

// Needs a compositor with layer-shell; CI and headless runs skip it.
TEST_CASE("surface: a layer surface reads back keyboard mode NONE") {
    if (!std::getenv("WAYLAND_DISPLAY") || !gtk_init_check()) {
        MESSAGE("no Wayland display; skipped");
        return;
    }
    if (!layer_shell_supported()) {
        MESSAGE("compositor has no layer-shell; skipped");
        return;
    }
    Gtk::init_gtkmm_internals();
    auto* win = new Gtk::Window();
    std::optional<std::string> why_not;
    const bool ok = make_overlay_surface(*win, "flowd-test", Edges::Left | Edges::Bottom,
                                         {.left = 10, .bottom = 6}, why_not);
    CHECK_MESSAGE(ok, why_not.value_or(""));
    CHECK_FALSE(why_not);
    CHECK(gtk_layer_is_layer_window(win->gobj()));
    CHECK(gtk_layer_get_keyboard_mode(win->gobj()) == GTK_LAYER_SHELL_KEYBOARD_MODE_NONE);
    CHECK(gtk_layer_get_layer(win->gobj()) == GTK_LAYER_SHELL_LAYER_OVERLAY);
    CHECK(gtk_layer_get_margin(win->gobj(), GTK_LAYER_SHELL_EDGE_LEFT) == 10);
    CHECK(gtk_layer_get_exclusive_zone(win->gobj()) == -1);

    set_overlay_margins(*win, {.left = 42, .bottom = 6});
    CHECK(gtk_layer_get_margin(win->gobj(), GTK_LAYER_SHELL_EDGE_LEFT) == 42);

    // An empty input region must be accepted on a realized surface.
    gtk_widget_realize(GTK_WIDGET(win->gobj()));
    set_input_region(*win, {});
    set_input_region(*win, {Gdk::Rectangle(0, 0, kPillW, kPillH)});
    win->destroy();
    delete win;
}
