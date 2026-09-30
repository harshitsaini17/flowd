#include <doctest/doctest.h>

#include <string>
#include <vector>

#include "line_splitter.hpp"

using namespace flowd;

namespace {

struct Collect {
    std::vector<std::string> lines;
    int overflows = 0;
    bool feed(LineSplitter& s, std::string_view data) {
        return s.feed(
            data,
            [this](std::string_view l) {
                lines.emplace_back(l);
                return true;
            },
            [this] { ++overflows; });
    }
};

}  // namespace

TEST_CASE("lines: complete lines come out without their newline") {
    LineSplitter s;
    Collect c;
    CHECK(c.feed(s, "a\nbc\n\n"));
    CHECK(c.lines == std::vector<std::string>{"a", "bc", ""});
    CHECK(s.pending() == 0);
}

TEST_CASE("lines: a line split across reads is joined") {
    LineSplitter s;
    Collect c;
    c.feed(s, "{\"type\":");
    CHECK(c.lines.empty());
    CHECK(s.pending() == 8);
    c.feed(s, "\"show\"}\nnext");
    CHECK(c.lines == std::vector<std::string>{"{\"type\":\"show\"}"});
    CHECK(s.pending() == 4);
}

TEST_CASE("lines: an over-long line is dropped to its newline with one overflow") {
    LineSplitter s(5);
    Collect c;
    c.feed(s, "ok\n12");
    c.feed(s, "345");
    c.feed(s, "6789");
    CHECK(c.overflows == 1);
    CHECK(s.pending() == 0);
    c.feed(s, "0\nafter\n");
    CHECK(c.lines == std::vector<std::string>{"ok", "after"});
    CHECK(c.overflows == 1);
    // Exactly at the cap still fits.
    c.feed(s, "abcde\n");
    CHECK(c.lines.back() == "abcde");
    // A second over-long line warns again.
    c.feed(s, "abcdef\n");
    CHECK(c.overflows == 2);
}

TEST_CASE("lines: returning false stops before the next line") {
    LineSplitter s;
    std::vector<std::string> got;
    const bool more = s.feed(
        "quit\nshow\n",
        [&](std::string_view l) {
            got.emplace_back(l);
            return false;
        },
        [] {});
    CHECK_FALSE(more);
    CHECK(got == std::vector<std::string>{"quit"});
}

TEST_CASE("lines: empty input does nothing") {
    LineSplitter s;
    Collect c;
    CHECK(c.feed(s, ""));
    CHECK(c.lines.empty());
    CHECK(c.overflows == 0);
}
