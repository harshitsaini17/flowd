#include "indicator_model.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

namespace flowd {

void IndicatorModel::advance(double now) {
    if (!std::isfinite(now)) return;
    now_ = now;

    if (inside_ && !hovered_ && now >= enter_at_ + kHoverEnterS) {
        hovered_ = true;
        // The grip counts from when the hover look was due, not from when
        // advance happened to run, so a late wakeup never delays it further.
        hover_since_ = enter_at_ + kHoverEnterS;
    }
    // A drag keeps the pill under the pointer until release, so the leave
    // delay waits for drag_end.
    if (leave_pending_ && !dragging_ && now >= leave_at_ + kHoverLeaveS) {
        hovered_ = false;
        leave_pending_ = false;
        grip_ = false;
    }
    if (hovered_ && !grip_ && now >= hover_since_ + kGripDelayS) grip_ = true;
    if (base_ == Base::Finishing && !finish_shown_ && now >= finish_at_ + kFinishGraceS) {
        finish_shown_ = true;
    }
}

void IndicatorModel::on_state(UiState s, double now) {
    advance(now);
    switch (s) {
    case UiState::Recording:
        base_ = Base::Recording;
        break;
    case UiState::Finishing:
    case UiState::TimeLimit:
        // At the limit the mic is already closing, so it reads as Finishing:
        // red must mean mic open only (design.md "Finishing"). Time limit is
        // followed by Finishing, which must not restart the grace.
        if (base_ != Base::Finishing) {
            finish_at_ = now_;
            finish_shown_ = false;
        }
        base_ = Base::Finishing;
        break;
    case UiState::Idle:
    case UiState::Done:
    case UiState::Fallback:
    case UiState::Error:
    case UiState::Cancelled:
    case UiState::NoSpeech:
        // design.md "Choreography": the pill shrinks at paste, not at fade-out.
        base_ = Base::Idle;
        break;
    }
    if (base_ != Base::Idle) dragging_ = false;
    // Advance again so a grace that is already over (a late message) applies.
    advance(now_);
}

void IndicatorModel::on_warn(std::optional<std::string> reason, bool blocking) {
    warn_ = std::move(reason);
    blocking_ = warn_.has_value() && blocking;
}

void IndicatorModel::pointer_enter(double now) {
    advance(now);
    if (inside_) return;
    inside_ = true;
    if (hovered_) {
        leave_pending_ = false;  // back before the leave delay ran out
    } else {
        enter_at_ = now_;
    }
}

void IndicatorModel::pointer_leave(double now) {
    advance(now);
    if (!inside_) return;
    inside_ = false;
    // Not yet hovered means a pass-through: the pending enter just lapses.
    if (hovered_) {
        leave_pending_ = true;
        leave_at_ = now_;
    }
}

void IndicatorModel::drag_begin() {
    if (base_ == Base::Idle) dragging_ = true;
}

void IndicatorModel::drag_end() {
    if (!dragging_) return;
    dragging_ = false;
    hovered_ = true;
    grip_ = true;  // a drag starts from the grip affordance, so it was showing
    if (!inside_) {
        // Released away from the pill: collapse after the usual leave delay.
        leave_pending_ = true;
        leave_at_ = now_;
    }
}

IndicatorLook IndicatorModel::look() const {
    if (dragging_) return IndicatorLook::Dragging;
    switch (base_) {
    case Base::Recording:
        return IndicatorLook::Recording;
    case Base::Finishing:
        return finish_shown_ ? IndicatorLook::Finishing : IndicatorLook::Recording;
    case Base::Idle:
        break;
    }
    if (warn_) return hovered_ ? IndicatorLook::WarningHover : IndicatorLook::Warning;
    return hovered_ ? IndicatorLook::Hover : IndicatorLook::Idle;
}

bool IndicatorModel::clickable() const {
    if (dragging_) return false;  // the release ends the drag, it is not a click
    switch (base_) {
    case Base::Recording:
        return true;
    case Base::Finishing:
        // design.md "Finishing": a late double-click must not start a new
        // session over an unfinished paste.
        return false;
    case Base::Idle:
        break;
    }
    // design.md "Warning": when the mic itself is the problem, not clickable.
    return !blocking_;
}

InputRegion IndicatorModel::input_region() const {
    // Wayland keeps delivering pointer events to the pressed surface, so the
    // region need not grow during a drag (design.md "Dragging").
    if (dragging_) return InputRegion::Pill;
    switch (base_) {
    case Base::Recording:
        return InputRegion::Pill;
    case Base::Finishing:
        // Empty at once, even during the visual grace.
        return InputRegion::Empty;
    case Base::Idle:
        break;
    }
    // A blocking warning keeps its region: hover must still reveal the reason.
    if (!hovered_) return InputRegion::Strip;
    return warn_ ? InputRegion::WarnPill : InputRegion::Pill;
}

bool IndicatorModel::show_grip() const {
    const IndicatorLook l = look();
    return grip_ && (l == IndicatorLook::Hover || l == IndicatorLook::WarningHover);
}

std::optional<std::string> IndicatorModel::warn_text() const {
    return warn_;
}

bool IndicatorModel::warn_blocking() const {
    return blocking_;
}

std::optional<double> IndicatorModel::next_deadline() const {
    std::optional<double> next;
    const auto consider = [&next](double t) { next = next ? std::min(*next, t) : t; };

    if (inside_ && !hovered_) consider(enter_at_ + kHoverEnterS);
    if (leave_pending_ && !dragging_) consider(leave_at_ + kHoverLeaveS);
    // The grip only shows on an idle hover, so it needs no wakeup otherwise.
    if (hovered_ && !grip_ && base_ == Base::Idle && !dragging_) {
        consider(hover_since_ + kGripDelayS);
    }
    if (base_ == Base::Finishing && !finish_shown_) consider(finish_at_ + kFinishGraceS);
    return next;
}

}  // namespace flowd
