#pragma once

#include <gdkmm/monitor.h>
#include <gtkmm/widget.h>
#include <gtkmm/window.h>
#include <pango/pango.h>

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "backend.hpp"
#include "footer.hpp"
#include "icons.hpp"
#include "motion.hpp"
#include "placement.hpp"
#include "popup_model.hpp"
#include "popup_text.hpp"
#include "protocol.hpp"
#include "theme.hpp"

// The preview popup: a read-only, click-through surface spanning the output's
// width, holding one transcript card with a footer (design.md "Preview
// popup"). PopupModel decides what it says and for how long; popup_text
// decides how the text changes. This file feeds them input and draws.
namespace flowd {

class Popup;

// The one widget inside the popup window: it draws the card and reports the
// fixed surface size.
class PopupCanvas : public Gtk::Widget {
public:
    explicit PopupCanvas(Popup& owner);

protected:
    void snapshot_vfunc(const Glib::RefPtr<Gtk::Snapshot>& snapshot) override;
    Gtk::SizeRequestMode get_request_mode_vfunc() const override;
    void measure_vfunc(Gtk::Orientation orientation, int for_size, int& minimum, int& natural,
                       int& minimum_baseline, int& natural_baseline) const override;
    void size_allocate_vfunc(int width, int height, int baseline) override;

private:
    Popup& owner_;
};

class Popup : public Gtk::Window {
public:
    // Sets the window up as a layer surface (Wayland) but does not show it;
    // on X11 the override-redirect setup happens on the first show. When the
    // surface fails its focus checks, why_not() says why and the popup never
    // shows (ADR 0003).
    Popup(Backend backend, Tokens tokens, bool reduced_motion);
    ~Popup() override;

    const std::optional<std::string>& why_not() const { return why_not_; }

    // Not on_show/on_hide: those are Gtk::Widget virtuals, and hiding them
    // replaces the handler that maps the window.
    void on_show_msg();
    void on_render(const Render& r);
    void on_state(const StateMsg& s);
    void on_meta(const Meta& m);
    void on_config(const UiConfig& c);
    void on_fade();
    void on_hide_msg();
    // design.md "Warning" → Recording + warning: the footer carries it.
    void on_warn(const Warn& w);
    // The indicator's centre on its output, in logical px; the card centres
    // on it (design.md "Popup placement").
    void set_anchor_x(double x);
    void set_tokens(Tokens t);
    void set_reduced_motion(bool reduced);
    // The meter's clipping flag, for the "Too loud" hint.
    void set_clipping(bool clipping);
    // The output to show on, normally the indicator's. Applied at the next
    // show, so a visible card never jumps between outputs.
    void set_output(const Glib::RefPtr<Gdk::Monitor>& monitor);

    // For tests: the model, the card as last laid out, and a frame drawn at
    // an explicit time, without a compositor.
    const PopupModel& model() const { return model_; }
    CardRect card() const { return card_; }
    int text_lines() const { return text_lines_; }
    void draw_at(GtkSnapshot* s, double now);

private:
    friend class PopupCanvas;

    enum Anim : std::size_t {
        kAnimOpacity,    // whole-card opacity, enter and exit
        kAnimShift,      // translateY, px: 6 -> 0 entering, 0 -> 4 exiting
        kAnimHeight,     // card height, px
        kAnimScroll,     // text scrolled off the top, px
        kAnimCrossfade,  // 0 -> 1: the new run fading in
        kAnimHighlight,  // the self-correction highlight's alpha
        kAnimCount,
    };

    // One footer item as drawn: its layout and where it sits in the card.
    struct FooterRun {
        FooterKind kind;
        PangoLayout* layout = nullptr;
        double x = 0.0;  // the text's left edge, from the card's left edge
        double w = 0.0;  // the text's drawn width
    };

