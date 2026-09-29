#include "meter.hpp"

#include <algorithm>
#include <cmath>

namespace flowd {

namespace {

// dBFS to 0..1 between the floor and the ceiling.
double normalise(double db) {
    return std::clamp((db - kFloorDb) / (kCeilDb - kFloorDb), 0.0, 1.0);
}

}  // namespace

void Meter::push(double rms_db, double peak_db) {
    // NaN would stick in the filter forever, and +inf rms is no real level
    // either; both read as silence. A bad peak never counts as clipping.
    if (!std::isfinite(rms_db)) rms_db = kFloorDb;
    if (!std::isfinite(peak_db)) peak_db = kFloorDb;
    if (queue_.size() >= kMaxQueued) queue_.pop_front();
    queue_.push_back({rms_db, peak_db});
}

bool Meter::tick(double dt_s) {
    // !(dt > 0) also catches NaN.
    if (!(dt_s > 0.0)) return false;

    accum_s_ += dt_s;
    bool consumed = false;
    if (!queue_.empty() && accum_s_ >= kWindowS) {
        const Window w = queue_.front();
        queue_.pop_front();
        accum_s_ -= kWindowS;
        target_ = normalise(w.rms_db);
        clip_run_ = w.peak_db >= kClipDb ? clip_run_ + 1 : 0;
        consumed = true;
    }
    if (queue_.empty()) {
        // Time with nothing to show is not banked: after an idle gap the next
        // window shows at once, but later ones still wait 50 ms each.
        accum_s_ = std::min(accum_s_, kWindowS);
    }

    // Scaling alpha by dt keeps the easing the same at any frame rate.
    const double alpha = 1.0 - std::exp(-dt_s / kTauS);
    smoothed_ += alpha * (target_ - smoothed_);
    return consumed;
}

std::array<double, 5> Meter::bar_heights() const {
    std::array<double, 5> h{};
    for (std::size_t i = 0; i < h.size(); ++i) {
        h[i] = kBarMin + (kBarMax - kBarMin) * smoothed_ * kBarGains[i];
    }
    return h;
}

double Meter::single_fill() const { return smoothed_; }

bool Meter::clipping() const { return clip_run_ >= kClipWindows; }

void Meter::reset() {
    queue_.clear();
    accum_s_ = 0.0;
    target_ = 0.0;
    smoothed_ = 0.0;
    clip_run_ = 0;
}

}  // namespace flowd
