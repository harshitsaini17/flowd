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

TEST_CASE("indicator geometry: a drag reads events against the presented surface") {
    DragAnchor a;
    a.begin(960, 888);
    // Before any margin change, the offset is the pointer's movement.
    CHECK(a.center_for(30) == doctest::Approx(990));
    // A margin of 918 is committed but not yet shown: events in flight are
    // still relative to 888, so the same offset means the same place.
    a.committed(918);
    CHECK(a.center_for(30) == doctest::Approx(990));
    // Once presented, events are relative to 918; the pointer at the same
    // output x now reads as offset 0.
    a.presented();
    CHECK(a.baseline() == 918);
    CHECK(a.center_for(0) == doctest::Approx(990));
    CHECK(a.output_dx(0) == doctest::Approx(30));
    // Presenting again without a new commit changes nothing.
    a.presented();
    CHECK(a.center_for(0) == doctest::Approx(990));
    CHECK(a.press_center() == doctest::Approx(960));
}

TEST_CASE("indicator geometry: steady pointer motion never runs ahead") {
    // The pointer moves 10 px per frame. Each frame commits the margin for
    // the latest event and the previous commit is presented. The pill centre
    // must track the pointer, not accelerate away from it.
    DragAnchor a;
    const double press_center = 500;
    const int press_left = 428;
    a.begin(press_center, press_left);
    int presented_left = press_left;
    for (int frame = 1; frame <= 50; ++frame) {
        const double pointer_dx = 10.0 * frame;  // on the output
        const double event_dx = pointer_dx - (presented_left - press_left);
        const double cx = a.center_for(event_dx);
        CHECK(cx == doctest::Approx(press_center + pointer_dx));
        a.presented();
        presented_left = a.baseline();
        a.committed(static_cast<int>(cx) - 72);
    }
}
