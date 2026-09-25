import wave
from pathlib import Path

import numpy as np
import pytest

from flowd.config import Config, Hotkey, Logging
from flowd.main import _ReplayCapture, build_parser, lock_path, replay_config


def write_wav(path: Path, pcm: np.ndarray, sample_rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


# --- argument parsing --------------------------------------------------------


def test_replay_and_fast_are_parsed() -> None:
    args = build_parser().parse_args(["--replay", "clip.wav", "--fast"])
    assert args.replay == Path("clip.wav")
    assert args.fast is True


def test_replay_defaults_to_real_time() -> None:
    """The user asked for real time by default, with --fast as the opt-out."""
    args = build_parser().parse_args(["--replay", "clip.wav"])
    assert args.fast is False


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--log-level", "shouting"])


# --- replay configuration ----------------------------------------------------


def test_replay_disables_hotkey_debounce() -> None:
    """A replay issues start and stop programmatically, microseconds apart.

    Debounce exists to swallow a hotkey double-press (spec 9.1). Left at its
    200 ms default it swallows the replay's own `stop`, so the run finalises
    nothing and prints an empty TEXT line — the phase 1 acceptance check would
    pass silently while transcribing nothing.
    """
    cfg = Config(hotkey=Hotkey(debounce_ms=200))
    assert replay_config(cfg).hotkey.debounce_ms == 0


def test_replay_config_changes_nothing_else() -> None:
    cfg = Config(hotkey=Hotkey(mode="ptt", debounce_ms=200), logging=Logging(level="debug"))
    replayed = replay_config(cfg)
    assert replayed.hotkey.mode == "ptt"
    assert replayed.logging.level == "debug"
    assert replayed.audio == cfg.audio
    assert cfg.hotkey.debounce_ms == 200, "the original config must not be mutated"


# --- replay capture ----------------------------------------------------------


def test_replay_capture_yields_every_frame_in_order() -> None:
    pcm = np.arange(250, dtype=np.float32)
    capture = _ReplayCapture(pcm, block=100, sample_rate=16000, realtime=False)
    capture.start()
    blocks = []
    while not capture.exhausted:
        blocks.append(capture.read())
    assert [len(b) for b in blocks] == [100, 100, 50]
    assert np.array_equal(np.concatenate(blocks), pcm)


def test_replay_capture_reports_exhaustion_and_then_returns_nothing() -> None:
    capture = _ReplayCapture(np.zeros(10, dtype=np.float32), 100, 16000, realtime=False)
    capture.start()
    capture.read()
    assert capture.exhausted is True
    assert capture.read().size == 0


def test_fast_replay_does_not_pace_itself() -> None:
    """--fast must not sleep: a 45 s clip would take 45 s in a test suite."""
    import time

    pcm = np.zeros(16000, dtype=np.float32)  # one second of audio
    capture = _ReplayCapture(pcm, block=1600, sample_rate=16000, realtime=False)
    capture.start()
    started = time.monotonic()
    while not capture.exhausted:
        capture.read()
    assert time.monotonic() - started < 0.2


def test_realtime_replay_paces_playback() -> None:
    """Without --fast the run is paced, so reported latencies mean something."""
    import time

    pcm = np.zeros(3200, dtype=np.float32)  # 200 ms at 16 kHz
    capture = _ReplayCapture(pcm, block=1600, sample_rate=16000, realtime=True)
    capture.start()
    started = time.monotonic()
    while not capture.exhausted:
        capture.read()
    assert time.monotonic() - started >= 0.05


def test_load_wav_rejects_a_rate_mismatch(tmp_path: Path) -> None:
    """A 48 kHz clip resampled by nobody would transcribe as gibberish."""
    from flowd.audio import load_wav

    path = write_wav(tmp_path / "wrong.wav", np.zeros(100, dtype=np.float32), sample_rate=48000)
    with pytest.raises(ValueError, match="48000 Hz"):
        load_wav(path, 16000)


# --- model verification ------------------------------------------------------


def test_lock_path_points_at_the_repo_lockfile() -> None:
    """A missing lockfile downgrades to a warning, so the path must be right."""
    assert lock_path().name == "models.lock"
    assert lock_path().is_file(), "models.lock should exist in a source checkout"
