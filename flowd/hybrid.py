"""Live preview from Moonshine, committed text from an accurate offline model.

Moonshine streams, so it drives the overlay, but on a real speaker it was the
weak link: 20% WER on the reference recording against 6.7% for Parakeet TDT
0.6B v2 (ADR 0011). Parakeet is offline and needs context to be accurate, so
the session's audio is cut into pieces of 8-20 s at pauses, and each piece is
decoded on a worker while the user keeps talking. Only Parakeet's text is
committed; Moonshine's commits are used for nothing but the preview.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flowd.stt import Committed, Event, Partial, SttEngine

log = logging.getLogger(__name__)

#: Below this a block counts as a pause. The reference microphone's noise floor
#: is about -54 dBFS and its speech about -35 dBFS RMS.
QUIET_RMS = 10 ** (-45 / 20)
#: Parakeet loses accuracy on short pieces (11.4% WER at ~2.5 s, 6.7% at 20 s),
#: so a pause shorter into the piece than this does not end it.
MIN_PIECE_S = 8.0
#: A piece is cut by force here, at its quietest block since `MIN_PIECE_S`.
#: Also the most audio left to decode after release.
MAX_PIECE_S = 20.0
#: How long a pause must last to end a piece.
PAUSE_MS = 600
#: Threads for the offline decode. The machine's other six are shared by
#: Moonshine, llama-server and the overlay.
FINAL_THREADS = 4


def _malloc_trim() -> None:
    """Return freed heap to the kernel.

    Parakeet's decode buffers are freed after each piece, but glibc keeps the
    pages: 1.13 GB idle grew to 1.42 GB after two 70 s dictations and came back
    to 1.13 GB on a trim, so it is held memory, not a leak.
    """
    # Not glibc: nothing to hand back.
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


@dataclass(slots=True)
class _Piece:
    """One cut of the session's audio, decoding or decoded."""

    result: Future[str]
    seconds: float
    #: The live words this piece covers, as offsets into `_live_words`.
    #: Approximate, since Moonshine lags the audio; used for the preview and
    #: as the fallback text if the decode fails.
    start: int
    end: int


