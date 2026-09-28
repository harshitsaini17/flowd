"""Microphone capture: 16 kHz mono float32, 100 ms blocks (spec 5.1)."""

from __future__ import annotations

import logging
import sys
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from flowd.config import Audio

log = logging.getLogger(__name__)

#: Seconds without a single frame before a stream counts as lost. Blocks arrive
#: every `block_ms` (100 ms by default), so this is ten missed blocks: long
#: enough to ride out a busy scheduler, short enough that a dead stream is
#: noticed before the user finishes their sentence.
STALL_S = 1.0

#: How long `_release` waits for PortAudio to stop a stream before abandoning it.
#: A healthy stop takes milliseconds; one on a dead audio server took 8 s.
RELEASE_WAIT_S = 0.25

#: How PortAudio names a raw ALSA device, e.g. "ALC294 Analog (hw:1,0)". Such a
#: device is exclusive: while flowd holds it, no other program can record.
RAW_ALSA_MARKER = "(hw:"


class MicrophoneStuck(RuntimeError):
    """A capture stream would not stop and was abandoned (ADR 0015).

    It may keep the device until this process exits, so the daemon exits once
    it is idle and systemd starts a fresh one.
    """


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


def _sounddevice() -> Any:
    """`sounddevice`, with PortAudio initialised.

    The first import initialises PortAudio itself. After `release_portaudio`
    it has to be initialised again, or every open fails with "Error querying
    device -1". Re-initialising costs about 17 ms (Ryzen 5 5600H).
    """
    import sounddevice as sd

    if sd._initialized == 0:
        sd._initialize()
    return sd


def _open_input_stream(**kwargs: Any) -> Any:
    """Import `sounddevice` lazily: it loads PortAudio at import time."""
    sd = _sounddevice()
    stream = sd.InputStream(**kwargs)
    info = sd.query_devices(stream.device)
    name = f"{info['name']} ({sd.query_hostapis(info['hostapi'])['name']})"
    log.info("mic device: %s", name)
    if kwargs.get("device") is None and RAW_ALSA_MARKER in info["name"]:
        log.warning(
            "the default input is a raw hardware device (%s); other programs cannot "
            "record while flowd does. Route it through PipeWire or set [audio] device.",
            name,
        )
    return stream


def release_portaudio() -> None:
    """Shut PortAudio down if it is loaded (ADR 0015).

    `Pa_Initialize` registers a PipeWire client and a "PortAudio" node that
    stay for as long as PortAudio is initialised, stream or no stream. Only
    `Pa_Terminate` removes them. `sounddevice` counts nested initialisations,
    so this terminates until the count is zero, as its own exit handler does.
    Never imports `sounddevice`: a daemon that never dictated has nothing to
    release.
    """
    sd = sys.modules.get("sounddevice")
    if sd is None:
        return
    while sd._initialized > 0:
        sd._terminate()


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
        clock: Callable[[], float] = time.monotonic,
        release_backend: Callable[[], None] = release_portaudio,
    ) -> None:
        self._cfg = cfg
        self._on_status = on_status
        self._stream_factory = stream_factory
        self._stream: Any = None
        self._recording = False
        self._clock = clock
        self._release_backend = release_backend
        # Streams `_release` gave up on. Each may still be stopping on its own
        # thread and holding the device, so PortAudio is never terminated
        # under them; the daemon restarts instead (ADR 0015).
        self._abandoned = 0
        # Set from PortAudio's thread when the stream ends without us asking:
        # an unplugged device (spec 9.2). Read through `failed`, which also
        # reports a stream that has gone silent.
        self._ended: str | None = None
        # When the callback last ran. A PipeWire restart leaves the stream
        # "active" and never calls `finished_callback`; it just stops calling
        # back, so silence from the callback is the only sign.
        self._last_frame = 0.0
        # Which stream is current. PortAudio may report a stream finished
        # after `stop()` has returned, so a flag set around our own stop would
        # race; a stale generation is simply one we already closed.
        self._generation = 0
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
        self._last_frame = self._clock()
        frames = indata[:, 0]
        if self._recording:
            self._ring.write(frames)
        elif self._cfg.always_open:
            self._preroll.write(frames)

    def _finished_for(self, generation: int) -> Callable[[], None]:
        def finished() -> None:
            """PortAudio thread: the stream stopped. Ours to close, or lost?"""
            if generation == self._generation and self._stream is not None:
                self._ended = "audio stream ended (device unplugged or audio server restarted)"
                log.warning("%s", self._ended)

        return finished

    @property
    def failed(self) -> str | None:
        """Why the stream is lost, or None. Checked by the daemon every pump."""
        if self._ended is not None:
            return self._ended
        if self._recording and self._stream is not None and self._stalled():
            return f"no audio from the microphone for {STALL_S:.0f} s (audio server restarted?)"
        return None

    @property
    def leaked(self) -> bool:
        """Whether a stream was abandoned and may still hold the device."""
        return self._abandoned > 0

    def _stalled(self) -> bool:
        return self._clock() - self._last_frame > STALL_S

    def start(self) -> None:
        if self._stream is not None and (self._ended is not None or self._stalled()):
            # spec 5.1: after device loss, retry opening on the next start. An
            # `always_open` stream can die while idle, so it is checked here too
            # rather than discovered a second into the next dictation.
            self._release()
        self._ended = None
        if self._stream is None:
            device = None if self._cfg.device == "default" else self._cfg.device
            self._stream = self._stream_factory(
                samplerate=self._cfg.sample_rate,
                blocksize=self.blocksize,
                device=device,
                channels=1,
                dtype="float32",
                callback=self._callback,
                finished_callback=self._finished_for(self._generation),
            )
            self._stream.start()
            # The stall clock starts at open: a device that never delivers a
            # first block is as lost as one that stopped.
            self._last_frame = self._clock()
            log.info("mic open: %d Hz, %d ms blocks", self._cfg.sample_rate, self._cfg.block_ms)
        # Anything left unread belongs to the previous session; replaying it
        # would inject phantom words into this one.
        self._ring.clear()
        self._ring.write(self.preroll())
        self._recording = True

    def stop(self) -> None:
        self._recording = False
        if self._stream is not None and not self._cfg.always_open:
            self._release()

    def close(self) -> None:
        """Release the device unconditionally, for shutdown."""
        self._recording = False
        if self._stream is not None:
            self._release()

    def _release(self) -> None:
        # Retire the generation first, so the finished callback this stop
        # triggers is recognised as ours rather than as a lost device.
        self._generation += 1
        stream, self._stream = self._stream, None
        # On a thread, with a bounded wait: this runs on the daemon's event
        # loop, and PortAudio's stop on a stream whose audio server restarted
        # blocks for seconds, during which `flowctl` could not be answered. A
        # stop that overruns is left to finish on its own; the next start
        # opens a fresh stream, which the restarted server serves normally.
        closer = threading.Thread(target=self._close_stream, args=(stream,), daemon=True)
        closer.start()
        closer.join(RELEASE_WAIT_S)
        if closer.is_alive():
            self._abandoned += 1
            log.warning("audio stream did not stop within %.2f s; abandoning it", RELEASE_WAIT_S)
        elif self._abandoned == 0:
            try:
                self._release_backend()
            except Exception as exc:
                log.warning("could not shut PortAudio down: %s", exc)
        log.info("mic closed")

    @staticmethod
    def _close_stream(stream: Any) -> None:
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            # A stream whose device is already gone may refuse to stop; it is
            # released either way, and the next start opens a fresh one.
            log.warning("error closing audio stream: %s", exc)

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
