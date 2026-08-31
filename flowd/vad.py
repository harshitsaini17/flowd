"""Voice activity detection: speech/silence per block (spec 5.2).

Spec 5.2 asks for Moonshine's own voice activity or segmentation support in
preference to a second model, and ADR 0001 found it: `libmoonshine.so` embeds
Silero VAD and builds every transcript out of voice-activity segments. What it
does not do is expose that detector to Python — there is no `moonshine_vad_*`
entry point — so flowd cannot ask "is the user speaking right now?". It can see
only the detector's conclusions, as the timestamps on the transcript lines the
segments produce.

`SegmentationVad` turns those conclusions into the per-block signal spec 5.2
specifies. ADR 0002 records the reasoning, the measurements behind
`lag_allowance_ms`, and why no `silero_vad.onnx` is fetched or pinned. No
PyTorch is involved either way: a VAD that needs it is an escalation trigger
(spec 13.3).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from flowd.config import Vad

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VadFrame:
    speech: bool
    silence_ms: int


class SilenceTracker:
    """Counts the current run of consecutive silent blocks in milliseconds."""

    def __init__(self, block_ms: int) -> None:
        self._block_ms = block_ms
        self.silence_ms = 0

    def update(self, speech: bool) -> int:
        self.silence_ms = 0 if speech else self.silence_ms + self._block_ms
        return self.silence_ms

    def reset(self) -> None:
        self.silence_ms = 0


class VadEngine(Protocol):
    def process(self, block: np.ndarray) -> VadFrame:
        """Classify one block of audio and report the silence run so far."""

    def reset(self) -> None:
        """Forget the current session."""


class FakeVad:
    """Scripted engine for deterministic tests; no model needed."""

    def __init__(self, script: Sequence[bool], block_ms: int = 100) -> None:
        self._script = list(script)
        self._index = 0
        self._tracker = SilenceTracker(block_ms)

    def process(self, block: np.ndarray) -> VadFrame:
        speech = self._script[self._index] if self._index < len(self._script) else False
        self._index += 1
        return VadFrame(speech=speech, silence_ms=self._tracker.update(speech))

    def reset(self) -> None:
        self._tracker.reset()


class SegmentationVad:
    """Speech state inferred from how far Moonshine's transcript has advanced.

    The engine tracks two clocks. One is how much audio has been fed, which
    `process` advances by `block_ms` a block. The other is the *frontier*: the
    end of the furthest transcript line seen so far, reported by the STT engine
    through `observe_frontier` as Moonshine emits line events. Because every
    line comes from a voice-activity segment, the frontier is the last instant
    the embedded detector judged to be speech.

    While someone is talking the frontier chases the fed clock. When they stop,
    audio keeps arriving and the frontier stops, so the gap between the two
    grows — and that gap is the only silence evidence available.

    Transcription lag opens the same gap, which is what `lag_allowance_ms` is
    for: gaps below it are treated as speech. The default is measured, not
    guessed (ADR 0002), and it is deliberately generous. Over-reporting speech
    delays a commit; under-reporting ends an utterance while the speaker is
    still in it, and spec 13.2 forbids typing partial text into the target app.
    """

    def __init__(self, block_ms: int, lag_allowance_ms: int) -> None:
        self._block_ms = block_ms
        self._lag_allowance_ms = lag_allowance_ms
        self._tracker = SilenceTracker(block_ms)
        self._fed_ms = 0.0
        self._frontier_ms = 0.0
        self.saw_speech = False

    def observe_frontier(self, end_ms: float) -> None:
        """Note the end of a transcript line, in milliseconds of session audio.

        Monotonic: a revision can shorten the line it revises, and a frontier
        that moved backwards would read as silence that had already been
        contradicted by the audio Moonshine transcribed to get there.
        """
        self._frontier_ms = max(self._frontier_ms, end_ms)
        self.saw_speech = True

    def process(self, block: np.ndarray) -> VadFrame:
        self._fed_ms += self._block_ms
        # Nothing has been segmented yet: the session is silent so far, not
        # merely lagging. spec 5.5's "no speech at all" case depends on this
        # distinction, and `block` is unread for the same reason — the verdict
        # comes from the detector inside Moonshine, not from these samples.
        gap_ms = self._fed_ms - self._frontier_ms
        speech = self.saw_speech and gap_ms <= self._lag_allowance_ms
        return VadFrame(speech=speech, silence_ms=self._tracker.update(speech))

    def reset(self) -> None:
        self._fed_ms = 0.0
        self._frontier_ms = 0.0
        self.saw_speech = False
        self._tracker.reset()


def load_vad(cfg: Vad, model_dir: Path, block_ms: int = 100) -> VadEngine:
    """Build the VAD engine chosen in ADR 0001 and recorded in ADR 0002.

    `model_dir` is accepted for symmetry with the other loaders and unused:
    the detector ships inside `libmoonshine.so`, so there is no file to find
    and nothing for `scripts/fetch_models.sh` to fetch or `models.lock` to pin.
    """
    log.debug("VAD: Moonshine segmentation, lag allowance %d ms", cfg.lag_allowance_ms)
    return SegmentationVad(block_ms=block_ms, lag_allowance_ms=cfg.lag_allowance_ms)
