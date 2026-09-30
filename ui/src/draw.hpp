#pragma once

#include <gtk/gtk.h>

#include <string_view>

#include "icons.hpp"
#include "theme.hpp"

// Snapshot helpers shared by the indicator and the popup: the glass material,
// rounded fills, Lucide icons and Inter text layouts. Everything here only
// appends render nodes; nothing allocates per frame except the nodes GTK
// itself builds.
namespace flowd {

// design.md "Shapes" → Icons: Lucide's 24-unit viewBox, 1.75 stroke.
constexpr float kIconViewBox = 24.0f;
constexpr float kIconStroke = 1.75f;
// design.md "Typography" → label: 13 px, +0.02em tracking.
constexpr int kLabelPx = 13;
constexpr double kLabelTrackingEm = 0.02;

// Makes every flowd window's background transparent, so only what the widgets
// draw shows; the rest of each surface is shadow room. Installs once per
// process, on the default display.
void install_window_css();

GdkRGBA to_gdk(const Rgba& c, double alpha_scale = 1.0);

// design.md "Glass material": the glass fill, a 1 px inner edge in `border`,
// and in dark mode a 1 px black-50% outer edge, over shadow-float. High
// contrast drops the shadow (design.md "Elevation & Depth"): the
// border-strong edge carries the separation instead.
void draw_glass(GtkSnapshot* s, graphene_rect_t r, float radius, const Tokens& t);

// A filled rounded rectangle; radius is clamped to half the shorter side.
void fill_rounded(GtkSnapshot* s, graphene_rect_t r, float radius, Rgba c);

// Strokes icon i into the size x size square at (x, y). Paths are parsed once
// and kept for the life of the process.
void draw_icon(GtkSnapshot* s, Icon i, float x, float y, float size, Rgba c);

// A new layout for text in Inter at size_px, weight 400 (design.md
// "Typography": one weight), with no tracking and no attributes. The caller
// owns it (g_object_unref).
PangoLayout* text_layout(GtkWidget* w, std::string_view text, int size_px);

// A new layout for text in Inter at size_px, weight 400 (design.md
// "Typography": one weight), with the label tracking. The caller owns it
// (g_object_unref).
PangoLayout* label_layout(GtkWidget* w, std::string_view text, int size_px);

}  // namespace flowd
