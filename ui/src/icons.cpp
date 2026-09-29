// Lucide icons, https://lucide.dev (lucide-static 1.48.0, the same copies as
// docs/design/assets/icons.js). Circles, rects and lines are rewritten as
// equivalent paths; the path data is otherwise unchanged.
//
// ISC License
//
// Copyright (c) 2026 Lucide Icons and Contributors
//
// Permission to use, copy, modify, and/or distribute this software for any
// purpose with or without fee is hereby granted, provided that the above
// copyright notice and this permission notice appear in all copies.
//
// THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
// WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
// MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
// ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
// WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
// ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
// OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
//
// ---
//
// The following Lucide icons are derived from the Feather project:
//
// airplay, alert-circle, alert-octagon, alert-triangle, aperture, arrow-down-circle, arrow-down-left, arrow-down-right, arrow-down, arrow-left-circle, arrow-left, arrow-right-circle, arrow-right, arrow-up-circle, arrow-up-left, arrow-up-right, arrow-up, at-sign, calendar, cast, check, chevron-down, chevron-left, chevron-right, chevron-up, chevrons-down, chevrons-left, chevrons-right, chevrons-up, circle, clipboard, clock, code, columns, command, compass, corner-down-left, corner-down-right, corner-left-down, corner-left-up, corner-right-down, corner-right-up, corner-up-left, corner-up-right, crosshair, database, divide-circle, divide-square, dollar-sign, download, external-link, feather, frown, hash, headphones, help-circle, info, italic, key, layout, life-buoy, link-2, link, loader, lock, log-in, log-out, maximize, meh, minimize, minimize-2, minus-circle, minus-square, minus, monitor, moon, more-horizontal, more-vertical, move, music, navigation-2, navigation, octagon, pause-circle, percent, plus-circle, plus-square, plus, power, radio, rss, search, server, share, shopping-bag, sidebar, smartphone, smile, square, table-2, tablet, target, terminal, trash-2, trash, triangle, tv, type, upload, x-circle, x-octagon, x-square, x, zoom-in, zoom-out
//
// The MIT License (MIT) (for the icons listed above)
//
// Copyright (c) 2013-present Cole Bemis
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

#include "icons.hpp"

#include <array>
#include <cstddef>

namespace flowd {

namespace {

// Conversions, so each element is one subpath:
//   circle cx,cy r   -> M cx-r cy a r r 0 1 0 2r 0 a r r 0 1 0 -2r 0
//   rect with rx     -> the rounded-rect outline, clockwise from the top edge
//   line x1,y1 x2,y2 -> M x1 y1 L x2 y2
constexpr std::array kCheck{IconElement{"M20 6 9 17l-5-5"}};
constexpr std::array kInfo{
    IconElement{"M2 12a10 10 0 1 0 20 0a10 10 0 1 0 -20 0"},
    IconElement{"M12 16v-4"},
    IconElement{"M12 8h.01"},
};
constexpr std::array kX{IconElement{"M18 6 6 18"}, IconElement{"m6 6 12 12"}};
constexpr std::array kMicOff{
    IconElement{"M12 19v3"},
    IconElement{"M15 9.34V5a3 3 0 0 0-5.68-1.33"},
    IconElement{"M16.95 16.95A7 7 0 0 1 5 12v-2"},
    IconElement{"M18.89 13.23A7 7 0 0 0 19 12v-2"},
    IconElement{"m2 2 20 20"},
    IconElement{"M9 9v3a3 3 0 0 0 5.12 2.12"},
};
constexpr std::array kCircleAlert{
    IconElement{"M2 12a10 10 0 1 0 20 0a10 10 0 1 0 -20 0"},
    IconElement{"M12 8L12 12"},
    IconElement{"M12 16L12.01 16"},
};
constexpr std::array kTimer{
    IconElement{"M10 2L14 2"},
    IconElement{"M12 14L15 11"},
    IconElement{"M4 14a8 8 0 1 0 16 0a8 8 0 1 0 -16 0"},
};
constexpr std::array kLoaderCircle{IconElement{"M21 12a9 9 0 1 1-6.219-8.56"}};
constexpr std::array kTriangleAlert{
    IconElement{"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"},
    IconElement{"M12 9v4"},
    IconElement{"M12 17h.01"},
};
constexpr std::array kMic{
    IconElement{"M12 19v3"},
    IconElement{"M19 10v2a7 7 0 0 1-14 0v-2"},
    // rect x=9 y=2 6x13 rx=3: the straight top and bottom runs are zero-length.
    IconElement{"M12 2h0a3 3 0 0 1 3 3v7a3 3 0 0 1 -3 3h0a3 3 0 0 1 -3 -3v-7a3 3 0 0 1 3 -3z"},
};
constexpr std::array kGripVertical{
    IconElement{"M8 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M8 5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M8 19a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M14 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M14 5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M14 19a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
};
constexpr std::array kGripHorizontal{
    IconElement{"M11 9a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M18 9a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M4 9a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M11 15a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M18 15a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
    IconElement{"M4 15a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"},
};
constexpr std::array kFileText{
    IconElement{"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"},
    IconElement{"M14 2v5a1 1 0 0 0 1 1h5"},
    IconElement{"M10 9H8"},
    IconElement{"M16 13H8"},
    IconElement{"M16 17H8"},
};
constexpr std::array kCode{IconElement{"m16 18 6-6-6-6"}, IconElement{"m8 6-6 6 6 6"}};
constexpr std::array kMessageSquare{IconElement{
    "M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"}};
constexpr std::array kMail{
    IconElement{"m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"},
    IconElement{"M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-16a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2z"},
};
constexpr std::array kAppWindow{
    IconElement{"M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-16a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2z"},
    IconElement{"M10 4v4"},
    IconElement{"M2 8h20"},
    IconElement{"M6 4v4"},
};

}  // namespace

std::span<const IconElement> icon(Icon i) {
    switch (i) {
    case Icon::Check: return kCheck;
    case Icon::Info: return kInfo;
    case Icon::X: return kX;
    case Icon::MicOff: return kMicOff;
    case Icon::CircleAlert: return kCircleAlert;
    case Icon::Timer: return kTimer;
    case Icon::LoaderCircle: return kLoaderCircle;
    case Icon::TriangleAlert: return kTriangleAlert;
    case Icon::Mic: return kMic;
    case Icon::GripVertical: return kGripVertical;
    case Icon::GripHorizontal: return kGripHorizontal;
    case Icon::FileText: return kFileText;
    case Icon::Code: return kCode;
    case Icon::MessageSquare: return kMessageSquare;
    case Icon::Mail: return kMail;
    case Icon::AppWindow: return kAppWindow;
    case Icon::Count_: break;
    }
    return {};
}

Icon app_icon(std::string_view mode) {
    if (mode == "default") return Icon::FileText;
    if (mode == "code") return Icon::Code;
    if (mode == "chat") return Icon::MessageSquare;
    if (mode == "email") return Icon::Mail;
    return Icon::AppWindow;
}

}  // namespace flowd
