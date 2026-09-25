"""Deterministic fallback cleanup, under 1 ms (spec 7.5)."""

from __future__ import annotations

import re
from collections.abc import Mapping

#: Fillers removed wherever they stand alone as a word.
_ALWAYS_FILLERS = ("um", "uh", "er", "ah", "hmm", "mm", "erm")
#: Removed only when set off by commas, so "I like pizza" survives.
_HEDGED_FILLERS = ("like", "you know", "sort of", "kind of", "i mean")

_FILLER_RE = re.compile(r"\b(?:" + "|".join(_ALWAYS_FILLERS) + r")\b[,]?\s*", re.IGNORECASE)
#: The comma that opens the aside is consumed with it: "to, like, the store"
#: must become "to the store", not "to, the store".
_HEDGED_RE = re.compile(
    r",?\s*\b(?:" + "|".join(_HEDGED_FILLERS) + r")\b\s*,",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_MULTISPACE_RE = re.compile(r"\s+")
_STANDALONE_I_RE = re.compile(r"\bi\b")


def basic_clean(raw: str, replacements: Mapping[str, str] | None = None) -> str:
    """Regex-clean dictated text. Used whenever the LLM is unavailable or rejected."""
    text = raw.strip()
    if not text:
        return ""

    text = _HEDGED_RE.sub(" ", text)
    text = _FILLER_RE.sub("", text)
    text = _REPEAT_RE.sub(r"\1", text)

    for source, target in (replacements or {}).items():
        # The target is text a user typed into vocab.toml, not a replacement
        # template: a lambda keeps a backslash in it literal, where a plain
        # string would be read as a group reference and raise re.error.
        text = re.sub(re.escape(source), lambda _m, t=target: t, text, flags=re.IGNORECASE)  # type: ignore[misc]

    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _MULTISPACE_RE.sub(" ", text).strip(" ,")
    if not text:
        return ""

    text = _STANDALONE_I_RE.sub("I", text)
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text
