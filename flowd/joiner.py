"""Join resolved chunks into the final text with code, never the LLM (spec 6.5)."""

from __future__ import annotations

import re
from collections.abc import Sequence

_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_MULTISPACE_RE = re.compile(r"\s+")
#: Start of a sentence: string start, or terminal punctuation plus whitespace.
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+)([a-z])")
#: Punctuation that cannot end dictated text; the final chunk often trails one
#: because the speaker stopped mid-clause.
_TRAILING_SOFT_PUNCT_RE = re.compile(r"[,;]+$")
#: "weariness,?" — seen from the cleanup LLM when the speaker trailed off on a
#: comma. The terminal mark wins; the comma before it is noise.
_SOFT_BEFORE_TERMINAL_RE = re.compile(r"[,;]+([.!?])")
#: A colon is kept: dictation that introduces a list legitimately ends in one.
_TERMINALS = ".!?:"


def join_chunks(texts: Sequence[str]) -> str:
    joined = " ".join(t.strip() for t in texts if t and t.strip())
    if not joined:
        return ""
    joined = _MULTISPACE_RE.sub(" ", joined)
    joined = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", joined).strip()
    joined = _SOFT_BEFORE_TERMINAL_RE.sub(r"\1", joined)
    joined = _TRAILING_SOFT_PUNCT_RE.sub("", joined).strip()
    if not joined:
        return ""
    joined = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), joined)
    if joined[-1] not in _TERMINALS:
        joined += "."
    return joined


#: A pronoun that stays capitalised mid-sentence: "I", "I'm", "I'll".
_CAPITAL_I_RE = re.compile(r"^I(\b|')")


def stitch(pairs: Sequence[tuple[str, str]], *, sentence: bool = True) -> str:
    """Join chunk texts polished separately, repairing the seams (spec 6.5 step 5).

    Each pair is `(raw, text)`. A chunk is cut on a pause or a word cap, often
    mid-sentence, and the LLM rounds each one off as a sentence. Where the raw
    text did not end a sentence, the period the LLM added is dropped, and the
    next chunk's capital is undone when its raw text started in lowercase —
    so "move the meeting. To Friday." comes out "move the meeting to Friday.".
    A "?" or "!" is kept: the LLM heard a question, and that is not a seam.
    A period in the raw text is a seam too when the next chunk continues in
    lowercase, since the recognizer puts one at every pause.

    `sentence=False` (code mode) only joins with single spaces: a command has
    no sentences to repair.
    """
    if not sentence:
        return " ".join(t.strip() for _, t in pairs if t.strip())
    texts = [text.strip() for _, text in pairs]
    for i in range(len(pairs) - 1):
        raw, nxt_raw = pairs[i][0].strip(), pairs[i + 1][0].strip()
        if not texts[i] or not texts[i + 1] or not raw:
            continue
        # Moonshine ends every line it commits with a period, pauses included,
        # so a raw "." is a sentence end only when the next chunk starts one.
        # "?", "!" and ":" are never put there by a pause.
        continues = nxt_raw[:1].islower()
        if raw[-1] in _TERMINALS and not (raw[-1] == "." and continues):
            continue
        if texts[i].endswith("."):
            texts[i] = texts[i][:-1]
        first = texts[i + 1]
        if continues and first[:1].isupper() and not _CAPITAL_I_RE.match(first):
            texts[i + 1] = first[:1].lower() + first[1:]
    return join_chunks(texts)
