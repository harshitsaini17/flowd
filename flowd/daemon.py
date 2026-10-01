"""The daemon: state machine driver and command handler (spec 4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import stat
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from flowd import guardrails
from flowd.audio import MicrophoneStuck
from flowd.cleanup import CleanupClient, CleanupResult
from flowd.config import Config, Ui, config_path, reload_config, runtime_dir, state_dir
from flowd.context import AppContext, focused_app_id
from flowd.inject import inject_text as real_inject
from flowd.inject.base import InjectResult
from flowd.joiner import stitch
from flowd.levels import FLOOR_DB, LevelWindows
from flowd.metrics import SessionMetrics, read_records, summarise, write_record
from flowd.modes import Style, finish, style_for
from flowd.recordings import SessionRecorder
from flowd.scheduler import Scheduler
from flowd.session import Chunk, Session
from flowd.settings_api import Busy, SettingsApi, Unavailable
from flowd.settings_server import SettingsServer, Tokens
from flowd.state import Action, Event, Machine, State
from flowd.stt import Committed, Partial, SttEngine
from flowd.suspend import SleepDetector
from flowd.textclean import apply_replacements, basic_clean, minimal_clean
from flowd.vocab import Vocab, load_vocab, vocab_path

log = logging.getLogger(__name__)

Injector = Callable[..., InjectResult]

#: spec 6.6: the full-rewrite pass takes the whole joined text, ≤ 300 words.
REWRITE_MAX_WORDS = 300
#: The microphone test reads the capture this often, the meter's 20 Hz.
MIC_TEST_POLL_S = 0.05
#: Empty reads in a row after which the microphone test reports silence, so the
#: settings server, which notices a closed page only when it writes, still
#: writes while the device delivers nothing. Two polls: blocks of up to 100 ms
#: arrive at least that often from a working device.
MIC_TEST_SILENT_POLLS = 2
#: How long the settings page's "Detect" waits before reading the focused
#: window, so the user has time to click into the app they mean.
DETECT_DELAY_S = 3.0
#: How long a daemon restart waits before asking systemd, so the reply to the
#: page is written before systemd stops this process.
RESTART_DELAY_S = 0.3
#: Where the settings page's tokens wait across a daemon restart. The new
#: daemon adopts the file at startup and deletes it.
SETTINGS_TOKENS_FILE = "settings-tokens.json"
#: How old that file may be and still be adopted. A restart from the page takes
#: a few seconds; anything older was left by a restart that never came back.
SETTINGS_TOKENS_MAX_AGE_S = 60.0
#: `flowctl settings`' reply when the page is configured off.
SETTINGS_OFF = "the settings page is turned off ([settings] enabled = false)"
#: Its reply before `run` has tried to start the settings server.
SETTINGS_NOT_STARTED = "the settings page is not running yet"
RESTART_TARGETS = ("ui", "daemon")


def indicator_position_file() -> Path | None:
    """flowd-ui's saved indicator position, or None when it has nowhere to
    keep one. Mirrors `default_position_file` in ui/src/position_store.cpp,
    which differs from `state_dir`: a relative $XDG_STATE_HOME is ignored
    (XDG spec) and there is no fallback when $HOME is unset."""
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and Path(xdg).is_absolute():
        base = Path(xdg)
    else:
        home = os.environ.get("HOME")
        if not home:
            return None
        base = Path(home) / ".local/state"
    return base / "flowd" / "indicator.json"


class Capture(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read(self) -> np.ndarray: ...
    def pending_seconds(self) -> float: ...


class OverlayLike(Protocol):
    """What the daemon tells flowd-ui (ADR 0013); `UiProcess` in production."""

    def start(self) -> None: ...
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def fade(self) -> None: ...
    def render(self, **zones: str) -> None: ...
    def state(self, state: str, reason: str = "") -> None: ...
    def end(self, state: str, reason: str = "", *, fade: bool) -> None: ...
    def level(self, rms_db: float, peak_db: float) -> None: ...
    def meta(self, mode: str, app: str, hotkey: str) -> None: ...
    def warn(self, reason: str | None, *, blocking: bool = False) -> None: ...
    def configure(self, cfg: Ui, max_session_s: int) -> None: ...
    def stop(self) -> None: ...


#: The indicator's warnings (design.md "Warning"). One slot on the UI side, so
#: the daemon picks which one shows: the microphone first, since it blocks
#: dictation, where a down LLM only degrades it.
WARN_MIC_UNAVAILABLE = "Microphone unavailable"
WARN_CLEANUP_OFFLINE = "Cleanup offline, pasting as heard"

#: flowd-ui's fallback reasons (ui/src/popup_model.cpp `kOutcomes`), most
#: severe first. A session's chunks fall back one by one and can do so for
#: different reasons, but the popup has room for one: it reports the most
#: severe. A server problem outranks a problem with this text, since it will
#: hit the next dictation too, and a timeout outranks a guardrail rejection,
#: which is the model doing its job.
FALLBACK_SEVERITY = ("offline", "failed", "timeout", "rejected")

#: How a discarded session ends on flowd-ui, by `_discard`'s reason. A
#: suspend throws the words away just as a cancel does, so it reads the same.
_DISCARD_OUTCOMES: dict[str, tuple[str, str]] = {
    "cancelled": ("cancelled", ""),
    "suspended": ("cancelled", ""),
    "fatal error": ("error", "dictation_failed"),
}


def discard_outcome(reason: str) -> tuple[str, str]:
    """flowd-ui's `(state, reason)` for a session `_discard`ed with `reason`."""
    return _DISCARD_OUTCOMES.get(reason, ("cancelled", ""))


def _fallback_reason(result: CleanupResult) -> str:
    """flowd-ui's reason for one chunk that fell back after `result`.

    A result with text fell back because a guardrail rejected it; one without
    says why in `error` and `offline` (flowd/cleanup.py).
    """
    if result.text is not None:
        return "rejected"
    if result.offline:
        return "offline"
    if result.error == "timeout":
        return "timeout"
    # "too long", "error: no content", a server error: cleanup was reached
    # and did not help.
    return "failed"


def worst_fallback(reasons: list[str]) -> str | None:
    """The one reason to show for a session, by `FALLBACK_SEVERITY`."""
    for reason in FALLBACK_SEVERITY:
        if reason in reasons:
            return reason
    return "failed" if reasons else None


async def _no_llm(
    raw: str, *, chunk_id: int, context: str, merged: bool, timeout_ms: int
) -> str | None:
    """The polish for a mode that does not use the LLM: always its fallback."""
    return None


