"""`flowd-ui` child-process management (ADR 0013).

`flowd-ui` draws the indicator and the preview popup. It is a separate process
so that a crash in it never costs a dictation (ADR 0003), which makes this
file's job error suppression: every failure is logged and swallowed, and the
worst a broken UI can do is leave the user without an indicator.

The protocol is newline-delimited JSON in both directions. Daemon → UI on the
child's stdin, UI → daemon (`click`, `moved`, `unsupported`) on its stdout,
read here on a thread of its own. Writes never block the caller: the daemon
calls these methods from its event loop, and a UI that stops reading must not
stall the microphone. Our end of stdin is non-blocking, and whatever the pipe
will not take waits in a small backlog drained by a helper thread.

Exit codes (ADR 0013): 0 is a normal end, 1 a crash or init failure (respawned
up to `MAX_SPAWN_FAILURES`), 3 "unsupported here" (never respawned until the
config is reloaded).
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flowd.config import Ui, ui_fields

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where `make ui` builds the binary. `FLOWD_UI` overrides it, for packagers.
DEFAULT_BINARY = REPO_ROOT / "build" / "ui" / "flowd-ui"
BINARY_ENV = "FLOWD_UI"

#: Consecutive crashes before we stop trying until the next session. `render`
#: runs on every STT event, so a UI that cannot start would otherwise have the
#: daemon forking ten times a second, competing for the cores STT needs.
MAX_SPAWN_FAILURES = 3

#: A child that died is not respawned sooner than this, except by `show`: a
#: new dictation is the user asking for the UI, and worth one immediate try.
RESPAWN_BACKOFF_S = 5.0

#: How long `stop` waits for the child to act on `quit` before signalling it.
QUIT_GRACE_S = 1.0

#: Exit codes from ADR 0013.
EXIT_OK = 0
EXIT_UNSUPPORTED = 3
#: A SIGTERM is a normal end too (ADR 0013): 143 when it lands before
#: flowd-ui installs its handler, `-SIGTERM` as `Popen` reports a death by it.
_NORMAL_EXITS = frozenset({EXIT_OK, 128 + signal.SIGTERM, -signal.SIGTERM})

#: Bytes waiting for the pipe beyond which the UI is taken to be hung. The pipe
#: itself holds 64 KiB, so this is minutes of renders a live UI never leaves
#: unread; one that does is killed and counted as a crash.
MAX_BACKLOG_BYTES = 256 * 1024

#: Longest event line accepted from the child. Real events are under 100
#: bytes; anything longer is discarded up to its newline.
MAX_EVENT_BYTES = 16 * 1024

#: How often the drain thread retries a full pipe.
DRAIN_INTERVAL_S = 0.01

#: `level` values below this are sent as it. Silence reads as -inf dBFS, and
#: `json.dumps` would write that as `-Infinity`, which is not JSON: flowd-ui
#: would drop the line.
LEVEL_FLOOR_DB = -120.0

#: The state names flowd-ui accepts (ADR 0013); anything else it discards.
STATES = frozenset(
    {
        "idle",
        "recording",
        "finishing",
        "done",
        "fallback",
        "error",
        "cancelled",
        "nospeech",
        "timelimit",
    }
)

#: States worth replaying to a respawned UI, so a crash mid-dictation does not
#: leave the indicator reading idle. Terminal states have already been acted on.
_LIVE_STATES = frozenset({"recording", "finishing", "timelimit"})

EventHandler = Callable[[dict[str, Any]], None]


def find_binary() -> Path:
    """`FLOWD_UI`, else the dev build, else `flowd-ui` on `PATH`.

    Falls back to the dev build path when nothing is found, so the "not found"
    log line names the place `make ui` would put it.
    """
    override = os.environ.get(BINARY_ENV)
    if override:
        return Path(override)
    if DEFAULT_BINARY.exists():
        return DEFAULT_BINARY
    on_path = shutil.which("flowd-ui")
    return Path(on_path) if on_path else DEFAULT_BINARY


@dataclass(slots=True)
class _Queued:
    kind: str  # the message's `type`, for the drop policy
    data: bytes


class UiProcess:
    """The daemon's half of the flowd-ui protocol (ADR 0013).

    Nothing is spawned at construction. `start` spawns the indicator at idle
    when `[ui] indicator` is on; otherwise the first `show` does.
    """

    def __init__(
        self,
        cfg: Ui,
        max_session_s: int,
        *,
        binary: Path | None = None,
        spawn: Callable[..., Any] = subprocess.Popen,
        on_event: EventHandler | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = cfg
        self._max_session_s = max_session_s
        self._binary = binary
        self._spawn = spawn
        self._clock = clock
        #: Called on the reader thread with each event dict other than
        #: `unsupported`. Settable after construction.
        self.on_event = on_event
        self._proc: Any = None
        self._failures = 0
        self._died_at: float | None = None
        self._unsupported = False
        self._missing_logged = False
        self._warn: tuple[str | None, bool] | None = None
        self._state: tuple[str, str] | None = None
        # One lock for the process handle and the write backlog: the drain
        # thread and the daemon both write, and must never interleave bytes.
        self._lock = threading.RLock()
        self._backlog: deque[_Queued] = deque()
        self._backlog_bytes = 0
        self._head_sent = 0  # bytes of `_backlog[0]` already in the pipe
        self._drainer: threading.Thread | None = None
        self._reader: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def unsupported(self) -> bool:
        """True after the UI said it cannot run here, until `configure`."""
        return self._unsupported

    # --- lifecycle ---

    def start(self) -> None:
        """Spawn the indicator now, so it is visible at idle.

        Idempotent and cheap when the UI is already up or cannot be spawned
        yet, so it is safe to call from a periodic loop to bring back a UI that
        died at idle once the backoff has passed.
        """
        if self._cfg.indicator:
            with self._lock:
                self._ensure()

    def configure(self, cfg: Ui, max_session_s: int) -> None:
        """Apply a reloaded config. A reload is also the one thing that lets a
        UI that reported `unsupported` be tried again (ADR 0013)."""
        with self._lock:
            # Account for a child that already exited before clearing the
            # flags, or an unreaped exit 3 would set `unsupported` again on
            # the next `_ensure` and the reload would change nothing.
            if self._proc is not None:
                rc = self._proc.poll()
                if rc is not None:
                    self._reap(self._proc, rc)
            self._cfg = cfg
            self._max_session_s = max_session_s
            self._unsupported = False
            self._failures = 0
            self._died_at = None
            self._missing_logged = False
        if not cfg.enabled:
            self.stop()
            return
        with self._lock:
            if self.alive:
                self._enqueue(self._config_message())
                return
        self.start()

    def stop(self) -> None:
        """Shut the child down. Never starts one.

        Blocking: it waits up to about 4 s for the child to exit (the quit
        grace, then SIGTERM, then SIGKILL). Do not call it on the event loop
        except at shutdown; anywhere else, run it in an executor.
        """
        with self._lock:
            proc, self._proc = self._proc, None
            if proc is not None:
                # Whatever is still queued is for a UI that is about to go.
                self._clear_backlog()
                self._write_now(proc, _encode({"type": "quit"}))
                self._close_stdin(proc)
        if proc is None:
            return
        try:
            # Let it act on `quit`: GTK drops its surfaces itself rather than
            # being cut off mid-frame.
            proc.wait(timeout=QUIT_GRACE_S)
            log.debug("flowd-ui exited on request")
        except Exception as exc:
            log.debug("flowd-ui ignored quit (%s); terminating", exc)
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception as exc2:  # a child that will not die must not block exit
                log.debug("flowd-ui did not exit cleanly: %s", exc2)
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception as exc3:
                    log.warning("could not kill flowd-ui: %s", exc3)
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)

    # --- daemon → UI messages ---

    def show(self) -> None:
        """Start a session's preview.

        Also the moment to forgive crashes: the user may have fixed whatever
        was wrong, and a daemon that runs for weeks should not stay UI-less
        because of one bad minute. `unsupported` is not forgiven here; that
        takes a config reload.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is not None:
                self._reap(self._proc, self._proc.poll())
            self._failures = 0
            # A new session: the last one's state is not worth replaying, and
            # replaying it would send a second `show` ahead of this one.
            self._state = None
            if self._ensure(immediate=True):
                self._enqueue({"type": "show"})

    def render(self, **zones: str) -> None:
        with self._lock:
            self._send({"type": "render", **zones})

    def fade(self) -> None:
        self._send_if_alive({"type": "fade"})

    def hide(self) -> None:
        self._send_if_alive({"type": "hide"})

    def state(self, state: str, reason: str = "") -> None:
        if state not in STATES:
            log.warning("not sending unknown ui state %r", state)
            return
        with self._lock:
            self._state = (state, reason)
            self._send_if_alive({"type": "state", "state": state, "reason": reason})

    def end(self, state: str, reason: str = "", *, fade: bool) -> None:
        """Send a session's terminal state, then fade or hide.

        The order is the protocol: the popup holds an outcome only if it has
        the state before the fade or hide arrives, so sending them the other
        way round cuts "Cancelled" and friends short.
        """
        with self._lock:
            self.state(state, reason)
            if fade:
                self.fade()
            else:
                self.hide()

    def level(self, rms_db: float, peak_db: float) -> None:
        """20 Hz while recording. Never spawns, and is the first message
        dropped when the UI falls behind."""
        self._send_if_alive(
            {"type": "level", "rms_db": _finite_db(rms_db), "peak_db": _finite_db(peak_db)}
        )

    def meta(self, mode: str, app: str, hotkey: str) -> None:
        with self._lock:
            self._send({"type": "meta", "mode": mode, "app": app, "hotkey": hotkey})

    def warn(self, reason: str | None, *, blocking: bool = False) -> None:
        """Show a warning on the indicator, or clear it with `None`. Kept and
        replayed to a respawned UI."""
        with self._lock:
            # An empty reason clears, and is sent as null so it reads that way.
            reason = reason or None
            self._warn = (reason, blocking) if reason else None
            self._send({"type": "warn", "reason": reason, "blocking": blocking})

    # --- spawning ---

    def _ensure(self, *, immediate: bool = False) -> bool:
        """Whether there is a live child to write to, spawning one if allowed.
        `immediate` skips the respawn backoff. Caller holds the lock."""
        if not self._cfg.enabled or self._unsupported:
            return False
        if self._proc is not None:
            rc = self._proc.poll()
            if rc is None:
                return True
            self._reap(self._proc, rc)
        if self._failures >= MAX_SPAWN_FAILURES:
            return False
        backing_off = (
            self._died_at is not None and self._clock() - self._died_at < RESPAWN_BACKOFF_S
        )
        if backing_off and not immediate:
            return False
        binary = self._binary or find_binary()
        if not binary.exists():
            if not self._missing_logged:
                log.warning(
                    "flowd-ui not found at %s (run `make ui`); continuing without it", binary
                )
                self._missing_logged = True
            # Retried by the next `show`, not by every render.
            self._failures = MAX_SPAWN_FAILURES
            return False
        try:
            proc = self._spawn(
                [str(binary)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                bufsize=0,
            )
        except (OSError, ValueError) as exc:
            log.warning("could not start flowd-ui: %s", exc)
            self._failures += 1
            self._died_at = self._clock()
            return False
        self._proc = proc
        self._set_nonblocking(proc)
        self._start_reader(proc)
        log.debug("flowd-ui started")
        # A new UI knows nothing: settings first, then what it would have been
        # told had it been running all along.
        self._enqueue(self._config_message())
        if self._warn is not None:
            reason, blocking = self._warn
            self._enqueue({"type": "warn", "reason": reason, "blocking": blocking})
        if self._state is not None and self._state[0] in _LIVE_STATES:
            # A dictation is in progress, so the popup was up: bring it back
            # before telling it the state.
            state, reason = self._state
            self._enqueue({"type": "show"})
            self._enqueue({"type": "state", "state": state, "reason": reason})
        return self._proc is proc

    def _reap(self, proc: Any, rc: int | None) -> None:
        """Account for a child found dead. Caller holds the lock."""
        if proc is self._proc:
            self._proc = None
            self._clear_backlog()
        self._close_stdin(proc)
        self._died_at = self._clock()
        if rc is None:
            # Still running with a broken pipe: stdin is closed now, so it
            # sees EOF and exits; reap it off the caller's thread.
            threading.Thread(target=_wait_quietly, args=(proc,), daemon=True).start()
        if rc == EXIT_UNSUPPORTED:
            if not self._unsupported:
                log.warning("flowd-ui is unsupported here; not restarting it until reload")
            self._unsupported = True
        elif rc in _NORMAL_EXITS:
            log.info("flowd-ui exited (%s)", rc)
        else:
            self._failures += 1
            log.warning("flowd-ui died (exit %s, %d/%d)", rc, self._failures, MAX_SPAWN_FAILURES)

    def _config_message(self) -> dict[str, Any]:
        return {"type": "config", "ui": ui_fields(self._cfg, self._max_session_s)}

    @staticmethod
    def _set_nonblocking(proc: Any) -> None:
        """Our end of stdin only; flowd-ui sets its own ends (ADR 0013). Fakes
        without a real descriptor are written as they are."""
        with contextlib.suppress(AttributeError, OSError, ValueError):
            os.set_blocking(proc.stdin.fileno(), False)

    @staticmethod
    def _close_stdin(proc: Any) -> None:
        with contextlib.suppress(AttributeError, OSError, ValueError):
            proc.stdin.close()

    # --- writing ---

    def _send(self, message: dict[str, Any]) -> None:
        with self._lock:
            if self._ensure():
                self._enqueue(message)

    def _send_if_alive(self, message: dict[str, Any]) -> None:
        with self._lock:
            if self._unsupported or not self.alive:
                return
            self._enqueue(message)

    def _enqueue(self, message: dict[str, Any]) -> None:
        """Queue one message, apply the drop policy, write what the pipe takes.
        Caller holds the lock."""
        kind = str(message["type"])
        if self._backlog:
            # Behind already: a meter frame is stale by the time it would land.
            if kind == "level":
                return
            # A render replaces a queued render right before it: only the
            # latest text matters. Only the tail, so order is never changed.
            tail_idx = len(self._backlog) - 1
            tail = self._backlog[tail_idx]
            if (
                kind == "render"
                and tail.kind == "render"
                and not (tail_idx == 0 and self._head_sent)
            ):
                self._backlog.pop()
                self._backlog_bytes -= len(tail.data)
        data = _encode(message)
        self._backlog.append(_Queued(kind, data))
        self._backlog_bytes += len(data)
        if self._backlog_bytes > MAX_BACKLOG_BYTES:
            self._give_up_on_hung_child()
            return
        self._drain()
        if self._backlog:
            self._start_drainer()

    def _drain(self) -> None:
        """Write queued bytes until the pipe is full or the queue is empty.
        Caller holds the lock."""
        proc = self._proc
        while self._backlog and proc is not None:
            head = self._backlog[0]
            chunk = head.data[self._head_sent :]
            try:
                written = proc.stdin.write(chunk)
            except BlockingIOError as exc:
                # A buffered writer reports a full pipe this way, having kept
                # what it could.
                written = exc.characters_written
            except (BrokenPipeError, OSError, AttributeError, ValueError) as exc:
                log.warning("flowd-ui stopped reading (%s); continuing without it", exc)
                self._reap(proc, proc.poll())
                return
            if written is None or written == 0:  # EAGAIN: the pipe is full
                return
            self._head_sent += written
            if self._head_sent >= len(head.data):
                self._backlog.popleft()
                self._backlog_bytes -= len(head.data)
                self._head_sent = 0

    def _write_now(self, proc: Any, data: bytes) -> None:
        """Best effort, for `quit`: no queue, since nothing will drain it."""
        try:
            proc.stdin.write(data)
        except (BrokenPipeError, OSError, AttributeError, ValueError) as exc:
            log.debug("could not send quit to flowd-ui: %s", exc)

    def _clear_backlog(self) -> None:
        self._backlog.clear()
        self._backlog_bytes = 0
        self._head_sent = 0

    def _give_up_on_hung_child(self) -> None:
        proc = self._proc
        log.warning("flowd-ui is not reading its input; restarting it")
        self._clear_backlog()
        if proc is None:
            return
        try:
            proc.kill()
        except (OSError, AttributeError) as exc:
            log.debug("could not kill flowd-ui: %s", exc)
        # Counted as a crash whatever it exits with.
        self._proc = None
        self._close_stdin(proc)
        self._failures += 1
        self._died_at = self._clock()
        threading.Thread(target=_wait_quietly, args=(proc,), daemon=True).start()

    def _start_drainer(self) -> None:
        if self._drainer is not None and self._drainer.is_alive():
            return
        self._drainer = threading.Thread(
            target=self._drain_loop, name="flowd-ui-writer", daemon=True
        )
        self._drainer.start()

    def _drain_loop(self) -> None:
        """Runs only while there is a backlog, retrying the full pipe."""
        while True:
            time.sleep(DRAIN_INTERVAL_S)
            with self._lock:
                self._drain()
                if not self._backlog or self._proc is None:
                    return

    # --- reading ---

    def _start_reader(self, proc: Any) -> None:
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        self._reader = threading.Thread(
            target=self._read_events, args=(proc, stdout), name="flowd-ui-events", daemon=True
        )
        self._reader.start()

    def _read_events(self, proc: Any, stdout: Any) -> None:
        """One JSON object per line until EOF. Never raises."""
        try:
            self._read_lines(proc, stdout)
        finally:
            with contextlib.suppress(OSError, ValueError):
                stdout.close()

    def _read_lines(self, proc: Any, stdout: Any) -> None:
        buf = b""
        discarding = False
        while True:
            try:
                chunk = stdout.read(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            buf += chunk
            while True:
                end = buf.find(b"\n")
                if end < 0:
                    if len(buf) > MAX_EVENT_BYTES:
                        buf, discarding = b"", True
                    break
                line, buf = buf[:end], buf[end + 1 :]
                if discarding:
                    discarding = False
                    continue
                if len(line) <= MAX_EVENT_BYTES:
                    self._handle_line(proc, line)

    def _handle_line(self, proc: Any, line: bytes) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            log.debug("ignoring a line from flowd-ui that is not JSON")
            return
        if not isinstance(event, dict):
            return
        if event.get("event") == "unsupported":
            # Handled here so the flag is set before the exit is seen, and the
            # UI's own reason reaches the log.
            with self._lock:
                self._unsupported = True
            log.warning(
                "flowd-ui cannot run here: %s; not restarting it until reload",
                event.get("reason", "no reason given"),
            )
            return
        handler = self.on_event
        if handler is None:
            return
        try:
            handler(event)
        except Exception:
            log.exception("flowd-ui event handler failed")


def _encode(message: dict[str, Any]) -> bytes:
    """One line of JSON. `json.dumps` escapes newlines inside values, so a
    multi-line preview stays a single message."""
    return json.dumps(message).encode("utf-8") + b"\n"


def _finite_db(value: float) -> float:
    if not math.isfinite(value):
        return LEVEL_FLOOR_DB
    return max(float(value), LEVEL_FLOOR_DB)


def _wait_quietly(proc: Any) -> None:
    """Reap a killed child so it does not linger as a zombie."""
    try:
        proc.wait(timeout=5)
    except Exception as exc:
        log.debug("flowd-ui did not exit after kill: %s", exc)
