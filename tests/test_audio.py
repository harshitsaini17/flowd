import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flowd.audio import AudioCapture, RingBuffer, load_wav
from flowd.config import Audio


def test_write_then_read_returns_same_frames() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(rb.read_available(), [1.0, 2.0, 3.0])


def test_read_drains_the_buffer() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(3, dtype=np.float32))
    rb.read_available()
    assert rb.read_available().size == 0


def test_wraps_and_keeps_newest_when_overrun() -> None:
    """Overrun drops the oldest audio, never blocks the callback."""
    rb = RingBuffer(capacity_frames=4)
    rb.write(np.array([1, 2, 3, 4, 5, 6], dtype=np.float32))
    out = rb.read_available()
    assert out.size == 4
    assert np.allclose(out, [3, 4, 5, 6])


def test_wrapping_across_several_writes_keeps_frame_order() -> None:
    """The read path reconstructs a wrapped span, so order must survive it."""
    rb = RingBuffer(capacity_frames=5)
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    rb.write(np.array([4, 5, 6], dtype=np.float32))  # wraps past the end
    assert np.allclose(rb.read_available(), [2, 3, 4, 5, 6])


def test_dropped_frames_are_counted_as_overruns() -> None:
    """The daemon logs dropped audio from this counter, so it must not undercount."""
    rb = RingBuffer(capacity_frames=4)
    rb.write(np.arange(6, dtype=np.float32))  # one write, larger than capacity
    assert rb.overruns == 1


def test_no_overrun_is_counted_when_everything_fits() -> None:
    rb = RingBuffer(capacity_frames=4)
    rb.write(np.ones(4, dtype=np.float32))
    assert rb.overruns == 0


def test_pending_seconds_reflects_sample_rate() -> None:
    rb = RingBuffer(capacity_frames=32000)
    rb.write(np.zeros(16000, dtype=np.float32))
    assert rb.pending_seconds(16000) == 1.0


def test_clear_empties_buffer() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(5, dtype=np.float32))
    rb.clear()
    assert rb.read_available().size == 0


def test_preserves_float32_dtype() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(3, dtype=np.float32))
    assert rb.read_available().dtype == np.float32


class FakeStream:
    """Stands in for `sounddevice.InputStream`, which needs a real device."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def deliver(self, frames: np.ndarray) -> None:
        """Invoke the capture callback the way PortAudio's thread would."""
        self.kwargs["callback"](frames.reshape(-1, 1), frames.size, None, None)


def capture(**overrides: Any) -> tuple[AudioCapture, list[FakeStream]]:
    streams: list[FakeStream] = []

    def factory(**kwargs: Any) -> FakeStream:
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    cfg = Audio(**overrides)
    return AudioCapture(cfg, stream_factory=factory), streams


def test_blocksize_follows_block_ms() -> None:
    cap, _ = capture(sample_rate=16000, block_ms=100)
    assert cap.blocksize == 1600


def test_captured_audio_reaches_the_reader() -> None:
    cap, streams = capture()
    cap.start()
    streams[0].deliver(np.array([0.25, 0.5], dtype=np.float32))
    assert np.allclose(cap.read(), [0.25, 0.5])


def test_status_flags_are_reported_not_swallowed() -> None:
    """An xrun must reach the log; the callback itself still only copies."""
    seen: list[str] = []
    cfg = Audio()
    streams: list[FakeStream] = []

    def factory(**kwargs: Any) -> FakeStream:
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    cap = AudioCapture(cfg, on_status=seen.append, stream_factory=factory)
    cap.start()
    streams[0].kwargs["callback"](np.zeros((1, 1), dtype=np.float32), 1, None, "input overflow")
    assert seen == ["input overflow"]


def test_stop_closes_the_device_by_default() -> None:
    """spec 5.1: the mic indicator must be off when idle."""
    cap, streams = capture(always_open=False)
    cap.start()
    cap.stop()
    assert streams[0].closed is True


def test_always_open_keeps_the_device_open_across_stop() -> None:
    """spec 5.1: with always_open the stream stays open between sessions."""
    cap, streams = capture(always_open=True)
    cap.start()
    cap.stop()
    assert streams[0].closed is False
    cap.start()
    assert len(streams) == 1  # reused, not reopened


def test_always_open_prepends_preroll_so_the_first_syllable_survives() -> None:
    """spec 5.1: 300 ms retained while idle is spliced onto the next session."""
    cap, streams = capture(always_open=True)
    cap.start()
    cap.stop()
    streams[0].deliver(np.array([0.1, 0.2], dtype=np.float32))  # spoken before start
    cap.start()
    streams[0].deliver(np.array([0.3], dtype=np.float32))
    assert np.allclose(cap.read(), [0.1, 0.2, 0.3])


def test_preroll_retains_only_the_configured_window() -> None:
    cap, streams = capture(always_open=True, sample_rate=1000, preroll_ms=10)
    cap.start()
    cap.stop()
    streams[0].deliver(np.arange(40, dtype=np.float32))
    assert cap.preroll().size == 10  # 10 ms at 1 kHz


def test_preroll_is_empty_when_the_mic_closes_between_sessions() -> None:
    """Without always_open nothing is retained, so there is nothing to splice."""
    cap, _ = capture(always_open=False)
    cap.start()
    cap.stop()
    assert cap.preroll().size == 0


def test_audio_from_a_previous_session_is_not_replayed() -> None:
    """Unread audio must not leak into the next dictation as phantom words."""
    cap, streams = capture(always_open=False)
    cap.start()
    streams[0].deliver(np.array([0.9, 0.9], dtype=np.float32))
    cap.stop()  # never read
    cap.start()
    assert cap.read().size == 0


def _write_wav(path: Path, samples: np.ndarray, rate: int, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.astype(np.int16).tobytes())
    return path


def test_load_wav_scales_int16_into_unit_floats(tmp_path: Path) -> None:
    path = _write_wav(tmp_path / "a.wav", np.array([0, 16384, -32768]), 16000)
    loaded = load_wav(path, 16000)
    assert loaded.dtype == np.float32
    assert np.allclose(loaded, [0.0, 0.5, -1.0])


def test_load_wav_rejects_a_mismatched_sample_rate(tmp_path: Path) -> None:
    """A 44.1 kHz file would transcribe as gibberish, so fail loudly instead."""
    path = _write_wav(tmp_path / "a.wav", np.zeros(4), 44100)
    with pytest.raises(ValueError, match="44100 Hz"):
        load_wav(path, 16000)


def test_load_wav_rejects_stereo(tmp_path: Path) -> None:
    path = _write_wav(tmp_path / "a.wav", np.zeros(4), 16000, channels=2)
    with pytest.raises(ValueError, match="channels"):
        load_wav(path, 16000)
