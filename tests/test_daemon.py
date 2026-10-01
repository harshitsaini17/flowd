import asyncio
import contextlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flowd import daemon as daemon_module
from flowd.audio import MicrophoneStuck
from flowd.config import Config, Hotkey, Inject, Settings, Ui
from flowd.daemon import Daemon
from flowd.inject.base import InjectResult
from flowd.levels import FLOOR_DB
from flowd.settings_api import Busy, Unavailable
from flowd.settings_server import Tokens
from flowd.state import Event as MachineEvent
from flowd.state import State
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
    """Records what the daemon tells flowd-ui.

    `calls` keeps the show/fade/hide lifecycle alone, so the older assertions
    on it still read as they did; `events` has every protocol call in order.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.events: list[tuple[Any, ...]] = []
        self.visible = False
        self.stopped = False
        self.started = False
        self.starts = 0
        # `start` and `stop` in order, kept apart from `calls` and `events`.
        self.lifecycle: list[str] = []

    def start(self) -> None:
        self.started = True
        self.starts += 1
        self.lifecycle.append("start")

    def state(self, state: str, reason: str = "") -> None:
        self.events.append(("state", state, reason))

    def end(self, state: str, reason: str = "", *, fade: bool) -> None:
        self.state(state, reason)
        if fade:
            self.fade()
        else:
            self.hide()

    def level(self, rms_db: float, peak_db: float) -> None:
        self.events.append(("level", rms_db, peak_db))

    def meta(self, mode: str, app: str, hotkey: str) -> None:
        self.events.append(("meta", mode, app, hotkey))

    def warn(self, reason: str | None, *, blocking: bool = False) -> None:
        self.events.append(("warn", reason, blocking))

    def configure(self, cfg: Ui, max_session_s: int) -> None:
        self.events.append(("configure", cfg, max_session_s))

    def states(self) -> list[tuple[str, str]]:
        return [(e[1], e[2]) for e in self.events if e[0] == "state"]

    def show(self) -> None:
        self.visible = True
        self.calls.append("show")
        self.events.append(("show",))

    def hide(self) -> None:
        self.visible = False
        self.calls.append("hide")
        self.events.append(("hide",))

    def fade(self) -> None:
        self.visible = False
        self.calls.append("fade")
        self.events.append(("fade",))

    def render(self, **zones: str) -> None:
        self.messages.append(dict(zones))

    def stop(self) -> None:
        self.stopped = True
        self.lifecycle.append("stop")


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

    # The settings page is off unless a test turns it on: a run loop would
    # otherwise bind 8178 next to the user's own daemon and adopt tokens from
    # the real runtime directory, which this suite does not isolate.
    return Daemon(
        cfg=cfg or Config(settings=Settings(enabled=False)),
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
    """Hotkey pressed and released with no speech."""
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


class ExplodingSttEngine:
    """An engine whose `feed` raises, the way a real decode can.

    Moonshine runs inference inside a vendored ONNX Runtime; a malformed block,
    an allocation failure or a stream left in a bad state surfaces here as an
    exception. `FakeSttEngine` and `BlockingSttEngine` both always succeed, so
    neither can reach the daemon's failure path.
    """

    def __init__(self) -> None:
        self.reset_calls = 0

    def feed(self, pcm: np.ndarray) -> list[Event]:
        raise RuntimeError("onnxruntime: allocation failed")

    def finalize(self) -> list[Event]:
        return []

    def reset(self) -> None:
        self.reset_calls += 1


async def test_a_failing_decode_releases_the_microphone_instead_of_killing_the_daemon() -> None:
    """A decode that raises must end the session, not the process.

    `pump` is awaited by `run`'s `while True`, so an exception escaping it
    unwinds the loop and the daemon exits — with the microphone still open,
    since nothing closed it on the way out. The user's hotkey then does nothing
    at all, and the only sign is a recording light that never goes off.

    Spec 4 gives this event a transition (any state + fatal error → IDLE,
    releasing the microphone) and spec 9.1 says the user must be told. Both
    exist; nothing reached them.
    """
    stt = ExplodingSttEngine()
    capture = FakeCapture()
    d = daemon(stt, capture)
    await d.handle({"cmd": "start"})
    assert capture.started is True

    await d.pump()  # must not raise

    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    assert capture.stopped is True, "microphone left open after a failed decode"
    assert d.session is None, "session survived a fatal error"


async def test_a_cancel_waiting_on_a_decode_cannot_discard_the_next_session() -> None:
    """A slow `cancel` must not reach past the session it was cancelling.

    `_discard` sets the state to IDLE and then awaits the STT lock, which a
    decode can hold for ~1.6 s. Debounce only suppresses a `start` for 200 ms,
    so a user who cancels and immediately re-presses their hotkey gets a new
    session while the old cancel is still queued. When it finally runs it
    resets the stream, writes the new session's metrics as cancelled and clears
    `self.session` — leaving the microphone open with no session attached, so
    the next `stop` finds nothing to inject and the words are gone.

    The lock is FIFO, so the queued reset still runs before the new session's
    first `feed`: the abandoned audio is flushed, which is what the reset is
    for. What must not follow it is the bookkeeping for a session that ended.
    """
    stt = BlockingSttEngine(block_s=1.0)
    d = daemon(stt)
    await d.handle({"cmd": "start"})

    pump = asyncio.create_task(d.pump())
    await asyncio.to_thread(stt.entered.wait, 3.0)
    cancel = asyncio.create_task(d.handle({"cmd": "cancel"}))
    await asyncio.sleep(0)  # let `_discard` reach the lock and block there

    # The user presses their hotkey again. `Clock` advances a second per call,
    # so this is well past the debounce window — a real re-press, not a bounce.
    assert (await d.handle({"cmd": "start"}))["ok"] is True
    new_session = d.session
    assert new_session is not None

    stt.release.set()
    await pump
    await cancel

    assert d.session is new_session, "the stale cancel discarded the new session"
    assert (await d.handle({"cmd": "status"}))["state"] == "recording"


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


async def test_reload_applies_a_new_debounce_to_the_live_state_machine(tmp_path: Path) -> None:
    """`flowctl reload` must change behaviour, not just the config object.

    `debounce_ms` is in the validated reloadable set, so a reload accepts it and
    reports `ok` — but `Machine` takes it at construction and keeps its own
    copy, so the window never moved. A user whose hotkey bounces raises the
    value, is told it worked, and finds nothing has changed; the only way out is
    a restart, which spec 8 says reload exists to avoid.

    Asserted through behaviour rather than by reading the value back, because
    the value was never the broken part: `d.cfg` was right all along.

    The window is raised rather than lowered, which is both the direction a
    user with a bouncing hotkey actually goes and the only one this clock can
    show: `Clock` advances a second per call, so any window shorter than that
    is already inert, and zero fails validation.
    """
    path = tmp_path / "config.toml"
    path.write_text("[hotkey]\ndebounce_ms = 60000\n")
    d = daemon(FakeSttEngine([[Committed("done")]]), clock=Clock())
    d.config_file = path

    # Under the default 200 ms window, presses a second apart are two distinct
    # commands: the second one stops the session it started.
    assert (await d.handle({"cmd": "toggle"}))["ok"] is True
    assert (await d.handle({"cmd": "toggle"}))["ok"] is True
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"

    assert (await d.handle({"cmd": "reload"}))["ok"] is True

    # A minute-wide window swallows presses this clock can never outrun, so the
    # press that just worked is now read as a bounce and ignored.
    assert (await d.handle({"cmd": "toggle"}))["ok"] is False
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"


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

    This sets the state directly mid-session: it pins `_render`'s split
    independently of when the scheduler resolves chunks. Each commit is at
    least `min_chunk_words`, so each becomes its own chunk.
    """
    d = daemon(
        FakeSttEngine(
            [[Committed("first chunk here right now")], [Committed("second chunk here right now")]]
        ),
        capture=FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(2)]),
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    assert d.session is not None
    d.session.chunks[0].polished = "First chunk here right now."
    d.session.chunks[0].state = "DONE"
    await d.pump()

    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.messages[-1]["polished"] == "First chunk here right now."
    assert overlay.messages[-1]["pending"] == "second chunk here right now"


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


