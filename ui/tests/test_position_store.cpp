#include <doctest/doctest.h>
#include <unistd.h>

#include <cmath>
#include <cstdlib>
#include <optional>
#include <string>

#include "position_store.hpp"
#include "support.hpp"

using namespace flowd;
using flowd::test::TempDir;
using flowd::test::write_file;

namespace {

// Sets or unsets an environment variable for one scope, then restores it.
class ScopedEnv {
public:
    ScopedEnv(const char* name, const char* value) : name_(name) {
        if (const char* old = std::getenv(name)) old_ = old;
        if (value) {
            REQUIRE(setenv(name, value, 1) == 0);
        } else {
            REQUIRE(unsetenv(name) == 0);
        }
    }
    ~ScopedEnv() {
        // A destructor cannot fail a test, and with a valid name these calls
        // only fail on out-of-memory, so the results are deliberately ignored.
        if (old_) {
            (void)setenv(name_, old_->c_str(), 1);
        } else {
            (void)unsetenv(name_);
        }
    }
    ScopedEnv(const ScopedEnv&) = delete;
    ScopedEnv& operator=(const ScopedEnv&) = delete;

private:
    const char* name_;
    std::optional<std::string> old_;
};

}  // namespace

TEST_CASE("store: an unknown output is centred") {
    TempDir d;
    PositionStore s(d.path / "indicator.json");
    CHECK(s.get("eDP-1") == doctest::Approx(0.5));
}

TEST_CASE("store: a saved position survives a new store (restart)") {
    TempDir d;
    {
        PositionStore s(d.path / "indicator.json");
        CHECK(s.set("eDP-1", 0.42));
        CHECK(s.set("HDMI-A-1", 0.75));
    }
    PositionStore again(d.path / "indicator.json");
    CHECK(again.get("eDP-1") == doctest::Approx(0.42));
    CHECK(again.get("HDMI-A-1") == doctest::Approx(0.75));
}

TEST_CASE("store: creates the flowd directory when it is missing") {
    TempDir d;
    PositionStore s(d.path / "state" / "flowd" / "indicator.json");
    CHECK(s.set("eDP-1", 0.3));
    CHECK(std::filesystem::exists(d.path / "state" / "flowd" / "indicator.json"));
}

TEST_CASE("store: a corrupt or foreign file reads as defaults and is replaced on save") {
    TempDir d;
    write_file(d.path / "indicator.json", "{garbage");
    PositionStore s(d.path / "indicator.json");
    CHECK(s.get("eDP-1") == doctest::Approx(0.5));
    CHECK(s.set("eDP-1", 0.6));
    CHECK(PositionStore(d.path / "indicator.json").get("eDP-1") == doctest::Approx(0.6));
}

TEST_CASE("store: out-of-range and non-numeric fractions are ignored") {
    TempDir d;
    write_file(d.path / "indicator.json", R"({"version":1,"outputs":{"a":7,"b":"x","c":0.2}})");
    PositionStore s(d.path / "indicator.json");
    CHECK(s.get("a") == doctest::Approx(0.5));
    CHECK(s.get("b") == doctest::Approx(0.5));
    CHECK(s.get("c") == doctest::Approx(0.2));
}

TEST_CASE("store: another version or a missing outputs object reads as defaults") {
    TempDir d;
    write_file(d.path / "v2.json", R"({"version":2,"outputs":{"a":0.2}})");
    write_file(d.path / "none.json", R"({"version":1})");
    CHECK(PositionStore(d.path / "v2.json").get("a") == doctest::Approx(0.5));
    CHECK(PositionStore(d.path / "none.json").get("a") == doctest::Approx(0.5));
}

TEST_CASE("store: set clamps the fraction to [0, 1]") {
    TempDir d;
    PositionStore s(d.path / "indicator.json");
    CHECK(s.set("a", 1.7));
    CHECK(s.set("b", -0.3));
    PositionStore again(d.path / "indicator.json");
    CHECK(again.get("a") == doctest::Approx(1.0));
    CHECK(again.get("b") == doctest::Approx(0.0));
}

TEST_CASE("store: an unwritable directory fails quietly") {
    if (geteuid() == 0) {
        MESSAGE("skipped: root ignores permission bits");
        return;
    }
    TempDir d;
    std::filesystem::permissions(d.path, std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec);
    PositionStore s(d.path / "indicator.json");
    CHECK_FALSE(s.set("eDP-1", 0.4));
    CHECK(s.get("eDP-1") == doctest::Approx(0.4));  // kept in memory for this run
    // TempDir's destructor restores the permissions, even if a check fails.
    CHECK(std::filesystem::is_empty(d.path));  // no indicator.json, no .tmp.<pid>
}

TEST_CASE("store: a path that is a directory reads as defaults and fails to save") {
    TempDir d;
    std::filesystem::create_directory(d.path / "indicator.json");
    std::optional<PositionStore> s;
    CHECK_NOTHROW(s.emplace(d.path / "indicator.json"));
    REQUIRE(s.has_value());
    CHECK(s->get("eDP-1") == doctest::Approx(0.5));
    CHECK_FALSE(s->set("eDP-1", 0.3));
}

TEST_CASE("store: an output name that is not UTF-8 does not throw") {
    TempDir d;
    PositionStore s(d.path / "indicator.json");
    bool ok = false;
    CHECK_NOTHROW(ok = s.set("bad\xff", 0.3));
    CHECK(ok);
    CHECK(s.get("bad\xff") == doctest::Approx(0.3));
}

TEST_CASE("store: NaN is stored as the centre") {
    TempDir d;
    PositionStore s(d.path / "indicator.json");
    CHECK(s.set("eDP-1", NAN));
    CHECK(s.get("eDP-1") == doctest::Approx(0.5));
    CHECK(PositionStore(d.path / "indicator.json").get("eDP-1") == doctest::Approx(0.5));
}

TEST_CASE("store: an empty path fails quietly") {
    PositionStore s{std::filesystem::path{}};
    CHECK_FALSE(s.set("eDP-1", 0.4));
    CHECK(s.get("eDP-1") == doctest::Approx(0.4));
}

TEST_CASE("store: the default file honours an absolute XDG_STATE_HOME") {
    ScopedEnv home("HOME", "/home/someone");
    {
        ScopedEnv xdg("XDG_STATE_HOME", "/tmp/xdg-state");
        CHECK(default_position_file() == std::filesystem::path("/tmp/xdg-state/flowd/indicator.json"));
    }
    {
        ScopedEnv xdg("XDG_STATE_HOME", "relative/state");
        CHECK(default_position_file() == std::filesystem::path("/home/someone/.local/state/flowd/indicator.json"));
    }
    {
        ScopedEnv xdg("XDG_STATE_HOME", "");
        CHECK(default_position_file() == std::filesystem::path("/home/someone/.local/state/flowd/indicator.json"));
    }
    {
        ScopedEnv xdg("XDG_STATE_HOME", nullptr);
        ScopedEnv nohome("HOME", nullptr);
        CHECK(default_position_file().empty());
    }
}
