"""Tests for overlay child-process management (spec 4, 9.5).

The overlay is optional, so the property under test throughout is that nothing
here raises into the dictation path: a missing interpreter, a crashed child, a
closed pipe and a child that dies on every spawn all have to end with the daemon
still dictating. `FakeProc` stands in for `subprocess.Popen` so the suite needs
no compositor and no system interpreter (CONTRIBUTING.md).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from flowd.config import Overlay as OverlayCfg
from flowd.overlay_ipc import OverlayProcess


class FakeProc:
    """A `Popen` reduced to what `OverlayProcess` touches."""

    def __init__(self, alive: bool = True) -> None:
        self.written = b""
        self._alive = alive
        self.terminated = False
        self.waited = False
        self.stdin = self

    # --- stdin duck-typing ---
    def write(self, data: bytes) -> int:
        if not self._alive:
            raise BrokenPipeError("child is gone")
        self.written += data
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    # --- process duck-typing ---
    def poll(self) -> int | None:
        return None if self._alive else 1

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        """Honest about still running: a `wait` that always succeeds would hide
        whether `stop` gave the child a chance to exit before killing it."""
        self.waited = True
        if self._alive:
            raise subprocess.TimeoutExpired("overlay", timeout or 0)
        return 0


def overlay(proc: FakeProc, cfg: OverlayCfg | None = None) -> OverlayProcess:
    return OverlayProcess(cfg or OverlayCfg(), spawn=lambda *_a, **_k: proc)


def counting_overlay(
    procs: list[FakeProc], cfg: OverlayCfg | None = None
) -> tuple[OverlayProcess, list[int]]:
    """An overlay that hands out `procs` in order, and a count of its spawns."""
    remaining = iter(procs)
    spawns: list[int] = []

    def spawn(*_a: Any, **_k: Any) -> FakeProc:
        spawns.append(1)
        return next(remaining)

    return OverlayProcess(cfg or OverlayCfg(), spawn=spawn), spawns


def spawn_argv(proc: FakeProc, cfg: OverlayCfg | None = None) -> list[str]:
    """The argv `OverlayProcess` would spawn the child with."""
    captured: list[list[str]] = []

    def spawn(argv: list[str], **_k: Any) -> FakeProc:
        captured.append(list(argv))
        return proc

    OverlayProcess(cfg or OverlayCfg(), spawn=spawn).show()
    return captured[0]


def messages(proc: FakeProc) -> list[dict[str, Any]]:
    return [json.loads(line) for line in proc.written.decode().splitlines() if line]


def test_show_spawns_and_sends_show() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    assert messages(proc) == [{"type": "show"}]


def test_overlay_config_reaches_the_child() -> None:
    """`max_lines` and `fade_ms` must cross the process boundary.

    Both are documented in spec 8's config file and validated by `flowd.config`,
    but the child kept its own hardcoded copies, so a user who set either was
    told nothing and got the default — the same silent kind of failure as a
    reload that reports success and changes nothing.

    They travel on argv rather than in the protocol because the child needs them
    before the first message can arrive: `max_lines` is applied while the labels
    are built, which happens before GTK opens a window.
    """
    argv = spawn_argv(FakeProc(), OverlayCfg(max_lines=7, fade_ms=250))
    assert "--max-lines" in argv, f"max_lines never reached the child: {argv}"
    assert argv[argv.index("--max-lines") + 1] == "7"
    assert "--fade-ms" in argv, f"fade_ms never reached the child: {argv}"
    assert argv[argv.index("--fade-ms") + 1] == "250"


def test_nothing_is_spawned_until_the_first_message() -> None:
    """`main` constructs this at daemon start, before any session exists."""
    procs: list[FakeProc] = [FakeProc()]
    o, spawns = counting_overlay(procs)
    assert spawns == []
    assert o.alive is False
    o.show()
    assert spawns == [1]


def test_render_sends_three_zones() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.render(polished="done", pending="soon", live="now")
    assert messages(proc)[-1] == {
        "type": "render",
        "polished": "done",
        "pending": "soon",
        "live": "now",
    }


def test_every_message_is_one_line_of_json() -> None:
    """The child reads line-delimited JSON, so an embedded newline would split
    one message into two unparseable halves."""
    proc = FakeProc()
    o = overlay(proc)
    o.render(polished="", pending="two\nlines", live="tab\there")
    assert proc.written.count(b"\n") == 1
    assert proc.written.endswith(b"\n")
    assert messages(proc)[-1]["pending"] == "two\nlines"


def test_disabled_overlay_never_spawns() -> None:
    """spec 8's `overlay.enabled = false` must cost nothing at all."""
    procs = [FakeProc()]
    o, spawns = counting_overlay(procs, OverlayCfg(enabled=False))
    o.show()
    o.render(live="x")
    o.fade()
    o.stop()
    assert spawns == []
    assert procs[0].written == b""
    assert o.alive is False


