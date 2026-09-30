#include "draw.hpp"

#include <gdkmm/display.h>
#include <gtkmm/cssprovider.h>
#include <gtkmm/styleprovider.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace flowd {

namespace {

// design.md "Typography": Inter, then the same fallbacks as --font-sans.
constexpr const char* kFontFamily = "Inter,InterVariable,Cantarell,Noto Sans,sans-serif";
constexpr int kRegularWeight = 400;
// design.md "Glass material": 1 px edges; dark mode's outer edge is black 50%.
constexpr float kEdgePx = 1.0f;
constexpr Rgba kDarkOuterEdge{0.0, 0.0, 0.0, 0.5};
constexpr const char* kWindowCss = "window { background: none; }";

GskRoundedRect rounded(graphene_rect_t r, float radius) {
    GskRoundedRect rr;
    const float max_r = std::min(r.size.width, r.size.height) / 2.0f;
    gsk_rounded_rect_init_from_rect(&rr, &r, std::clamp(radius, 0.0f, max_r));
    return rr;
}

// One parsed path per icon element, built on first use. Parsing allocates,
// and icons are drawn every frame while the spinner turns.
const std::vector<GskPath*>& icon_paths(Icon i) {
    static std::array<std::vector<GskPath*>, static_cast<std::size_t>(Icon::Count_)> cache;
    static std::array<bool, static_cast<std::size_t>(Icon::Count_)> parsed{};
    static const std::vector<GskPath*> kNone;
    const auto idx = static_cast<std::size_t>(i);
    if (idx >= cache.size()) return kNone;
    if (!parsed[idx]) {
        parsed[idx] = true;
        for (const auto& e : icon(i)) {
            // gsk_path_parse needs a NUL-terminated string.
            if (GskPath* p = gsk_path_parse(std::string(e.path).c_str())) cache[idx].push_back(p);
        }
    }
    return cache[idx];
}

}  // namespace

void install_window_css() {
    static bool done = false;
    if (done) return;
    auto display = Gdk::Display::get_default();
    if (!display) return;
    done = true;
    auto css = Gtk::CssProvider::create();
    css->load_from_string(kWindowCss);
    Gtk::StyleProvider::add_provider_for_display(display, css,
                                                 GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
}

GdkRGBA to_gdk(const Rgba& c, double alpha_scale) {
    return GdkRGBA{static_cast<float>(c.r), static_cast<float>(c.g), static_cast<float>(c.b),
                   static_cast<float>(std::clamp(c.a * alpha_scale, 0.0, 1.0))};
}

void fill_rounded(GtkSnapshot* s, graphene_rect_t r, float radius, Rgba c) {
    const GskRoundedRect rr = rounded(r, radius);
    const GdkRGBA col = to_gdk(c);
    gtk_snapshot_push_rounded_clip(s, &rr);
    gtk_snapshot_append_color(s, &col, &r);
    gtk_snapshot_pop(s);
}

void draw_glass(GtkSnapshot* s, graphene_rect_t r, float radius, const Tokens& t) {
    const GskRoundedRect outline = rounded(r, radius);
    if (!t.high_contrast) {
        for (const Shadow& sh : t.shadow) {
            const GdkRGBA c = to_gdk(sh.color);
            gtk_snapshot_append_outset_shadow(s, &outline, &c, static_cast<float>(sh.dx),
                                              static_cast<float>(sh.dy),
                                              static_cast<float>(sh.spread),
                                              static_cast<float>(sh.blur));
        }
    }
    if (t.dark_edge) {
        // A spread-only outset shadow is exactly a ring outside the outline.
        const GdkRGBA c = to_gdk(kDarkOuterEdge);
        gtk_snapshot_append_outset_shadow(s, &outline, &c, 0, 0, kEdgePx, 0);
    }
    fill_rounded(s, r, radius, t.glass);
    const std::array<float, 4> widths{kEdgePx, kEdgePx, kEdgePx, kEdgePx};
    const GdkRGBA e = to_gdk(t.border);
    const std::array<GdkRGBA, 4> colors{e, e, e, e};
    gtk_snapshot_append_border(s, &outline, widths.data(), colors.data());
}

void draw_icon(GtkSnapshot* s, Icon i, float x, float y, float size, Rgba c) {
    const auto& paths = icon_paths(i);
    if (paths.empty() || size <= 0) return;
    const GdkRGBA col = to_gdk(c);
    GskStroke* stroke = gsk_stroke_new(kIconStroke);
    gsk_stroke_set_line_cap(stroke, GSK_LINE_CAP_ROUND);
    gsk_stroke_set_line_join(stroke, GSK_LINE_JOIN_ROUND);
    gtk_snapshot_save(s);
    const graphene_point_t origin = GRAPHENE_POINT_INIT(x, y);
    gtk_snapshot_translate(s, &origin);
    const float k = size / kIconViewBox;
    // The stroke is scaled with the path, so it stays 1.75 in viewBox units
    // as Lucide's own SVGs do.
    gtk_snapshot_scale(s, k, k);
    for (GskPath* p : paths) gtk_snapshot_append_stroke(s, p, stroke, &col);
    gtk_snapshot_restore(s);
    gsk_stroke_free(stroke);
}

PangoLayout* text_layout(GtkWidget* w, std::string_view text, int size_px) {
    const std::string str(text);
    PangoLayout* layout = gtk_widget_create_pango_layout(w, str.c_str());
    PangoFontDescription* fd = pango_font_description_from_string(kFontFamily);
    pango_font_description_set_weight(fd, static_cast<PangoWeight>(kRegularWeight));
    pango_font_description_set_absolute_size(fd, size_px * PANGO_SCALE);
    pango_layout_set_font_description(layout, fd);
    pango_font_description_free(fd);
    return layout;
}

PangoLayout* label_layout(GtkWidget* w, std::string_view text, int size_px) {
    PangoLayout* layout = text_layout(w, text, size_px);

    PangoAttrList* attrs = pango_attr_list_new();
    pango_attr_list_insert(attrs, pango_attr_letter_spacing_new(static_cast<int>(
                                      kLabelTrackingEm * size_px * PANGO_SCALE)));
    pango_layout_set_attributes(layout, attrs);
    pango_attr_list_unref(attrs);
    pango_layout_set_single_paragraph_mode(layout, TRUE);
    return layout;
}

}  // namespace flowd
