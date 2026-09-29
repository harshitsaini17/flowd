#pragma once

#include <array>
#include <cstddef>

// Easing curves, duration tokens and retargeting tweens. The GTK side keeps a
// frame tick callback installed only while a Timeline reports a running
// tween. No GTK here, so all of it is unit-tested.
namespace flowd {

// A CSS-style cubic-bezier easing curve through (0,0), (x1,y1), (x2,y2), (1,1).
struct Bezier {
    double x1, y1, x2, y2;

    // Progress t (0..1, clamped; NaN reads as 0) to eased progress. Exactly 0
    // at 0 and exactly 1 at 1, so a finished tween lands on its target.
    double operator()(double t) const;
};

// design.md "Motion" → Tokens: ease-standard, for anything that moves and stays.
constexpr Bezier kStandard{0.2, 0.0, 0.0, 1.0};
// design.md "Motion" → Tokens: ease-enter, for appearing surfaces (decelerate).
constexpr Bezier kEnter{0.05, 0.7, 0.1, 1.0};
// design.md "Motion" → Tokens: ease-exit, for disappearing surfaces (accelerate).
constexpr Bezier kExit{0.3, 0.0, 0.8, 0.15};

// design.md "Motion" → Tokens: durations in ms.
constexpr int kInstant = 80;
constexpr int kFast = 120;
constexpr int kBase = 160;
constexpr int kSlow = 200;
constexpr int kFadeOut = 240;

// design.md "Motion" → Reduced motion: every animation becomes an 80 ms
// crossfade, so the duration collapses to kInstant.
int motion_ms(int ms, bool reduced);

// One animated value. Times are in seconds on the caller's monotonic clock.
class Tween {
public:
    // Animates from the value at now_s to target over ms. Starting from the
    // current value means retargeting mid-flight never jumps. A duration of
    // 0 or less jumps straight to the target. A NaN target is ignored, so a
    // bad input never poisons the value; a NaN now_s has nothing to time
    // against, so it also jumps to the target.
    void to(double target, int ms, Bezier e, double now_s);

    // Sets the value at once and stops any animation. NaN is ignored.
    void jump(double v);

    // from before the start, to after the end, eased in between. A NaN now_s
    // reads as the target.
    double value(double now_s) const;

    // True while now_s < start + duration. False for NaN.
    bool running(double now_s) const;

private:
    double from_ = 0.0;
    double to_ = 0.0;
    double start_s_ = 0.0;
    double duration_s_ = 0.0;
    Bezier easing_ = kStandard;
    bool active_ = false;
};

// A fixed set of N tweens, indexed by a caller-defined enum or small int. It
// lives in a std::array, so it never allocates.
template <std::size_t N>
class Timeline {
public:
    Tween& operator[](std::size_t i) { return tweens_[i]; }
    const Tween& operator[](std::size_t i) const { return tweens_[i]; }

    // Whether the frame tick callback should stay installed.
    bool any_running(double now_s) const {
        for (const Tween& t : tweens_) {
            if (t.running(now_s)) return true;
        }
        return false;
    }

private:
    std::array<Tween, N> tweens_{};
};

}  // namespace flowd
