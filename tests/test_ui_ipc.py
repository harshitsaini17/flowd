"""Tests for the flowd-ui child-process wrapper (ADR 0013).

The property under test throughout is that nothing here raises into, or
blocks, the dictation path. `FakeProc` stands in for `Popen` for the logic;
the tests that need real pipes and threads run a small Python script as the
child (`fake_ui`), so none of this needs GTK or a display.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from flowd import ui_ipc
from flowd.config import Ui, ui_fields
from flowd.ui_ipc import MAX_SPAWN_FAILURES, RESPAWN_BACKOFF_S, UiProcess

BINARY = Path(sys.executable)  # exists, so the "missing binary" check passes


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeStdin:
    def __init__(self, proc: FakeProc) -> None:
        self.proc = proc
        self.closed = False

    def write(self, data: bytes) -> int | None:
        if self.proc.broken or self.closed:
            raise BrokenPipeError("child is gone")
        room = self.proc.capacity - self.proc.unread
        if room <= 0:
            return None  # EAGAIN on a non-blocking pipe
        taken = data[:room]
        self.proc.written += taken
        self.proc.unread += len(taken)
        return len(taken)

    def close(self) -> None:
        self.closed = True


class FakeProc:
    """A `Popen` reduced to what `UiProcess` touches. `capacity` models the
    pipe buffer: `unread` bytes the child has not consumed yet."""

    def __init__(self, rc: int | None = None, capacity: int = 1 << 30) -> None:
        self.written = b""
        self.rc = rc
        self.broken = rc is not None
        self.capacity = capacity
        self.unread = 0
        self.terminated = False
        self.killed = False
        self.waited = False
        self.stdin = FakeStdin(self)
        self.stdout = None

    def poll(self) -> int | None:
        return self.rc

    def die(self, rc: int) -> None:
        self.rc = rc
        self.broken = True

    def terminate(self) -> None:
        self.terminated = True
        self.die(-15)

    def kill(self) -> None:
        self.killed = True
        self.die(-9)

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        if self.rc is None:
            raise subprocess.TimeoutExpired("flowd-ui", timeout or 0)
        return self.rc


def messages(proc: FakeProc) -> list[dict[str, Any]]:
    return [json.loads(line) for line in proc.written.decode().splitlines() if line]


def types(proc: FakeProc) -> list[str]:
    return [m["type"] for m in messages(proc)]


def ui_with_proc(
    cfg: Ui | None = None, proc: FakeProc | None = None, **kwargs: Any
) -> tuple[UiProcess, FakeProc]:
    p = proc or FakeProc()
    ui = UiProcess(cfg or Ui(), 300, binary=BINARY, spawn=lambda *_a, **_k: p, **kwargs)
    return ui, p


def counting_ui(
    cfg: Ui | None = None,
    make: Callable[[], FakeProc] = FakeProc,
    **kwargs: Any,
) -> tuple[UiProcess, list[FakeProc]]:
    spawned: list[FakeProc] = []

    def spawn(*_a: Any, **_k: Any) -> FakeProc:
        spawned.append(make())
        return spawned[-1]

    return UiProcess(cfg or Ui(), 300, binary=BINARY, spawn=spawn, **kwargs), spawned


# --- spawning and the first message ---


def test_start_spawns_the_indicator_at_idle() -> None:
    ui, spawned = counting_ui(Ui(indicator=True))
    ui.start()
    assert len(spawned) == 1


def test_start_does_nothing_when_the_indicator_is_off() -> None:
    ui, spawned = counting_ui(Ui(indicator=False))
    ui.start()
    assert spawned == []


def test_nothing_is_spawned_at_construction() -> None:
    ui, spawned = counting_ui()
    assert spawned == []
    assert ui.alive is False


def test_argv_is_just_the_binary_with_dedicated_pipes() -> None:
    captured: list[tuple[list[str], dict[str, Any]]] = []

    def spawn(argv: list[str], **kwargs: Any) -> FakeProc:
        captured.append((list(argv), kwargs))
        return FakeProc()

    UiProcess(Ui(), 300, binary=BINARY, spawn=spawn).show()
    argv, kwargs = captured[0]
    assert argv == [str(BINARY)]
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stdout"] is subprocess.PIPE
    assert "shell" not in kwargs


def test_the_first_message_is_config() -> None:
    ui, proc = ui_with_proc(Ui(theme="dark"))
    ui.show()
    first = messages(proc)[0]
    assert first == {"type": "config", "ui": {**ui_fields(Ui(theme="dark"), 300)}}
    assert first["ui"]["max_session_s"] == 300
    assert "enabled" not in first["ui"]
    assert types(proc)[1] == "show"


def test_disabled_ui_never_spawns() -> None:
    ui, spawned = counting_ui(Ui(enabled=False))
    ui.start()
    ui.show()
    ui.render(polished="", pending="", live="x")
    ui.warn("mic")
    ui.stop()
    assert spawned == []


def test_binary_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLOWD_UI", str(tmp_path / "custom"))
    assert ui_ipc.find_binary() == tmp_path / "custom"


def test_a_missing_binary_is_logged_once_and_never_retried_per_render(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spawned: list[int] = []

    def spawn(*_a: Any, **_k: Any) -> FakeProc:
        spawned.append(1)
        return FakeProc()

    ui = UiProcess(Ui(), 300, binary=tmp_path / "nope", spawn=spawn)
    with caplog.at_level(logging.WARNING, logger="flowd.ui_ipc"):
        ui.start()
        for _ in range(20):
            ui.render(polished="", pending="", live="x")
        ui.show()
        ui.show()
    assert spawned == []
    assert sum("not found" in r.message for r in caplog.records) == 1


# --- encoding ---


def test_new_messages_are_one_json_line_each() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.state("fallback", "timeout")
    ui.level(-20.5, -3.0)
    ui.meta("prose", "kitty", "Super+D")
    ui.warn(None)
    assert messages(proc)[-4:] == [
        {"type": "state", "state": "fallback", "reason": "timeout"},
        {"type": "level", "rms_db": -20.5, "peak_db": -3.0},
        {"type": "meta", "mode": "prose", "app": "kitty", "hotkey": "Super+D"},
        {"type": "warn", "reason": None, "blocking": False},
    ]


def test_render_newlines_stay_inside_one_line() -> None:
    ui, proc = ui_with_proc()
    ui.render(polished="", pending="two\nlines", live="tab\there")
    last = proc.written.decode().splitlines()[-1]
    assert json.loads(last)["pending"] == "two\nlines"


def test_silence_is_sent_as_a_finite_level() -> None:
    """`json.dumps(-inf)` is `-Infinity`, which flowd-ui cannot parse."""
    ui, proc = ui_with_proc()
    ui.show()
    ui.level(float("-inf"), float("nan"))
    raw = proc.written.decode().splitlines()[-1]
    assert "Infinity" not in raw and "NaN" not in raw
    assert json.loads(raw) == {
        "type": "level",
        "rms_db": ui_ipc.LEVEL_FLOOR_DB,
        "peak_db": ui_ipc.LEVEL_FLOOR_DB,
    }


def test_unknown_states_are_not_sent() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.state("no_speech")  # the ADR spells it `nospeech`
    assert "state" not in types(proc)


def test_level_and_state_never_spawn() -> None:
    ui, spawned = counting_ui()
    ui.level(-20.0, -10.0)
    ui.state("recording")
    ui.fade()
    ui.hide()
    assert spawned == []


# --- order ---


def test_end_sends_the_terminal_state_before_fade() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.end("done", fade=True)
    assert types(proc)[-2:] == ["state", "fade"]
    assert messages(proc)[-2]["state"] == "done"


def test_end_sends_the_terminal_state_before_hide() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.end("cancelled", fade=False)
    assert types(proc)[-2:] == ["state", "hide"]


def test_order_is_kept_through_a_backlog() -> None:
    """A full pipe must delay messages, never reorder them."""
    proc = FakeProc(capacity=0)
    ui, _ = ui_with_proc(proc=proc)
    ui.show()
    ui.render(polished="", pending="", live="a")
    ui.end("done", fade=True)
    proc.capacity = 1 << 30
    deadline = time.monotonic() + 2
    while "fade" not in types(proc) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert types(proc) == ["config", "show", "render", "state", "fade"]


# --- backpressure ---


def test_levels_are_dropped_first_when_the_pipe_is_full() -> None:
    proc = FakeProc(capacity=0)
    ui, _ = ui_with_proc(proc=proc)
    ui.show()  # config + show wait in the backlog
    for _ in range(50):
        ui.level(-20.0, -10.0)
    ui.state("finishing")
    kinds = [q.kind for q in ui._backlog]
    assert "level" not in kinds
    assert kinds == ["config", "show", "state"]
    proc.capacity = 1 << 30
    ui.stop()


def test_a_queued_render_is_replaced_by_the_next() -> None:
    proc = FakeProc(capacity=0)
    ui, _ = ui_with_proc(proc=proc)
    ui.show()
    for i in range(30):
        ui.render(polished="", pending="", live=str(i))
    renders = [q for q in ui._backlog if q.kind == "render"]
    assert len(renders) == 1
    assert json.loads(renders[0].data)["live"] == "29"
    ui.stop()


def test_writes_do_not_block_on_a_full_pipe() -> None:
    proc = FakeProc(capacity=0)
    ui, _ = ui_with_proc(proc=proc)
    started = time.monotonic()
    ui.show()
    for i in range(200):
        ui.meta("code", "kitty", str(i))
    assert time.monotonic() - started < 0.5
    ui.stop()


def test_a_ui_that_never_reads_is_killed_and_counted() -> None:
    proc = FakeProc(capacity=0)
    ui, _ = ui_with_proc(proc=proc)
    ui.show()
    big = "x" * 4096
    for i in range(ui_ipc.MAX_BACKLOG_BYTES // 4096 + 2):
        ui.meta("code", big, str(i))  # distinct, so nothing coalesces
    assert proc.killed is True
    assert ui.alive is False


# --- failures and respawn ---


def test_broken_pipe_is_swallowed() -> None:
    proc = FakeProc()
    ui, _ = ui_with_proc(proc=proc)
    ui.show()
    proc.broken = True  # pipe broke; process not reaped yet
    ui.render(polished="", pending="", live="still fine")
    ui.meta("a", "b", "c")
    assert ui.alive is False


def test_spawn_failure_is_swallowed() -> None:
    def spawn(*_a: Any, **_k: Any) -> Any:
        raise PermissionError("flowd-ui")

    ui = UiProcess(Ui(), 300, binary=BINARY, spawn=spawn)
    ui.show()
    ui.render(polished="", pending="", live="x")
    assert ui.alive is False


def test_a_crashing_ui_is_respawned_up_to_the_limit() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(clock=clock)
    for _ in range(MAX_SPAWN_FAILURES + 3):
        ui.render(polished="", pending="", live="x")
        if spawned:
            spawned[-1].die(1)
        ui.render(polished="", pending="", live="x")  # notices the death
        clock.now += RESPAWN_BACKOFF_S + 1
    ui.render(polished="", pending="", live="x")
    assert len(spawned) == MAX_SPAWN_FAILURES


def test_show_forgives_crashes() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(clock=clock)
    for _ in range(MAX_SPAWN_FAILURES):
        ui.render(polished="", pending="", live="x")
        spawned[-1].die(1)
        ui.render(polished="", pending="", live="x")  # notices the death
        clock.now += RESPAWN_BACKOFF_S + 1
    ui.render(polished="", pending="", live="x")
    assert len(spawned) == MAX_SPAWN_FAILURES
    ui.show()
    assert len(spawned) == MAX_SPAWN_FAILURES + 1


def test_a_normal_exit_is_not_a_crash() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(clock=clock)
    for _ in range(MAX_SPAWN_FAILURES + 2):
        ui.render(polished="", pending="", live="x")
        spawned[-1].die(0)
        ui.render(polished="", pending="", live="x")  # notices the exit
        clock.now += RESPAWN_BACKOFF_S + 1
    ui.render(polished="", pending="", live="x")
    assert len(spawned) == MAX_SPAWN_FAILURES + 3


def test_a_child_that_dies_at_idle_is_respawned_after_the_backoff() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(Ui(indicator=True), clock=clock)
    ui.start()
    spawned[0].die(1)
    ui.start()  # notices the death; the clock starts here
    clock.now += RESPAWN_BACKOFF_S - 0.1
    ui.start()
    assert len(spawned) == 1
    clock.now += 0.2
    ui.start()
    assert len(spawned) == 2


def test_exit_3_stops_all_spawns_until_reload() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(clock=clock)
    ui.show()
    spawned[0].die(3)
    clock.now += 1000
    ui.show()  # show forgives crashes, not "unsupported"
    ui.start()
    ui.render(polished="", pending="", live="x")
    assert len(spawned) == 1
    assert ui.unsupported is True
    ui.configure(Ui(), 300)
    assert ui.unsupported is False
    ui.show()
    assert len(spawned) == 2


def test_a_respawned_ui_gets_the_current_warning_and_state() -> None:
    clock = FakeClock()
    ui, spawned = counting_ui(clock=clock)
    ui.show()
    ui.warn("microphone busy", blocking=True)
    ui.state("recording")
    spawned[0].die(1)
    ui.show()
    assert messages(spawned[1])[:3] == [
        {"type": "config", "ui": ui_fields(Ui(), 300)},
        {"type": "warn", "reason": "microphone busy", "blocking": True},
        {"type": "state", "state": "recording", "reason": ""},
    ]


def test_a_cleared_warning_is_not_replayed() -> None:
    ui, spawned = counting_ui()
    ui.show()
    ui.warn("x")
    ui.warn(None)
    spawned[0].die(1)
    ui.show()
    assert "warn" not in types(spawned[1])


def test_configure_sends_config_to_a_live_ui() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.configure(Ui(theme="light", max_lines=6), 120)
    assert messages(proc)[-1] == {
        "type": "config",
        "ui": ui_fields(Ui(theme="light", max_lines=6), 120),
    }


def test_configure_to_disabled_stops_the_ui() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.configure(Ui(enabled=False), 300)
    assert ui.alive is False
    assert types(proc)[-1] == "quit"


def test_stop_lets_a_child_that_obeys_quit_exit() -> None:
    proc = FakeProc()
    original = proc.stdin.write

    def write(data: bytes) -> int | None:
        n = original(data)
        if b'"quit"' in data:
            proc.rc = 0
        return n

    proc.stdin.write = write  # type: ignore[method-assign]
    ui, _ = ui_with_proc(proc=proc)
    ui.show()
    ui.stop()
    assert types(proc)[-1] == "quit"
    assert proc.terminated is False


def test_stop_terminates_a_child_that_ignores_quit() -> None:
    ui, proc = ui_with_proc()
    ui.show()
    ui.stop()
    assert proc.terminated is True
    assert ui.alive is False


def test_stop_does_not_spawn() -> None:
    ui, spawned = counting_ui()
    ui.stop()
    assert spawned == []


# --- the real pipe: a Python script as the child ---

FAKE_UI = textwrap.dedent(
    """
    import json, os, sys
    # Behaviour comes from the environment so one script covers every test.
    out = os.environ.get("FAKE_OUT", "")
    log = open(os.environ["FAKE_LOG"], "a")
    sys.stdout.buffer.write(out.encode().decode("unicode_escape").encode())
    sys.stdout.flush()
    rc = int(os.environ.get("FAKE_RC_AFTER_OUT", "-1"))
    if rc >= 0:
        sys.exit(rc)
    for line in sys.stdin:
        log.write(line); log.flush()
        if json.loads(line).get("type") == "quit":
            sys.exit(0)
    """
)


@pytest.fixture
def fake_ui(tmp_path: Path) -> Iterator[Callable[..., tuple[UiProcess, Path]]]:
    script = tmp_path / "fake_ui.py"
    script.write_text(FAKE_UI)
    made: list[UiProcess] = []

    def make(out: str = "", rc_after_out: int = -1, on_event: Any = None) -> tuple[UiProcess, Path]:
        log_path = tmp_path / f"log{len(made)}.jsonl"
        env = {
            "FAKE_OUT": out,
            "FAKE_LOG": str(log_path),
            "FAKE_RC_AFTER_OUT": str(rc_after_out),
            "PATH": "/usr/bin:/bin",
        }

        def spawn(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            return subprocess.Popen([sys.executable, str(script)], env=env, **kwargs)

        ui = UiProcess(Ui(), 300, binary=BINARY, spawn=spawn, on_event=on_event)
        made.append(ui)
        return ui, log_path

    yield make
    for ui in made:
        ui.stop()


def wait_for(cond: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_a_click_reaches_on_event(fake_ui: Callable[..., tuple[UiProcess, Path]]) -> None:
    got: list[dict[str, Any]] = []
    seen = threading.Event()

    def on_event(event: dict[str, Any]) -> None:
        got.append(event)
        if event.get("event") == "moved":
            seen.set()

    out = r'{"event":"click"}\n{"event":"moved","x":0.42,"output":"eDP-1"}\n'
    ui, _ = fake_ui(out=out, on_event=on_event)
    ui.start()
    assert seen.wait(2)
    assert got == [{"event": "click"}, {"event": "moved", "x": 0.42, "output": "eDP-1"}]


def test_bad_json_from_the_child_is_ignored(
    fake_ui: Callable[..., tuple[UiProcess, Path]],
) -> None:
    got: list[dict[str, Any]] = []
    seen = threading.Event()

    def on_event(event: dict[str, Any]) -> None:
        got.append(event)
        seen.set()

    long_line = "y" * (ui_ipc.MAX_EVENT_BYTES + 10)
    out = "not json\\n[1,2]\\n" + long_line + '\\n{"event":"click"}\\n'
    ui, _ = fake_ui(out=out, on_event=on_event)
    ui.start()
    assert seen.wait(2)
    assert got == [{"event": "click"}]


def test_an_event_handler_that_raises_is_logged_not_propagated(
    fake_ui: Callable[..., tuple[UiProcess, Path]], caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []

    def on_event(event: dict[str, Any]) -> None:
        calls.append(1)
        raise RuntimeError("boom")

    ui, _ = fake_ui(out=r'{"event":"click"}\n{"event":"click"}\n', on_event=on_event)
    with caplog.at_level(logging.ERROR, logger="flowd.ui_ipc"):
        ui.start()
        assert wait_for(lambda: len(calls) == 2)
    assert any("handler failed" in r.message for r in caplog.records)


def test_unsupported_event_and_exit_3_stop_all_further_spawns(
    fake_ui: Callable[..., tuple[UiProcess, Path]],
) -> None:
    events: list[dict[str, Any]] = []
    out = r'{"event":"unsupported","reason":"GNOME Wayland"}\n'
    ui, _ = fake_ui(out=out, rc_after_out=3, on_event=events.append)
    ui.start()
    first = ui._proc
    assert first is not None
    assert wait_for(lambda: ui.unsupported)
    first.wait(timeout=2)
    ui.show()
    ui.render(polished="", pending="", live="x")
    ui.start()
    assert ui.alive is False
    assert ui._proc is None
    assert events == []  # handled inside, not forwarded


def test_messages_reach_a_real_child_in_order(
    fake_ui: Callable[..., tuple[UiProcess, Path]],
) -> None:
    ui, log_path = fake_ui()
    ui.show()
    ui.meta("code", "kitty", "Super D")
    ui.level(-30.0, -12.0)
    ui.end("done", fade=True)
    ui.stop()
    received = [json.loads(line)["type"] for line in log_path.read_text().splitlines()]
    assert received == ["config", "show", "meta", "level", "state", "fade", "quit"]


def test_a_child_that_exits_is_seen_as_dead(
    fake_ui: Callable[..., tuple[UiProcess, Path]],
) -> None:
    ui, _ = fake_ui(rc_after_out=1)
    ui.start()
    proc = ui._proc
    assert proc is not None
    proc.wait(timeout=2)
    ui.render(polished="", pending="", live="x")  # must not raise
    assert ui._failures >= 1
