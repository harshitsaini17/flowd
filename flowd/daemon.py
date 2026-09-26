"""The daemon: state machine driver and command handler (spec 4)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from flowd.config import Config, config_path, reload_config, state_dir
from flowd.inject import inject_text as real_inject
from flowd.inject.base import InjectResult
from flowd.joiner import join_chunks
from flowd.metrics import SessionMetrics, read_records, summarise, write_record
from flowd.session import Session
from flowd.state import Action, Event, Machine, State
from flowd.stt import Committed, Partial, SttEngine
from flowd.textclean import basic_clean

log = logging.getLogger(__name__)

Injector = Callable[..., InjectResult]


class Capture(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read(self) -> np.ndarray: ...
    def pending_seconds(self) -> float: ...


class OverlayLike(Protocol):
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def fade(self) -> None: ...
    def render(self, **zones: str) -> None: ...
    def stop(self) -> None: ...


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
    ) -> None:
        self.cfg = cfg
        self.stt = stt
        self.capture = capture
        self.overlay = overlay
        self.inject = injector
        self.clock = clock
        self.config_file = config_file or config_path()
        self.metrics_path = metrics_path
        self.machine = Machine(debounce_ms=cfg.hotkey.debounce_ms, clock=clock)
        self.session: Session | None = None
        self.metrics: SessionMetrics | None = None
        self.last_text: str = ""
        self.last_record: dict[str, Any] = {}

    # --- command handling -------------------------------------------------

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = str(request["cmd"])
        if cmd == "status":
            return {"ok": True, "state": str(self.machine.state)}
        if cmd == "last":
            return {"ok": True, "text": self.last_text}
        if cmd == "stats":
            path = self.metrics_path or (state_dir() / "metrics.jsonl")
            return {"ok": True, "stats": summarise(read_records(path))}
        if cmd == "reload":
            new_cfg, error = reload_config(self.cfg, self.config_file)
            if error is not None:
                return {"ok": False, "error": error}
            self.cfg = new_cfg
            return {"ok": True}

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
        return await self._perform(action)

    async def _perform(self, action: Action) -> dict[str, Any]:
        match action:
            case Action.OPEN_MIC:
                return self._begin()
            case Action.FLUSH_AND_FINALIZE:
                return await self._finalize()
            case Action.DISCARD:
                self._discard()
                return {"ok": True, "cancelled": True}
            case Action.RELEASE_MIC:
                self._discard(reason="fatal error")
                return {"ok": False, "error": "fatal error; microphone released"}
            case _:
                return {"ok": True}

    # --- lifecycle --------------------------------------------------------

    def _begin(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        # `started_at` takes the injected clock, not `time.monotonic`: the
        # session's age is compared against `self.clock()` in
        # `_check_max_duration`, and two different time bases there would make
        # the elapsed time meaningless.
        self.session = Session(id=session_id, started_at=self.clock())
        self.metrics = SessionMetrics(
            session_id=session_id,
            mode=self.session.mode,
            clock=self.clock,
            log_transcripts=self.cfg.logging.log_transcripts,
        )
        try:
            self.capture.start()
        except Exception as exc:
            log.error("could not open microphone: %s", exc)
            self.machine.handle(Event.FATAL)
            self.session = None
            self.metrics = None
            self._notify(f"flowd: microphone unavailable ({exc})")
            return {"ok": False, "error": str(exc)}
        self.metrics.mark("mic_open")
        if self.overlay is not None:
            self.overlay.show()
        return {"ok": True, "session": session_id}

    async def pump(self) -> None:
        """Move one block of audio through STT. Called by the run loop and tests."""
        if self.session is None or self.machine.state is not State.RECORDING:
            return
        pcm = self.capture.read()
        for event in self.stt.feed(pcm):
            self._on_stt_event(event)
        if self.capture.pending_seconds() > 2.0:
            log.warning("STT is behind real time: %.1f s queued", self.capture.pending_seconds())

    def _on_stt_event(self, event: Partial | Committed) -> None:
        assert self.session is not None and self.metrics is not None
        if isinstance(event, Partial):
            self.session.live_partial = event.text
            if not self.metrics.has("first_partial"):
                self.metrics.mark("first_partial")
        else:
            self.session.live_partial = ""
            if event.text.strip():
                self.session.add_chunk(event.text)
                self.metrics.count("chunks")
        self._render()

    def _render(self) -> None:
        """Paint the three preview zones (spec 6.1).

        A chunk moves from pending to polished when it resolves. Phase 2 has no
        LLM and resolves nothing, so in practice the polished zone stays empty
        and everything shows dimmed until phase 3 fills it; the split is written
        here rather than later because this is the code that owns it.

        `Chunk.resolved` rather than a list of state names: the states that count
        as finished are session.py's to define, and a second copy of that list
        here would be one to forget when it changes.
        """
        if self.overlay is None or self.session is None:
            return
        visible = self.session.visible_chunks()
        polished = " ".join(c.text for c in visible if c.resolved)
        pending = " ".join(c.raw for c in visible if not c.resolved)
        self.overlay.render(polished=polished, pending=pending, live=self.session.live_partial)

    async def _finalize(self) -> dict[str, Any]:
        assert self.session is not None and self.metrics is not None
        # The release instant, marked before any finalize work begins. Two of
        # spec 10.1's budgets are deltas from here rather than from the hotkey —
        # "release → last chunk committed" and the end-to-end "release → text
        # injected" — and every other mark is relative to the start of the
        # session, so without this one neither delta can be computed at all.
        self.metrics.mark("released")
        self.capture.stop()
        for event in self.stt.finalize():
            self._on_stt_event(event)
        self.metrics.mark("finalized")

        raw_parts = [c.raw for c in self.session.visible_chunks()]
        if not any(part.strip() for part in raw_parts):
            # spec 9.1: no speech at all means inject nothing.
            self._show_status("No speech")
            # Still walk the machine back to IDLE. The chunks resolved, to
            # nothing, and there is nothing to inject; returning straight from
            # FINALIZING would strand it there and every later hotkey press
            # would be ignored until the daemon was restarted.
            self.machine.handle(Event.CHUNKS_RESOLVED)
            self.machine.handle(Event.INJECT_DONE)
            self._end_session(text="", reason="no speech")
            return {"ok": True, "reason": "no speech"}

        cleaned = [basic_clean(part) for part in raw_parts]
        final = join_chunks(cleaned)
        self.metrics.count("words", len(final.split()))
        self.metrics.text = final

        self.machine.handle(Event.CHUNKS_RESOLVED)
        result = await asyncio.to_thread(self.inject, final, self.cfg.inject, is_terminal=False)
        self.metrics.mark("inject")
        self.metrics.backend = result.backend
        if not result.ok:
            log.warning("injection failed: %s; text kept for `flowctl last`", result.error)
            self.metrics.error(f"inject: {result.error}")

        self.machine.handle(Event.INJECT_DONE)
        self._end_session(text=final, reason=None)
        return {"ok": True, "text": final, "backend": result.backend}

    def _discard(self, reason: str = "cancelled") -> None:
        try:
            self.capture.stop()
        except Exception as exc:
            log.warning("error closing microphone: %s", exc)
        # The engine outlives the session (spec 5.3 loads the model once), so an
        # abandoned session's audio and half-formed transcript have to be thrown
        # away explicitly or the next dictation starts inside this one.
        self.stt.reset()
        if self.metrics is not None:
            # spec 10.2 asks for one line per session, and an abandoned session
            # is still a session: how often dictation gets cancelled is the
            # signal that a hotkey is misfiring or a microphone is opening too
            # slowly, and dropping the record leaves `flowctl stats` reporting a
            # clean history of a tool nobody can use. An empty `text` keeps
            # whatever `flowctl last` already held (spec 5.7): cancelling this
            # session does not erase the previous one.
            self._end_session(text="", reason=reason)
            return
        # No metrics to write: the microphone never opened, and `_begin` has
        # already reported and cleared that failure.
        if self.overlay is not None:
            self.overlay.hide()
        self.session = None

    def _end_session(self, text: str, reason: str | None) -> None:
        assert self.metrics is not None
        if text:
            self.last_text = text
        if reason:
            self.metrics.error(reason)
        self.last_record = self.metrics.to_record()
        path = self.metrics_path or (state_dir() / "metrics.jsonl")
        # With no explicit path, write only into a state directory that already
        # exists, so importing the daemon never creates one as a side effect.
        if self.metrics_path is not None or path.parent.exists():
            try:
                write_record(self.last_record, path)
            except OSError as exc:
                log.warning("could not write metrics: %s", exc)
        if self.overlay is not None:
            # A successful dictation fades, so the user sees what landed in the
            # window; one with nothing to show goes at once (spec 6.1).
            if text:
                self.overlay.fade()
            else:
                self.overlay.hide()
        self.session = None
        self.metrics = None

    # --- helpers ----------------------------------------------------------

    def _show_status(self, message: str) -> None:
        if self.overlay is not None:
            self.overlay.render(polished="", pending="", live=message)

    def _notify(self, message: str) -> None:
        """Desktop notification; failure to notify is never fatal."""
        try:
            subprocess.run(["notify-send", "flowd", message], check=False, timeout=2)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("notify-send unavailable: %s", exc)

    async def run(self, socket_path: Path) -> None:
        from flowd.control import serve

        server = await serve(socket_path, self.handle)
        log.info("flowd listening on %s", socket_path)
        block_s = self.cfg.audio.block_ms / 1000.0
        try:
            while True:
                await self.pump()
                await self._check_max_duration()
                await asyncio.sleep(block_s if self.session is not None else 0.2)
        finally:
            server.close()
            await server.wait_closed()
            # The overlay is our child (spec 9.5). It does exit when its stdin
            # closes, but only once it notices; telling it to quit means the
            # daemon does not leave a stale preview over the user's work.
            if self.overlay is not None:
                self.overlay.stop()

    async def _check_max_duration(self) -> None:
        if self.session is None or self.machine.state is not State.RECORDING:
            return
        elapsed = self.clock() - self.session.started_at
        if elapsed >= self.cfg.audio.max_session_s:
            log.info("session hit max_session_s; finalizing")
            if self.machine.handle(Event.MAX_DURATION) is Action.FLUSH_AND_FINALIZE:
                await self._finalize()
