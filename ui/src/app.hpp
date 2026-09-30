#pragma once

#include <gtkmm/application.h>
#include <gtkmm/settings.h>

#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "backend.hpp"
#include "line_splitter.hpp"
#include "position_store.hpp"
#include "protocol.hpp"
#include "theme.hpp"

// The flowd-ui program: reads the daemon's JSON lines on stdin, drives the
// indicator and the popup, and writes click / moved / unsupported events on
// stdout (ADR 0013). Everything runs on the GLib main loop; neither stream is
// ever read or written in a way that can stall a frame.
namespace flowd {

class Indicator;
class Popup;

// Exit codes the daemon sees (ADR 0013).
constexpr int kExitOk = 0;           // quit received, or stdin closed
constexpr int kExitError = 1;        // anything unexpected
constexpr int kExitUnsupported = 3;  // no focus-free surface here; do not respawn

enum class LogLevel { Error, Warn, Info, Debug };

// "error", "warn" (or "warning"), "info", "debug"; nothing for anything else.
std::optional<LogLevel> parse_log_level(std::string_view s);

// Writes "flowd-ui: <msg>" to stderr, which the daemon forwards to the journal.
void log_line(std::string_view msg);

// Writes line to stdout in full, blocking. Only for before the main loop runs,
// where there is nothing else to keep responsive.
void write_all_blocking(std::string_view line);

class App {
public:
    // backend is the choice made from the environment before GTK init; it is
    // decided again once the display is open and layer-shell can be asked.
    App(Backend backend, LogLevel level);
    ~App();
    App(const App&) = delete;
    App& operator=(const App&) = delete;

    // Runs the main loop and returns the exit code.
    int run();

private:
    void on_activate();
    // Emits `unsupported`, logs why and ends the loop with kExitUnsupported.
    void unsupported(const std::string& why);
    void quit(int code);
    void log(LogLevel level, std::string_view msg) const;

    // stdin.
    bool setup_stdin();
    bool on_stdin(Glib::IOCondition cond);
    bool on_line(std::string_view line);
    void dispatch(const Message& m);

    // stdout.
    void setup_stdout();
    void emit(std::string_view event);
    bool flush_stdout();
    bool on_stdout_writable(Glib::IOCondition cond);

    // Windows.
    void ensure_indicator();
    void ensure_popup();
    void apply_config(const UiConfig& c);

    // Desktop settings.
    void watch_settings();
    Tokens current_tokens() const;
    bool reduced_motion() const;
    void retheme();

    LogLevel level_;
    Backend backend_;
    int exit_code_ = kExitOk;
    bool quitting_ = false;
    Glib::RefPtr<Gtk::Application> app_;
    Glib::RefPtr<Gtk::Settings> settings_;
    std::vector<sigc::connection> settings_watch_;
    std::vector<guint> signal_sources_;  // SIGTERM / SIGINT handlers

    // The file flags stdin and stdout had, restored at exit so a terminal
    // is not left non-blocking for the shell.
    std::optional<int> stdin_flags_, stdout_flags_;
    sigc::connection stdin_watch_;
    std::vector<char> read_buf_;
    LineSplitter lines_;

    std::string out_;  // event bytes stdout could not take yet
    sigc::connection stdout_watch_;
    bool stdout_dead_ = false;
    bool warned_out_full_ = false;

    UiConfig config_{};
    Meta meta_{};
    std::optional<Warn> warn_;
    std::optional<UiState> last_state_;  // replayed into a new indicator
    PositionStore store_;
    std::unique_ptr<Indicator> indicator_;
    std::unique_ptr<Popup> popup_;
};

}  // namespace flowd
