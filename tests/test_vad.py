"""Tests for speech/silence tracking (spec 5.2, ADR 0002)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from flowd.config import Vad
from flowd.vad import FakeVad, SegmentationVad, SilenceTracker, VadFrame, load_vad

BLOCK = np.zeros(1600, dtype=np.float32)


def test_silence_tracker_counts_consecutive_silence() -> None:
    tracker = SilenceTracker(block_ms=100)
    assert tracker.update(speech=True) == 0
    assert tracker.update(speech=False) == 100
    assert tracker.update(speech=False) == 200
    assert tracker.update(speech=False) == 300


def test_silence_tracker_resets_on_speech() -> None:
    tracker = SilenceTracker(block_ms=100)
    tracker.update(speech=False)
    tracker.update(speech=False)
    assert tracker.update(speech=True) == 0
    assert tracker.update(speech=False) == 100


def test_silence_tracker_starts_at_zero() -> None:
    assert SilenceTracker(block_ms=100).silence_ms == 0


def test_silence_tracker_honours_block_size() -> None:
    tracker = SilenceTracker(block_ms=30)
    tracker.update(speech=False)
    assert tracker.update(speech=False) == 60


def test_fake_vad_reports_scripted_frames() -> None:
    vad = FakeVad([True, True, False], block_ms=100)
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)
    assert vad.process(BLOCK) == VadFrame(speech=False, silence_ms=100)


def test_fake_vad_treats_exhausted_script_as_silence() -> None:
    vad = FakeVad([True], block_ms=100)
    vad.process(BLOCK)
    assert vad.process(BLOCK).speech is False


def test_reset_clears_silence_run() -> None:
    vad = FakeVad([False, False], block_ms=100)
    vad.process(BLOCK)
    vad.reset()
    assert vad.process(BLOCK).silence_ms == 100


# --- SegmentationVad: speech derived from Moonshine's own segments (ADR 0002) ---


def test_leading_audio_is_silence_until_a_segment_appears() -> None:
    """Nothing has been segmented as speech yet, so nothing is speech yet.

    spec 5.5's "no speech at all" case depends on this: if the engine reported
    speech before Moonshine had recognised any, every silent session would
    inject the empty string instead of reporting "No speech".
    """
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    assert vad.process(BLOCK).speech is False
    assert vad.process(BLOCK).speech is False
    assert vad.saw_speech is False


def test_an_advancing_frontier_reads_as_speech() -> None:
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    vad.observe_frontier(1000.0)
    for _ in range(10):  # fed time catches up to 1000 ms
        assert vad.process(BLOCK).speech is True
    assert vad.saw_speech is True


def test_silence_accrues_once_the_frontier_stops_advancing() -> None:
    """The gap between fed audio and the transcript frontier is the signal.

    A frontier that stops moving while audio keeps arriving is the only silence
    evidence Moonshine exposes (ADR 0001 Q3): the embedded detector's verdict is
    not queryable, so flowd infers it from what the detector segmented.
    """
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    vad.observe_frontier(500.0)
    for _ in range(5):  # fed 500 ms, frontier 500 ms: within allowance
        assert vad.process(BLOCK).speech is True
    # Frontier frozen at 500 ms. The allowance absorbs 300 ms of lag first.
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)  # gap 100
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)  # gap 200
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)  # gap 300
    assert vad.process(BLOCK) == VadFrame(speech=False, silence_ms=100)  # gap 400
    assert vad.process(BLOCK) == VadFrame(speech=False, silence_ms=200)


def test_a_late_frontier_update_clears_the_silence_run() -> None:
    """Transcription lag must not be mistaken for a pause.

    Measured on this machine, a line's frontier can trail the audio already fed
    by up to 576 ms (ADR 0002). When the late event finally arrives, the silence
    it appeared to prove never happened.
    """
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    vad.observe_frontier(200.0)
    for _ in range(8):
        vad.process(BLOCK)
    assert vad.process(BLOCK).silence_ms > 0
    vad.observe_frontier(900.0)
    assert vad.process(BLOCK) == VadFrame(speech=True, silence_ms=0)


def test_the_frontier_never_moves_backwards() -> None:
    """Lines are revised, and a revision can shorten the one being revised."""
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    vad.observe_frontier(900.0)
    vad.observe_frontier(400.0)
    for _ in range(9):
        assert vad.process(BLOCK).speech is True


def test_reset_forgets_the_session() -> None:
    vad = SegmentationVad(block_ms=100, lag_allowance_ms=300)
    vad.observe_frontier(1000.0)
    vad.process(BLOCK)
    vad.reset()
    assert vad.saw_speech is False
    assert vad.process(BLOCK).speech is False


def test_load_vad_returns_a_segmentation_engine_needing_no_model_file(tmp_path: Path) -> None:
    """ADR 0001/0002: the detector is inside libmoonshine.so, so there is no
    model file to find and an empty model directory is not an error."""
    vad = load_vad(Vad(), tmp_path, block_ms=100)
    assert isinstance(vad, SegmentationVad)
    assert list(tmp_path.iterdir()) == []


def test_the_default_allowance_clears_the_measured_lag() -> None:
    """The default is measured, and this test is what stops it drifting.

    ADR 0002 swept it against a real 44s stream: at 500 ms, six stretches of
    continuously loud audio accrued more than `commit_silence_ms` of silence and
    would each have committed mid-phrase. At 900 ms only the clip's two real
    pauses remained. A default below the observed lag makes the engine invent
    pauses, so it must stay above it with room to spare.
    """
    assert Vad().lag_allowance_ms == 900
    assert Vad().lag_allowance_ms > 576  # worst single-event lag measured


def test_load_vad_takes_its_allowance_from_config(tmp_path: Path) -> None:
    vad = load_vad(Vad(lag_allowance_ms=750), tmp_path, block_ms=100)
    assert isinstance(vad, SegmentationVad)
    vad.observe_frontier(100.0)
    for _ in range(8):  # gap reaches 700 ms, still inside a 750 ms allowance
        assert vad.process(BLOCK).speech is True


@pytest.mark.parametrize("module", ["flowd.vad", "flowd.stt", "flowd.daemon"])
def test_nothing_imports_onnxruntime(module: str) -> None:
    """ADR 0002 drops the `onnxruntime` dependency; this is the proof.

    Moonshine links its own ONNX runtime into `libmoonshine.so` and imports
    neither `onnx` nor `onnxruntime`, and with the separate Silero model gone
    nothing else wanted it. A fresh interpreter is used because an earlier test
    in the same process could have imported it for some other reason.
    """
    code = f"import {module}, sys; sys.exit(1 if 'onnxruntime' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_onnxruntime_is_not_a_declared_dependency() -> None:
    """The declared dependency list, not the file text: pyproject carries a
    comment saying why `onnxruntime` is absent, and that comment is the point."""
    root = Path(__file__).resolve().parent.parent
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    declared = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)
    assert not [d for d in declared if "onnxruntime" in d], declared
