#include "popup.hpp"

#include <gdkmm/display.h>
#include <glibmm/main.h>
#include <gtk4-layer-shell.h>
#include <gtkmm/snapshot.h>

#include <algorithm>
#include <array>
#include <climits>
#include <cmath>
#include <utility>

#include "draw.hpp"
#include "outputs.hpp"
#include "surface.hpp"

namespace flowd {

namespace {

constexpr const char* kNamespace = "flowd-popup";

// design.md "Shapes": the card is rounded.xl.
constexpr float kCardRadius = 14.0f;
// design.md "Preview popup" → Anatomy: 18 px sides; popup-text 15 / 22.
constexpr float kPadX = 18.0f;
constexpr int kTextPx = 15;

// design.md "The three text zones" → Pending: a 1 px underline in text-2 at
// 40%, 4 px under the baseline (overlay.css text-underline-offset).
constexpr float kUnderlinePx = 1.0f;
constexpr float kUnderlineOffset = 4.0f;
constexpr double kUnderlineAlpha = 0.4;
// Live: a 2 x 16 caret, 2 px after the last glyph, its bottom 2 px under the
// baseline (overlay.css .caret vertical-align: -2px), blinking in 1 s steps:
// on for the first half, off for the second.
constexpr float kCaretW = 2.0f;
constexpr float kCaretH = 16.0f;
constexpr float kCaretGap = 2.0f;
constexpr float kCaretDrop = 2.0f;
constexpr double kCaretPeriodS = 1.0;
constexpr double kCaretOnS = 0.5;
// Self-correction merge: a primary-soft highlight, radius 3, for 600 ms. It
// covers the glyphs' content area, not the whole 22 px line, as a CSS inline
// background does.
constexpr float kHighlightRadius = 3.0f;
constexpr float kHighlightInsetY = 2.0f;
constexpr int kHighlightMs = 600;
// Auto-scroll: the top fade runs from transparent at 14 px to opaque at 34 px
// from the card's top edge, taken from overlay.css (.popup .body.scrolled
// mask-image) rather than design.md's "16 px".
constexpr float kMaskClearY = 14.0f;
constexpr float kMaskOpaqueY = 34.0f;
// Enter translateY 6 -> 0, exit 0 -> 4 (design.md "States" 1 and 4).
constexpr double kEnterShift = 6.0;
constexpr double kExitShift = 4.0;
// design.md "Reduced motion": the popup only fades, over dur-instant, linear.
constexpr Bezier kLinear{0.0, 0.0, 1.0, 1.0};

// Footer (design.md "Preview popup" → Anatomy, overlay.css .foot): 8 px of
// top padding inside its 28 px, padding 0 18 0 14, a 1 px top border in
// text-2 at 18%. design.md's "@ 50%" names no colour, so the CSS value wins.
constexpr float kFootPadTop = 8.0f;
constexpr float kFootPadL = 14.0f;
constexpr float kFootPadR = kPadX;
constexpr float kFootBorderPx = 1.0f;
constexpr double kFootBorderAlpha = 0.18;
// The mode chip: 20 px tall, padding 0 7 0 5, a 12 px icon 4 px before the
// text, rounded.sm, text-2 at 14%. kModeChipExtraPx is the same sum.
constexpr float kChipH = 20.0f;
constexpr float kChipPadL = 5.0f;
constexpr float kChipPadR = 7.0f;
constexpr float kChipIcon = 12.0f;
constexpr float kChipIconGap = 4.0f;
constexpr float kChipRadius = 6.0f;
constexpr double kChipAlpha = 0.14;
// The status and countdown icons are 14 px; the end group (elapsed, "·",
// hint) keeps kFooterEndGapPx gaps and dims the dot to 60% (overlay.css
// .end, .sep).
constexpr float kStatusIcon = 14.0f;
constexpr double kSepAlpha = 0.6;
// design.md "Preview popup" → Finishing: loader-circle at 800 ms per turn.
constexpr double kSpinPeriodS = 0.8;
constexpr double kFullTurnDeg = 360.0;

constexpr double kFull = 1.0;
constexpr double kNone = 0.0;
constexpr double kUsPerS = 1e6;
constexpr double kMsPerS = 1000.0;
constexpr int kAlphaMax = 65535;

graphene_rect_t rect(double x, double y, double w, double h) {
    return GRAPHENE_RECT_INIT(static_cast<float>(x), static_cast<float>(y),
                              static_cast<float>(std::max(w, 0.0)),
                              static_cast<float>(std::max(h, 0.0)));
}

double px(int pango_units) { return static_cast<double>(pango_units) / PANGO_SCALE; }

Rgba scaled(Rgba c, double alpha) {
    c.a = std::clamp(c.a * alpha, 0.0, 1.0);
    return c;
}

// Foreground colour and alpha over r. Pango reads an alpha of 0 as "unset",
// so an invisible run gets the smallest non-zero alpha instead.
void color_attr(PangoAttrList* a, Rgba c, ByteRange r, double alpha = 1.0) {
    if (r.empty()) return;
    const auto channel = [](double v) {
        return static_cast<guint16>(std::lround(std::clamp(v, 0.0, 1.0) * kAlphaMax));
    };
    PangoAttribute* fg = pango_attr_foreground_new(channel(c.r), channel(c.g), channel(c.b));
    PangoAttribute* al =
        pango_attr_foreground_alpha_new(std::max<guint16>(1, channel(c.a * alpha)));
    for (PangoAttribute* at : {fg, al}) {
        at->start_index = static_cast<guint>(r.begin);
        at->end_index = static_cast<guint>(r.end);
        pango_attr_list_change(a, at);
    }
}

void style_attr(PangoAttrList* a, PangoAttribute* at, ByteRange r) {
    at->start_index = static_cast<guint>(r.begin);
    at->end_index = static_cast<guint>(r.end);
    pango_attr_list_change(a, at);
}

PangoAttrList* base_attrs() {
    PangoAttrList* a = pango_attr_list_new();
    pango_attr_list_insert(a, pango_attr_line_height_new_absolute(kPopupLineH * PANGO_SCALE));
    return a;
}

// Calls fn(x0, x1, line_top, line_bottom, baseline), in px from the layout's
// origin, for each visual piece of r on each line it touches.
template <typename Fn>
void for_each_piece(PangoLayout* l, ByteRange r, Fn&& fn) {
    if (!l || r.empty()) return;
    PangoLayoutIter* it = pango_layout_get_iter(l);
    do {
        PangoLayoutLine* line = pango_layout_iter_get_line_readonly(it);
        const int ls = line->start_index;
        const int le = ls + line->length;
        // Clamped to the line: outside it, x ranges run to the layout's edge.
        const int b = std::max(ls, static_cast<int>(r.begin));
        const int e = std::min(le, static_cast<int>(r.end));
        if (b < e) {
            int y0 = 0, y1 = 0;
            pango_layout_iter_get_line_yrange(it, &y0, &y1);
            const int base = pango_layout_iter_get_baseline(it);
            int* ranges = nullptr;
            int n = 0;
            pango_layout_line_get_x_ranges(line, b, e, &ranges, &n);
            for (int i = 0; i < n; ++i)
                fn(px(ranges[2 * i]), px(ranges[2 * i + 1]), px(y0), px(y1), px(base));
            g_free(ranges);
        }
    } while (pango_layout_iter_next_line(it));
    pango_layout_iter_free(it);
}

double last_baseline(PangoLayout* l) {
    PangoLayoutIter* it = pango_layout_get_iter(l);
    while (pango_layout_iter_next_line(it)) {
    }
    const double b = px(pango_layout_iter_get_baseline(it));
    pango_layout_iter_free(it);
    return b;
}

void append_layout_at(GtkSnapshot* s, PangoLayout* l, double x, double y, Rgba c) {
    gtk_snapshot_save(s);
    const graphene_point_t at = GRAPHENE_POINT_INIT(static_cast<float>(x), static_cast<float>(y));
    gtk_snapshot_translate(s, &at);
    const GdkRGBA col = to_gdk(c);
    gtk_snapshot_append_layout(s, l, &col);
    gtk_snapshot_restore(s);
}

// A single-line layout's text drawn with its logical box centred on cy.
void draw_line(GtkSnapshot* s, PangoLayout* l, double x, double cy, Rgba c) {
    int h = 0;
    pango_layout_get_pixel_size(l, nullptr, &h);
    append_layout_at(s, l, x, std::round(cy - h / 2.0), c);
}

int pixel_width(PangoLayout* l) {
    int w = 0;
    pango_layout_get_pixel_size(l, &w, nullptr);
    return w;
}

}  // namespace

// ---- canvas -----------------------------------------------------------------

PopupCanvas::PopupCanvas(Popup& owner) : owner_(owner) {
    set_focusable(false);
    set_can_focus(false);
}

Gtk::SizeRequestMode PopupCanvas::get_request_mode_vfunc() const {
    return Gtk::SizeRequestMode::CONSTANT_SIZE;
}

void PopupCanvas::measure_vfunc(Gtk::Orientation orientation, int, int& minimum, int& natural,
                                int& minimum_baseline, int& natural_baseline) const {
    // Fixed for a given max_lines and output: the card grows inside the
    // surface, so the compositor never resizes it mid-animation (design.md
    // "Motion" → GTK mapping). Wide enough for the widest card and its
    // shadow; apply_position slides it under the card.
    const int w = popup_surface_w(owner_.output_width());
    minimum = natural = orientation == Gtk::Orientation::HORIZONTAL ? w : owner_.surface_h_;
    minimum_baseline = natural_baseline = -1;
}

void PopupCanvas::size_allocate_vfunc(int width, int height, int baseline) {
    Gtk::Widget::size_allocate_vfunc(width, height, baseline);
    owner_.on_canvas_allocated();
}

void PopupCanvas::snapshot_vfunc(const Glib::RefPtr<Gtk::Snapshot>& snapshot) {
    owner_.draw(snapshot->gobj());
}

// ---- window -----------------------------------------------------------------

Popup::Popup(Backend backend, Tokens tokens, bool reduced_motion)
    : backend_(backend), tokens_(tokens), reduced_(reduced_motion), canvas_(*this) {
    install_window_css();
    set_decorated(false);
    set_resizable(false);
    set_focusable(false);
    set_can_focus(false);
    set_title(kNamespace);
    set_child(canvas_);
    tl_[kAnimCrossfade].jump(kFull);

    GtkWidget* w = GTK_WIDGET(canvas_.gobj());
    text_ = text_layout(w, "", kTextPx);
    pango_layout_set_wrap(text_, PANGO_WRAP_WORD_CHAR);
    measure_ = label_layout(w, "", kLabelPx);
    measure_tnum_ = footer_layout("", true);
    sep_ = label_layout(w, kFooterSep, kLabelPx);

    switch (backend_) {
    case Backend::Wayland:
        // The card sits kPopupPad above the surface's bottom edge, 52 px
        // above the output's (design.md "Popup placement"); the left margin
        // follows the card. Click-through: the input region is set empty on
        // show.
        make_overlay_surface(*this, kNamespace, Edges::Left | Edges::Bottom,
                             {.bottom = kPopupSurfaceBottom}, why_not_);
        break;
    case Backend::X11:
        break;  // set up on the first show: make_x11_overlay realizes the window
    case Backend::Unsupported:
        why_not_ = "no display backend can keep the popup from taking focus";
        break;
    }
}

Popup::~Popup() {
    // Timers and the tick first: each captures this.
    deadline_.disconnect();
    monitor_gone_.disconnect();
    if (tick_id_) canvas_.remove_tick_callback(tick_id_);
    tick_id_ = 0;
    clear_footer();
    for (PangoLayout* l : {text_, prev_text_, measure_, measure_tnum_, sep_})
        if (l) g_object_unref(l);
}

double Popup::now_s() { return static_cast<double>(g_get_monotonic_time()) / kUsPerS; }

// ---- inputs -----------------------------------------------------------------

void Popup::on_show_msg() {
    model_.on_show(now_s());
    restart_ = true;
    refresh();
}

void Popup::on_render(const Render& r) {
    model_.on_render(r);
    refresh();
}

void Popup::on_state(const StateMsg& s) {
    model_.on_state(s, now_s());
    refresh();
}

void Popup::on_meta(const Meta& m) {
    model_.on_meta(m);
    refresh();
}

void Popup::on_config(const UiConfig& c) {
    config_ = c;
    model_.on_config(c);
    // The surface height follows max_lines and nothing else.
    const int h = popup_surface_h(c.max_lines);
    if (h != surface_h_) {
        surface_h_ = h;
        canvas_.queue_resize();
    }
    refresh();
}

void Popup::on_fade() {
    model_.on_fade(now_s());
    refresh();
}

void Popup::on_hide_msg() {
    model_.on_hide(now_s());
    refresh();
}

void Popup::on_warn(const Warn& w) {
    model_.on_warn(w.reason);
    refresh();
}

void Popup::set_anchor_x(double x) {
    if (!std::isfinite(x)) return;
    anchor_x_ = x;
    refresh();
}

void Popup::set_tokens(Tokens t) {
    tokens_ = t;
    rebuild_attrs(now_s());
    canvas_.queue_draw();
}

void Popup::set_reduced_motion(bool reduced) {
    reduced_ = reduced;
    refresh();
}

void Popup::set_clipping(bool clipping) {
    model_.set_clipping(clipping, now_s());
    refresh();
}

void Popup::set_output(const Glib::RefPtr<Gdk::Monitor>& monitor) {
    if (!monitor || monitor == monitor_) return;
    // A card on screen stays where it is; the next session moves.
    if (get_visible()) {
        pending_monitor_ = monitor;
        return;
    }
    pending_monitor_ = {};
    use_monitor(monitor);
}

// ---- state ------------------------------------------------------------------

void Popup::refresh() {
    const double now = now_s();
    model_.advance(now);
    const PopupPhase to = model_.phase();
    const bool fresh = std::exchange(restart_, false);
    if (fresh || to != phase_) on_phase(phase_, to, now);
    if (phase_ == PopupPhase::Hidden) return;

    if (highlight_ && now >= highlight_until_) highlight_.reset();
    update_text(now, fresh);

    FooterInput in = model_.footer(now);
    // [ui] footer = false keeps only a status (design.md "Preview popup").
    if (!config_.footer) {
        FooterInput only;
        only.status = std::move(in.status);
        in = std::move(only);
    }
    countdown_ = !in.elapsed.empty() && model_.countdown(now).has_value();
    footer_status_ = model_.status();
    update_geometry(now, fresh, in);

    schedule_deadline(now);
    ensure_tick();
    canvas_.queue_draw();
}

void Popup::on_phase(PopupPhase from, PopupPhase to, double now) {
    phase_ = to;
    if (to == PopupPhase::Hidden) {
        hide_now();
        return;
    }
    const bool was_hidden = from == PopupPhase::Hidden;
    if (was_hidden) {
        if (pending_monitor_) use_monitor(std::exchange(pending_monitor_, {}));
        if (!monitor_) use_monitor(first_monitor(get_display()));
        show_now();
        tl_[kAnimOpacity].jump(kNone);
        tl_[kAnimShift].jump(reduced_ ? kNone : kEnterShift);
    }
    if (to == PopupPhase::Entering || (was_hidden && to == PopupPhase::Shown)) {
        const Bezier e = reduced_ ? kLinear : kEnter;
        const int ms = motion_ms(kBase, reduced_);
        tl_[kAnimOpacity].to(kFull, ms, e, now);
        tl_[kAnimShift].to(kNone, ms, e, now);
    } else if (to == PopupPhase::Exiting) {
        const Bezier e = reduced_ ? kLinear : kExit;
        const int ms = motion_ms(kFadeOut, reduced_);
        tl_[kAnimOpacity].to(kNone, ms, e, now);
        if (!reduced_) tl_[kAnimShift].to(kExitShift, ms, e, now);
    }
}

void Popup::show_now() {
    if (why_not_ || get_visible()) return;
    if (backend_ == Backend::X11) {
        if (!x11_ready_) {
            if (!make_x11_overlay(*this, why_not_)) return;
            x11_ready_ = true;
        }
        // Placed before mapping, so it never flashes at the origin.
        apply_position();
        if (!show_x11_overlay(*this)) {
            why_not_ = "the X11 popup window failed its focus checks";
            return;
        }
        apply_position();
    } else {
        // Never present(): the surface must not ask for focus.
        set_visible(true);
    }
    apply_input_region();
}

void Popup::hide_now() {
    // Unmapped, not destroyed: the next show reuses the surface.
    if (get_visible()) set_visible(false);
    deadline_.disconnect();
    if (tick_id_) canvas_.remove_tick_callback(tick_id_);
    tick_id_ = 0;
    end_crossfade();
    highlight_.reset();
    tl_[kAnimHighlight].jump(kNone);
    tl_[kAnimOpacity].jump(kNone);
    // The next session may land elsewhere.
    if (pending_monitor_) use_monitor(std::exchange(pending_monitor_, {}));
}

// ---- text -------------------------------------------------------------------

void Popup::update_text(double now, bool fresh) {
    TextSpec next = text_spec(model_.content(), !reduced_);
    if (fresh) {
        shown_at_ = now;
        prev_w_ = 0;
        height_target_ = scroll_target_ = -1.0;
        footer_avail_ = -1;
        end_crossfade();
        highlight_.reset();
        spec_ = TextSpec{};
    }

    const bool changed = next != spec_ || fresh;
    if (changed) {
        // A swap still fading in survives later partials as long as the
        // polished run it belongs to is untouched; anything else ends it.
        const bool keep_fade = fade_ && !prev_text_ && next.polished == spec_.polished &&
                               next.text.compare(0, next.polished.end, spec_.text, 0,
                                                 spec_.polished.end) == 0;
        if (!keep_fade) end_crossfade();

        if (!fresh) {
            if (const auto f = crossfade(spec_, next)) {
                end_crossfade();
                fade_ = f;
                if (f->out == spec_.live) {
                    // Recording ended: the words stay put, so the old live run
                    // fades out on top while the pending restyle fades in.
                    prev_text_ = pango_layout_copy(text_);
                    prev_spec_ = spec_;
                    PangoAttrList* a = base_attrs();
                    color_attr(a, tokens_.text, {0, spec_.text.size()}, kNone);
                    color_attr(a, tokens_.live, spec_.live);
                    style_attr(a, pango_attr_style_new(PANGO_STYLE_ITALIC), spec_.live);
                    pango_layout_set_attributes(prev_text_, a);
                    pango_attr_list_unref(a);
                }
                tl_[kAnimCrossfade].jump(kNone);
                tl_[kAnimCrossfade].to(kFull, motion_ms(kFast, reduced_), kStandard, now);
            }
            if (const auto c = correction(spec_, next)) {
                highlight_ = c;
                highlight_until_ = now + kHighlightMs / kMsPerS;
                tl_[kAnimHighlight].jump(kFull);
                // Reduced motion: held at full, then removed at the deadline.
                if (!reduced_) tl_[kAnimHighlight].to(kNone, kHighlightMs, kStandard, now);
            }
        }
        spec_ = std::move(next);
        pango_layout_set_text(text_, spec_.text.c_str(), static_cast<int>(spec_.text.size()));
        dots_shown_ = -1;
    }
    // A highlight outside the polished run no longer marks anything.
    if (highlight_ && highlight_->end > spec_.polished.end) highlight_.reset();

    const int dots = spec_.dots.empty() ? -1 : listening_dots(now - shown_at_);
    if (dots != dots_shown_ || changed) {
        dots_shown_ = dots;
        rebuild_attrs(now);
    }
}

void Popup::rebuild_attrs(double now) {
    if (!text_) return;
    PangoAttrList* a = base_attrs();
    const ByteRange all{0, spec_.text.size()};
    const auto italic = [&a](ByteRange r) {
        if (!r.empty()) style_attr(a, pango_attr_style_new(PANGO_STYLE_ITALIC), r);
    };
    switch (spec_.kind) {
    case TextKind::Empty:
        break;
    case TextKind::Note:
        color_attr(a, tokens_.text2, all);
        break;
    case TextKind::Listening:
        color_attr(a, tokens_.text2, all);
        italic(all);
        // The dots fade in one by one; unshown dots keep their width, so
        // nothing reflows.
        for (std::size_t i = spec_.dots.begin; i < spec_.dots.end; ++i) {
            if (static_cast<int>(i - spec_.dots.begin) >= dots_shown_)
                color_attr(a, tokens_.text2, {i, i + 1}, kNone);
        }
        break;
    case TextKind::Zones:
        color_attr(a, tokens_.text, spec_.polished);
        color_attr(a, tokens_.pending, spec_.pending);
        color_attr(a, tokens_.live, spec_.live);
        italic(spec_.live);
        if (fade_) {
            const bool polished = fade_->in.begin >= spec_.polished.begin &&
                                  fade_->in.end <= spec_.polished.end;
            color_attr(a, polished ? tokens_.text : tokens_.pending, fade_->in,
                       tl_[kAnimCrossfade].value(now));
        }
        break;
    case TextKind::Struck:
        // design.md "States" 7: text-2 with a 1 px strike-through.
        color_attr(a, tokens_.text2, all);
        if (!all.empty()) style_attr(a, pango_attr_strikethrough_new(TRUE), all);
        break;
    }
    pango_layout_set_attributes(text_, a);
    pango_attr_list_unref(a);
}

void Popup::end_crossfade() {
    fade_.reset();
    if (prev_text_) g_object_unref(prev_text_);
    prev_text_ = nullptr;
    prev_spec_ = TextSpec{};
    tl_[kAnimCrossfade].jump(kFull);
}

// ---- geometry ---------------------------------------------------------------

void Popup::update_geometry(double now, bool fresh, const FooterInput& in) {
    const int out_w = output_width();
    const double cx = anchor_x_ >= 0.0 ? anchor_x_ : out_w / 2.0;
    footer_on_ = model_.footer_visible();

    // The width the content wants: the paragraph unwrapped plus the caret,
    // or the whole footer row, whichever is wider.
    pango_layout_set_width(text_, -1);
    text_natural_w_ = pixel_width(text_) + static_cast<int>(kCaretGap + kCaretW);
    int natural = text_natural_w_ + static_cast<int>(2 * kPadX);
    if (footer_on_) {
        const TextMeasure m = footer_measure();
        const int row = footer_width(compose_footer(in, INT_MAX, m), m);
        natural = std::max(natural, row + static_cast<int>(kFootPadL + kFootPadR));
    }

    // The surface follows the centre, not the card's width, so a card
    // growing mid-session never moves it; only a moved indicator does.
    const int left = popup_surface_left(out_w, cx);
    if (fresh || left != surface_left_) {
        surface_left_ = left;
        apply_position();
    }

    // Width first, since the line count depends on it.
    const int w = popup_card(out_w, cx, kPopupMinLines, footer_on_, prev_w_, natural).w;
    pango_layout_set_width(text_, std::max(1, w - static_cast<int>(2 * kPadX)) * PANGO_SCALE);
    text_lines_ = std::max(1, pango_layout_get_line_count(text_));
    const int max_lines = config_.max_lines;
    card_ = popup_card(out_w, cx, visible_lines(text_lines_, max_lines), footer_on_, prev_w_,
                       natural);
    prev_w_ = card_.w;
    if (prev_text_) pango_layout_set_width(prev_text_, pango_layout_get_width(text_));

    // Height over dur-slow (design.md "Pending -> polished swap"); the scroll
    // keeps the last line fully visible over dur-slow. Reduced motion jumps.
    const double h = card_.h;
    const double scroll = scrolled_lines(text_lines_, max_lines) * kPopupLineH;
    if (fresh || height_target_ < 0 || reduced_) tl_[kAnimHeight].jump(h);
    else if (h != height_target_) tl_[kAnimHeight].to(h, kSlow, kStandard, now);
    if (fresh || scroll_target_ < 0 || reduced_) tl_[kAnimScroll].jump(scroll);
    else if (scroll != scroll_target_) tl_[kAnimScroll].to(scroll, kSlow, kStandard, now);
    height_target_ = h;
    scroll_target_ = scroll;

    update_footer(in);
}

int Popup::output_width() const { return output_w_; }

void Popup::use_monitor(const Glib::RefPtr<Gdk::Monitor>& monitor) {
    if (!monitor) return;
    Gdk::Rectangle g;
    monitor->get_geometry(g);
    const bool resized = g.get_width() != output_w_;
    monitor_ = monitor;
    output_w_ = g.get_width();
    monitor_gone_.disconnect();
    // An unplugged output: fall back to whatever is left. With nothing left,
    // output_w_ keeps the old width, so a card on screen keeps its size
    // instead of collapsing to nothing until it fades.
    monitor_gone_ = monitor->signal_invalidate().connect([this] {
        auto m = first_monitor(get_display());
        if (m == monitor_) m = {};
        monitor_ = {};
        monitor_gone_.disconnect();
        if (m) use_monitor(m);
    });
    if (backend_ == Backend::Wayland && gtk_layer_is_layer_window(gobj()))
        gtk_layer_set_monitor(gobj(), monitor->gobj());
    if (resized) canvas_.queue_resize();
}

void Popup::apply_position() {
    // The same frame as the indicator's: margins count from the output's
    // left edge (on X11, its workarea's), in logical px of the output's
    // geometry width, which is also the frame of the anchor it reports.
    if (backend_ == Backend::Wayland) {
        if (gtk_layer_is_layer_window(gobj()))
            set_overlay_margins(*this, {.left = surface_left_, .bottom = kPopupSurfaceBottom});
    } else if (backend_ == Backend::X11 && x11_ready_ && get_realized() && monitor_) {
        place_x11_overlay(*this, monitor_, surface_left_, kPopupSurfaceBottom);
    }
}

void Popup::apply_input_region() {
    if (!get_realized()) return;
    // Click-through everywhere: the popup never takes input (design.md
    // "Preview popup").
    set_input_region(*this, {}, 0);
}

void Popup::on_canvas_allocated() {
    // X11 clamps the window inside the workarea by its size, so a resize
    // moves it again.
    if (backend_ == Backend::X11) apply_position();
    apply_input_region();
}

// ---- footer -----------------------------------------------------------------

PangoLayout* Popup::footer_layout(std::string_view text, bool tnum) {
    PangoLayout* l = label_layout(GTK_WIDGET(canvas_.gobj()), text, kLabelPx);
    if (tnum) {
        // design.md "Typography": tabular figures for every changing number.
        PangoAttrList* a = pango_attr_list_copy(pango_layout_get_attributes(l));
        if (!a) a = pango_attr_list_new();
        pango_attr_list_insert(a, pango_attr_font_features_new("tnum"));
        pango_layout_set_attributes(l, a);
        pango_attr_list_unref(a);
    }
    return l;
}

TextMeasure Popup::footer_measure() {
    return [this](FooterKind kind, std::string_view text) {
        const bool clock = kind == FooterKind::Elapsed;
        PangoLayout* l = clock ? measure_tnum_ : measure_;
        pango_layout_set_text(l, text.data(), static_cast<int>(text.size()));
        int w = pixel_width(l);
        if (clock && countdown_) w += static_cast<int>(kStatusIcon + kFooterEndGapPx);
        return w;
    };
}

void Popup::clear_footer() {
    for (FooterRun& r : footer_runs_)
        if (r.layout) g_object_unref(r.layout);
    footer_runs_.clear();
    sep_x_ = -1.0;
}

void Popup::update_footer(const FooterInput& in) {
    const int avail = card_.w - static_cast<int>(kFootPadL + kFootPadR);
    // Relaid out only when the row changed: the clock ticks once a second.
    if (in == footer_in_ && avail == footer_avail_) return;
    footer_in_ = in;
    footer_avail_ = avail;
    clear_footer();
    if (!footer_on_) {
        footer_avail_ = -1;  // so turning the footer on lays it out
        return;
    }

    const auto items = compose_footer(in, avail, footer_measure());
    const bool others = std::any_of(items.begin(), items.end(), [](const FooterItem& i) {
        return i.kind != FooterKind::Status;
    });

    // Left group: the chip and app id, or a status standing alone. End
    // group, right-aligned: elapsed · hint and a status beside the chip.
    std::vector<FooterRun> left, end;
    double left_w = 0.0, end_w = 0.0;
    const auto lead = [this](FooterKind k) -> double {
        switch (k) {
        case FooterKind::Mode:
            return kChipPadL + kChipIcon + kChipIconGap;
        case FooterKind::Status:
            return kStatusIconPx;
        case FooterKind::Elapsed:
            return countdown_ ? kStatusIcon + kFooterEndGapPx : 0.0;
        case FooterKind::App:
        case FooterKind::Hint:
            break;
        }
        return 0.0;
    };
    const auto trail = [](FooterKind k) { return k == FooterKind::Mode ? kChipPadR : 0.0f; };
    const auto gap_before = [](const std::vector<FooterRun>& g) {
        return g.empty() ? 0.0 : static_cast<double>(kFooterGapPx);
    };
    const int sep_w = pixel_width(sep_);
    // The same spacing footer_width counts, so what compose_footer kept fits.
    bool sep = false;
    const FooterItem* status = nullptr;
    for (std::size_t i = 0; i < items.size(); ++i) {
        const FooterItem& item = items[i];
        if (item.kind == FooterKind::Status) {
            status = &item;
            continue;
        }
        const bool is_end = item.kind == FooterKind::Elapsed || item.kind == FooterKind::Hint;
        auto& group = is_end ? end : left;
        double& gw = is_end ? end_w : left_w;
        PangoLayout* l = footer_layout(item.text, item.kind == FooterKind::Elapsed);
        const double w = pixel_width(l);
        if (footer_sep_before(items, i)) {
            sep = true;
            gw += kFooterEndGapPx + sep_w + kFooterEndGapPx;
        } else {
            gw += gap_before(group);
        }
        group.push_back({item.kind, l, gw + lead(item.kind), w});
        gw += lead(item.kind) + w + trail(item.kind);
    }
    if (status) {
        const bool alone = !others;
        auto& group = alone ? left : end;
        double& gw = alone ? left_w : end_w;
        gw += gap_before(group);
        PangoLayout* l = footer_layout(status->text, false);
        // Ellipsized into what the other items leave (design.md: "A status
        // message is ellipsized last").
        const double other = alone ? 0.0 : left_w + (left.empty() ? 0.0 : kFooterGapPx);
        const double room = std::max(0.0, avail - other - gw - kStatusIconPx);
        if (pixel_width(l) > room) {
            pango_layout_set_width(l, static_cast<int>(room * PANGO_SCALE));
            pango_layout_set_ellipsize(l, PANGO_ELLIPSIZE_END);
        }
        const double w = pixel_width(l);
        group.push_back({FooterKind::Status, l, gw + kStatusIconPx, w});
        gw += kStatusIconPx + w;
    }

    // Offsets so far are within each group; make them card-relative.
    const double end_x = card_.w - kFootPadR - end_w;
    for (FooterRun& r : left) r.x += kFootPadL;
    for (FooterRun& r : end) {
        if (r.kind == FooterKind::Hint && sep) sep_x_ = end_x + r.x - kFooterEndGapPx - sep_w;
        r.x += end_x;
    }
    footer_runs_ = std::move(left);
    footer_runs_.insert(footer_runs_.end(), end.begin(), end.end());
}

// ---- time -------------------------------------------------------------------

bool Popup::spinning() const {
    return !reduced_ && phase_ != PopupPhase::Hidden && footer_on_ && footer_status_ &&
           footer_status_->icon == Icon::LoaderCircle;
}

bool Popup::caret_blinks() const {
    return !reduced_ && spec_.kind == TextKind::Zones && !spec_.live.empty();
}

void Popup::schedule_deadline(double now) {
    deadline_.disconnect();
    std::optional<double> next = model_.next_deadline();
    const auto consider = [&next](double t) { next = next ? std::min(*next, t) : t; };
    // The next step of something counted from the show, period apart.
    const auto step = [now, this](double period) {
        return shown_at_ + (std::floor((now - shown_at_) / period) + 1.0) * period;
    };
    if (caret_blinks()) consider(step(kCaretOnS));
    if (!spec_.dots.empty()) consider(step(kListeningDotStepS));
    if (highlight_) consider(highlight_until_);
    if (!next) return;
    const double wait_ms = std::max(0.0, std::ceil((*next - now) * kMsPerS));
    deadline_ = Glib::signal_timeout().connect(
        [this] {
            refresh();
            return false;
        },
        static_cast<unsigned>(wait_ms));
}

bool Popup::needs_tick(double now) const {
    if (phase_ == PopupPhase::Hidden) return false;
    return tl_.any_running(now) || spinning();
}

void Popup::ensure_tick() {
    if (tick_id_ || !needs_tick(now_s())) return;
    tick_id_ = canvas_.add_tick_callback(sigc::mem_fun(*this, &Popup::on_tick));
}

bool Popup::on_tick(const Glib::RefPtr<Gdk::FrameClock>&) {
    const double now = now_s();
    if (fade_) {
        if (tl_[kAnimCrossfade].running(now)) {
            rebuild_attrs(now);
        } else {
            end_crossfade();
            rebuild_attrs(now);
        }
    }
    canvas_.queue_draw();
    if (needs_tick(now)) return true;
    // At rest: nothing wakes up until the next message or deadline.
    tick_id_ = 0;
    return false;
}

// ---- drawing ----------------------------------------------------------------

void Popup::draw(GtkSnapshot* s) { draw_at(s, now_s()); }

void Popup::draw_at(GtkSnapshot* s, double now) {
    if (phase_ == PopupPhase::Hidden) return;
    const double alpha = tl_[kAnimOpacity].value(now);
    if (alpha <= 0.0) return;

    const double h = tl_[kAnimHeight].value(now);
    const double bottom = surface_h_ - kPopupPad + tl_[kAnimShift].value(now);
    // card_.x counts from the output's left edge; the surface starts at
    // surface_left_.
    const graphene_rect_t card = rect(card_.x - surface_left_, bottom - h, card_.w, h);
    const double footer_h = footer_on_ ? kPopupFooterH : 0.0;
    const double text_h = h - 2 * kPopupPadY - footer_h;

    gtk_snapshot_push_opacity(s, alpha);
    draw_glass(s, card, kCardRadius, tokens_);
    const graphene_rect_t box =
        rect(card.origin.x + kPadX, card.origin.y + kPopupPadY, card_.w - 2 * kPadX, text_h);
    const graphene_rect_t clip = rect(card.origin.x, box.origin.y, card_.w, text_h);
    draw_text(s, box, clip, card.origin.y, now);
    draw_footer(s, card, now);
    gtk_snapshot_pop(s);
}

void Popup::draw_text(GtkSnapshot* s, graphene_rect_t box, graphene_rect_t clip, float card_top,
                      double now) {
    if (!text_ || clip.size.height <= 0) return;
    gtk_snapshot_push_clip(s, &clip);
    const double scroll = tl_[kAnimScroll].value(now);
    const bool masked = scroll > 0.0;
    if (masked) {
        // Text scrolled off the top fades out (design.md "Auto-scroll"). The
        // gradient covers the whole clip: outside the mask node is masked.
        gtk_snapshot_push_mask(s, GSK_MASK_MODE_ALPHA);
        const graphene_point_t from = GRAPHENE_POINT_INIT(clip.origin.x, card_top + kMaskClearY);
        const graphene_point_t to = GRAPHENE_POINT_INIT(clip.origin.x, card_top + kMaskOpaqueY);
        const std::array<GskColorStop, 2> stops{
            GskColorStop{0.0f, GdkRGBA{0, 0, 0, 0}},
            GskColorStop{1.0f, GdkRGBA{0, 0, 0, 1}},
        };
        gtk_snapshot_append_linear_gradient(s, &clip, &from, &to, stops.data(), stops.size());
        gtk_snapshot_pop(s);
    }

    gtk_snapshot_save(s);
    const graphene_point_t origin =
        GRAPHENE_POINT_INIT(box.origin.x, static_cast<float>(box.origin.y - scroll));
    gtk_snapshot_translate(s, &origin);

    // Under the words: the self-correction highlight.
    const double hl = tl_[kAnimHighlight].value(now);
    if (highlight_ && hl > 0.0) {
        const Rgba c = scaled(tokens_.primary_soft, hl);
        const auto piece = [&](double x0, double x1, double y0, double y1, double) {
            const double h = y1 - y0 - 2 * kHighlightInsetY;
            fill_rounded(s, rect(x0, y0 + kHighlightInsetY, x1 - x0, h), kHighlightRadius, c);
        };
        for_each_piece(text_, *highlight_, piece);
    }

    const GdkRGBA text_col = to_gdk(tokens_.text);
    gtk_snapshot_append_layout(s, text_, &text_col);
    if (prev_text_ && fade_) {
        gtk_snapshot_push_opacity(s, kFull - tl_[kAnimCrossfade].value(now));
        gtk_snapshot_append_layout(s, prev_text_, &text_col);
        gtk_snapshot_pop(s);
    }

    // Pango has no dotted underline, and its solid one sits too close.
    if (spec_.kind == TextKind::Zones) {
        const Rgba u = scaled(tokens_.text2, kUnderlineAlpha);
        const auto piece = [&](double x0, double x1, double, double, double base) {
            fill_rounded(s, rect(x0, base + kUnderlineOffset, x1 - x0, kUnderlinePx), 0, u);
        };
        for_each_piece(text_, spec_.pending, piece);
    }

    if (spec_.kind == TextKind::Zones && !spec_.live.empty()) {
        const bool on = reduced_ || std::fmod(now - shown_at_, kCaretPeriodS) < kCaretOnS;
        if (on) {
            PangoRectangle strong{};
            pango_layout_get_cursor_pos(text_, static_cast<int>(spec_.text.size()), &strong,
                                        nullptr);
            const double base = last_baseline(text_);
            fill_rounded(s,
                         rect(px(strong.x) + kCaretGap, base + kCaretDrop - kCaretH, kCaretW,
                              kCaretH),
                         0, tokens_.live);
        }
    }
    gtk_snapshot_restore(s);

    if (masked) gtk_snapshot_pop(s);
    gtk_snapshot_pop(s);
}

void Popup::draw_footer(GtkSnapshot* s, graphene_rect_t card, double now) {
    if (!footer_on_) return;
    const double x0 = card.origin.x;
    const double top = card.origin.y + card.size.height - kPopupFooterH;
    fill_rounded(s, rect(x0, top, card.size.width, kFootBorderPx), 0,
                 scaled(tokens_.text2, kFootBorderAlpha));
    const double cy = top + kFootPadTop + (kPopupFooterH - kFootPadTop) / 2.0;

    const auto tone = [this](Tone t) {
        switch (t) {
        case Tone::Primary:
            return tokens_.primary;
        case Tone::Warn:
            return tokens_.warn;
        case Tone::Danger:
            return tokens_.danger;
        case Tone::Info:
        case Tone::Muted:
            break;
        }
        return tokens_.text2;
    };

    for (const FooterRun& r : footer_runs_) {
        const double x = x0 + r.x;
        switch (r.kind) {
        case FooterKind::Mode: {
            const double chip_x = x - kChipIconGap - kChipIcon - kChipPadL;
            const double chip_w = kChipPadL + kChipIcon + kChipIconGap + r.w + kChipPadR;
            fill_rounded(s, rect(chip_x, cy - kChipH / 2, chip_w, kChipH), kChipRadius,
                         scaled(tokens_.text2, kChipAlpha));
            draw_icon(s, app_icon(footer_in_.mode), static_cast<float>(chip_x + kChipPadL),
                      static_cast<float>(cy - kChipIcon / 2), kChipIcon, tokens_.text);
            draw_line(s, r.layout, x, cy, tokens_.text);
            break;
        }
        case FooterKind::App:
        case FooterKind::Hint:
            draw_line(s, r.layout, x, cy, tokens_.text2);
            break;
        case FooterKind::Elapsed:
            if (countdown_) {
                // design.md "Recording": the countdown in warn, with a timer.
                draw_icon(s, Icon::Timer, static_cast<float>(x - kFooterEndGapPx - kStatusIcon),
                          static_cast<float>(cy - kStatusIcon / 2), kStatusIcon, tokens_.warn);
                draw_line(s, r.layout, x, cy, tokens_.warn);
            } else {
                draw_line(s, r.layout, x, cy, tokens_.text2);
            }
            break;
        case FooterKind::Status: {
            if (!footer_status_) break;
            const float ix = static_cast<float>(x - kStatusIconPx);
            const float iy = static_cast<float>(cy - kStatusIcon / 2);
            const Rgba c = tone(footer_status_->tone);
            if (spinning()) {
                gtk_snapshot_save(s);
                const graphene_point_t mid =
                    GRAPHENE_POINT_INIT(ix + kStatusIcon / 2, iy + kStatusIcon / 2);
                gtk_snapshot_translate(s, &mid);
                const double turn = std::fmod(now - shown_at_, kSpinPeriodS) / kSpinPeriodS;
                gtk_snapshot_rotate(s, static_cast<float>(turn * kFullTurnDeg));
                draw_icon(s, footer_status_->icon, -kStatusIcon / 2, -kStatusIcon / 2,
                          kStatusIcon, c);
                gtk_snapshot_restore(s);
            } else {
                draw_icon(s, footer_status_->icon, ix, iy, kStatusIcon, c);
            }
            // design.md: the message stays `text`; only the icon takes the tone.
            draw_line(s, r.layout, x, cy, tokens_.text);
            break;
        }
        }
    }
    if (sep_x_ >= 0.0) draw_line(s, sep_, x0 + sep_x_, cy, scaled(tokens_.text2, kSepAlpha));
}

}  // namespace flowd