class Daemon:
    """Owns the session lifecycle.

    Every side effect goes through an injected collaborator, so the whole class
    is testable with fakes and no hardware.
    """

    def __init__(
        self,
        cfg: Config,
        stt: SttEngine,
        capture: Capture,
        overlay: OverlayLike | None = None,
        injector: Injector = real_inject,
        metrics_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        config_file: Path | None = None,
        write_metrics: bool = True,
        vocab: Vocab | None = None,
        vocab_file: Path | None = None,
        cleanup: CleanupClient | None = None,
        context: Callable[[Config], AppContext] | None = None,
    ) -> None:
        self.cfg = cfg
        self.stt = stt
        self.capture = capture
        self.overlay = overlay
        self.inject = injector
        self.clock = clock
        self.config_file = config_file or config_path()
        self.vocab_file = vocab_file or vocab_path()
        self.vocab = vocab or Vocab()
        self.metrics_path = metrics_path
        # None runs every session through `basic_clean` alone.
        self.cleanup = cleanup
        # Reads the focused app at session start (spec 5.6). None, as in tests
        # and `--replay`, means every session is `default` and not a terminal.
        self.context = context
        self.app = AppContext(None, "default", False)
        self.style: Style = style_for("default")
        # False for `--replay`: a probe run is not dictation, and written to the
        # log it would show up in `flowctl stats` as one.
        self.write_metrics = write_metrics
        self.machine = Machine(debounce_ms=cfg.hotkey.debounce_ms, clock=clock)
        self.session: Session | None = None
        self.metrics: SessionMetrics | None = None
        # Polishes the session's committed text chunk by chunk while the user
        # speaks (spec 6); one per session, made in `_begin`.
        self.scheduler: Scheduler | None = None
        self.last_text: str = ""
        self.last_record: dict[str, Any] = {}
        # The last session's STT text before cleanup, for the eval's raw WER
        # (spec 11.3). In memory only, never logged (spec 13.2).
        self.last_raw: str = ""
        # Moonshine runs off the loop (spec 4 gives STT its own worker), and
        # there is one stream per session, so the three calls that touch it —
        # `feed`, `finalize` and `reset` — must not overlap. Without this, a
        # `cancel` arriving mid-decode resets the stream underneath the worker
        # still reading it. Held only around those calls, so `status`, `last`
        # and `stats` continue to answer while the model runs.
        self._stt_lock = asyncio.Lock()
        # Fire-and-forget work (desktop notifications), held so it is not
        # garbage-collected mid-flight and so tests can wait for it.
        self._background: set[asyncio.Future[None]] = set()
        # spec 9.1: armed at each session start, checked on every pump.
        self.sleep = SleepDetector()
        # Opt-in audio capture for testing (`[logging] recordings_dir`).
        self.recorder: SessionRecorder | None = None
        # Set by `run`, so events from other threads (flowd-ui's reader) can
        # be handed to the loop the daemon lives on.
        self.loop: asyncio.AbstractEventLoop | None = None
        # The meter's windows for the current session (made in `_begin`).
        self.levels = LevelWindows(cfg.audio.sample_rate)
        # Why each of this session's chunks fell back, by `Chunk.id`. A chunk
        # merged away is no longer visible, so its reason no longer counts.
        self._fallback_reasons: dict[int, str] = {}
        # `_ui` call sites that have failed once, so a UI that keeps failing
        # logs one warning per site and then drops to debug.
        self._ui_failed: set[str] = set()
        # The two warning conditions `_sync_warning` chooses between, and
        # what it last sent, so a steady condition is not re-sent.
        self._mic_unavailable = False
        self._warning: tuple[str | None, bool] = (None, False)
        # The settings page's microphone test: whether one is running, and
        # whether a dictation took its stream (see `mic_test`).
        self._mic_testing = False
        self._mic_test_preempted = False
        # The settings server's tokens, handed to the next daemon across a
        # restart from the page. None while there is no settings server.
        self.settings_tokens: Tokens | None = None
        # The settings page's loopback server, made in `run`, and why there
        # is none when it is off or could not listen.
        self.settings_server: SettingsServer | None = None
        self._settings_error = SETTINGS_NOT_STARTED
        # When `_health_loop` last probed the LLM (monotonic), for the page.
        self._health_checked_at: float | None = None
        # Held while the settings page restarts flowd-ui: restarts run one at
        # a time, and the run loop's idle respawn waits until the old UI has
        # gone and its position file, if asked, with it.
        self._ui_restart_lock = asyncio.Lock()
        # Set once a daemon restart is scheduled, so a second request in the
        # delay does not queue another; cleared if systemctl fails.
        self._daemon_restart_pending = False

    # --- command handling -------------------------------------------------

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = str(request["cmd"])
        if cmd == "status":
            return {"ok": True, "state": str(self.machine.state)}
        if cmd == "last":
            return {"ok": True, "text": self.last_text}
        if cmd == "stats":
            return {"ok": True, "stats": summarise(read_records(self.metrics_file))}
        if cmd == "reload":
            error = await self.reload()
            return {"ok": True} if error is None else {"ok": False, "error": error}
        if cmd == "settings":
            return self._settings_url()

        event = {
            "start": Event.START,
            "stop": Event.STOP,
            "toggle": Event.TOGGLE,
            "cancel": Event.CANCEL,
        }.get(cmd)
        if event is None:
            return {"ok": False, "error": f"unsupported command: {cmd}"}

        action = self.machine.handle(event)
        if action is None:
            return {"ok": False, "error": f"ignored in state {self.machine.state}"}
        # `--rewrite` is a modifier on whichever command ends the session
        # (spec 6.6), so a toggle bound to a second hotkey works as well.
        return await self._perform(action, rewrite=bool(request.get("rewrite")))

    @property
    def metrics_file(self) -> Path:
        return self.metrics_path or (state_dir() / "metrics.jsonl")

    async def reload(self) -> str | None:
        """Re-read config and vocab and apply both; None, or the error text."""
        new_cfg, error = reload_config(self.cfg, self.config_file)
        if error is not None:
            return error
        # Both files are checked before either is applied, so a bad vocab
        # leaves the old config and the old vocabulary in place together.
        try:
            new_vocab = load_vocab(self.vocab_file)
        except ValueError as exc:
            return str(exc)
        await self.apply_vocab(new_vocab)
        if self.cleanup is not None and new_cfg.llm != self.cfg.llm:
            # The client holds its URL and timeouts from construction, so a
            # changed [llm] table needs a new one or the reload is a no-op.
            old, self.cleanup = self.cleanup, CleanupClient(new_cfg.llm)
            await old.aclose()
        self.cfg = new_cfg
        # The state machine holds its own copy of the window, taken at
        # construction, so assigning `self.cfg` alone would report success
        # and change nothing. Every other config value is read live through
        # `self.cfg`; this is the one that has to be pushed.
        self.machine.set_debounce_ms(new_cfg.hotkey.debounce_ms)
        # Off the loop: turning the UI off stops it, which waits for it.
        await asyncio.to_thread(self._configure_ui, new_cfg)
        return None

    def daemon_status(self) -> dict[str, Any]:
        """What the settings page's Status section shows about the daemon."""
        if not self.cfg.llm.enabled:
            cleanup = "disabled"
        elif self.cleanup is None or self.cleanup.down:
            cleanup = "offline"
        else:
            cleanup = "ready"
        checked = self._health_checked_at
        return {
            "state": str(self.machine.state),
            "stt_model": self.cfg.stt.model,
            "final_model": self.cfg.stt.final_model,
            "cleanup": cleanup,
            "health_checked_s_ago": (
                None if checked is None else round(time.monotonic() - checked, 1)
            ),
        }

    def _settings_url(self) -> dict[str, Any]:
        """`flowctl settings`: a fresh sign-in link, or why there is no page."""
        if self.settings_server is None or self.settings_tokens is None:
            return {"ok": False, "error": self._settings_error}
        token = self.settings_tokens.issue()
        return {"ok": True, "url": f"http://127.0.0.1:{self.settings_server.port}/#token={token}"}

    async def _start_settings(self) -> None:
        """Serve the settings page. Never fatal: dictation works without it."""
        if not self.cfg.settings.enabled:
            # No socket at all, and the saved tokens are left alone: a later
            # daemon with the page on rejects them as too old.
            self._settings_error = SETTINGS_OFF
            return
        adopted = self._take_settings_tokens()
        tokens = Tokens()
        if adopted:
            tokens.adopt(adopted)
        server = SettingsServer(self.cfg.settings.port, SettingsApi(self), tokens)
        reason = await server.start()
        if reason is not None:
            log.warning("settings page off: %s", reason)
            self._settings_error = reason
            return
        self.settings_tokens = tokens
        self.settings_server = server
        log.info("settings page on http://127.0.0.1:%d/", server.port)

    def _take_settings_tokens(self) -> list[str]:
        """The tokens a daemon restarted from the page left behind, if they
        can be trusted. The file is deleted either way.

        Trusted means a regular file (no symlink is followed), owned by us,
        reachable by nobody else and younger than `SETTINGS_TOKENS_MAX_AGE_S`.
        $XDG_RUNTIME_DIR is private to us, but the /tmp fallback is not: a
        file planted there must not sign anyone in.
        """
        path = runtime_dir() / SETTINGS_TOKENS_FILE
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError:
            return []
        except OSError as exc:
            # ELOOP for a symlink: not ours to follow.
            log.warning("ignoring the settings page's saved tokens: %s", exc)
            self._discard_settings_tokens(path)
            return []
        try:
            with os.fdopen(fd, "rb") as f:
                info = os.fstat(f.fileno())
                problem = self._untrusted_tokens_file(info)
                if problem is not None:
                    log.warning("ignoring the settings page's saved tokens: %s", problem)
                    return []
                data = json.loads(f.read(64 * 1024).decode("utf-8"))
        # RecursionError: deeply nested JSON. A bad file is rejected, never
        # fatal to startup.
        except (OSError, ValueError, RecursionError) as exc:
            log.warning("ignoring the settings page's saved tokens: %s", exc)
            return []
        finally:
            self._discard_settings_tokens(path)
        tokens = data.get("tokens") if isinstance(data, dict) else None
        if not isinstance(tokens, list) or not all(isinstance(t, str) and t for t in tokens):
            log.warning("ignoring the settings page's saved tokens: not a list of tokens")
            return []
        return tokens

    @staticmethod
    def _untrusted_tokens_file(info: os.stat_result) -> str | None:
        if not stat.S_ISREG(info.st_mode):
            return "not a regular file"
        if info.st_uid != os.getuid():
            return "owned by another user"
        if info.st_mode & 0o077:
            return f"mode {stat.S_IMODE(info.st_mode):o} lets others reach it"
        # A future mtime is no proof of freshness either.
        if not 0 <= time.time() - info.st_mtime < SETTINGS_TOKENS_MAX_AGE_S:
            return "too old"
        return None

    @staticmethod
    def _discard_settings_tokens(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete the settings page's saved tokens: %s", exc)

    async def _perform(self, action: Action, rewrite: bool = False) -> dict[str, Any]:
        match action:
            case Action.OPEN_MIC:
                return self._begin()
            case Action.FLUSH_AND_FINALIZE:
                return await self._finalize(rewrite=rewrite)
            case Action.DISCARD:
                await self._discard()
                return {"ok": True, "cancelled": True}
            case Action.RELEASE_MIC:
                await self._discard(reason="fatal error")
                return {"ok": False, "error": "fatal error; microphone released"}
            case _:
                return {"ok": True}

    # --- lifecycle --------------------------------------------------------

    def _begin(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        # Once, here: spec 9.4 keeps the mode chosen at start if focus moves.
        self.app = (
            self.context(self.cfg)
            if self.context is not None
            else AppContext(None, "default", False)
        )
        self.style = style_for(self.app.mode)
        self._fallback_reasons = {}
        self.levels = LevelWindows(self.cfg.audio.sample_rate)
        # `started_at` takes the injected clock, not `time.monotonic`: the
        # session's age is compared against `self.clock()` in
        # `_check_max_duration`, and two different time bases there would make
        # the elapsed time meaningless.
        self.session = Session(
            id=session_id, mode=self.app.mode, app_id=self.app.app_id, started_at=self.clock()
        )
        self.metrics = SessionMetrics(
            session_id=session_id,
            mode=self.session.mode,
            app_id=self.app.app_id,
            clock=self.clock,
            log_transcripts=self.cfg.logging.log_transcripts,
        )
        self.scheduler = Scheduler(
            self.session,
            self._polish if self.style.use_llm else _no_llm,
            (
                (lambda raw: basic_clean(raw, self.vocab.replace))
                if self.style.sentence
                else (lambda raw: minimal_clean(raw, self.vocab.replace))
            ),
            self.cfg.chunking,
            timeout_ms=self.cfg.llm.timeout_ms,
            on_change=self._render,
            clock=self.clock,
        )
        if self._mic_testing:
            # A dictation always wins: the test sees this after its next await
            # and stops, leaving the stream to the session.
            self._mic_test_preempted = True
        try:
            self.capture.start()
        except Exception as exc:
            log.error("could not open microphone: %s", exc)
            self.machine.handle(Event.FATAL)
            self.session = None
            self.metrics = None
            self.scheduler = None
            # Shown, not only stated: the popup is how the user learns why the
            # press did nothing, and it holds the error by itself.
            self._ui(lambda o: o.show())
            self._ui(lambda o: o.end("error", "mic_unavailable", fade=False))
            self._mic_unavailable = True
            self._sync_warning()
            self._notify(f"flowd: microphone unavailable ({exc})")
            return {"ok": False, "error": str(exc)}
        if self._mic_unavailable:
            # Cleared only by an open that works; nothing polls the device.
            self._mic_unavailable = False
            self._sync_warning()
        self.metrics.mark("mic_open")
        self.sleep.arm()
        where = self.cfg.logging.recordings_dir
        self.recorder = (
            SessionRecorder(Path(where).expanduser(), self.cfg.audio.sample_rate) if where else None
        )
        # `show` first: it starts a new session on the UI, clearing the last
        # one's state, so a state sent before it would be lost.
        self._ui(lambda o: o.show())
        self._ui(lambda o: o.state("recording"))
        app, hotkey = self.app, self.cfg.ui.hotkey_label
        self._ui(lambda o: o.meta(app.mode, app.app_id or "", hotkey))
        return {"ok": True, "session": session_id}

    def _recording(self) -> bool:
        """Whether there is a live session actively taking audio.

        A method rather than the condition written twice in `pump`: it is checked
        once before the lock and again after, and a type checker narrowing
        `self.session` at the first check treats the second as dead code. It is
        not — awaiting the lock is exactly where a `cancel` lands.
        """
        return self.session is not None and self.machine.state is State.RECORDING

    @property
    def recording(self) -> bool:
        """Whether a capture stream may be open: a session, a microphone test,
        or `audio.always_open`. The capture has no public way to say whether
        its idle stream is open, so `always_open` counts as open throughout."""
        return self.session is not None or self._mic_testing or self.cfg.audio.always_open

    @property
    def mic_test_preempted(self) -> bool:
        """Whether the last microphone test was ended by a dictation."""
        return self._mic_test_preempted

    def _preempted(self) -> bool:
        """The flag behind a call, as in `_recording`: `_begin` sets it while
        `mic_test` is suspended at a yield, which a type checker narrowing the
        attribute would take for dead code."""
        return self._mic_test_preempted

    async def mic_test(self, seconds: float) -> AsyncIterator[tuple[float, float]]:
        """Levels from the microphone for the settings page (design.md
        Microphone), as `(rms_db, peak_db)` per 50 ms window, for `seconds`.

        Uses `self.capture`, so there is one device path and one PortAudio
        client; `pump` does nothing without a session, so these reads do not
        race the STT. Refused with `Busy` during a dictation or another test.
        A dictation that starts mid-test ends it and keeps the stream. An
        error opening the device propagates.
        """
        if self.session is not None or self._mic_testing:
            raise Busy("the microphone is in use by a dictation")
        self._mic_testing, self._mic_test_preempted = True, False
        levels = LevelWindows(self.cfg.audio.sample_rate)
        try:
            # On the loop, as `_begin` does, so the two never open it at once.
            self.capture.start()
            deadline = self.clock() + seconds
            silent = 0
            while not self._preempted():
                pairs = levels.feed(self.capture.read())
                silent = 0 if pairs else silent + 1
                if silent >= MIC_TEST_SILENT_POLLS:
                    pairs, silent = [(FLOOR_DB, FLOOR_DB)], 0
                for pair in pairs:
                    yield pair
                    if self._preempted():
                        return
                # Checked after the first read, so even a short test reports.
                if self.clock() >= deadline:
                    return
                await asyncio.sleep(MIC_TEST_POLL_S)
        finally:
            self._mic_testing = False
            # A session that took the stream owns it now. One that failed to
            # open left it to nobody, so it is released here.
            if not self._mic_test_preempted or self.session is None:
                try:
                    self.capture.stop()
                except Exception as exc:
                    log.warning("error closing microphone: %s", exc)

    # --- settings page: detect app, restart -------------------------------

    async def focused_app(self) -> str | None:
        """The focused window's app id after `DETECT_DELAY_S`, or None when
        the desktop cannot tell (KDE and GNOME on Wayland)."""
        await asyncio.sleep(DETECT_DELAY_S)
        return await asyncio.to_thread(focused_app_id)

    async def restart(self, target: str, *, reset_position: bool) -> None:
        """Restart flowd-ui (`"ui"`) or this daemon (`"daemon"`).

        Raises `Busy` during a dictation and `Unavailable` when the target
        cannot be restarted from here. A daemon restart is only scheduled:
        it happens `RESTART_DELAY_S` after this returns.
        """
        if target not in RESTART_TARGETS:
            raise Unavailable(f"unknown restart target: {target}")
        if self.session is not None:
            raise Busy("finish the dictation first")
        if target == "ui":
            await self._restart_ui(reset_position=reset_position)
        else:
            self._restart_daemon()

    async def _restart_ui(self, *, reset_position: bool) -> None:
        overlay = self.overlay
        if overlay is None:
            raise Unavailable("the indicator is turned off")
        failure: str | None = None
        async with self._ui_restart_lock:
            # Blocking for up to a few seconds while the child quits.
            await asyncio.to_thread(overlay.stop)
            path = indicator_position_file() if reset_position else None
            if path is not None:
                # Before the start, so the new flowd-ui finds no saved
                # position and opens at the default.
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("could not delete %s: %s", path, exc)
                    failure = f"could not reset the position: {exc.strerror or exc}"
            # Restarted either way: a position that stays is no reason to
            # leave the user without an indicator.
            self._spawn_ui()
        if failure is not None:
            raise Unavailable(failure)

    def _restart_daemon(self) -> None:
        # systemd sets INVOCATION_ID for every unit it runs; anywhere else
        # there is nobody to start us again.
        if not os.environ.get("INVOCATION_ID"):
            raise Unavailable("flowd is not running under systemd; restart it yourself")
        if self._daemon_restart_pending:
            return
        if self.settings_tokens is not None:
            try:
                self._write_settings_tokens(self.settings_tokens.export())
            except OSError as exc:
                log.warning("could not save the settings page's tokens: %s", exc)
                # Not restarted: the open page would be locked out afterwards.
                raise Unavailable(
                    f"could not keep the page signed in across the restart: {exc.strerror or exc}"
                ) from exc
        self._daemon_restart_pending = True
        loop = asyncio.get_running_loop()
        loop.call_later(RESTART_DELAY_S, self._spawn_restart)

    def _write_settings_tokens(self, tokens: list[str]) -> None:
        """Leave the page's tokens for the next daemon, so the open tab keeps
        working. $XDG_RUNTIME_DIR is a per-user 0700 tmpfs, so the tokens
        still never reach a disk."""
        directory = runtime_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / SETTINGS_TOKENS_FILE
        # O_EXCL after the unlink: the file is ours and 0600 from creation,
        # never a stale one (or a link) with someone else's mode.
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"tokens": tokens}, f)

    def _spawn_restart(self) -> None:
        task = asyncio.get_running_loop().create_task(self._systemctl_restart())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _systemctl_restart(self) -> None:
        log.info("restarting flowd.service at the settings page's request")
        try:
            # `--no-block` returns once systemd has queued the job. systemctl
            # runs in this unit's cgroup, so the stop kills it along with us
            # (a new session does not leave the cgroup); a queued job no
            # longer needs it. The new session only keeps it out of signals
            # sent to our process group.
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "--user",
                "--no-block",
                "restart",
                "flowd.service",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            code = await proc.wait()
        except OSError as exc:
            log.error("could not run systemctl to restart flowd: %s", exc)
            self._restart_failed()
            return
        if code != 0:
            log.error("systemctl --user restart flowd.service failed (exit %s)", code)
            self._restart_failed()

    def _restart_failed(self) -> None:
        """No restart is coming: the tokens left for the next daemon go, and
        the page may ask again."""
        self._daemon_restart_pending = False
        try:
            (runtime_dir() / SETTINGS_TOKENS_FILE).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete the settings page's tokens: %s", exc)

    async def pump(self) -> None:
        """Move one block of audio through STT. Called by the run loop and tests."""
        if not self._recording():
            return
        if self.sleep.slept():
            # spec 9.1: the words from before a suspend are stale by resume,
            # and whatever has focus now is not where the user was dictating.
            log.info("machine suspended mid-session; cancelling it")
            if self.machine.handle(Event.CANCEL) is Action.DISCARD:
                await self._discard(reason="suspended")
            return
        pcm = self.capture.read()
        if self.recorder is not None:
            self.recorder.add(pcm)
        # Here rather than in the capture callback, which must never wait on
        # anything; a block costs microseconds (flowd/levels.py).
        self._send_levels(pcm)
        # Read before feeding what is left, so the last audio the device
        # delivered still reaches the transcript.
        lost = getattr(self.capture, "failed", None)
        # Carried out of the `async with` rather than handled inside it: the
        # fatal path calls `_discard`, which acquires this same lock, so
        # handling it here would deadlock the daemon instead of crashing it —
        # trading a loud failure for a silent one.
        failure: Exception | None = None
        async with self._stt_lock:
            # `cancel` may have landed while we waited for the lock, in which
            # case the session it belonged to is gone and its audio is not ours
            # to decode.
            if not self._recording():
                return
            try:
                # Off the loop: one `feed` call is 0.2 ms at the median on this
                # machine but 553 ms at p95 and 1.6 s at worst, because most
                # calls only buffer and every eighth or so runs the model.
                # Inline, those are windows in which the control socket cannot
                # be answered and `flowctl cancel` — the valve that stops a
                # runaway session — waits behind the decoder, against spec
                # 5.9's 50 ms budget.
                events = await asyncio.to_thread(self.stt.feed, pcm)
                # Dispatched under the lock as well, so a `cancel` cannot
                # discard the session between the decode returning and its
                # events being applied to it.
                for event in events:
                    self._on_stt_event(event)
            except Exception as exc:
                failure = exc
        if failure is not None:
            await self._fail(failure)
            return
        if lost is not None:
            await self._device_lost(str(lost))
            return
        backlog = self.capture.pending_seconds()
        if backlog > 2.0:
            # spec 9.2: warn with the CPU load, since contention is the usual
            # cause; the audio stays queued and is decoded late, never dropped.
            load = os.getloadavg()[0]
            log.warning(
                "STT is behind real time: %.1f s queued, load %.2f on %d CPUs",
                backlog,
                load,
                os.cpu_count() or 1,
            )

    def _on_stt_event(self, event: Partial | Committed) -> None:
        assert self.session is not None and self.metrics is not None
        if isinstance(event, Partial):
            self.session.live_partial = event.text
            if not self.metrics.has("first_partial"):
                self.metrics.mark("first_partial")
        else:
            self.session.live_partial = ""
            if event.text.strip():
                self.metrics.count("chunks")
                assert self.scheduler is not None
                # Renders itself when a chunk is dispatched or resolves.
                self.scheduler.on_committed(event.text)
        self._render()

    def _render(self, live: str | None = None) -> None:
        """Paint the three preview zones (spec 6.1).

        `live` overrides the live zone for a status note that belongs *beside*
        the transcript rather than instead of it — the time-limit note, where the
        user has text and also needs to know why dictation ended. `_show_status`
        is the other shape, blanking all three zones for when there is no
        transcript to show.

        A chunk moves from pending to polished when it resolves, which the
        scheduler does while the user is still speaking (spec 6). Committed text
        not yet sent as a chunk is pending too.

        `Chunk.resolved` rather than a list of state names: the states that count
        as finished are session.py's to define, and a second copy of that list
        here would be one to forget when it changes.
        """
        if self.overlay is None or self.session is None:
            return
        visible = self.session.visible_chunks()
        polished = " ".join(c.text for c in visible if c.resolved)
        pending = " ".join([c.raw for c in visible if not c.resolved] + self.session.pending_raw)
        zones = {
            "polished": polished,
            "pending": pending,
            "live": self.session.live_partial if live is None else live,
        }
        self._ui(lambda o: o.render(**zones))

    async def load_startup_vocab(self) -> None:
        """Apply vocab.toml before the first session.

        A broken file is logged, not fatal: vocabulary is a refinement, and a
        typo in it should not stop dictation from starting. `flowctl reload`
        reports the same error once the user goes to fix it.
        """
        try:
            vocab = load_vocab(self.vocab_file)
        except ValueError as exc:
            log.warning("%s; starting without a vocabulary", exc)
            return
        await self.apply_vocab(vocab)
        if vocab.terms or vocab.replace:
            log.info("vocab: %d term(s), %d replacement(s)", len(vocab.terms), len(vocab.replace))

    async def apply_vocab(self, vocab: Vocab) -> None:
        """Adopt a vocabulary: replacements for cleanup, terms for the recognizer.

        Engines without keyterm support (the fakes, the batch engine) keep only
        the replacements. The engine call takes the STT lock because it reaches
        the same transcriber a decode in flight is using.
        """
        self.vocab = vocab
        set_keyterms = getattr(self.stt, "set_keyterms", None)
        if set_keyterms is None:
            return
        async with self._stt_lock:
            await asyncio.to_thread(set_keyterms, vocab.terms)

    async def _finalize(
        self, note: str | None = None, rewrite: bool = False, *, mic_lost: bool = False
    ) -> dict[str, Any]:
        """Flush, clean, join and inject. `note` is a status line for the final
        frame — the auto-stop reason, which the user needs beside their text.
        `mic_lost` ends the session on flowd-ui as a lost microphone rather than
        as a paste, since the text is only what was heard before the loss.

        Painted here rather than by the caller because it has to be the *last*
        render before the fade: the events from `stt.finalize()` each trigger a
        render of their own, so a note painted earlier would be wiped by them.
        """
        assert self.session is not None and self.metrics is not None
        # The release instant, marked before any finalize work begins. Two of
        # spec 10.1's budgets are deltas from here rather than from the hotkey —
        # "release → last chunk committed" and the end-to-end "release → text
        # injected" — and every other mark is relative to the start of the
        # session, so without this one neither delta can be computed at all.
        self.metrics.mark("released")
        self.capture.stop()
        if note == "time limit":
            self._ui(lambda o: o.state("timelimit"))
        self._ui(lambda o: o.state("finishing"))
        # Same worker and same lock as `feed`: `finalize` runs the model over
        # whatever audio is still undecoded (anywhere from ~10 ms to ~850 ms on
        # a Ryzen 5 5600H, growing with backlog and CPU contention)
        # and touches the same stream, so it waits for any decode still in
        # flight rather than entering beside it.
        async with self._stt_lock:
            events = await asyncio.to_thread(self.stt.finalize)
        for event in events:
            self._on_stt_event(event)
        self.metrics.mark("finalized")

        if note is not None:
            # After the finalize events, so their renders cannot wipe it, and
            # before the no-speech branch below, so that `_show_status("No
            # speech")` deliberately replaces it: a user who hit the time limit
            # with nothing transcribed needs to know nothing was heard first.
            self._render(live=note)

        session, scheduler = self.session, self.scheduler
        assert scheduler is not None
        if not session.pending_raw and not session.chunks:
            return self._no_speech(mic_lost=mic_lost)
        # spec 6.5 steps 3-4: only the last chunk should still need the LLM.
        await scheduler.flush(self.cfg.llm.final_timeout_ms)
        # `cancelled` as well as the identity check: `_discard` cancels the
        # scheduler (waking this flush) before it can take the STT lock and
        # clear `self.session`, so the session can still look current here.
        if scheduler.cancelled or self.session is not session:
            # A cancel landed while the LLM was working (spec 4: FINALIZING +
            # cancel → IDLE, discard). `_discard` has already closed this
            # session out, and `self.session` may be a new one by now, so
            # nothing here may touch either.
            return {"ok": False, "reason": "cancelled"}
        assert self.metrics is not None
        if scheduler.bypassed:
            # spec 9.1: too short to be worth the round trip, and not a fallback.
            self.metrics.count("bypassed")
        if scheduler.abandoned:
            self.metrics.count("fallbacks", scheduler.abandoned)
            self.metrics.error("llm: deadline")
        visible = session.visible_chunks()
        fallback = self._session_fallback(visible, abandoned=scheduler.abandoned > 0)
        self.last_raw = " ".join(c.raw for c in visible)
        final = finish(
            stitch([(c.raw, c.text) for c in visible], sentence=self.style.sentence), self.style
        )
        self._render()
        if not final:
            # Only fillers ("um, uh"): cleaning left nothing, and injecting an
            # empty string would still paste over the user's selection.
            return self._no_speech(mic_lost=mic_lost)
        rewrite_status: str | None = None
        if rewrite:
            final, rewrite_status = await self._rewrite(final)
            if scheduler.cancelled or self.session is not session:
                return {"ok": False, "reason": "cancelled"}
        assert self.metrics is not None
        self.metrics.count("words", len(final.split()))
        self.metrics.text = final

        self.machine.handle(Event.CHUNKS_RESOLVED)
        result = await asyncio.to_thread(
            self.inject, final, self.cfg.inject, is_terminal=self.app.is_terminal
        )
        self.metrics.mark("inject")
        self.metrics.backend = result.backend
        if not result.ok:
            log.warning("injection failed: %s; text kept for `flowctl last`", result.error)
            self.metrics.error(f"inject: {result.error}")

        self.machine.handle(Event.INJECT_DONE)
        if self.recorder is not None:
            self.recorder.save(session.id, self.last_raw, final)
            self.recorder = None
        if not result.ok:
            # Checked first: nothing landed, so "pasted what was heard" and
            # "pasted as heard" would both be false.
            outcome = ("error", "paste_failed")
        elif mic_lost:
            outcome = ("error", "mic_lost")
        elif fallback is not None:
            outcome = ("fallback", fallback)
        else:
            outcome = ("done", "")
        self._end_session(text=final, reason=None, outcome=outcome)
        self._sync_warning()
        if self.cfg.ui.notify_on_finish and not mic_lost:
            # design.md Appearance: for people who don't watch the popup.
            # Errors already notify on their own paths, and a lost mic gets
            # its own notification right after this call returns (see
            # `_device_lost`) — skipped here so that session doesn't notify
            # twice.
            words = len(final.split())
            what = "pasted" if result.ok else "could not paste"
            self._notify_later(f"flowd: {what} {words} word{'s' if words != 1 else ''}")
        if self._llm_active() and self.cleanup is not None and self.cleanup.down:
            # spec 9.3: once per session, and only after the text is in: the
            # user's words matter more than the news that cleanup is degraded.
            #
            # Not awaited: `notify-send` can take its full 2 s timeout, and the
            # `stop` reply that `flowctl` is waiting on must not wait for it.
            self._notify_later("flowd: cleanup LLM is down; using basic cleanup")
        reply: dict[str, Any] = {"ok": True, "text": final, "backend": result.backend}
        if rewrite_status is not None:
            reply["rewrite"] = rewrite_status
        return reply

    def _llm_active(self) -> bool:
        """Whether cleanup requests should go out at all.

        True only when a client is wired up and `[llm] enabled` (spec 8.1) is
        still true. Checked instead of `self.cleanup is None` everywhere a
        reload could have flipped the config live.
        """
        return self.cleanup is not None and self.cfg.llm.enabled

    async def _rewrite(self, joined: str) -> tuple[str, str]:
        """spec 6.6: one more LLM pass over the whole joined text.

        Returns the text to inject and what happened: `accepted`, `rejected`
        (a guardrail failed), `failed` (no answer) or `skipped` (no LLM for
        this mode, or over `REWRITE_MAX_WORDS`). Anything but `accepted`
        injects the joined text unchanged.
        """
        metrics = self.metrics
        assert metrics is not None
        if (
            not self._llm_active()
            or not self.style.use_llm
            or len(joined.split()) > REWRITE_MAX_WORDS
        ):
            return joined, "skipped"
        assert self.cleanup is not None
        # The recording-time budget, not `final_timeout_ms`: the user asked for
        # this pass and its latency grows with length, which is why it is
        # opt-in (spec 6.6).
        result = await self.cleanup.clean(joined, self.cfg.llm.timeout_ms)
        metrics.count("llm_chunks")
        if result.text is None:
            metrics.error(f"rewrite: {result.error}")
            return joined, "failed"
        failed = guardrails.check(joined, result.text, self.cfg.guardrails, terms=self.vocab.terms)
        if failed is not None:
            log.info("rewrite failed guardrail check %d; keeping the joined text", failed)
            metrics.fail(failed)
            metrics.count("rewrite_rejected")
            return joined, "rejected"
        metrics.count("rewrite_accepted")
        return finish(result.text, self.style), "accepted"

    def _no_speech(self, *, mic_lost: bool = False) -> dict[str, Any]:
        """spec 9.1: no speech at all means inject nothing."""
        self._show_status("No speech")
        self.recorder = None
        # Still walk the machine back to IDLE. The chunks resolved, to
        # nothing, and there is nothing to inject; returning straight from
        # FINALIZING would strand it there and every later hotkey press
        # would be ignored until the daemon was restarted.
        self.machine.handle(Event.CHUNKS_RESOLVED)
        self.machine.handle(Event.INJECT_DONE)
        # `linger` even though there is no text: spec 9.1 asks for "No
        # speech" to stay up for a second, and the default would hide it in
        # the same tick it was rendered.
        outcome = ("error", "mic_lost_empty") if mic_lost else ("nospeech", "")
        self._end_session(text="", reason="no speech", linger=True, outcome=outcome)
        return {"ok": True, "reason": "no speech"}

    async def _polish(
        self, raw: str, *, chunk_id: int, context: str, merged: bool, timeout_ms: int
    ) -> str | None:
        reasons = self._fallback_reasons  # this session's, even after a cancel
        try:
            return await self._polish_chunk(
                raw, chunk_id=chunk_id, context=context, merged=merged, timeout_ms=timeout_ms
            )
        except Exception:
            # The scheduler logs it and falls back; the popup must say so too,
            # or a chunk pasted as heard would read as "Pasted".
            reasons[chunk_id] = "failed"
            raise

    async def _polish_chunk(
        self, raw: str, *, chunk_id: int, context: str, merged: bool, timeout_ms: int
    ) -> str | None:
        """The LLM's rewrite of one chunk if it passes spec 7.4, else None.

        Called by the scheduler. Every None with a cleanup client configured is
        a fallback, counted and attributed in the metrics; the text itself is
        never logged (spec 13.2). `context` is the last polished sentences:
        Sotto's prompt has no slot for it (ADR 0006), so it reaches the
        guardrails only, as known words for check 3 and repeats for check 6.
        """
        metrics = self.metrics
        if not self._llm_active() or metrics is None:
            return None
        assert self.cleanup is not None
        raw = apply_replacements(raw, self.vocab.replace)
        result = await self.cleanup.clean(raw, timeout_ms)
        if self.metrics is not metrics:
            return None  # cancelled while waiting; the caller notices
        metrics.mark("cleaned")
        metrics.count("llm_chunks")
        if result.text is None:
            metrics.count("fallbacks")
            metrics.error(f"llm: {result.error}")
            self._fallback_reasons[chunk_id] = _fallback_reason(result)
            return None
        failed = guardrails.check(
            raw,
            result.text,
            self.cfg.guardrails,
            context=context,
            terms=self.vocab.terms,
            # Scoped to this chunk (≤ `max_chunk_words` plus one merged
            # predecessor), so one cue no longer loosens the whole session.
            merged=merged or guardrails.has_correction_cue(raw, self.cfg.chunking.correction_cues),
        )
        if failed is not None:
            log.info("cleanup output failed guardrail check %d; using fallback", failed)
            metrics.fail(failed)
            metrics.count("fallbacks")
            self._fallback_reasons[chunk_id] = _fallback_reason(result)
            return None
        return result.text

    def _session_fallback(self, visible: list[Chunk], *, abandoned: bool) -> str | None:
        """flowd-ui's fallback reason for the finished session, or None.

        Only chunks the LLM was asked for count. A mode without the LLM, a
        session under `short_bypass_words` and a daemon without a cleanup
        client all resolve chunks with basic cleanup too, but nothing fell
        back there, so they report `done`. A fallen-back chunk with no recorded
        reason was cut off by the release deadline.
        """
        reasons: list[str] = []
        for chunk in visible:
            if chunk.state != "FALLBACK":
                continue
            reason = self._fallback_reasons.get(chunk.id)
            if reason is None and abandoned:
                reason = "timeout"
            if reason is not None:
                reasons.append(reason)
        return worst_fallback(reasons)

    async def _device_lost(self, reason: str) -> None:
        """spec 9.2: finalize with the text so far, inject it, then notify.

        After the injection, like the LLM-down note: the user's words matter
        more than the news, and `notify-send` can take its full 2 s timeout.
        """
        log.warning("microphone lost mid-session: %s", reason)
        if self.machine.handle(Event.DEVICE_LOST) is not Action.FLUSH_AND_FINALIZE:
            return
        assert self.metrics is not None
        self.metrics.error(f"audio: {reason}")
        await self._finalize(note="microphone lost", mic_lost=True)
        self._notify_later(f"flowd: microphone lost ({reason}); kept the text so far")

    def _notify_later(self, message: str) -> None:
        """A desktop notification that nobody waits for."""
        future = asyncio.get_running_loop().run_in_executor(None, self._notify, message)
        self._background.add(future)
        future.add_done_callback(self._background.discard)

    async def _fail(self, exc: Exception) -> None:
        """Route a mid-session engine failure to spec 4's fatal transition.

        Spec 4 gives this its own row — any state + fatal error → IDLE,
        releasing the microphone — and spec 9.1 requires the user be told.
        Without this the exception unwinds `pump`, then `run`'s loop, and the
        daemon exits with the microphone still open: the hotkey stops working
        and the only sign is a recording light that never goes off.
        """
        log.exception("STT failed mid-session: %s", exc)
        if self.machine.handle(Event.FATAL) is Action.RELEASE_MIC:
            await self._discard(reason="fatal error")
        self._notify(f"flowd: dictation failed ({exc})")

    async def _discard(self, reason: str = "cancelled") -> None:
        # Which session this discard is for. Waiting on the lock below can take
        # as long as one decode (~1.6 s at worst), and debounce only suppresses
        # a `start` for 200 ms, so a user who cancels and re-presses their
        # hotkey can have a *new* session by the time we resume. Everything
        # after the lock is bookkeeping for the session that ended, and applying
        # it to its successor would clear `self.session` with the microphone
        # open — the next `stop` would then find nothing to inject.
        discarding = self.session
        # Before the lock wait below: `_begin` for a newer session may replace
        # the recorder meanwhile, and that one must survive this discard.
        if self.recorder is not None:
            self.recorder.discard()
            self.recorder = None
        if self.scheduler is not None and self.scheduler.session is discarding:
            # Stop polishing for a session nobody will read, and wake a
            # `flush` waiting on it so the cancel is not held up by the LLM.
            self.scheduler.cancel()
        try:
            self.capture.stop()
        except Exception as exc:
            log.warning("error closing microphone: %s", exc)
        # The engine outlives the session (spec 5.3 loads the model once), so an
        # abandoned session's audio and half-formed transcript have to be thrown
        # away explicitly or the next dictation starts inside this one.
        #
        # Under the lock, and so possibly waiting for an in-flight decode: one
        # Moonshine stream cannot be reset while a worker is still reading it.
        # The wait is bounded by a single `feed` call and costs this cancel up to
        # ~1.6 s at worst, which is the price of not corrupting the stream. The
        # microphone is already closed above, so the user has stopped being
        # recorded either way — which is what `cancel` is urgent about.
        async with self._stt_lock:
            self.stt.reset()
        # The reset above is kept even when a new session has begun: the lock is
        # FIFO, so it runs before that session's first `feed`, and flushing the
        # abandoned audio is exactly what it is for. What must not follow it is
        # the bookkeeping, which belongs to a session that is already over.
        if discarding is not None and self.session is not discarding:
            log.debug("discard for session %s overtaken by a new session", discarding.id)
            return
        if self.metrics is not None:
            # spec 10.2 asks for one line per session, and an abandoned session
            # is still a session: how often dictation gets cancelled is the
            # signal that a hotkey is misfiring or a microphone is opening too
            # slowly, and dropping the record leaves `flowctl stats` reporting a
            # clean history of a tool nobody can use. An empty `text` keeps
            # whatever `flowctl last` already held (spec 5.7): cancelling this
            # session does not erase the previous one.
            self._end_session(text="", reason=reason, outcome=discard_outcome(reason))
            return
        # No metrics to write: the microphone never opened, and `_begin` has
        # already reported and cleared that failure.
        state, why = discard_outcome(reason)
        self._ui(lambda o: o.end(state, why, fade=False))
        self.session = None

    def _end_session(
        self,
        text: str,
        reason: str | None,
        linger: bool | None = None,
        *,
        outcome: tuple[str, str],
    ) -> None:
        """Log the session and end it on flowd-ui with `outcome`, its
        `(state, reason)` from `kOutcomes` in ui/src/popup_model.cpp."""
        assert self.metrics is not None
        if text:
            self.last_text = text
        if reason:
            self.metrics.error(reason)
        self.last_record = self.metrics.to_record()
        path = self.metrics_file
        # With no explicit path, write only into a state directory that already
        # exists, so importing the daemon never creates one as a side effect.
        if self.write_metrics and (self.metrics_path is not None or path.parent.exists()):
            try:
                write_record(self.last_record, path)
            except OSError as exc:
                log.warning("could not write metrics: %s", exc)
        # A successful dictation fades, so the user sees what landed in the
        # window; one with nothing to show goes at once (spec 6.1).
        #
        # `linger` overrides that default for the case where there is no text
        # but there *is* something to read: spec 9.1 wants "No speech" up for
        # a second, and inferring the choice from `text` alone hid it, since
        # the message and the teardown went out in the same tick.
        #
        # `end` sends the state before the fade or hide: flowd-ui holds an
        # outcome only if it knows it before the popup is told to go.
        fade = linger if linger is not None else bool(text)
        state, why = outcome
        self._ui(lambda o: o.end(state, why, fade=fade))
        self.session = None
        self.metrics = None
        self.scheduler = None

    # --- helpers ----------------------------------------------------------

    def _show_status(self, message: str) -> None:
        self._ui(lambda o: o.render(polished="", pending="", live=message))

    def _ui(self, send: Callable[[OverlayLike], None]) -> None:
        """Tell flowd-ui something, if there is one. A UI failure never costs
        a dictation (ADR 0003), so nothing it raises reaches the session.
        """
        if self.overlay is None:
            return
        try:
            send(self.overlay)
        except Exception:
            # Each lambda literal has its own code object, so this names the
            # call site.
            code = getattr(send, "__code__", None)
            site = f"{code.co_filename}:{code.co_firstlineno}" if code else repr(send)
            self._log_ui_failure(site, "message to flowd-ui failed")

    def _log_ui_failure(self, site: str, message: str) -> None:
        """Warn the first time a call site fails, then log at debug: a broken
        UI would otherwise log once per level frame, 20 times a second."""
        if site in self._ui_failed:
            log.debug("%s (%s)", message, site, exc_info=True)
            return
        self._ui_failed.add(site)
        log.warning("%s (%s); later failures here log at debug", message, site, exc_info=True)

    def _send_levels(self, pcm: np.ndarray) -> None:
        """The meter's frames for one block. Direct rather than through `_ui`,
        as it runs 20 times a second; `UiProcess.level` drops frames while the
        UI is down or behind, so this never waits on it."""
        overlay = self.overlay
        if overlay is None:
            return
        try:
            for rms_db, peak_db in self.levels.feed(pcm):
                overlay.level(rms_db, peak_db)
        except Exception:
            self._log_ui_failure("level", "level to flowd-ui failed")

    def _configure_ui(self, cfg: Config) -> None:
        """Push a reloaded `[ui]`. Blocking when it turns the UI off."""
        if self.overlay is None:
            return
        try:
            self.overlay.configure(cfg.ui, cfg.audio.max_session_s)
        except Exception:
            log.exception("could not apply the new [ui] settings to flowd-ui")

    def _sync_warning(self) -> None:
        """Show whichever warning applies now, or clear it (design.md "Warning")."""
        if self._mic_unavailable:
            warning: tuple[str | None, bool] = (WARN_MIC_UNAVAILABLE, True)
        elif self._llm_active() and self.cleanup is not None and self.cleanup.down:
            warning = (WARN_CLEANUP_OFFLINE, False)
        else:
            warning = (None, False)
        if warning == self._warning:
            return
        self._warning = warning
        reason, blocking = warning
        self._ui(lambda o: o.warn(reason, blocking=blocking))

    def _notify(self, message: str) -> None:
        """Desktop notification; failure to notify is never fatal."""
        try:
            subprocess.run(["notify-send", "flowd", message], check=False, timeout=2)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("notify-send unavailable: %s", exc)

    async def run(self, socket_path: Path) -> None:
        from flowd.control import serve

        self.loop = asyncio.get_running_loop()
        await self.load_startup_vocab()
        server = await serve(socket_path, self.handle)
        log.info("flowd listening on %s", socket_path)
        block_s = self.cfg.audio.block_ms / 1000.0
        health = asyncio.create_task(self._health_loop()) if self.cleanup is not None else None
        try:
            await self._start_settings()
            # Only once the socket is ours: a second flowd that loses the
            # single-instance check must not flash a second indicator.
            self._start_ui()
            self._sync_warning()
            while True:
                await self.pump()
                await self._check_max_duration()
                self._exit_if_microphone_stuck()
                if self.session is None:
                    # Brings back an indicator that died at idle. Cheap: a
                    # poll of the child, and `UiProcess` keeps its own
                    # respawn backoff. A UI that exits cleanly is respawned
                    # too, once per backoff interval, by design.
                    self._start_ui()
                await asyncio.sleep(block_s if self.session is not None else 0.2)
        finally:
            if health is not None:
                health.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await health
            # Each step on its own, so a failing LLM client still lets both
            # servers close.
            if self.cleanup is not None:
                try:
                    await self.cleanup.aclose()
                except Exception:
                    log.exception("could not close the cleanup client")
            if self.settings_server is not None:
                try:
                    await self.settings_server.close()
                except Exception:
                    log.exception("could not close the settings page's server")
                self.settings_server = None
            server.close()
            await server.wait_closed()
            # The overlay is our child (spec 9.5). It does exit when its stdin
            # closes, but only once it notices; telling it to quit means the
            # daemon does not leave a stale preview over the user's work.
            if self.overlay is not None:
                try:
                    self.overlay.stop()
                except Exception:
                    log.exception("could not stop flowd-ui")

    def _start_ui(self) -> None:
        if self._ui_restart_lock.locked():
            # A restart from the settings page starts it when it is ready.
            return
        self._spawn_ui()

    def _spawn_ui(self) -> None:
        if self.overlay is None:
            return
        try:
            self.overlay.start()
        except Exception:
            # A UI failure never costs a dictation (ADR 0003).
            log.exception("could not start flowd-ui")

    def on_ui_event(self, event: dict[str, Any]) -> None:
        """An event from flowd-ui (ADR 0013). Called on its reader thread, so
        anything that touches the session hops to the loop first."""
        kind = event.get("event")
        if kind == "click":
            loop = self.loop
            if loop is None or loop.is_closed():
                return
            loop.call_soon_threadsafe(self._toggle_from_ui)
        elif kind == "moved":
            # flowd-ui stores the position itself; nothing to do here.
            log.debug("indicator moved to %s on %s", event.get("x"), event.get("output"))

    def _toggle_from_ui(self) -> None:
        task = asyncio.ensure_future(self._toggle())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _toggle(self) -> None:
        try:
            reply = await self.handle({"cmd": "toggle"})
        except Exception:
            # A click has no one to report to, so a failure lands in the log.
            log.exception("toggle from the indicator failed")
            return
        if not reply.get("ok"):
            log.debug("indicator click: %s", reply.get("error"))

    def _exit_if_microphone_stuck(self) -> None:
        """ADR 0015: a stream that would not stop may hold the device until this
        process exits, blocking every other program that wants the mic.

        Only while idle, so a dictation in progress still gets its text, and
        `settle` releases PortAudio only when no stream is open. A stop that
        finishes within the grace period is slow, not stuck, and does not
        restart the daemon. The exit is non-zero and systemd's
        `Restart=on-failure` starts a fresh daemon, which is what actually
        frees the device. Captures without `settle` (replay, tests) never leak.
        """
        if self.machine.state is not State.IDLE:
            return
        settle = getattr(self.capture, "settle", None)
        if settle is None or not settle():
            return
        self._notify("flowd: the microphone did not close; restarting to release it")
        raise MicrophoneStuck("an audio stream did not stop and may still hold the microphone")

    async def _health_loop(self) -> None:
        """spec 5.5: probe the LLM every `health_interval_s` while idle.

        This is the only way back from `down`, since a down client sends no
        cleanup requests. Skipped mid-session so a probe never competes with a
        dictation for the server's single slot.
        """
        while True:
            if self._llm_active() and self.session is None:
                assert self.cleanup is not None
                try:
                    await self.cleanup.check_health()
                except Exception:
                    # A dead loop leaves a down client down for good.
                    log.exception("cleanup health probe failed")
                self._health_checked_at = time.monotonic()
            # Every pass, mid-session too: requests during a dictation can
            # mark the client down, and the popup footer should say so.
            self._sync_warning()
            await asyncio.sleep(self.cfg.llm.health_interval_s)

    async def _check_max_duration(self) -> None:
        if self.session is None or self.machine.state is not State.RECORDING:
            return
        elapsed = self.clock() - self.session.started_at
        if elapsed >= self.cfg.audio.max_session_s:
            log.info("session hit max_session_s; finalizing")
            if self.machine.handle(Event.MAX_DURATION) is Action.FLUSH_AND_FINALIZE:
                # spec 4's table and spec 9.1: an auto-stop says so, or the user
                # cannot tell it from their own stop.
                await self._finalize(note="time limit")
