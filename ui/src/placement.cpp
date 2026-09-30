#include "placement.hpp"

#include <algorithm>
#include <cmath>

namespace flowd {

namespace {

struct Range {
    double lo, hi;
};

// The pill centre's allowed range on an output of width w (> 0). An output
// too narrow for the pill plus both edges collapses it to the output centre.
Range center_range(int w) {
    const double lo = kEdgeClampPx + kPillW / 2.0;
    const double hi = w - kEdgeClampPx - kPillW / 2.0;
    if (lo > hi) return {w / 2.0, w / 2.0};
    return {lo, hi};
}

double clamp_center(double center_x, int w) {
    const Range r = center_range(w);
    return std::clamp(center_x, r.lo, r.hi);
}

}  // namespace

// design.md "Indicator" → Dragging: "> 4 px horizontally", so dy is ignored.
bool is_drag(double dx, double /*dy*/) { return std::abs(dx) > kDragThresholdPx; }

// Widths of 0 or less are guarded throughout: hyprctl can report 0 for a
// monitor that is being disabled mid-query.
Snap snap_center(double center_x, int output_width) {
    if (output_width <= 0) return {0.0, std::nullopt};  // the zero-width output's centre
    const Range r = center_range(output_width);
    const double x = std::clamp(center_x, r.lo, r.hi);

    // Nearest snap point that the clamp allows; on a narrow output the
    // quarters can fall inside the edge margin and must not pull the pill there.
    std::optional<double> best;
    for (double p : kSnapPoints) {
        const double px = p * output_width;
        if (px < r.lo || px > r.hi) continue;
        if (!best || std::abs(x - px) < std::abs(x - *best * output_width)) best = p;
    }
    if (!best) return {x, std::nullopt};

    const double range = *best == kSnapCenter ? kSnapCenterRangePx : kSnapRangePx;
    const double snapped = *best * output_width;
    if (std::abs(x - snapped) <= range) return {snapped, best};
    return {x, std::nullopt};
}

double to_fraction(double center_x, int output_width) {
    if (output_width <= 0) return kDefaultFraction;
    return clamp_center(center_x, output_width) / output_width;
}

double from_fraction(double f, int output_width) {
    // The centre of a zero-width output is 0.
    if (output_width <= 0) return 0.0;
    return clamp_center(f * output_width, output_width);
}

int indicator_left_margin(double center_x, int surface_w) {
    return static_cast<int>(std::lround(center_x - surface_w / 2.0));
}

CardRect popup_card(int output_w, double center_x, int lines, bool footer, int prev_w,
                    int natural_w) {
    const int inner = std::max(0, output_w - 2 * kPopupEdge);
    int w;
    if (inner < kPopupMinW) {
        // Narrower than the minimum card: fill the output minus its edges so
        // the card never overflows.
        w = inner;
    } else {
        w = std::clamp(std::max(prev_w, natural_w), kPopupMinW, std::min(kPopupMaxW, inner));
    }

    const int x_hi = std::max(kPopupEdge, output_w - kPopupEdge - w);
    const int x = std::clamp(static_cast<int>(std::lround(center_x - w / 2.0)), kPopupEdge, x_hi);

    const int n = std::max(kPopupMinLines, lines);
    const int h = kPopupPadY + kPopupLineH * n + kPopupPadY + (footer ? kPopupFooterH : 0);

    return {x, kCardBottomAboveEdge, w, h};
}

int popup_surface_w(int output_w) {
    return std::clamp(output_w, 0, kPopupSurfaceMaxW);
}

int popup_surface_left(int output_w, double center_x) {
    // The widest card this centre can get; it holds every narrower one.
    const CardRect widest = popup_card(output_w, center_x, kPopupMinLines, false, 0, kPopupMaxW);
    const int hi = std::max(0, output_w - popup_surface_w(output_w));
    return std::clamp(widest.x - kPopupPad, 0, hi);
}

int popup_surface_h(int max_lines) {
    const int n = std::max(kPopupMinLines, max_lines);
    return kPopupPad + kPopupPadY + kPopupLineH * n + kPopupPadY + kPopupFooterH + kPopupPad;
}

}  // namespace flowd