# --- personal vocabulary (spec 7.6) -------------------------------------------


class KeytermEngine(FakeSttEngine):
    """A scripted engine that records the keyterms it is given."""

    def __init__(self, script: list[list[Event]]) -> None:
        super().__init__(script)
        self.keyterms: list[tuple[str, ...]] = []

    def set_keyterms(self, terms: tuple[str, ...]) -> None:
        self.keyterms.append(tuple(terms))


def vocab_daemon(stt: Any, vocab_file: Path, injected: list[str]) -> Daemon:
    d = daemon(stt, injected=injected)
    d.vocab_file = vocab_file
    d.config_file = vocab_file.with_name("config.toml")
    return d


async def test_vocab_replacements_apply_to_injected_text(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.toml"
    vocab.write_text('[replace]\n"stair-tier" = "STT"\n')
    injected: list[str] = []
    d = vocab_daemon(FakeSttEngine([[Committed("is it just a stair-tier model")]]), vocab, injected)
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})
    assert injected == ["Is it just a STT model."]


async def test_reload_pushes_vocab_terms_to_the_engine(tmp_path: Path) -> None:
    # The recognizer is what hears "LLM" as a word; biasing it is the fix, so
    # a reload that only updated the daemon's copy would change nothing.
    vocab = tmp_path / "vocab.toml"
    vocab.write_text('terms = ["LLM", "STT"]\n')
    engine = KeytermEngine([])
    d = vocab_daemon(engine, vocab, [])
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    assert engine.keyterms[-1] == ("LLM", "STT")


async def test_reload_with_bad_vocab_keeps_the_old_one(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.toml"
    vocab.write_text('[replace]\n"stair-tier" = "STT"\n')
    injected: list[str] = []
    d = vocab_daemon(FakeSttEngine([[Committed("a stair-tier model")]]), vocab, injected)
    assert (await d.handle({"cmd": "reload"}))["ok"] is True

    vocab.write_text("[replace\n")
    reply = await d.handle({"cmd": "reload"})
    assert reply["ok"] is False
    assert "vocab.toml" in reply["error"]

    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})
    assert injected == ["A STT model."]


async def test_engines_without_keyterms_are_left_alone(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.toml"
    vocab.write_text('terms = ["LLM"]\n')
    d = vocab_daemon(FakeSttEngine([]), vocab, [])
    assert (await d.handle({"cmd": "reload"}))["ok"] is True


async def test_startup_applies_vocab_before_the_first_session(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.toml"
    vocab.write_text('terms = ["LLM"]\n[replace]\n"stair-tier" = "STT"\n')
    engine = KeytermEngine([[Committed("a stair-tier model")]])
    injected: list[str] = []
    d = vocab_daemon(engine, vocab, injected)
    await d.load_startup_vocab()
    assert engine.keyterms == [("LLM",)]
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})
    assert injected == ["A STT model."]


async def test_startup_with_broken_vocab_still_dictates(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.toml"
    vocab.write_text("[replace\n")
    injected: list[str] = []
    d = vocab_daemon(FakeSttEngine([[Committed("still works")]]), vocab, injected)
    await d.load_startup_vocab()
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})
    assert injected == ["Still works."]


async def test_a_vocab_edit_applies_to_the_next_dictation_without_a_restart(
    tmp_path: Path,
) -> None:
    """Replacement works after `flowctl reload`, same daemon."""
    vocab = tmp_path / "vocab.toml"
    vocab.write_text("")
    injected: list[str] = []
    d = vocab_daemon(FakeSttEngine([[Committed("open hyper land")]]), vocab, injected)
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})

    vocab.write_text('[replace]\n"hyper land" = "Hyprland"\n')
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    d.stt = FakeSttEngine([[Committed("open hyper land")]])
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle"})
    assert injected == ["Open hyper land.", "Open Hyprland."]


class LosableCapture(FakeCapture):
    """A capture whose device can vanish mid-session, like AudioCapture's."""

    failed: str | None = None


async def test_a_lost_microphone_injects_the_text_so_far_and_notifies() -> None:
    """spec 9.2: PipeWire restarted or mic unplugged mid-session.

    Finalize with what was heard, inject it, then tell the user. Losing the
    words already spoken would break spec 9's first rule.
    """
    injected: list[str] = []
    capture = LosableCapture()
    d = daemon(FakeSttEngine([[Committed("keep what i said")]]), capture, injected)
    notes: list[str] = []
    d._notify = notes.append  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    await d.pump()
    capture.failed = "audio stream ended"
    await d.pump()
    await asyncio.gather(*d._background)
    assert injected == ["Keep what I said."]
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    assert notes and "microphone" in notes[0]
    assert "audio stream ended" in d.last_record["errors"][0]


async def test_a_lost_microphone_sends_exactly_one_notification_when_notify_on_finish() -> None:
    """The mic-lost notice already tells the user their text was kept; the

    generic `notify_on_finish` "pasted N words" note would be a second,
    redundant notification for the same session, so `_finalize` skips it when
    `mic_lost` is true.
    """
    injected: list[str] = []
    capture = LosableCapture()
    cfg = replace(Config(), ui=replace(Ui(), notify_on_finish=True))
    d = daemon(FakeSttEngine([[Committed("keep what i said")]]), capture, injected, cfg=cfg)
    notes: list[str] = []
    d._notify = notes.append  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    await d.pump()
    capture.failed = "audio stream ended"
    await d.pump()
    await asyncio.gather(*d._background)
    assert injected == ["Keep what I said."]
    assert len(notes) == 1
    assert "microphone" in notes[0]


