#pragma once

#include <array>
#include <optional>

// Pure placement geometry for the indicator and the popup, in logical pixels.
// No GTK here, so all of it is unit-tested.
namespace flowd {

// design.md "Indicator" → Dragging: more than 4 px of movement is a drag.
constexpr double kDragThresholdPx = 4.0;
// design.md "Indicator" → Dragging: snap points and their magnetic ranges.
constexpr std::array<double, 3> kSnapPoints = {0.25, 0.5, 0.75};
constexpr double kSnapCenter = 0.5;
constexpr double kSnapRangePx = 8.0;
constexpr double kSnapCenterRangePx = 12.0;
// design.md "Indicator" → Dragging: the pill is clamped 16 px from the output edges.
constexpr double kEdgeClampPx = 16.0;
// design.md "Indicator placement": the stored fraction defaults to 0.5.
constexpr double kDefaultFraction = 0.5;

// design.md "Indicator" → Anatomy: the expanded pill.
constexpr int kPillW = 120;
constexpr int kPillH = 36;
// design.md "Indicator" → Idle: the idle line.
constexpr int kIdleLineW = 48;
constexpr int kIdleLineH = 8;
// design.md "Elevation" → GTK caveat: shadow padding inside each surface.
constexpr int kSurfacePad = 12;
constexpr int kPopupPad = 24;
// design.md "Indicator placement": bottom margin from the output edge.
constexpr int kIndicatorBottom = 6;

// design.md "Popup placement": width is min(640, out - 32), shrinking to 280.
constexpr int kPopupMaxW = 640;
constexpr int kPopupMinW = 280;
// design.md "Popup placement": the card stays >= 16 px inside the output edges.
constexpr int kPopupEdge = 16;
// design.md "Popup placement": 6 px margin + 36 px pill + 10 px gap.
constexpr int kCardBottomAboveEdge = 52;
// design.md "Preview popup": 14 px padding top and bottom, 22 px lines, 28 px footer.
constexpr int kPopupPadY = 14;
constexpr int kPopupLineH = 22;
constexpr int kPopupFooterH = 28;

// True when a pointer move of (dx, dy) is a drag rather than a click.
bool is_drag(double dx, double dy);

struct Snap {
    double x;                     // the pill centre to use
    std::optional<double> point;  // the snap fraction, when within range
};

// Clamps the pill centre inside the output, then snaps it to the nearest
// snap point when within that point's (inclusive) range.
Snap snap_center(double center_x, int output_width);

// Converts between a pill centre and the stored fraction of output width.
// Both clamp the centre inside the output.
double to_fraction(double center_x, int output_width);
double from_fraction(double f, int output_width);

// The LEFT anchor margin for a fixed-size surface centred on center_x.
int indicator_left_margin(double center_x, int surface_w);

// The popup card. x is the left edge from the output's left edge. y is the
// distance from the output's BOTTOM edge to the card's bottom edge (the
// bottom margin of a BOTTOM-anchored surface), not a top-down coordinate.
struct CardRect {
    int x, y, w, h;
};

// prev_w is the width already shown this session (0 at the start), so the
// card only grows; natural_w is the width the content wants.
CardRect popup_card(int output_w, double center_x, int lines, bool footer, int prev_w, int natural_w);

}  // namespace flowd
