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


#: Events a user can trigger by keypress, and so subject to debounce (spec 9.1).
#: `cancel` is deliberately absent: it is the safety valve that stops a runaway
#: session, so it must never be swallowed.
_DEBOUNCED = frozenset({Event.START, Event.STOP, Event.TOGGLE})


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

    def handle(self, event: Event) -> Action | None:
        """Apply an event. Returns the side effect to perform, or None to ignore."""
        if event in _DEBOUNCED:
            now = self._clock()
            if self._last_command is not None and now - self._last_command < self._debounce_s:
                log.debug("debounced %s", event)
                return None
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
