#pragma once

#include <gdkmm/monitor.h>
#include <gtkmm/eventcontrollermotion.h>
#include <gtkmm/gesturedrag.h>
#include <gtkmm/widget.h>
#include <gtkmm/window.h>
#include <pango/pango.h>

#include <array>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "backend.hpp"
#include "indicator_geometry.hpp"
#include "indicator_model.hpp"
#include "meter.hpp"
#include "motion.hpp"
#include "outputs.hpp"
#include "position_store.hpp"
#include "protocol.hpp"
#include "theme.hpp"

// The indicator: a fixed-size, focus-free surface holding one pill that
// changes size, drawn from IndicatorModel (design.md "Indicator"). All
// timing lives in the model, the meter and the tweens; this file only feeds
// them input and draws what they say.
namespace flowd {

class Indicator;

// The one widget inside the indicator window: it draws the pill and reports
// the fixed surface size.
class IndicatorCanvas : public Gtk::Widget {
public:
    explicit IndicatorCanvas(Indicator& owner);

protected:
    void snapshot_vfunc(const Glib::RefPtr<Gtk::Snapshot>& snapshot) override;
    Gtk::SizeRequestMode get_request_mode_vfunc() const override;
    void measure_vfunc(Gtk::Orientation orientation, int for_size, int& minimum, int& natural,
                       int& minimum_baseline, int& natural_baseline) const override;
    void size_allocate_vfunc(int width, int height, int baseline) override;

private:
    Indicator& owner_;
};

class Indicator : public Gtk::Window {
public:
    using ClickFn = std::function<void()>;
    using MovedFn = std::function<void(double fraction, std::string output)>;

    // Sets the window up as a layer surface (Wayland) or an override-redirect
    // window (X11) but does not show it; call start(). store must outlive
    // this window.
    Indicator(Backend backend, PositionStore& store, Tokens tokens, bool reduced_motion,
              ClickFn on_click, MovedFn on_moved);
    ~Indicator() override;

    // Shows the window and starts following outputs. Returns false, with
    // why_not() saying why, when the surface failed its focus checks; the
    // window must then stay hidden (ADR 0003).
    bool start();
    const std::optional<std::string>& why_not() const { return why_not_; }

    void on_state(UiState s);
    void on_level(Level l);
    void on_warn(Warn w);
    void on_config(UiConfig c);
    void set_tokens(Tokens t);
    void set_reduced_motion(bool reduced);
    // Moves to monitor with a crossfade and applies its saved position.
    void set_output(const Glib::RefPtr<Gdk::Monitor>& monitor);

    // The pill centre on its output, in logical px, for the popup's anchor.
    double center_x() const { return center_x_; }
    // The output the indicator is on, or null before start(); the popup
    // shows on the same one.
    const Glib::RefPtr<Gdk::Monitor>& monitor() const { return monitor_; }
    // Called whenever the meter's clipping state changes.
    void set_on_clipping(std::function<void(bool)> fn) { on_clipping_ = std::move(fn); }

private:
    friend class IndicatorCanvas;

    // Indices into the timeline; each is one animated value.
    enum Anim : std::size_t {
        kAnimW,        // pill width, px
        kAnimH,        // pill height, px
        kAnimOpacity,  // whole-pill opacity
        kAnimGlass,    // 0 = idle line material, 1 = glass
        kAnimContent,  // the expanded pill's content
        kAnimRing,     // the recording ring
        kAnimGrip,     // the grip affordance
        kAnimScale,    // the drag lift
        kAnimWarnDot,  // the idle warning dot
        kAnimFade,     // the output-switch crossfade
        kAnimCount,
    };

    static double now_s();
    // Settles the model at now and brings everything derived from it up to
    // date: targets, input region, cursor, timers and the tick callback.
    void refresh();
    void aim(Anim a, double target, int ms, const Bezier& e, double now, double delay_s = 0.0);
    void update_targets(double now);
    void apply_input_region();
    void apply_position();
    void update_cursor(double x, double y);
    void schedule_deadline();
    void ensure_tick();
    bool needs_tick(double now) const;
    bool on_tick(const Glib::RefPtr<Gdk::FrameClock>& clock);
    void rebuild_warn_layout();
    void use_monitor(const Glib::RefPtr<Gdk::Monitor>& monitor);
    void set_fullscreen_hidden(bool hidden);
    // Shows or hides for the config and fullscreen state together.
    void update_visibility();
    // Returns a pill-sized surface to its narrow width once the wide pill has
    // collapsed.
    void narrow_if_done(double now);
    // Runs the reduced-motion meter on a 10 Hz timer while recording.
    void update_reduced_meter();
    bool on_reduced_meter();
    void show_now();
    int output_width() const;
    // The width the surface spans: the output's (its workarea's on X11), or
    // 0 when it must stay pill-sized (X11 without a compositor).
    int spanned_width() const;
    // Re-reads the saved position and re-sizes for the current monitor.
    void place_on_monitor();
    std::string output_name() const;
    // Where the surface's left edge belongs on the output, for the width it
    // has now; placed_left_ is where apply_position last put it.
    int surface_left() const;
    // Places the surface for a width the compositor has just given it.
    void on_canvas_allocated();
    double pill_cx_in_surface(double pill_w) const;

