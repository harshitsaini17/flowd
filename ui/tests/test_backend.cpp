#include <doctest/doctest.h>

#include "backend.hpp"

using namespace flowd;

TEST_CASE("backend: wayland with layer-shell uses it") {
    auto d = choose_backend({"wayland-1", ":1", "Hyprland", {}}, true);
    CHECK(d.backend == Backend::Wayland);
}

TEST_CASE("backend: wayland without layer-shell is unsupported, never a toplevel") {
    auto d = choose_backend({"wayland-1", ":1", "Hyprland", {}}, false);
    CHECK(d.backend == Backend::Unsupported);
    CHECK(d.reason.find("layer-shell") != std::string::npos);
}

TEST_CASE("backend: GNOME on Wayland is disabled with a reason") {
    auto d = choose_backend({"wayland-0", ":0", "GNOME", {}}, false);
    CHECK(d.backend == Backend::Unsupported);
    CHECK(d.reason.find("GNOME") != std::string::npos);
    auto u = choose_backend({"wayland-0", ":0", "ubuntu:GNOME", {}}, false);
    CHECK(u.backend == Backend::Unsupported);
}

TEST_CASE("backend: GNOME matches per token and in any case") {
    CHECK(is_gnome("gnome"));
    CHECK(is_gnome("ubuntu:GNOME"));
    CHECK(is_gnome("GNOME-Classic:GNOME"));
    CHECK_FALSE(is_gnome("GNOME-Flashback"));  // a token, not a substring
    CHECK_FALSE(is_gnome("KDE"));
    CHECK_FALSE(is_gnome(""));
}

TEST_CASE("backend: GNOME Wayland stays disabled even if layer-shell reads as present") {
    // ADR 0003: without a focus guarantee the overlay disables itself.
    auto d = choose_backend({"wayland-0", ":0", "GNOME", {}}, true);
    CHECK(d.backend == Backend::Unsupported);
    CHECK(d.reason.find("GNOME") != std::string::npos);
}

TEST_CASE("backend: X11 alone uses override-redirect") {
    CHECK(choose_backend({{}, ":0", "i3", {}}, false).backend == Backend::X11);
    // GNOME on Xorg is fine: override-redirect never takes focus there either.
    CHECK(choose_backend({{}, ":0", "GNOME", {}}, false).backend == Backend::X11);
}

TEST_CASE("backend: empty display variables count as unset") {
    CHECK(choose_backend({"", ":0", {}, {}}, false).backend == Backend::X11);
    CHECK(choose_backend({"", "", {}, {}}, false).backend == Backend::Unsupported);
}

TEST_CASE("backend: no display at all is unsupported") {
    auto d = choose_backend({}, false);
    CHECK(d.backend == Backend::Unsupported);
    CHECK_FALSE(d.reason.empty());
}

TEST_CASE("backend: cairo is the default renderer but a user choice wins") {
    CHECK(*renderer_default({}) == "cairo");
    CHECK_FALSE(renderer_default({{}, {}, {}, "gl"}));
}

TEST_CASE("backend: X11 origin turns bottom-left margins into a top-left point") {
    // A 1920x1080 monitor with a 30 px top panel: workarea y=30, h=1050.
    const X11Origin o = x11_origin({0, 30, 1920, 1050}, 900, 6, 48);
    CHECK(o.x == 900);
    CHECK(o.y == 30 + 1050 - 6 - 48);
    // A second monitor to the right keeps its own offset.
    const X11Origin r = x11_origin({1920, 0, 2560, 1440}, 100, 28, 200);
    CHECK(r.x == 2020);
    CHECK(r.y == 1440 - 28 - 200);
}
