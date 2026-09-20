"""Phase 4: the single-flight chunk scheduler (spec 6.2-6.5)."""

import asyncio

import pytest

from flowd.config import Chunking
from flowd.scheduler import Scheduler
from flowd.session import Session


class FakePolish:
    """Stands in for the daemon's LLM call. `hold` keeps each call open until released."""

    def __init__(self, hold: bool = False, fail: bool = False) -> None:
        self.hold = hold
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self.gates: list[asyncio.Event] = []

    async def __call__(
        self, raw: str, *, context: str, merged: bool, timeout_ms: int
    ) -> str | None:
        self.calls.append({"raw": raw, "context": context, "merged": merged, "timeout": timeout_ms})
        if self.hold:
            gate = asyncio.Event()
            self.gates.append(gate)
            await gate.wait()
        return None if self.fail else f"<{raw}>"

    def release(self) -> None:
        self.gates.pop(0).set()


def fallback(raw: str) -> str:
    return f"[{raw}]"


def make(polish: FakePolish, **chunking: object) -> tuple[Scheduler, Session]:
    session = Session(id="s")
    sched = Scheduler(session, polish, fallback, Chunking(**chunking), timeout_ms=2000)  # type: ignore[arg-type]
    return sched, session


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_small_commits_wait_until_min_chunk_words() -> None:
    polish = FakePolish()
    sched, _ = make(polish)
    sched.on_committed("so i was")
    await settle()
    assert polish.calls == []
    sched.on_committed("thinking we should")
    await settle()
    assert [c["raw"] for c in polish.calls] == ["so i was thinking we should"]


