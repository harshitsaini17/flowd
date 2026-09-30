#include "footer.hpp"

#include <array>
#include <cstddef>

namespace flowd {

namespace {

// Width of one item, including what the widget draws around its text.
int item_width(const FooterItem& item, const TextMeasure& measure) {
    const int text = measure(item.text);
    switch (item.kind) {
    case FooterKind::Mode:
        return text + kModeChipExtraPx;
    case FooterKind::Status:
        return text + kStatusIconPx;
    case FooterKind::App:
    case FooterKind::Elapsed:
    case FooterKind::Hint:
        break;
    }
    return text;
}

int row_width(const std::vector<FooterItem>& items, const TextMeasure& measure) {
    int w = 0;
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i > 0) w += kFooterGapPx;
        w += item_width(items[i], measure);
    }
    return w;
}

}  // namespace

int footer_width(const std::vector<FooterItem>& items, const TextMeasure& measure) {
    if (!measure) return 0;
    return row_width(items, measure);
}

std::vector<FooterItem> compose_footer(const FooterInput& in, int avail_px, const TextMeasure& measure) {
    std::vector<FooterItem> items;
    if (!in.mode.empty()) items.push_back({FooterKind::Mode, in.mode});
    if (!in.app.empty()) items.push_back({FooterKind::App, in.app});
    if (!in.elapsed.empty()) items.push_back({FooterKind::Elapsed, in.elapsed});
    if (!in.hint.empty()) items.push_back({FooterKind::Hint, in.hint});
    if (in.status) items.push_back({FooterKind::Status, *in.status, true});
    if (!measure) return items;

    // design.md "Preview popup": the least important part goes first.
    constexpr std::array kDropOrder = {FooterKind::App, FooterKind::Elapsed, FooterKind::Hint};
    for (FooterKind drop : kDropOrder) {
        if (row_width(items, measure) <= avail_px) return items;
        std::erase_if(items, [drop](const FooterItem& i) { return i.kind == drop; });
    }
    // What is left is the mode chip and the status, which the widget
    // ellipsizes (ellipsize is already set) rather than drops.
    return items;
}

}  // namespace flowd
