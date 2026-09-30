#include <doctest/doctest.h>

#include <string>

#include "placement.hpp"
#include "popup_model.hpp"
#include "popup_text.hpp"

using namespace flowd;

TEST_CASE("popup text: zones join with one space and ranges cover only their words") {
    const auto j = join_zones({"So the thing is,", "we ship", "on friday"});
    CHECK(j.text == "So the thing is, we ship on friday");
    CHECK(j.text.substr(j.polished.begin, j.polished.end - j.polished.begin) == "So the thing is,");
    CHECK(j.text.substr(j.pending.begin, j.pending.end - j.pending.begin) == "we ship");
    CHECK(j.text.substr(j.live.begin, j.live.end - j.live.begin) == "on friday");
}

TEST_CASE("popup text: a zone that brings its own space gets no extra one") {
    const auto j = join_zones({"So the thing is,", " we ship", " on friday"});
    CHECK(j.text == "So the thing is, we ship on friday");
    CHECK(j.pending.begin == 16);
}

TEST_CASE("popup text: empty zones have empty ranges and add no space") {
    const auto j = join_zones({"", "", "so the thing is"});
    CHECK(j.text == "so the thing is");
    CHECK(j.polished.empty());
    CHECK(j.pending.empty());
    CHECK(j.live == ByteRange{0, 15});
}

TEST_CASE("popup text: polished text that only grew is no correction") {
    CHECK_FALSE(correction_range("Move it", "Move it to Friday."));
    CHECK_FALSE(correction_range("", "Hello"));
    CHECK_FALSE(correction_range("Same", "Same"));
}

TEST_CASE("popup text: a correction highlights from the changed word to the end") {
    const auto r = correction_range("Move the meeting to Friday", "Move the meeting to Thursday.");
    REQUIRE(r);
    CHECK(r->begin == 20);
    CHECK(r->end == 29);
}

TEST_CASE("popup text: a polished run cut back inside a word highlights that word") {
    const auto r = correction_range("Move it to Friday no wait", "Move it t");
    // The highlight backs up to the start of the word the texts diverge in.
    REQUIRE(r);
    CHECK(r->begin == 8);
}

TEST_CASE("popup text: a correction range never starts inside a UTF-8 character") {
    // "é" is two bytes; the texts differ in its second byte.
    const std::string before = "caf\xC3\xA9";
    const std::string after = "caf\xC3\xA8s";
    const auto r = correction_range(before, after);
    REQUIRE(r);
    CHECK(r->begin == 0);  // backed up to the word start
}

TEST_CASE("popup text: promoted range is the newly polished tail") {
    CHECK(*promoted_range("So the thing is,", "So the thing is, we ship") == ByteRange{16, 24});
    CHECK_FALSE(promoted_range("abc", "abc"));
    CHECK_FALSE(promoted_range("abc", "abd e"));
}

TEST_CASE("popup text: visible lines stay within 1..max_lines and scroll the rest") {
    CHECK(visible_lines(0, 4) == 1);
    CHECK(visible_lines(3, 4) == 3);
    CHECK(visible_lines(9, 4) == 4);
    CHECK(visible_lines(2, 0) == 1);
    CHECK(scrolled_lines(3, 4) == 0);
    CHECK(scrolled_lines(9, 4) == 5);
}

TEST_CASE("popup text: the surface fits the tallest card and its shadow room") {
    // 24 + (14 + 22*4 + 14 + 28) + 24
    CHECK(popup_surface_h(4) == 192);
    CHECK(popup_surface_h(0) == popup_surface_h(1));
    CHECK(kPopupSurfaceBottom == 28);
}

TEST_CASE("popup text: listening animates three dots, reduced motion keeps the ellipsis") {
    const Content c = Placeholder{"Listening…", true};
    const auto a = text_spec(c, true);
    CHECK(a.kind == TextKind::Listening);
    CHECK(a.text == "Listening...");
    CHECK(a.dots == ByteRange{9, 12});
    const auto r = text_spec(c, false);
    CHECK(r.text == "Listening…");
    CHECK(r.dots.empty());
}

TEST_CASE("popup text: other placeholders are static notes") {
    const auto t = text_spec(Placeholder{"No speech detected", false}, true);
    CHECK(t.kind == TextKind::Note);
    CHECK(t.text == "No speech detected");
}

TEST_CASE("popup text: zones and struck text become specs") {
    const auto z = text_spec(Zones{"A.", "b", "c"}, true);
    CHECK(z.kind == TextKind::Zones);
    CHECK(z.text == "A. b c");
    CHECK(z.live == ByteRange{5, 6});
    CHECK(text_spec(Struck{"gone"}, true).kind == TextKind::Struck);
    CHECK(text_spec(NoContent{}, true).kind == TextKind::Empty);
}

TEST_CASE("popup text: listening dots cycle 0..3 every step") {
    CHECK(listening_dots(0.0) == 0);
    CHECK(listening_dots(kListeningDotStepS * 1.5) == 1);
    CHECK(listening_dots(kListeningDotStepS * 3.5) == 3);
    CHECK(listening_dots(kListeningDotStepS * 4.5) == 0);
    CHECK(listening_dots(-1.0) == 0);
}

TEST_CASE("popup text: a promoted chunk crossfades out of pending into polished") {
    const auto before = text_spec(Zones{"So the thing is,", "we ship", "on"}, true);
    const auto after = text_spec(Zones{"So the thing is, we ship", "", "on friday"}, true);
    const auto f = crossfade(before, after);
    REQUIRE(f);
    CHECK(f->out == before.pending);
    CHECK(after.text.substr(f->in.begin, f->in.end - f->in.begin) == " we ship");
}

TEST_CASE("popup text: finishing crossfades the live run into pending") {
    const auto before = text_spec(Zones{"Hi.", "", "there"}, true);
    const auto after = text_spec(Zones{"Hi.", "there", ""}, true);
    const auto f = crossfade(before, after);
    REQUIRE(f);
    CHECK(f->out == before.live);
    CHECK(after.text.substr(f->in.begin, f->in.end - f->in.begin) == "there");
}

TEST_CASE("popup text: live-only updates and first text do not crossfade") {
    CHECK_FALSE(crossfade(text_spec(Zones{"A.", "", "b"}, true),
                          text_spec(Zones{"A.", "", "bc"}, true)));
    CHECK_FALSE(crossfade(text_spec(Placeholder{"Listening…", true}, true),
                          text_spec(Zones{"", "", "so"}, true)));
}

TEST_CASE("popup text: a rewritten polished run is a correction in the joined text") {
    const auto before = text_spec(Zones{"Move it to Friday.", "", "no wait"}, true);
    const auto after = text_spec(Zones{"Move it to Thursday.", "", ""}, true);
    const auto r = correction(before, after);
    REQUIRE(r);
    CHECK(after.text.substr(r->begin, r->end - r->begin) == "Thursday.");
    CHECK_FALSE(correction(after, text_spec(Zones{"Move it to Thursday. And", "", ""}, true)));
}

TEST_CASE("popup text: dropping whole trailing words is no correction") {
    CHECK_FALSE(correction_range("Move it to Friday.", "Move it to"));
    CHECK_FALSE(correction_range("Move it to Friday.", "Move it to "));
    // Cut inside a word: that word changed, so it is highlighted.
    const auto r = correction_range("Move it to Friday.", "Move it to Fri");
    REQUIRE(r);
    CHECK(r->begin == 11);
}
