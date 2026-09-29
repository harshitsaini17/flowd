#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>

// Parsing for the compositor events that move and hide the indicator
// (design.md "Indicator on-screen rules"): the focused output and whether a
// fullscreen client is focused. No GTK or I/O here, so it is unit-tested.
namespace flowd {

struct OutputEvent {
    std::optional<std::string> focused_output;  // a connector name, e.g. "eDP-1"
    std::optional<bool> fullscreen;
    // Focus moved to another workspace or output, which Hyprland does not
    // follow with a fullscreen>> line; the caller asks again.
    bool recheck_fullscreen = false;
};

// One line from Hyprland's .socket2.sock: "focusedmon>>NAME,WORKSPACE",
// "fullscreen>>0|1" or "workspace>>NAME". Anything else is nothing.
std::optional<OutputEvent> parse_hypr_line(std::string_view line);

// One compact JSON event from `swaymsg -r -m -t subscribe '["window","workspace"]'`:
// a workspace "focus" names its output; a window "focus" or
// "fullscreen_mode" says whether that window is fullscreen.
std::optional<OutputEvent> parse_sway_event(std::string_view json);

// The focused output's name from `hyprctl -j monitors` or `swaymsg -r -t
// get_outputs` (both are arrays of objects with "name" and "focused").
std::optional<std::string> focused_output_from_json(std::string_view json);

// Whether `hyprctl -j activewindow` reports a fullscreen window.
std::optional<bool> fullscreen_from_hypr_activewindow(std::string_view json);

// Splits a byte stream into top-level JSON objects, whatever their line
// breaks: swaymsg may print each event compact or pretty. Bytes outside an
// object are skipped. A single object larger than kMaxJsonObject is dropped,
// so a stuck stream cannot grow the buffer without bound.
constexpr std::size_t kMaxJsonObject = 1 << 20;

class JsonObjectSplitter {
public:
    // Appends data and calls on_object for each object it completes.
    template <typename F>
    void feed(std::string_view data, F&& on_object) {
        for (char c : data) {
            if (step(c)) {
                on_object(std::string_view(buf_));
                buf_.clear();
            }
        }
    }

private:
    // Returns true when c closes a top-level object held in buf_.
    bool step(char c);

    std::string buf_;
    int depth_ = 0;
    bool in_string_ = false;
    bool escaped_ = false;
};

}  // namespace flowd
