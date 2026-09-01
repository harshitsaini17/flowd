"""Tests for the streaming STT engine (spec 5.3, ADR 0001, ADR 0002).

The engine drives Moonshine's native streaming API, so the seam under test is
that API's shape: a stream that accepts audio and calls listeners with events
carrying a transcript line. `FakeStream` scripts those events per block, which
keeps every test deterministic and model-free (CONTRIBUTING.md: no models, no
hardware, no wall clock in the suite).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from flowd.committer import Committer
from flowd.stt import Committed, Partial, StreamingSttEngine
from flowd.vad import SegmentationVad

BLOCK = np.zeros(1600, dtype=np.float32)


@dataclass
class FakeLine:
    """A Moonshine `TranscriptLine`, reduced to the fields the engine reads."""

    text: str
    line_id: int = 0
    start_time: float = 0.0
    duration: float = 0.0
    is_complete: bool = False


@dataclass
class FakeEvent:
    line: FakeLine


@dataclass
class FakeStream:
    """Scripts one list of line events per `add_audio` call.

    Events fire synchronously from inside `add_audio`, which is what the real
    stream does: verified against `moonshine-voice` 0.1.5, where every listener
    callback arrived on the calling thread before `add_audio` returned.
    """

    script: list[list[FakeLine]] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    index: int = 0
    _listeners: list[object] = field(default_factory=list)

    def add_listener(self, fn: object) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        self.started = True

    def add_audio(self, pcm: object, sample_rate: int) -> None:
        lines = self.script[self.index] if self.index < len(self.script) else []
        self.index += 1
        for line in lines:
            for fn in self._listeners:
                fn(FakeEvent(line))  # type: ignore[operator]

    def stop(self) -> None:
        self.stopped = True


def engine(
    script: list[list[FakeLine]],
    *,
    max_uncommitted_words: int = 25,
    commit_silence_ms: int = 350,
    lag_allowance_ms: int = 300,
) -> tuple[StreamingSttEngine, FakeStream]:
    stream = FakeStream(script=script)
    e = StreamingSttEngine(
        new_stream=lambda: stream,
        vad=SegmentationVad(block_ms=100, lag_allowance_ms=lag_allowance_ms),
        committer=Committer(
            max_uncommitted_words=max_uncommitted_words,
            commit_silence_ms=commit_silence_ms,
        ),
        block_ms=100,
        sample_rate=16000,
    )
    return e, stream


def line(text: str, *, end_s: float, complete: bool = False, line_id: int = 0) -> FakeLine:
    """A line ending at `end_s` seconds of session audio."""
    return FakeLine(text=text, line_id=line_id, duration=end_s, is_complete=complete)


def test_the_stream_is_started_once_and_listened_to() -> None:
    e, stream = engine([[], []])
    assert stream.started is False  # nothing opened before the first block
    e.feed(BLOCK)
    assert stream.started is True
    assert stream._listeners  # the engine registered itself
    e.feed(BLOCK)
    assert stream.started is True  # not restarted per block


def test_emits_partial_as_hypothesis_grows() -> None:
    e, _ = engine(
        [
            [line("hello", end_s=0.1)],
            [line("hello there", end_s=0.2)],
        ]
    )
    assert e.feed(BLOCK) == [Partial("hello")]
    assert e.feed(BLOCK) == [Partial("hello there")]


def test_unchanged_hypothesis_emits_nothing() -> None:
    e, _ = engine(
        [
            [line("hello", end_s=0.1)],
            [line("hello", end_s=0.2)],
        ]
    )
    e.feed(BLOCK)
    assert e.feed(BLOCK) == []


def test_a_block_with_no_events_emits_nothing() -> None:
    """Most blocks produce no event: Moonshine updates every ~300 ms."""
    e, _ = engine([[], [], []])
    assert e.feed(BLOCK) == []
    assert e.feed(BLOCK) == []


def test_a_completed_line_commits_it() -> None:
    """ADR 0001: `LineCompleted` is the authoritative commit signal."""
    e, _ = engine(
        [
            [line("hello there", end_s=0.1)],
            [line("hello there friend", end_s=0.2, complete=True)],
        ]
    )
    e.feed(BLOCK)
    assert e.feed(BLOCK) == [Committed("hello there friend")]


def test_committed_text_is_not_repeated_in_later_partials() -> None:
    """Each line carries its own segment's text, and the engine joins them.

    The committer wants the whole utterance (it strips the committed prefix by
    word count), but Moonshine reports per-segment lines — ADR 0001's
    `_transcript_text` joins `line.text` across lines for exactly this reason.
    So a second line's text is "three", not "one two three".
    """
    e, _ = engine(
        [
            [line("one two", end_s=0.1, complete=True)],
            [line("three", end_s=0.2, line_id=1)],
        ]
    )
    assert e.feed(BLOCK) == [Committed("one two")]
    assert e.feed(BLOCK) == [Partial("three")]


def test_silence_commits_what_the_engine_had_not_completed() -> None:
    """spec 5.4 rule 2, on the signal ADR 0002 derives from segmentation.

    The frontier stops at 100 ms while blocks keep arriving, so the gap grows
    past the 300 ms allowance and then accrues `commit_silence_ms` of silence.
    """
    e, _ = engine([[line("half a sentence", end_s=0.1)]])
    assert e.feed(BLOCK) == [Partial("half a sentence")]
    events: list[object] = []
    for _ in range(8):
        events.extend(e.feed(BLOCK))
    assert Committed("half a sentence") in events


def test_no_speech_at_all_emits_nothing() -> None:
    """spec 5.5: a session with no speech must inject nothing."""
    e, _ = engine([[], [], [], [], [], []])
    events: list[object] = []
    for _ in range(6):
        events.extend(e.feed(BLOCK))
    assert events == []


def test_finalize_commits_the_remainder_and_stops_the_stream() -> None:
    e, stream = engine([[line("trailing words", end_s=0.1)]])
    e.feed(BLOCK)
    assert e.finalize() == [Committed("trailing words")]
    assert stream.stopped is True


def test_finalize_twice_is_safe() -> None:
    e, _ = engine([[line("words here", end_s=0.1)]])
    e.feed(BLOCK)
    e.finalize()
    assert e.finalize() == []


def test_finalize_with_no_audio_emits_nothing() -> None:
    e, _ = engine([])
    assert e.finalize() == []


def test_finalize_flushes_events_the_stream_emits_on_stop() -> None:
    """`stop()` emitted nothing on this version, but the engine reads what it
    does emit rather than assuming: a flush-on-stop in a later release would
    otherwise drop the last words of every session."""
    e, stream = engine([[]])
    e.feed(BLOCK)  # opens the stream; no events yet

    original_stop = stream.stop
    stream.script = [[line("late arrival", end_s=0.1)]]
    stream.index = 0

    def stop_then_emit() -> None:
        original_stop()
        stream.add_audio(BLOCK, 16000)

    stream.stop = stop_then_emit  # type: ignore[method-assign]
    assert e.finalize() == [Committed("late arrival")]


def test_empty_block_is_ignored() -> None:
    e, stream = engine([[line("hello", end_s=0.1)]])
    assert e.feed(np.empty(0, dtype=np.float32)) == []
    assert stream.index == 0  # nothing was fed to the stream


def test_a_commit_and_a_new_partial_in_one_block_keep_their_order() -> None:
    """Committed text must reach the target app before the partial that follows
    it reaches the overlay, or the preview would show text already typed."""
    e, _ = engine(
        [
            [
                line("first part", end_s=0.1, complete=True),
                line("second", end_s=0.2, line_id=1),
            ]
        ]
    )
    assert e.feed(BLOCK) == [Committed("first part"), Partial("second")]


def test_a_later_line_is_not_committed_by_an_earlier_line_completing() -> None:
    """Completion commits up to that line, not everything provisional after it."""
    e, _ = engine(
        [
            [
                line("done bit", end_s=0.1, line_id=0, complete=True),
                line("still moving", end_s=0.2, line_id=1),
            ]
        ]
    )
    events = e.feed(BLOCK)
    assert Committed("done bit") in events
    assert Partial("still moving") in events
    assert Committed("done bit still moving") not in events


def test_the_stable_prefix_rule_still_applies_during_long_speech() -> None:
    """spec 5.4 rule 3 is the engine's own backstop: neither a completion nor a
    pause has happened, and the uncommitted text is past the cap."""
    words = "one two three four five six"
    e, _ = engine(
        [
            [line(words, end_s=0.1)],
            [line(words + " seven", end_s=0.2)],
            [line(words + " seven eight", end_s=0.3)],
        ],
        max_uncommitted_words=5,
    )
    events: list[object] = []
    for _ in range(3):
        events.extend(e.feed(BLOCK))
    assert any(isinstance(ev, Committed) for ev in events)


def test_a_revised_line_updates_rather_than_duplicates() -> None:
    """Moonshine revises a line in place; the same line_id is not new text."""
    e, _ = engine(
        [
            [line("send it to john", end_s=0.1)],
            [line("send it to sarah", end_s=0.2)],
        ]
    )
    assert e.feed(BLOCK) == [Partial("send it to john")]
    assert e.feed(BLOCK) == [Partial("send it to sarah")]


def test_the_frontier_drives_the_vad() -> None:
    """ADR 0002: line end times are the only speech signal available."""
    e, _ = engine([[line("speaking", end_s=1.0)]], lag_allowance_ms=300)
    e.feed(BLOCK)  # frontier 1000 ms, fed 100 ms
    for _ in range(9):  # fed catches up to 1000 ms; gap stays inside allowance
        assert all(not isinstance(ev, Committed) for ev in e.feed(BLOCK))


def _reusable() -> tuple[StreamingSttEngine, list[FakeStream]]:
    """An engine that builds a fresh stream per session, as the real one does."""
    made: list[FakeStream] = []

    def make_stream() -> FakeStream:
        stream = FakeStream(script=[[line(f"session {len(made) + 1}", end_s=0.1)]])
        made.append(stream)
        return stream

    e = StreamingSttEngine(
        new_stream=make_stream,
        vad=SegmentationVad(block_ms=100, lag_allowance_ms=300),
        committer=Committer(),
        block_ms=100,
        sample_rate=16000,
    )
    return e, made


def test_a_new_session_gets_a_fresh_stream_after_finalize() -> None:
    """The daemon loads the model once and reuses the engine (spec 5.3), but a
    Moonshine stream accumulates one transcript, so each session needs its own.

    The engine rebuilds it lazily on the next `feed` rather than making the
    daemon ask, which keeps the `SttEngine` protocol unchanged.
    """
    e, made = _reusable()
    assert e.feed(BLOCK) == [Partial("session 1")]
    assert e.finalize() == [Committed("session 1")]
    assert made[0].stopped is True
    assert e.feed(BLOCK) == [Partial("session 2")]
    assert len(made) == 2


def test_reset_discards_a_session_without_committing_it() -> None:
    """spec 9.4's cancel: the audio and the transcript go, nothing is injected."""
    e, made = _reusable()
    e.feed(BLOCK)
    e.reset()
    assert made[0].stopped is True
    assert e.finalize() == []
    assert e.feed(BLOCK) == [Partial("session 2")]


def test_the_stream_is_built_lazily_so_loading_opens_nothing() -> None:
    """`load_engine` runs at daemon start; a stream opened there would be live
    for every session that never happens."""
    e, made = _reusable()
    assert made == []
    e.feed(BLOCK)
    assert len(made) == 1
