import threading
from collections.abc import Callable
from concurrent.futures import Future

import numpy as np
import pytest

from flowd.hybrid import HybridSttEngine
from flowd.stt import Committed, Event, Partial

RATE = 16000
BLOCK = RATE // 10  # 100 ms


def speech(seconds: float) -> list[np.ndarray]:
    """Loud blocks, about -23 dBFS."""
    return [np.full(BLOCK, 0.07, dtype=np.float32) for _ in range(round(seconds * 10))]


def quiet(seconds: float) -> list[np.ndarray]:
    """Near-silent blocks, about -60 dBFS."""
    return [np.full(BLOCK, 0.001, dtype=np.float32) for _ in range(round(seconds * 10))]


class Live:
    """Stands in for Moonshine: one scripted word per fed block, committed on request."""

    def __init__(self) -> None:
        self.fed = 0
        self.words: list[str] = []
        self.finalized = False
        self.was_reset = False
        self.keyterms: list[str] | None = None

    def feed(self, pcm: np.ndarray) -> list[Event]:
        self.fed += 1
        self.words.append(f"w{self.fed}")
        # Moonshine commits some of its own text; the hybrid must not pass it on.
        if self.fed % 5 == 0:
            return [Committed(" ".join(self.words[-5:])), Partial("")]
        return [Partial(" ".join(self.words[-(self.fed % 5) :]))]

    def finalize(self) -> list[Event]:
        self.finalized = True
        tail = self.words[len(self.words) - self.fed % 5 :] if self.fed % 5 else []
        return [Committed(" ".join(tail))] if tail else []

    def reset(self) -> None:
        self.was_reset = True

    def set_keyterms(self, terms: list[str]) -> None:
        self.keyterms = list(terms)


class Now:
    """An executor that runs work at submit, so tests are deterministic."""

    def submit(self, fn: Callable[..., str], *args: object) -> "Future[str]":
        future: Future[str] = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


def seconds_of(pcm: np.ndarray) -> str:
    return f"piece {pcm.size / RATE:.1f}s"


def engine(
    transcribe: Callable[[np.ndarray], str] = seconds_of, live: Live | None = None, **kw: object
) -> tuple[HybridSttEngine, Live]:
    live = live or Live()
    return HybridSttEngine(live, transcribe, sample_rate=RATE, executor=Now(), **kw), live  # type: ignore[arg-type]


def feed_all(e: HybridSttEngine, blocks: list[np.ndarray]) -> list[Event]:
    out: list[Event] = []
    for block in blocks:
        out.extend(e.feed(block))
    return out


def commits(events: list[Event]) -> list[str]:
    return [ev.text for ev in events if isinstance(ev, Committed)]


def test_a_short_dictation_is_transcribed_whole_at_finalize() -> None:
    e, live = engine()
    during = feed_all(e, speech(3) + quiet(0.5) + speech(2))
    assert commits(during) == []
    assert commits(e.finalize()) == ["piece 5.5s"]
    # Reset, not finalized: its tail is not wanted, and finalizing it would
    # make the user wait for Moonshine to decode its backlog.
    assert live.was_reset
    assert not live.finalized


def test_moonshine_commits_never_reach_the_session() -> None:
    e, _ = engine(transcribe=lambda pcm: "accurate")
    events = feed_all(e, speech(2)) + e.finalize()
    assert commits(events) == ["accurate"]


def test_the_preview_shows_the_live_transcript() -> None:
    e, _ = engine()
    events = feed_all(e, speech(0.7))
    partials = [ev.text for ev in events if isinstance(ev, Partial)]
    assert partials[-1] == "w1 w2 w3 w4 w5 w6 w7"


def test_a_pause_after_enough_speech_commits_that_piece_while_recording() -> None:
    e, _ = engine()
    during = feed_all(e, speech(9) + quiet(1) + speech(2))
    assert commits(during) == ["piece 9.6s"]
    assert commits(e.finalize()) == ["piece 2.4s"]


