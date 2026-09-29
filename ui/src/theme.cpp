#include "theme.hpp"

namespace flowd {

namespace {

// design.md "Colors" → Roles: border is black (light) or white (dark) at 10%.
constexpr double kHairlineAlpha = 0.10;
// design.md "Glass material": 94% white, 88% Charcoal. High contrast is opaque.
constexpr double kGlassLightAlpha = 0.94;
constexpr double kGlassDarkAlpha = 0.88;
constexpr double kOpaque = 1.0;

// design.md "Elevation & Depth" → shadow-float:
// 0 1px 2px, 0 8px 24px; light .06/.08, dark .4/.5.
constexpr Shadow kFloatNear{0, 1, 2, 0, {0, 0, 0, 0}};
constexpr Shadow kFloatFar{0, 8, 24, 0, {0, 0, 0, 0}};
constexpr double kShadowLightNear = 0.06;
constexpr double kShadowLightFar = 0.08;
constexpr double kShadowDarkNear = 0.4;
constexpr double kShadowDarkFar = 0.5;

Shadow with_alpha(Shadow s, double a) {
    s.color = hex("#000000", a);
    return s;
}

Tokens light() {
    Tokens t{};
    t.text = hex("#000000");
    t.text2 = hex("#6c6b6b");
    t.sunken = hex("#f1f1f1");
    t.border = hex("#000000", kHairlineAlpha);
    t.border_strong = hex("#8a8989");
    t.primary = hex("#9333ea");
    t.primary_soft = hex("#f5edfe");
    t.live = hex("#8b2fd9");
    t.record = hex("#c42f2a");
    t.record_fill = hex("#c42f2a");
    t.warn = hex("#835500");
    t.danger = hex("#b8261f");
    t.glass = hex("#ffffff", kGlassLightAlpha);
    t.shadow = {with_alpha(kFloatNear, kShadowLightNear), with_alpha(kFloatFar, kShadowLightFar)};
    t.dark_edge = false;
    return t;
}

Tokens dark() {
    Tokens t{};
    t.text = hex("#ffffff");
    t.text2 = hex("#a3a3a3");
    t.sunken = hex("#0b0b0b");
    t.border = hex("#ffffff", kHairlineAlpha);
    t.border_strong = hex("#6e6d6d");
    t.primary = hex("#c98bfb");
    t.primary_soft = hex("#2a1840");
    t.live = hex("#c98bfb");
    t.record = hex("#ff6b66");
    t.record_fill = hex("#d03b36");
    t.warn = hex("#f2b34c");
    t.danger = hex("#ff7470");
    t.glass = hex("#171717", kGlassDarkAlpha);
    t.shadow = {with_alpha(kFloatNear, kShadowDarkNear), with_alpha(kFloatFar, kShadowDarkFar)};
    t.dark_edge = true;
    return t;
}

}  // namespace

Tokens tokens(bool is_dark, bool high_contrast) {
    Tokens t = is_dark ? dark() : light();
    t.pending = t.text2;
    if (high_contrast) {
        // design.md "High contrast": opaque glass, border-strong edges, and
        // pending words in text.
        t.glass.a = kOpaque;
        t.border = t.border_strong;
        t.pending = t.text;
    }
    return t;
}

bool resolve_dark(Theme cfg, std::optional<bool> system_prefers_dark) {
    switch (cfg) {
    case Theme::Light:
        return false;
    case Theme::Dark:
        return true;
    case Theme::System:
        break;
    }
    return system_prefers_dark.value_or(true);
}

}  // namespace flowd