class HybridSttEngine:
    def __init__(
        self,
        live: SttEngine,
        transcribe: Callable[[np.ndarray], str],
        sample_rate: int = 16000,
        executor: Executor | None = None,
        trim: Callable[[], None] = _malloc_trim,
    ) -> None:
        self._live = live
        self._trim = trim
        self._transcribe = transcribe
        self._rate = sample_rate
        # One worker, so pieces decode in the order they were cut and never
        # two at once on a model that was loaded once.
        self._executor = executor or ThreadPoolExecutor(1, thread_name_prefix="flowd-final")
        self._blocks: list[np.ndarray] = []
        self._levels: list[float] = []
        #: Live word count after each block of the current piece.
        self._marks: list[int] = []
        self._quiet_ms = 0.0
        self._piece_start = 0
        self._pieces: list[_Piece] = []
        self._live_committed: list[str] = []
        self._live_partial: list[str] = []
        self._shown = 0
        self._last_preview = ""

    # --- SttEngine ------------------------------------------------------

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if pcm.size == 0:
            return []
        self._fold(self._live.feed(pcm))
        block = np.asarray(pcm, dtype=np.float32).reshape(-1)
        self._blocks.append(block)
        level = float(np.sqrt(np.mean(block * block)))
        self._levels.append(level)
        self._marks.append(len(self._live_words))
        block_ms = 1000 * block.size / self._rate
        self._quiet_ms = self._quiet_ms + block_ms if level < QUIET_RMS else 0.0

        seconds = self._buffered_seconds()
        if seconds >= MIN_PIECE_S and self._quiet_ms >= PAUSE_MS:
            self._cut(len(self._blocks))
        elif seconds >= MAX_PIECE_S:
            self._cut(self._quietest_cut())

        events: list[Event] = []
        while self._pieces and self._pieces[0].result.done():
            events.extend(self._commit(self._pieces.pop(0)))
        events.extend(self._preview())
        return events

    def finalize(self) -> list[Event]:
        if self._blocks:
            self._cut(len(self._blocks))
        events: list[Event] = []
        live_finalized = False
        for piece in self._pieces:
            if piece is self._pieces[-1] and piece.result.exception() is not None:
                # The last piece's live text may still be in Moonshine's
                # backlog, so let it finish before falling back to it.
                self._fold(self._live.finalize())
                piece.end = len(self._live_words)
                live_finalized = True
            events.extend(self._commit(piece))
        if not live_finalized:
            # Its tail is not wanted, and finalizing would make the user wait
            # for Moonshine to decode a backlog nobody will read.
            self._live.reset()
        self._clear()
        self._trim()
        return events

    def reset(self) -> None:
        self._live.reset()
        for piece in self._pieces:
            piece.result.cancel()
        self._clear()
        self._trim()

    def set_keyterms(self, terms: list[str]) -> None:
        set_keyterms = getattr(self._live, "set_keyterms", None)
        if set_keyterms is not None:
            set_keyterms(terms)

    # --- pieces ---------------------------------------------------------

    def _buffered_seconds(self) -> float:
        return sum(b.size for b in self._blocks) / self._rate

    def _quietest_cut(self) -> int:
        """Where to cut unbroken speech: just after its quietest block."""
        first = 0
        total = 0
        for index, block in enumerate(self._blocks):
            total += block.size
            if total / self._rate >= MIN_PIECE_S:
                first = index
                break
        window = self._levels[first:]
        return first + int(np.argmin(window)) + 1

    def _cut(self, count: int) -> None:
        audio = np.concatenate(self._blocks[:count])
        end = self._marks[count - 1]
        self._pieces.append(
            _Piece(
                result=self._executor.submit(self._transcribe, audio),
                seconds=audio.size / self._rate,
                start=self._piece_start,
                end=end,
            )
        )
        self._piece_start = end
        del self._blocks[:count], self._levels[:count], self._marks[:count]
        self._quiet_ms = 0.0

    def _commit(self, piece: _Piece) -> list[Event]:
        try:
            text = piece.result.result().strip()
        except Exception as exc:
            log.warning(
                "final model failed on a %.1f s piece (%s); using the live transcript",
                piece.seconds,
                exc,
            )
            text = " ".join(self._live_words[piece.start : piece.end])
        self._shown = max(self._shown, piece.end)
        return [Committed(text)] if text else []

    # --- live preview ---------------------------------------------------

    @property
    def _live_words(self) -> list[str]:
        return self._live_committed + self._live_partial

    def _fold(self, events: list[Event]) -> None:
        for event in events:
            if isinstance(event, Committed):
                self._live_committed.extend(event.text.split())
                self._live_partial = []
            else:
                self._live_partial = event.text.split()

    def _preview(self) -> list[Event]:
        """Live words not yet replaced by a committed piece.

        Kept on screen until the piece covering them lands, rather than
        dropped at the cut, so the overlay never blanks for the second a
        piece takes to decode. An empty preview is not emitted: it only
        follows a commit, which clears the live zone itself.
        """
        text = " ".join(self._live_words[self._shown :])
        if text == self._last_preview:
            return []
        self._last_preview = text
        return [Partial(text)] if text else []

    def _clear(self) -> None:
        self._blocks.clear()
        self._levels.clear()
        self._marks.clear()
        self._quiet_ms = 0.0
        self._piece_start = 0
        self._pieces = []
        self._live_committed = []
        self._live_partial = []
        self._shown = 0
        self._last_preview = ""


def load_parakeet(model_dir: Path, sample_rate: int = 16000) -> Callable[[np.ndarray], str]:
    """Load Parakeet TDT 0.6B v2 (int8) through sherpa-onnx, once at daemon start.

    `scripts/fetch_models.sh` puts the files in `model_dir` and pins them in
    models.lock, which the daemon verifies before this runs.
    """
    import sherpa_onnx

    recognizer: Any = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_dir / "encoder.int8.onnx"),
        decoder=str(model_dir / "decoder.int8.onnx"),
        joiner=str(model_dir / "joiner.int8.onnx"),
        tokens=str(model_dir / "tokens.txt"),
        model_type="nemo_transducer",
        num_threads=FINAL_THREADS,
    )
    log.info("loaded final STT model from %s", model_dir)

    def transcribe(pcm: np.ndarray) -> str:
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, pcm)
        recognizer.decode_stream(stream)
        return str(stream.result.text)

    return transcribe
