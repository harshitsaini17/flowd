import asyncio
import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from flowd.config import Config, Hotkey, Inject
from flowd.daemon import Daemon
from flowd.inject.base import InjectResult
from flowd.stt import Committed, Event, FakeSttEngine, Partial


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
        self.calls: list[str] = []
        self.visible = False
        self.stopped = False

    def show(self) -> None:
        self.visible = True
        self.calls.append("show")

    def hide(self) -> None:
        self.visible = False
        self.calls.append("hide")

    def fade(self) -> None:
        self.visible = False
        self.calls.append("fade")

    def render(self, **zones: str) -> None:
        self.messages.append(dict(zones))

    def stop(self) -> None:
        self.stopped = True


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


async def test_cancel_resets_the_engine_so_nothing_leaks_into_the_next_session() -> None:
    """spec 9.4: the daemon holds one engine for its whole life (spec 5.3), so a
    cancelled session that left state behind carries on into the next one.

    The second `stop` still reports a finished session, which is what separates
    a cleared engine from a daemon that merely stopped recording.
    """
    injected: list[str] = []
    d = daemon(
        FakeSttEngine([[Committed("cancelled words")], [Committed("next session")]]),
        capture=FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(4)]),
        injected=injected,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})

    await d.handle({"cmd": "start"})
    await d.pump()
    reply = await d.handle({"cmd": "stop"})
    assert injected == []
    assert reply == {"ok": True, "reason": "no speech"}