async def test_a_lost_microphone_with_nothing_heard_injects_nothing() -> None:
    injected: list[str] = []
    capture = LosableCapture()
    d = daemon(FakeSttEngine([]), capture, injected)
    d._notify = lambda message: None  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    capture.failed = "audio stream ended"
    await d.pump()
    assert injected == []
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"


async def test_stt_falling_behind_warns_with_cpu_load_and_drops_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """spec 9.2: log a warning with CPU load; never drop audio."""

    class BacklogCapture(FakeCapture):
        def pending_seconds(self) -> float:
            return 2.5

    capture = BacklogCapture([np.zeros(1600, dtype=np.float32)] * 2)
    d = daemon(FakeSttEngine([[], []]), capture)
    await d.handle({"cmd": "start"})
    with caplog.at_level("WARNING", logger="flowd.daemon"):
        await d.pump()
    message = next(r.getMessage() for r in caplog.records if "behind" in r.getMessage())
    assert "load" in message
    assert len(capture.blocks) == 1  # read one block, dropped none


async def test_a_suspend_mid_session_cancels_it_and_injects_nothing() -> None:
    """spec 9.1: suspend or resume mid-session cancels the session and logs it.

    The words from before the lid closed are stale by the time it opens, and
    pasting them into whatever window has focus after resume is the worse
    failure.
    """
    from flowd.suspend import SleepDetector

    clocks = {"mono": 0.0, "boot": 0.0}
    injected: list[str] = []
    capture = FakeCapture([np.zeros(1600, dtype=np.float32)] * 2)
    d = daemon(FakeSttEngine([[Committed("before the lid closed")], []]), capture, injected)
    d.sleep = SleepDetector(monotonic=lambda: clocks["mono"], boottime=lambda: clocks["boot"])
    await d.handle({"cmd": "start"})
    await d.pump()
    clocks["boot"] += 120
    await d.pump()
    assert injected == []
    assert capture.stopped is True
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    assert "suspended" in d.last_record["errors"]


class StuckCapture(FakeCapture):
    """A capture whose abandoned stop may outlive the grace period (ADR 0015).

    `stuck` is what `settle()` reports: a stop still running past
    `LEAK_GRACE_S`, which may hold the device until the process exits.
    """

    stuck = False

    def settle(self) -> bool:
        return self.stuck


async def _start_run(d: Daemon, socket_path: Path) -> "asyncio.Task[None]":
    task = asyncio.create_task(d.run(socket_path))
    for _ in range(100):  # wait for the run loop to be up, without a fixed sleep
        if socket_path.exists():
            break
        await asyncio.sleep(0.01)
    return task


async def test_an_idle_daemon_with_a_stuck_microphone_exits_to_be_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abandoned stream can hold the device until the process exits, and
    only a restart frees it. systemd restarts on a non-zero exit."""
    notes: list[str] = []
    capture = StuckCapture()
    capture.stuck = True
    d = daemon(FakeSttEngine([]), capture=capture)
    monkeypatch.setattr(d, "_notify", notes.append)
    task = await _start_run(d, tmp_path / "flowd.sock")
    with pytest.raises(MicrophoneStuck):
        await asyncio.wait_for(task, timeout=2)
    assert any("microphone" in n for n in notes)


async def test_a_stuck_microphone_waits_for_the_session_to_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exiting mid-dictation would throw away what the user just said."""
    monkeypatch.setattr(Daemon, "_notify", lambda self, message: None)
    capture = StuckCapture()
    d = daemon(FakeSttEngine([]), capture=capture)
    await d.handle({"cmd": "start"})
    capture.stuck = True
    task = await _start_run(d, tmp_path / "flowd.sock")
    await asyncio.sleep(0.3)
    assert not task.done()
    assert d.machine.state is State.RECORDING
    await d.handle({"cmd": "stop"})
    with pytest.raises(MicrophoneStuck):
        await asyncio.wait_for(task, timeout=2)


async def test_an_indicator_click_toggles_on_the_loop() -> None:
    """flowd-ui's reader thread calls `on_ui_event`; the toggle must run on the
    daemon's loop, not on that thread."""
    d = daemon(FakeSttEngine([]))
    d.loop = asyncio.get_running_loop()
    seen: list[dict[str, Any]] = []

    async def handle(request: dict[str, Any]) -> dict[str, Any]:
        seen.append(request)
        return {"ok": True}

    d.handle = handle  # type: ignore[method-assign]
    thread = threading.Thread(target=d.on_ui_event, args=({"event": "click"},))
    thread.start()
    thread.join()
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen == [{"cmd": "toggle"}]


def test_ui_events_before_the_loop_starts_are_ignored() -> None:
    d = daemon(FakeSttEngine([]))
    d.on_ui_event({"event": "click"})
    d.on_ui_event({"event": "moved", "x": 0.5, "output": "eDP-1"})
    d.on_ui_event({"event": "whatever"})


async def test_the_ui_starts_only_once_the_socket_is_ours(tmp_path: Path) -> None:
    d = daemon(FakeSttEngine([]))
    socket_path = tmp_path / "flowd.sock"
    task = asyncio.create_task(d.run(socket_path))
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    for _ in range(100):
        if overlay.started:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert overlay.started is True
    assert overlay.stopped is True


async def test_a_second_daemon_never_starts_a_ui(tmp_path: Path) -> None:
    """Losing the single-instance check must not flash a second indicator."""
    from flowd.control import AlreadyRunning

    first = daemon(FakeSttEngine([]))
    socket_path = tmp_path / "flowd.sock"
    task = asyncio.create_task(first.run(socket_path))
    for _ in range(100):
        if socket_path.exists():
            break
        await asyncio.sleep(0.01)
    second = daemon(FakeSttEngine([]))
    try:
        with pytest.raises(AlreadyRunning):
            await second.run(socket_path)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    overlay = second.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.started is False


# --- flowd-ui protocol (ADR 0013) -------------------------------------------


def overlay_of(d: Daemon) -> FakeOverlay:
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    return overlay


