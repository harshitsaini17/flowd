#include <doctest/doctest.h>

#include <string>
#include <vector>

#include "output_events.hpp"

using namespace flowd;

TEST_CASE("output events: Hyprland focusedmon names the output") {
    auto e = parse_hypr_line("focusedmon>>DP-2,3");
    REQUIRE(e);
    CHECK(e->focused_output == "DP-2");
    CHECK_FALSE(e->fullscreen);
    CHECK(e->recheck_fullscreen);
    CHECK(parse_hypr_line("focusedmon>>eDP-1")->focused_output == "eDP-1");
    CHECK_FALSE(parse_hypr_line("focusedmon>>,3"));
}

TEST_CASE("output events: Hyprland fullscreen toggles, other lines are ignored") {
    CHECK(parse_hypr_line("fullscreen>>1")->fullscreen == true);
    CHECK(parse_hypr_line("fullscreen>>0\r")->fullscreen == false);
    CHECK_FALSE(parse_hypr_line("fullscreen>>2"));
    auto ws = parse_hypr_line("workspace>>2");
    REQUIRE(ws);
    CHECK(ws->recheck_fullscreen);
    CHECK_FALSE(ws->focused_output);
    CHECK_FALSE(parse_hypr_line("fullscreen>>1")->recheck_fullscreen);
    CHECK_FALSE(parse_hypr_line("garbage"));
    CHECK_FALSE(parse_hypr_line(""));
    // focusedmonv2 is a different event, not focusedmon.
    CHECK_FALSE(parse_hypr_line("focusedmonv2>>DP-2,3"));
}

TEST_CASE("output events: Sway workspace focus and window fullscreen") {
    auto ws = parse_sway_event(R"({"change":"focus","current":{"output":"HDMI-A-1"},"old":{}})");
    REQUIRE(ws);
    CHECK(ws->focused_output == "HDMI-A-1");
    CHECK(ws->recheck_fullscreen);

    auto fs = parse_sway_event(R"({"change":"fullscreen_mode","container":{"fullscreen_mode":1}})");
    REQUIRE(fs);
    CHECK(fs->fullscreen == true);
    CHECK(parse_sway_event(R"({"change":"focus","container":{"fullscreen_mode":0}})")->fullscreen ==
          false);

    CHECK_FALSE(parse_sway_event(R"({"change":"title","container":{"fullscreen_mode":1}})"));
    CHECK_FALSE(parse_sway_event(R"({"change":"init","current":{"output":"X"}})"));
    CHECK_FALSE(parse_sway_event("not json"));
    CHECK_FALSE(parse_sway_event("[]"));
}

TEST_CASE("output events: focus moving elsewhere asks for a recheck") {
    for (const char* line : {"closewindow>>55d1a2b0", "activewindowv2>>55d1a2b0", "workspace>>3"}) {
        auto e = parse_hypr_line(line);
        REQUIRE(e);
        CHECK(e->recheck_fullscreen);
        CHECK_FALSE(e->fullscreen);
    }
    auto close = parse_sway_event(R"({"change":"close","container":{"fullscreen_mode":1}})");
    REQUIRE(close);
    CHECK(close->recheck_fullscreen);
    // The closing window's own mode says nothing about what is left.
    CHECK_FALSE(close->fullscreen);
    auto ws = parse_sway_event(R"({"change":"focus","current":{"type":"workspace"}})");
    REQUIRE(ws);
    CHECK(ws->recheck_fullscreen);
    CHECK_FALSE(ws->focused_output);
}

TEST_CASE("output events: Sway tree fullscreen follows the focused node") {
    // A focused fullscreen window.
    CHECK(fullscreen_from_sway_tree(R"({"nodes":[{"type":"output","nodes":[{"type":"workspace",
        "nodes":[{"focused":true,"fullscreen_mode":1}]}]}]})") == true);
    // A focused window inside a fullscreen container.
    CHECK(fullscreen_from_sway_tree(R"({"nodes":[{"fullscreen_mode":1,
        "nodes":[{"focused":true,"fullscreen_mode":0}]}]})") == true);
    // A fullscreen window elsewhere, the focused one tiled.
    CHECK(fullscreen_from_sway_tree(R"({"nodes":[{"nodes":[{"fullscreen_mode":1}]},
        {"nodes":[{"focused":true,"fullscreen_mode":0}]}]})") == false);
    // An empty workspace is focused itself.
    CHECK(fullscreen_from_sway_tree(R"({"nodes":[{"type":"workspace","focused":true,"nodes":[]}]})") ==
          false);
    // Nothing focused at all.
    CHECK(fullscreen_from_sway_tree(R"({"nodes":[]})") == false);
    // Floating windows count too.
    CHECK(fullscreen_from_sway_tree(R"({"floating_nodes":[{"focused":true,"fullscreen_mode":2}]})") ==
          true);
    CHECK_FALSE(fullscreen_from_sway_tree("not json"));
    CHECK_FALSE(fullscreen_from_sway_tree("[]"));
}

TEST_CASE("output events: startup queries") {
    CHECK(focused_output_from_json(
              R"([{"name":"eDP-1","focused":false},{"name":"DP-2","focused":true}])") == "DP-2");
    CHECK_FALSE(focused_output_from_json(R"([{"name":"eDP-1","focused":false}])"));
    CHECK_FALSE(focused_output_from_json("{"));
    CHECK(fullscreen_from_hypr_activewindow(R"({"fullscreen":2})") == true);
    CHECK(fullscreen_from_hypr_activewindow(R"({"fullscreen":0})") == false);
    CHECK(fullscreen_from_hypr_activewindow(R"({"fullscreen":true})") == true);
    // No active window: hyprctl prints {}.
    CHECK_FALSE(fullscreen_from_hypr_activewindow("{}"));
}

TEST_CASE("output events: the splitter finds objects across chunks and line breaks") {
    JsonObjectSplitter split;
    std::vector<std::string> got;
    const auto collect = [&got](std::string_view o) { got.emplace_back(o); };
    split.feed("{\"a\":1}\n{\n  \"b\": {\"c\": \"}\\\"{\"}", collect);
    CHECK(got.size() == 1);
    split.feed("\n}\n  junk {\"d\":[1,{}]}", collect);
    REQUIRE(got.size() == 3);
    CHECK(got[0] == "{\"a\":1}");
    CHECK(got[1] == "{\n  \"b\": {\"c\": \"}\\\"{\"}\n}");
    CHECK(got[2] == "{\"d\":[1,{}]}");
    CHECK(parse_sway_event(got[1]) == std::nullopt);
}

TEST_CASE("output events: an oversized object is dropped and the stream recovers") {
    JsonObjectSplitter split;
    int count = 0;
    const auto collect = [&count](std::string_view) { ++count; };
    split.feed("{\"x\":\"", collect);
    split.feed(std::string(kMaxJsonObject, 'a'), collect);
    split.feed("\"}", collect);
    CHECK(count == 0);
    split.feed("{}", collect);
    CHECK(count == 1);
}
