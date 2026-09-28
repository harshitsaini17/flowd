import asyncio
import dataclasses
import wave
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
import pytest

import flowd.main as main
from flowd.audio import MicrophoneStuck
from flowd.config import Config, Hotkey, Logging, state_dir
from flowd.main import _ReplayCapture, build_parser, lock_path, replay_config
from flowd.stt import Committed, FakeSttEngine


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
    nothing and prints an empty TEXT line — a replay-based check would
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


class FakeTime:
    """A clock the test drives, where sleeping and working both move it.

    Real time here would make the test both slow and flaky; what matters is the
    schedule the pacer computes, which a fake clock shows exactly.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def work(self, seconds: float) -> None:
        self.now += seconds


def test_realtime_replay_keeps_an_absolute_schedule() -> None:
    """A microphone delivers blocks on its own schedule, not the consumer's.

    Moonshine decodes in bursts: most blocks cost almost nothing and every few
    hundred ms one costs more than a block is long. If each deadline is measured
    from the end of the previous wait, that overrun is added to the clip instead
    of caught up on the cheap blocks that follow, and a 12 s clip takes 16 s.
    Every latency `--replay` reports is then inflated by however slow the
    machine was, which defeats the point of pacing it at all.

    Here 800 ms of audio carries 500 ms of bursty compute, so a pacer holding an
    absolute schedule delivers the last block at 800 ms.
    """
    t = FakeTime()
    pcm = np.zeros(12800, dtype=np.float32)  # 800 ms at 16 kHz, eight blocks
    capture = _ReplayCapture(
        pcm, block=1600, sample_rate=16000, realtime=True, clock=t.clock, sleep=t.sleep
    )
    capture.start()
    for burst in (0.25, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0):
        capture.read()
        t.work(burst)
    assert capture.exhausted
    assert t.now == pytest.approx(0.8, abs=1e-9)


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


# --- version reporting -------------------------------------------------------


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`.github/ISSUE_TEMPLATE/bug_report.md` asks reporters to run this."""
    import flowd

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert flowd.__version__ in capsys.readouterr().out


def test_reported_version_matches_the_package_metadata() -> None:
    """A skew here makes every bug report name a version that was never released."""
    import tomllib

    import flowd

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert flowd.__version__ == declared


# --- replay leaves no trace ---------------------------------------------------


def test_replay_writes_no_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A replay is a probe, not dictation. Written to metrics.jsonl it reads as
    # a real session in `flowctl stats`, and a user looking for their own
    # timings finds the harness's instead.
    engine = FakeSttEngine([[Committed("hello there")]])
    monkeypatch.setattr(main, "load_engine", lambda *a, **kw: engine)
    state_dir().mkdir(parents=True)
    clip = write_wav(tmp_path / "clip.wav", np.zeros(1600, dtype=np.float32))

    moonshine_only = dataclasses.replace(
        Config(), stt=dataclasses.replace(Config().stt, final_model="")
    )
    assert asyncio.run(main._replay(moonshine_only, clip, fast=True)) == 0
    assert not (state_dir() / "metrics.jsonl").exists()


def test_an_stt_model_that_fails_to_load_exits_non_zero_with_a_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """spec 9.2: exit non-zero with a clear message; systemd restarts with backoff."""

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("model file is truncated")

    monkeypatch.setattr(main, "_verify_or_exit", lambda cfg: None)
    monkeypatch.setattr(main, "load_engine", broken)
    with caplog.at_level("ERROR"):
        code = main.main([])
    assert code == main.EXIT_STT_LOAD
    assert any("model file is truncated" in r.getMessage() for r in caplog.records)


def test_an_invalid_config_at_startup_exits_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def invalid(path: Any = None) -> Any:
        raise ValueError("[audio] block_ms: must be a positive integer, got 0")

    monkeypatch.setattr(main, "load_config", invalid)
    assert main.main([]) == main.EXIT_CONFIG
    assert "block_ms" in capsys.readouterr().err


def test_a_stuck_microphone_exits_with_its_own_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-zero so systemd's `Restart=on-failure` starts a fresh daemon, and
    distinct so `systemctl --user status flowd` says why (ADR 0015). The exit
    skips atexit, so it is intercepted here rather than returned."""
    from flowd.daemon import Daemon

    def hard_exit(code: int) -> NoReturn:
        raise SystemExit(code)

    async def stuck(self: Daemon, socket_path: Path) -> None:
        raise MicrophoneStuck("audio stream did not stop")

    monkeypatch.setattr(main, "_verify_or_exit", lambda cfg: None)
    monkeypatch.setattr(main, "_load_stt", lambda cfg: FakeSttEngine([]))
    monkeypatch.setattr(Daemon, "run", stuck)
    monkeypatch.setattr(main, "_hard_exit", hard_exit)
    with pytest.raises(SystemExit) as exited:
        main.main([])
    assert exited.value.code == main.EXIT_MIC_STUCK
    assert "did not stop" in capsys.readouterr().err


# --- the final model (ADR 0011) ----------------------------------------------


def test_the_final_model_wraps_the_live_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from flowd.hybrid import HybridSttEngine

    live = FakeSttEngine([])
    seen: list[Path] = []
    monkeypatch.setattr(main, "load_engine", lambda *a, **kw: live)
    monkeypatch.setattr(main, "load_parakeet", lambda path, rate: seen.append(path) or str)
    engine = main._load_stt(Config())
    assert isinstance(engine, HybridSttEngine)
    assert seen == [main.data_dir() / "models" / "parakeet-tdt-0.6b-v2-int8"]


def test_without_a_final_model_moonshine_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    live = FakeSttEngine([])
    monkeypatch.setattr(main, "load_engine", lambda *a, **kw: live)
    cfg = dataclasses.replace(Config(), stt=dataclasses.replace(Config().stt, final_model=""))
    assert main._load_stt(cfg) is live


def test_a_final_model_that_fails_to_load_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any) -> Any:
        raise RuntimeError("encoder.int8.onnx: Protobuf parsing failed")

    monkeypatch.setattr(main, "_verify_or_exit", lambda cfg: None)
    monkeypatch.setattr(main, "load_engine", lambda *a, **kw: FakeSttEngine([]))
    monkeypatch.setattr(main, "load_parakeet", broken)
    with caplog.at_level("ERROR"):
        assert main.main([]) == main.EXIT_STT_LOAD
    assert any("Protobuf parsing failed" in r.getMessage() for r in caplog.records)