async def test_silent_session_injects_nothing() -> None:
    """Review Focus 4: hotkey pressed and released with no speech."""
    injected: list[str] = []
    d = daemon(FakeSttEngine([]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == []


async def test_the_no_speech_message_stays_up_long_enough_to_read() -> None:
    """spec 9.1: "overlay shows 'No speech' for 1 s".

    The message was rendered and then torn down in the same synchronous breath —
    `_show_status` followed by an `_end_session` that hides at once — so a user
    whose microphone was muted saw one frame at best and had no idea why nothing
    was typed. That is the case where feedback matters most.

    Asserted as `fade` rather than a duration because the 1 s linger is the
    overlay child's (`FADE_MS`), which keeps the daemon out of the business of
    sleeping to time a window.
    """
    d = daemon(FakeSttEngine([]))
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    await d.handle({"cmd": "start"})
    await d.handle({"cmd": "stop"})
    assert overlay.messages[-1]["live"] == "No speech", "the message was never rendered"
    assert overlay.calls[-1] == "fade", "torn down in the same tick; nothing to read"


async def test_max_duration_notes_the_limit_on_the_overlay() -> None:
    """spec 4's table: max duration is "Same as stop; overlay shows 'time limit'",
    and spec 9.1 repeats it as "overlay notes the limit".

    Nothing said so. An auto-stop looked identical to the user's own stop, so
    someone whose five minutes ran out could not tell why their dictation ended.
    The note rides the final frame, which fades, so it is shown beside the text
    that was injected rather than instead of it.
    """
    cfg = Config(hotkey=Hotkey(debounce_ms=0))
    clock = Clock(step=0.0)
    d = daemon(FakeSttEngine([[Committed("ran out of time")]]), cfg=cfg, clock=clock)
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    await d.handle({"cmd": "start"})
    await d.pump()
    clock.now += cfg.audio.max_session_s + 1
    await d._check_max_duration()
    assert any("time limit" in m.get("live", "") for m in overlay.messages), (
        "auto-stop is indistinguishable from the user's own stop"
    )


async def test_an_ordinary_stop_does_not_claim_a_time_limit() -> None:
    """The companion to the test above: the note must be specific to auto-stop,
    or it says nothing. Without this, rendering it unconditionally would pass."""
    d = daemon(FakeSttEngine([[Committed("plenty of time")]]))
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert not any("time limit" in m.get("live", "") for m in overlay.messages)


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


class BlockingSttEngine:
    """An engine whose `feed` blocks, the way a real Moonshine decode does.

    Measured on this machine, one `feed` call is 0.2 ms at the median but
    553 ms at p95 and 1,596 ms at worst: most calls only buffer, and every
    eighth or so runs the model. Those are the windows that matter, and
    `FakeSttEngine` returns instantly so it cannot expose them.

    `feed` blocks on an event with a timeout rather than forever, so a test that
    fails leaves a failure rather than a hung suite.
    """

    def __init__(self, block_s: float = 1.5) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.entered_at = 0.0
        self.in_feed = False
        #: Set if `reset` is called while a `feed` is still running — the race a
        #: naive `to_thread` would introduce, since both touch one Moonshine
        #: stream.
        self.concurrent_reset = False
        self._block_s = block_s

    def feed(self, pcm: np.ndarray) -> list[Event]:
        self.in_feed = True
        self.entered_at = time.monotonic()
        self.entered.set()
        try:
            self.release.wait(self._block_s)
            return [Partial("mid decode")]
        finally:
            self.in_feed = False

    def finalize(self) -> list[Event]:
        return [Committed("mid decode")]

    def reset(self) -> None:
        if self.in_feed:
            self.concurrent_reset = True


async def test_the_control_socket_answers_during_a_decode() -> None:
    """spec 5.9 budgets `flowctl` under 50 ms, and spec 4 puts STT on its own
    worker for this reason: the loop must stay free while the model runs.

    `cancel` is the safety valve that stops a runaway session (spec 9.4). If a
    decode holds the only thread, that valve waits behind it — up to 1.6 s on
    this machine.

    The wait happens in a worker thread rather than on the loop, because a loop
    that is blocked cannot resume the coroutine measuring it: `asked_at` would
    then be recorded after the decode finished and the assertion would pass for
    the wrong reason. The delta measured is decode-start to command-start.
    """
    stt = BlockingSttEngine(block_s=1.5)
    d = daemon(stt)
    await d.handle({"cmd": "start"})

    pump = asyncio.create_task(d.pump())
    await asyncio.to_thread(stt.entered.wait, 3.0)
    asked_at = time.monotonic()
    reply = await d.handle({"cmd": "status"})
    stt.release.set()
    await pump

    waited_ms = (asked_at - stt.entered_at) * 1000
    assert reply["ok"] is True
    assert waited_ms < 250, f"control socket blocked {waited_ms:.0f} ms behind the decoder"


async def test_cancel_does_not_reset_the_engine_mid_decode() -> None:
    """Moving STT off the loop must not let two callers touch one stream.

    `_discard` calls `stt.reset()`, and Moonshine holds a single stream per
    session, so a `cancel` arriving while a decode is in flight would reset it
    underneath the worker. This guards the fix rather than the old behaviour:
    inline STT cannot reach it (the loop is blocked, so no command is
    dispatched at all), but a `to_thread` without mutual exclusion can.
    """
    stt = BlockingSttEngine(block_s=1.0)
    d = daemon(stt)
    await d.handle({"cmd": "start"})

    pump = asyncio.create_task(d.pump())
    await asyncio.to_thread(stt.entered.wait, 3.0)
    cancel = asyncio.create_task(d.handle({"cmd": "cancel"}))
    stt.release.set()
    await pump
    assert (await cancel)["ok"] is True
    assert stt.concurrent_reset is False, "reset ran while a decode was still in flight"


async def test_debounce_still_applies_through_the_daemon() -> None:
    """spec 9.1: a hotkey double-press must not end the session it just began.

    Two presses of the same toggle key, which is what a bounce delivers. The
    earlier version of this test used `start` then `stop` — a press/release
    pair, not a double press — and so asserted that a push-to-talk tap leaves
    the microphone open. It passed for the wrong reason.
    """
    d = daemon(FakeSttEngine([[Committed("keep recording")]]), clock=FrozenClock())
    assert (await d.handle({"cmd": "toggle"}))["ok"] is True
    reply = await d.handle({"cmd": "toggle"})
    assert reply["ok"] is False
    assert (await d.handle({"cmd": "status"}))["state"] == "recording"


async def test_a_quick_push_to_talk_tap_finalizes_through_the_daemon() -> None:
    """The release of a tap shorter than `debounce_ms` must still be honoured.

    `FrozenClock` puts both commands at the same instant, the worst case for a
    `ptt` binding. Asserted at the daemon rather than only on the state machine
    because this is the layer the README's `bindr`/`--release` bindings reach,
    and a mic left open here is the user-visible failure.
    """
    d = daemon(FakeSttEngine([[Committed("a quick word")]]), clock=FrozenClock())
    assert (await d.handle({"cmd": "start"}))["ok"] is True
    reply = await d.handle({"cmd": "stop"})
    assert reply["ok"] is True, "release swallowed by debounce; microphone left open"
    assert (await d.handle({"cmd": "status"}))["state"] != "recording"


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


async def test_the_release_instant_is_marked() -> None:
    """Two of spec 10.1's budgets are measured from release, not from the hotkey.

    "Release → last chunk committed" (<= 300 ms) and "release → text injected"
    (p50 <= 600 ms) are both deltas from the moment the speaker stopped. Every
    mark is relative to the start of the session, so without a mark at release
    neither delta exists — including the end-to-end budget that is the headline
    number for the whole product. A session's recorded length would otherwise be
    indistinguishable from its latency.
    """
    d = daemon(FakeSttEngine([[Committed("some words to finalize")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    stages = d.last_record["stages"]
    assert "released_ms" in stages
    # Release comes after the microphone opened and before the text was injected,
    # so both budget subtractions land the right way round.
    assert stages["mic_open_ms"] <= stages["released_ms"] <= stages["inject_ms"]


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


async def test_overlay_child_is_stopped_when_the_daemon_exits(tmp_path: Path) -> None:
    """The overlay is a child process (spec 9.5), so somebody has to reap it.

    It does exit on its own when stdin closes, but only once it notices. A daemon
    that owns a `stop()` and does not call it leaves a GTK process holding a
    layer surface for as long as the compositor lets it — a preview from a
    session that ended, on top of the user's work.
    """
    d = daemon(FakeSttEngine([]))
    socket_path = tmp_path / "flowd.sock"
    task = asyncio.create_task(d.run(socket_path))
    for _ in range(100):  # wait for the run loop to be up, without a fixed sleep
        if socket_path.exists():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.stopped is True


async def test_resolved_chunks_render_in_the_polished_zone() -> None:
    """The three zones split by chunk state (spec 6.1): a resolved chunk shows as
    polished, an unresolved one as pending.

    Phase 2 has no LLM and so never resolves a chunk, which is why this sets the
    state directly. The split is phase 3's contract, pinned here because
    `_render` is the code that has to honour it, and a `_render` that ignores
    state would otherwise pass every phase 2 test.
    """
    d = daemon(
        FakeSttEngine([[Committed("first chunk here")], [Committed("second chunk here")]]),
        capture=FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(2)]),
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    assert d.session is not None
    d.session.chunks[0].polished = "First chunk here."
    d.session.chunks[0].state = "DONE"
    await d.pump()

    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.messages[-1]["polished"] == "First chunk here."
    assert overlay.messages[-1]["pending"] == "second chunk here"


async def test_overlay_fades_when_text_was_injected() -> None:
    """spec 6.1: the preview lingers briefly on success, so the user sees what
    landed. Cutting it at the instant of injection leaves them unsure whether
    anything was typed at all."""
    d = daemon(FakeSttEngine([[Committed("some words here now")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.calls == ["show", "fade"]


async def test_overlay_hides_at_once_when_nothing_was_injected() -> None:
    """A cancelled session has nothing to show off, so it goes immediately."""
    d = daemon(FakeSttEngine([[Committed("discard me")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.calls == ["show", "hide"]


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


async def test_cancelled_session_is_still_logged() -> None:
    """spec 10.2: one line per session, and a cancelled session is a session.

    Dropping the record loses the only signal that says how often dictation is
    abandoned — the symptom of a misfiring hotkey or a microphone that opens
    slowly — and `flowctl stats` would report a clean history of a tool nobody
    could actually use.
    """
    d = daemon(FakeSttEngine([[Committed("never mind")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    assert d.last_record.get("errors") == ["cancelled"]
    assert "mic_open_ms" in d.last_record["stages"]


async def test_cancelling_keeps_the_previous_text_for_flowctl_last() -> None:
    """spec 5.7: cancel discards this session, it does not erase the last one."""
    d = daemon(FakeSttEngine([[Committed("keep this one")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    # A fresh engine for the second session: `FakeSttEngine.finalize` drains
    # every remaining script entry, so one engine cannot serve two sessions —
    # the first session's stop would swallow the second session's lines.
    d.stt = FakeSttEngine([[Committed("drop this one")]])
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    assert (await d.handle({"cmd": "last"}))["text"] == "Keep this one."
