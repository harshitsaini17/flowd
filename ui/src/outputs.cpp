#include "outputs.hpp"

#include <giomm/listmodel.h>
#include <glibmm/spawn.h>
#include <gio/gio.h>

#include <fcntl.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <optional>
#include <utility>
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
// Queries run on the main loop, so a stuck compositor must not freeze the
// indicator: each send or receive gives up after this long.
constexpr int kQueryTimeoutMs = 200;
constexpr int kUsPerMs = 1000;

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
bool set_timeouts(int fd) {
    timeval tv{};
    tv.tv_sec = kQueryTimeoutMs / 1000;
    tv.tv_usec = (kQueryTimeoutMs % 1000) * kUsPerMs;
    return setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) == 0 &&
           setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)) == 0;
}

std::optional<std::string> hypr_query(const std::string& socket_path, std::string_view request) {
    const int fd = connect_unix(socket_path);
    if (fd < 0) return std::nullopt;
    std::optional<std::string> reply;
    // MSG_NOSIGNAL: a compositor that hung up must not kill us with SIGPIPE.
    if (set_timeouts(fd) &&
        send(fd, request.data(), request.size(), MSG_NOSIGNAL) ==
            static_cast<ssize_t>(request.size())) {
        std::string out;
        std::array<char, kReadChunk> buf{};
        for (;;) {
            const ssize_t n = recv(fd, buf.data(), buf.size(), 0);
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

OutputTracker::OutputTracker(Callbacks cb) : cb_(std::move(cb)) { shared_->self = this; }

OutputTracker::~OutputTracker() {
    stop();
    shared_->alive = false;
    shared_->self = nullptr;
}

void OutputTracker::stop() {
    io_.disconnect();
    if (fd_ >= 0) close(fd_);
    fd_ = -1;
    if (sway_pid_ > 0 && !shared_->exited) {
        // The child watch reaps it; swaymsg dies on SIGTERM or on the closed
        // pipe. Once it has exited its pid may be reused, so it is left alone.
        kill(sway_pid_, SIGTERM);
    }
    sway_pid_ = 0;
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
    const int v = static_cast<int>(fs);
    if (failed_ || last_fullscreen_ == v) return;
    last_fullscreen_ = v;
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

namespace {

// One async swaymsg query in flight: the subprocess and where its reply goes.
struct SwayQuery {
    std::function<void(std::string)> deliver;  // a no-op once the tracker is gone
};

void on_sway_query_done(GObject* source, GAsyncResult* res, gpointer data) {
    std::unique_ptr<SwayQuery> q(static_cast<SwayQuery*>(data));
    char* out = nullptr;
    GError* err = nullptr;
    const bool ok = g_subprocess_communicate_utf8_finish(G_SUBPROCESS(source), res, &out, nullptr,
                                                         &err);
    std::string reply = ok && out ? out : "";
    g_free(out);
    if (err) g_error_free(err);
    g_object_unref(source);
    // A failed query leaves the last known state; the next event asks again.
    if (ok) q->deliver(std::move(reply));
}

}  // namespace

void OutputTracker::sway_query(const char* type,
                               std::function<void(OutputTracker&, std::string)> on_reply) {
    const char* argv[] = {"swaymsg", "-r", "-t", type, nullptr};
    GError* err = nullptr;
    GSubprocess* proc = g_subprocess_newv(
        argv, static_cast<GSubprocessFlags>(G_SUBPROCESS_FLAGS_STDOUT_PIPE |
                                            G_SUBPROCESS_FLAGS_STDERR_SILENCE),
        &err);
    if (!proc) {
        const std::string why = err ? err->message : "unknown error";
        if (err) g_error_free(err);
        fail(std::string("cannot run swaymsg ") + type + ": " + why);
        return;
    }
    std::weak_ptr<Shared> weak = shared_;
    auto* q = new SwayQuery{[weak, on_reply](std::string reply) {
        const auto sh = weak.lock();
        if (sh && sh->alive && sh->self) on_reply(*sh->self, std::move(reply));
    }};
    g_subprocess_communicate_utf8_async(proc, nullptr, nullptr, on_sway_query_done, q);
}

bool OutputTracker::start_sway() {
    // The focused output as soon as swaymsg answers; later changes come from
    // the subscription. Asynchronous, so a slow Sway never blocks startup.
    sway_query("get_outputs", [](OutputTracker& t, std::string out) {
        if (const auto name = focused_output_from_json(out)) t.report_output(*name);
    });
    recheck_sway_fullscreen();
    if (failed_) return false;

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
    // Reaps the child whenever it exits, so it never lingers as a zombie, and
    // records that it did, so stop() never signals a reused pid.
    g_child_watch_add_full(
        G_PRIORITY_DEFAULT, pid,
        [](GPid p, gint, gpointer data) {
            static_cast<std::shared_ptr<Shared>*>(data)->get()->exited = true;
            g_spawn_close_pid(p);
        },
        new std::shared_ptr<Shared>(shared_),
        [](gpointer data) { delete static_cast<std::shared_ptr<Shared>*>(data); });
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

void OutputTracker::recheck_sway_fullscreen() {
    // One get_tree at a time; requests meanwhile collapse into one more.
    if (sway_tree_busy_) {
        sway_tree_again_ = true;
        return;
    }
    sway_tree_busy_ = true;
    sway_query("get_tree", [](OutputTracker& t, std::string tree) {
        t.sway_tree_busy_ = false;
        if (const auto fs = fullscreen_from_sway_tree(tree)) t.report_fullscreen(*fs);
        if (std::exchange(t.sway_tree_again_, false)) t.recheck_sway_fullscreen();
    });
}

void OutputTracker::handle_sway_event(std::string_view obj) {
    const auto e = parse_sway_event(obj);
    if (!e) return;
    if (e->focused_output) report_output(*e->focused_output);
    if (e->fullscreen) report_fullscreen(*e->fullscreen);
    if (e->recheck_fullscreen) recheck_sway_fullscreen();
}

bool OutputTracker::on_sway_readable(Glib::IOCondition cond) {
    std::array<char, kReadChunk> buf{};
    for (;;) {
        const ssize_t n = read(fd_, buf.data(), buf.size());
        if (n > 0) {
            sway_split_.feed(std::string_view(buf.data(), static_cast<std::size_t>(n)),
                             [this](std::string_view obj) { handle_sway_event(obj); });
            if (failed_) return false;
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        fail(n == 0 ? "swaymsg exited" : std::string("reading swaymsg: ") + std::strerror(errno));
        return false;
    }
    if ((cond & (Glib::IOCondition::IO_HUP | Glib::IOCondition::IO_ERR)) !=
        Glib::IOCondition{}) {
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
