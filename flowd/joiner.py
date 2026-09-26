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
#: A colon is kept: dictation that introduces a list legitimately ends in one.
_TERMINALS = ".!?:"


def join_chunks(texts: Sequence[str]) -> str:
    joined = " ".join(t.strip() for t in texts if t and t.strip())
    if not joined:
        return ""
    joined = _MULTISPACE_RE.sub(" ", joined)
    joined = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", joined).strip()
    joined = _TRAILING_SOFT_PUNCT_RE.sub("", joined).strip()
    if not joined:
        return ""
    joined = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), joined)
    if joined[-1] not in _TERMINALS:
        joined += "."
    return joined
