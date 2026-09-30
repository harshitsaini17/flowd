#include "app.hpp"

#include <fcntl.h>
#include <glib-unix.h>
#include <gtk/gtk.h>
#include <gtkmm/version.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <type_traits>
#include <utility>

#include "fonts.hpp"
#include "indicator.hpp"
#include "popup.hpp"
#include "surface.hpp"

namespace flowd {

namespace {

constexpr const char* kLogPrefix = "flowd-ui: ";
constexpr int kStdin = 0;
constexpr int kStdout = 1;
// One read() per chunk; a wake reads at most this many before yielding to
// drawing, so a burst of level messages cannot starve a frame.
constexpr std::size_t kReadChunk = 64 * 1024;
constexpr int kMaxReadsPerWake = 16;
// Events are a few dozen bytes; this much unread means the daemon has
// stopped reading, and further events are dropped rather than queued.
constexpr std::size_t kMaxPendingOut = 64 * 1024;
// At exit, how long the last events (an `unsupported`, say) may wait for a
// full pipe to drain before they are given up.
constexpr int kFinalFlushMs = 200;

// Sets O_NONBLOCK on fd and returns the flags it had, or nothing on failure.
std::optional<int> make_nonblocking(int fd) {
    const int flags = fcntl(fd, F_GETFL);
    if (flags < 0) return std::nullopt;
    if (!(flags & O_NONBLOCK) && fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) return std::nullopt;
    return flags;
}

void restore_flags(int fd, std::optional<int>& flags) {
    if (!flags) return;
    // Best effort: the process is leaving, and a failure changes nothing for it.
    if (fcntl(fd, F_SETFL, *flags) < 0) log_line(std::string("could not restore file flags: ") +
                                                  std::strerror(errno));
    flags.reset();
}

std::string errno_text(const char* what) { return std::string(what) + ": " + std::strerror(errno); }

// The desktop's light / dark preference, or nothing when it states none, so
// resolve_dark() applies design.md's dark fallback. GTK >= 4.20 fills
// gtk-interface-color-scheme from the portal's color-scheme by itself.
std::optional<bool> system_prefers_dark(const Glib::RefPtr<Gtk::Settings>& s) {
    if (!s) return std::nullopt;
#if GTKMM_CHECK_VERSION(4, 20, 0)
    switch (s->property_gtk_interface_color_scheme().get_value()) {
    case Gtk::InterfaceColorScheme::DARK:
        return true;
    case Gtk::InterfaceColorScheme::LIGHT:
        return false;
    default:
        break;
    }
#endif
    // Only a true is a statement: false is also what an unset key reads as.
    if (s->property_gtk_application_prefer_dark_theme().get_value()) return true;
    return std::nullopt;
}

bool high_contrast(const Glib::RefPtr<Gtk::Settings>& s) {
#if GTKMM_CHECK_VERSION(4, 20, 0)
    return s && s->property_gtk_interface_contrast().get_value() == Gtk::InterfaceContrast::MORE;
#else
    (void)s;
    return false;
#endif
}

}  // namespace

std::optional<LogLevel> parse_log_level(std::string_view s) {
    if (s == "error") return LogLevel::Error;
    if (s == "warn" || s == "warning") return LogLevel::Warn;
    if (s == "info") return LogLevel::Info;
    if (s == "debug") return LogLevel::Debug;
    return std::nullopt;
}

void log_line(std::string_view msg) { std::cerr << kLogPrefix << msg << '\n'; }

void write_all_blocking(std::string_view line) {
    while (!line.empty()) {
        const ssize_t n = write(kStdout, line.data(), line.size());
        if (n < 0) {
            if (errno == EINTR) continue;
            // EPIPE included: nobody is listening, so there is no one to tell.
            log_line(errno_text("could not write to stdout"));
            return;
        }
        line.remove_prefix(static_cast<std::size_t>(n));
    }
}

App::App(Backend backend, LogLevel level)
    : level_(level), backend_(backend), store_(default_position_file()) {
    // No application id and NON_UNIQUE: the daemon supervises the one
    // instance, so there is nothing to register on the session bus.
    app_ = Gtk::Application::create({}, Gio::Application::Flags::NON_UNIQUE);
    app_->signal_activate().connect(sigc::mem_fun(*this, &App::on_activate));
}

App::~App() {
    // The windows go before the application and the loop they belong to.
    popup_.reset();
    indicator_.reset();
    for (auto& c : settings_watch_) c.disconnect();
    // They hold this.
    for (guint id : signal_sources_) g_source_remove(id);
    stdin_watch_.disconnect();
    stdout_watch_.disconnect();
    restore_flags(kStdin, stdin_flags_);
    restore_flags(kStdout, stdout_flags_);
}

int App::run() {
    // Nothing is added to the application, so it is held open instead; only
    // quit() or the end of stdin ends the loop.
    app_->hold();
    // Before the loop starts, so a stop during GTK init or activation still
    // ends the loop cleanly and the file flags are restored.
    for (int sig : {SIGTERM, SIGINT}) {
        signal_sources_.push_back(g_unix_signal_add(
            sig,
            [](gpointer self) -> gboolean {
                static_cast<App*>(self)->quit(kExitOk);
                // Kept, so the destructor's g_source_remove stays valid.
                return G_SOURCE_CONTINUE;
            },
            this));
    }
    const int rc = app_->run();
    popup_.reset();
    indicator_.reset();

    // Give whatever the daemon has not taken yet a moment to go out.
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(kFinalFlushMs);
    while (!out_.empty() && !stdout_dead_) {
        const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(
                              deadline - std::chrono::steady_clock::now())
                              .count();
        if (left <= 0) break;
        pollfd p{kStdout, POLLOUT, 0};
        if (poll(&p, 1, static_cast<int>(left)) <= 0) break;
        flush_stdout();
    }
    restore_flags(kStdin, stdin_flags_);
    restore_flags(kStdout, stdout_flags_);
    if (rc != 0 && exit_code_ == kExitOk) return kExitError;
    return exit_code_;
}

void App::log(LogLevel level, std::string_view msg) const {
    if (level <= level_) log_line(msg);
}

void App::quit(int code) {
    if (quitting_) return;
    quitting_ = true;
    // An unsupported exit stays one, whatever ends the loop after it.
    if (exit_code_ != kExitUnsupported) exit_code_ = code;
    stdin_watch_.disconnect();
    app_->quit();
}

void App::unsupported(const std::string& why) {
    // Set first: if the event meets a dead stdout, the EPIPE quit keeps it.
    if (!quitting_) exit_code_ = kExitUnsupported;
    log(LogLevel::Error, "disabled: " + why);
    emit(encode_unsupported(why));
    quit(kExitUnsupported);
}

// ---- startup ----------------------------------------------------------------

void App::on_activate() {
    setup_stdout();
    if (quitting_) return;

    // The environment allowed backend_; the open display now decides.
    if (auto why = display_mismatch(backend_)) return unsupported(*why);
    // gtk4-layer-shell asserts on a non-Wayland display, so X11 never asks.
    const bool layer_shell = backend_ == Backend::Wayland && layer_shell_supported();
    const Decision d = choose_backend(read_env(), layer_shell);
    if (d.backend == Backend::Unsupported) return unsupported(d.reason);
    if (d.backend != backend_)
        return unsupported("the display backend changed after start: " + d.reason);
    log(LogLevel::Info, "backend: " + d.reason);

    if (auto dir = bundled_fonts_dir())
        register_fonts(*dir);
    else
        log(LogLevel::Warn, "no bundled fonts found; using the system's");

    settings_ = Gtk::Settings::get_default();
    watch_settings();

    if (!setup_stdin()) return;

    // At idle priority, so a config already waiting on stdin is usually read
    // before the indicator appears. The daemon sends config first, but if it
    // arrives later an `indicator = false` still destroys the indicator.
    Glib::signal_idle().connect_once([this] {
        if (!quitting_ && config_.indicator) ensure_indicator();
    });
}

// ---- stdin ------------------------------------------------------------------

bool App::setup_stdin() {
    stdin_flags_ = make_nonblocking(kStdin);
    if (!stdin_flags_) {
        log(LogLevel::Error, errno_text("could not make stdin non-blocking"));
        quit(kExitError);
        return false;
    }
    read_buf_.resize(kReadChunk);
    stdin_watch_ = Glib::signal_io().connect(
        sigc::mem_fun(*this, &App::on_stdin), kStdin,
        Glib::IOCondition::IO_IN | Glib::IOCondition::IO_HUP | Glib::IOCondition::IO_ERR);
    return true;
}

bool App::on_stdin(Glib::IOCondition cond) {
    // HUP can arrive with data still buffered, so read until EOF either way.
    if ((cond & (Glib::IOCondition::IO_IN | Glib::IOCondition::IO_HUP)) ==
        Glib::IOCondition{}) {
        log(LogLevel::Error, "stdin failed");
        quit(kExitError);
        return false;
    }
    for (int i = 0; i < kMaxReadsPerWake; ++i) {
        const ssize_t n = read(kStdin, read_buf_.data(), read_buf_.size());
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) return true;
            log(LogLevel::Error, errno_text("could not read stdin"));
            quit(kExitError);
            return false;
        }
        if (n == 0) {
            log(LogLevel::Info, "stdin closed");
            quit(kExitOk);
            return false;
        }
        const bool more = lines_.feed(
            std::string_view(read_buf_.data(), static_cast<std::size_t>(n)),
            [this](std::string_view line) { return on_line(line); },
            [this] {
                log(LogLevel::Warn, "dropped an input line longer than " +
                                        std::to_string(kMaxLineBytes) + " bytes");
            });
        if (!more || quitting_) return false;
    }
    return true;
}

