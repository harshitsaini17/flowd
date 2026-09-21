"""Phase 3: the cleanup pass inside a dictation (spec 5.5, 7.4, 9.3)."""

import asyncio
from typing import Any

import httpx

from flowd.cleanup import CleanupClient, CleanupResult
from flowd.config import Config, Inject, Llm
from flowd.daemon import Daemon
from flowd.inject.base import InjectResult
from flowd.stt import Committed, FakeSttEngine
from flowd.vocab import Vocab
from tests.test_daemon import Clock, FakeCapture, FakeOverlay

LONG_RAW = "so um i think we should ship the release on friday"
LONG_CLEAN = "So I think we should ship the release on Friday."
#: What `basic_clean` makes of LONG_RAW: it removes fillers but, unlike the
#: LLM, knows nothing of proper nouns. Distinct on purpose, so each test can
#: tell which path produced its text.
FALLBACK = "So I think we should ship the release on friday."


class FakeCleanup:
    """Stands in for `CleanupClient`; `gate` holds `clean` open until set."""

    def __init__(self, text: str | None = LONG_CLEAN, error: str | None = None) -> None:
        self.text = text
        self.error = error
        self.down = False
        self.calls: list[tuple[str, int]] = []
        self.health_checks = 0
        self.closed = False
        self.gate: asyncio.Event | None = None

    async def clean(self, raw: str, timeout_ms: int) -> CleanupResult:
        self.calls.append((raw, timeout_ms))
        if self.gate is not None:
            await self.gate.wait()
        return CleanupResult(self.text, self.error)

    async def check_health(self) -> bool:
        self.health_checks += 1
        return not self.down

    async def aclose(self) -> None:
        self.closed = True


def make(
    text: str,
    cleanup: Any,
    injected: list[str],
    *,
    cfg: Config | None = None,
    vocab: Vocab | None = None,
) -> Daemon:
    def fake_inject(out: str, inject_cfg: Inject, **kwargs: Any) -> InjectResult:
        injected.append(out)
        return InjectResult(ok=True, backend="fake")

    return Daemon(
        cfg=cfg or Config(),
        stt=FakeSttEngine([[Committed(text)]]),
        capture=FakeCapture(),
        overlay=FakeOverlay(),
        injector=fake_inject,
        clock=Clock(),
        write_metrics=False,
        vocab=vocab,
        cleanup=cleanup,
    )


async def dictate(d: Daemon) -> dict[str, Any]:
    await d.handle({"cmd": "start"})
    await d.pump()
    return await d.handle({"cmd": "stop"})


async def test_accepted_llm_output_is_injected() -> None:
    injected: list[str] = []
    cleanup = FakeCleanup()
    d = make(LONG_RAW, cleanup, injected)
    await dictate(d)
    assert injected == [LONG_CLEAN]
    # Sent while recording, as soon as it was committed (spec 6.3), so it gets
    # the recording-time budget, not the release one.
    assert cleanup.calls == [(LONG_RAW, Config().llm.timeout_ms)]
    assert "cleaned_ms" in d.last_record["stages"]
    assert "fallbacks" not in d.last_record["counts"]
    assert d.last_raw == LONG_RAW


async def test_the_final_frame_shows_the_polished_text() -> None:
    d = make(LONG_RAW, FakeCleanup(), [])
    await dictate(d)
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    assert overlay.messages[-1]["polished"] == LONG_CLEAN
    assert overlay.messages[-1]["pending"] == ""


async def test_a_short_session_skips_the_llm() -> None:
    """spec 9.1: under `short_bypass_words`, basic_clean alone, no fallback."""
    injected: list[str] = []
    cleanup = FakeCleanup()
    d = make("um ship it", cleanup, injected)
    await dictate(d)
    assert cleanup.calls == []
    assert injected == ["Ship it."]
    assert d.last_record["counts"]["bypassed"] == 1
    assert "fallbacks" not in d.last_record["counts"]


