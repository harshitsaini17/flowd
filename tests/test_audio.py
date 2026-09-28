import sys
import threading
import time
import types
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flowd.audio import (
    STALL_S,
    AudioCapture,
    RingBuffer,
    _open_input_stream,
    load_wav,
    release_portaudio,
)
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


# --- PortAudio lifetime (ADR 0015) ------------------------------------------


class FakeSoundDevice(types.ModuleType):
    """Stands in for the `sounddevice` module and counts PortAudio init/terminate.

    Importing the real module initialises PortAudio once, which is why
    `_initialized` starts at 1.
    """

    def __init__(self, device_name: str = "default") -> None:
        super().__init__("sounddevice")
        self._initialized = 1
        self.device_name = device_name
        self.opened_while_initialized: list[int] = []

    def _initialize(self) -> None:
        self._initialized += 1

    def _terminate(self) -> None:
        self._initialized -= 1

    def InputStream(self, **kwargs: Any) -> FakeStream:
        self.opened_while_initialized.append(self._initialized)
        stream = FakeStream(**kwargs)
        stream.device = 5  # type: ignore[attr-defined]
        return stream

    def query_devices(self, index: int) -> dict[str, Any]:
        return {"name": self.device_name, "hostapi": 0}

    def query_hostapis(self, index: int) -> dict[str, Any]:
        return {"name": "ALSA"}


def test_releasing_portaudio_never_imports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A daemon that never dictated has not loaded PortAudio; releasing it must
    not load it just to shut it down."""
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    release_portaudio()
    assert "sounddevice" not in sys.modules


def test_releasing_portaudio_terminates_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Pa_Initialize` registers a PipeWire client that outlives every stream;
    only `Pa_Terminate` removes it."""
    sd = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    release_portaudio()
    assert sd._initialized == 0


def test_a_stream_opened_after_release_reinitialises_portaudio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After `Pa_Terminate`, opening a stream fails with "Error querying device
    -1" until PortAudio is initialised again."""
    sd = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    release_portaudio()
    _open_input_stream(samplerate=16000, channels=1)
    assert sd.opened_while_initialized == [1]