bool App::on_line(std::string_view line) {
    if (quitting_) return false;
    if (auto m = parse_message(line)) {
        dispatch(*m);
    } else if (!line.empty()) {
        // Unknown types are ignored both ways (ADR 0013).
        log(LogLevel::Debug, "ignored: " + std::string(line.substr(0, 200)));
    }
    return !quitting_;
}

void App::dispatch(const Message& m) {
    std::visit(
        [this](const auto& msg) {
            using T = std::decay_t<decltype(msg)>;
            if constexpr (std::is_same_v<T, ConfigMsg>) {
                apply_config(msg.ui);
            } else if constexpr (std::is_same_v<T, StateMsg>) {
                last_state_ = msg.state;
                if (indicator_) indicator_->on_state(msg.state);
                if (popup_) popup_->on_state(msg);
            } else if constexpr (std::is_same_v<T, Level>) {
                if (indicator_) indicator_->on_level(msg);
            } else if constexpr (std::is_same_v<T, Meta>) {
                meta_ = msg;
                if (popup_) popup_->on_meta(msg);
            } else if constexpr (std::is_same_v<T, Warn>) {
                warn_ = msg;
                if (indicator_) indicator_->on_warn(msg);
                // design.md "Warning": while recording the footer carries it.
                if (popup_) popup_->on_warn(msg);
            } else if constexpr (std::is_same_v<T, Show>) {
                ensure_popup();
                if (!popup_) return;
                if (indicator_) {
                    // Set while hidden, so the new card lands on the
                    // indicator's output, centred on it.
                    popup_->set_output(indicator_->monitor());
                    popup_->set_anchor_x(indicator_->center_x());
                }
                popup_->on_show();
            } else if constexpr (std::is_same_v<T, Render>) {
                if (!popup_) return;
                if (indicator_) popup_->set_anchor_x(indicator_->center_x());
                popup_->on_render(msg);
            } else if constexpr (std::is_same_v<T, Fade>) {
                if (popup_) popup_->on_fade();
            } else if constexpr (std::is_same_v<T, Hide>) {
                if (popup_) popup_->on_hide();
            } else if constexpr (std::is_same_v<T, Quit>) {
                log(LogLevel::Info, "quit received");
                quit(kExitOk);
            }
        },
        m);
}

