#include "indicator_geometry.hpp"

#include <algorithm>
#include <cmath>

namespace flowd {

int indicator_surface_w(bool wide) { return wide ? kWarnSurfaceW : kSurfaceW; }

int indicator_surface_left(double center_x, int surface_w, int out_w) {
    const int left = indicator_left_margin(center_x, surface_w);
    // An output narrower than the surface keeps its left edge; nothing fits.
    if (out_w <= 0 || out_w < surface_w) return left;
    return std::clamp(left, 0, out_w - surface_w);
}

double pill_center_in_surface(double center_x, double pill_w, int surface_left, int out_w) {
    double cx = center_x;
    if (out_w > 0) {
        const double lo = kEdgeClampPx + pill_w / 2.0;
        const double hi = out_w - kEdgeClampPx - pill_w / 2.0;
        if (lo <= hi) cx = std::clamp(cx, lo, hi);
    }
    return cx - surface_left;
}

namespace {

double warn_fixed_w(bool blocking) {
    const double icon = blocking ? 0.0 : kWarnIconSize + kContentGap;
    return kButtonInset + kButtonD + kContentGap + icon + kWarnPadRight;
}

}  // namespace

double warn_text_max_w(bool blocking) { return kWarnPillMaxW - warn_fixed_w(blocking); }

double warn_pill_w(double text_w, bool blocking) {
    if (!std::isfinite(text_w) || text_w < 0) text_w = 0;
    // Never narrower than the ordinary pill, so a short reason doesn't shrink it.
    return std::clamp(warn_fixed_w(blocking) + text_w, double(kPillW), double(kWarnPillMaxW));
}

std::optional<PillRect> input_rect(InputRegion region, double pill_w, double pill_cx_in_surface) {
    const double cx = pill_cx_in_surface - kSurfacePad;  // content coordinates
    switch (region) {
    case InputRegion::Empty:
        return std::nullopt;
    case InputRegion::Strip: {
        // Centred on the idle line, whose bottom is the pill's bottom.
        const double line_cy = kPillH - kIdleLineH / 2.0;
        return PillRect{cx - kStripW / 2.0, line_cy - kStripH / 2.0, double(kStripW),
                        double(kStripH)};
    }
    case InputRegion::Pill:
        return PillRect{cx - kPillW / 2.0, 0.0, double(kPillW), double(kPillH)};
    case InputRegion::WarnPill:
        return PillRect{cx - pill_w / 2.0, 0.0, pill_w, double(kPillH)};
    }
    return std::nullopt;
}

void DragAnchor::begin(double center_x, int surface_left) {
    press_center_ = center_x;
    press_left_ = baseline_ = surface_left;
    committed_.reset();
}

double DragAnchor::output_dx(double dx) const { return dx + (baseline_ - press_left_); }

double DragAnchor::center_for(double dx) const { return press_center_ + output_dx(dx); }

void DragAnchor::committed(int surface_left) { committed_ = surface_left; }

void DragAnchor::presented() {
    if (committed_) baseline_ = *committed_;
    committed_.reset();
}

}  // namespace flowd
