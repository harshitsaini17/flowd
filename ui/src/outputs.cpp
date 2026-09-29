#include "outputs.hpp"

#include <giomm/listmodel.h>
#include <glibmm/spawn.h>
#include <gio/gio.h>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <optional>
#include <vector>

#include "output_events.hpp"

namespace flowd {

namespace {

constexpr const char* kLogPrefix = "flowd-ui: ";
// Hyprland's IPC sockets, under $XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE.
constexpr const char* kHyprEvents = ".socket2.sock";
constexpr const char* kHyprQueries = ".socket.sock";
constexpr const char* kHyprMonitors = "j/monitors";
constexpr const char* kHyprActiveWindow = "j/activewindow";
// A read chunk; events are short lines.
constexpr std::size_t kReadChunk = 4096;
// Hyprland lines are well under this; a longer one is garbage and dropped.
constexpr std::size_t kMaxLine = 64 * 1024;
// A query answer (all monitors as JSON) stays far below this.
constexpr std::size_t kMaxQueryReply = 1 << 20;

void log_error(const std::string& msg) { std::cerr << kLogPrefix << msg << '\n'; }

std::optional<std::string> env(const char* name) {
    const char* v = std::getenv(name);
    if (!v || !*v) return std::nullopt;
    return std::string(v);
}

std::optional<std::filesystem::path> hypr_dir() {
    const auto sig = env("HYPRLAND_INSTANCE_SIGNATURE");
    const auto run = env("XDG_RUNTIME_DIR");
    if (!sig || !run) return std::nullopt;
    return std::filesystem::path(*run) / "hypr" / *sig;
}

// A connected, close-on-exec Unix stream socket, or -1 with errno set.
int connect_unix(const std::string& path) {
    sockaddr_un addr{};
    if (path.size() >= sizeof(addr.sun_path)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    addr.sun_family = AF_UNIX;
    std::memcpy(addr.sun_path, path.c_str(), path.size() + 1);
    if (connect(fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) != 0) {
        const int saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    return fd;
}

// One Hyprland request: write it, read the whole reply. Blocking, but it is
// a local socket answered at once, and only asked at start and on focus
// changes, never per frame.
std::optional<std::string> hypr_query(const std::string& socket_path, std::string_view request) {
    const int fd = connect_unix(socket_path);
    if (fd < 0) return std::nullopt;
    std::optional<std::string> reply;
    if (write(fd, request.data(), request.size()) == static_cast<ssize_t>(request.size())) {
        std::string out;
        std::array<char, kReadChunk> buf{};
        for (;;) {
            const ssize_t n = read(fd, buf.data(), buf.size());
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            out.append(buf.data(), static_cast<std::size_t>(n));
            if (out.size() > kMaxQueryReply) break;
        }
        reply = std::move(out);
    }
    close(fd);
    return reply;
}

bool set_nonblocking(int fd) {
    const int flags = fcntl(fd, F_GETFL);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

}  // namespace

OutputTracker::OutputTracker(Callbacks cb) : cb_(std::move(cb)) {}

OutputTracker::~OutputTracker() { stop(); }

void OutputTracker::stop() {
    io_.disconnect();
    if (fd_ >= 0) close(fd_);
    fd_ = -1;
    if (sway_pid_ > 0) {
        // The child watch reaps it; swaymsg dies on SIGTERM or on the closed pipe.
        kill(sway_pid_, SIGTERM);
        sway_pid_ = 0;
    }
}

void OutputTracker::fail(const std::string& why) {
    if (!failed_) log_error("not following outputs: " + why + "; the indicator stays put");
    failed_ = true;
    stop();
}

bool OutputTracker::start() {
    if (hypr_dir()) return start_hyprland();
    if (env("SWAYSOCK")) return start_sway();
    return false;  // other desktops: stay on the first monitor, silently
}

void OutputTracker::report_output(const std::string& name) {
    if (failed_ || name.empty() || name == last_output_) return;
    last_output_ = name;
    if (cb_.on_output) cb_.on_output(name);
}

void OutputTracker::report_fullscreen(bool fs) {
    if (failed_ || last_fullscreen_ == int(fs)) return;
    last_fullscreen_ = int(fs);
    if (cb_.on_fullscreen) cb_.on_fullscreen(fs);
}

// ---- Hyprland ---------------------------------------------------------------

bool OutputTracker::start_hyprland() {
    const auto dir = hypr_dir();
    const std::string events = (*dir / kHyprEvents).string();
    hypr_query_path_ = (*dir / kHyprQueries).string();

    fd_ = connect_unix(events);
    if (fd_ < 0) {
        fail("cannot connect to " + events + ": " + std::strerror(errno));
        return false;
    }
    if (!set_nonblocking(fd_)) {
        fail(std::string("cannot make the Hyprland event socket non-blocking: ") +
             std::strerror(errno));
        return false;
    }
    io_ = Glib::signal_io().connect(sigc::mem_fun(*this, &OutputTracker::on_hypr_readable), fd_,
                                    Glib::IOCondition::IO_IN | Glib::IOCondition::IO_HUP |
                                        Glib::IOCondition::IO_ERR);

    if (const auto mons = hypr_query(hypr_query_path_, kHyprMonitors)) {
        if (const auto name = focused_output_from_json(*mons)) report_output(*name);
    }
    recheck_hypr_fullscreen();
    return true;
}

void OutputTracker::recheck_hypr_fullscreen() {
    const auto win = hypr_query(hypr_query_path_, kHyprActiveWindow);
    if (!win) return;
    // No active window ({}) means nothing covers the output.
    report_fullscreen(fullscreen_from_hypr_activewindow(*win).value_or(false));
}

void OutputTracker::handle_hypr_line(std::string_view line) {
    const auto e = parse_hypr_line(line);
    if (!e) return;
    if (e->focused_output) report_output(*e->focused_output);
    if (e->fullscreen) report_fullscreen(*e->fullscreen);
    if (e->recheck_fullscreen) recheck_hypr_fullscreen();
}

bool OutputTracker::on_hypr_readable(Glib::IOCondition cond) {
    std::array<char, kReadChunk> buf{};
    for (;;) {
        const ssize_t n = read(fd_, buf.data(), buf.size());
        if (n > 0) {
            line_buf_.append(buf.data(), static_cast<std::size_t>(n));
            std::size_t start = 0;
            for (std::size_t nl; (nl = line_buf_.find('\n', start)) != std::string::npos;
                 start = nl + 1)
                handle_hypr_line(std::string_view(line_buf_).substr(start, nl - start));
            line_buf_.erase(0, start);
            if (line_buf_.size() > kMaxLine) line_buf_.clear();
            if (failed_) return false;
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        // EOF or a hard error: Hyprland went away.
        fail(n == 0 ? "the Hyprland event socket closed"
                    : std::string("reading Hyprland events: ") + std::strerror(errno));
        return false;
    }
    if ((cond & (Glib::IOCondition::IO_HUP | Glib::IOCondition::IO_ERR)) !=
        Glib::IOCondition{}) {
        fail("the Hyprland event socket hung up");
        return false;
    }
    return true;
}

// ---- Sway -------------------------------------------------------------------

bool OutputTracker::start_sway() {
    // The focused output right away; later changes come from the subscription.
    try {
        std::string out;
        int status = 0;
        Glib::spawn_sync("", std::vector<std::string>{"swaymsg", "-r", "-t", "get_outputs"},
                         Glib::SpawnFlags::SEARCH_PATH | Glib::SpawnFlags::STDERR_TO_DEV_NULL,
                         {}, &out, nullptr, &status);
        if (const auto name = focused_output_from_json(out)) report_output(*name);
    } catch (const Glib::Error& e) {
        fail("swaymsg get_outputs failed: " + std::string(e.what()));
        return false;
    }

    int out_fd = -1;
    Glib::Pid pid{};
    try {
        Glib::spawn_async_with_pipes(
            "",
            std::vector<std::string>{"swaymsg", "-r", "-m", "-t", "subscribe",
                                     R"(["window","workspace"])"},
            Glib::SpawnFlags::SEARCH_PATH | Glib::SpawnFlags::DO_NOT_REAP_CHILD |
                Glib::SpawnFlags::STDERR_TO_DEV_NULL,
            {}, &pid, nullptr, &out_fd, nullptr);
    } catch (const Glib::Error& e) {
        fail("cannot run swaymsg: " + std::string(e.what()));
        return false;
    }
    sway_pid_ = pid;
    // Reaps the child whenever it exits, so it never lingers as a zombie.
    g_child_watch_add(pid, [](GPid p, gint, gpointer) { g_spawn_close_pid(p); }, nullptr);
    fd_ = out_fd;
    if (!set_nonblocking(fd_)) {
        fail(std::string("cannot make the swaymsg pipe non-blocking: ") + std::strerror(errno));
        return false;
    }
    io_ = Glib::signal_io().connect(sigc::mem_fun(*this, &OutputTracker::on_sway_readable), fd_,
                                    Glib::IOCondition::IO_IN | Glib::IOCondition::IO_HUP |
                                        Glib::IOCondition::IO_ERR);
    return true;
}

bool OutputTracker::on_sway_readable(Glib::IOCondition cond) {
    std::array<char, kReadChunk> buf{};
    for (;;) {
        const ssize_t n = read(fd_, buf.data(), buf.size());
        if (n > 0) {
            sway_split_.feed(std::string_view(buf.data(), static_cast<std::size_t>(n)),
                       [this](std::string_view obj) {
                           const auto e = parse_sway_event(obj);
                           if (!e) return;
                           if (e->focused_output) report_output(*e->focused_output);
                           if (e->fullscreen) report_fullscreen(*e->fullscreen);
                       });
            if (failed_) return false;
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        sway_pid_ = 0;  // it exited; the child watch reaps it
        fail(n == 0 ? "swaymsg exited" : std::string("reading swaymsg: ") + std::strerror(errno));
        return false;
    }
    if ((cond & (Glib::IOCondition::IO_HUP | Glib::IOCondition::IO_ERR)) !=
        Glib::IOCondition{}) {
        sway_pid_ = 0;
        fail("swaymsg hung up");
        return false;
    }
    return true;
}

// ---- monitors ---------------------------------------------------------------

Glib::RefPtr<Gdk::Monitor> find_monitor(const Glib::RefPtr<Gdk::Display>& display,
                                        std::string_view name) {
    if (!display) return {};
    auto list = display->get_monitors();
    for (guint i = 0; i < list->get_n_items(); ++i) {
        auto m = std::dynamic_pointer_cast<Gdk::Monitor>(list->get_object(i));
        if (m && m->get_connector() == Glib::ustring(std::string(name))) return m;
    }
    return {};
}

Glib::RefPtr<Gdk::Monitor> first_monitor(const Glib::RefPtr<Gdk::Display>& display) {
    if (!display) return {};
    auto list = display->get_monitors();
    if (list->get_n_items() == 0) return {};
    return std::dynamic_pointer_cast<Gdk::Monitor>(list->get_object(0));
}

}  // namespace flowd
