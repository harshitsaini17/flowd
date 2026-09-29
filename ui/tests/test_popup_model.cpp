#include <doctest/doctest.h>

#include <string>
#include <variant>

#include "popup_model.hpp"

using namespace flowd;

TEST_CASE("popup: show enters with Listening, render switches to zones") {
    PopupModel p;
    p.on_show(0);
    CHECK(p.phase() == PopupPhase::Entering);
    CHECK(std::get<Placeholder>(p.content()).text == "Listening…");
    p.on_render({"Hi.", "", " there"});
    CHECK(std::holds_alternative<Zones>(p.content()));
}

TEST_CASE("popup: done shows Pasted into app and holds fade_ms before exiting") {
    PopupModel p; UiConfig c; c.fade_ms = 1000; p.on_config(c);
    p.on_meta({"prose", "firefox", ""});
    p.on_show(0);
    p.on_state({UiState::Done, ""}, 5.0);
    p.on_fade(5.0);
    CHECK(p.status()->text == "Pasted into firefox");
    CHECK(p.status()->icon == Icon::Check);
    p.advance(5.9); CHECK(p.phase() == PopupPhase::Shown);
    p.advance(6.01); CHECK(p.phase() == PopupPhase::Exiting);
    p.advance(6.3); CHECK(p.phase() == PopupPhase::Hidden);
}

TEST_CASE("popup: each fallback reason has its own wording and holds a second longer") {
    PopupModel p; UiConfig c; c.fade_ms = 1000; p.on_config(c);
    p.on_show(0);
    p.on_state({UiState::Fallback, "timeout"}, 1.0);
    p.on_fade(1.0);
    CHECK(p.status()->text == "Pasted as heard · cleanup timed out");
    CHECK(p.status()->tone == Tone::Info);
    p.advance(2.9); CHECK(p.phase() == PopupPhase::Shown);
    p.advance(3.01); CHECK(p.phase() == PopupPhase::Exiting);
}

TEST_CASE("popup: cancelled strikes the text through and holds 800 ms, even on hide") {
    PopupModel p;
    p.on_show(0);
    p.on_render({"Hello", "", ""});
    p.on_state({UiState::Cancelled, ""}, 1.0);
    p.on_hide(1.0);
    CHECK(std::get<Struck>(p.content()).text == "Hello");
    CHECK(p.status()->text == "Cancelled, nothing pasted");
    p.advance(1.79); CHECK(p.phase() == PopupPhase::Shown);
    p.advance(1.81); CHECK(p.phase() == PopupPhase::Exiting);
}

TEST_CASE("popup: error reasons map to design wording and hold times") {
    struct Case { const char* reason; const char* text; double hold; };
    for (auto [reason, text, hold] : {
             Case{"mic_lost", "Mic disconnected · pasted what was heard", 3.0},
             Case{"paste_failed", "Couldn't paste. Run flowctl last to copy it", 4.0}}) {
        PopupModel p;
        p.on_show(0);
        p.on_state({UiState::Error, reason}, 1.0);
        p.on_fade(1.0);
        CHECK(p.status()->text == text);
        p.advance(1.0 + hold - 0.01); CHECK(p.phase() == PopupPhase::Shown);
        p.advance(1.0 + hold + 0.01); CHECK(p.phase() == PopupPhase::Exiting);
    }
}

TEST_CASE("popup: no speech holds 1 s") {
    PopupModel p;
    p.on_show(0);
    p.on_state({UiState::NoSpeech, ""}, 2.0);
    p.on_hide(2.0);
    CHECK(std::get<Placeholder>(p.content()).text == "No speech detected");
    p.advance(3.01); CHECK(p.phase() == PopupPhase::Exiting);
}

TEST_CASE("popup: countdown starts 10 s before the limit") {
    PopupModel p; UiConfig c; c.max_session_s = 300; p.on_config(c);
    p.on_show(0);
    CHECK_FALSE(p.countdown(289.0));
    CHECK(*p.countdown(291.0) == "0:09 left");
}