    // Gestures.
    void on_drag_begin(double x, double y);
    void on_drag_update(double dx, double dy);
    void on_drag_end(double dx, double dy);
    void end_drag();
    bool fire_delayed(double now);
    bool any_delayed() const;

    // Drawing, called from the canvas.
    void draw(GtkSnapshot* s);
    void draw_idle_line(GtkSnapshot* s, graphene_rect_t r, double now);
    void draw_content(GtkSnapshot* s, graphene_rect_t r, double now);
    void draw_meter(GtkSnapshot* s, graphene_rect_t r);
    void draw_dots(GtkSnapshot* s, graphene_rect_t r, double now);
    void draw_text(GtkSnapshot* s, PangoLayout* l, float x, float cy, Rgba c);
    PangoLayout* layout_for(PangoLayout*& slot, const char* text);

    Backend backend_;
    PositionStore& store_;
    Tokens tokens_;
    bool reduced_;
    ClickFn on_click_;
    MovedFn on_moved_;
    std::function<void(bool)> on_clipping_;

    IndicatorCanvas canvas_;
    Glib::RefPtr<Gtk::EventControllerMotion> motion_;
    Glib::RefPtr<Gtk::GestureDrag> drag_;
    std::unique_ptr<OutputTracker> tracker_;

    IndicatorModel model_;
    Meter meter_;
    Timeline<kAnimCount> tl_;
    std::array<double, kAnimCount> targets_{};
    // A tween waiting for its delay (design.md "Choreography": the ring
    // fades in after the size lands, content after the size starts).
    struct Delayed {
        bool armed = false;
        double at_s = 0.0;
        double target = 0.0;
        int ms = 0;
        Bezier easing = kStandard;
    };
    std::array<Delayed, kAnimCount> delayed_{};
    std::optional<UiState> last_state_;

    IndicatorLook look_ = IndicatorLook::Idle;
    // The last expanded look, drawn while the content fades out on collapse.
    IndicatorLook content_look_ = IndicatorLook::Hover;
    bool wide_ = false;  // a pill-sized surface is sized for the warning pill
    bool clipping_ = false;
    bool started_ = false;
    bool fullscreen_hidden_ = false;
    bool config_hidden_ = false;  // [ui] indicator = false
    std::optional<std::string> why_not_;

    Glib::RefPtr<Gdk::Monitor> monitor_;
    Glib::RefPtr<Gdk::Monitor> pending_monitor_;  // waiting for the fade-out
    sigc::connection monitor_switch_;
    sigc::connection monitor_gone_;
    sigc::connection monitor_geometry_;
    double center_x_ = 0.0;
    int placed_left_ = 0;

    // Drag bookkeeping, in logical px.
    bool pressed_ = false;
    bool moved_ = false;  // passed the drag threshold, so never a click
    bool dragging_ = false;
    bool cancelled_ = false;  // the compositor took the grab: no click
    double press_x_ = 0.0, press_y_ = 0.0;
    double press_center_ = 0.0;
    std::optional<double> snap_point_;
    // The pointer's last position over the surface, so the cursor can follow
    // look changes that happen without motion.
    std::optional<std::pair<double, double>> pointer_;

    guint tick_id_ = 0;
    double last_tick_s_ = 0.0;
    double last_meter_draw_s_ = 0.0;  // the reduced-motion meter timer's last run
    double reduced_fill_ = 0.0;  // the single bar's level, sampled at 10 Hz
    sigc::connection deadline_;
    sigc::connection reduced_meter_;

    PangoLayout* dictate_layout_ = nullptr;
    PangoLayout* move_layout_ = nullptr;
    PangoLayout* warn_layout_ = nullptr;
    double warn_text_w_ = 0.0;
};

}  // namespace flowd