async def test_a_session_reports_recording_finishing_done() -> None:
    d = daemon(FakeSttEngine([[Committed("some words here now")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    overlay = overlay_of(d)
    assert overlay.states() == [("recording", ""), ("finishing", ""), ("done", "")]
    # `show` first, since it clears the UI's state; the outcome before the fade.
    lifecycle = [e[0] for e in overlay.events if e[0] in ("show", "state", "fade", "hide")]
    assert lifecycle == ["show", "state", "state", "state", "fade"]
    assert "idle" not in [s for s, _ in overlay.states()]


async def test_recording_sends_meta_with_the_app_and_hotkey_label() -> None:
    from flowd.context import AppContext

    cfg = Config(ui=Ui(hotkey_label="Super D"))
    d = daemon(FakeSttEngine([]), cfg=cfg)
    d.context = lambda c: AppContext("kitty", "code", True)
    await d.handle({"cmd": "start"})
    assert ("meta", "code", "kitty", "Super D") in overlay_of(d).events


async def test_meta_for_an_unknown_app_sends_an_empty_name() -> None:
    d = daemon(FakeSttEngine([]))
    await d.handle({"cmd": "start"})
    assert ("meta", "default", "", "") in overlay_of(d).events


async def test_pump_sends_levels_while_recording_only() -> None:
    capture = FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(3)])
    d = daemon(FakeSttEngine([[], [], []]), capture=capture)
    await d.pump()  # idle: nothing read, nothing sent
    assert not any(e[0] == "level" for e in overlay_of(d).events)
    await d.handle({"cmd": "start"})
    await d.pump()
    levels = [e for e in overlay_of(d).events if e[0] == "level"]
    assert levels == [("level", -90.0, -90.0)] * 2  # 100 ms at 16 kHz: two windows
    await d.handle({"cmd": "stop"})
    await d.pump()
    assert len([e for e in overlay_of(d).events if e[0] == "level"]) == 2


async def test_levels_to_a_dead_ui_do_not_stop_the_session() -> None:
    class DeadPipe(FakeOverlay):
        def level(self, rms_db: float, peak_db: float) -> None:
            raise BrokenPipeError

    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("still typed")]]), injected=injected)
    d.overlay = DeadPipe()
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == ["Still typed."]


async def test_a_ui_that_raises_on_every_call_never_costs_a_dictation() -> None:
    class Broken(FakeOverlay):
        def __getattribute__(self, name: str) -> Any:
            if name in {"show", "state", "meta", "render", "end", "fade", "hide"}:
                raise RuntimeError("ui gone")
            return super().__getattribute__(name)

    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("still typed")]]), injected=injected)
    d.overlay = Broken()
    await d.handle({"cmd": "start"})
    await d.pump()
    reply = await d.handle({"cmd": "stop"})
    assert reply["ok"] is True
    assert injected == ["Still typed."]


async def test_a_failed_paste_reports_paste_failed() -> None:
    def failing_inject(text: str, inject_cfg: Inject, **kwargs: Any) -> InjectResult:
        return InjectResult(ok=False, error="no backend")

    d = daemon(FakeSttEngine([[Committed("kept anyway")]]))
    d.inject = failing_inject
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    overlay = overlay_of(d)
    assert overlay.states()[-1] == ("error", "paste_failed")
    assert overlay.calls[-1] == "fade"


async def test_a_lost_mic_reports_mic_lost() -> None:
    capture = LosableCapture()
    d = daemon(FakeSttEngine([[Committed("keep what i said")]]), capture)
    d._notify = lambda message: None  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    await d.pump()
    capture.failed = "audio stream ended"
    await d.pump()
    await asyncio.gather(*d._background)
    assert overlay_of(d).states()[-1] == ("error", "mic_lost")


async def test_a_lost_mic_with_nothing_heard_reports_mic_lost_empty() -> None:
    capture = LosableCapture()
    d = daemon(FakeSttEngine([]), capture)
    d._notify = lambda message: None  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    capture.failed = "audio stream ended"
    await d.pump()
    await asyncio.gather(*d._background)
    assert overlay_of(d).states()[-1] == ("error", "mic_lost_empty")


