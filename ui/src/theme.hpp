#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "protocol.hpp"

// design.md "Colors" and "Elevation & Depth" as plain values, so the GTK side
// only paints what these say and the token table is unit-tested.
namespace flowd {

struct Rgba {
    double r, g, b, a;
};

namespace detail {

constexpr int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

}  // namespace detail

// "#rrggbb" plus an alpha. Anything else is magenta, so a typo in a token is
// visible on screen instead of a crash or a silent black.
constexpr Rgba hex(std::string_view s, double alpha = 1.0) {
    constexpr Rgba kMagenta{1.0, 0.0, 1.0, 1.0};
    constexpr std::size_t kLen = 7;  // '#' and six digits
    if (s.size() != kLen || s[0] != '#') return {kMagenta.r, kMagenta.g, kMagenta.b, alpha};
    std::array<double, 3> ch{};
    for (std::size_t i = 0; i < ch.size(); ++i) {
        const int hi = detail::hex_digit(s[1 + 2 * i]);
        const int lo = detail::hex_digit(s[2 + 2 * i]);
        if (hi < 0 || lo < 0) return {kMagenta.r, kMagenta.g, kMagenta.b, alpha};
        ch[i] = (hi * 16 + lo) / 255.0;
    }
    return {ch[0], ch[1], ch[2], alpha};
}

// One CSS box-shadow layer: offset, blur and spread in px.
struct Shadow {
    double dx, dy, blur, spread;
    Rgba color;
};

// The tokens the indicator and popup draw with (design.md "Colors" → Roles).
struct Tokens {
    Rgba text, text2, sunken, border, border_strong, primary, primary_soft, live,
        record, record_fill, warn, danger, glass;
    // Pending words: text-2, or text in high contrast (design.md "High
    // contrast"), where the pending state relies on its underline instead.
    Rgba pending;
    // design.md "Elevation & Depth": shadow-float, two layers.
    std::array<Shadow, 2> shadow;
    // design.md "Glass material": dark glass adds a 1 px black-50% outer edge
    // on top of the white-10% inner one, so it separates from dark wallpaper.
    bool dark_edge;
    // design.md "Elevation & Depth": floating surfaces keep their edge but
    // drop shadow-float in high contrast, so drawing skips the shadow layers.
    bool high_contrast;
};

Tokens tokens(bool dark, bool high_contrast);

// Whether to draw dark. System follows the desktop; when neither GTK nor the
// portal says, design.md "Implementation notes" → Theme falls back to dark.
bool resolve_dark(Theme cfg, std::optional<bool> system_prefers_dark);

}  // namespace flowd
