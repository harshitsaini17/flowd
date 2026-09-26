"""Microphone capture: 16 kHz mono float32, 100 ms blocks (spec 5.1)."""

from __future__ import annotations

import logging
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from flowd.config import Audio

log = logging.getLogger(__name__)


class RingBuffer:
    """Fixed-capacity float32 ring buffer.

    The audio callback only writes; the STT worker only reads. A lock guards the
    indices, held for a bounded copy so the callback never waits on real work
    (spec 4). On overrun the oldest audio is dropped, which is logged by the
    caller — the callback must never block the device.
    """

    def __init__(self, capacity_frames: int) -> None:
        self._buf = np.zeros(capacity_frames, dtype=np.float32)
        self._capacity = capacity_frames
        self._write = 0
        self._available = 0
        self._lock = threading.Lock()
        self.overruns = 0

    def write(self, frames: np.ndarray) -> None:
        data = np.asarray(frames, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return
        # A single block larger than the buffer loses its oldest frames before
        # they are ever stored. That is still dropped audio, so it is counted:
        # `overruns` is the only signal the daemon logs about lost input.
        oversized = data.size > self._capacity
        if oversized:
            data = data[-self._capacity :]
        with self._lock:
            end = self._write + data.size
            if end <= self._capacity:
                self._buf[self._write : end] = data
            else:
                split = self._capacity - self._write
                self._buf[self._write :] = data[:split]
                self._buf[: end - self._capacity] = data[split:]
            self._write = end % self._capacity
            total = self._available + data.size
            if total > self._capacity or oversized:
                self.overruns += 1
                total = min(total, self._capacity)
            self._available = total

    def read_available(self) -> np.ndarray:
        with self._lock:
            count = self._available
            if count == 0:
                return np.empty(0, dtype=np.float32)
            start = (self._write - count) % self._capacity
            if start + count <= self._capacity:
                out = self._buf[start : start + count].copy()
            else:
                split = self._capacity - start
                out = np.concatenate((self._buf[start:], self._buf[: count - split]))
            self._available = 0
            return out

    def pending_seconds(self, sample_rate: int) -> float:
        with self._lock:
            return self._available / float(sample_rate)

    def clear(self) -> None:
        with self._lock:
            self._available = 0


def _open_input_stream(**kwargs: Any) -> Any:
    """Import `sounddevice` lazily: it loads PortAudio at import time."""
    import sounddevice as sd

    return sd.InputStream(**kwargs)


class AudioCapture:
    """Opens the mic on start and closes it on stop, so the indicator is off when idle.

    With `always_open` the stream stays open between sessions and audio spoken
    while idle is retained as pre-roll, so the first syllable is never clipped
    (spec 5.1). That is a privacy trade-off and is off by default.
    """

    def __init__(
        self,
        cfg: Audio,
        on_status: Callable[[str], None] | None = None,
        stream_factory: Callable[..., Any] = _open_input_stream,
    ) -> None:
        self._cfg = cfg
        self._on_status = on_status
        self._stream_factory = stream_factory
        self._stream: Any = None
        self._recording = False
        capacity = cfg.sample_rate * 30  # 30 s headroom; overrun is logged, never fatal
        self._ring = RingBuffer(capacity)
        self._preroll = RingBuffer(max(1, cfg.sample_rate * cfg.preroll_ms // 1000))

    @property
    def blocksize(self) -> int:
        return self._cfg.sample_rate * self._cfg.block_ms // 1000

    def _callback(self, indata: np.ndarray, _frames: int, _time: Any, status: Any) -> None:
        """PortAudio thread: copy only (spec 4)."""
        if status and self._on_status is not None:
            self._on_status(str(status))
        frames = indata[:, 0]
        if self._recording:
            self._ring.write(frames)
        elif self._cfg.always_open:
            self._preroll.write(frames)

    def start(self) -> None:
        if self._stream is None:
            device = None if self._cfg.device == "default" else self._cfg.device
            self._stream = self._stream_factory(
                samplerate=self._cfg.sample_rate,
                blocksize=self.blocksize,
                device=device,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            log.info("mic open: %d Hz, %d ms blocks", self._cfg.sample_rate, self._cfg.block_ms)
        # Anything left unread belongs to the previous session; replaying it
        # would inject phantom words into this one.
        self._ring.clear()
        self._ring.write(self.preroll())
        self._recording = True

    def stop(self) -> None:
        self._recording = False
        if self._stream is not None and not self._cfg.always_open:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("mic closed")

    def close(self) -> None:
        """Release the device unconditionally, for shutdown."""
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("mic closed")

    def read(self) -> np.ndarray:
        return self._ring.read_available()

    def preroll(self) -> np.ndarray:
        """Take the audio retained while idle. Empty unless `always_open` is set."""
        return self._preroll.read_available()

    def pending_seconds(self) -> float:
        return self._ring.pending_seconds(self._cfg.sample_rate)

    @property
    def overruns(self) -> int:
        return self._ring.overruns


def load_wav(path: Path, sample_rate: int) -> np.ndarray:
    """Load a mono 16-bit WAV for --replay. Rejects mismatched rates loudly."""
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != sample_rate:
            raise ValueError(
                f"{path}: {handle.getframerate()} Hz, expected {sample_rate} Hz "
                f"(convert with: ffmpeg -i in.wav -ar {sample_rate} -ac 1 out.wav)"
            )
        if handle.getnchannels() != 1:
            raise ValueError(f"{path}: {handle.getnchannels()} channels, expected mono")
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