def test_a_pause_too_early_in_a_piece_does_not_cut_it() -> None:
    e, _ = engine()
    during = feed_all(e, speech(3) + quiet(1) + speech(3))
    assert commits(during) == []
    assert commits(e.finalize()) == ["piece 7.0s"]


def test_unbroken_speech_is_cut_at_the_quietest_moment_before_the_limit() -> None:
    e, _ = engine()
    dip = [np.full(BLOCK, 0.02, dtype=np.float32)]
    during = feed_all(e, speech(18) + dip + speech(5))
    # Cut after the dip at 18.1 s, not mid-word at 20 s.
    assert commits(during) == ["piece 18.1s"]
    assert commits(e.finalize()) == ["piece 5.0s"]


def test_the_preview_drops_words_already_committed() -> None:
    e, _ = engine()
    events = feed_all(e, speech(9) + quiet(1) + speech(0.3))
    partials = [ev.text for ev in events if isinstance(ev, Partial)]
    # The cut came at block 96, so the live words from 97 on are the next piece.
    assert partials[-1] == "w97 w98 w99 w100 w101 w102 w103"


def test_silence_commits_nothing() -> None:
    e, _ = engine(transcribe=lambda pcm: "")
    feed_all(e, quiet(12))
    assert commits(e.finalize()) == []


def test_finalize_without_audio_is_empty() -> None:
    e, _ = engine()
    assert e.finalize() == []


def test_a_failed_piece_falls_back_to_the_live_text(caplog: pytest.LogCaptureFixture) -> None:
    def broken(pcm: np.ndarray) -> str:
        raise RuntimeError("decoder crashed")

    e, _ = engine(transcribe=broken)
    feed_all(e, speech(0.4))
    with caplog.at_level("WARNING"):
        assert commits(e.finalize()) == ["w1 w2 w3 w4"]
    assert any("decoder crashed" in r.getMessage() for r in caplog.records)


def test_reset_discards_the_session_and_its_pieces() -> None:
    e, live = engine()
    feed_all(e, speech(9) + quiet(0.5))
    e.reset()
    assert live.was_reset
    assert e.finalize() == []
    feed_all(e, speech(1))
    assert commits(e.finalize()) == ["piece 1.0s"]


def test_a_new_session_starts_clean_after_finalize() -> None:
    e, _ = engine()
    feed_all(e, speech(2))
    e.finalize()
    feed_all(e, speech(1))
    assert commits(e.finalize()) == ["piece 1.0s"]


def test_keyterms_go_to_the_live_model() -> None:
    e, live = engine()
    e.set_keyterms(["flowd"])
    assert live.keyterms == ["flowd"]


def test_pieces_decode_off_the_feeding_thread_and_commit_in_order() -> None:
    gate = threading.Event()
    seen: list[str] = []

    def slow(pcm: np.ndarray) -> str:
        seen.append(threading.current_thread().name)
        gate.wait(5)
        return seconds_of(pcm)

    e = HybridSttEngine(Live(), slow, sample_rate=RATE)  # type: ignore[arg-type]
    during = feed_all(e, speech(9) + quiet(1) + speech(9) + quiet(1))
    # The first piece is still decoding, so nothing is committed yet and
    # feeding carried on regardless.
    assert commits(during) == []
    gate.set()
    # The trailing 0.4 s of quiet is decoded too: judging a piece silent by
    # level alone would drop a quiet speaker's words.
    assert commits(e.finalize()) == ["piece 9.6s", "piece 10.0s", "piece 0.4s"]
    assert threading.current_thread().name not in seen


def test_each_session_hands_its_decode_memory_back() -> None:
    """glibc keeps freed decode buffers, ~250 MB after a 70 s dictation (ADR 0011)."""
    trims: list[str] = []
    e = HybridSttEngine(
        Live(), seconds_of, sample_rate=RATE, executor=Now(), trim=lambda: trims.append("t")
    )  # type: ignore[arg-type]
    feed_all(e, speech(1))
    e.finalize()
    feed_all(e, speech(1))
    e.reset()
    assert trims == ["t", "t"]
