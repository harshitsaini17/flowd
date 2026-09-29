#include "placement.hpp"

#include <algorithm>
#include <cmath>

namespace flowd {

namespace {

// The pill centre's allowed range on an output of width w (> 0).
double clamp_center(double center_x, int w) {
    const double lo = kEdgeClampPx + kPillW / 2.0;
    const double hi = w - kEdgeClampPx - kPillW / 2.0;
    // An output too narrow for the pill plus both edges: centre it.
    if (lo > hi) return w / 2.0;
    return std::clamp(center_x, lo, hi);
}

}  // namespace

bool is_drag(double dx, double dy) { return std::hypot(dx, dy) > kDragThresholdPx; }

// Widths of 0 or less are guarded throughout: hyprctl can report 0 for a
// monitor that is being disabled mid-query.
Snap snap_center(double center_x, int output_width) {
    if (output_width <= 0) return {0.0, std::nullopt};  // the zero-width output's centre
    const double x = clamp_center(center_x, output_width);

    double best = kSnapPoints.front();
    for (double p : kSnapPoints) {
        if (std::abs(x - p * output_width) < std::abs(x - best * output_width)) best = p;
    }
    const double range = best == kSnapCenter ? kSnapCenterRangePx : kSnapRangePx;
    const double snapped = best * output_width;
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

CardRect popup_card(int output_w, double center_x, int lines, bool footer, int prev_w, int natural_w) {
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

    const int h = kPopupPadY + kPopupLineH * lines + kPopupPadY + (footer ? kPopupFooterH : 0);

    return {x, kCardBottomAboveEdge, w, h};
}

}  // namespace flowd