// ---- stdout -----------------------------------------------------------------

void App::setup_stdout() {
    // A daemon that stops reading must never freeze the UI mid-draw, so
    // writes are non-blocking and queue behind a writable watch.
    stdout_flags_ = make_nonblocking(kStdout);
    if (!stdout_flags_) {
        log(LogLevel::Error, errno_text("could not make stdout non-blocking"));
        quit(kExitError);
    }
}

void App::emit(std::string_view event) {
    if (stdout_dead_) return;
    if (out_.size() + event.size() > kMaxPendingOut) {
        if (!warned_out_full_) {
            log(LogLevel::Warn, "the daemon is not reading events; dropping them");
            warned_out_full_ = true;
        }
        return;
    }
    out_.append(event);
    if (!stdout_watch_.connected()) flush_stdout();
}

bool App::flush_stdout() {
    while (!out_.empty()) {
        const ssize_t n = write(kStdout, out_.data(), out_.size());
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                if (!stdout_watch_.connected() && !quitting_)
                    stdout_watch_ = Glib::signal_io().connect(
                        sigc::mem_fun(*this, &App::on_stdout_writable), kStdout,
                        Glib::IOCondition::IO_OUT | Glib::IOCondition::IO_ERR |
                            Glib::IOCondition::IO_HUP);
                return false;
            }
            stdout_dead_ = true;
            out_.clear();
            stdout_watch_.disconnect();
            if (errno == EPIPE) {
                // SIGPIPE is ignored, so a gone daemon shows up here instead.
                log(LogLevel::Info, "stdout closed");
                quit(kExitOk);
            } else {
                log(LogLevel::Error, errno_text("could not write to stdout"));
                quit(kExitError);
            }
            return false;
        }
        out_.erase(0, static_cast<std::size_t>(n));
    }
    warned_out_full_ = false;
    stdout_watch_.disconnect();
    return true;
}