def test_dead_child_is_respawned_on_next_show() -> None:
    """spec 9.5: an overlay crash must not end the session; respawn next time."""
    dead, alive = FakeProc(alive=False), FakeProc()
    o, spawns = counting_overlay([dead, alive])
    o.show()  # spawns `dead`; the write fails
    o.show()  # notices it died and spawns `alive`
    assert len(spawns) == 2
    assert messages(alive) == [{"type": "show"}]


def test_broken_pipe_is_swallowed() -> None:
    """A failing overlay must never raise into the dictation path."""
    o = overlay(FakeProc(alive=False))
    o.show()
    o.render(live="still fine")  # must not raise


def test_spawn_failure_is_swallowed() -> None:
    def spawn(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("/usr/bin/python3")

    o = OverlayProcess(OverlayCfg(), spawn=spawn)
    o.show()
    o.render(live="x")
    assert o.alive is False


def test_a_child_that_dies_every_time_is_given_up_on() -> None:
    """A crash loop must not spawn a process per audio block.

    `render` is called on every STT event — ten times a second — so an overlay
    that dies instantly would otherwise have the daemon forking continuously,
    competing for the cores STT needs. Spec 9.5 makes the overlay optional; the
    honest response to one that cannot start is to stop trying.
    """
    o, spawns = counting_overlay([FakeProc(alive=False) for _ in range(50)])
    for _ in range(40):
        o.render(live="speaking")
    assert len(spawns) < 10, f"kept respawning a dying overlay: {len(spawns)} attempts"


def test_giving_up_is_reset_by_a_new_session() -> None:
    """`show` starts a session, which is the moment to try again.

    The user may have fixed whatever was wrong — installed the package, moved to
    a compositor with layer-shell — and a daemon that runs for weeks should not
    stay permanently overlay-less because of one bad minute.
    """
    healthy = FakeProc()
    fixed = False
    spawns: list[int] = []

    def spawn(*_a: Any, **_k: Any) -> FakeProc:
        spawns.append(1)
        return healthy if fixed else FakeProc(alive=False)

    o = OverlayProcess(OverlayCfg(), spawn=spawn)
    for _ in range(40):
        o.render(live="speaking")
    given_up = len(spawns)
    assert given_up < 40

    for _ in range(20):  # still given up: renders alone do not retry
        o.render(live="speaking")
    assert len(spawns) == given_up

    fixed = True
    o.show()  # a new session is a fresh chance
    assert len(spawns) == given_up + 1
    assert messages(healthy) == [{"type": "show"}]


def test_a_child_that_obeys_quit_is_not_killed() -> None:
    """`quit` is in the protocol and the overlay implements it, so `stop` has to
    let it run.

    Sending `quit` and signalling in the same breath makes the message dead
    weight: the child is on SIGTERM before it has read a byte, which shows up as
    a daemon that appears to kill its overlay on every exit. GTK also gets to
    drop its layer surface itself rather than be cut off mid-frame.
    """

    class Obedient(FakeProc):
        def write(self, data: bytes) -> int:
            written = super().write(data)
            if b'"quit"' in data:
                self._alive = False  # exits of its own accord, as the real one does
            return written

    proc = Obedient()
    o = overlay(proc)
    o.show()
    o.stop()
    assert {"type": "quit"} in messages(proc)
    assert proc.waited is True, "did not wait for the child to exit"
    assert proc.terminated is False, "killed a child that had already quit"
    assert o.alive is False


def test_stop_terminates_child() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.stop()
    assert {"type": "quit"} in messages(proc)
    assert proc.terminated is True
    assert o.alive is False


def test_stop_does_not_spawn_a_child_just_to_kill_it() -> None:
    """Nothing is running, so there is nothing to tell to quit."""
    procs = [FakeProc()]
    o, spawns = counting_overlay(procs)
    o.stop()
    assert spawns == []
    assert procs[0].written == b""


def test_stop_after_a_crash_does_not_respawn() -> None:
    """The child already died; `stop` is cleanup, not a reason to start one."""
    dead, spare = FakeProc(alive=False), FakeProc()
    o, spawns = counting_overlay([dead, spare])
    o.show()  # spawns `dead`
    o.stop()
    assert len(spawns) == 1
    assert spare.written == b""


def test_stop_is_idempotent() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.stop()
    o.stop()  # must not raise


def test_stop_survives_a_child_that_will_not_die() -> None:
    """`terminate` and `wait` both failing must not stop the daemon exiting."""

    class Stubborn(FakeProc):
        def terminate(self) -> None:
            raise OSError("no such process")

        def wait(self, timeout: float | None = None) -> int:
            raise TimeoutError("still running")

    o = overlay(Stubborn())
    o.show()
    o.stop()  # must not raise
    assert o.alive is False


def test_hide_and_fade_are_sent() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.hide()
    o.fade()
    assert [m["type"] for m in messages(proc)] == ["show", "hide", "fade"]
