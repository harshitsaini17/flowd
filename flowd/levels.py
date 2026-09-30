"""Microphone level for flowd-ui's meter (ADR 0013, design.md "Recording").

The meter is driven by RMS and peak in dBFS over each 50 ms window, 20 Hz.
Blocks from the capture ring are not window-sized, so the tail of one block is
carried into the next rather than reported as a short, noisier window.
"""

from __future__ import annotations

import numpy as np

#: design.md: "RMS in dBFS over each 50 ms window (20 Hz)".
WINDOW_S = 0.05
#: Silence and anything below it. Finite, so it survives JSON.
FLOOR_DB = -90.0
#: Keeps `log10` finite for digital silence; far below `FLOOR_DB` anyway.
_EPSILON = 1e-9


def _db(values: np.ndarray) -> list[float]:
    db = np.maximum(20.0 * np.log10(np.maximum(values, _EPSILON)), FLOOR_DB)
    return [float(v) for v in db]


class LevelWindows:
    """Splits mono float32 PCM into 50 ms windows of `(rms_db, peak_db)`.

    One per session: the daemon makes a fresh one at each start, so no tail
    carries from one dictation into the next.
    """

    def __init__(self, sample_rate: int) -> None:
        self._size = max(1, round(sample_rate * WINDOW_S))
        self._carry = np.empty(0, dtype=np.float32)

    def feed(self, pcm: np.ndarray) -> list[tuple[float, float]]:
        """The levels of every window completed by `pcm`, oldest first."""
        samples = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if self._carry.size:
            samples = np.concatenate((self._carry, samples))
        whole = samples.size // self._size
        self._carry = samples[whole * self._size :].copy()
        if whole == 0:
            return []
        windows = samples[: whole * self._size].reshape(whole, self._size)
        # float64 for the mean of squares: float32 loses precision on long
        # windows of quiet audio, and the arrays here are tiny.
        rms = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
        peak = np.max(np.abs(windows), axis=1)
        return list(zip(_db(rms), _db(peak), strict=True))
