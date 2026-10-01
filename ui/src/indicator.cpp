#include "indicator.hpp"

#include <gdkmm/display.h>
#include <gdkmm/surface.h>
#include <glibmm/main.h>
#include <gtk4-layer-shell.h>
#include <gtkmm/snapshot.h>

#include <algorithm>
#include <cmath>
#include <numbers>
#include <utility>

#include "draw.hpp"
#include "indicator_geometry.hpp"
#include "placement.hpp"
#include "surface.hpp"

namespace flowd {

namespace {

constexpr const char* kNamespace = "flowd-indicator";

// design.md "Indicator" → Idle / Hover / Warning: overall opacity per look.
constexpr double kIdleOpacity = 0.35;
constexpr double kIdleWarnOpacity = 0.55;
constexpr double kExpandedOpacity = 0.96;
// design.md "Elevation & Depth" → the idle line: a Charcoal core in both
// themes, a 1 px 55%-white ring, and 0 1px 3px black-35% below it.
constexpr Rgba kIdleFill = hex("#171717");
constexpr Rgba kIdleRing{1.0, 1.0, 1.0, 0.55};
constexpr Rgba kIdleShadow{0.0, 0.0, 0.0, 0.35};
constexpr float kIdleRingPx = 1.0f;
constexpr float kIdleShadowDy = 1.0f;
constexpr float kIdleShadowBlur = 3.0f;
// design.md "Indicator" → Warning: a 6 px dot, centred at +18 px from the
// line's centre and 5 px above its top, with a 1 px dark ring. It is amber in
// both themes: the dark theme's `warn`, since it sits on the dark idle core
// (flowd/web/assets/overlay.css .warn-dot).
constexpr float kWarnDotD = 6.0f;
constexpr float kWarnDotDx = 18.0f;
constexpr float kWarnDotDy = -5.0f;
constexpr Rgba kWarnDotFill = hex("#f2b34c");
constexpr Rgba kWarnDotRing{0.0, 0.0, 0.0, 0.6};
// design.md "Indicator" → Hover: content fades in 60 ms after the size starts.
constexpr double kContentDelayS = 0.06;
// design.md "Indicator" → Hover: the 16 px mic, the 12 px grip at 70% in
// text-2, 12 px of right padding (overlay.css .pill).
constexpr float kMicSize = 16.0f;
constexpr float kGripSize = 12.0f;
constexpr double kGripAlpha = 0.7;
constexpr float kPadRight = 12.0f;
// design.md "Indicator" → Recording: a 24 px record-fill disc holding a white
// 8 x 8 stop square (2 px corners, as overlay.css draws it: rounded.xs would
// turn an 8 px square into a circle).
constexpr float kDiscD = 24.0f;
constexpr float kStopSide = 8.0f;
constexpr float kStopRadius = 2.0f;
constexpr Rgba kStopFill{1.0, 1.0, 1.0, 1.0};
// design.md "Indicator" → Recording: a 1.5 px inside ring in `record` that
// breathes 1.0 <-> 0.72 over 1.5 s; it fades in over 80 ms after 40 ms so the
// size lands first (design.md "Choreography").
constexpr float kRingPx = 1.5f;
constexpr double kBreathHigh = 1.0;
constexpr double kBreathLow = 0.72;
constexpr double kBreathHalfPeriodS = 1.5;
constexpr double kRingDelayS = 0.04;
// design.md "Indicator" → Recording: bars 3 px wide, 3 px apart, radius
// rounded.xs (clamped to the bar), 4 px in from the right padding.
constexpr float kBarW = 3.0f;
constexpr float kBarGap = 3.0f;
constexpr float kBarRadius = 4.0f;
constexpr float kMeterRightInset = 4.0f;
// design.md "Reduced motion": a single bar whose fill width tracks the
// level, updated at 10 Hz. It never drops below kBarMin, like the bars.
constexpr float kSingleBarMaxW = 48.0f;
constexpr double kReducedMeterPeriodS = 0.1;
// design.md "Indicator" → Finishing: loader-circle at 800 ms per turn; three
// 4 px dots pulsing 0.3 <-> 1, staggered 120 ms, static at 0.6 when reduced.
// overlay.css runs each pulse 720 ms each way.
constexpr double kSpinPeriodS = 0.8;
constexpr float kDotD = 4.0f;
constexpr float kDotGap = 4.0f;
constexpr float kDotsRightInset = 10.0f;
constexpr double kDotLow = 0.3;
constexpr double kDotHigh = 1.0;
constexpr double kDotStatic = 0.6;
constexpr double kDotStaggerS = 0.12;
constexpr double kDotHalfPeriodS = 0.72;
constexpr int kDotCount = 3;
// design.md "Indicator" → Dragging: scale 1.04 in dur-fast; a 1 x 12 tick in
// text-2 at the snap point, drawn in the shadow room above the pill.
constexpr double kDragScale = 1.04;
constexpr float kTickW = 1.0f;
constexpr float kTickH = 12.0f;
// design.md "Indicator on-screen rules": outputs switch with a 160 ms
// crossfade, half out and half in.
constexpr int kOutputFadeHalfMs = 80;

constexpr double kFull = 1.0;
constexpr double kNone = 0.0;
constexpr double kUsPerS = 1e6;
constexpr double kMsPerS = 1000.0;

bool expanded(IndicatorLook l) {
    return l != IndicatorLook::Idle && l != IndicatorLook::Warning;
}

graphene_rect_t rect(double x, double y, double w, double h) {
    return GRAPHENE_RECT_INIT(static_cast<float>(x), static_cast<float>(y),
                              static_cast<float>(w), static_cast<float>(h));
}

GskRoundedRect rounded(graphene_rect_t r, float radius) {
    GskRoundedRect rr;
    gsk_rounded_rect_init_from_rect(&rr, &r,
                                    std::min(radius, std::min(r.size.width, r.size.height) / 2));
    return rr;
}

void inside_ring(GtkSnapshot* s, graphene_rect_t r, float width, Rgba c) {
    const GskRoundedRect rr = rounded(r, r.size.height / 2);
    const std::array<float, 4> w{width, width, width, width};
    const GdkRGBA g = to_gdk(c);
    const std::array<GdkRGBA, 4> cs{g, g, g, g};
    gtk_snapshot_append_border(s, &rr, w.data(), cs.data());
}

void circle(GtkSnapshot* s, float cx, float cy, float d, Rgba c) {
    fill_rounded(s, rect(cx - d / 2, cy - d / 2, d, d), d / 2, c);
}

// A cosine between lo and hi with the given half period, lo at t = 0.
double pulse(double t_s, double half_period_s, double lo, double hi) {
    const double k = 0.5 - 0.5 * std::cos(std::numbers::pi * t_s / half_period_s);
    return lo + (hi - lo) * k;
}

}  // namespace

// ---- canvas -----------------------------------------------------------------

IndicatorCanvas::IndicatorCanvas(Indicator& owner) : owner_(owner) {
    set_focusable(false);
    set_can_focus(false);
}

Gtk::SizeRequestMode IndicatorCanvas::get_request_mode_vfunc() const {
    return Gtk::SizeRequestMode::CONSTANT_SIZE;
}

void IndicatorCanvas::measure_vfunc(Gtk::Orientation orientation, int, int& minimum, int& natural,
                                    int& minimum_baseline, int& natural_baseline) const {
    // Fixed: the pill animates and moves inside the surface, which spans the
    // output, so the compositor never resizes or moves it (design.md
    // "Motion" → GTK mapping, "Indicator placement").
    const int w = indicator_surface_w(owner_.wide_, owner_.spanned_width());
    minimum = natural = orientation == Gtk::Orientation::HORIZONTAL ? w : kSurfaceH;
    minimum_baseline = natural_baseline = -1;
}

void IndicatorCanvas::size_allocate_vfunc(int width, int height, int baseline) {
    Gtk::Widget::size_allocate_vfunc(width, height, baseline);
    owner_.on_canvas_allocated();
}

void IndicatorCanvas::snapshot_vfunc(const Glib::RefPtr<Gtk::Snapshot>& snapshot) {
    owner_.draw(snapshot->gobj());
}

// ---- window -----------------------------------------------------------------

Indicator::Indicator(Backend backend, PositionStore& store, Tokens tokens, bool reduced_motion,
                     ClickFn on_click, MovedFn on_moved)
    : backend_(backend),
      store_(store),
      tokens_(tokens),
      reduced_(reduced_motion),
      on_click_(std::move(on_click)),
      on_moved_(std::move(on_moved)),
      canvas_(*this) {
    // A transparent window, so only the pill is drawn; the rest of the
    // surface is shadow room and click-through.
    install_window_css();
    set_decorated(false);
    set_resizable(false);
    set_focusable(false);
    set_can_focus(false);
    set_title(kNamespace);
    set_child(canvas_);

    // Start at rest: the idle line, fully faded in.
    tl_[kAnimW].jump(kIdleLineW);
    tl_[kAnimH].jump(kIdleLineH);
    tl_[kAnimOpacity].jump(kIdleOpacity);
    tl_[kAnimScale].jump(kFull);
    tl_[kAnimFade].jump(kFull);
    targets_ = {kIdleLineW, kIdleLineH, kIdleOpacity, kNone, kNone, kNone,
                kNone,      kFull,      kNone,        kFull};

    motion_ = Gtk::EventControllerMotion::create();
    motion_->signal_enter().connect([this](double x, double y) {
        model_.pointer_enter(now_s());
        pointer_.emplace(x, y);
        refresh();
    });
    motion_->signal_leave().connect([this] {
        model_.pointer_leave(now_s());
        pointer_.reset();
        refresh();
    });
    motion_->signal_motion().connect([this](double x, double y) {
        pointer_.emplace(x, y);
        update_cursor(x, y);
    });
    canvas_.add_controller(motion_);

    drag_ = Gtk::GestureDrag::create();
    drag_->set_button(GDK_BUTTON_PRIMARY);
    drag_->signal_drag_begin().connect(sigc::mem_fun(*this, &Indicator::on_drag_begin));
    drag_->signal_drag_update().connect(sigc::mem_fun(*this, &Indicator::on_drag_update));
    drag_->signal_drag_end().connect(sigc::mem_fun(*this, &Indicator::on_drag_end));
    drag_->signal_cancel().connect([this](Gdk::EventSequence*) {
        // The compositor took the grab: no click, and the pill goes back to
        // where the press found it.
        cancelled_ = true;
        if (dragging_) center_x_ = press_center_;
        end_drag();
    });
    canvas_.add_controller(drag_);

    switch (backend_) {
    case Backend::Wayland:
        // The surface's bottom edge sits on the output edge; the pill's
        // 6 px margin is inside it (design.md "Indicator placement").
        make_overlay_surface(*this, kNamespace, Edges::Left | Edges::Bottom, {}, why_not_);
        break;
    case Backend::X11:
        break;  // set up in start(): make_x11_overlay realizes the window
    case Backend::Unsupported:
        why_not_ = "no display backend can keep the indicator from taking focus";
        break;
    }
}

Indicator::~Indicator() {
    // First, before any member goes: unmapping synthesizes crossing events,
    // and a controller or timer reaching this half-destroyed window would
    // touch freed members or re-arm a timer that captures this.
    canvas_.remove_controller(motion_);
    canvas_.remove_controller(drag_);
    deadline_.disconnect();
    monitor_switch_.disconnect();
    monitor_gone_.disconnect();
    monitor_geometry_.disconnect();
    reduced_meter_.disconnect();
    if (tick_id_) canvas_.remove_tick_callback(tick_id_);
    tick_id_ = 0;
    tracker_.reset();
    for (PangoLayout* l : {dictate_layout_, move_layout_, warn_layout_})
        if (l) g_object_unref(l);
}

double Indicator::now_s() { return static_cast<double>(g_get_monotonic_time()) / kUsPerS; }

bool Indicator::start() {
    if (why_not_) return false;
    if (backend_ == Backend::X11 && !make_x11_overlay(*this, why_not_)) return false;

    tracker_ = std::make_unique<OutputTracker>(OutputTracker::Callbacks{
        [this](const std::string& name) {
            if (auto m = find_monitor(get_display(), name)) set_output(m);
        },
        [this](bool fs) { set_fullscreen_hidden(fs); },
    });
    // May report the focused output and fullscreen state at once.
    tracker_->start();
    if (!monitor_) use_monitor(first_monitor(get_display()));

    started_ = true;
    update_visibility();
    return !why_not_;
}

void Indicator::show_now() {
    if (backend_ == Backend::X11) {
        // Placed before mapping, so it never flashes at the origin.
        apply_position();
        if (!show_x11_overlay(*this)) {
            why_not_ = "the X11 indicator window failed its focus checks";
            return;
        }
    } else {
        // Never present(): the surface must not ask for focus.
        set_visible(true);
    }
    apply_position();
    apply_input_region();
    ensure_tick();
}

void Indicator::set_fullscreen_hidden(bool hidden) {
    fullscreen_hidden_ = hidden;
    update_visibility();
}

void Indicator::update_visibility() {
    if (!started_) return;
    if (fullscreen_hidden_ || config_hidden_) {
        if (!get_visible()) return;
        set_visible(false);
        // A hidden surface gets no leave event, so the hover would stick.
        pointer_.reset();
        model_.pointer_leave(now_s());
        refresh();
    } else if (!get_visible()) {
        show_now();
    }
}

// ---- inputs -----------------------------------------------------------------

void Indicator::on_state(UiState s) {
    if (s == UiState::Recording && last_state_ != UiState::Recording) {
        meter_.reset();
        reduced_fill_ = meter_.single_fill();
        if (clipping_) {
            clipping_ = false;
            if (on_clipping_) on_clipping_(false);
        }
    }
    last_state_ = s;
    model_.on_state(s, now_s());
    refresh();
}

void Indicator::on_level(Level l) {
    meter_.push(l.rms_db, l.peak_db);
    ensure_tick();
}

void Indicator::on_warn(Warn w) {
    model_.on_warn(std::move(w.reason), w.blocking);
    rebuild_warn_layout();
    refresh();
}

void Indicator::on_config(UiConfig c) {
    // design.md "Indicator" → Idle: hidden entirely when [ui] indicator = false.
    config_hidden_ = !c.indicator;
    update_visibility();
}

void Indicator::set_tokens(Tokens t) {
    tokens_ = t;
    canvas_.queue_draw();
}

void Indicator::set_reduced_motion(bool reduced) {
    reduced_ = reduced;
    refresh();
}

void Indicator::update_reduced_meter() {
    const bool needed = reduced_ && look_ == IndicatorLook::Recording;
    if (!needed) {
        reduced_meter_.disconnect();
        return;
    }
    if (reduced_meter_.connected()) return;
    last_meter_draw_s_ = now_s();
    reduced_meter_ = Glib::signal_timeout().connect(
        sigc::mem_fun(*this, &Indicator::on_reduced_meter),
        static_cast<unsigned>(kReducedMeterPeriodS * kMsPerS));
}

bool Indicator::on_reduced_meter() {
    // design.md "Reduced motion": the single bar updates at 10 Hz, so a timer
    // replaces the per-frame tick while recording.
    const double now = now_s();
    meter_.tick(now - last_meter_draw_s_);
    last_meter_draw_s_ = now;
    if (meter_.clipping() != clipping_) {
        clipping_ = meter_.clipping();
        if (on_clipping_) on_clipping_(clipping_);
    }
    reduced_fill_ = meter_.single_fill();
    canvas_.queue_draw();
    return true;
}

void Indicator::set_output(const Glib::RefPtr<Gdk::Monitor>& monitor) {
    if (!monitor || monitor == monitor_ || monitor == pending_monitor_) return;
    if (!started_ || !get_visible()) {
        use_monitor(monitor);
        return;
    }
    // Fade out, switch while invisible, fade back in; never a slide across
    // outputs (design.md "Indicator on-screen rules").
    pending_monitor_ = monitor;
    const int half = motion_ms(kOutputFadeHalfMs, reduced_) / (reduced_ ? 2 : 1);
    tl_[kAnimFade].to(kNone, half, kStandard, now_s());
    ensure_tick();
    monitor_switch_.disconnect();
    monitor_switch_ = Glib::signal_timeout().connect(
        [this, half] {
            if (pending_monitor_) use_monitor(std::exchange(pending_monitor_, {}));
            tl_[kAnimFade].to(kFull, half, kStandard, now_s());
            ensure_tick();
            return false;
        },
        half);
}

void Indicator::use_monitor(const Glib::RefPtr<Gdk::Monitor>& monitor) {
    if (!monitor) return;
    monitor_ = monitor;
    monitor_gone_.disconnect();
    // An unplugged output: fall back to whatever is left.
    monitor_gone_ = monitor->signal_invalidate().connect([this] {
        auto m = first_monitor(get_display());
        if (m == monitor_) m = {};
        monitor_ = {};
        if (m) use_monitor(m);
    });
    if (backend_ == Backend::Wayland && gtk_layer_is_layer_window(gobj()))
        gtk_layer_set_monitor(gobj(), monitor->gobj());
    // A resolution or scale change on the same output: the surface spans
    // it, so it re-measures, and the saved fraction maps to the new width.
    monitor_geometry_.disconnect();
    monitor_geometry_ = monitor->property_geometry().signal_changed().connect(
        [this] { place_on_monitor(); });
    place_on_monitor();
}

void Indicator::place_on_monitor() {
    center_x_ = from_fraction(store_.get(output_name()), output_width());
    canvas_.queue_resize();
    apply_position();
    apply_input_region();
}

int Indicator::output_width() const {
    if (!monitor_) return 0;
    Gdk::Rectangle g;
    monitor_->get_geometry(g);
    return g.get_width();
}

int Indicator::spanned_width() const {
    // Without a compositing manager X11 paints a window's transparent area
    // opaque, so there the surface stays pill-sized and moves instead.
    if (backend_ == Backend::X11 && !get_display()->is_composited()) return 0;
    // On X11 the window is placed inside the workarea, so it spans that.
    return backend_ == Backend::X11 && monitor_ ? x11_workarea_width(monitor_) : output_width();
}

std::string Indicator::output_name() const {
    if (!monitor_) return {};
    return monitor_->get_connector();
}

int Indicator::surface_left() const {
    // The allocated width, not the requested one: a resize (a new output, or
    // the wide warning before the output is known) lands with a later frame,
    // and the surface must stay where its current buffer's pill is drawn.
    const int w = canvas_.get_width() > 0 ? canvas_.get_width()
                                          : indicator_surface_w(wide_, spanned_width());
    return full_width_surface_left(center_x_, w, spanned_width());
}

void Indicator::on_canvas_allocated() {
    // The margin and the buffer at the new width go out in the same commit.
    apply_position();
    apply_input_region();
}

double Indicator::pill_cx_in_surface(double pill_w) const {
    return pill_center_in_surface(center_x_, pill_w, placed_left_, output_width());
}

// ---- gestures ---------------------------------------------------------------

void Indicator::on_drag_begin(double x, double y) {
    pressed_ = true;
    moved_ = dragging_ = cancelled_ = false;
    press_x_ = x;
    press_y_ = y;
    press_center_ = center_x_;
    snap_point_.reset();
}

void Indicator::on_drag_update(double dx, double dy) {
    if (!pressed_) return;
    // The gesture reports offsets against the press. The surface never
    // moves, so they are the pointer's movement on the output.
    const double center = drag_center(press_center_, dx);
    if (!moved_ && is_drag(dx, dy)) {
        moved_ = true;
        model_.drag_begin();
        dragging_ = model_.look() == IndicatorLook::Dragging;
        refresh();
    }
    if (!dragging_) return;
    const Snap snap = snap_center(center, output_width());
    center_x_ = snap.x;
    snap_point_ = snap.point;
    // Only the drawing and the input region move; the surface does not.
    apply_input_region();
    canvas_.queue_draw();
}

void Indicator::on_drag_end(double dx, double dy) {
    if (!pressed_) return;
    const bool was_click = !moved_ && !cancelled_;
    if (dragging_) {
        const std::string out = output_name();
        const double f = to_fraction(center_x_, output_width());
        store_.set(out, f);
        if (on_moved_) on_moved_(f, out);
        end_drag();
        return;
    }
    end_drag();
    if (!was_click || !model_.clickable()) return;
    // design.md "Indicator" → Hover: press and release within the pill.
    const double rx = press_x_ + dx, ry = press_y_ + dy;
    const double w = tl_[kAnimW].value(now_s());
    const auto hit = input_rect(model_.input_region(), w, pill_cx_in_surface(w));
    if (!hit) return;
    const double x = rx - kSurfacePad, y = ry - kSurfacePad;
    if (x < hit->x || x > hit->x + hit->w || y < hit->y || y > hit->y + hit->h) return;
    if (on_click_) on_click_();
}

void Indicator::end_drag() {
    pressed_ = false;
    if (dragging_) model_.drag_end();
    dragging_ = false;
    snap_point_.reset();
    refresh();
}

void Indicator::update_cursor(double x, double y) {
    const char* name = "default";
    const IndicatorLook l = model_.look();
    if (l == IndicatorLook::Dragging) {
        name = "grabbing";
    } else if (expanded(l) && model_.clickable()) {
        name = "pointer";
        // design.md "Indicator" → Dragging: the cursor over the grip is grab.
        if (model_.show_grip() && l == IndicatorLook::Hover) {
            const double right = pill_cx_in_surface(kPillW) + kPillW / 2.0;
            if (x >= right - kPadRight - kGripSize - kContentGap && x <= right &&
                y >= kSurfacePad)
                name = "grab";
        }
    }
    canvas_.set_cursor(name);
}

// ---- state → animation targets ----------------------------------------------

void Indicator::refresh() {
    const double now = now_s();
    model_.advance(now);
    const IndicatorLook l = model_.look();
    if (expanded(l)) content_look_ = l;
    look_ = l;
    update_targets(now);
    narrow_if_done(now);
    apply_input_region();
    update_reduced_meter();
    if (pointer_) update_cursor(pointer_->first, pointer_->second);
    schedule_deadline();
    ensure_tick();
    canvas_.queue_draw();
}

void Indicator::aim(Anim a, double target, int ms, const Bezier& e, double now, double delay_s) {
    const bool size = a == kAnimW || a == kAnimH || a == kAnimScale;
    // design.md "Reduced motion": sizes swap instantly, everything else
    // becomes an 80 ms crossfade, and nothing waits.
    if (reduced_) {
        ms = size ? 0 : motion_ms(ms, true);
        delay_s = 0.0;
    }
    // Already heading there, or waiting to: re-arming would push a delayed
    // tween back on every refresh.
    if (targets_[a] == target) return;
    targets_[a] = target;
    if (delay_s > 0.0) {
        delayed_[a] = {true, now + delay_s, target, ms, e};
        return;
    }
    delayed_[a].armed = false;
    tl_[a].to(target, ms, e, now);
}

bool Indicator::fire_delayed(double now) {
    bool fired = false;
    for (std::size_t a = 0; a < delayed_.size(); ++a) {
        Delayed& d = delayed_[a];
        if (!d.armed || now < d.at_s) continue;
        d.armed = false;
        tl_[a].to(d.target, d.ms, d.easing, d.at_s);
        fired = true;
    }
    return fired;
}

bool Indicator::any_delayed() const {
    return std::any_of(delayed_.begin(), delayed_.end(), [](const Delayed& d) { return d.armed; });
}

void Indicator::update_targets(double now) {
    const IndicatorLook l = look_;
    const bool warn = model_.warn_text().has_value();
    const bool open = expanded(l);

    double w = kPillW;
    if (l == IndicatorLook::WarningHover) w = warn_pill_w(warn_text_w_, model_.warn_blocking());
    if (!open) w = kIdleLineW;
    // Widen the surface before the pill grows (design.md "Warning"); it
    // narrows again once the pill has shrunk, in on_tick. Only a pill-sized
    // surface resizes: an output-wide one already has room.
    if (w > kPillW && !wide_ && spanned_width() == 0) {
        wide_ = true;
        canvas_.queue_resize();
        apply_position();
    }

    aim(kAnimW, w, kBase, kStandard, now);
    aim(kAnimH, open ? kPillH : kIdleLineH, kBase, kStandard, now);
    aim(kAnimOpacity, open ? kExpandedOpacity : (warn ? kIdleWarnOpacity : kIdleOpacity), kBase,
        kStandard, now);
    aim(kAnimGlass, open ? kFull : kNone, kBase, kStandard, now);
    if (open)
        aim(kAnimContent, kFull, kFast, kStandard, now, kContentDelayS);
    else
        aim(kAnimContent, kNone, kFast, kStandard, now);

    const bool ring = l == IndicatorLook::Recording;
    if (ring)
        aim(kAnimRing, kFull, kInstant, kStandard, now, kRingDelayS);
    else
        aim(kAnimRing, kNone, kFast, kStandard, now);

    aim(kAnimGrip, model_.show_grip() ? kFull : kNone, kFast, kStandard, now);
    // design.md "Reduced motion": no lift while dragging.
    aim(kAnimScale, l == IndicatorLook::Dragging && !reduced_ ? kDragScale : kFull, kFast,
        kStandard, now);
    // design.md "Warning": the dot fades out over 160 ms when it clears.
    aim(kAnimWarnDot, warn && !open ? kFull : kNone, kBase, kStandard, now);
}

void Indicator::apply_input_region() {
    if (!get_realized()) return;
    const double w = tl_[kAnimW].value(now_s());
    const auto r = input_rect(model_.input_region(), w, pill_cx_in_surface(w));
    std::vector<Gdk::Rectangle> rects;
    if (r) {
        // Whole pixels, rounded outward so the region never loses an edge.
        const int x0 = static_cast<int>(std::floor(r->x));
        const int y0 = static_cast<int>(std::floor(r->y));
        const int x1 = static_cast<int>(std::ceil(r->x + r->w));
        const int y1 = static_cast<int>(std::ceil(r->y + r->h));
        rects.emplace_back(x0, y0, x1 - x0, y1 - y0);
    }
    set_input_region(*this, rects);
}

void Indicator::apply_position() {
    const int left = placed_left_ = surface_left();
    if (backend_ == Backend::Wayland) {
        if (gtk_layer_is_layer_window(gobj())) set_overlay_margins(*this, {.left = left});
    } else if (backend_ == Backend::X11 && get_realized() && monitor_) {
        place_x11_overlay(*this, monitor_, left, 0);
    }
}

void Indicator::narrow_if_done(double now) {
    // Only once the wide pill has collapsed, so it is never clipped; with
    // reduced motion the size jumps and this happens at once.
    if (!wide_ || look_ == IndicatorLook::WarningHover || tl_[kAnimW].running(now)) return;
    wide_ = false;
    canvas_.queue_resize();
    apply_position();
    apply_input_region();
}

// ---- time -------------------------------------------------------------------

void Indicator::schedule_deadline() {
    deadline_.disconnect();
    const auto d = model_.next_deadline();
    if (!d) return;
    // One timer for the earliest model deadline (hover delays, grip, the
    // finishing grace); nothing is scheduled while none is pending.
    const double wait_ms = std::max(0.0, std::ceil((*d - now_s()) * kMsPerS));
    deadline_ = Glib::signal_timeout().connect(
        [this] {
            refresh();
            return false;
        },
        static_cast<unsigned>(wait_ms));
}

bool Indicator::needs_tick(double now) const {
    if (tl_.any_running(now) || any_delayed()) return true;
    // The meter and ring breath; reduced motion uses a 10 Hz timer instead.
    if (look_ == IndicatorLook::Recording && !reduced_) return true;
    if (look_ == IndicatorLook::Finishing && !reduced_) return true;  // spinner, dots
    return false;
}

void Indicator::ensure_tick() {
    if (tick_id_ || !needs_tick(now_s())) return;
    last_tick_s_ = now_s();
    tick_id_ = canvas_.add_tick_callback(sigc::mem_fun(*this, &Indicator::on_tick));
}

bool Indicator::on_tick(const Glib::RefPtr<Gdk::FrameClock>&) {
    const double now = now_s();
    const double dt = now - last_tick_s_;
    last_tick_s_ = now;

    bool redraw = fire_delayed(now) || tl_.any_running(now);

    if (!reduced_ && (look_ == IndicatorLook::Recording || look_ == IndicatorLook::Finishing)) {
        meter_.tick(dt);
        if (meter_.clipping() != clipping_) {
            clipping_ = meter_.clipping();
            if (on_clipping_) on_clipping_(clipping_);
        }
        redraw = true;
    }

    // The warning pill's region follows its width while it animates.
    if (model_.input_region() == InputRegion::WarnPill && tl_[kAnimW].running(now))
        apply_input_region();

    narrow_if_done(now);

    if (redraw) canvas_.queue_draw();
    if (needs_tick(now)) return true;
    // Idle: remove the callback so nothing wakes up until the next input.
    tick_id_ = 0;
    canvas_.queue_draw();  // the final frame at the tweens' targets
    return false;
}

// ---- drawing ----------------------------------------------------------------

PangoLayout* Indicator::layout_for(PangoLayout*& slot, const char* text) {
    if (!slot) slot = label_layout(GTK_WIDGET(canvas_.gobj()), text, kLabelPx);
    return slot;
}

void Indicator::rebuild_warn_layout() {
    if (warn_layout_) g_object_unref(warn_layout_);
    warn_layout_ = nullptr;
    warn_text_w_ = 0.0;
    const auto text = model_.warn_text();
    if (!text) return;
    warn_layout_ = label_layout(GTK_WIDGET(canvas_.gobj()), *text, kLabelPx);
    pango_layout_set_width(warn_layout_,
                           static_cast<int>(warn_text_max_w(model_.warn_blocking()) * PANGO_SCALE));
    pango_layout_set_ellipsize(warn_layout_, PANGO_ELLIPSIZE_END);
    PangoRectangle logical{};
    pango_layout_get_pixel_extents(warn_layout_, nullptr, &logical);
    warn_text_w_ = logical.width;
}

void Indicator::draw_text(GtkSnapshot* s, PangoLayout* l, float x, float cy, Rgba c) {
    PangoRectangle logical{};
    pango_layout_get_pixel_extents(l, nullptr, &logical);
    gtk_snapshot_save(s);
    const graphene_point_t at = GRAPHENE_POINT_INIT(x, std::round(cy - logical.height / 2.0f));
    gtk_snapshot_translate(s, &at);
    const GdkRGBA col = to_gdk(c);
    gtk_snapshot_append_layout(s, l, &col);
    gtk_snapshot_restore(s);
}

void Indicator::draw(GtkSnapshot* s) {
    const double now = now_s();
    const double w = tl_[kAnimW].value(now);
    const double h = tl_[kAnimH].value(now);
    const double cx = pill_cx_in_surface(w);
    const double bottom = kSurfaceH - kIndicatorBottom;
    const graphene_rect_t pill = rect(cx - w / 2, bottom - h, w, h);
    const float radius = pill.size.height / 2;

    const double alpha = tl_[kAnimOpacity].value(now) * tl_[kAnimFade].value(now);
    if (alpha <= 0.0) return;

    if (dragging_ && snap_point_) {
        const double tick_x = *snap_point_ * output_width() - placed_left_;
        fill_rounded(s, rect(tick_x - kTickW / 2, 0, kTickW, kTickH), 0, tokens_.text2);
    }

    gtk_snapshot_push_opacity(s, alpha);
    const double scale = tl_[kAnimScale].value(now);
    const bool scaled = std::abs(scale - kFull) > 1e-4;
    if (scaled) {
        gtk_snapshot_save(s);
        const graphene_point_t c = GRAPHENE_POINT_INIT(static_cast<float>(cx),
                                                       pill.origin.y + pill.size.height / 2);
        const graphene_point_t back = GRAPHENE_POINT_INIT(-c.x, -c.y);
        gtk_snapshot_translate(s, &c);
        gtk_snapshot_scale(s, static_cast<float>(scale), static_cast<float>(scale));
        gtk_snapshot_translate(s, &back);
    }

    const double glass = tl_[kAnimGlass].value(now);
    if (glass < kFull) {
        gtk_snapshot_push_opacity(s, kFull - glass);
        draw_idle_line(s, pill, now);
        gtk_snapshot_pop(s);
    }
    if (glass > kNone) {
        gtk_snapshot_push_opacity(s, glass);
        draw_glass(s, pill, radius, tokens_);
        gtk_snapshot_pop(s);
    }

    const double ring = tl_[kAnimRing].value(now);
    if (ring > kNone) {
        const double breath =
            reduced_ ? kBreathHigh : pulse(now, kBreathHalfPeriodS, kBreathHigh, kBreathLow);
        Rgba c = tokens_.record;
        c.a *= ring * breath;
        inside_ring(s, pill, kRingPx, c);
    }

    const double content = tl_[kAnimContent].value(now);
    if (content > kNone) {
        const GskRoundedRect clip = rounded(pill, radius);
        gtk_snapshot_push_rounded_clip(s, &clip);
        gtk_snapshot_push_opacity(s, content);
        draw_content(s, pill, now);
        gtk_snapshot_pop(s);
        gtk_snapshot_pop(s);
    }

    if (scaled) gtk_snapshot_restore(s);
    gtk_snapshot_pop(s);
}

void Indicator::draw_idle_line(GtkSnapshot* s, graphene_rect_t r, double now) {
    const GskRoundedRect rr = rounded(r, r.size.height / 2);
    const GdkRGBA shadow = to_gdk(kIdleShadow);
    const GdkRGBA ring = to_gdk(kIdleRing);
    gtk_snapshot_append_outset_shadow(s, &rr, &shadow, 0, kIdleShadowDy, 0, kIdleShadowBlur);
    gtk_snapshot_append_outset_shadow(s, &rr, &ring, 0, 0, kIdleRingPx, 0);
    fill_rounded(s, r, r.size.height / 2, kIdleFill);

    const double dot = tl_[kAnimWarnDot].value(now);
    if (dot <= kNone) return;
    const float dcx = r.origin.x + r.size.width / 2 + kWarnDotDx;
    const float dcy = r.origin.y + kWarnDotDy + kWarnDotD / 2;
    gtk_snapshot_push_opacity(s, dot);
    circle(s, dcx, dcy, kWarnDotD + 2 * kIdleRingPx, kWarnDotRing);
    circle(s, dcx, dcy, kWarnDotD, kWarnDotFill);
    gtk_snapshot_pop(s);
}

void Indicator::draw_content(GtkSnapshot* s, graphene_rect_t r, double now) {
    const float left = r.origin.x;
    const float right = r.origin.x + r.size.width;
    const float cy = r.origin.y + r.size.height / 2;
    const float bx = left + kButtonInset + kButtonD / 2.0f;  // the button's centre
    const float after_button = left + kButtonInset + kButtonD + kContentGap;

    switch (content_look_) {
    case IndicatorLook::Hover: {
        circle(s, bx, cy, kButtonD, tokens_.sunken);
        draw_icon(s, Icon::Mic, bx - kMicSize / 2, cy - kMicSize / 2, kMicSize, tokens_.text);
        draw_text(s, layout_for(dictate_layout_, "Dictate"), after_button, cy, tokens_.text2);
        const double grip = tl_[kAnimGrip].value(now);
        if (grip > kNone) {
            Rgba c = tokens_.text2;
            c.a *= kGripAlpha * grip;
            draw_icon(s, Icon::GripVertical, right - kPadRight - kGripSize, cy - kGripSize / 2,
                      kGripSize, c);
        }
        break;
    }
    case IndicatorLook::Recording: {
        circle(s, bx, cy, kDiscD, tokens_.record_fill);
        fill_rounded(s, rect(bx - kStopSide / 2, cy - kStopSide / 2, kStopSide, kStopSide),
                     kStopRadius, kStopFill);
        draw_meter(s, r);
        break;
    }
    case IndicatorLook::Finishing: {
        gtk_snapshot_save(s);
        const graphene_point_t c = GRAPHENE_POINT_INIT(bx, cy);
        gtk_snapshot_translate(s, &c);
        if (!reduced_) {
            const double turn = std::fmod(now, kSpinPeriodS) / kSpinPeriodS;
            gtk_snapshot_rotate(s, static_cast<float>(turn * 360.0));
        }
        draw_icon(s, Icon::LoaderCircle, -kMicSize / 2, -kMicSize / 2, kMicSize, tokens_.text2);
        gtk_snapshot_restore(s);
        draw_dots(s, r, now);
        break;
    }
    case IndicatorLook::WarningHover: {
        float x = after_button;
        if (model_.warn_blocking()) {
            // design.md "Warning": the mic itself is the problem.
            draw_icon(s, Icon::MicOff, bx - kMicSize / 2, cy - kMicSize / 2, kMicSize,
                      tokens_.danger);
        } else {
            circle(s, bx, cy, kButtonD, tokens_.sunken);
            draw_icon(s, Icon::Mic, bx - kMicSize / 2, cy - kMicSize / 2, kMicSize, tokens_.text);
            draw_icon(s, Icon::TriangleAlert, x, cy - kWarnIconSize / 2.0f, kWarnIconSize,
                      tokens_.warn);
            x += kWarnIconSize + kContentGap;
        }
        if (warn_layout_) draw_text(s, warn_layout_, x, cy, tokens_.text);
        break;
    }
    case IndicatorLook::Dragging: {
        PangoLayout* move = layout_for(move_layout_, "Move");
        PangoRectangle logical{};
        pango_layout_get_pixel_extents(move, nullptr, &logical);
        const float group = kMicSize + kContentGap + logical.width;
        const float x = r.origin.x + (r.size.width - group) / 2;
        draw_icon(s, Icon::GripHorizontal, x, cy - kMicSize / 2, kMicSize, tokens_.text2);
        draw_text(s, move, x + kMicSize + kContentGap, cy, tokens_.text2);
        break;
    }
    case IndicatorLook::Idle:
    case IndicatorLook::Warning:
        break;
    }
}

void Indicator::draw_meter(GtkSnapshot* s, graphene_rect_t r) {
    const float right = r.origin.x + r.size.width - kPadRight - kMeterRightInset;
    const float cy = r.origin.y + r.size.height / 2;
    if (reduced_) {
        const float w = static_cast<float>(kBarMin + (kSingleBarMaxW - kBarMin) * reduced_fill_);
        const float h = static_cast<float>(kBarMin);
        fill_rounded(s, rect(right - kSingleBarMaxW, cy - h / 2, w, h), kBarRadius,
                     tokens_.record);
        return;
    }
    const auto heights = meter_.bar_heights();
    const float total = heights.size() * kBarW + (heights.size() - 1) * kBarGap;
    float x = right - total;
    for (double bh : heights) {
        const float h = static_cast<float>(bh);
        fill_rounded(s, rect(x, cy - h / 2, kBarW, h), kBarRadius, tokens_.record);
        x += kBarW + kBarGap;
    }
}

void Indicator::draw_dots(GtkSnapshot* s, graphene_rect_t r, double now) {
    const float right = r.origin.x + r.size.width - kPadRight - kDotsRightInset;
    const float cy = r.origin.y + r.size.height / 2;
    float x = right - kDotCount * kDotD - (kDotCount - 1) * kDotGap;
    for (int i = 0; i < kDotCount; ++i) {
        const double a = reduced_ ? kDotStatic
                                  : pulse(now - i * kDotStaggerS, kDotHalfPeriodS, kDotLow, kDotHigh);
        Rgba c = tokens_.text2;
        c.a *= a;
        circle(s, x + kDotD / 2, cy, kDotD, c);
        x += kDotD + kDotGap;
    }
}

}  // namespace flowd