async def test_cancel_reports_cancelled_and_still_hides() -> None:
    d = daemon(FakeSttEngine([[Committed("discard me")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    overlay = overlay_of(d)
    assert overlay.states()[-1] == ("cancelled", "")
    assert overlay.events[-2:] == [("state", "cancelled", ""), ("hide",)]
    assert overlay.calls[-1] == "hide"


async def test_a_failing_decode_reports_dictation_failed() -> None:
    d = daemon(ExplodingSttEngine())
    d._notify = lambda message: None  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    await d.pump()
    assert overlay_of(d).states()[-1] == ("error", "dictation_failed")


async def test_a_suspend_reports_cancelled() -> None:
    from flowd.suspend import SleepDetector

    clocks = {"mono": 0.0, "boot": 0.0}
    d = daemon(FakeSttEngine([[Committed("before the lid closed")], []]))
    d.sleep = SleepDetector(monotonic=lambda: clocks["mono"], boottime=lambda: clocks["boot"])
    await d.handle({"cmd": "start"})
    clocks["boot"] += 120
    await d.pump()
    assert overlay_of(d).states()[-1] == ("cancelled", "")


async def test_no_speech_reports_nospeech() -> None:
    d = daemon(FakeSttEngine([]))
    await d.handle({"cmd": "start"})
    await d.handle({"cmd": "stop"})
    overlay = overlay_of(d)
    assert overlay.states()[-1] == ("nospeech", "")
    assert overlay.calls[-1] == "fade"


async def test_the_time_limit_reports_timelimit_before_finishing() -> None:
    cfg = Config(hotkey=Hotkey(debounce_ms=0))
    clock = Clock(step=0.0)
    d = daemon(FakeSttEngine([[Committed("ran out of time")]]), cfg=cfg, clock=clock)
    await d.handle({"cmd": "start"})
    await d.pump()
    clock.now += cfg.audio.max_session_s + 1
    await d._check_max_duration()
    assert overlay_of(d).states() == [
        ("recording", ""),
        ("timelimit", ""),
        ("finishing", ""),
        ("done", ""),
    ]


async def test_a_mic_that_will_not_open_warns_and_blocks() -> None:
    class FlakyCapture(FakeCapture):
        broken = True

        def start(self) -> None:
            if self.broken:
                raise OSError("device busy")
            super().start()

    capture = FlakyCapture()
    d = daemon(FakeSttEngine([]), capture=capture)
    d._notify = lambda message: None  # type: ignore[method-assign]
    await d.handle({"cmd": "start"})
    overlay = overlay_of(d)
    assert overlay.states() == [("error", "mic_unavailable")]
    assert overlay.calls == ["show", "hide"]
    assert ("warn", "Microphone unavailable", True) in overlay.events

    capture.broken = False
    await d.handle({"cmd": "start"})
    assert overlay.events[-1] != ("warn", "Microphone unavailable", True)
    assert ("warn", None, False) in overlay.events


async def test_reload_pushes_the_new_ui_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[ui]\nhotkey_label = "Super D"\n\n[audio]\nmax_session_s = 120\n')
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    d.vocab_file = tmp_path / "vocab.toml"
    assert (await d.handle({"cmd": "reload"}))["ok"] is True
    configured = [e for e in overlay_of(d).events if e[0] == "configure"]
    assert configured == [("configure", d.cfg.ui, d.cfg.audio.max_session_s)]
    assert d.cfg.ui.hotkey_label == "Super D"


async def test_a_bad_reload_leaves_the_ui_config_alone(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[ui]\nmax_lines = 0\n")
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    assert (await d.handle({"cmd": "reload"}))["ok"] is False
    assert not any(e[0] == "configure" for e in overlay_of(d).events)


async def test_a_click_while_finishing_is_ignored() -> None:
    """design.md "Finishing": a late click must not start a session over an
    unfinished paste."""
    d = daemon(FakeSttEngine([[Committed("some words here now")]]))
    d.loop = asyncio.get_running_loop()
    await d.handle({"cmd": "start"})
    await d.pump()
    d.machine.handle(MachineEvent.STOP)  # finalizing, as while the LLM finishes
    assert d.machine.state is State.FINALIZING
    d.on_ui_event({"event": "click"})
    await asyncio.gather(*d._background)
    await asyncio.sleep(0)
    await asyncio.gather(*d._background)
    assert d.machine.state is State.FINALIZING
    assert overlay_of(d).calls == ["show"]


async def test_a_click_at_idle_starts_a_session() -> None:
    d = daemon(FakeSttEngine([]))
    d.loop = asyncio.get_running_loop()
    d.on_ui_event({"event": "click"})
    for _ in range(50):
        if d.machine.state is State.RECORDING:
            break
        await asyncio.sleep(0.01)
    assert d.machine.state is State.RECORDING
    assert overlay_of(d).states() == [("recording", "")]


async def test_a_ui_that_will_not_start_does_not_stop_the_daemon(tmp_path: Path) -> None:
    class Unstartable(FakeOverlay):
        def start(self) -> None:
            super().start()
            raise OSError("no display")

    d = daemon(FakeSttEngine([]))
    d.overlay = Unstartable()
    task = await _start_run(d, tmp_path / "flowd.sock")
    await asyncio.sleep(0.3)
    assert not task.done()
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_the_idle_loop_brings_back_a_ui_that_died(tmp_path: Path) -> None:
    """`start` again from the idle loop; `UiProcess` rate-limits the respawn."""
    d = daemon(FakeSttEngine([]))
    task = await _start_run(d, tmp_path / "flowd.sock")
    await asyncio.sleep(0.5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert overlay_of(d).starts >= 2


async def test_the_idle_loop_does_not_start_the_ui_mid_session(tmp_path: Path) -> None:
    capture = FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(50)])
    d = daemon(FakeSttEngine([[] for _ in range(50)]), capture=capture)
    await d.handle({"cmd": "start"})
    task = await _start_run(d, tmp_path / "flowd.sock")
    await asyncio.sleep(0.05)  # past the one `start` once the socket is up
    before = overlay_of(d).starts
    await asyncio.sleep(0.3)
    after = overlay_of(d).starts
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert before == after == 1


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("cancelled", ("cancelled", "")),
        ("suspended", ("cancelled", "")),
        ("fatal error", ("error", "dictation_failed")),
        ("something new", ("cancelled", "")),
    ],
)
def test_discard_reasons_map_to_the_popup_outcomes(reason: str, outcome: tuple[str, str]) -> None:
    from flowd.daemon import discard_outcome

    assert discard_outcome(reason) == outcome


async def test_notify_on_finish_sends_one_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = replace(Config(), ui=replace(Ui(), notify_on_finish=True))
    d = daemon(FakeSttEngine([[Committed("ship it")]]), cfg=cfg)
    sent: list[str] = []
    monkeypatch.setattr(d, "_notify", sent.append)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    await asyncio.gather(*d._background)
    assert sent == ["flowd: pasted 2 words"]


async def test_notify_on_finish_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    d = daemon(FakeSttEngine([[Committed("ship it")]]))
    sent: list[str] = []
    monkeypatch.setattr(d, "_notify", sent.append)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    await asyncio.gather(*d._background)
    assert sent == []


# --- microphone test (settings page) -------------------------------------


class FailingCapture(FakeCapture):
    def start(self) -> None:
        raise OSError("device busy")


async def test_mic_test_streams_levels_then_releases_the_mic() -> None:
    d = daemon(FakeSttEngine([]))
    levels = [pair async for pair in d.mic_test(0.2)]
    assert levels  # FakeCapture's blocks produce windows
    assert d.capture.stopped
    assert not d.recording


async def test_mic_test_refused_while_recording() -> None:
    d = daemon(FakeSttEngine([[]]))
    await d.handle({"cmd": "start"})
    with pytest.raises(Busy):
        async for _ in d.mic_test(1):
            pass


async def test_mic_test_refused_while_another_runs() -> None:
    d = daemon(FakeSttEngine([]))
    first = d.mic_test(15)
    await anext(first)
    assert d.recording
    with pytest.raises(Busy):
        await anext(d.mic_test(1))
    await first.aclose()
    assert d.capture.stopped and not d.recording


async def test_dictation_start_ends_mic_test() -> None:
    d = daemon(FakeSttEngine([[Committed("hi")]]))
    gen = d.mic_test(15)
    await anext(gen)
    await d.handle({"cmd": "start"})
    rest = [p async for p in gen]
    assert d.mic_test_preempted and d.session is not None
    assert not d.capture.stopped  # the session kept the stream
    assert len(rest) <= 2


async def test_mic_test_open_failure_raises_and_frees_the_test() -> None:
    d = daemon(FakeSttEngine([]), capture=FailingCapture())
    with pytest.raises(OSError):
        await anext(d.mic_test(1))
    assert not d.recording
    # The failed test does not block the next one.
    d.capture = FakeCapture()
    assert [p async for p in d.mic_test(0.2)]


async def test_mic_test_after_a_preempted_one_is_not_preempted() -> None:
    d = daemon(FakeSttEngine([[]]))
    gen = d.mic_test(15)
    await anext(gen)
    await d.handle({"cmd": "start"})
    _ = [p async for p in gen]
    await d.handle({"cmd": "cancel"})
    assert d.session is None
    d.capture = FakeCapture()
    assert [p async for p in d.mic_test(0.2)]
    assert not d.mic_test_preempted and d.capture.stopped


def test_always_open_counts_as_recording() -> None:
    cfg = Config()
    d = daemon(FakeSttEngine([]), cfg=replace(cfg, audio=replace(cfg.audio, always_open=True)))
    assert d.recording


async def test_mic_test_releases_the_mic_when_the_preempting_dictation_fails_to_open() -> None:
    d = daemon(FakeSttEngine([[]]))
    gen = d.mic_test(15)
    await anext(gen)

    def refuse() -> None:
        raise OSError("device busy")

    d.capture.start = refuse  # type: ignore[method-assign]
    reply = await d.handle({"cmd": "start"})
    assert reply["ok"] is False and d.session is None
    _ = [p async for p in gen]
    # The dictation took the test's stream and then never owned one, so the
    # test is the last holder and must close it.
    assert d.mic_test_preempted and d.capture.stopped
    assert not d.recording


async def test_mic_test_reports_silence_while_the_device_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_module, "MIC_TEST_POLL_S", 0)
    d = daemon(FakeSttEngine([]), capture=FakeCapture(blocks=[]))
    levels = [pair async for pair in d.mic_test(10)]
    # Every read is empty, yet the stream keeps writing: one floor reading
    # per MIC_TEST_SILENT_POLLS empty reads.
    assert levels and all(pair == (FLOOR_DB, FLOOR_DB) for pair in levels)
    assert d.capture.stopped


# --- detect app and restart (settings page) ------------------------------


async def test_focused_app_waits_then_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(daemon_module, "DETECT_DELAY_S", 0.25)
    monkeypatch.setattr(daemon_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(daemon_module, "focused_app_id", lambda: "org.gnome.Terminal")
    d = daemon(FakeSttEngine([]))
    assert await d.focused_app() == "org.gnome.Terminal"
    assert slept == [0.25]


async def test_focused_app_none_when_the_desktop_cannot_tell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_module, "DETECT_DELAY_S", 0)
    monkeypatch.setattr(daemon_module, "focused_app_id", lambda: None)
    assert await daemon(FakeSttEngine([])).focused_app() is None


async def test_restart_ui_stops_and_starts_the_indicator() -> None:
    d = daemon(FakeSttEngine([]))
    await d.restart("ui", reset_position=False)
    assert overlay_of(d).lifecycle == ["stop", "start"]


def _position_file(root: Path) -> Path:
    path = root / "flowd" / "indicator.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"DP-1": 0.25}')
    return path


async def test_restart_ui_reset_position_deletes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = _position_file(tmp_path)
    d = daemon(FakeSttEngine([]))
    seen_at_start: list[bool] = []
    overlay = overlay_of(d)
    real_start = overlay.start

    def start() -> None:
        seen_at_start.append(path.exists())
        real_start()

    overlay.start = start  # type: ignore[method-assign]
    await d.restart("ui", reset_position=True)
    assert not path.exists()
    # Gone before the new flowd-ui reads it, so it starts at the default.
    assert seen_at_start == [False]
    assert overlay.lifecycle == ["stop", "start"]


async def test_restart_ui_reset_position_with_no_file_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    d = daemon(FakeSttEngine([]))
    await d.restart("ui", reset_position=True)
    assert overlay_of(d).lifecycle == ["stop", "start"]


async def test_restart_ui_keeps_the_position_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = _position_file(tmp_path)
    await daemon(FakeSttEngine([])).restart("ui", reset_position=False)
    assert path.exists()


def test_indicator_position_file_matches_flowd_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ui/src/position_store.cpp `default_position_file`: an absolute
    # $XDG_STATE_HOME, else $HOME/.local/state; a relative one is ignored.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert daemon_module.indicator_position_file() == tmp_path / "state/flowd/indicator.json"
    monkeypatch.setenv("XDG_STATE_HOME", "relative/state")
    expected = tmp_path / "home/.local/state/flowd/indicator.json"
    assert daemon_module.indicator_position_file() == expected
    monkeypatch.delenv("XDG_STATE_HOME")
    assert daemon_module.indicator_position_file() == expected
    monkeypatch.setenv("HOME", "")
    assert daemon_module.indicator_position_file() is None


async def test_restart_ui_with_the_indicator_off_is_refused() -> None:
    d = daemon(FakeSttEngine([]))
    d.overlay = None
    with pytest.raises(Unavailable, match="the indicator is turned off"):
        await d.restart("ui", reset_position=False)


async def test_restart_refused_during_a_session() -> None:
    d = daemon(FakeSttEngine([[]]))
    await d.handle({"cmd": "start"})
    with pytest.raises(Busy, match="finish the dictation first"):
        await d.restart("ui", reset_position=False)
    with pytest.raises(Busy):
        await d.restart("daemon", reset_position=False)
    assert overlay_of(d).lifecycle == []


async def test_idle_respawn_waits_for_a_ui_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    # The run loop's idle respawn must not start a flowd-ui while the old one
    # is still quitting, or the new one would read the position being reset.
    d = daemon(FakeSttEngine([]))
    overlay = overlay_of(d)
    released = threading.Event()

    def slow_stop() -> None:
        released.wait(2)
        overlay.lifecycle.append("stop")

    overlay.stop = slow_stop  # type: ignore[method-assign]
    restart = asyncio.create_task(d.restart("ui", reset_position=False))
    await asyncio.sleep(0.05)
    d._start_ui()
    assert overlay.lifecycle == []
    released.set()
    await restart
    assert overlay.lifecycle == ["stop", "start"]
    d._start_ui()
    assert overlay.lifecycle == ["stop", "start", "start"]


async def test_restart_daemon_outside_systemd_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    spawned: list[Any] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Any:
        spawned.append(argv)
        raise AssertionError("must not spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    d = daemon(FakeSttEngine([]))
    with pytest.raises(Unavailable, match="not running under systemd"):
        await d.restart("daemon", reset_position=False)
    await asyncio.sleep(0.35)
    assert spawned == []
    assert not (tmp_path / "flowd" / "settings-tokens.json").exists()


class _FakeProc:
    def __init__(self, code: int = 0) -> None:
        self.returncode = code

    async def wait(self) -> int:
        return self.returncode


async def test_restart_daemon_under_systemd_writes_tokens_and_schedules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVOCATION_ID", "abc123")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    spawned: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Any:
        spawned.append((argv, kwargs))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    stale = tmp_path / "flowd" / "settings-tokens.json"
    stale.parent.mkdir()
    stale.write_text('{"tokens": ["old"]}')
    stale.chmod(0o644)
    d = daemon(FakeSttEngine([]))
    tokens = Tokens()
    issued = tokens.issue()
    d.settings_tokens = tokens
    await d.restart("daemon", reset_position=False)
    # The reply goes out before systemd stops us: nothing is spawned yet.
    assert spawned == []
    path = tmp_path / "flowd" / "settings-tokens.json"
    assert json.loads(path.read_text()) == {"tokens": [issued]}
    assert path.stat().st_mode & 0o777 == 0o600
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv == ("systemctl", "--user", "--no-block", "restart", "flowd.service")
    assert kwargs["start_new_session"] is True
    for stream in ("stdin", "stdout", "stderr"):
        assert kwargs[stream] == asyncio.subprocess.DEVNULL


async def test_restart_daemon_without_tokens_still_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVOCATION_ID", "abc123")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    spawned: list[tuple[str, ...]] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Any:
        spawned.append(argv)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    d = daemon(FakeSttEngine([]))
    assert d.settings_tokens is None
    await d.restart("daemon", reset_position=False)
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert spawned == [("systemctl", "--user", "--no-block", "restart", "flowd.service")]
    assert not (tmp_path / "flowd" / "settings-tokens.json").exists()


async def test_restart_unknown_target_is_refused() -> None:
    with pytest.raises(Unavailable):
        await daemon(FakeSttEngine([])).restart("everything", reset_position=False)


async def test_overlapping_ui_restarts_start_after_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A plain restart and a reset in flight together: no flowd-ui may start
    # while the position file is still there to be deleted.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = _position_file(tmp_path)
    d = daemon(FakeSttEngine([]))
    overlay = overlay_of(d)
    gates = [threading.Event(), threading.Event()]
    stops = iter(gates)
    seen_at_start: list[bool] = []

    def slow_stop() -> None:
        next(stops).wait(2)
        overlay.lifecycle.append("stop")

    def start() -> None:
        seen_at_start.append(path.exists())
        overlay.lifecycle.append("start")

    overlay.stop = slow_stop  # type: ignore[method-assign]
    overlay.start = start  # type: ignore[method-assign]
    first = asyncio.create_task(d.restart("ui", reset_position=False))
    second = asyncio.create_task(d.restart("ui", reset_position=True))
    await asyncio.sleep(0.05)
    gates[0].set()
    await first
    # The first restart is done; the second is still waiting to stop the UI.
    d._start_ui()  # the run loop's idle respawn
    gates[1].set()
    await second
    assert overlay.lifecycle == ["stop", "start", "stop", "start"]
    assert seen_at_start == [True, False]


async def test_restart_ui_reset_failure_still_restarts_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # A directory where the file should be: unlink raises.
    (tmp_path / "flowd" / "indicator.json").mkdir(parents=True)
    d = daemon(FakeSttEngine([]))
    with pytest.raises(Unavailable, match="could not reset the position"):
        await d.restart("ui", reset_position=True)
    assert overlay_of(d).lifecycle == ["stop", "start"]


def _record_spawns(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[tuple[str, ...]]:
    spawned: list[tuple[str, ...]] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Any:
        spawned.append(argv)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return spawned


def _systemd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INVOCATION_ID", "abc123")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path / "flowd" / "settings-tokens.json"


def _with_tokens(d: Daemon) -> None:
    tokens = Tokens()
    tokens.issue()
    d.settings_tokens = tokens


async def test_restart_daemon_requests_in_the_delay_schedule_one_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _systemd(tmp_path, monkeypatch)
    spawned = _record_spawns(monkeypatch, _FakeProc())
    d = daemon(FakeSttEngine([]))
    _with_tokens(d)
    await d.restart("daemon", reset_position=False)
    await d.restart("daemon", reset_position=False)
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert len(spawned) == 1


async def test_restart_daemon_waits_for_a_dictation_that_starts_in_the_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _systemd(tmp_path, monkeypatch)
    spawned = _record_spawns(monkeypatch, _FakeProc())
    d = daemon(FakeSttEngine([]))
    _with_tokens(d)
    await d.restart("daemon", reset_position=False)
    d.session = object()  # type: ignore[assignment]  # a dictation began in the delay
    await asyncio.sleep(0.7)
    assert spawned == []
    d.session = None
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert len(spawned) == 1


@pytest.mark.parametrize("result", [_FakeProc(1), OSError("no systemctl")])
async def test_restart_daemon_failure_removes_the_tokens_and_allows_a_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: Any
) -> None:
    path = _systemd(tmp_path, monkeypatch)
    spawned = _record_spawns(monkeypatch, result)
    d = daemon(FakeSttEngine([]))
    _with_tokens(d)
    await d.restart("daemon", reset_position=False)
    assert path.exists()
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert len(spawned) == 1
    assert not path.exists()
    # Nothing is pending any more, so the page can ask again.
    await d.restart("daemon", reset_position=False)
    await asyncio.sleep(0.35)
    await asyncio.gather(*d._background)
    assert len(spawned) == 2


async def test_restart_daemon_tokens_write_failure_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _systemd(tmp_path, monkeypatch)
    # A file where the runtime directory should be: mkdir raises.
    (tmp_path / "flowd").write_text("")
    spawned = _record_spawns(monkeypatch, _FakeProc())
    d = daemon(FakeSttEngine([]))
    _with_tokens(d)
    with pytest.raises(Unavailable, match="signed in"):
        await d.restart("daemon", reset_position=False)
    await asyncio.sleep(0.35)
    assert spawned == []


# --- settings server wiring --------------------------------------------------


def _settings_cfg(port: int = 0, *, enabled: bool = True) -> Config:
    return Config(settings=Settings(enabled=enabled, port=port))


async def _settings_reply(d: Daemon) -> dict[str, Any]:
    """`settings` once the run loop has tried to start the server."""
    reply: dict[str, Any] = {}
    for _ in range(200):
        reply = await d.handle({"cmd": "settings"})
        if reply.get("ok") or reply.get("error") != daemon_module.SETTINGS_NOT_STARTED:
            return reply
        await asyncio.sleep(0.01)
    return reply


async def _stop_run(task: "asyncio.Task[None]") -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _http_get(port: int, path: str, token: str | None) -> int:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    auth = f"Authorization: Bearer {token}\r\n" if token else ""
    writer.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{auth}\r\n".encode())
    await writer.drain()
    status_line = await reader.readline()
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return int(status_line.split()[1])


async def test_settings_command_returns_a_tokened_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    task = await _start_run(d, tmp_path / "flowd.sock")
    try:
        reply = await _settings_reply(d)
        assert reply["ok"] is True, reply
        assert d.settings_server is not None
        port = d.settings_server.port
        assert port != 0
        prefix = f"http://127.0.0.1:{port}/#token="
        assert reply["url"].startswith(prefix)
        token = reply["url"][len(prefix) :]
        assert d.settings_tokens is not None and d.settings_tokens.valid(token)
        assert await _http_get(port, "/api/status", None) == 403
        assert await _http_get(port, "/api/status", token) == 200
        # Each request issues a fresh token; the earlier one stays valid.
        again = await d.handle({"cmd": "settings"})
        assert again["url"] != reply["url"]
        assert d.settings_tokens.valid(token)
    finally:
        await _stop_run(task)
    # The socket is closed with the daemon.
    with pytest.raises(OSError):
        await _http_get(port, "/api/status", token)


async def test_settings_disabled_means_no_socket_and_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg(enabled=False))
    task = await _start_run(d, tmp_path / "flowd.sock")
    try:
        reply = await _settings_reply(d)
        assert reply == {
            "ok": False,
            "error": "the settings page is turned off ([settings] enabled = false)",
        }
        assert d.settings_server is None
    finally:
        await _stop_run(task)


async def test_settings_port_taken_keeps_dictation_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import socket

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as squatter:
        squatter.bind(("127.0.0.1", 0))
        squatter.listen()
        port = squatter.getsockname()[1]
        injected: list[str] = []
        capture = FakeCapture([np.zeros(1600, dtype=np.float32) for _ in range(5)])
        d = daemon(
            FakeSttEngine([[Committed("ship it")]]),
            capture,
            injected,
            cfg=_settings_cfg(port),
        )
        with caplog.at_level("WARNING", logger="flowd.daemon"):
            task = await _start_run(d, tmp_path / "flowd.sock")
            try:
                reply = await _settings_reply(d)
                assert reply["ok"] is False
                assert reply["error"] == f"port {port} is in use"
                assert any(
                    r.levelname == "WARNING" and "settings page off" in r.getMessage()
                    for r in caplog.records
                )
                assert (await d.handle({"cmd": "start"}))["ok"] is True
                await asyncio.sleep(0.1)
                assert (await d.handle({"cmd": "stop"}))["ok"] is True
                assert not task.done()
            finally:
                await _stop_run(task)
    assert injected == ["Ship it."]


def _tokens_file(tmp_path: Path, tokens: list[str], mode: int = 0o600) -> Path:
    path = tmp_path / "flowd" / "settings-tokens.json"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(json.dumps({"tokens": tokens}))
    path.chmod(mode)
    return path


async def _run_until_settings(d: Daemon, tmp_path: Path) -> None:
    task = await _start_run(d, tmp_path / "flowd.sock")
    try:
        assert (await _settings_reply(d))["ok"] is True
    finally:
        await _stop_run(task)


async def test_tokens_file_is_adopted_and_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, ["kept-from-the-last-daemon"])
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert d.settings_tokens.valid("kept-from-the-last-daemon")
    assert not path.exists()


