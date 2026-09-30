#include "popup_model.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <string_view>

#include "motion.hpp"

namespace flowd {

namespace {

// Hold times, next to the strings they belong to. design.md "Preview popup"
// → States, except where noted.
constexpr int kFallbackExtraMs = 1000;  // fade_ms + 1000: the note needs reading time
constexpr int kNoSpeechMs = 1000;       // spec 9.1
constexpr int kCancelledMs = 800;
constexpr int kErrorMs = 3000;
constexpr int kPasteFailedMs = 4000;

constexpr double kMsPerS = 1000.0;
constexpr int kSecondsPerMinute = 60;
// A clock this long is already nonsense; the cap keeps the integer
// conversion defined for any finite input.
constexpr double kClockCeilingS = 1e9;

// How long a terminal state holds before the exit starts.
struct Hold {
    int ms;          // fixed part
    bool plus_fade;  // add the configured fade_ms
};

// One terminal outcome. An empty reason is the default for that state, used
// when the daemon's reason is empty or unknown.
struct Outcome {
    UiState state;
    std::string_view reason;
    std::optional<Icon> icon;  // none: the state has no footer status
    Tone tone;
    std::string_view text;     // footer status, or the placeholder for NoSpeech
    Hold hold;
};

// Every user-visible string the popup shows, with design.md's wording verbatim.
constexpr std::string_view kListening = "Listening…";
constexpr std::string_view kFinishing = "Finishing";
constexpr std::string_view kTooLoud = "Too loud, move back a little";
constexpr std::string_view kTimeLimitPrefix = "Time limit reached (";
constexpr std::string_view kTimeLimitSuffix = ")";
constexpr std::string_view kCountdownSuffix = " left";
constexpr std::string_view kPastedIntoPrefix = "Pasted into ";
// design.md "Preview popup" → Anatomy: "Super D to stop".
constexpr std::string_view kStopHintSuffix = " to stop";

constexpr std::array kOutcomes = {
    // design.md "States" 4: "Pasted into {app}"; plain "Pasted" when the app
    // is unknown (design.md "Choreography").
    Outcome{UiState::Done, "", Icon::Check, Tone::Primary, "Pasted", {0, true}},
    // design.md "States" 5.
    Outcome{UiState::Fallback, "offline", Icon::Info, Tone::Info,
            "Pasted as heard · cleanup offline", {kFallbackExtraMs, true}},
    Outcome{UiState::Fallback, "timeout", Icon::Info, Tone::Info,
            "Pasted as heard · cleanup timed out", {kFallbackExtraMs, true}},
    Outcome{UiState::Fallback, "rejected", Icon::Info, Tone::Info,
            "Pasted as heard · cleanup changed too much", {kFallbackExtraMs, true}},
    Outcome{UiState::Fallback, "failed", Icon::Info, Tone::Info,
            "Pasted as heard · cleanup failed", {kFallbackExtraMs, true}},
    // The text was still pasted, so an unknown reason is no error.
    Outcome{UiState::Fallback, "", Icon::Info, Tone::Info, "Pasted as heard",
            {kFallbackExtraMs, true}},
    // design.md "States" 6: a placeholder, no footer status.
    Outcome{UiState::NoSpeech, "", std::nullopt, Tone::Muted, "No speech detected",
            {kNoSpeechMs, false}},
    // design.md "States" 7.
    Outcome{UiState::Cancelled, "", Icon::X, Tone::Muted, "Cancelled, nothing pasted",
            {kCancelledMs, false}},
    // design.md "States" 8 and 9.
    Outcome{UiState::Error, "mic_lost", Icon::MicOff, Tone::Danger,
            "Mic disconnected · pasted what was heard", {kErrorMs, false}},
    Outcome{UiState::Error, "mic_lost_empty", Icon::MicOff, Tone::Danger,
            "Mic disconnected · nothing was pasted", {kErrorMs, false}},
    Outcome{UiState::Error, "paste_failed", Icon::CircleAlert, Tone::Danger,
            "Couldn't paste. Run flowctl last to copy it", {kPasteFailedMs, false}},
    // design.md "Warning" words the mic problem as "Microphone unavailable".
    Outcome{UiState::Error, "mic_unavailable", Icon::MicOff, Tone::Danger,
            "Microphone unavailable", {kErrorMs, false}},
    Outcome{UiState::Error, "dictation_failed", Icon::CircleAlert, Tone::Danger,
            "Dictation failed · see flowctl status", {kErrorMs, false}},
    Outcome{UiState::Error, "", Icon::CircleAlert, Tone::Danger,
            "Something went wrong · see flowctl status", {kErrorMs, false}},
};

const Outcome* find_outcome(UiState state, std::string_view reason) {
    const Outcome* fallback = nullptr;
    for (const Outcome& o : kOutcomes) {
        if (o.state != state) continue;
        if (o.reason == reason) return &o;
        if (o.reason.empty()) fallback = &o;
    }
    return fallback;
}

// Zones flow inline in one paragraph separated by a normal space (design.md
// "The three text zones"), unless a run already carries its own.
void append_run(std::string& out, const std::string& run) {
    if (run.empty()) return;
    const auto space = [](char c) { return c == ' ' || c == '\n' || c == '\t'; };
    if (!out.empty() && !space(out.back()) && !space(run.front())) out += ' ';
    out += run;
}

}  // namespace

std::string format_clock(double s) {
    if (!std::isfinite(s) || s < 0.0) s = 0.0;
    const auto total = static_cast<long long>(std::floor(std::min(s, kClockCeilingS)));
    const long long minutes = total / kSecondsPerMinute;
    const long long seconds = total % kSecondsPerMinute;
    std::string out = std::to_string(minutes) + ':';
    if (seconds < 10) out += '0';
    out += std::to_string(seconds);
    return out;
}

void PopupModel::on_show(double now) {
    if (!std::isfinite(now)) return;
    now_ = now;
    phase_ = PopupPhase::Entering;
    // design.md "Motion" → Choreography: the popup enters in dur-base.
    phase_end_ = now + kBase / kMsPerS;
    shown_at_ = now;
    exit_at_.reset();
    stopped_at_.reset();
    content_ = Placeholder{std::string(kListening), true};
    outcome_.reset();
    terminal_ = false;
    finishing_ = false;
    time_limit_.reset();
    // A new session needs a fresh rising edge before the hint shows again.
    clipping_ = false;
    clip_until_.reset();
}

void PopupModel::on_render(const Render& r) {
    if (phase_ == PopupPhase::Hidden) return;
    // Once cancelled or with nothing heard, the content is settled. Any other
    // outcome still takes a late render: it is the final text that was pasted.
    if (std::holds_alternative<Struck>(content_)) return;
    if (const auto* p = std::get_if<Placeholder>(&content_);
        p != nullptr && p->text != kListening)
        return;
    if (r.polished.empty() && r.pending.empty() && r.live.empty()) {
        // No words yet: keep listening rather than draw an empty card.
        if (live()) content_ = Placeholder{std::string(kListening), true};
        return;
    }
    content_ = Zones{r.polished, r.pending, r.live};
}

void PopupModel::on_state(const StateMsg& s, double now) {
    advance(now);
    // Nothing to show, or the session is already leaving.
    if (phase_ == PopupPhase::Hidden || phase_ == PopupPhase::Exiting || terminal_) return;

    switch (s.state) {
    case UiState::Idle:
    case UiState::Recording:
        return;
    case UiState::Finishing:
        finishing_ = true;
        if (!stopped_at_) stopped_at_ = now_;
        return;
    case UiState::TimeLimit:
        // design.md "States" 10: kept until the outcome replaces it.
        time_limit_ = Status{Icon::Timer, Tone::Warn,
                             std::string(kTimeLimitPrefix) + format_clock(config_.max_session_s) +
                                 std::string(kTimeLimitSuffix)};
        if (!stopped_at_) stopped_at_ = now_;
        return;
    case UiState::Done:
    case UiState::Fallback:
    case UiState::Error:
    case UiState::Cancelled:
    case UiState::NoSpeech:
        break;
    }

    const Outcome* o = find_outcome(s.state, s.reason);
    if (o == nullptr) return;  // every terminal state has a default row
    terminal_ = true;
    if (!stopped_at_) stopped_at_ = now_;

    if (o->icon) {
        std::string text(o->text);
        if (s.state == UiState::Done && !meta_.app.empty()) {
            text = std::string(kPastedIntoPrefix) + meta_.app;
        }
        outcome_ = Status{*o->icon, o->tone, std::move(text)};
    }
    if (s.state == UiState::NoSpeech) {
        content_ = Placeholder{std::string(o->text)};
    } else if (s.state == UiState::Cancelled) {
        // design.md "States" 7: the text dims with a strike-through.
        if (const auto* z = std::get_if<Zones>(&content_)) {
            std::string all;
            append_run(all, z->polished);
            append_run(all, z->pending);
            append_run(all, z->live);
            content_ = Struck{std::move(all)};
        } else {
            content_ = NoContent{};
        }
    }

    const int hold_ms = o->hold.ms + (o->hold.plus_fade ? std::max(config_.fade_ms, 0) : 0);
    exit_at_ = now_ + hold_ms / kMsPerS;
}

void PopupModel::on_meta(const Meta& m) {
    meta_ = m;
}

void PopupModel::on_config(const UiConfig& c) {
    config_ = c;
}

void PopupModel::on_fade(double now) {
    advance(now);
    if (phase_ == PopupPhase::Hidden || phase_ == PopupPhase::Exiting) return;
    // A terminal state already set its own hold, which a fade never shortens.
    if (terminal_ || exit_at_) return;
    exit_at_ = now_ + std::max(config_.fade_ms, 0) / kMsPerS;
    advance(now_);
}

void PopupModel::on_hide(double now) {
    advance(now);
    if (phase_ == PopupPhase::Hidden || phase_ == PopupPhase::Exiting) return;
    // design.md "States": a hold outlives the hide ("Cancelled ... holds 800 ms").
    if (terminal_) return;
    start_exit(now_);
}

void PopupModel::on_warn(std::optional<std::string> reason) {
    // An empty reason says nothing, so it clears like null does.
    if (!reason || reason->empty()) {
        warning_.reset();
        return;
    }
    warning_ = std::move(*reason);
}

void PopupModel::advance(double now) {
    if (!std::isfinite(now)) return;
    now_ = std::max(now_, now);

    if (phase_ == PopupPhase::Entering && now_ >= phase_end_) phase_ = PopupPhase::Shown;
    // Exit from the moment the hold ended, not from when advance ran, so a
    // late wakeup never stretches the fade.
    if (exit_at_ && now_ >= *exit_at_ &&
        (phase_ == PopupPhase::Entering || phase_ == PopupPhase::Shown)) {
        start_exit(*exit_at_);
    }
    if (phase_ == PopupPhase::Exiting && now_ >= phase_end_) phase_ = PopupPhase::Hidden;
    if (clip_until_ && now_ >= *clip_until_) clip_until_.reset();
}

void PopupModel::set_clipping(bool clipping, double now) {
    advance(now);
    // A rising edge only: the hint shows once per burst, with no flashing.
    if (clipping && !clipping_ && live() && phase_ != PopupPhase::Hidden) {
        clip_until_ = now_ + kClipHintS;
    }
    clipping_ = clipping;
}

void PopupModel::start_exit(double at) {
    phase_ = PopupPhase::Exiting;
    // design.md "Motion": exits run dur-fade-out.
    phase_end_ = at + kFadeOut / kMsPerS;
    exit_at_.reset();
    clip_until_.reset();
}

bool PopupModel::live() const {
    return !terminal_ && !finishing_ && !time_limit_;
}

PopupPhase PopupModel::phase() const {
    return phase_;
}

Content PopupModel::content() const {
    if (phase_ == PopupPhase::Hidden) return NoContent{};
    if (const auto* z = std::get_if<Zones>(&content_);
        z != nullptr && !live() && !z->live.empty()) {
        // design.md "States" 3: once recording ends the live run restyles to
        // pending, since no partial will replace it any more.
        Zones frozen{z->polished, z->pending, ""};
        append_run(frozen.pending, z->live);
        return frozen;
    }
    return content_;
}

std::optional<Status> PopupModel::status() const {
    if (phase_ == PopupPhase::Hidden) return std::nullopt;
    if (terminal_) return outcome_;
    if (time_limit_) return time_limit_;
    if (finishing_) return Status{Icon::LoaderCircle, Tone::Muted, std::string(kFinishing)};
    // design.md does not name an icon for the clipping hint; it is a warn-level
    // nudge, so it reuses the warning's triangle.
    if (clip_until_) return Status{Icon::TriangleAlert, Tone::Warn, std::string(kTooLoud)};
    // The warning is lasting, so a passing clipping hint outranks it and it
    // returns once the hint expires. Only while recording: afterwards the
    // outcome says what happened (design.md "Warning").
    if (warning_ && live()) return Status{Icon::TriangleAlert, Tone::Warn, *warning_};
    return std::nullopt;
}

bool PopupModel::footer_visible() const {
    if (phase_ == PopupPhase::Hidden) return false;
    return config_.footer || status().has_value();
}

double PopupModel::elapsed_s(double now) const {
    if (phase_ == PopupPhase::Hidden || !std::isfinite(now)) return 0.0;
    const double end = stopped_at_ ? *stopped_at_ : now;
    return std::max(end - shown_at_, 0.0);
}

std::optional<std::string> PopupModel::countdown(double now) const {
    if (phase_ == PopupPhase::Hidden || !live() || !std::isfinite(now)) return std::nullopt;
    const double remaining = config_.max_session_s - elapsed_s(now);
    if (remaining > kCountdownS) return std::nullopt;
    return format_clock(remaining) + std::string(kCountdownSuffix);
}

FooterInput PopupModel::footer(double now) const {
    FooterInput in;
    if (phase_ == PopupPhase::Hidden) return in;
    const std::optional<Status> st = status();
    if (st) in.status = st->text;
    // Once recording ends, a status stands alone: design.md "States" 3-10
    // list only the status (Finishing, Time limit, every outcome), where 1
    // and 2 name "mode · app". Without one, the row still names them.
    if (!live() && st) return in;
    in.mode = meta_.mode;
    in.app = meta_.app;
    if (!live()) return in;
    // design.md "Recording": the countdown replaces the elapsed time.
    const auto left = countdown(now);
    in.elapsed = left ? *left : format_clock(elapsed_s(now));
    // The label typed in Settings wins; the daemon's meta hotkey is the
    // fallback. Neither means no hint, never a guessed binding.
    const std::string& key = config_.hotkey_label.empty() ? meta_.hotkey : config_.hotkey_label;
    if (!key.empty()) in.hint = key + std::string(kStopHintSuffix);
    return in;
}

std::optional<double> PopupModel::next_deadline() const {
    if (phase_ == PopupPhase::Hidden) return std::nullopt;
    std::optional<double> next;
    const auto consider = [&next](double t) { next = next ? std::min(*next, t) : t; };

    if (phase_ == PopupPhase::Entering || phase_ == PopupPhase::Exiting) consider(phase_end_);
    if (exit_at_) consider(*exit_at_);
    if (clip_until_) consider(*clip_until_);
    if (live()) {
        // The elapsed clock and the countdown both turn over on whole seconds
        // since the show.
        const double elapsed = std::max(now_ - shown_at_, 0.0);
        consider(shown_at_ + std::floor(elapsed) + 1.0);
    }
    return next;
}

}  // namespace flowd