    static double now_s();
    // Settles the model at now and brings everything derived from it up to
    // date: text, card geometry, footer, phase, timers and the tick.
    void refresh();
    void on_phase(PopupPhase from, PopupPhase to, double now);
    void show_now();
    void hide_now();
    void update_text(double now, bool fresh);
    void rebuild_attrs(double now);
    void update_geometry(double now, bool fresh, const FooterInput& in);
    void update_footer(const FooterInput& in);
    void clear_footer();
    void end_crossfade();
    void schedule_deadline(double now);
    bool spinning() const;
    bool caret_blinks() const;
    bool needs_tick(double now) const;
    void ensure_tick();
    bool on_tick(const Glib::RefPtr<Gdk::FrameClock>& clock);
    void apply_input_region();
    // Places the X11 window for a size the canvas has just been given.
    void on_canvas_allocated();
    // The output's logical width; the last one known while no output is.
    int output_width() const;
    void use_monitor(const Glib::RefPtr<Gdk::Monitor>& monitor);
    // Moves the surface so its left edge is at surface_left_.
    void apply_position();
    // A footer label at the label size; tnum turns on tabular figures.
    PangoLayout* footer_layout(std::string_view text, bool tnum);
    // What each footer item's text measures, as compose_footer needs it:
    // the Pango width (tabular figures for the clock), plus the timer icon
    // drawn before a countdown.
    TextMeasure footer_measure();

    // Drawing. box is the text area, clip the part of it text may show in.
    void draw(GtkSnapshot* s);
    void draw_text(GtkSnapshot* s, graphene_rect_t box, graphene_rect_t clip, float card_top,
                   double now);
    void draw_footer(GtkSnapshot* s, graphene_rect_t card, double now);

    Backend backend_;
    Tokens tokens_;
    bool reduced_;
    std::optional<std::string> why_not_;
    bool x11_ready_ = false;

    PopupCanvas canvas_;
    PopupModel model_;
    PopupPhase phase_ = PopupPhase::Hidden;  // as last acted on
    bool restart_ = false;  // on_show since the last refresh: a new session
    Timeline<kAnimCount> tl_;
    UiConfig config_{};
    int surface_h_ = popup_surface_h(kDefaultMaxLines);
    double anchor_x_ = -1.0;  // unset until the indicator reports one
    Glib::RefPtr<Gdk::Monitor> monitor_;          // the output shown on
    Glib::RefPtr<Gdk::Monitor> pending_monitor_;  // applied at the next show
    sigc::connection monitor_gone_;
    int output_w_ = 0;  // monitor_'s width, kept if it goes away while shown
    // The surface's left edge on the output (popup_surface_left); the card
    // is drawn at card_.x - surface_left_ within it.
    int surface_left_ = 0;

    // The text as laid out now, and the spec it was built from.
    TextSpec spec_;
    PangoLayout* text_ = nullptr;
    int text_lines_ = 1;   // lines in the whole paragraph
    int text_natural_w_ = 0;  // the paragraph unwrapped, px
    int dots_shown_ = -1;  // the listening dots in text_'s attributes
    double shown_at_ = 0.0;  // the caret, dots and spinner count from here
    // A zone swap in progress (design.md "Pending -> polished swap"). The
    // new run fades in; when the live run turns pending, the previous
    // layout also fades out its live run, since the words stay put.
    std::optional<Crossfade> fade_;
    PangoLayout* prev_text_ = nullptr;  // only while a live run fades out
    TextSpec prev_spec_;                // what prev_text_ holds
    // design.md "Self-correction merge": the rewritten polished run.
    std::optional<ByteRange> highlight_;
    double highlight_until_ = 0.0;

    CardRect card_{};
    int prev_w_ = 0;  // the card only grows during a session
    bool footer_on_ = false;
    double height_target_ = -1.0;  // the card height kAnimHeight aims at
    double scroll_target_ = -1.0;  // the scroll kAnimScroll aims at

    // The footer as last composed, so the elapsed tick only relays out when
    // the row actually changed.
    FooterInput footer_in_;
    int footer_avail_ = -1;
    std::vector<FooterRun> footer_runs_;
    std::optional<Status> footer_status_;
    bool countdown_ = false;  // the elapsed item is the countdown
    PangoLayout* measure_ = nullptr;
    PangoLayout* measure_tnum_ = nullptr;  // with tabular figures, for the clock
    PangoLayout* sep_ = nullptr;  // the "·" between elapsed time and hint
    double sep_x_ = -1.0;  // its left edge from the card's, or < 0 when not drawn

    guint tick_id_ = 0;
    sigc::connection deadline_;
};

}  // namespace flowd