async def test_a_stale_tokens_file_is_deleted_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, ["old"])
    long_ago = time.time() - 61
    os.utime(path, (long_ago, long_ago))
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert not d.settings_tokens.valid("old")
    assert not path.exists()


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o660])
async def test_a_tokens_file_others_can_reach_is_deleted_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    """The /tmp fallback is not a private tmpfs: a file anyone else could
    have read or written proves nothing about who left it."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, ["planted"], mode)
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert not d.settings_tokens.valid("planted")
    assert not path.exists()


async def test_a_symlinked_tokens_file_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"tokens": ["linked"]}))
    target.chmod(0o600)
    link = tmp_path / "flowd" / "settings-tokens.json"
    link.parent.mkdir(mode=0o700)
    link.symlink_to(target)
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert not d.settings_tokens.valid("linked")
    assert not link.is_symlink()
    assert target.exists()


@pytest.mark.parametrize(
    "body", ["not json", "[]", '{"tokens": "abc"}', '{"tokens": [1, 2]}', '{"other": []}']
)
async def test_a_malformed_tokens_file_is_deleted_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, [])
    path.write_text(body)
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert d.settings_tokens.export() != []  # just the one `settings` issued
    assert len(d.settings_tokens.export()) == 1
    assert not path.exists()


async def test_a_disabled_page_leaves_the_tokens_file_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off means the daemon does nothing for the page; a later daemon with it
    on rejects the file as too old."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, ["unused"])
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg(enabled=False))
    task = await _start_run(d, tmp_path / "flowd.sock")
    await _stop_run(task)
    assert path.exists()
    assert d.settings_tokens is None


def test_metrics_file_defaults_to_the_state_dir() -> None:
    from flowd.config import state_dir

    assert daemon(FakeSttEngine([])).metrics_file == state_dir() / "metrics.jsonl"


def test_metrics_file_prefers_the_given_path(tmp_path: Path) -> None:
    d = daemon(FakeSttEngine([]), metrics_path=tmp_path / "m.jsonl")
    assert d.metrics_file == tmp_path / "m.jsonl"


async def test_reload_method_returns_the_error_text(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = -1\n")
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    error = await d.reload()
    assert isinstance(error, str) and error
    path.write_text("[vad]\ncommit_silence_ms = 500\n")
    assert await d.reload() is None
    assert d.cfg.vad.commit_silence_ms == 500


class _FakeCleanup:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.checks = 0

    async def check_health(self) -> bool:
        self.checks += 1
        return not self.down

    async def aclose(self) -> None:
        pass


def test_daemon_status_reports_models_and_state() -> None:
    d = daemon(FakeSttEngine([]))
    status = d.daemon_status()
    assert status["state"] == "idle"
    assert status["stt_model"] == d.cfg.stt.model
    assert status["final_model"] == d.cfg.stt.final_model
    assert status["health_checked_s_ago"] is None


def test_daemon_status_cleanup_states() -> None:
    d = daemon(FakeSttEngine([]))
    assert d.daemon_status()["cleanup"] == "offline"  # no client
    d.cleanup = _FakeCleanup()  # type: ignore[assignment]
    assert d.daemon_status()["cleanup"] == "ready"
    d.cleanup = _FakeCleanup(down=True)  # type: ignore[assignment]
    assert d.daemon_status()["cleanup"] == "offline"
    d.cfg = replace(d.cfg, llm=replace(d.cfg.llm, enabled=False))
    assert d.daemon_status()["cleanup"] == "disabled"


async def test_the_health_loop_stamps_when_it_checked() -> None:
    d = daemon(FakeSttEngine([]))
    d.cleanup = _FakeCleanup()  # type: ignore[assignment]
    loop = asyncio.create_task(d._health_loop())
    for _ in range(100):
        if d.daemon_status()["health_checked_s_ago"] is not None:
            break
        await asyncio.sleep(0.01)
    loop.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await loop
    ago = d.daemon_status()["health_checked_s_ago"]
    assert isinstance(ago, float) and 0 <= ago < 5


async def test_a_deeply_nested_tokens_file_is_rejected_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`json.loads` raises RecursionError, not ValueError, on deep nesting."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, [])
    path.write_text("[" * 60_000)
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert len(d.settings_tokens.export()) == 1
    assert not path.exists()


async def test_a_tokens_file_from_the_future_is_deleted_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _tokens_file(tmp_path, ["from-the-future"])
    later = time.time() + 3600
    os.utime(path, (later, later))
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    await _run_until_settings(d, tmp_path)
    assert d.settings_tokens is not None
    assert not d.settings_tokens.valid("from-the-future")
    assert not path.exists()


class _FailingCleanup(_FakeCleanup):
    async def aclose(self) -> None:
        raise RuntimeError("client already broken")


async def test_a_failing_cleanup_close_still_closes_both_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = daemon(FakeSttEngine([]), cfg=_settings_cfg())
    d.cleanup = _FailingCleanup()  # type: ignore[assignment]
    sock = tmp_path / "flowd.sock"
    task = await _start_run(d, sock)
    assert (await _settings_reply(d))["ok"] is True
    assert d.settings_server is not None
    port = d.settings_server.port
    await _stop_run(task)
    assert d.settings_server is None
    with pytest.raises(OSError):
        await _http_get(port, "/", None)
    with pytest.raises(OSError):
        await asyncio.open_unix_connection(str(sock))
    overlay = overlay_of(d)
    assert overlay.stopped is True
