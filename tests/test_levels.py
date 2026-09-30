import numpy as np
import pytest

from flowd.levels import FLOOR_DB, LevelWindows


def test_silence_is_the_floor() -> None:
    assert LevelWindows(16000).feed(np.zeros(1600, np.float32)) == [(FLOOR_DB, FLOOR_DB)] * 2


def test_a_full_scale_sine_is_about_minus_3_db_rms_and_0_peak() -> None:
    t = np.arange(800) / 16000
    ((rms, peak),) = LevelWindows(16000).feed(np.sin(2 * np.pi * 440 * t).astype(np.float32))
    assert rms == pytest.approx(-3.01, abs=0.1)
    assert peak == pytest.approx(0.0, abs=0.1)


def test_a_partial_window_is_carried_to_the_next_block() -> None:
    w = LevelWindows(16000)
    assert w.feed(np.zeros(500, np.float32)) == []
    assert len(w.feed(np.zeros(300, np.float32))) == 1


def test_an_empty_block_yields_nothing() -> None:
    assert LevelWindows(16000).feed(np.empty(0, np.float32)) == []


def test_a_window_spanning_two_blocks_measures_both() -> None:
    """The carried tail counts: half a window at full scale, half silent."""
    w = LevelWindows(16000)
    w.feed(np.ones(400, np.float32))
    ((rms, peak),) = w.feed(np.zeros(400, np.float32))
    assert rms == pytest.approx(-3.01, abs=0.1)
    assert peak == pytest.approx(0.0, abs=0.01)