async def test_one_request_in_flight_and_the_backlog_goes_as_one_chunk() -> None:
    polish = FakePolish(hold=True)
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    sched.on_committed("six seven eight nine ten")
    sched.on_committed("eleven twelve thirteen fourteen fifteen")
    await settle()
    assert len(polish.calls) == 1
    polish.release()
    await settle()
    assert [c["raw"] for c in polish.calls][1] == (
        "six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    )
    assert session.chunks[0].state == "DONE"
    assert session.chunks[0].polished == "<one two three four five>"


async def test_recording_chunks_use_the_recording_timeout() -> None:
    polish = FakePolish()
    sched, _ = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    assert polish.calls[0]["timeout"] == 2000


async def test_a_failed_chunk_uses_the_fallback() -> None:
    polish = FakePolish(fail=True)
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    assert session.chunks[0].state == "FALLBACK"
    assert session.chunks[0].polished == "[one two three four five]"


async def test_a_correction_cue_merges_with_the_previous_resolved_chunk() -> None:
    polish = FakePolish()
    sched, session = make(polish)
    sched.on_committed("we should meet at five tomorrow")
    await settle()
    sched.on_committed("no wait six tomorrow is better")
    await settle()
    assert polish.calls[1]["raw"] == (
        "we should meet at five tomorrow no wait six tomorrow is better"
    )
    assert polish.calls[1]["merged"] is True
    assert polish.calls[0]["merged"] is False
    assert [c.state for c in session.chunks] == ["MERGED", "DONE"]
    assert [c.text for c in session.visible_chunks()] == [
        "<we should meet at five tomorrow no wait six tomorrow is better>"
    ]


async def test_a_cue_waits_for_an_inflight_chunk_then_merges() -> None:
    polish = FakePolish(hold=True)
    sched, session = make(polish)
    sched.on_committed("we should meet at five tomorrow")
    await settle()
    sched.on_committed("actually make it six please")
    await settle()
    assert len(polish.calls) == 1
    polish.release()
    await settle()
    assert polish.calls[1]["raw"] == "we should meet at five tomorrow actually make it six please"
    assert session.chunks[0].state == "MERGED"


async def test_a_merge_takes_at_most_one_previous_chunk() -> None:
    polish = FakePolish()
    sched, session = make(polish)
    sched.on_committed("first we deploy the api")
    await settle()
    sched.on_committed("then we run the migration")
    await settle()
    sched.on_committed("sorry the migration runs first")
    await settle()
    assert [c.state for c in session.chunks] == ["DONE", "MERGED", "DONE"]
    assert polish.calls[2]["raw"] == "then we run the migration sorry the migration runs first"


async def test_context_is_the_last_polished_sentences() -> None:
    polish = FakePolish()
    sched, session = make(polish, context_sentences=2)
    sched.on_committed("one two three four five")
    await settle()
    session.chunks[0].polished = "First one. Second one. Third one."
    sched.on_committed("six seven eight nine ten")
    await settle()
    assert polish.calls[0]["context"] == ""
    assert polish.calls[1]["context"] == "Second one. Third one."


async def test_flush_sends_a_remainder_below_min_chunk_words() -> None:
    polish = FakePolish()
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    sched.on_committed("thanks")
    await sched.flush(800)
    assert [c["raw"] for c in polish.calls] == ["one two three four five", "thanks"]
    assert all(c.resolved for c in session.chunks)
    assert polish.calls[1]["timeout"] <= 800


async def test_a_short_session_skips_the_llm() -> None:
    polish = FakePolish()
    sched, session = make(polish)
    sched.on_committed("hi there")
    await sched.flush(800)
    assert polish.calls == []
    assert sched.bypassed
    assert [c.text for c in session.chunks] == ["[hi there]"]


async def test_flush_waits_for_the_inflight_chunk_then_sends_the_rest() -> None:
    polish = FakePolish(hold=True)
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    sched.on_committed("and the rest")

    async def release_both() -> None:
        await settle()
        polish.release()
        await settle()
        polish.release()

    releaser = asyncio.create_task(release_both())
    await sched.flush(800)
    await releaser
    assert [c.text for c in session.visible_chunks()] == [
        "<one two three four five>",
        "<and the rest>",
    ]
    assert sched.abandoned == 0


async def test_the_flush_deadline_falls_back_whatever_is_unresolved() -> None:
    polish = FakePolish(hold=True)
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    sched.on_committed("and the rest")
    await sched.flush(50)
    assert [c.text for c in session.visible_chunks()] == [
        "[one two three four five]",
        "[and the rest]",
    ]
    assert all(c.state == "FALLBACK" for c in session.chunks)
    assert sched.abandoned == 2


async def test_cancel_stops_the_inflight_request_and_ignores_later_commits() -> None:
    polish = FakePolish(hold=True)
    sched, session = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    sched.cancel()
    await settle()
    sched.on_committed("six seven eight nine ten")
    await settle()
    assert len(polish.calls) == 1
    assert session.chunks[0].state == "INFLIGHT"
    assert session.pending_raw == []


async def test_a_polish_that_raises_falls_back_instead_of_stranding_the_session() -> None:
    async def boom(raw: str, *, context: str, merged: bool, timeout_ms: int) -> str | None:
        raise RuntimeError("unexpected")

    session = Session(id="s")
    sched = Scheduler(session, boom, fallback, Chunking(), timeout_ms=2000)
    sched.on_committed("one two three four five")
    await sched.flush(800)
    assert session.chunks[0].state == "FALLBACK"


async def test_on_change_fires_when_a_chunk_resolves() -> None:
    seen: list[str] = []
    session = Session(id="s")
    sched = Scheduler(
        session,
        FakePolish(),
        fallback,
        Chunking(),
        timeout_ms=2000,
        on_change=lambda: seen.append(",".join(c.state for c in session.chunks)),
    )
    sched.on_committed("one two three four five")
    await settle()
    assert seen[-1] == "DONE"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("no wait make it six", True),
        ("Actually, six.", True),
        ("we actually need six", False),
        ("nowhere to go", False),
    ],
)
def test_starts_with_correction_cue(raw: str, expected: bool) -> None:
    from flowd.guardrails import starts_with_correction_cue

    assert starts_with_correction_cue(raw, Chunking().correction_cues) is expected


async def test_cancel_during_flush_returns_at_once() -> None:
    polish = FakePolish(hold=True)
    sched, _ = make(polish)
    sched.on_committed("one two three four five")
    await settle()
    loop = asyncio.get_running_loop()
    started = loop.time()
    flushing = asyncio.create_task(sched.flush(800))
    await settle()
    sched.cancel()
    await flushing
    assert loop.time() - started < 0.2
    assert sched.abandoned == 0
