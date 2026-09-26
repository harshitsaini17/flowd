"""Speech-to-text behind a streaming-shaped interface (spec 5.3)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeAlias

import numpy as np

from flowd.committer import Committer
from flowd.config import Stt, Vad
from flowd.vad import SegmentationVad, load_vad

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

    def reset(self) -> None:
        """Discard the current session without committing it (spec 9.4 cancel).

        The daemon holds one engine for its whole life (spec 5.3: load the model
        once), so a cancelled session that left state behind would leak its
        audio and its transcript into whatever the user dictates next.
        """


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

    def reset(self) -> None:
        self._index = len(self._script)


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

    def reset(self) -> None:
        self._buffer.clear()


class StreamingSttEngine:
    """Moonshine's native streaming API, with commits ruled by the committer.

    ADR 0001 chose the native stream over spec 5.3's re-transcription fallback,
    and ADR 0002 makes the stream's own line timestamps the speech signal. So
    three things share one block of audio here: the stream produces line events,
    those events move the VAD's frontier, and the committer turns both into the
    commits spec 5.4 defines.

    One stream per dictation session. The stream accumulates a transcript
    internally, so a reused one would carry the previous session's lines into
    the next; it is built lazily on the first block rather than in
    `load_engine`, which runs at daemon start, where a stream would sit open
    through every session the user never begins.
    """

    def __init__(
        self,
        new_stream: Callable[[], Any],
        vad: SegmentationVad,
        committer: Committer,
        block_ms: int = 100,
        sample_rate: int = 16000,
        set_keyterms: Callable[[Sequence[str]], None] | None = None,
    ) -> None:
        self._new_stream = new_stream
        self._set_keyterms = set_keyterms
        self._vad = vad
        self._committer = committer
        self._block_ms = block_ms
        self._sample_rate = sample_rate
        self._stream: Any | None = None
        # Line text by id, in the order Moonshine first reported each line. A
        # line is revised in place under the same id, and completed lines stay:
        # the committer strips its committed prefix by word count, so the
        # hypothesis it sees must keep spanning the whole utterance.
        self._lines: dict[int, str] = {}
        self._pending: list[Any] = []
        self._last_partial = ""

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if pcm.size == 0:
            return []
        stream = self._ensure_stream()
        events: list[Event] = []

        # Listeners fire synchronously from inside `add_audio`, filling
        # `_pending` before it returns (verified against moonshine-voice 0.1.5).
        stream.add_audio(pcm, self._sample_rate)
        events.extend(self._drain_pending())

        frame = self._vad.process(pcm)
        committed = self._committer.on_silence(frame.silence_ms)
        if committed:
            events.append(Committed(committed))

        events.extend(self._partial())
        return events

    def finalize(self) -> list[Event]:
        if self._stream is None:
            return []
        self._stop_stream(self._stream)
        # `stop()` flushed nothing on 0.1.5, but a later release that flushes
        # would otherwise drop the last words of every session.
        events = self._drain_pending()
        committed = self._committer.finalize()
        if committed:
            events.append(Committed(committed))
        self._discard()
        return events

    def reset(self) -> None:
        """Drop the session without committing it (spec 9.4 cancel).

        Whatever the stream emitted on the way out is thrown away with it: the
        user cancelled, so nothing from this session may reach the target app.
        """
        if self._stream is not None:
            self._stop_stream(self._stream)
        self._discard()

    def set_keyterms(self, terms: Sequence[str]) -> None:
        """Bias recognition towards `terms` (vocab.toml `[terms]`).

        Moonshine applies this from its next decode, including mid-stream, and
        an empty sequence turns biasing off.
        """
        if self._set_keyterms is not None:
            self._set_keyterms(list(terms))

    def _ensure_stream(self) -> Any:
        if self._stream is None:
            stream = self._new_stream()
            stream.add_listener(self._record)
            stream.start()
            self._stream = stream
        return self._stream

    def _record(self, event: Any) -> None:
        """The stream's listener. A method, not `self._pending.append`: the bound
        method would hold the list it was taken from, so rebinding `_pending`
        while draining would orphan every later event."""
        self._pending.append(event)

    def _stop_stream(self, stream: Any) -> None:
        try:
            stream.stop()
        except Exception:  # a failed stop must not lose what the session already said
            log.warning("STT stream did not stop cleanly", exc_info=True)

    def _discard(self) -> None:
        self._stream = None
        self._pending.clear()
        self._lines.clear()
        self._last_partial = ""
        self._committer.reset()
        self._vad.reset()

    def _drain_pending(self) -> list[Event]:
        """Fold the events of one block into the committer, in the order fired.

        Each event is folded before the next is read, so a line completing
        commits the text up to itself and not the still-provisional line that
        arrived after it in the same block.
        """
        pending = list(self._pending)
        self._pending.clear()
        events: list[Event] = []
        for event in pending:
            line = event.line
            self._lines[line.line_id] = str(line.text).strip()
            self._vad.observe_frontier((line.start_time + line.duration) * 1000)
            hypothesis = " ".join(text for text in self._lines.values() if text)
            committed = (
                self._committer.on_complete(hypothesis)
                if line.is_complete
                else self._committer.on_partial(hypothesis)
            )
            if committed:
                events.append(Committed(committed))
        return events

    def _partial(self) -> list[Event]:
        """The uncommitted tail, emitted only when it changed.

        Moonshine revises a line in place, so most blocks leave the hypothesis
        untouched and the overlay has nothing to redraw. An emptied tail updates
        what we last showed without emitting: it means a commit just took the
        words, and the overlay learns that from the `Committed` event.
        """
        remainder = self._committer.uncommitted_text
        if remainder == self._last_partial:
            return []
        self._last_partial = remainder
        return [Partial(remainder)] if remainder else []


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


def load_engine(
    cfg: Stt,
    model_dir: Path,
    sample_rate: int = 16000,
    vad_cfg: Vad | None = None,
    block_ms: int = 100,
) -> SttEngine:
    """Load Moonshine once at daemon start; never reload per session (spec 5.3).

    With `vad_cfg` the result streams (`StreamingSttEngine`); without it, it
    buffers and transcribes once (`BatchSttEngine`, phase 1's behaviour), which
    is what a caller that only wants a whole-file transcript should ask for.

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

    if vad_cfg is None:

        def transcribe(pcm: np.ndarray) -> str:
            transcript = transcriber.transcribe_without_streaming(pcm.tolist(), sample_rate)
            return _transcript_text(transcript)

        return BatchSttEngine(transcribe=transcribe)

    # How often the stream re-runs the decoder, and so the floor on how soon a
    # first partial can appear (spec 10.1 budgets 300 ms). ADR 0001 measured the
    # model at ~1.05x realtime here, so asking for updates much faster than this
    # buys latency the decoder cannot deliver and spends cores the overlay and
    # llama-server also want.
    update_interval = max(block_ms, 200) / 1000

    return StreamingSttEngine(
        new_stream=lambda: transcriber.create_stream(update_interval=update_interval),
        vad=load_vad(vad_cfg, model_dir, block_ms=block_ms),
        committer=Committer(
            max_uncommitted_words=cfg.max_uncommitted_words,
            commit_silence_ms=vad_cfg.commit_silence_ms,
        ),
        block_ms=block_ms,
        sample_rate=sample_rate,
        set_keyterms=transcriber.set_keyterms,
    )
