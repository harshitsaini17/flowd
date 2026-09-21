"""Per-app modes as pipeline styles (spec 7.3, ADR 0009).

Spec 7.3 has modes append an instruction to the system prompt. Sotto takes a
fixed completion prompt with no instruction slot (ADR 0006), so each mode is
instead a style: whether the LLM runs, whether sentence rules apply at the
join, and a last code-only touch. Everything here is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Style:
    #: Send chunks to the cleanup LLM at all.
    use_llm: bool = True
    #: Capitalise sentence starts and end with terminal punctuation at the join.
    sentence: bool = True
    #: Drop a single final period: chat messages rarely end in one.
    drop_final_period: bool = False


_STYLES = {
    "default": Style(),
    "email": Style(),
    # "Minimal edits. Keep technical terms, casing and symbols. Do not
    # restructure." A prose rewriter can only do less than that by not running.
    "code": Style(use_llm=False, sentence=False),
    "chat": Style(drop_final_period=True),
}


def style_for(mode: str) -> Style:
    return _STYLES.get(mode, _STYLES["default"])


def finish(text: str, style: Style) -> str:
    """The mode's last touch on the joined text."""
    if style.drop_final_period and text.endswith(".") and not text.endswith(".."):
        return text[:-1]
    return text
