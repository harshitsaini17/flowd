"""Optional full-rewrite mode (spec 6.6, ADR 0010)."""

from typing import Any

from flowd.cleanup import CleanupResult
from flowd.config import Config, Hotkey
from flowd.daemon import REWRITE_MAX_WORDS
from tests.test_daemon_cleanup import LONG_CLEAN, LONG_RAW, FakeCleanup, make


class ScriptedCleanup(FakeCleanup):
    """Returns one scripted output per call, in order."""

    def __init__(self, outputs: list[str | None]) -> None:
        super().__init__()
        self.outputs = outputs

    async def clean(self, raw: str, timeout_ms: int) -> CleanupResult:
        self.calls.append((raw, timeout_ms))
        text = self.outputs.pop(0)
        return CleanupResult(text, None if text is not None else "timeout")


CFG = Config(hotkey=Hotkey(debounce_ms=0))


async def dictate(d: Any, **stop: Any) -> dict[str, Any]:
    await d.handle({"cmd": "start"})
    await d.pump()
    return dict(await d.handle({"cmd": "stop", **stop}))


async def test_without_the_flag_there_is_no_second_pass() -> None:
    injected: list[str] = []
    cleanup = ScriptedCleanup([LONG_CLEAN])
    await dictate(make(LONG_RAW, cleanup, injected, cfg=CFG))
    assert len(cleanup.calls) == 1
    assert injected == [LONG_CLEAN]


async def test_stop_rewrite_sends_the_joined_text_through_one_more_pass() -> None:
    injected: list[str] = []
    rewritten = "I think we should ship the release on Friday."
    cleanup = ScriptedCleanup([LONG_CLEAN, rewritten])
    d = make(LONG_RAW, cleanup, injected, cfg=CFG)
    reply = await dictate(d, rewrite=True)
    assert cleanup.calls[1][0] == LONG_CLEAN
    assert injected == [rewritten]
    assert reply["rewrite"] == "accepted"
    assert d.last_record["counts"]["rewrite_accepted"] == 1


async def test_a_rewrite_that_fails_the_guardrails_keeps_the_joined_text() -> None:
    injected: list[str] = []
    invented = "Sure! Here is a plan: ship the release on Friday and tell the whole team."
    cleanup = ScriptedCleanup([LONG_CLEAN, invented])
    d = make(LONG_RAW, cleanup, injected, cfg=CFG)
    reply = await dictate(d, rewrite=True)
    assert injected == [LONG_CLEAN]
    assert reply["rewrite"] == "rejected"


async def test_a_rewrite_that_times_out_keeps_the_joined_text() -> None:
    injected: list[str] = []
    cleanup = ScriptedCleanup([LONG_CLEAN, None])
    reply = await dictate(make(LONG_RAW, cleanup, injected, cfg=CFG), rewrite=True)
    assert injected == [LONG_CLEAN]
    assert reply["rewrite"] == "failed"


async def test_text_over_the_word_limit_is_not_rewritten() -> None:
    """spec 6.6: the whole joined text, ≤ 300 words."""
    injected: list[str] = []
    # Distinct words: `basic_clean` collapses repeats, which would shrink it.
    raw = " ".join(f"w{i}" for i in range(REWRITE_MAX_WORDS + 1))
    cleanup = ScriptedCleanup([None] * 50)
    d = make(raw, cleanup, injected, cfg=CFG)
    reply = await dictate(d, rewrite=True)
    assert reply["rewrite"] == "skipped"
    # Only the chunk pass ran; no call carried the whole joined text again.
    assert len(cleanup.calls) == 1


async def test_toggle_rewrite_while_recording_rewrites_too() -> None:
    injected: list[str] = []
    rewritten = "I think we should ship the release on Friday."
    cleanup = ScriptedCleanup([LONG_CLEAN, rewritten])
    d = make(LONG_RAW, cleanup, injected, cfg=CFG)
    await d.handle({"cmd": "toggle"})
    await d.pump()
    await d.handle({"cmd": "toggle", "rewrite": True})
    assert injected == [rewritten]


async def test_code_mode_never_rewrites() -> None:
    """Code mode skips the LLM (ADR 0009); a rewrite would undo that."""
    from flowd.context import AppContext

    injected: list[str] = []
    cleanup = ScriptedCleanup([])
    d = make("git status short", cleanup, injected, cfg=CFG)
    d.context = lambda cfg: AppContext("kitty", "code", True)
    reply = await dictate(d, rewrite=True)
    assert cleanup.calls == []
    assert reply["rewrite"] == "skipped"
