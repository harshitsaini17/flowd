#pragma once

#include <optional>
#include <string>
#include <variant>

#include "protocol.hpp"

// What the preview popup shows, for how long, and when it leaves. The widget
// only draws what this says. Time is passed in explicitly (seconds on the
// caller's monotonic clock), so every hold is unit-tested without GTK.
namespace flowd {

enum class PopupPhase {
    Hidden,
    Entering,
    Shown,
    Exiting,
};

// The Lucide icons the popup footer uses (design.md "Preview popup" → States).
enum class Icon {
    Check,
    Info,
    X,
    MicOff,
    CircleAlert,
    Timer,
    LoaderCircle,
    TriangleAlert,
};

// The footer icon's color role. Muted is text-2. design.md: error footers use
// danger for the icon only; the message text stays text.
enum class Tone {
    Primary,
    Info,
    Warn,
    Danger,
    Muted,
};

struct Status {
    Icon icon;
    Tone tone;
    std::string text;
};

// A one-line note in text-2 instead of the transcript ("Listening…").
struct Placeholder {
    std::string text;
};
// The three streaming zones (design.md "The three text zones").
struct Zones {
    std::string polished;
    std::string pending;
    std::string live;
};
// The transcript dimmed and struck through (design.md "States" → Cancelled).
struct Struck {
    std::string text;
};
struct NoContent {};

using Content = std::variant<NoContent, Placeholder, Zones, Struck>;

// design.md "Recording": the clipping hint shows for 2 s.
constexpr double kClipHintS = 2.0;
// design.md "Recording": the countdown starts at max_session_s - 10 s.
constexpr double kCountdownS = 10.0;

// Seconds as m:ss, rounded down: 0 -> "0:00", 59.9 -> "0:59", 300 -> "5:00".
// Negative or non-finite input reads as 0.
std::string format_clock(double s);

class PopupModel {
public:
    // Starts a session: Entering, "Listening…", the elapsed clock at zero.
    // Resets everything but meta and config, so a show during an exit
    // restarts cleanly.
    void on_show(double now);
    void on_render(const Render& r);
    // Terminal states start their hold at `now` and then exit on their own;
    // fade and hide never cut a hold short.
    void on_state(const StateMsg& s, double now);
    void on_meta(const Meta& m);
    void on_config(const UiConfig& c);
    // Without a terminal state, fade holds fade_ms and hide exits at once.
    void on_fade(double now);
    void on_hide(double now);
    // Fires every timer due at or before now. A non-finite now is ignored.
    void advance(double now);
    // The meter's clipping flag. A rising edge while recording shows the
    // hint for kClipHintS; the hint outlives the clipping itself.
    void set_clipping(bool clipping, double now);

    PopupPhase phase() const;
    Content content() const;
    std::optional<Status> status() const;
    // design.md "Preview popup": shown when [ui] footer is on, or whenever it
    // carries a status, so status never depends on the setting.
    bool footer_visible() const;
    // Seconds since on_show, frozen when recording ends.
    double elapsed_s(double now) const;
    // "0:09 left" from kCountdownS before the limit, while recording.
    std::optional<std::string> countdown(double now) const;
    // The earliest time something changes on its own (a phase change, a
    // hold ending, the hint expiring, the elapsed clock ticking over), or
    // nothing when the popup is hidden.
    std::optional<double> next_deadline() const;

private:
    // Recording until the first Finishing, TimeLimit or terminal state.
    bool live() const;
    void start_exit(double at);

    UiConfig config_{};
    Meta meta_{};

    PopupPhase phase_ = PopupPhase::Hidden;
    double now_ = 0.0;          // the latest time seen
    double shown_at_ = 0.0;     // on_show
    double phase_end_ = 0.0;    // when Entering or Exiting completes
    std::optional<double> exit_at_;  // when the hold ends and Exiting begins
    std::optional<double> stopped_at_;  // when recording ended, freezing the clock

    Content content_ = NoContent{};
    std::optional<Status> outcome_;     // the terminal state's status
    bool terminal_ = false;             // a terminal state arrived
    bool finishing_ = false;
    std::optional<Status> time_limit_;  // kept until the outcome replaces it
    bool clipping_ = false;
    std::optional<double> clip_until_;
};

}  // namespace flowd
