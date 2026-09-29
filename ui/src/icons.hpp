#pragma once

#include <span>
#include <string_view>

// Lucide icons as SVG path data in the 24-unit viewBox, drawn by the GTK side
// with gsk_path_parse and a 1.75 stroke, round caps and joins (design.md
// "Shapes" → Icons). Plain strings, so they live in the GTK-free core.
namespace flowd {

// The icons flowd-ui draws: footer statuses (design.md "Preview popup" →
// States), the indicator's states, and the footer's mode chip.
enum class Icon {
    Check,
    Info,
    X,
    MicOff,
    CircleAlert,
    Timer,
    LoaderCircle,
    TriangleAlert,
    Mic,
    GripVertical,
    GripHorizontal,
    FileText,
    Code,
    MessageSquare,
    Mail,
    AppWindow,
    Count_,  // not an icon: the number of icons, for iterating
};

// One stroked subpath. Lucide's circle, rect and line elements are
// pre-converted to paths, so every element is drawn the same way.
struct IconElement {
    std::string_view path;
};

// The icon's elements; empty only for Count_ or an out-of-range value.
std::span<const IconElement> icon(Icon i);

// The mode chip's icon (design.md "Apps & modes"): default → file-text,
// code → code, chat → message-square, email → mail, anything else →
// app-window.
Icon app_icon(std::string_view mode);

}  // namespace flowd