TEST_CASE("popup: a time limit shows the reached message then continues to finishing") {
    PopupModel p; UiConfig c; c.max_session_s = 300; p.on_config(c);
    p.on_show(0);
    p.on_state({UiState::TimeLimit, ""}, 300);
    CHECK(p.status()->text == "Time limit reached (5:00)");
    CHECK(p.status()->tone == Tone::Warn);
    p.on_state({UiState::Finishing, ""}, 300.1);
    CHECK(p.status()->text == "Time limit reached (5:00)");  // kept until done
}

TEST_CASE("popup: a clipping hint shows for 2 s") {
    PopupModel p;
    p.on_show(0);
    p.set_clipping(true, 1.0);
    CHECK(p.status()->text == "Too loud, move back a little");
    p.set_clipping(false, 1.1);
    p.advance(2.9); CHECK(p.status());
    p.advance(3.01); CHECK_FALSE(p.status());
}

TEST_CASE("popup: a new show during an exit restarts cleanly") {
    PopupModel p;
    p.on_show(0);
    p.on_state({UiState::Done, ""}, 1);
    p.on_fade(1);
    p.advance(2.1);
    CHECK(p.phase() == PopupPhase::Exiting);
    p.on_show(2.15);
    CHECK(p.phase() == PopupPhase::Entering);
    CHECK_FALSE(p.status());
}

TEST_CASE("popup: footer shows when enabled or when it carries a status") {
    PopupModel p; UiConfig c; c.footer = false; p.on_config(c);
    p.on_show(0);
    CHECK_FALSE(p.footer_visible());
    p.on_state({UiState::Finishing, ""}, 1);
    CHECK(p.footer_visible());
}

TEST_CASE("popup: format_clock renders m:ss, rounded down") {
    CHECK(format_clock(0) == "0:00");
    CHECK(format_clock(59.9) == "0:59");
    CHECK(format_clock(300) == "5:00");
    CHECK(format_clock(-3) == "0:00");
}

TEST_CASE("popup: an unknown error reason gets the generic danger wording") {
    PopupModel p;
    p.on_show(0);
    p.on_state({UiState::Error, "gremlins"}, 1.0);
    CHECK(p.status()->text == "Something went wrong · see flowctl status");
    CHECK(p.status()->tone == Tone::Danger);
    p.advance(3.99); CHECK(p.phase() == PopupPhase::Shown);
    p.advance(4.01); CHECK(p.phase() == PopupPhase::Exiting);
}

TEST_CASE("popup: mic lost with nothing heard uses the design wording") {
    PopupModel p;
    p.on_show(0);
    p.on_state({UiState::Error, "mic_lost_empty"}, 1.0);
    CHECK(p.status()->text == "Mic disconnected · nothing was pasted");
    CHECK(p.status()->icon == Icon::MicOff);
}

TEST_CASE("popup: finishing restyles the live run to pending and freezes the clock") {
    PopupModel p;
    p.on_show(0);
    p.on_render({"Hi.", "", "there"});
    p.on_state({UiState::Finishing, ""}, 4.0);
    const auto z = std::get<Zones>(p.content());
    CHECK(z.live.empty());
    CHECK(z.pending == "there");
    CHECK(p.elapsed_s(9.0) == doctest::Approx(4.0));
    CHECK(p.status()->icon == Icon::LoaderCircle);
}

TEST_CASE("popup: deadlines follow the phase and nothing is due when hidden") {
    PopupModel p;
    CHECK_FALSE(p.next_deadline());
    p.on_show(0);
    CHECK(*p.next_deadline() == doctest::Approx(0.16));  // dur-base enter
    p.on_state({UiState::Cancelled, ""}, 1.0);
    CHECK(*p.next_deadline() == doctest::Approx(1.8));
    p.advance(1.8);
    CHECK(*p.next_deadline() == doctest::Approx(2.04));  // dur-fade-out exit
    p.advance(2.1);
    CHECK_FALSE(p.next_deadline());
}
