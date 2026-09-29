#include <doctest/doctest.h>

#include "placement.hpp"

using namespace flowd;

TEST_CASE("placement: 4 px is still a click, more is a drag") {
    CHECK_FALSE(is_drag(4, 0));
    CHECK_FALSE(is_drag(2.8, 2.8));  // hypot < 4
    CHECK(is_drag(3, 3));            // hypot 4.24
    CHECK(is_drag(0, -5));
}

TEST_CASE("placement: centre snaps from 12 px, quarters from 8 px") {
    const int w = 1920;
    CHECK(snap_center(960 + 12, w).x == doctest::Approx(960));
    CHECK(snap_center(960 + 12, w).point == doctest::Approx(0.5));
    CHECK_FALSE(snap_center(960 + 13, w).point);
    CHECK(snap_center(480 + 8, w).point == doctest::Approx(0.25));
    CHECK_FALSE(snap_center(480 + 9, w).point);
}

TEST_CASE("placement: the pill stays 16 px inside the output") {
    CHECK(snap_center(0, 1920).x == doctest::Approx(16 + kPillW / 2.0));
    CHECK(snap_center(5000, 1920).x == doctest::Approx(1920 - 16 - kPillW / 2.0));
}

TEST_CASE("placement: fractions round-trip and clamp") {
    CHECK(from_fraction(to_fraction(700, 1920), 1920) == doctest::Approx(700));
    CHECK(from_fraction(-1.0, 1920) == doctest::Approx(16 + kPillW / 2.0));
    CHECK(to_fraction(960, 0) == doctest::Approx(0.5));  // unknown width: default
}

TEST_CASE("placement: popup width fits content, grows only, stays inside") {
    auto a = popup_card(1920, 960, 1, false, 0, 200);
    CHECK(a.w == kPopupMinW);
    auto b = popup_card(1920, 960, 2, false, a.w, 500);
    CHECK(b.w == 500);
    auto c = popup_card(1920, 960, 2, false, b.w, 300);
    CHECK(c.w == 500);  // never shrinks mid-session
    auto d = popup_card(1920, 960, 3, false, 0, 9000);
    CHECK(d.w == kPopupMaxW);
    auto narrow = popup_card(400, 200, 1, false, 0, 9000);
    CHECK(narrow.w == 400 - 32);
}

TEST_CASE("placement: popup is centred on the pill but clamped to the edge") {
    auto r = popup_card(1920, 100, 1, false, 0, 640);
    CHECK(r.x == kPopupEdge);
    auto m = popup_card(1920, 960, 1, false, 0, 640);
    CHECK(m.x == 960 - 320);
}

TEST_CASE("placement: popup height is 14 + 22n + 14, plus 28 for the footer") {
    CHECK(popup_card(1920, 960, 1, false, 0, 300).h == 50);
    CHECK(popup_card(1920, 960, 4, true, 0, 300).h == 14 + 88 + 14 + 28);
}

TEST_CASE("placement: a zero-width output never divides by zero") {
    CHECK(from_fraction(0.3, 0) == doctest::Approx(0));
    CHECK(snap_center(500, 0).x == doctest::Approx(0));
    CHECK_FALSE(snap_center(500, 0).point);
    CHECK(to_fraction(960, -5) == doctest::Approx(0.5));
}

TEST_CASE("placement: the indicator surface is centred on the pill") {
    CHECK(indicator_left_margin(960, 144) == 960 - 72);
    CHECK(indicator_left_margin(100.5, 145) == 28);
}
