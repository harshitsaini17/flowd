"""Reject LLM output that looks like invention (spec 7.4, ADR 0007).

Each check returns its number so the caller can log it and count it in
`metrics.jsonl` without logging the text itself (spec 13.2). Checks run in
number order and the first failure wins: one reason per rejection keeps the
fallback histogram readable.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from flowd.config import Guardrails
from flowd.textclean import ALWAYS_FILLERS

#: A word, keeping an inner apostrophe so "don't" stays one token.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_DIGITS_RE = re.compile(r"\d+")
#: spec 7.4 check 5, anchored at the start of the output.
_CHATTER_RE = re.compile(r"^\s*(?:sure|certainly|here's|here is|okay,? here)\b", re.IGNORECASE)
#: spec 7.4 check 6. The `###` markers are Sotto's completion format (ADR 0006).
_LEAKED_TAGS = (
    "<new>",
    "</new>",
    "<context>",
    "</context>",
    "<vocab>",
    "</vocab>",
    "### input",
    "### output",
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: A context sentence shorter than this is too generic to count as repeated.
_MIN_REPEATED_SENTENCE_WORDS = 3


def _words(text: str) -> tuple[str, ...]:
    """Split a whitespace-separated word list; keeps the long lists below readable."""
    return tuple(text.split())


#: Stop-words for check 3 (novel words) and check 8 (repeats). Function words
#: carry no facts, so a rewrite may add or drop them freely.
STOP_WORDS: frozenset[str] = frozenset(
    _words(
        """a about above after again against all am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just me more most my myself no nor not now of off on
    once only or other our ours ourselves out over own same she should so some such than
    that the their theirs them themselves then there these they this those through to too
    under until up very was we were what when where which while who whom why will with
    would you your yours yourself yourselves i'm i've i'll i'd you're you've you'll we're
    we've they're it's that's there's don't doesn't didn't can't won't isn't aren't
    wasn't weren't let's hey okay oh yes yeah well"""
    )
)

#: Spoken numbers the model may legitimately write as digits ("five" -> "5").
_NUMBER_WORDS: dict[str, str] = {
    word: str(value)
    for value, word in enumerate(
        _words(
            "zero one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
        )
    )
}
_NUMBER_WORDS.update(
    {"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60"}
    | {"seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100"}
)

#: Check 7: pronouns whose appearance flips who is speaking to whom.
_PERSON_PRONOUNS = frozenset(_words("i me my mine you your yours we us our ours"))
#: Check 7: an output that opens with one of these is answering, not rewriting.
_ANSWER_WORDS = frozenset(_words("yes no yeah nope"))
#: Check 9: words that negate. Not "no": in dictation it is mostly a
#: self-correction cue ("five no wait six") that the rewrite rightly drops.
_NEGATIONS = frozenset(_words("not never cannot"))


def _is_negation(token: str) -> bool:
    return token in _NEGATIONS or token.endswith("n't")


def _negations(toks: Iterable[str]) -> int:
    return sum(1 for t in toks if _is_negation(t))


def _with_contraction_pronouns(toks: Iterable[str]) -> set[str]:
    """Tokens plus the pronoun inside each contraction: "i'm" also counts as "i"."""
    out = set()
    for t in toks:
        out.add(t)
        if "'" in t:
            out.add(t.split("'", 1)[0])
    return out


def tokens(text: str) -> list[str]:
    """Lower-cased word tokens; curly apostrophes fold to straight ones."""
    return _TOKEN_RE.findall(text.lower().replace("\u2019", "'"))


def novel_words(raw: str, output: str, extra: Iterable[str] = ()) -> tuple[list[str], int]:
    """Output content words found in neither `raw` nor `extra`, and the content-word count.

    `extra` is the context and vocabulary (spec 7.4 check 3). Public so the eval
    can list the novel words of *accepted* outputs for manual review (spec 11.3).
    """
    known = set(tokens(raw))
    known |= {_NUMBER_WORDS[t] for t in known if t in _NUMBER_WORDS}
    for text in extra:
        known.update(tokens(text))
    content = [t for t in tokens(output) if t not in STOP_WORDS]
    return [t for t in content if t not in known], len(content)


def check(
    raw: str,
    output: str,
    cfg: Guardrails,
    *,
    context: str = "",
    terms: Iterable[str] = (),
    merged: bool = False,
) -> int | None:
    """Return the number of the first failing check, or None when `output` passes.

    `merged` loosens the lower length bound for a self-correction (spec 7.4
    check 2), where keeping only the correction legitimately drops most words.
    """
    if not output.strip():
        return 1

    raw_tokens = tokens(raw)
    out_tokens = tokens(output)
    spoken = [t for t in raw_tokens if t not in ALWAYS_FILLERS]
    if not spoken:
        return 2
    ratio = len(out_tokens) / len(spoken)
    lower = cfg.len_ratio_min_merged if merged else cfg.len_ratio_min
    if not lower <= ratio <= cfg.len_ratio_max:
        return 2

    novel, content = novel_words(raw, output, (context, *terms))
    if content and len(novel) / content > cfg.novel_word_max:
        return 3

    out_digits = set(_DIGITS_RE.findall(output))
    if any(d not in out_digits for d in _DIGITS_RE.findall(raw)):
        return 4

    if _CHATTER_RE.match(output):
        return 5

    lowered = output.lower()
    if any(tag in lowered for tag in _LEAKED_TAGS):
        return 6
    for sentence in _SENTENCE_SPLIT_RE.split(context):
        sentence = sentence.strip().lower()
        if len(sentence.split()) >= _MIN_REPEATED_SENTENCE_WORDS and sentence in lowered:
            return 6

    raw_set = set(raw_tokens)
    if _PERSON_PRONOUNS & set(out_tokens) - _with_contraction_pronouns(raw_tokens):
        return 7
    if out_tokens[0] in _ANSWER_WORDS and out_tokens[0] not in raw_set:
        return 7

    raw_counts = Counter(t for t in raw_tokens if t not in STOP_WORDS)
    out_counts = Counter(t for t in out_tokens if t not in STOP_WORDS)
    if any(n > raw_counts[t] for t, n in out_counts.items() if t in raw_counts):
        return 8
    # Negations are stop words, so checks 3 and 8 never see them; one gained or
    # lost flips the meaning while every other check passes (ADR 0007).
    if _negations(out_tokens) != _negations(raw_tokens):
        return 9
    return None


def has_correction_cue(raw: str, cues: Iterable[str]) -> bool:
    """Whether `raw` contains a self-correction cue anywhere (spec 6.4's list).

    Anywhere rather than at the start, as spec 6.4 has it for chunks: phase 3
    cleans the whole session in one pass, so a correction is mid-text.
    """
    padded = f" {' '.join(tokens(raw))} "
    return any(f" {' '.join(tokens(cue))} " in padded for cue in cues)


def starts_with_correction_cue(raw: str, cues: Iterable[str]) -> bool:
    """Whether `raw` opens with a self-correction cue (spec 6.4, chunk start)."""
    words = tokens(raw)
    for cue in cues:
        cue_words = tokens(cue)
        if cue_words and words[: len(cue_words)] == cue_words:
            return True
    return False
