#include <string_view>

#include <doctest/doctest.h>

#include "version.hpp"

TEST_CASE("the core library links and reports its version") {
    CHECK(std::string_view(flowd::kVersion) == "0.1.0");
}
