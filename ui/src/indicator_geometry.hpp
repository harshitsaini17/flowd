#pragma once

#include <optional>

#include "indicator_model.hpp"
#include "placement.hpp"

// Where the pill sits inside the indicator surface, and which part of the
// surface takes pointer input, in logical px. No GTK here, so it is
// unit-tested; the widget only draws and hit-tests what this says.
namespace flowd {

// design.md "Indicator" → Warning: the widened pill is at most 360 px.
constexpr int kWarnPillMaxW = 360;
// The surface is the pill plus kSurfacePad of shadow room on the left, right
// and top. The pill's bottom edge sits kIndicatorBottom above the surface's
// bottom edge, which is anchored on the output edge with no margin.
constexpr int kSurfaceW = kPillW + 2 * kSurfacePad;
constexpr int kWarnSurfaceW = kWarnPillMaxW + 2 * kSurfacePad;
constexpr int kSurfaceH = kSurfacePad + kPillH + kIndicatorBottom;
// design.md "Indicator placement": the idle hit area, centred on the idle line.
constexpr int kStripW = 120;
constexpr int kStripH = 20;

// design.md "Indicator" → Anatomy / Warning: the pill's fixed parts, left to
// right: 4 px inset, the 28 px button, an 8 px gap, the 14 px triangle-alert
// and another gap (not when the mic itself is the problem: mic-off takes the
// button instead), the reason, then 14 px of right padding.
constexpr int kButtonInset = 4;
constexpr int kButtonD = 28;
constexpr int kContentGap = 8;
constexpr int kWarnIconSize = 14;
constexpr int kWarnPadRight = 14;

struct PillRect {
    double x, y, w, h;
};

// The surface width: wide while the warning pill is shown or still collapsing.
int indicator_surface_w(bool wide);

// The surface's left edge on an output out_w wide (0 when unknown), for a
// pill centred on center_x. It is kept on the output, since a wide surface
// near an edge would otherwise hang off it.
int indicator_surface_left(double center_x, int surface_w, int out_w);

// The pill centre inside the surface. A pill wider than the clamp allows at
// center_x shifts inward so it stays kEdgeClampPx inside the output.
double pill_center_in_surface(double center_x, double pill_w, int surface_left, int out_w);

// The widest reason text that fits, and the pill width for a reason text_w
// px wide.
double warn_text_max_w(bool blocking);
double warn_pill_w(double text_w, bool blocking);

// The input rectangle for region, relative to the content inside the
// surface's padding (set_input_region adds the pad back). Nothing for Empty.
std::optional<PillRect> input_rect(InputRegion region, double pill_w, double pill_cx_in_surface);

// Where a drag puts the pill. Pointer events arrive relative to the surface
// as it was placed when the compositor generated them, and a margin change
// takes effect only when the frame carrying it lands. Moving the surface by
// the requested margin at once would read in-flight events against the wrong
// origin and make the pill race ahead of the pointer, so the origin used for
// events (the baseline) advances only once the frame with the new margin has
// been presented.
class DragAnchor {
public:
    // A press at surface-relative offsets, with the pill centred on center_x
    // and the surface's left edge at surface_left on the output.
    void begin(double center_x, int surface_left);
    // The pill centre for a drag offset dx (the gesture's, in surface
    // coordinates), before snapping.
    double center_for(double dx) const;
    // The pointer's movement on the output for a drag offset dx.
    double output_dx(double dx) const;
    // A frame carrying surface_left has been committed.
    void committed(int surface_left);
    // The next frame has started, so the committed one was presented: events
    // from now on are relative to it.
    void presented();
    int baseline() const { return baseline_; }
    double press_center() const { return press_center_; }

private:
    double press_center_ = 0.0;
    int press_left_ = 0;
    int baseline_ = 0;
    std::optional<int> committed_;
};

}  // namespace flowd