async def test_a_guardrail_rejection_falls_back_and_records_the_check() -> None:
    injected: list[str] = []
    cleanup = FakeCleanup(text="The ocean whispers secrets to the patient moon tonight.")
    d = make(LONG_RAW, cleanup, injected)
    await dictate(d)
    assert injected == [FALLBACK]
    assert d.last_record["fallback_checks"] == {"3": 1}
    assert d.last_record["counts"]["fallbacks"] == 1


async def test_a_timeout_falls_back_and_says_why() -> None:
    injected: list[str] = []
    d = make(LONG_RAW, FakeCleanup(text=None, error="timeout"), injected)
    await dictate(d)
    assert injected == [FALLBACK]
    assert d.last_record["errors"] == ["llm: timeout"]
    assert d.last_record["counts"]["fallbacks"] == 1


async def test_rejections_never_log_the_text() -> None:
    """spec 13.2: fallback records carry check numbers, never transcripts."""
    d = make(LONG_RAW, FakeCleanup(text="Sure, here it is."), [])
    await dictate(d)
    assert "text" not in d.last_record
    assert "ship" not in str(d.last_record)


async def test_replacements_reach_the_llm() -> None:
    """spec 7.6: [replace] applies before the LLM, not only in basic_clean."""
    cleanup = FakeCleanup(text="Open Hyprland and check the logs now please.")
    vocab = Vocab(replace={"hyper land": "Hyprland"})
    d = make("open hyper land and check the logs now please", cleanup, [], vocab=vocab)
    await dictate(d)
    assert cleanup.calls[0][0] == "open Hyprland and check the logs now please"


async def test_a_self_correction_may_drop_words() -> None:
    """spec 7.4 check 2's merged bound: keeping only the correction is allowed."""
    injected: list[str] = []
    cleanup = FakeCleanup(text="Send it to Sarah.")
    d = make("send it to john no wait send it to sarah", cleanup, injected)
    await dictate(d)
    assert injected == ["Send it to Sarah."]


async def test_a_down_llm_notifies_once_per_session() -> None:
    injected: list[str] = []
    cleanup = FakeCleanup(text=None, error="down")
    cleanup.down = True
    d = make(LONG_RAW, cleanup, injected)
    notes: list[str] = []
    d._notify = notes.append  # type: ignore[method-assign]
    reply = await dictate(d)
    assert reply["text"] == FALLBACK
    await asyncio.gather(*d._background)
    assert injected == [FALLBACK]
    assert notes == ["flowd: cleanup LLM is down; using basic cleanup"]


