#include "motion.hpp"

#include <algorithm>
#include <cmath>

namespace flowd {

namespace {

// Newton converges in a handful of steps on these curves; 8 is headroom.
constexpr int kNewtonIterations = 8;
// Below this slope a Newton step would overshoot wildly, so bisect instead.
constexpr double kMinSlope = 1e-6;
// Far finer than a pixel over any duration the design uses.
constexpr double kSolveEpsilon = 1e-7;
// Halving [0, 1] 40 times gets well under kSolveEpsilon.
constexpr int kBisectIterations = 40;

// One coordinate of the curve at parameter u, with endpoints 0 and 1 and
// control points p1 and p2 (the standard cubic Bernstein form).
double bezier_at(double p1, double p2, double u) {
    const double v = 1.0 - u;
    return 3.0 * v * v * u * p1 + 3.0 * v * u * u * p2 + u * u * u;
}

// Its derivative with respect to u.
double bezier_slope(double p1, double p2, double u) {
    const double v = 1.0 - u;
    return 3.0 * v * v * p1 + 6.0 * v * u * (p2 - p1) + 3.0 * u * u * (1.0 - p2);
}

}  // namespace

double Bezier::operator()(double t) const {
    if (!(t > 0.0)) return 0.0;  // also catches NaN
    if (t >= 1.0) return 1.0;

    // Solve x(u) = t. x is monotonic for x1, x2 in [0, 1], so the root is unique.
    double u = t;
    bool solved = false;
    for (int i = 0; i < kNewtonIterations; ++i) {
        const double err = bezier_at(x1, x2, u) - t;
        if (std::abs(err) < kSolveEpsilon) {
            solved = true;
            break;
        }
        const double slope = bezier_slope(x1, x2, u);
        if (std::abs(slope) < kMinSlope) break;
        u -= err / slope;
        if (u < 0.0 || u > 1.0) break;
    }
    if (!solved) {
        double lo = 0.0;
        double hi = 1.0;
        u = t;
        for (int i = 0; i < kBisectIterations; ++i) {
            const double x = bezier_at(x1, x2, u);
            if (std::abs(x - t) < kSolveEpsilon) break;
            if (x < t) lo = u;
            else hi = u;
            u = 0.5 * (lo + hi);
        }
    }
    return bezier_at(y1, y2, u);
}

int motion_ms(int ms, bool reduced) { return reduced ? kInstant : ms; }

void Tween::to(double target, int ms, Bezier e, double now_s) {
    // A NaN target would stick in to_ and every later value(); ignore it.
    if (std::isnan(target)) return;
    if (ms <= 0 || !std::isfinite(now_s)) {
        jump(target);
        return;
    }
    from_ = value(now_s);  // from wherever it is now, so a retarget never jumps
    to_ = target;
    start_s_ = now_s;
    duration_s_ = ms / 1000.0;
    easing_ = e;
    active_ = true;
}

void Tween::jump(double v) {
    if (std::isnan(v)) return;
    from_ = v;
    to_ = v;
    active_ = false;
}

double Tween::value(double now_s) const {
    if (!active_ || std::isnan(now_s)) return to_;
    if (now_s <= start_s_) return from_;
    const double end_s = start_s_ + duration_s_;
    if (now_s >= end_s) return to_;
    return from_ + (to_ - from_) * easing_((now_s - start_s_) / duration_s_);
}

bool Tween::running(double now_s) const {
    // NaN compares false, so a NaN clock reads as not running.
    return active_ && now_s < start_s_ + duration_s_;
}

}  // namespace flowd
