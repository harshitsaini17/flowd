#include <doctest/doctest.h>

#include <optional>
#include <string>

#include "indicator_model.hpp"

using namespace flowd;

TEST_CASE("indicator: hover needs 80 ms of pointer, leave waits 240 ms") {
    IndicatorModel m;
    m.pointer_enter(0.0);
    m.advance(0.05); CHECK(m.look() == IndicatorLook::Idle);
    m.advance(0.09); CHECK(m.look() == IndicatorLook::Hover);
    m.pointer_leave(1.0);
    m.advance(1.2);  CHECK(m.look() == IndicatorLook::Hover);
    m.advance(1.25); CHECK(m.look() == IndicatorLook::Idle);
}

TEST_CASE("indicator: a pass-through pointer never expands it") {
    IndicatorModel m;
    m.pointer_enter(0.0); m.pointer_leave(0.05);
    m.advance(0.2); CHECK(m.look() == IndicatorLook::Idle);
}

TEST_CASE("indicator: the grip appears after 600 ms of hover") {
    IndicatorModel m;
    m.pointer_enter(0.0); m.advance(0.5);
    CHECK_FALSE(m.show_grip());
    m.advance(0.69); CHECK(m.show_grip());
}

TEST_CASE("indicator: idle takes clicks on the 120x20 strip only") {
    IndicatorModel m;
    CHECK(m.input_region() == InputRegion::Strip);
    CHECK(m.clickable());
}

TEST_CASE("indicator: finishing empties the input region at once, before the grace ends") {
    IndicatorModel m;
    m.on_state(UiState::Recording, 0.0);
    CHECK(m.input_region() == InputRegion::Pill);
    m.on_state(UiState::Finishing, 1.0);
    CHECK(m.input_region() == InputRegion::Empty);
    CHECK_FALSE(m.clickable());
    CHECK(m.look() == IndicatorLook::Recording);  // visual grace
    m.advance(1.13);
    CHECK(m.look() == IndicatorLook::Finishing);
}

TEST_CASE("indicator: a fast finish never shows the spinner") {
    IndicatorModel m;
    m.on_state(UiState::Recording, 0.0);
    m.on_state(UiState::Finishing, 1.0);
    m.on_state(UiState::Done, 1.05);
    m.advance(1.2);
    CHECK(m.look() == IndicatorLook::Idle);
    CHECK(m.clickable());
}

TEST_CASE("indicator: a warning shows while idle and widens on hover") {
    IndicatorModel m;
    m.on_warn(std::string("Cleanup offline, pasting as heard"), false);
    CHECK(m.look() == IndicatorLook::Warning);
    m.pointer_enter(0); m.advance(0.1);
    CHECK(m.look() == IndicatorLook::WarningHover);
    CHECK(m.input_region() == InputRegion::WarnPill);
    CHECK(m.clickable());
    m.on_warn(std::nullopt, false);
    CHECK(m.look() == IndicatorLook::Hover);
}

TEST_CASE("indicator: a blocking mic warning is not clickable") {
    IndicatorModel m;
    m.on_warn(std::string("Microphone unavailable"), true);
    CHECK_FALSE(m.clickable());
    CHECK(m.warn_blocking());
}

TEST_CASE("indicator: recording hides the warning and dragging is idle-only") {
    IndicatorModel m;
    m.on_warn(std::string("x"), false);
    m.on_state(UiState::Recording, 0);
    CHECK(m.look() == IndicatorLook::Recording);
    m.drag_begin();
    CHECK(m.look() == IndicatorLook::Recording);  // drag ignored while recording
}

TEST_CASE("indicator: the only deadline while idle and untouched is none") {
    IndicatorModel m;
    CHECK_FALSE(m.next_deadline());  // no timers at idle (global constraint)
}

TEST_CASE("indicator: timers report their deadlines") {
    IndicatorModel m;
    m.pointer_enter(1.0);
    CHECK(*m.next_deadline() == doctest::Approx(1.08));
    m.advance(1.08);
    CHECK(*m.next_deadline() == doctest::Approx(1.68));  // the grip
    m.advance(1.7);
    CHECK_FALSE(m.next_deadline());
}

TEST_CASE("indicator: dragging from hover shows the drag look, release returns to hover") {
    IndicatorModel m;
    m.pointer_enter(0); m.advance(0.7);
    m.drag_begin();
    CHECK(m.look() == IndicatorLook::Dragging);
    CHECK_FALSE(m.clickable());
    m.drag_end();
    CHECK(m.look() == IndicatorLook::Hover);
}

TEST_CASE("indicator: a warning survives a finished session and shows again at idle") {
    IndicatorModel m;
    m.on_warn(std::string("Cleanup offline, pasting as heard"), false);
    m.on_state(UiState::Recording, 0);
    m.on_state(UiState::Fallback, 1.0);
    CHECK(m.look() == IndicatorLook::Warning);
    CHECK(*m.warn_text() == "Cleanup offline, pasting as heard");
}
