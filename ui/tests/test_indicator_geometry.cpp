#include <doctest/doctest.h>

#include "indicator_geometry.hpp"

using namespace flowd;

TEST_CASE("indicator geometry: surfaces are 144 x 54, or 384 x 54 with the warning pill") {
    CHECK(indicator_surface_w(false) == 144);
    CHECK(indicator_surface_w(true) == 384);
    CHECK(kSurfaceH == 54);
}

TEST_CASE("indicator geometry: the surface is centred on the pill and kept on the output") {
    CHECK(indicator_surface_left(960, 144, 1920) == 960 - 72);
    CHECK(indicator_surface_left(76, 384, 1920) == 0);
    CHECK(indicator_surface_left(1920 - 76, 384, 1920) == 1920 - 384);
    // Unknown output width: no clamp.
    CHECK(indicator_surface_left(76, 384, 0) == 76 - 192);
}

TEST_CASE("indicator geometry: a wide pill near an edge shifts inward") {
    const int out = 1920;
    const double cx = 76;  // the leftmost centre the 120 px pill allows
    const int left = indicator_surface_left(cx, 384, out);
    const double pill = 360;
    const double in_surface = pill_center_in_surface(cx, pill, left, out);
    CHECK(left + in_surface - pill / 2 == doctest::Approx(16));
    // The ordinary pill stays centred on its x.
    CHECK(pill_center_in_surface(960, 120, 888, out) == doctest::Approx(72));
}

TEST_CASE("indicator geometry: the warning pill fits its reason, 120 to 360 px") {
    CHECK(warn_pill_w(0, false) == doctest::Approx(kPillW));
    CHECK(warn_pill_w(1000, false) == doctest::Approx(kWarnPillMaxW));
    CHECK(warn_pill_w(100, false) == doctest::Approx(4 + 28 + 8 + 14 + 8 + 100 + 14));
    // mic-off takes the button, so no separate triangle.
    CHECK(warn_pill_w(100, true) == doctest::Approx(4 + 28 + 8 + 100 + 14));
    CHECK(warn_pill_w(-5, false) == doctest::Approx(kPillW));
    CHECK(warn_pill_w(warn_text_max_w(false), false) == doctest::Approx(kWarnPillMaxW));
}

TEST_CASE("indicator geometry: input regions per model region") {
    const double cx = kSurfaceW / 2.0;
    CHECK_FALSE(input_rect(InputRegion::Empty, 120, cx));

    auto strip = input_rect(InputRegion::Strip, 120, cx);
    REQUIRE(strip);
    CHECK(strip->w == doctest::Approx(120));
    CHECK(strip->h == doctest::Approx(20));
    CHECK(strip->x == doctest::Approx(0));
    // Centred on the idle line (bottom 8 px of the pill area).
    CHECK(strip->y + strip->h / 2 == doctest::Approx(kPillH - 4));

    auto pill = input_rect(InputRegion::Pill, 300, cx);
    REQUIRE(pill);
    CHECK(pill->w == doctest::Approx(kPillW));
    CHECK(pill->h == doctest::Approx(kPillH));
    CHECK(pill->y == doctest::Approx(0));

    auto warn = input_rect(InputRegion::WarnPill, 300, kWarnSurfaceW / 2.0);
    REQUIRE(warn);
    CHECK(warn->w == doctest::Approx(300));
    CHECK(warn->x == doctest::Approx(30));
}

TEST_CASE("indicator geometry: a drag follows the pointer across the surface switch") {
    // Pressed at centre 960 on a narrow surface whose left edge is 888.
    // Events still relative to the narrow surface: the offset is the motion.
    CHECK(drag_center(960, 888, 888, 30) == doctest::Approx(990));
    // Once the full-width surface (left edge 0) is in place, the same pointer
    // position reads as an offset 888 px larger, and lands on the same centre.
    CHECK(drag_center(960, 888, 0, 30 + 888) == doctest::Approx(990));
    CHECK(drag_center(960, 888, 0, 888 - 400) == doctest::Approx(560));
}

TEST_CASE("indicator geometry: events are read against the origin they were generated for") {
    // Pressed at centre 960, narrow surface at 888; the pointer is at +30.
    // An event still against the narrow surface says dx 32 (moved 2 px).
    CHECK(drag_event_origin(960, 888, 888, 0, 32, 990) == 888);
    // One against the full-width surface says dx 888 + 32.
    CHECK(drag_event_origin(960, 888, 888, 0, 888 + 32, 990) == 0);
    // Also when the pill moves leftward, past the old surface's edge.
    CHECK(drag_event_origin(960, 888, 888, 0, 888 - 200, 760) == 0);
    CHECK(drag_event_origin(960, 888, 888, 0, -205, 760) == 888);
}

TEST_CASE("indicator geometry: steady pointer motion tracks exactly on the full surface") {
    // The surface no longer moves, so there is no feedback between the pill
    // and the offsets: each event maps to the pointer, whatever the frame.
    const double press_center = 500;
    const int press_left = 428;
    for (int step = 1; step <= 50; ++step) {
        const double pointer_dx = 10.0 * step;          // on the output
        const double event_dx = pointer_dx + press_left;  // against origin 0
        CHECK(drag_center(press_center, press_left, 0, event_dx) ==
              doctest::Approx(press_center + pointer_dx));
    }
}

TEST_CASE("indicator geometry: on the full-width drag surface the pill sits at its centre") {
    const int out_w = 1920;
    // With the surface's left edge at 0, surface x is output x.
    CHECK(pill_center_in_surface(700, kPillW, 0, out_w) == doctest::Approx(700));
    // Still kept kEdgeClampPx inside the output.
    CHECK(pill_center_in_surface(10, kPillW, 0, out_w) ==
          doctest::Approx(kEdgeClampPx + kPillW / 2.0));
    // The input region is only the pill there; the rest of the output clicks
    // through.
    const auto r = input_rect(InputRegion::Pill, kPillW, 700);
    REQUIRE(r);
    CHECK(r->x == doctest::Approx(700 - kSurfacePad - kPillW / 2.0));
    CHECK(r->w == doctest::Approx(kPillW));
    CHECK(r->h == doctest::Approx(kPillH));
}
