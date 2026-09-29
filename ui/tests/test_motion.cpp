#include <doctest/doctest.h>

#include <cmath>
#include <limits>

#include "motion.hpp"

using namespace flowd;

TEST_CASE("motion: curves start at 0 and end at 1") {
    for (auto e : {kStandard, kEnter, kExit}) {
        CHECK(e(0.0) == doctest::Approx(0.0));
        CHECK(e(1.0) == doctest::Approx(1.0));
    }
    CHECK(kEnter(0.5) > kExit(0.5));  // enter is fast early, exit slow early
}

TEST_CASE("motion: every design curve is non-decreasing") {
    for (auto e : {kStandard, kEnter, kExit}) {
        double prev = e(0.0);
        for (int i = 1; i <= 100; ++i) {
            const double y = e(i / 100.0);
            CHECK(y >= prev);
            prev = y;
        }
    }
}

TEST_CASE("motion: a tween reaches its target on time and stops running") {
    Tween t; t.jump(0);
    t.to(1, kBase, kStandard, 10.0);
    CHECK(t.running(10.1));
    CHECK(t.value(10.0 + kBase / 1000.0) == doctest::Approx(1));
    CHECK_FALSE(t.running(10.0 + kBase / 1000.0 + 0.001));
}

TEST_CASE("motion: retargeting mid-flight starts from where it is, no jump") {
    Tween t; t.jump(0);
    t.to(1, kBase, kStandard, 0.0);
    double mid = t.value(0.08);
    t.to(0, kBase, kStandard, 0.08);
    CHECK(t.value(0.08) == doctest::Approx(mid));
}

TEST_CASE("motion: reduced motion turns every duration into an 80 ms crossfade") {
    CHECK(motion_ms(kSlow, true) == kInstant);
    CHECK(motion_ms(kSlow, false) == kSlow);
}

TEST_CASE("motion: a default tween sits at 0 and is idle; zero duration jumps") {
    Tween t;
    CHECK(t.value(0.0) == 0.0);
    CHECK_FALSE(t.running(0.0));
    t.to(5, 0, kStandard, 1.0);
    CHECK(t.value(1.0) == 5.0);
    CHECK_FALSE(t.running(1.0));
}

TEST_CASE("motion: a timeline runs while any of its tweens does") {
    Timeline<3> tl;
    CHECK_FALSE(tl.any_running(0.0));
    tl[0].to(1, kFast, kStandard, 0.0);
    tl[2].to(1, kSlow, kExit, 0.0);
    CHECK(tl.any_running(0.1));
    CHECK(tl.any_running(0.15));  // tl[0] is done, tl[2] is not
    CHECK_FALSE(tl.any_running(0.25));
}

TEST_CASE("motion: a NaN target or clock never poisons a tween") {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    Tween t; t.jump(0.5);
    t.to(nan, kBase, kStandard, 0.0);  // ignored
    CHECK(t.value(0.1) == 0.5);
    CHECK_FALSE(t.running(0.1));

    CHECK(std::isfinite(t.value(nan)));
    CHECK_FALSE(t.running(nan));

    t.to(1, kBase, kStandard, nan);  // no clock to time it against: settles at the target
    CHECK(t.value(0.0) == 1.0);
    t.to(0, kBase, kStandard, 1.0);  // and animates normally afterwards
    CHECK(t.running(1.1));
    CHECK(t.value(1.0 + kBase / 1000.0) == doctest::Approx(0));

    CHECK(std::isfinite(kStandard(nan)));
}
