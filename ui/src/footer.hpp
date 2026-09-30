#pragma once

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

// The popup footer's one-line layout: which items fit, in which order. The
// widget supplies a Pango-backed text measure; tests supply a fixed-width one.
namespace flowd {

enum class FooterKind {
    Mode,
    App,
    Elapsed,
    Hint,
    Status,
};

struct FooterItem {
    FooterKind kind;
    std::string text;
    // Only a status is ever ellipsized; everything else fits whole or drops.
    bool ellipsize = false;

    bool operator==(const FooterItem&) const = default;
};

struct FooterInput {
    std::string mode;
    std::string app;
    std::string elapsed;
    // The stop hint ("Super D to stop"), built from the hotkey label the user
    // typed in Settings. Empty means no hint: flowd never sees the
    // compositor binding.
    std::string hint;
    std::optional<std::string> status;

    bool operator==(const FooterInput&) const = default;
};

// Width in logical px of a run of footer text.
using TextMeasure = std::function<int(std::string_view)>;

// overlay.css .popup .foot: an 8 px gap between items.
constexpr int kFooterGapPx = 8;
// overlay.css .popup .foot .chip: 5 px + 12 px icon + 4 px gap on the left,
// 7 px on the right, around the mode label.
constexpr int kModeChipExtraPx = 5 + 12 + 4 + 7;
// design.md "Preview popup" → States: the status icon is 14 px, 8 px before
// its text.
constexpr int kStatusIconPx = 14 + kFooterGapPx;

// Width of a composed row: each item with what the widget draws around its
// text, plus the gaps between items. The card uses it for its natural width.
int footer_width(const std::vector<FooterItem>& items, const TextMeasure& measure);

// Items in order: mode chip, app id, elapsed time, stop hint, then a status
// if there is one. When avail_px runs out they drop as app id first, then
// elapsed time, then the stop hint. The mode chip always stays, and a status
// is kept and ellipsized last. Empty fields produce no item.
std::vector<FooterItem> compose_footer(const FooterInput& in, int avail_px, const TextMeasure& measure);

}  // namespace flowd
