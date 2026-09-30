"""Chunked streaming cleanup: the single-flight scheduler (spec 6.2-6.5).

Committed text is polished in chunks while the user is still speaking, so at
release only the last chunk still needs the LLM. One request is in flight at a
time; whatever was committed meanwhile goes next, as one chunk.

The scheduler knows nothing about HTTP, guardrails or metrics: `polish` is the
daemon's function that runs the LLM and the guardrails and returns accepted
text or None, and `fallback` is `basic_clean`. That keeps this pure ordering
logic, testable without a server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from flowd.config import Chunking
from flowd.guardrails import starts_with_correction_cue
from flowd.session import Chunk, Session

log = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class Polish(Protocol):
    def __call__(
        self, raw: str, *, chunk_id: int, context: str, merged: bool, timeout_ms: int
    ) -> Awaitable[str | None]: ...

    # `chunk_id` is the chunk's `Chunk.id`, unique within the session, so the
    # caller can attach what it learns to that chunk.


class Scheduler:
    """Owns the chunks of one session, from commit to resolution."""

    def __init__(
        self,
        session: Session,
        polish: Polish,
        fallback: Callable[[str], str],
        chunking: Chunking,
        *,
        timeout_ms: int,
        on_change: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self._polish = polish
        self._fallback = fallback
        self._cfg = chunking
        self._timeout_ms = timeout_ms
        self._on_change = on_change
        self._clock = clock
        self._inflight: asyncio.Task[None] | None = None
        self._changed = asyncio.Event()
        self._cancelled = False
        #: Set by `flush`: chunks sent from now on get what is left of its budget.
        self._deadline: float | None = None
        #: The whole session was under `short_bypass_words` (spec 9.1).
        self.bypassed = False
        #: Chunks the release deadline resolved with fallback text.
        self.abandoned = 0

    # --- inputs -----------------------------------------------------------

    def on_committed(self, text: str) -> None:
        if self._cancelled or not text.strip():
            return
        self.session.pending_raw.append(text.strip())
        self._maybe_dispatch()

    async def flush(self, final_timeout_ms: int) -> None:
        """spec 6.5 steps 3-4: send the remainder, wait for every chunk or the deadline."""
        loop = asyncio.get_running_loop()
        self._deadline = loop.time() + final_timeout_ms / 1000
        self._maybe_dispatch(final=True)
        try:
            async with asyncio.timeout_at(self._deadline):
                while not self._cancelled and not self._settled():
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            self._abandon()

    def cancel(self) -> None:
        """Stop work for a discarded session; nothing it resolves is used."""
        self._cancelled = True
        self.session.pending_raw.clear()
        if self._inflight is not None:
            self._inflight.cancel()
        self._changed.set()  # wake a `flush` so the discard is not held up

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # --- scheduling -------------------------------------------------------

    def _settled(self) -> bool:
        return (
            self._inflight is None
            and not self.session.pending_raw
            and all(c.resolved for c in self.session.chunks)
        )

    def _maybe_dispatch(self, final: bool = False) -> None:
        if self._inflight is not None or self._cancelled:
            return
        session = self.session
        raw = " ".join(session.pending_raw)
        if not raw:
            return
        words = len(raw.split())
        if final and not session.chunks and words < self._cfg.short_bypass_words:
            # spec 9.1: a session this short is not worth the round trip.
            self.bypassed = True
            session.pending_raw.clear()
            self._resolve(session.add_chunk(raw), None)
            return
        if words < self._cfg.min_chunk_words and not final:
            return
        session.pending_raw.clear()
        merged = False
        previous = self._last_resolved()
        if previous is not None and starts_with_correction_cue(raw, self._cfg.correction_cues):
            # spec 6.4: fold the corrected chunk into this one, at most one deep.
            previous.state = "MERGED"
            raw = f"{previous.raw} {raw}"
            merged = True
        chunk = session.add_chunk(raw)
        if merged and previous is not None:
            chunk.version = previous.version + 1
        chunk.state = "INFLIGHT"
        context = self._context()
        self._inflight = asyncio.get_running_loop().create_task(
            self._run(chunk, chunk.version, context, merged)
        )
        self._notify()

    def _last_resolved(self) -> Chunk | None:
        visible = self.session.visible_chunks()
        if visible and visible[-1].resolved:
            return visible[-1]
        return None

    def _context(self) -> str:
        """The last `context_sentences` polished sentences, read-only (spec 6.2)."""
        polished = " ".join(
            c.text for c in self.session.visible_chunks() if c.resolved and c.polished
        )
        if not polished or self._cfg.context_sentences <= 0:
            return ""
        sentences = _SENTENCE_SPLIT_RE.split(polished.strip())
        return " ".join(sentences[-self._cfg.context_sentences :])

    def _budget_ms(self) -> int:
        if self._deadline is None:
            return self._timeout_ms
        left = (self._deadline - asyncio.get_running_loop().time()) * 1000
        return max(1, int(left))

    async def _run(self, chunk: Chunk, version: int, context: str, merged: bool) -> None:
        try:
            text = await self._polish(
                chunk.raw,
                chunk_id=chunk.id,
                context=context,
                merged=merged,
                timeout_ms=self._budget_ms(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A polish that raises must not strand the session in FINALIZING.
            log.exception("chunk cleanup raised; using fallback")
            text = None
        if self._cancelled:
            return
        self._inflight = None
        if chunk.state == "MERGED" or chunk.version != version:
            return  # stale (spec 6.3)
        self._resolve(chunk, text)
        self._maybe_dispatch(final=self._deadline is not None)

    def _resolve(self, chunk: Chunk, text: str | None) -> None:
        if text is None:
            chunk.polished, chunk.state = self._fallback(chunk.raw), "FALLBACK"
        else:
            chunk.polished, chunk.state = text, "DONE"
        chunk.t_resolved = self._clock()
        self._notify()

    def _abandon(self) -> None:
        """The release deadline passed: everything unresolved gets fallback text."""
        if self._inflight is not None:
            self._inflight.cancel()
            self._inflight = None
        if self.session.pending_raw:
            self.session.add_chunk(" ".join(self.session.pending_raw))
            self.session.pending_raw.clear()
        for chunk in self.session.visible_chunks():
            if not chunk.resolved:
                self.abandoned += 1
                self._resolve(chunk, None)

    def _notify(self) -> None:
        self._changed.set()
        if self._on_change is not None:
            with contextlib.suppress(Exception):
                self._on_change()
