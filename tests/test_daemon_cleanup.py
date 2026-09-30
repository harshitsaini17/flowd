"""The cleanup pass inside a dictation (spec 5.5, 7.4, 9.3)."""

import asyncio
import contextlib
from dataclasses import replace
from typing import Any

import httpx
import numpy as np
import pytest

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

    def __init__(
        self, text: str | None = LONG_CLEAN, error: str | None = None, offline: bool = False
    ) -> None:
        self.text = text
        self.error = error
        self.offline = offline
        self.down = False
        self.calls: list[tuple[str, int]] = []
        self.health_checks = 0
        self.closed = False
        self.gate: asyncio.Event | None = None

    async def clean(self, raw: str, timeout_ms: int) -> CleanupResult:
        self.calls.append((raw, timeout_ms))
        if self.gate is not None:
            await self.gate.wait()
        return CleanupResult(self.text, self.error, self.offline)

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


async def test_llm_disabled_pastes_rule_based_text_without_calling_the_llm() -> None:
    injected: list[str] = []
    cleanup = FakeCleanup()
    cfg = replace(Config(), llm=replace(Llm(), enabled=False))
    d = make(LONG_RAW, cleanup, injected, cfg=cfg)
    await dictate(d)
    assert injected == [FALLBACK]
    assert cleanup.calls == []


async def test_llm_disabled_skips_health_probes() -> None:
    cleanup = FakeCleanup()
    cfg = replace(Config(), llm=replace(Llm(), enabled=False, health_interval_s=1))
    d = make(LONG_RAW, cleanup, [], cfg=cfg)
    task = asyncio.create_task(d._health_loop())
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert cleanup.health_checks == 0


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


async def test_a_model_that_never_answers_after_release_is_bounded_by_the_final_timeout() -> None:
    """spec 9.3 "final chunk slow": the release waits `final_timeout_ms`, then
    pastes the fallback instead of waiting on the model."""
    injected: list[str] = []
    cleanup = FakeCleanup()
    cleanup.gate = asyncio.Event()  # never set: the model hangs
    cfg = replace(Config(), llm=replace(Llm(), final_timeout_ms=50))
    d = make(LONG_RAW, cleanup, injected, cfg=cfg)
    await d.handle({"cmd": "start"})
    await d.pump()
    reply = await asyncio.wait_for(d.handle({"cmd": "stop"}), timeout=2)
    assert reply["ok"] is True
    assert injected == [FALLBACK]


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
    """llama-server down means dictation works via fallback."""

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


# --- what flowd-ui is told about the cleanup pass ---------------------------


class ScriptedCleanup(FakeCleanup):
    """Answers each `clean` call with the next `(text, error)` in turn."""

    def __init__(self, answers: list[tuple[str | None, str | None]]) -> None:
        super().__init__()
        self.answers = answers

    async def clean(self, raw: str, timeout_ms: int) -> CleanupResult:
        self.calls.append((raw, timeout_ms))
        text, error = self.answers.pop(0)
        # Echo the input for an accepted answer, so the guardrails pass it.
        return CleanupResult(raw if text == "echo" else text, error)


def ui_states(d: Daemon) -> list[tuple[str, str]]:
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    return overlay.states()


async def test_an_accepted_polish_reports_done() -> None:
    d = make(LONG_RAW, FakeCleanup(), [])
    await dictate(d)
    assert ui_states(d)[-1] == ("done", "")


async def test_a_short_session_reports_done_not_fallback() -> None:
    """Under `short_bypass_words` nothing fell back; the LLM was never asked."""
    d = make("um ship it", FakeCleanup(), [])
    await dictate(d)
    assert ui_states(d)[-1] == ("done", "")


async def test_a_session_without_cleanup_reports_done() -> None:
    d = make(LONG_RAW, None, [])
    await dictate(d)
    assert ui_states(d)[-1] == ("done", "")


async def test_a_cleanup_timeout_reports_fallback_timeout() -> None:
    d = make(LONG_RAW, FakeCleanup(text=None, error="timeout"), [])
    await dictate(d)
    assert ui_states(d)[-1] == ("fallback", "timeout")


async def test_a_guardrail_rejection_reports_fallback_rejected() -> None:
    cleanup = FakeCleanup(text="The ocean whispers secrets to the patient moon tonight.")
    d = make(LONG_RAW, cleanup, [])
    await dictate(d)
    assert ui_states(d)[-1] == ("fallback", "rejected")


