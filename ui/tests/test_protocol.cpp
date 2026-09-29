#include <doctest/doctest.h>

#include "protocol.hpp"

using namespace flowd;

TEST_CASE("protocol: render carries all three zones") {
    auto m = parse_message(R"({"type":"render","polished":"Hi.","pending":" there","live":" how"})");
    REQUIRE(m);
    auto* r = std::get_if<Render>(&*m);
    REQUIRE(r);
    CHECK(r->polished == "Hi.");
    CHECK(r->pending == " there");
    CHECK(r->live == " how");
}

TEST_CASE("protocol: state with a reason code") {
    auto m = parse_message(R"({"type":"state","state":"fallback","reason":"timeout"})");
    REQUIRE(m);
    auto& s = std::get<StateMsg>(*m);
    CHECK(s.state == UiState::Fallback);
    CHECK(s.reason == "timeout");
}

TEST_CASE("protocol: warn null clears, blocking defaults to false") {
    auto clear = parse_message(R"({"type":"warn","reason":null})");
    REQUIRE(clear);
    CHECK_FALSE(std::get<Warn>(*clear).reason.has_value());
    auto set = parse_message(R"({"type":"warn","reason":"Cleanup offline, pasting as heard"})");
    CHECK(std::get<Warn>(*set).blocking == false);
}

TEST_CASE("protocol: config fills defaults for missing keys") {
    auto m = parse_message(R"({"type":"config","ui":{"theme":"dark","max_lines":6}})");
    REQUIRE(m);
    auto& c = std::get<ConfigMsg>(*m).ui;
    CHECK(c.theme == Theme::Dark);
    CHECK(c.max_lines == 6);
    CHECK(c.fade_ms == 1000);
    CHECK(c.indicator);
}

TEST_CASE("protocol: unknown types, bad JSON and wrong field types are ignored") {
    CHECK_FALSE(parse_message(R"({"type":"sparkle"})"));
    CHECK_FALSE(parse_message("{not json"));
    CHECK_FALSE(parse_message(R"({"type":"level","rms_db":"loud"})"));
    CHECK_FALSE(parse_message(R"({"type":"state","state":"dancing"})"));
    CHECK_FALSE(parse_message(""));
}

TEST_CASE("protocol: out-of-range config values are clamped, not trusted") {
    auto m = parse_message(R"({"type":"config","ui":{"max_lines":0,"fade_ms":-5}})");
    auto& c = std::get<ConfigMsg>(*m).ui;
    CHECK(c.max_lines == 1);
    CHECK(c.fade_ms == 0);
}

TEST_CASE("protocol: events are one JSON line each") {
    CHECK(encode_click() == "{\"event\":\"click\"}\n");
    CHECK(encode_moved(0.42, "eDP-1") == "{\"event\":\"moved\",\"output\":\"eDP-1\",\"x\":0.42}\n");
    CHECK(encode_unsupported("no layer-shell").find("\"unsupported\"") != std::string::npos);
}

TEST_CASE("protocol: encoders never throw on invalid UTF-8") {
    std::string out;
    CHECK_NOTHROW(out = encode_moved(0.5, std::string("bad\xff")));
    CHECK(out.find("\"event\":\"moved\"") != std::string::npos);
}

TEST_CASE("protocol: out-of-range config integers are ignored, not truncated") {
    auto m = parse_message(R"({"type":"config","ui":{"max_lines":99999999999}})");
    REQUIRE(m);
    auto& c = std::get<ConfigMsg>(*m).ui;
    CHECK(c.max_lines == kDefaultMaxLines);
}

TEST_CASE("protocol: state names follow the ADR spelling") {
    auto a = parse_message(R"({"type":"state","state":"nospeech","reason":""})");
    REQUIRE(a);
    CHECK(std::get<StateMsg>(*a).state == UiState::NoSpeech);
    auto b = parse_message(R"({"type":"state","state":"timelimit","reason":""})");
    REQUIRE(b);
    CHECK(std::get<StateMsg>(*b).state == UiState::TimeLimit);
    CHECK_FALSE(parse_message(R"({"type":"state","state":"no_speech","reason":""})"));
}
