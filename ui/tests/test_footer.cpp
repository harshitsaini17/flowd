#include <doctest/doctest.h>

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "footer.hpp"

using namespace flowd;

// 8 px per character keeps the arithmetic readable.
static int eight(std::string_view s) { return int(s.size()) * 8; }

TEST_CASE("footer: everything fits on a wide card") {
    auto items = compose_footer({"prose", "firefox", "0:12", "Super+D to stop", std::nullopt}, 600, eight);
    CHECK(items.size() == 4);
}

TEST_CASE("footer: drops the app id first, then elapsed, then the hint") {
    FooterInput in{"prose", "firefox", "0:12", "Super+D to stop", std::nullopt};
    auto names = [](auto v) { std::vector<FooterKind> k; for (auto& i : v) k.push_back(i.kind); return k; };
    CHECK(names(compose_footer(in, 260, eight)) ==
          std::vector{FooterKind::Mode, FooterKind::Elapsed, FooterKind::Hint});
    CHECK(names(compose_footer(in, 200, eight)) == std::vector{FooterKind::Mode, FooterKind::Hint});
    CHECK(names(compose_footer(in, 60, eight)) == std::vector{FooterKind::Mode});
}

TEST_CASE("footer: a status is kept and ellipsized last") {
    FooterInput in{"prose", "firefox", "0:12", "", std::string(80, 'a')};
    auto items = compose_footer(in, 200, eight);
    REQUIRE(items.back().kind == FooterKind::Status);
    CHECK(items.back().ellipsize);
}

TEST_CASE("footer: with no hotkey label there is no stop hint") {
    auto items = compose_footer({"prose", "", "0:01", "", std::nullopt}, 600, eight);
    for (auto& i : items) CHECK(i.kind != FooterKind::Hint);
}

TEST_CASE("footer: the mode chip stays even when nothing else fits") {
    auto items = compose_footer({"prose", "firefox", "0:12", "Super+D to stop", std::nullopt}, 0, eight);
    REQUIRE(items.size() == 1);
    CHECK(items[0].kind == FooterKind::Mode);
    CHECK_FALSE(items[0].ellipsize);
}
