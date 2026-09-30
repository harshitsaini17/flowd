#include "popup_text.hpp"

#include <algorithm>
#include <cmath>
#include <variant>

#include "placement.hpp"

namespace flowd {

namespace {

bool is_space(char c) { return c == ' ' || c == '\n' || c == '\t'; }

// True for a byte that continues a UTF-8 sequence, so a range never splits a
// character.
bool is_continuation(char c) { return (static_cast<unsigned char>(c) & 0xC0) == 0x80; }

// Appends run with a separating space when neither side carries one, and
// returns the run's range. Matches how PopupModel joins zones.
ByteRange append_zone(std::string& out, const std::string& run) {
    if (run.empty()) return {out.size(), out.size()};
    if (!out.empty() && !is_space(out.back()) && !is_space(run.front())) out += ' ';
    const std::size_t begin = out.size();
    out += run;
    return {begin, out.size()};
}

}  // namespace

JoinedZones join_zones(const Zones& z) {
    JoinedZones j;
    j.polished = append_zone(j.text, z.polished);
    j.pending = append_zone(j.text, z.pending);
    j.live = append_zone(j.text, z.live);
    return j;
}

std::optional<ByteRange> correction_range(std::string_view before, std::string_view after) {
    if (after.empty() || after.starts_with(before)) return std::nullopt;
    const auto [b, a] = std::mismatch(before.begin(), before.end(), after.begin(), after.end());
    std::size_t start = static_cast<std::size_t>(a - after.begin());
    // Back up to the start of the word the change landed in, so the
    // highlight covers whole words rather than the tail of one.
    while (start > 0 && !is_space(after[start - 1])) --start;
    while (start < after.size() && is_continuation(after[start])) ++start;
    if (start >= after.size()) return std::nullopt;
    return ByteRange{start, after.size()};
}

std::optional<ByteRange> promoted_range(std::string_view before, std::string_view after) {
    if (after.size() <= before.size() || !after.starts_with(before)) return std::nullopt;
    return ByteRange{before.size(), after.size()};
}

TextSpec text_spec(const Content& c, bool animate_dots) {
    TextSpec t;
    if (const auto* p = std::get_if<Placeholder>(&c)) {
        t.text = p->text;
        if (!p->listening) {
            t.kind = TextKind::Note;
            return t;
        }
        t.kind = TextKind::Listening;
        // Swap the one-glyph ellipsis for three dots that can fade apart.
        constexpr std::string_view kEllipsis = "…";
        if (animate_dots && t.text.ends_with(kEllipsis)) {
            t.text.resize(t.text.size() - kEllipsis.size());
            const std::size_t begin = t.text.size();
            t.text.append(kListeningDots, '.');
            t.dots = {begin, t.text.size()};
        }
        return t;
    }
    if (const auto* z = std::get_if<Zones>(&c)) {
        JoinedZones j = join_zones(*z);
        t.kind = TextKind::Zones;
        t.text = std::move(j.text);
        t.polished = j.polished;
        t.pending = j.pending;
        t.live = j.live;
        return t;
    }
    if (const auto* s = std::get_if<Struck>(&c)) {
        t.kind = TextKind::Struck;
        t.text = s->text;
    }
    return t;
}

int listening_dots(double t_s) {
    if (!std::isfinite(t_s) || t_s < 0.0) return 0;
    const auto step = static_cast<long long>(std::floor(t_s / kListeningDotStepS));
    return static_cast<int>(step % (kListeningDots + 1));
}

namespace {

std::string_view slice(const std::string& s, ByteRange r) {
    return std::string_view(s).substr(r.begin, r.end - r.begin);
}

}  // namespace

std::optional<Crossfade> crossfade(const TextSpec& before, const TextSpec& after) {
    if (before.kind != TextKind::Zones || after.kind != TextKind::Zones) return std::nullopt;
    const std::string_view old_polished = slice(before.text, before.polished);
    const std::string_view new_polished = slice(after.text, after.polished);
    if (const auto grown = promoted_range(old_polished, new_polished)) {
        // A pending chunk came back polished: the old pending run gives way
        // to the new polished tail.
        if (before.pending.empty()) return std::nullopt;
        return Crossfade{before.pending,
                         {after.polished.begin + grown->begin, after.polished.begin + grown->end}};
    }
    // Recording ended: the live run turned into the tail of pending.
    if (!before.live.empty() && after.live.empty() && old_polished == new_polished) {
        const std::string_view old_live = slice(before.text, before.live);
        const std::string_view new_pending = slice(after.text, after.pending);
        if (!new_pending.ends_with(old_live)) return std::nullopt;
        return Crossfade{before.live, {after.pending.end - old_live.size(), after.pending.end}};
    }
    return std::nullopt;
}

std::optional<ByteRange> correction(const TextSpec& before, const TextSpec& after) {
    if (before.kind != TextKind::Zones || after.kind != TextKind::Zones) return std::nullopt;
    const auto r = correction_range(slice(before.text, before.polished), slice(after.text, after.polished));
    if (!r) return std::nullopt;
    return ByteRange{after.polished.begin + r->begin, after.polished.begin + r->end};
}

int visible_lines(int total_lines, int max_lines) {
    const int cap = std::max(kPopupMinLines, max_lines);
    return std::clamp(total_lines, kPopupMinLines, cap);
}

int scrolled_lines(int total_lines, int max_lines) {
    return std::max(0, total_lines - visible_lines(total_lines, max_lines));
}

}  // namespace flowd
