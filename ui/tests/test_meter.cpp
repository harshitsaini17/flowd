#include <doctest/doctest.h>

#include <cmath>
#include <limits>

#include "meter.hpp"

using namespace flowd;

TEST_CASE("meter: silence sits at the floor, -12 dB reaches full height") {
    Meter m;
    for (int i = 0; i < 20; ++i) { m.push(-90, -90); m.tick(0.05); }
    for (double h : m.bar_heights()) CHECK(h == doctest::Approx(kBarMin));
    for (int i = 0; i < 40; ++i) { m.push(-12, -12); m.tick(0.05); }
    CHECK(m.bar_heights()[1] == doctest::Approx(kBarMax).epsilon(0.02));   // gain 1.0
    CHECK(m.bar_heights()[3] < m.bar_heights()[1]);                        // gain 0.7
}

TEST_CASE("meter: the low-pass smooths a single spike") {
    Meter m;
    m.push(-12, -12);
    m.tick(0.05);
    CHECK(m.bar_heights()[1] < kBarMax);
    CHECK(m.bar_heights()[1] > kBarMin);
}

TEST_CASE("meter: bursts are spread out at 20 Hz, never more than 4 queued") {
    Meter m;
    for (int i = 0; i < 10; ++i) m.push(-12, -12);
    int consumed = 0;
    for (int i = 0; i < 10; ++i) { if (m.tick(0.05)) ++consumed; }
    CHECK(consumed == 4);
}

TEST_CASE("meter: clipping needs three windows in a row") {
    Meter m;
    m.push(-6, -0.5); m.tick(0.05);
    m.push(-6, -0.5); m.tick(0.05);
    CHECK_FALSE(m.clipping());
    m.push(-6, -0.5); m.tick(0.05);
    CHECK(m.clipping());
    m.push(-6, -3); m.tick(0.05);
    CHECK_FALSE(m.clipping());
}

TEST_CASE("meter: reset clears the level, the queue and the clip run") {
    Meter m;
    for (int i = 0; i < 3; ++i) { m.push(-12, 0); m.tick(0.05); }
    m.push(-12, 0);
    REQUIRE(m.clipping());
    REQUIRE(m.single_fill() > 0.5);
    m.reset();
    CHECK_FALSE(m.clipping());
    CHECK(m.single_fill() == doctest::Approx(0));
    for (double h : m.bar_heights()) CHECK(h == doctest::Approx(kBarMin));
    // The accumulator restarts at zero, so a fresh window waits for its 50 ms.
    m.push(-12, -12);
    CHECK_FALSE(m.tick(0.01));
    CHECK(m.tick(0.05));
    CHECK_FALSE(m.tick(0.05));  // the window queued before reset went too
}

TEST_CASE("meter: non-finite input reads as silence and never clips") {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();
    Meter m;
    for (int i = 0; i < 4; ++i) { m.push(nan, nan); m.tick(0.05); }
    for (int i = 0; i < 4; ++i) { m.push(inf, inf); m.tick(0.05); }
    CHECK_FALSE(m.clipping());
    CHECK(m.single_fill() == doctest::Approx(0));
    for (double h : m.bar_heights()) {
        CHECK(std::isfinite(h));
        CHECK(h == doctest::Approx(kBarMin));
    }
}

TEST_CASE("meter: a non-positive or NaN dt is a no-op") {
    Meter m;
    m.push(-12, -12);
    CHECK_FALSE(m.tick(0));
    CHECK_FALSE(m.tick(-1));
    CHECK_FALSE(m.tick(std::numeric_limits<double>::quiet_NaN()));
    CHECK(m.single_fill() == doctest::Approx(0));
    CHECK(m.tick(0.05));  // the window is still there
}

TEST_CASE("meter: an idle gap is not banked into a later burst") {
    Meter m;
    CHECK_FALSE(m.tick(10));  // nothing queued
    m.push(-12, -12);
    m.push(-12, -12);
    CHECK(m.tick(0.001));        // the first waits no longer than 50 ms
    CHECK_FALSE(m.tick(0.001));  // the second waits for its own 50 ms
}

TEST_CASE("meter: single_fill tracks the smoothed level between 0 and 1") {
    Meter m;
    m.push(-36, -36);  // halfway between the floor and the ceiling
    for (int i = 0; i < 40; ++i) m.tick(0.05);
    CHECK(m.single_fill() == doctest::Approx(0.5).epsilon(0.01));
    m.push(0, -3);  // above the ceiling clamps to 1
    for (int i = 0; i < 40; ++i) m.tick(0.05);
    CHECK(m.single_fill() == doctest::Approx(1.0).epsilon(0.01));
}