async def test_a_cancel_during_the_llm_injects_nothing() -> None:
    """spec 4: FINALIZING + cancel discards, even with the LLM mid-request."""
    injected: list[str] = []
    cleanup = FakeCleanup()
    cleanup.gate = asyncio.Event()
    d = make(LONG_RAW, cleanup, injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    while not cleanup.calls:  # dispatched at commit, then held open by the gate
        await asyncio.sleep(0)
    stop = asyncio.create_task(d.handle({"cmd": "stop"}))
    while str(d.machine.state) != "finalizing":
        await asyncio.sleep(0)
    await d.handle({"cmd": "cancel"})
    cleanup.gate.set()
    reply = await stop
    assert reply == {"ok": False, "reason": "cancelled"}
    assert injected == []
    assert d.session is None
    assert str(d.machine.state) == "idle"


async def test_a_dead_server_still_dictates() -> None:
    """Phase 3 acceptance: llama-server down means dictation works via fallback."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = CleanupClient(Llm(), transport=httpx.MockTransport(refuse))
    injected: list[str] = []
    d = make(LONG_RAW, client, injected)
    d._notify = lambda message: None  # type: ignore[method-assign]
    for _ in range(3):
        d.stt = FakeSttEngine([[Committed(LONG_RAW)]])  # one script per session
        await dictate(d)
    assert injected == [FALLBACK] * 3
    assert client.down is True
    assert d.last_record["errors"] == ["llm: down"]


async def test_the_health_loop_probes_only_while_idle() -> None:
    cleanup = FakeCleanup()
    d = make(LONG_RAW, cleanup, [], cfg=Config(llm=Llm(health_interval_s=1)))
    task = asyncio.create_task(d._health_loop())
    await asyncio.sleep(0)
    assert cleanup.health_checks == 1
    task.cancel()
    await d.handle({"cmd": "start"})
    # A second loop started mid-session must not probe.
    task = asyncio.create_task(d._health_loop())
    await asyncio.sleep(0)
    assert cleanup.health_checks == 1
    task.cancel()


async def test_a_session_of_only_fillers_injects_nothing() -> None:
    """Long enough to reach the LLM, but cleaning leaves nothing: spec 9.1's
    "No speech", not an empty paste over the user's selection."""
    injected: list[str] = []
    d = make("um uh um uh um uh", FakeCleanup(text="Um."), injected)
    reply = await dictate(d)
    assert injected == []
    assert reply == {"ok": True, "reason": "no speech"}
    assert str(d.machine.state) == "idle"


async def test_the_health_loop_survives_a_failing_probe() -> None:
    # The loop is the only way back from `down`; one bad probe must not end it.
    cleanup = FakeCleanup()

    async def boom() -> bool:
        cleanup.health_checks += 1
        raise RuntimeError("client closed")

    cleanup.check_health = boom  # type: ignore[method-assign]
    d = make(LONG_RAW, cleanup, [], cfg=Config(llm=Llm(health_interval_s=1)))
    task = asyncio.create_task(d._health_loop())
    await asyncio.sleep(0.01)
    assert cleanup.health_checks == 1
    assert not task.done()
    task.cancel()


def make_in(
    app: str, mode: str, is_terminal: bool, text: str, cleanup: Any
) -> tuple[Daemon, list[tuple[str, bool]]]:
    from flowd.context import AppContext

    sent: list[tuple[str, bool]] = []
    calls: list[int] = []

    def inject(out: str, inject_cfg: Inject, *, is_terminal: bool = False) -> InjectResult:
        sent.append((out, is_terminal))
        return InjectResult(ok=True, backend="fake")

    def context(cfg: Config) -> AppContext:
        calls.append(1)
        return AppContext(app, mode, is_terminal)

    d = Daemon(
        cfg=Config(),
        stt=FakeSttEngine([[Committed(text)]]),
        capture=FakeCapture(),
        overlay=FakeOverlay(),
        injector=inject,
        clock=Clock(),
        write_metrics=False,
        cleanup=cleanup,
        context=context,
    )
    d._context_calls = calls  # type: ignore[attr-defined]
    return d, sent


async def test_a_terminal_session_skips_the_llm_and_pastes_as_a_terminal() -> None:
    cleanup = FakeCleanup()
    d, sent = make_in("kitty", "code", True, "um git status dash dash short", cleanup)
    await dictate(d)
    assert cleanup.calls == []
    assert sent == [("git status dash dash short", True)]
    assert d.last_record["mode"] == "code"
    assert d.last_record["app_id"] == "kitty"
    assert "fallbacks" not in d.last_record["counts"]


async def test_a_chat_session_drops_the_final_period() -> None:
    d, sent = make_in("org.telegram.desktop", "chat", False, LONG_RAW, FakeCleanup())
    await dictate(d)
    assert sent == [(LONG_CLEAN.removesuffix("."), False)]


async def test_the_app_is_read_once_at_start() -> None:
    """spec 9.4: the mode stays as chosen at start even if focus moves."""
    d, _ = make_in("thunderbird", "email", False, LONG_RAW, FakeCleanup())
    await dictate(d)
    assert d._context_calls == [1]  # type: ignore[attr-defined]
    assert d.last_record["mode"] == "email"
