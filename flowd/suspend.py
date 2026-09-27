"""Suspend detection for a live session (spec 9.1).

`CLOCK_MONOTONIC` stops while the machine is suspended and `CLOCK_BOOTTIME`
does not, so the gap between them grows by exactly the time spent asleep. That
needs no D-Bus connection to logind, and it catches a suspend however it was
triggered.
"""

from __future__ import annotations

import time
from collections.abc import Callable

#: spec 9.1: "Monotonic clock jump > 5 s".
SLEEP_THRESHOLD_S = 5.0


def _boottime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


class SleepDetector:
    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        boottime: Callable[[], float] = _boottime,
        threshold_s: float = SLEEP_THRESHOLD_S,
    ) -> None:
        self._monotonic = monotonic
        self._boottime = boottime
        self._threshold_s = threshold_s
        self._offset = 0.0

    def _gap(self) -> float:
        return self._boottime() - self._monotonic()

    def arm(self) -> None:
        """Start watching from now, forgetting any earlier sleep."""
        self._offset = self._gap()

    def slept(self) -> bool:
        """Whether the machine was suspended for longer than the threshold since `arm`."""
        return self._gap() - self._offset > self._threshold_s