def test_opening_logs_the_device_and_host_api(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sd = FakeSoundDevice("default")
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    with caplog.at_level("INFO", logger="flowd.audio"):
        _open_input_stream(samplerate=16000, channels=1, device=None)
    assert any("default (ALSA)" in r.getMessage() for r in caplog.records)


def test_a_raw_hardware_default_device_is_warned_about(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A raw `hw:` device is exclusive: while flowd holds it no other program can
    record. With `audio.device = "default"` that should never be what opens."""
    sd = FakeSoundDevice("HD-Audio Generic: ALC294 Analog (hw:1,0)")
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    with caplog.at_level("WARNING", logger="flowd.audio"):
        _open_input_stream(samplerate=16000, channels=1, device=None)
    assert any("raw hardware device" in r.getMessage() for r in caplog.records)


def released_capture(**overrides: Any) -> tuple[AudioCapture, list[FakeStream], list[int]]:
    """A capture over fake streams that records each PortAudio release."""
    streams: list[FakeStream] = []
    releases: list[int] = []

    def factory(**kwargs: Any) -> FakeStream:
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    cap = AudioCapture(
        Audio(**overrides),
        stream_factory=factory,
        release_backend=lambda: releases.append(len(streams)),
    )
    return cap, streams, releases


def test_stopping_a_session_releases_portaudio() -> None:
    cap, streams, releases = released_capture()
    cap.start()
    cap.stop()
    assert streams[0].closed is True
    assert releases == [1]


def test_always_open_never_releases_portaudio_between_sessions() -> None:
    cap, _, releases = released_capture(always_open=True)
    cap.start()
    cap.stop()
    cap.start()
    cap.stop()
    assert releases == []


def test_closing_an_always_open_capture_releases_portaudio() -> None:
    cap, _, releases = released_capture(always_open=True)
    cap.start()
    cap.stop()
    cap.close()
    assert releases == [1]


def test_an_abandoned_stream_marks_the_capture_leaked() -> None:
    streams: list[HangingStream] = []
    releases: list[int] = []

    def factory(**kwargs: Any) -> HangingStream:
        streams.append(HangingStream(**kwargs))
        return streams[-1]

    cap = AudioCapture(Audio(), stream_factory=factory, release_backend=lambda: releases.append(1))
    cap.start()
    assert cap.leaked is False
    cap.stop()
    assert cap.leaked is True
    assert releases == []
    streams[0].release.set()


def test_portaudio_is_kept_while_an_abandoned_stream_may_still_be_stopping() -> None:
    """The abandoned stop runs on its own thread inside `Pa_StopStream`;
    terminating PortAudio under it is undefined behaviour. The restart in the
    daemon frees the device instead."""
    streams: list[FakeStream] = []
    releases: list[int] = []

    def factory(**kwargs: Any) -> FakeStream:
        stream: FakeStream = HangingStream(**kwargs) if not streams else FakeStream(**kwargs)
        streams.append(stream)
        return stream

    cap = AudioCapture(Audio(), stream_factory=factory, release_backend=lambda: releases.append(1))
    cap.start()
    cap.stop()  # hangs, abandoned
    cap.start()
    cap.stop()  # stops cleanly
    assert releases == []
    first = streams[0]
    assert isinstance(first, HangingStream)
    first.release.set()


def test_a_failing_portaudio_shutdown_does_not_break_stop(caplog: pytest.LogCaptureFixture) -> None:
    """If PortAudio fails to shut down, log it and continue; do not break stop()."""
    cap, streams, _ = released_capture()

    def failing_backend() -> None:
        raise RuntimeError("Pa_Terminate failed")

    cap._release_backend = failing_backend
    cap.start()
    with caplog.at_level("WARNING", logger="flowd.audio"):
        cap.stop()
    assert streams[0].closed is True
    assert any("could not shut PortAudio down" in r.getMessage() for r in caplog.records)


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


def test_a_stream_that_ends_while_recording_marks_the_capture_failed() -> None:
    """spec 9.2: an unplugged mic or a PipeWire restart ends the stream under us.

    PortAudio reports that through `finished_callback`, not an exception, so the
    daemon only learns of it from this flag.
    """
    cap, streams = capture()
    cap.start()
    assert cap.failed is None
    streams[0].kwargs["finished_callback"]()
    assert cap.failed is not None


def test_a_stream_closed_by_stop_is_not_a_failure() -> None:
    cap, streams = capture()
    cap.start()
    cap.stop()
    streams[0].kwargs["finished_callback"]()
    assert cap.failed is None


def test_a_new_session_after_device_loss_opens_a_fresh_stream() -> None:
    """spec 5.1: retry opening on the next start."""
    cap, streams = capture(always_open=True)
    cap.start()
    streams[0].kwargs["finished_callback"]()
    cap.stop()
    cap.start()
    assert len(streams) == 2
    assert cap.failed is None


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def clocked(**overrides: Any) -> tuple[AudioCapture, list[FakeStream], Clock]:
    streams: list[FakeStream] = []
    clock = Clock()

    def factory(**kwargs: Any) -> FakeStream:
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    return AudioCapture(Audio(**overrides), stream_factory=factory, clock=clock), streams, clock


def test_a_stream_that_stops_delivering_marks_the_capture_failed() -> None:
    """spec 9.2: after a PipeWire restart the stream stays "active" but goes
    silent, and `finished_callback` never fires. Only the missing frames say so."""
    cap, streams, clock = clocked()
    cap.start()
    streams[0].deliver(np.zeros(1600, dtype=np.float32))
    clock.now += STALL_S - 0.1
    assert cap.failed is None
    clock.now += 0.2
    assert cap.failed is not None


def test_a_stream_that_keeps_delivering_is_not_stalled() -> None:
    cap, streams, clock = clocked()
    cap.start()
    for _ in range(10):
        clock.now += 0.5
        streams[0].deliver(np.zeros(1600, dtype=np.float32))
    assert cap.failed is None


def test_an_idle_capture_is_never_stalled() -> None:
    cap, _streams, clock = clocked(always_open=True)
    cap.start()
    cap.stop()
    clock.now += 60
    assert cap.failed is None


def test_an_always_open_stream_that_went_silent_while_idle_is_reopened() -> None:
    """Otherwise the first dictation after an audio server restart records
    nothing for the stall window and then reports the mic lost."""
    cap, streams, clock = clocked(always_open=True)
    cap.start()
    cap.stop()
    clock.now += 60
    cap.start()
    assert len(streams) == 2
    assert cap.failed is None


class HangingStream(FakeStream):
    """A stream on a dead audio server: `stop()` blocks until released."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.release = threading.Event()

    def stop(self) -> None:
        self.release.wait(10)
        super().stop()


def test_releasing_a_lost_stream_does_not_wait_for_it() -> None:
    """PortAudio's stop on a stalled stream took 8 s live; the daemon's event
    loop calls `stop`, so waiting would freeze `flowctl` for as long."""
    streams: list[HangingStream] = []

    def factory(**kwargs: Any) -> HangingStream:
        streams.append(HangingStream(**kwargs))
        return streams[-1]

    cap = AudioCapture(Audio(), stream_factory=factory)
    cap.start()
    streams[0].kwargs["finished_callback"]()
    began = time.monotonic()
    cap.stop()
    assert time.monotonic() - began < 0.5
    cap.start()
    assert len(streams) == 2
    streams[0].release.set()
