"""Session and chunk data model (spec 4)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

ChunkState = Literal["PENDING", "INFLIGHT", "DONE", "FALLBACK", "MERGED"]

#: States in which a chunk will not change again, so finalizing need not wait.
_TERMINAL: frozenset[str] = frozenset({"DONE", "FALLBACK", "MERGED"})


@dataclass
class Chunk:
    id: int
    raw: str
    polished: str | None = None
    state: ChunkState = "PENDING"
    version: int = 1
    t_committed: float = field(default_factory=time.monotonic)
    t_resolved: float | None = None

    @property
    def resolved(self) -> bool:
        return self.state in _TERMINAL

    @property
    def text(self) -> str:
        """The best available text: polished when it passed, else raw.

        The comparison is against None, not falsiness: the cleanup model
        legitimately returns "" for a chunk that was pure filler, and falling
        back to raw there would re-inject what cleanup removed.
        """
        return self.polished if self.polished is not None else self.raw


@dataclass
class Session:
    id: str
    mode: str = "default"
    app_id: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    chunks: list[Chunk] = field(default_factory=list)
    live_partial: str = ""
    pending_raw: list[str] = field(default_factory=list)

    def add_chunk(self, raw: str) -> Chunk:
        chunk = Chunk(id=len(self.chunks) + 1, raw=raw)
        self.chunks.append(chunk)
        return chunk

    def visible_chunks(self) -> list[Chunk]:
        """Chunks that contribute text; merged ones have been folded away."""
        return [c for c in self.chunks if c.state != "MERGED"]
