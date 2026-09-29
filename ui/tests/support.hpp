#pragma once

#include <doctest/doctest.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

// Shared helpers for tests that touch the filesystem.
namespace flowd::test {

// A fresh directory under the system temp dir, removed on destruction.
// mkdtemp makes the name unique, so parallel test runs never collide.
struct TempDir {
    std::filesystem::path path;

    TempDir() {
        std::error_code ec;
        const auto base = std::filesystem::temp_directory_path(ec);
        REQUIRE_FALSE(ec);
        std::string templ = (base / "flowd-ui-test.XXXXXX").string();
        char* made = mkdtemp(templ.data());
        REQUIRE(made != nullptr);
        path = made;
    }
    ~TempDir() {
        // Only ever this exact path, and never throwing from a destructor.
        // A test may have made it read-only; restore that first so the
        // removal works even when the test failed part-way.
        std::error_code ec;
        std::filesystem::permissions(path, std::filesystem::perms::owner_all, ec);
        std::filesystem::remove_all(path, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
};

inline void write_file(const std::filesystem::path& path, std::string_view text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    REQUIRE(out.good());
    out << text;
    out.close();
    REQUIRE_FALSE(out.fail());
}

}  // namespace flowd::test
