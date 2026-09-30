#pragma once

#include <cstddef>
#include <string>
#include <string_view>

// Splits the daemon's stdin byte stream into newline-terminated lines, with a
// cap so a runaway writer cannot grow the buffer without bound. No GTK or I/O
// here, so it is unit-tested; app.cpp feeds it whatever read() returned.
namespace flowd {

// ADR 0013 messages are small; a render carries at most a session's text.
// A line longer than this is dropped whole, up to its newline.
constexpr std::size_t kMaxLineBytes = 1 << 20;

class LineSplitter {
public:
    explicit LineSplitter(std::size_t max_line = kMaxLineBytes) : max_(max_line) {}

    // Appends data. Calls on_line(std::string_view) for each complete line,
    // without its '\n', and on_overflow() once for each line dropped for
    // being longer than the cap. Returns early, keeping the rest unread, when
    // on_line returns false (e.g. after `quit`); the return value is then
    // false too.
    template <typename Line, typename Overflow>
    bool feed(std::string_view data, Line&& on_line, Overflow&& on_overflow) {
        while (!data.empty()) {
            const auto nl = data.find('\n');
            const auto chunk = data.substr(0, nl);
            if (!dropping_) {
                if (buf_.size() + chunk.size() > max_) {
                    // Past the cap: forget what was kept and skip to the newline.
                    buf_.clear();
                    buf_.shrink_to_fit();
                    dropping_ = true;
                    on_overflow();
                } else {
                    buf_.append(chunk);
                }
            }
            if (nl == std::string_view::npos) return true;
            data.remove_prefix(nl + 1);
            if (dropping_) {
                dropping_ = false;
                continue;
            }
            const bool more = on_line(std::string_view(buf_));
            buf_.clear();
            if (!more) return false;
        }
        return true;
    }

    // Bytes held for an unfinished line.
    std::size_t pending() const { return buf_.size(); }

private:
    std::size_t max_;
    std::string buf_;
    bool dropping_ = false;  // inside an over-long line, until its newline
};

}  // namespace flowd
