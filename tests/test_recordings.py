"""Opt-in session recordings for testing the recognizer on a real voice."""

import json
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flowd.config import Config, Logging, load_config
from flowd.stt import Committed, FakeSttEngine
from tests.test_daemon import FakeCapture, daemon

TONE = (np.sin(np.arange(1600) / 5) * 0.5).astype(np.float32)


def recording(where: Path) -> Config:
    return replace(Config(), logging=replace(Logging(), recordings_dir=str(where)))


async def dictate(d: Any, stop: str = "stop") -> None:
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.pump()
    await d.handle({"cmd": stop})


def frames(path: Path) -> int:
    with wave.open(str(path)) as w:
        return w.getnframes()


async def test_nothing_is_recorded_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spec 13.2's rule for transcripts holds for audio too: off unless asked."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    d = daemon(FakeSttEngine([[Committed("hello there friend")]]), FakeCapture([TONE, TONE]))
    await dictate(d)
    assert list(tmp_path.rglob("*.wav")) == []


async def test_a_session_is_saved_as_16_bit_mono_wav_with_its_transcripts(tmp_path: Path) -> None:
    stt = FakeSttEngine([[Committed("hello there friend")]])
    d = daemon(stt, FakeCapture([TONE, TONE]), cfg=recording(tmp_path))
    await dictate(d)
    wavs = list(tmp_path.glob("*.wav"))
    assert len(wavs) == 1
    with wave.open(str(wavs[0])) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
    assert frames(wavs[0]) == 3200
    meta = json.loads(wavs[0].with_suffix(".json").read_text())
    assert meta["raw"] == "hello there friend"
    assert meta["text"] == "Hello there friend."
    assert meta["session"] == wavs[0].stem.split("_")[-1]


async def test_a_cancelled_session_is_not_saved(tmp_path: Path) -> None:
    """Cancel means discard everything (spec 9.1), the audio included."""
    stt = FakeSttEngine([[Committed("never mind")]])
    d = daemon(stt, FakeCapture([TONE]), cfg=recording(tmp_path))
    await dictate(d, stop="cancel")
    assert list(tmp_path.iterdir()) == []


async def test_a_failed_write_does_not_lose_the_dictation(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    injected: list[str] = []
    stt = FakeSttEngine([[Committed("keep this text")]])
    d = daemon(stt, FakeCapture([TONE]), injected, cfg=recording(blocker))
    await dictate(d)
    assert injected == ["Keep this text."]


async def test_a_new_session_starts_with_empty_audio(tmp_path: Path) -> None:
    capture = FakeCapture([TONE, TONE])
    d = daemon(FakeSttEngine([[Committed("first one here")]]), capture, cfg=recording(tmp_path))
    await dictate(d)
    d.stt = FakeSttEngine([[Committed("second one here")]])
    capture.blocks = [TONE]
    await dictate(d)
    assert sorted(frames(p) for p in tmp_path.glob("*.wav")) == [1600, 3200]


def test_recordings_dir_is_read_from_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[logging]\nrecordings_dir = "~/flowd-recordings"\n')
    assert load_config(path).logging.recordings_dir == "~/flowd-recordings"
