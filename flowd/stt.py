"""Speech-to-text behind a streaming-shaped interface (spec 5.3)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeAlias

import numpy as np

from flowd.config import Stt

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Partial:
    """A still-changing hypothesis. Never leaves the overlay (spec 1)."""

    text: str


@dataclass(frozen=True, slots=True)
class Committed:
    """Text the engine will no longer revise."""

    text: str


Event: TypeAlias = Partial | Committed


class SttEngine(Protocol):
    def feed(self, pcm: np.ndarray) -> list[Event]:
        """Accept audio and return any events it produced."""

    def finalize(self) -> list[Event]:
        """Flush at end of session, committing whatever remains."""


class FakeSttEngine:
    """Scripted engine for deterministic tests; no model needed."""

    def __init__(self, script: Sequence[list[Event]]) -> None:
        self._script = list(script)
        self._index = 0

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if self._index >= len(self._script):
            return []
        events = self._script[self._index]
        self._index += 1
        return list(events)

    def finalize(self) -> list[Event]:
        remaining: list[Event] = []
        while self._index < len(self._script):
            remaining.extend(self._script[self._index])
            self._index += 1
        return remaining


class BatchSttEngine:
    """Phase 1: buffer the utterance, transcribe once at finalize.

    Emits no partials, so phase 1 has no live preview. Task 16 replaces this
    with the streaming engine behind the same interface.
    """

    def __init__(self, transcribe: Callable[[np.ndarray], str]) -> None:
        self._transcribe = transcribe
        self._buffer: list[np.ndarray] = []

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if pcm.size:
            self._buffer.append(np.asarray(pcm, dtype=np.float32))
        return []

    def finalize(self) -> list[Event]:
        if not self._buffer:
            return []
        audio = np.concatenate(self._buffer)
        self._buffer.clear()
        text = self._transcribe(audio).strip()
        return [Committed(text)] if text else []


def _transcript_text(transcript: Any) -> str:
    """Join a Moonshine `Transcript`'s lines into plain dictated text.

    `str(transcript)` renders each line as "[12.34s] words", so the timestamps
    would be typed into the user's text box. Reading `line.text` avoids that.
    """
    lines = [str(line.text).strip() for line in transcript.lines]
    return " ".join(line for line in lines if line)


def _split_model_name(model: str) -> tuple[str, str]:
    """Split a model directory name into the architecture and language Moonshine wants.

    `stt.model` names a model as Moonshine caches it, e.g. "medium-streaming-en",
    but `string_to_model_arch` accepts only the architecture ("medium-streaming")
    and rejects the full name. A trailing two-letter segment is the language tag;
    every published architecture ends in a longer word, so the two never collide.
    """
    head, _, tail = model.rpartition("-")
    if head and len(tail) == 2 and tail.isalpha() and tail.islower():
        return head, tail
    return model, "en"


def load_engine(cfg: Stt, model_dir: Path, sample_rate: int = 16000) -> SttEngine:
    """Load Moonshine once at daemon start; never reload per session (spec 5.3).

    `model_dir` is accepted for symmetry with the LLM weights but unused:
    Moonshine fetches and CRC32C-verifies its own files under
    `$XDG_CACHE_HOME/moonshine_voice/`, which ADR 0001 decided not to duplicate.

    `sample_rate` must match the capture rate. Moonshine resamples internally
    from whatever rate it is told, so a wrong value transcribes as gibberish
    rather than failing (ADR 0001).
    """
    from moonshine_voice import Transcriber, get_model_for_language, string_to_model_arch

    arch_name, language = _split_model_name(cfg.model)
    model_path, arch = get_model_for_language(language, string_to_model_arch(arch_name))
    transcriber = Transcriber(model_path, arch)
    log.info("loaded STT model %s (%s) from %s", cfg.model, arch.name, model_path)

    def transcribe(pcm: np.ndarray) -> str:
        transcript = transcriber.transcribe_without_streaming(pcm.tolist(), sample_rate)
        return _transcript_text(transcript)

    return BatchSttEngine(transcribe=transcribe)
