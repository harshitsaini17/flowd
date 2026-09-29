#include <doctest/doctest.h>

#include <optional>

#include "icons.hpp"
#include "theme.hpp"

using namespace flowd;

TEST_CASE("theme: hex parses #rrggbb and keeps the alpha") {
    auto c = hex("#9333ea", 0.5);
    CHECK(c.r == doctest::Approx(0x93 / 255.0));
    CHECK(c.g == doctest::Approx(0x33 / 255.0));
    CHECK(c.b == doctest::Approx(0xea / 255.0));
    CHECK(c.a == doctest::Approx(0.5));
    CHECK(hex("#FFFFFF").g == doctest::Approx(1.0));
}

TEST_CASE("theme: malformed hex is magenta, never a crash") {
    for (auto bad : {"oops", "", "#12345", "#1234567", "123456a", "#12345g"}) {
        auto c = hex(bad, 0.3);
        CHECK(c.r == doctest::Approx(1.0));
        CHECK(c.g == doctest::Approx(0.0));
        CHECK(c.b == doctest::Approx(1.0));
        CHECK(c.a == doctest::Approx(0.3));
    }
}

TEST_CASE("theme: hex works at compile time") {
    constexpr Rgba c = hex("#c42f2a");
    static_assert(c.a == 1.0);
    CHECK(c.r == doctest::Approx(0xc4 / 255.0));
}

TEST_CASE("theme: light and dark tokens match design.md") {
    auto l = tokens(false, false), d = tokens(true, false);
    CHECK(l.primary.r == doctest::Approx(0x93 / 255.0));
    CHECK(d.primary.r == doctest::Approx(0xc9 / 255.0));
    CHECK(l.glass.a == doctest::Approx(0.94));
    CHECK(d.glass.a == doctest::Approx(0.88));
    CHECK(d.glass.r == doctest::Approx(0x17 / 255.0));
    CHECK(l.border.a == doctest::Approx(0.10));
    CHECK(d.record_fill.r == doctest::Approx(0xd0 / 255.0));
    CHECK(l.pending.r == doctest::Approx(l.text2.r));
    CHECK(d.dark_edge);
    CHECK_FALSE(l.dark_edge);
}

TEST_CASE("theme: shadow-float has its two layers per theme") {
    auto l = tokens(false, false), d = tokens(true, false);
    CHECK(l.shadow[0].dy == doctest::Approx(1));
    CHECK(l.shadow[0].blur == doctest::Approx(2));
    CHECK(l.shadow[1].dy == doctest::Approx(8));
    CHECK(l.shadow[1].blur == doctest::Approx(24));
    CHECK(l.shadow[0].color.a == doctest::Approx(0.06));
    CHECK(d.shadow[1].color.a == doctest::Approx(0.5));
}

TEST_CASE("theme: high contrast makes glass opaque and borders strong") {
    for (bool dark : {false, true}) {
        auto h = tokens(dark, true);
        CHECK(h.glass.a == doctest::Approx(1.0));
        CHECK(h.border.r == doctest::Approx(h.border_strong.r));
        CHECK(h.border.a == doctest::Approx(1.0));
        CHECK(h.pending.r == doctest::Approx(h.text.r));
        CHECK(h.high_contrast);
        CHECK_FALSE(tokens(dark, false).high_contrast);
    }
}

// design.md "Implementation notes" → Theme: system falls back to dark.
TEST_CASE("theme: system follows the desktop, dark when unknown") {
    CHECK(resolve_dark(Theme::System, true));
    CHECK_FALSE(resolve_dark(Theme::System, false));
    CHECK(resolve_dark(Theme::System, std::nullopt));
    CHECK(resolve_dark(Theme::Dark, false));
    CHECK_FALSE(resolve_dark(Theme::Light, true));
}

TEST_CASE("icons: every icon has elements, modes map to their icons") {
    for (int i = 0; i < int(Icon::Count_); ++i) CHECK_FALSE(icon(Icon(i)).empty());
    CHECK(icon(Icon::Count_).empty());
    CHECK(app_icon("default") == Icon::FileText);
    CHECK(app_icon("code") == Icon::Code);
    CHECK(app_icon("chat") == Icon::MessageSquare);
    CHECK(app_icon("email") == Icon::Mail);
    CHECK(app_icon("unknown-mode") == Icon::AppWindow);
    CHECK(app_icon("") == Icon::AppWindow);
}
