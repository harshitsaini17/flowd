"""Opt-in session recordings, for measuring the recognizer on a real voice.

Off by default, like transcripts (spec 13.2): a dictation can hold a password.
When `[logging] recordings_dir` is set, each finished session is saved there as
a 16 kHz mono WAV plus a JSON sidecar with what the recognizer heard and what
was pasted, so the same audio can be replayed through other models later
(`flowd --replay`, `eval/`). Cancelled sessions are never kept.
"""

from __future__ import annotations

import json
import logging
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


class SessionRecorder:
    """Collects one session's audio in memory and writes it out at the end.

    In memory rather than streamed to disk, so a cancel leaves no file behind
    and nothing is written while the user is speaking. Five minutes, the
    default `max_session_s`, is under 20 MB of float32.
    """

    def __init__(self, directory: Path, sample_rate: int) -> None:
        self._dir = directory
        self._rate = sample_rate
        self._blocks: list[np.ndarray] = []

    def add(self, pcm: np.ndarray) -> None:
        if pcm.size:
            self._blocks.append(pcm.copy())

    def discard(self) -> None:
        self._blocks = []

    def save(self, session_id: str, raw: str, text: str) -> Path | None:
        """Write the WAV and its sidecar. Never raises: a full disk or a bad
        path costs the recording, not the dictation."""
        audio = np.concatenate(self._blocks) if self._blocks else np.empty(0, np.float32)
        self._blocks = []
        stem = f"{time.strftime('%Y%m%d-%H%M%S')}_{session_id}"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{stem}.wav"
            pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(self._rate)
                out.writeframes(pcm16.tobytes())
            sidecar = {
                "session": session_id,
                "seconds": audio.size / self._rate,
                "raw": raw,
                "text": text,
            }
            path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2) + "\n")
        except OSError as exc:
            log.warning("could not save session recording: %s", exc)
            return None
        log.info("session recording saved to %s", path)
        return path