bool App::on_stdout_writable(Glib::IOCondition) {
    // flush_stdout disconnects the watch itself once drained or dead; on
    // EAGAIN it keeps it, so this only says whether to stay connected.
    flush_stdout();
    return stdout_watch_.connected() && !out_.empty();
}

// ---- windows ----------------------------------------------------------------

void App::ensure_indicator() {
    if (indicator_) return;
    auto ind = std::make_unique<Indicator>(
        backend_, store_, current_tokens(), reduced_motion(),
        [this] { emit(encode_click()); },
        [this](double fraction, std::string output) { emit(encode_moved(fraction, output)); });
    ind->set_on_clipping([this](bool clipping) {
        if (popup_) popup_->set_clipping(clipping);
    });
    ind->on_config(config_);
    if (!ind->start()) {
        const std::string why = ind->why_not().value_or("the indicator surface failed its checks");
        // ADR 0003: a surface that might take focus is never shown.
        return unsupported(why);
    }
    // Catch it up with what the daemon already said.
    if (last_state_) ind->on_state(*last_state_);
    if (warn_) ind->on_warn(*warn_);
    indicator_ = std::move(ind);
    if (popup_) popup_->set_output(indicator_->monitor());
}

void App::ensure_popup() {
    if (popup_ || quitting_) return;
    auto p = std::make_unique<Popup>(backend_, current_tokens(), reduced_motion());
    if (p->why_not()) return unsupported(*p->why_not());
    p->on_config(config_);
    p->on_meta(meta_);
    if (warn_) p->on_warn(*warn_);
    popup_ = std::move(p);
}

void App::apply_config(const UiConfig& c) {
    const bool theme_changed = c.theme != config_.theme;
    config_ = c;
    if (!c.indicator && indicator_) {
        // Destroyed, not just hidden: nothing to draw means nothing to hold.
        indicator_.reset();
        if (popup_) popup_->set_clipping(false);
    } else if (indicator_) {
        indicator_->on_config(c);
    } else if (c.indicator && settings_) {
        // settings_ is set once activation got past its checks.
        ensure_indicator();
    }
    if (popup_) popup_->on_config(c);
    if (theme_changed) retheme();
}

// ---- desktop settings -------------------------------------------------------

void App::watch_settings() {
    if (!settings_) return;
    const auto changed = [this] { retheme(); };
    settings_watch_.push_back(
        settings_->property_gtk_application_prefer_dark_theme().signal_changed().connect(changed));
    settings_watch_.push_back(
        settings_->property_gtk_enable_animations().signal_changed().connect(changed));
#if GTKMM_CHECK_VERSION(4, 20, 0)
    settings_watch_.push_back(
        settings_->property_gtk_interface_color_scheme().signal_changed().connect(changed));
    settings_watch_.push_back(
        settings_->property_gtk_interface_contrast().signal_changed().connect(changed));
#endif
#if GTKMM_CHECK_VERSION(4, 22, 0)
    settings_watch_.push_back(
        settings_->property_gtk_interface_reduced_motion().signal_changed().connect(changed));
#endif
}

Tokens App::current_tokens() const {
    return tokens(resolve_dark(config_.theme, system_prefers_dark(settings_)),
                  high_contrast(settings_));
}

bool App::reduced_motion() const {
    if (!settings_) return false;
#if GTKMM_CHECK_VERSION(4, 22, 0)
    if (settings_->property_gtk_interface_reduced_motion().get_value() ==
        Gtk::ReducedMotion::REDUCE)
        return true;
#endif
    return !settings_->property_gtk_enable_animations().get_value();
}

void App::retheme() {
    const Tokens t = current_tokens();
    const bool reduced = reduced_motion();
    if (indicator_) {
        indicator_->set_tokens(t);
        indicator_->set_reduced_motion(reduced);
    }
    if (popup_) {
        popup_->set_tokens(t);
        popup_->set_reduced_motion(reduced);
    }
}

}  // namespace flowd
