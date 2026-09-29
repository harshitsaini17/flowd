#pragma once

#include <optional>
#include <string>

#include "protocol.hpp"

// What the indicator shows, when, and what it accepts clicks on. The widget
// only draws what this says. Time is passed in explicitly (seconds on the
// caller's monotonic clock), so every delay is unit-tested without GTK.
namespace flowd {

// design.md "Indicator" → Hover: enter delay 80 ms, so a pointer crossing the
// screen edge on its way elsewhere never expands the pill; leave delay 240 ms.
constexpr double kHoverEnterS = 0.08;
constexpr double kHoverLeaveS = 0.24;
// design.md "Indicator" → Hover: the grip fades in only after 600 ms of hover.
constexpr double kGripDelayS = 0.6;
// design.md "Latency honesty": a paste within 120 ms of release skips the
// Finishing visuals, so fast sessions don't flicker a spinner.
constexpr double kFinishGraceS = 0.12;

enum class IndicatorLook {
    Idle,
    Hover,
    Recording,
    Finishing,
    Warning,
    WarningHover,
    Dragging,
};

// The surface's input region. design.md "Indicator": Idle takes the 120 x 20
// strip, the expanded pill takes the pill, a warning on hover takes the
// widened pill, and Finishing takes nothing.
enum class InputRegion {
    Empty,
    Strip,
    Pill,
    WarnPill,
};

class IndicatorModel {
public:
    // Every timed input settles due timers at `now` first, so the order of
    // events is honoured even when advance() was not called in between.
    void on_state(UiState s, double now);
    void on_warn(std::optional<std::string> reason, bool blocking);
    void pointer_enter(double now);
    void pointer_leave(double now);
    // Ignored unless idle: dragging is idle-only (design.md "Dragging").
    void drag_begin();
    // Returns to Hover (design.md "Dragging" → Release).
    void drag_end();
    // Fires every timer due at or before now. A NaN or infinite now is ignored.
    void advance(double now);

    IndicatorLook look() const;
    bool clickable() const;
    InputRegion input_region() const;
    bool show_grip() const;
    std::optional<std::string> warn_text() const;
    bool warn_blocking() const;
    // The earliest time a timer fires, or nothing when no timer is pending,
    // so an idle, untouched indicator schedules no wakeups at all.
    std::optional<double> next_deadline() const;

private:
    // The daemon's states collapse to three for the indicator: the pill
    // shrinks back to idle at paste, and the popup explains the outcome.
    enum class Base { Idle, Recording, Finishing };

    Base base_ = Base::Idle;
    double now_ = 0.0;  // the latest time seen, for inputs that carry none

    bool inside_ = false;         // the pointer is over the input region
    bool hovered_ = false;        // the hover look is showing
    double enter_at_ = 0.0;       // when the pointer entered
    bool leave_pending_ = false;  // hovered, pointer gone, leave delay running
    double leave_at_ = 0.0;       // when the pointer left
    double hover_since_ = 0.0;    // when the hover look began
    bool grip_ = false;           // the grip delay has elapsed

    bool dragging_ = false;

    double finish_at_ = 0.0;      // when Finishing began
    bool finish_shown_ = false;   // the grace has elapsed

    std::optional<std::string> warn_;
    bool blocking_ = false;
};

}  // namespace flowd
