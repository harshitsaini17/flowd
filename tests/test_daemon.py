import json
from pathlib import Path
from typing import Any

import numpy as np

from flowd.config import Config, Hotkey, Inject
from flowd.daemon import Daemon
from flowd.inject.base import InjectResult
from flowd.stt import Committed, FakeSttEngine, Partial


class Clock:
    """A monotonic clock the test advances deliberately.

    The default 200 ms debounce (spec 9.1) is measured against this clock, and a
    test issues `start` and `stop` microseconds apart. On a real clock the
    `stop` is swallowed as a double-press and nothing is ever injected, so every
    session test needs time to move between commands.
    """

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class FrozenClock:
    """A clock that never advances, so debounce always bites."""

    def __call__(self) -> float:
        return 0.0


class FakeCapture:
    def __init__(self, blocks: list[np.ndarray] | None = None) -> None:
        self.blocks = blocks if blocks is not None else [np.zeros(1600, dtype=np.float32)]
        self.started = False
        self.stopped = False
        self.overruns = 0

    def start(self) -> None:
        self.started = True
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def read(self) -> np.ndarray:
        return self.blocks.pop(0) if self.blocks else np.empty(0, dtype=np.float32)

    def pending_seconds(self) -> float:
        return 0.0


class FakeOverlay:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def render(self, **zones: str) -> None:
        self.messages.append(dict(zones))

    def stop(self) -> None:
        pass


def daemon(
    stt: Any,
    capture: Any = None,
    injected: list[str] | None = None,
    *,
    cfg: Config | None = None,
    clock: Any = None,
    metrics_path: Path | None = None,
) -> Daemon:
    sink = injected if injected is not None else []

    def fake_inject(text: str, inject_cfg: Inject, **kwargs: Any) -> InjectResult:
        sink.append(text)
        return InjectResult(ok=True, backend="fake")

    return Daemon(
        cfg=cfg or Config(),
        stt=stt,
        capture=capture or FakeCapture(),
        overlay=FakeOverlay(),
        injector=fake_inject,
        metrics_path=metrics_path,
        clock=clock or Clock(),
    )


async def test_toggle_records_then_injects_cleaned_text() -> None:
    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("so um i think we should ship it")]]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    # Capital "I": `basic_clean` capitalises the standalone pronoun, which
    # tests/test_textclean.py pins for this very sentence.
    assert injected == ["So I think we should ship it."]


async def test_cancel_injects_nothing() -> None:
    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("discard me")]]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    assert injected == []


async def test_silent_session_injects_nothing() -> None:
    """Review Focus 4: hotkey pressed and released with no speech."""
    injected: list[str] = []
    d = daemon(FakeSttEngine([]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == []


async def test_silent_session_reports_no_speech() -> None:
    d = daemon(FakeSttEngine([]))
    await d.handle({"cmd": "start"})
    reply = await d.handle({"cmd": "stop"})
    assert reply["ok"] is True
    assert reply.get("reason") == "no speech"


async def test_whitespace_only_transcript_counts_as_no_speech() -> None:
    """A transcript of blanks must not inject an empty string and claim success."""
    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("   ")]]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    reply = await d.handle({"cmd": "stop"})
    assert injected == []
    assert reply.get("reason") == "no speech"


async def test_silent_session_returns_to_idle() -> None:
    """A no-speech session must not strand the machine outside IDLE.

    The no-speech path returns before the CHUNKS_RESOLVED/INJECT_DONE pair that
    normally walks FINALIZING to IDLE, so the next hotkey press would be
    ignored and dictation would be dead until restart.
    """
    d = daemon(FakeSttEngine([]))
    await d.handle({"cmd": "start"})
    await d.handle({"cmd": "stop"})
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    assert (await d.handle({"cmd": "start"}))["ok"] is True


