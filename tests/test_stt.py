from dataclasses import dataclass

import numpy as np
import pytest

from flowd.stt import (
    BatchSttEngine,
    Committed,
    FakeSttEngine,
    Partial,
    _split_model_name,
    _transcript_text,
)


def test_fake_engine_emits_scripted_events() -> None:
    engine = FakeSttEngine([[Partial("hello")], [Committed("hello there")]])
    assert engine.feed(np.zeros(160, dtype=np.float32)) == [Partial("hello")]
    assert engine.feed(np.zeros(160, dtype=np.float32)) == [Committed("hello there")]
    assert engine.feed(np.zeros(160, dtype=np.float32)) == []


def test_fake_engine_finalize_drains_the_unplayed_script() -> None:
    """Release can arrive before every scripted block was fed."""
    engine = FakeSttEngine([[Partial("a")], [Partial("b")], [Committed("a b")]])
    engine.feed(np.zeros(1, dtype=np.float32))
    assert engine.finalize() == [Partial("b"), Committed("a b")]
    assert engine.finalize() == []


def test_batch_engine_buffers_until_finalize() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: f"{pcm.size} frames")
    assert engine.feed(np.zeros(100, dtype=np.float32)) == []
    assert engine.feed(np.zeros(60, dtype=np.float32)) == []
    assert engine.finalize() == [Committed("160 frames")]


def test_batch_engine_finalize_with_no_audio_emits_nothing() -> None:
    """A hotkey press with no speech must not produce a bogus commit."""
    engine = BatchSttEngine(transcribe=lambda pcm: "should not be called")
    assert engine.finalize() == []


def test_batch_engine_ignores_empty_transcription() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: "   ")
    engine.feed(np.zeros(100, dtype=np.float32))
    assert engine.finalize() == []


def test_batch_engine_resets_after_finalize() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: f"{pcm.size}")
    engine.feed(np.zeros(100, dtype=np.float32))
    engine.finalize()
    engine.feed(np.zeros(50, dtype=np.float32))
    assert engine.finalize() == [Committed("50")]


def test_batch_engine_preserves_frame_order_across_feeds() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: ",".join(str(int(v)) for v in pcm))
    engine.feed(np.array([1, 2], dtype=np.float32))
    engine.feed(np.array([3], dtype=np.float32))
    assert engine.finalize() == [Committed("1,2,3")]


def test_events_are_comparable_and_frozen() -> None:
    assert Partial("a") == Partial("a")
    assert Partial("a") != Committed("a")


@dataclass
class FakeLine:
    text: str


@dataclass
class FakeTranscript:
    lines: list[FakeLine]


def test_transcript_text_joins_lines_without_timestamps() -> None:
    """`str(Transcript)` renders "[0.00s] text", which must never be dictated.

    Moonshine's own __str__ prefixes every line with its start time. Reading
    `.text` per line is the only way to get the words alone.
    """
    transcript = FakeTranscript([FakeLine("hello there"), FakeLine("how are you")])
    assert _transcript_text(transcript) == "hello there how are you"


def test_transcript_text_handles_no_lines() -> None:
    assert _transcript_text(FakeTranscript([])) == ""


def test_transcript_text_ignores_blank_lines() -> None:
    transcript = FakeTranscript([FakeLine("hello"), FakeLine("   "), FakeLine("there")])
    assert _transcript_text(transcript) == "hello there"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("medium-streaming-en", ("medium-streaming", "en")),
        ("small-streaming-en", ("small-streaming", "en")),
        ("tiny-streaming-en", ("tiny-streaming", "en")),
        ("base-en", ("base", "en")),
        ("tiny-es", ("tiny", "es")),
        # No language suffix: the arch alone, defaulting to English.
        ("medium-streaming", ("medium-streaming", "en")),
        ("base", ("base", "en")),
    ],
)
def test_split_model_name(configured: str, expected: tuple[str, str]) -> None:
    """`stt.model` names a model directory; Moonshine wants arch and language apart.

    The spec's default is "medium-streaming-en", but the architecture string
    Moonshine accepts is "medium-streaming" — passing the whole name raises
    `ValueError: Invalid model architecture string`.
    """
    assert _split_model_name(configured) == expected


def test_every_split_arch_is_one_moonshine_accepts() -> None:
    """Guards against a rename in either the config defaults or Moonshine."""
    from moonshine_voice import string_to_model_arch

    for name in ("medium-streaming-en", "small-streaming-en", "base-en", "tiny-en"):
        arch, _ = _split_model_name(name)
        assert string_to_model_arch(arch) is not None
