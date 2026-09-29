#pragma once

#include <gdkmm/display.h>
#include <gdkmm/monitor.h>
#include <glibmm/main.h>

#include <functional>
#include <string>
#include <string_view>

#include "output_events.hpp"

// Follows the focused output and fullscreen state on Hyprland and Sway, so
// the indicator can move to the output being worked on and hide over
// fullscreen clients (design.md "Indicator on-screen rules"). Best effort:
// elsewhere, or after any failure, it reports nothing and the indicator
// stays where it is.
namespace flowd {

class OutputTracker {
public:
    struct Callbacks {
        std::function<void(const std::string& connector)> on_output;
        std::function<void(bool fullscreen)> on_fullscreen;
    };

    explicit OutputTracker(Callbacks cb);
    ~OutputTracker();
    OutputTracker(const OutputTracker&) = delete;
    OutputTracker& operator=(const OutputTracker&) = delete;

    // Reports the current state, then follows changes. Returns false when
    // this compositor is not followed or setup failed (logged once).
    bool start();

private:
    bool start_hyprland();
    bool start_sway();
    bool on_hypr_readable(Glib::IOCondition cond);
    bool on_sway_readable(Glib::IOCondition cond);
    void handle_hypr_line(std::string_view line);
    void recheck_hypr_fullscreen();
    void report_output(const std::string& name);
    void report_fullscreen(bool fs);
    void fail(const std::string& why);
    void stop();

    Callbacks cb_;
    std::string hypr_query_path_;
    int fd_ = -1;              // socket2 on Hyprland, swaymsg's stdout on Sway
    int sway_pid_ = 0;         // the swaymsg child, reaped by a child watch
    sigc::connection io_;
    std::string line_buf_;     // Hyprland: bytes after the last newline
    JsonObjectSplitter sway_split_;  // Sway: swaymsg's event stream
    std::string last_output_;  // so repeated focus lines report nothing new
    int last_fullscreen_ = -1; // -1 unknown, 0 no, 1 yes
    bool failed_ = false;      // logged once; no further reports
};

// The monitor on display whose connector is name, or null.
Glib::RefPtr<Gdk::Monitor> find_monitor(const Glib::RefPtr<Gdk::Display>& display,
                                        std::string_view name);

// The display's first monitor, or null: the fallback when nothing better is
// known (Wayland has no primary output).
Glib::RefPtr<Gdk::Monitor> first_monitor(const Glib::RefPtr<Gdk::Display>& display);

}  // namespace flowd
