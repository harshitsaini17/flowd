#include <doctest/doctest.h>

#include "indicator_geometry.hpp"

using namespace flowd;

TEST_CASE("indicator geometry: surfaces are 144 x 54, or 384 x 54 with the warning pill") {
    CHECK(indicator_surface_w(false, 0) == 144);
    CHECK(indicator_surface_w(true, 0) == 384);
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

TEST_CASE("indicator geometry: the surface spans the output, so it never moves") {
    // As wide as the output, whichever pill it shows; a drag, a warning and a
    // hover all draw inside it and only change the input region.
    CHECK(indicator_surface_w(false, 1920) == 1920);
    CHECK(indicator_surface_w(true, 1920) == 1920);
    CHECK(indicator_surface_left(76, 1920, 1920) == 0);
    CHECK(indicator_surface_left(1844, 1920, 1920) == 0);
    // Until the output is known it is only as wide as the pill needs.
    CHECK(indicator_surface_w(false, 0) == kSurfaceW);
    CHECK(indicator_surface_w(true, 0) == kWarnSurfaceW);
    // An output narrower than the warning surface still fits the pill.
    CHECK(indicator_surface_w(true, 300) == kWarnSurfaceW);
}

TEST_CASE("indicator geometry: a drag puts the pill under the pointer") {
    // Pressed at centre 1844 (the bottom-right corner); every event maps to
    // the pointer's movement on the output, whatever the frame.
    for (int step = 1; step <= 50; ++step) {
        const double dx = -20.0 * step;
        CHECK(drag_center(1844, dx) == doctest::Approx(1844 + dx));
    }
    CHECK(drag_center(960, 0) == doctest::Approx(960));
}

TEST_CASE("indicator geometry: on the full-width surface the pill sits at its centre") {
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
