"""The daemon: state machine driver and command handler (spec 4)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from flowd import guardrails
from flowd.audio import MicrophoneStuck
from flowd.cleanup import CleanupClient
from flowd.config import Config, config_path, reload_config, state_dir
from flowd.context import AppContext
from flowd.inject import inject_text as real_inject
from flowd.inject.base import InjectResult
from flowd.joiner import stitch
from flowd.metrics import SessionMetrics, read_records, summarise, write_record
from flowd.modes import Style, finish, style_for
from flowd.recordings import SessionRecorder
from flowd.scheduler import Scheduler
from flowd.session import Session
from flowd.state import Action, Event, Machine, State
from flowd.stt import Committed, Partial, SttEngine
from flowd.suspend import SleepDetector
from flowd.textclean import apply_replacements, basic_clean, minimal_clean
from flowd.vocab import Vocab, load_vocab, vocab_path

log = logging.getLogger(__name__)

Injector = Callable[..., InjectResult]

#: spec 6.6: the full-rewrite pass takes the whole joined text, ≤ 300 words.
REWRITE_MAX_WORDS = 300


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


async def _no_llm(raw: str, *, context: str, merged: bool, timeout_ms: int) -> str | None:
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
            # Both files are checked before either is applied, so a bad vocab
            # leaves the old config and the old vocabulary in place together.
            try:
                new_vocab = load_vocab(self.vocab_file)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
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
        # `--rewrite` is a modifier on whichever command ends the session
        # (spec 6.6), so a toggle bound to a second hotkey works as well.
        return await self._perform(action, rewrite=bool(request.get("rewrite")))

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
        try:
            self.capture.start()
        except Exception as exc:
            log.error("could not open microphone: %s", exc)
            self.machine.handle(Event.FATAL)
            self.session = None
            self.metrics = None
            self.scheduler = None
            self._notify(f"flowd: microphone unavailable ({exc})")
            return {"ok": False, "error": str(exc)}
        self.metrics.mark("mic_open")
        self.sleep.arm()
        where = self.cfg.logging.recordings_dir
        self.recorder = (
            SessionRecorder(Path(where).expanduser(), self.cfg.audio.sample_rate) if where else None
        )
        if self.overlay is not None:
            self.overlay.show()
        return {"ok": True, "session": session_id}

    def _recording(self) -> bool:
        """Whether there is a live session actively taking audio.

        A method rather than the condition written twice in `pump`: it is checked
        once before the lock and again after, and a type checker narrowing
        `self.session` at the first check treats the second as dead code. It is
        not — awaiting the lock is exactly where a `cancel` lands.
        """
        return self.session is not None and self.machine.state is State.RECORDING

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
        self.overlay.render(
            polished=polished,
            pending=pending,
            live=self.session.live_partial if live is None else live,
        )

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

    async def _finalize(self, note: str | None = None, rewrite: bool = False) -> dict[str, Any]:
        """Flush, clean, join and inject. `note` is a status line for the final
        frame — the auto-stop reason, which the user needs beside their text.

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
            return self._no_speech()
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
        self.last_raw = " ".join(c.raw for c in visible)
        final = finish(
            stitch([(c.raw, c.text) for c in visible], sentence=self.style.sentence), self.style
        )
        self._render()
        if not final:
            # Only fillers ("um, uh"): cleaning left nothing, and injecting an
            # empty string would still paste over the user's selection.
            return self._no_speech()
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
        self._end_session(text=final, reason=None)
        if self.cleanup is not None and self.cleanup.down:
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
            self.cleanup is None
            or not self.style.use_llm
            or len(joined.split()) > REWRITE_MAX_WORDS
        ):
            return joined, "skipped"
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

    def _no_speech(self) -> dict[str, Any]:
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
        self._end_session(text="", reason="no speech", linger=True)
        return {"ok": True, "reason": "no speech"}

    async def _polish(self, raw: str, *, context: str, merged: bool, timeout_ms: int) -> str | None:
        """The LLM's rewrite of one chunk if it passes spec 7.4, else None.

        Called by the scheduler. Every None with a cleanup client configured is
        a fallback, counted and attributed in the metrics; the text itself is
        never logged (spec 13.2). `context` is the last polished sentences:
        Sotto's prompt has no slot for it (ADR 0006), so it reaches the
        guardrails only, as known words for check 3 and repeats for check 6.
        """
        metrics = self.metrics
        if self.cleanup is None or metrics is None:
            return None
        raw = apply_replacements(raw, self.vocab.replace)
        result = await self.cleanup.clean(raw, timeout_ms)
        if self.metrics is not metrics:
            return None  # cancelled while waiting; the caller notices
        metrics.mark("cleaned")
        metrics.count("llm_chunks")
        if result.text is None:
            metrics.count("fallbacks")
            metrics.error(f"llm: {result.error}")
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
            return None
        return result.text

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
        await self._finalize(note="microphone lost")
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
            self._end_session(text="", reason=reason)
            return
        # No metrics to write: the microphone never opened, and `_begin` has
        # already reported and cleared that failure.
        if self.overlay is not None:
            self.overlay.hide()
        self.session = None

    def _end_session(self, text: str, reason: str | None, linger: bool | None = None) -> None:
        assert self.metrics is not None
        if text:
            self.last_text = text
        if reason:
            self.metrics.error(reason)
        self.last_record = self.metrics.to_record()
        path = self.metrics_path or (state_dir() / "metrics.jsonl")
        # With no explicit path, write only into a state directory that already
        # exists, so importing the daemon never creates one as a side effect.
        if self.write_metrics and (self.metrics_path is not None or path.parent.exists()):
            try:
                write_record(self.last_record, path)
            except OSError as exc:
                log.warning("could not write metrics: %s", exc)
        if self.overlay is not None:
            # A successful dictation fades, so the user sees what landed in the
            # window; one with nothing to show goes at once (spec 6.1).
            #
            # `linger` overrides that default for the case where there is no text
            # but there *is* something to read: spec 9.1 wants "No speech" up for
            # a second, and inferring the choice from `text` alone hid it, since
            # the message and the teardown went out in the same tick.
            if linger if linger is not None else bool(text):
                self.overlay.fade()
            else:
                self.overlay.hide()
        self.session = None
        self.metrics = None
        self.scheduler = None

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

        self.loop = asyncio.get_running_loop()
        await self.load_startup_vocab()
        server = await serve(socket_path, self.handle)
        log.info("flowd listening on %s", socket_path)
        block_s = self.cfg.audio.block_ms / 1000.0
        health = asyncio.create_task(self._health_loop()) if self.cleanup is not None else None
        try:
            while True:
                await self.pump()
                await self._check_max_duration()
                self._exit_if_microphone_stuck()
                await asyncio.sleep(block_s if self.session is not None else 0.2)
        finally:
            if health is not None:
                health.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await health
            if self.cleanup is not None:
                await self.cleanup.aclose()
            server.close()
            await server.wait_closed()
            # The overlay is our child (spec 9.5). It does exit when its stdin
            # closes, but only once it notices; telling it to quit means the
            # daemon does not leave a stale preview over the user's work.
            if self.overlay is not None:
                self.overlay.stop()

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
            if self.cleanup is not None and self.session is None:
                try:
                    await self.cleanup.check_health()
                except Exception:
                    # A dead loop leaves a down client down for good.
                    log.exception("cleanup health probe failed")
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
