#pragma once

#include <array>
#include <cstddef>
#include <deque>

// The recording level meter: level windows in, five bar heights out. No GTK
// here, so all of it is unit-tested.
namespace flowd {

// design.md "Indicator" → Recording: RMS is mapped -60 dB → 4 px, -12 dB → 20 px.
constexpr double kFloorDb = -60.0;
constexpr double kCeilDb = -12.0;
constexpr double kBarMin = 4.0;
constexpr double kBarMax = 20.0;
// design.md "Indicator" → Recording: a fixed per-bar offset × level, so the
// bars don't move in lockstep.
constexpr std::array<double, 5> kBarGains = {0.8, 1.0, 0.9, 0.7, 0.85};
// design.md "Indicator" → Recording: each bar eases toward its target with a
// 50 ms one-pole low-pass.
constexpr double kTauS = 0.05;
// design.md "Indicator" → Recording: clipping is peak >= -1 dBFS for >= 3
// consecutive windows.
constexpr double kClipDb = -1.0;
constexpr int kClipWindows = 3;
// design.md "Indicator" → Recording: one RMS window every 50 ms (20 Hz).
constexpr double kWindowS = 0.05;
// The daemon reads 100 ms blocks, so windows can arrive two at a time. Four
// is enough slack for that; beyond it the meter would lag behind the voice,
// so the oldest windows are dropped.
constexpr std::size_t kMaxQueued = 4;

class Meter {
public:
    // Queues one level window. Non-finite values read as silence (rms) and as
    // not clipping (peak), so a bad frame never poisons the filter.
    void push(double rms_db, double peak_db);

    // Advances time by dt_s: consumes at most one queued window once 50 ms
    // have elapsed, then runs the low-pass. Returns true when it consumed a
    // window. A non-positive or NaN dt does nothing and returns false.
    bool tick(double dt_s);

    // Bar heights in px, kBarMin to kBarMax.
    std::array<double, 5> bar_heights() const;
    // The smoothed level, 0 to 1, for the reduced-motion single bar.
    double single_fill() const;
    // True while the last kClipWindows consumed windows all clipped.
    bool clipping() const;

    // Back to silence with nothing queued; called at session start.
    void reset();

private:
    struct Window {
        double rms_db;
        double peak_db;
    };

    std::deque<Window> queue_;
    double accum_s_ = 0.0;   // time elapsed toward the next window
    double target_ = 0.0;    // normalised rms of the last consumed window
    double smoothed_ = 0.0;  // the low-passed level, normalised
    int clip_run_ = 0;       // consecutive consumed windows at or above kClipDb
};

}  // namespace flowd
