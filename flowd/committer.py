"""Deciding when raw text stops changing (spec 5.4).

Moonshine revises its hypothesis as more audio arrives, so text is committed
only once it is stable: when the engine marks a line complete, when VAD reports
a pause, or — during speech long enough that neither has happened yet — by the
stable-prefix rule.

Committing is one-way. Committed text is appended to the session's pending raw
buffer and handed to the scheduler, on its way to the target app, so every rule
here errs towards holding text back: spec 13.2 forbids typing partial or
unpolished text, and `finalize` at release flushes whatever never settled.
"""

from __future__ import annotations

import logging
from collections import deque

log = logging.getLogger(__name__)


class Committer:
    """Accumulates hypotheses and decides which words have stopped changing.

    The three constructor defaults that are also config keys — spec 8's
    `max_uncommitted_words` and `commit_silence_ms` — are passed in by the STT
    engine rather than read here, so this stays pure logic with no config or I/O.
    """

    def __init__(
        self,
        max_uncommitted_words: int = 25,
        stability_window: int = 3,
        keep_uncommitted: int = 3,
        commit_silence_ms: int = 350,
    ) -> None:
        self._max_uncommitted = max_uncommitted_words
        self._keep = keep_uncommitted
        self._commit_silence_ms = commit_silence_ms
        self._committed: list[str] = []
        self._uncommitted: list[str] = []
        #: Recent uncommitted word lists, newest last, for the stability check.
        self._stability_window = stability_window
        self._history: deque[list[str]] = deque(maxlen=stability_window)

    @property
    def committed_text(self) -> str:
        return " ".join(self._committed)

    @property
    def uncommitted_text(self) -> str:
        return " ".join(self._uncommitted)

    def reset(self) -> None:
        self._committed.clear()
        self._uncommitted.clear()
        self._history.clear()

    def on_partial(self, text: str) -> str | None:
        """Accept a new hypothesis for the whole utterance.

        The engine reports the full utterance, so the already-committed prefix is
        stripped before the remainder is considered.
        """
        words = text.split()
        if not words:
            return None
        self._uncommitted = self._strip_committed(words)
        self._history.append(list(self._uncommitted))
        return self._maybe_commit_stable_prefix()

    def _strip_committed(self, words: list[str]) -> list[str]:
        """Drop the committed prefix, tolerating engine revisions of later words.

        Stripping is by count rather than by matching text. Matching would look
        safer and is not: when the engine revises a word inside the committed
        prefix, a text match resynchronises to the wrong place and re-commits
        words the target app already received. The count is always right about
        how many words have left, which is the only question here.
        """
        n = len(self._committed)
        if n == 0:
            return words
        if len(words) < n:
            # The engine shrank its hypothesis below what has already been
            # committed and sent onward. There is no prefix left to strip, and
            # slicing by count anyway would commit a fragment of a real word.
            return []
        return words[n:]

    def _maybe_commit_stable_prefix(self) -> str | None:
        """spec 5.4 rule 3: past the cap, commit the prefix unchanged across the window."""
        if len(self._uncommitted) <= self._max_uncommitted:
            return None
        if len(self._history) < self._stability_window:
            return None

        stable = self._stable_prefix_length()
        # Always leave a tail uncommitted: the engine may still revise it.
        commit_count = min(stable, len(self._uncommitted) - self._keep)
        if commit_count <= 0:
            return None
        return self._commit(commit_count)

    def _stable_prefix_length(self) -> int:
        """How many leading words are identical across every remembered partial."""
        snapshots = list(self._history)
        shortest = min(len(s) for s in snapshots)
        length = 0
        while length < shortest and len({s[length] for s in snapshots}) == 1:
            length += 1
        return length

    def _commit(self, count: int) -> str:
        taken = self._uncommitted[:count]
        self._uncommitted = self._uncommitted[count:]
        self._committed.extend(taken)
        # History entries describe the old split, so they no longer apply.
        self._history.clear()
        text = " ".join(taken)
        log.debug("committed %d word(s)", count)
        return text

    def on_silence(self, silence_ms: int) -> str | None:
        """spec 5.4 rule 2: a VAD pause commits everything outstanding."""
        if silence_ms < self._commit_silence_ms or not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))

    def on_complete(self, text: str) -> str | None:
        """spec 5.4 rule 1: the engine says the line is done.

        ADR 0001 makes this the authoritative signal — Moonshine's own
        `LineCompleted`, decided by the model rather than by a heuristic — so an
        empty payload still commits whatever is pending rather than discarding
        it.
        """
        words = text.split()
        if words:
            self._uncommitted = self._strip_committed(words)
        if not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))

    def finalize(self) -> str | None:
        """Commit the remainder at release (spec 6.5 step 2).

        The one rule that does not wait for stability, because there is no more
        audio coming: whatever the engine last offered is as settled as it will
        get, and dropping it would lose the end of what someone said.
        """
        if not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))