async def test_a_down_llm_reports_fallback_offline() -> None:
    cleanup = FakeCleanup(text=None, error="down", offline=True)
    cleanup.down = True
    d = make(LONG_RAW, cleanup, [])
    d._notify = lambda message: None  # type: ignore[method-assign]
    await dictate(d)
    assert ui_states(d)[-1] == ("fallback", "offline")


async def test_a_model_that_never_answers_reports_fallback_timeout() -> None:
    """The release deadline abandons the chunk, which records no reason."""
    cleanup = FakeCleanup()
    cleanup.gate = asyncio.Event()
    cfg = replace(Config(), llm=replace(Llm(), final_timeout_ms=50))
    d = make(LONG_RAW, cleanup, [], cfg=cfg)
    await dictate(d)
    assert ui_states(d)[-1] == ("fallback", "timeout")


async def test_mixed_chunk_fallbacks_report_the_most_severe() -> None:
    """One chunk rejected, the next timed out: the session says timed out."""
    first, second = "we should ship the release on friday", "and then tell the whole team"
    cleanup = ScriptedCleanup([("Totally unrelated words about the sea.", None), (None, "timeout")])
    d = Daemon(
        cfg=Config(),
        stt=FakeSttEngine([[Committed(first)], [Committed(second)]]),
        capture=FakeCapture([np.zeros(1600, dtype=np.float32)] * 2),
        overlay=FakeOverlay(),
        injector=lambda text, cfg, **kw: InjectResult(ok=True, backend="fake"),
        clock=Clock(),
        write_metrics=False,
        cleanup=cleanup,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await asyncio.sleep(0)
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert len(cleanup.calls) == 2
    assert ui_states(d)[-1] == ("fallback", "timeout")


async def test_one_polished_chunk_and_one_fallback_still_reports_the_fallback() -> None:
    first, second = "we should ship the release on friday", "and then tell the whole team"
    cleanup = ScriptedCleanup([("echo", None), (None, "error: HTTPStatusError")])
    d = Daemon(
        cfg=Config(),
        stt=FakeSttEngine([[Committed(first)], [Committed(second)]]),
        capture=FakeCapture([np.zeros(1600, dtype=np.float32)] * 2),
        overlay=FakeOverlay(),
        injector=lambda text, cfg, **kw: InjectResult(ok=True, backend="fake"),
        clock=Clock(),
        write_metrics=False,
        cleanup=cleanup,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await asyncio.sleep(0)
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert ui_states(d)[-1] == ("fallback", "failed")


async def test_fallback_reasons_start_empty_for_each_session() -> None:
    cleanup = ScriptedCleanup([(None, "timeout"), ("echo", None)])
    d = make(LONG_RAW, cleanup, [])
    await dictate(d)
    d.stt = FakeSttEngine([[Committed(LONG_RAW)]])
    await dictate(d)
    assert ui_states(d)[-1] == ("done", "")


def warnings(d: Daemon) -> list[tuple[Any, ...]]:
    overlay = d.overlay
    assert isinstance(overlay, FakeOverlay)
    return [e for e in overlay.events if e[0] == "warn"]


async def test_cleanup_going_down_and_up_sets_and_clears_the_warning() -> None:
    cleanup = FakeCleanup()
    d = make(LONG_RAW, cleanup, [], cfg=Config(llm=Llm(health_interval_s=1)))
    cleanup.down = True
    task = asyncio.create_task(d._health_loop())
    await asyncio.sleep(0)
    assert warnings(d) == [("warn", "Cleanup offline, pasting as heard", False)]
    cleanup.down = False
    await asyncio.sleep(1.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert warnings(d) == [
        ("warn", "Cleanup offline, pasting as heard", False),
        ("warn", None, False),
    ]


async def test_a_steady_warning_is_sent_once() -> None:
    cleanup = FakeCleanup()
    cleanup.down = True
    d = make(LONG_RAW, cleanup, [], cfg=Config(llm=Llm(health_interval_s=1)))
    d._sync_warning()
    d._sync_warning()
    assert len(warnings(d)) == 1


async def test_cleanup_going_down_mid_session_warns_after_the_paste() -> None:
    client = CleanupClient(
        Llm(down_after_failures=1),
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no"))),
    )
    d = make(LONG_RAW, client, [])
    d._notify = lambda message: None  # type: ignore[method-assign]
    await dictate(d)
    assert ui_states(d)[-1] == ("fallback", "offline")
    assert warnings(d) == [("warn", "Cleanup offline, pasting as heard", False)]
    await client.aclose()


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (CleanupResult(None, "down", offline=True), "offline"),
        (CleanupResult(None, "error: ConnectError", offline=True), "offline"),
        # The error text alone does not make it offline; the client decides.
        (CleanupResult(None, "error: ConnectError"), "failed"),
        (CleanupResult(None, "timeout"), "timeout"),
        (CleanupResult(None, "too long"), "failed"),
        (CleanupResult(None, "error: no content"), "failed"),
        (CleanupResult(None, "error: HTTPStatusError"), "failed"),
        (CleanupResult(None, "error: RuntimeError"), "failed"),
        (CleanupResult(None, None), "failed"),
        # Text came back, so it fell back on a guardrail.
        (CleanupResult("Anything at all.", None), "rejected"),
    ],
)
def test_cleanup_results_map_to_the_popup_fallback_reasons(
    result: CleanupResult, reason: str
) -> None:
    from flowd.daemon import _fallback_reason

    assert _fallback_reason(result) == reason


@pytest.mark.parametrize(
    ("reasons", "shown"),
    [
        ([], None),
        (["rejected"], "rejected"),
        (["rejected", "timeout"], "timeout"),
        (["timeout", "failed"], "failed"),
        (["rejected", "offline", "timeout"], "offline"),
        (["something new"], "failed"),
    ],
)
def test_a_session_reports_its_most_severe_fallback(reasons: list[str], shown: str | None) -> None:
    from flowd.daemon import worst_fallback

    assert worst_fallback(reasons) == shown


def refusing(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadError("connection reset"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
)
async def test_a_client_that_cannot_reach_the_server_reports_offline(exc: Exception) -> None:
    from flowd.daemon import _fallback_reason

    client = CleanupClient(Llm(), transport=refusing(exc))
    result = await client.clean(LONG_RAW, 1000)
    await client.aclose()
    assert result.offline is True
    assert _fallback_reason(result) == "offline"


async def test_a_server_error_is_not_offline() -> None:
    from flowd.daemon import _fallback_reason

    client = CleanupClient(
        Llm(), transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    result = await client.clean(LONG_RAW, 1000)
    await client.aclose()
    assert result.offline is False
    assert _fallback_reason(result) == "failed"


async def test_a_down_client_reports_offline() -> None:
    client = CleanupClient(Llm())
    client.down = True
    result = await client.clean(LONG_RAW, 1000)
    await client.aclose()
    assert result.offline is True


async def test_a_session_against_an_unreachable_server_reports_fallback_offline() -> None:
    client = CleanupClient(Llm(), transport=refusing(httpx.ConnectError("refused")))
    d = make(LONG_RAW, client, [])
    d._notify = lambda message: None  # type: ignore[method-assign]
    await dictate(d)
    await client.aclose()
    assert ui_states(d)[-1] == ("fallback", "offline")


async def test_a_polish_that_raises_reports_fallback_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flowd.daemon

    def boom(*args: Any, **kwargs: Any) -> int | None:
        raise RuntimeError("guardrail bug")

    monkeypatch.setattr(flowd.daemon.guardrails, "check", boom)
    injected: list[str] = []
    d = make(LONG_RAW, FakeCleanup(), injected)
    await dictate(d)
    assert injected == [FALLBACK]
    assert ui_states(d)[-1] == ("fallback", "failed")


async def test_a_ui_failure_warns_once_per_call_site(caplog: pytest.LogCaptureFixture) -> None:
    class Broken(FakeOverlay):
        def state(self, state: str, reason: str = "") -> None:
            raise BrokenPipeError

        def level(self, rms_db: float, peak_db: float) -> None:
            raise BrokenPipeError

    d = make(LONG_RAW, None, [])
    d.overlay = Broken()
    d.capture = FakeCapture([np.zeros(1600, dtype=np.float32)] * 3)
    d.stt = FakeSttEngine([[], [], [Committed(LONG_RAW)]])
    with caplog.at_level("DEBUG", logger="flowd.daemon"):
        await d.handle({"cmd": "start"})
        for _ in range(3):
            await d.pump()
        await d.handle({"cmd": "stop"})
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "flowd-ui" in r.message]
    debugs = [r for r in caplog.records if r.levelname == "DEBUG" and "flowd-ui" in r.message]
    # One warning for levels, one per distinct state call site; repeats at debug.
    assert len([r for r in warnings if "level" in r.message]) == 1
    assert any("level" in r.message for r in debugs)
    sites = [r.message for r in warnings if "message to flowd-ui" in r.message]
    assert len(sites) == len(set(sites))
