import asyncio
import json
from typing import Any

import httpx
import pytest

from flowd.cleanup import PROMPT_TEMPLATE, CleanupClient
from flowd.config import Llm


class FakeServer:
    """A scripted llama-server behind `httpx.MockTransport`."""

    def __init__(self, content: str = "Cleaned.", tokens: int = 4) -> None:
        self.content = content
        self.tokens = tokens
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.fail: Exception | None = None
        self.status = 200
        self.delay_s = 0.0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.url.path, body))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail is not None:
            raise self.fail
        if request.url.path == "/tokenize":
            return httpx.Response(self.status, json={"tokens": list(range(self.tokens))})
        if request.url.path == "/health":
            return httpx.Response(self.status, json={"status": "ok"})
        return httpx.Response(self.status, json={"content": self.content})

    def client(self, **overrides: Any) -> CleanupClient:
        return CleanupClient(Llm(**overrides), transport=httpx.MockTransport(self.handler))


async def test_clean_sends_the_sotto_completion_prompt() -> None:
    server = FakeServer(content=" I think so. \n")
    result = await server.client().clean("um i think so", timeout_ms=800)
    assert result.text == "I think so."
    path, body = server.requests[-1]
    assert path == "/completion"
    assert body["prompt"] == PROMPT_TEMPLATE.format(raw="um i think so")
    assert body["temperature"] == 0
    assert body["cache_prompt"] is True
    assert body["stop"] == ["###", "\n\n"]


def test_max_tokens_follows_spec_5_5() -> None:
    client = CleanupClient(Llm())
    assert client.max_tokens(10) == 31  # ceil(1.5 * 10) + 16
    assert client.max_tokens(3) == 21  # ceil(4.5) + 16


async def test_n_predict_uses_the_server_token_count() -> None:
    server = FakeServer(tokens=10)
    await server.client().clean("some words", timeout_ms=800)
    assert server.requests[-1][1]["n_predict"] == 31


async def test_a_slow_server_times_out_without_counting_as_down() -> None:
    server = FakeServer()
    server.delay_s = 0.5
    client = server.client()
    for _ in range(3):
        result = await client.clean("hello there", timeout_ms=50)
        assert result.text is None
        assert result.error == "timeout"
    assert client.down is False


async def test_two_connect_errors_mark_the_llm_down() -> None:
    server = FakeServer()
    server.fail = httpx.ConnectError("refused")
    client = server.client()
    assert (await client.clean("a", timeout_ms=800)).error == "error: ConnectError"
    assert client.down is False
    await client.clean("a", timeout_ms=800)
    assert client.down is True
    # While down, no request is even attempted (spec 5.5).
    sent = len(server.requests)
    assert (await client.clean("a", timeout_ms=800)).error == "down"
    assert len(server.requests) == sent


async def test_a_server_error_status_counts_as_a_failure() -> None:
    server = FakeServer()
    server.status = 500
    client = server.client(down_after_failures=1)
    result = await client.clean("a", timeout_ms=800)
    assert result.text is None
    assert client.down is True


async def test_malformed_json_is_a_failure_not_a_crash() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = CleanupClient(Llm(), transport=httpx.MockTransport(handler))
    result = await client.clean("a", timeout_ms=800)
    assert result.text is None
    assert result.error is not None


async def test_a_healthy_probe_brings_the_llm_back() -> None:
    server = FakeServer()
    server.fail = httpx.ConnectError("refused")
    client = server.client()
    assert await client.check_health() is False
    assert await client.check_health() is False
    assert client.down is True
    server.fail = None
    assert await client.check_health() is True
    assert client.down is False
    assert (await client.clean("a", timeout_ms=800)).text == "Cleaned."


async def test_a_success_resets_the_failure_count() -> None:
    server = FakeServer()
    client = server.client()
    server.fail = httpx.ConnectError("refused")
    await client.clean("a", timeout_ms=800)
    server.fail = None
    await client.clean("a", timeout_ms=800)
    server.fail = httpx.ConnectError("refused")
    await client.clean("a", timeout_ms=800)
    assert client.down is False


@pytest.mark.parametrize("content", [None, 42])
async def test_a_reply_without_text_content_is_rejected(content: Any) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, json={"content": content})

    client = CleanupClient(Llm(), transport=httpx.MockTransport(handler))
    assert (await client.clean("a", timeout_ms=800)).text is None


async def test_text_too_long_for_the_context_skips_the_llm() -> None:
    server = FakeServer(tokens=400)  # 400 + 16 + ceil(600) + 16 > 1024
    client = server.client()
    result = await client.clean("a long dictation", timeout_ms=800)
    assert result.text is None
    assert result.error == "too long"
    assert [path for path, _ in server.requests] == ["/tokenize"]
    assert client.down is False
