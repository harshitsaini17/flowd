#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>

#include "popup_model.hpp"

// Text decisions for the popup's one Pango paragraph: where each zone's bytes
// sit, which polished run a self-correction changed, and how far the text
// box scrolls. No GTK here, so all of it is unit-tested.
namespace flowd {

// A half-open byte range [begin, end) into a UTF-8 string.
struct ByteRange {
    std::size_t begin = 0;
    std::size_t end = 0;

    bool empty() const { return end <= begin; }
    bool operator==(const ByteRange&) const = default;
};

// The three zones joined into one paragraph (design.md "The three text
// zones": inline, separated by a normal space), with each zone's range. A
// separating space belongs to no zone, so it takes no zone style.
struct JoinedZones {
    std::string text;
    ByteRange polished, pending, live;
};

JoinedZones join_zones(const Zones& z);

// design.md "Self-correction merge": the polished run changed rather than
// grew. Returns the range in `after` from the start of the first changed word
// to its end, or nothing when `after` only extends `before` (or is empty).
std::optional<ByteRange> correction_range(std::string_view before, std::string_view after);

// design.md "Pending → polished swap": the bytes of `after` that were added
// to a polished run which only grew, or nothing when it did not grow.
std::optional<ByteRange> promoted_range(std::string_view before, std::string_view after);

// What the text box draws, reduced to plain text and byte ranges, so the
// widget can tell whether its layout is stale by comparing two of these.
enum class TextKind {
    Empty,
    Note,       // a placeholder in text-2 ("No speech detected")
    Listening,  // "Listening" in text-2 italic, with its ellipsis dots
    Zones,      // the three streaming zones
    Struck,     // the cancelled transcript, dimmed and struck through
};

struct TextSpec {
    TextKind kind = TextKind::Empty;
    std::string text;
    ByteRange polished, pending, live;
    // Listening only: the three ellipsis dots, one byte each, when they are
    // animated; empty when drawn as the static "…".
    ByteRange dots;

    bool operator==(const TextSpec&) const = default;
};

// design.md "States" 1: the listening dots fade in one after another; under
// reduced motion the placeholder reads a static "Listening…".
TextSpec text_spec(const Content& c, bool animate_dots);

// The dots shown at t seconds into the placeholder, 0..3, cycling one step
// every kListeningDotStepS.
constexpr double kListeningDotStepS = 0.3;
constexpr int kListeningDots = 3;
int listening_dots(double t_s);

// A zone change that crossfades: `out` fades out of the previous layout
// while `in` fades into the new one (design.md "Pending → polished swap",
// and "States" 3, where the live run restyles to pending over dur-fast).
struct Crossfade {
    ByteRange out;  // in before.text
    ByteRange in;   // in after.text
};
std::optional<Crossfade> crossfade(const TextSpec& before, const TextSpec& after);

// The polished range a self-correction rewrote, in after.text, or nothing.
std::optional<ByteRange> correction(const TextSpec& before, const TextSpec& after);

// The text box shows 1..max_lines lines of the paragraph (design.md "Popup
// placement": the card holds 1-4 lines, so never fewer than one).
int visible_lines(int total_lines, int max_lines);

// Lines scrolled off the top so the last line stays visible (design.md
// "Auto-scroll").
int scrolled_lines(int total_lines, int max_lines);

}  // namespace flowd
