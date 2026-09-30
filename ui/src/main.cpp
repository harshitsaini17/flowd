#include <fcntl.h>
#include <glibmm/error.h>
#include <signal.h>
#include <unistd.h>

#include <cerrno>

#include <exception>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>

#include "app.hpp"
#include "backend.hpp"
#include "protocol.hpp"
#include "surface.hpp"
#include "version.hpp"

// flowd-ui [--version] [--log-level LEVEL]
//
// Config arrives only over stdin (`config`), so argv carries nothing the
// daemon would have to keep in sync.
namespace {

using namespace flowd;

constexpr LogLevel kDefaultLogLevel = LogLevel::Warn;
constexpr std::string_view kUsage = "usage: flowd-ui [--version] [--log-level error|warn|info|debug]";

struct Args {
    bool version = false;
    LogLevel level = kDefaultLogLevel;
};

// Nothing, after logging why, when argv is not understood.
std::optional<Args> parse_args(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg = argv[i];
        if (arg == "--version") {
            a.version = true;
        } else if (arg == "--log-level" && i + 1 == argc) {
            log_line("missing value for --log-level");
            log_line(kUsage);
            return std::nullopt;
        } else if (arg == "--log-level") {
            const auto level = parse_log_level(argv[++i]);
            if (!level) {
                log_line(std::string("unknown log level: ") + argv[i]);
                return std::nullopt;
            }
            a.level = *level;
        } else {
            log_line(std::string("unknown argument: ") + std::string(arg));
            log_line(kUsage);
            return std::nullopt;
        }
    }
    return a;
}

constexpr int kFirstStdFd = 0;
constexpr int kLastStdFd = 2;
constexpr const char* kDevNull = "/dev/null";

// A closed stdin, stdout or stderr would be the next fd GLib or Wayland
// opens, and then protocol bytes or log lines would land in a socket. Each
// closed one is filled with /dev/null first.
void fill_closed_std_fds() {
    for (int fd = kFirstStdFd; fd <= kLastStdFd; ++fd) {
        if (fcntl(fd, F_GETFD) >= 0 || errno != EBADF) continue;
        const int flags = fd == kFirstStdFd ? O_RDONLY : O_WRONLY;
        const int got = open(kDevNull, flags);
        // open returns the lowest free fd, which is this one; anything else
        // means something else is off, and the fd is not kept.
        if (got >= 0 && got != fd) close(got);
    }
}

int run(int argc, char** argv) {
    fill_closed_std_fds();
    // A daemon that dies mid-write must not kill the UI with SIGPIPE; the
    // write sees EPIPE instead and the UI exits cleanly.
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) log_line("could not ignore SIGPIPE");

    const auto args = parse_args(argc, argv);
    if (!args) return kExitError;
    if (args->version) {
        std::cout << "flowd-ui " << kVersion << '\n';
        return kExitOk;
    }

    // Decided from the environment before GTK opens anything: with no
    // display, or on GNOME Wayland, there is no surface to check, and GTK
    // init would only fail or open the wrong one. Layer-shell support needs
    // an open display, so it is assumed here and checked after init.
    const Decision d = choose_backend(read_env(), true);
    if (d.backend == Backend::Unsupported) {
        log_line("disabled: " + d.reason);
        write_all_blocking(encode_unsupported(d.reason));
        return kExitUnsupported;
    }

    // Both before GTK init: the renderer and the backend are read only then.
    apply_env_defaults(d.backend);
    if (auto replaced = pin_gdk_backend(d.backend); replaced && args->level >= LogLevel::Info)
        log_line("GDK_BACKEND=" + *replaced + " overridden: " + d.reason);

    App app(d.backend, args->level);
    return app.run();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return run(argc, argv);
    } catch (const Glib::Error& e) {
        log_line("fatal: " + std::string(e.what()));
    } catch (const std::exception& e) {
        log_line(std::string("fatal: ") + e.what());
    }
    return kExitError;
}
