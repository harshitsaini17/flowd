"""The session state machine (spec 4).

Pure logic: it decides transitions and names the side effect to perform, but
performs none itself, so every row of the spec table is directly testable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum

log = logging.getLogger(__name__)


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    INJECTING = "injecting"


class Event(StrEnum):
    START = "start"
    STOP = "stop"
    TOGGLE = "toggle"
    CANCEL = "cancel"
    MAX_DURATION = "max_duration"
    CHUNKS_RESOLVED = "chunks_resolved"
    INJECT_DONE = "inject_done"
    FATAL = "fatal"


class Action(StrEnum):
    OPEN_MIC = "open_mic"
    FLUSH_AND_FINALIZE = "flush_and_finalize"
    DISCARD = "discard"
    JOIN = "join"
    HIDE_OVERLAY = "hide_overlay"
    RELEASE_MIC = "release_mic"


#: Events a user can trigger by keypress. Spec 4 measures the debounce window
#: from "the previous command", whatever kind it was, so every one of these
#: records when it arrived — see `_SUPPRESSIBLE` for which can be swallowed.
_USER_COMMANDS = frozenset({Event.START, Event.STOP, Event.TOGGLE, Event.CANCEL})

#: The events debounce may actually discard: spec 4 names exactly one, "a
#: `start` within 200 ms of the previous command", and `toggle` because a
#: repeated press of one key is the bounce that rule exists for.
#:
#: `stop` and `cancel` are deliberately absent, and for the same reason: both
#: end something the user started, and swallowing either strands the session
#: with the microphone open. In `ptt` mode the compositor sends `start` on press
#: and `stop` on release, so any tap shorter than `debounce_ms` delivers both
#: inside the window — two halves of one gesture rather than a repeat of one.
#: Discarding that release leaves RECORDING live until `max_session_s` (five
#: minutes by default), with the user's next `start` debounced too, and the only
#: sign being a microphone that never closed.
_SUPPRESSIBLE = frozenset({Event.START, Event.TOGGLE})


class Machine:
    def __init__(
        self,
        debounce_ms: int = 200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = State.IDLE
        self._debounce_s = debounce_ms / 1000.0
        self._clock = clock
        self._last_command: float | None = None

    @property
    def state(self) -> State:
        return self._state

    def set_debounce_ms(self, debounce_ms: int) -> None:
        """Change the debounce window in place (spec 8: `flowctl reload`).

        A setter rather than a fresh `Machine`, because replacing the object
        would reset `_state` to IDLE: a reload during dictation would drop the
        session and leave the microphone open with nothing attached.
        """
        self._debounce_s = debounce_ms / 1000.0

    def handle(self, event: Event) -> Action | None:
        """Apply an event. Returns the side effect to perform, or None to ignore."""
        if event in _USER_COMMANDS:
            now = self._clock()
            recent = self._last_command is not None and now - self._last_command < self._debounce_s
            if recent and event in _SUPPRESSIBLE:
                log.debug("debounced %s", event)
                return None
            # Recorded even for an event that cannot be suppressed: the window
            # runs from the previous command of any kind, so a `stop` that gets
            # through still arms it against the `start` that follows.
            self._last_command = now

        # "Any | fatal error | IDLE" (spec 4): checked before the table so it
        # applies from every state, including INJECTING.
        if event is Event.FATAL:
            self._state = State.IDLE
            return Action.RELEASE_MIC

        if event is Event.TOGGLE:
            event = Event.START if self._state is State.IDLE else Event.STOP

        match (self._state, event):
            case (State.IDLE, Event.START):
                self._state = State.RECORDING
                return Action.OPEN_MIC
            case (State.RECORDING, Event.STOP) | (State.RECORDING, Event.MAX_DURATION):
                self._state = State.FINALIZING
                return Action.FLUSH_AND_FINALIZE
            case (State.RECORDING, Event.CANCEL) | (State.FINALIZING, Event.CANCEL):
                self._state = State.IDLE
                return Action.DISCARD
            case (State.FINALIZING, Event.CHUNKS_RESOLVED):
                self._state = State.INJECTING
                return Action.JOIN
            case (State.INJECTING, Event.INJECT_DONE):
                self._state = State.IDLE
                return Action.HIDE_OVERLAY
            case _:
                log.info("ignoring %s in state %s", event, self._state)
                return None