async def test_partials_never_reach_the_injector() -> None:
    """spec 1 non-goals: partial text must never be typed into the target app."""
    injected: list[str] = []
    d = daemon(
        FakeSttEngine([[Partial("half a sen")], [Committed("half a sentence")]]),
        injected=injected,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == ["Half a sentence."]


async def test_start_while_recording_is_ignored() -> None:
    d = daemon(FakeSttEngine([[Committed("one")]]))
    await d.handle({"cmd": "start"})
    reply = await d.handle({"cmd": "start"})
    assert reply["ok"] is False


async def test_debounce_still_applies_through_the_daemon() -> None:
    """spec 9.1: a hotkey double-press must not end the session it just began."""
    d = daemon(FakeSttEngine([[Committed("keep recording")]]), clock=FrozenClock())
    assert (await d.handle({"cmd": "start"}))["ok"] is True
    reply = await d.handle({"cmd": "stop"})
    assert reply["ok"] is False
    assert (await d.handle({"cmd": "status"}))["state"] == "recording"


async def test_status_reports_state() -> None:
    d = daemon(FakeSttEngine([]))
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    await d.handle({"cmd": "start"})
    assert (await d.handle({"cmd": "status"}))["state"] == "recording"


async def test_last_returns_previous_text_after_failed_injection() -> None:
    """spec 5.7: the text is never lost even if injection lands nowhere."""

    def failing_inject(text: str, inject_cfg: Inject, **kwargs: Any) -> InjectResult:
        return InjectResult(ok=False, error="no backend")

    d = Daemon(
        cfg=Config(),
        stt=FakeSttEngine([[Committed("kept anyway")]]),
        capture=FakeCapture(),
        overlay=FakeOverlay(),
        injector=failing_inject,
        metrics_path=None,
        clock=Clock(),
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert (await d.handle({"cmd": "last"}))["text"] == "Kept anyway."


async def test_reload_with_bad_config_keeps_old(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = -1\n")
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    reply = await d.handle({"cmd": "reload"})
    assert reply["ok"] is False
    assert d.cfg.vad.commit_silence_ms == 350


async def test_reload_applies_a_good_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = 500\n")
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    assert d.cfg.vad.commit_silence_ms == 500


async def test_mic_open_is_timed() -> None:
    d = daemon(FakeSttEngine([[Committed("hi there friend")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert "mic_open_ms" in d.last_record["stages"]
    assert "inject_ms" in d.last_record["stages"]


async def test_capture_is_released_on_cancel() -> None:
    capture = FakeCapture()
    d = daemon(FakeSttEngine([]), capture=capture)
    await d.handle({"cmd": "start"})
    await d.handle({"cmd": "cancel"})
    assert capture.stopped is True


async def test_overlay_hidden_after_session() -> None:
    d = daemon(FakeSttEngine([[Committed("some words here now")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.visible is False


async def test_microphone_failure_is_reported_and_releases_the_machine() -> None:
    """A mic held by another process must not leave the daemon stuck."""

    class DeadCapture(FakeCapture):
        def start(self) -> None:
            raise OSError("device busy")

    d = daemon(FakeSttEngine([]), capture=DeadCapture())
    reply = await d.handle({"cmd": "start"})
    assert reply["ok"] is False
    assert "device busy" in str(reply["error"])
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"


async def test_unsupported_command_is_refused() -> None:
    d = daemon(FakeSttEngine([]))
    reply = await d.handle({"cmd": "teleport"})
    assert reply["ok"] is False


async def test_metrics_are_written_when_a_path_is_given(tmp_path: Path) -> None:
    log_path = tmp_path / "metrics.jsonl"
    d = daemon(FakeSttEngine([[Committed("write this down")]]), metrics_path=log_path)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["stages"]["inject_ms"] >= 0


async def test_stats_reads_the_metrics_log(tmp_path: Path) -> None:
    log_path = tmp_path / "metrics.jsonl"
    d = daemon(FakeSttEngine([[Committed("one two three four")]]), metrics_path=log_path)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    reply = await d.handle({"cmd": "stats"})
    assert reply["ok"] is True
    assert reply["stats"], "stats must summarise the session just recorded"


async def test_transcripts_are_not_logged_by_default(tmp_path: Path) -> None:
    """spec 9.4: dictation can contain a password; default to not recording it."""
    log_path = tmp_path / "metrics.jsonl"
    d = daemon(FakeSttEngine([[Committed("my secret passphrase")]]), metrics_path=log_path)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert "passphrase" not in log_path.read_text()


async def test_max_duration_finalizes_the_session() -> None:
    """spec 5.1: a session that hits max_session_s flushes rather than running on."""
    injected: list[str] = []
    cfg = Config(hotkey=Hotkey(debounce_ms=0))
    clock = Clock(step=0.0)
    d = daemon(
        FakeSttEngine([[Committed("ran out of time")]]),
        injected=injected,
        cfg=cfg,
        clock=clock,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    clock.now += cfg.audio.max_session_s + 1
    await d._check_max_duration()
    assert injected == ["Ran out of time."]
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
