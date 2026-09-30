"""The settings server's HTTP layer (ADR 0014)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from flowd.settings_server import Reply, SettingsServer, Stream, Tokens


async def echo(method: str, path: str, query: dict[str, str], body: Any) -> Reply | Stream:
    if path == "/api/boom":
        raise RuntimeError("secret detail")
    if path == "/api/sse":

        async def events():
            for i in range(3):
                yield "level", {"i": i}

        return Stream(events())
    return Reply(200, {"ok": True, "method": method, "path": path, "query": query, "body": body})


@dataclass(frozen=True)
class Live:
    """A started server and a token it accepts."""

    srv: SettingsServer
    token: str

    @property
    def port(self) -> int:
        return self.srv.port


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[Live]:
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    (tmp_path / "app.js").write_text("1")
    tokens = Tokens()
    srv = SettingsServer(0, echo, tokens, web_root=tmp_path)
    assert await srv.start() is None
    yield Live(srv, tokens.issue())
    await srv.close()


async def raw(srv: Live, head: str, body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", srv.port)
    writer.write(head.replace("\n", "\r\n").encode() + b"\r\n" + body)
    await writer.drain()
    data = await reader.read()
    writer.close()
    head_b, _, rest = data.partition(b"\r\n\r\n")
    lines = head_b.decode().split("\r\n")
    headers = dict(line.split(": ", 1) for line in lines[1:])
    return int(lines[0].split()[1]), {k.lower(): v for k, v in headers.items()}, rest


def req(
    srv: Live,
    method: str = "GET",
    path: str = "/api/config",
    *,
    host: str | None = None,
    origin: str | None = None,
    token: str | None = "ok",
    body: bytes = b"",
    ctype: str = "application/json",
) -> tuple[str, bytes]:
    host = host or f"127.0.0.1:{srv.port}"
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}"]
    if origin:
        lines.append(f"Origin: {origin}")
    if token:
        lines.append(f"Authorization: Bearer {srv.token if token == 'ok' else token}")
    if body:
        lines += [f"Content-Type: {ctype}", f"Content-Length: {len(body)}"]
    return "\n".join(lines) + "\n", body


async def test_valid_request_reaches_the_handler(server) -> None:
    status, headers, body = await raw(server, *req(server, path="/api/config?a=1"))
    assert status == 200
    assert json.loads(body)["query"] == {"a": "1"}
    assert headers["content-security-policy"].startswith("default-src 'self'")
    assert headers["cache-control"] == "no-store"


async def test_missing_token_is_403(server) -> None:
    status, _, _ = await raw(server, *req(server, token=None))
    assert status == 403


async def test_wrong_token_is_403(server) -> None:
    status, _, _ = await raw(server, *req(server, token="x" * 43))
    assert status == 403


async def test_foreign_origin_with_valid_token_is_403(server) -> None:
    status, _, _ = await raw(server, *req(server, origin="http://evil.example"))
    assert status == 403


async def test_same_origin_is_allowed(server) -> None:
    status, _, _ = await raw(server, *req(server, origin=f"http://127.0.0.1:{server.port}"))
    assert status == 200


async def test_localhost_host_with_matching_origin_is_allowed(server) -> None:
    host = f"localhost:{server.port}"
    status, _, _ = await raw(server, *req(server, host=host, origin=f"http://{host}"))
    assert status == 200


async def test_rebound_host_is_403(server) -> None:
    status, _, _ = await raw(server, *req(server, host=f"evil.example:{server.port}"))
    assert status == 403
    status, _, _ = await raw(server, *req(server, path="/", host="evil.example", token=None))
    assert status == 403


async def test_mismatched_origin_and_host_is_403(server) -> None:
    status, _, _ = await raw(
        server,
        *req(server, host=f"localhost:{server.port}", origin=f"http://127.0.0.1:{server.port}"),
    )
    assert status == 403


async def test_preflight_is_403(server) -> None:
    status, headers, _ = await raw(server, *req(server, method="OPTIONS"))
    assert status == 403
    assert "access-control-allow-origin" not in headers


async def test_static_files_need_no_token(server) -> None:
    status, headers, _ = await raw(server, *req(server, path="/", token=None))
    assert status == 200 and headers["content-type"].startswith("text/html")
    assert headers["content-security-policy"].startswith("default-src 'self'")
    status, headers, _ = await raw(server, *req(server, path="/app.js", token=None))
    assert headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", ["/../secret", "/%2e%2e/secret", "/nope.html", "/x.py"])
async def test_static_traversal_and_unknown_are_404(server, tmp_path: Path, path: str) -> None:
    (tmp_path.parent / "secret").write_text("no")
    status, _, _ = await raw(server, *req(server, path=path, token=None))
    assert status == 404


async def test_json_body_is_decoded(server) -> None:
    _, _, body = await raw(server, *req(server, "PATCH", body=b'{"a": 1}'))
    assert json.loads(body)["body"] == {"a": 1}


async def test_bad_json_is_400_and_wrong_type_is_415(server) -> None:
    assert (await raw(server, *req(server, "PATCH", body=b"{")))[0] == 400
    assert (await raw(server, *req(server, "PATCH", body=b"a=1", ctype="text/plain")))[0] == 415


async def test_oversized_body_is_413(server) -> None:
    head, _ = req(server, "PATCH", body=b"x")
    head = head.replace("Content-Length: 1", "Content-Length: 999999999")
    assert (await raw(server, head))[0] == 413


async def test_handler_error_is_500_without_detail(server) -> None:
    status, _, body = await raw(server, *req(server, path="/api/boom"))
    assert status == 500 and b"secret" not in body


async def test_sse_stream(server) -> None:
    status, headers, body = await raw(server, *req(server, "POST", "/api/sse"))
    assert status == 200
    assert headers["content-type"] == "text/event-stream"
    assert body.count(b"event: level\n") == 3


async def test_port_in_use_is_reported_not_raised(server) -> None:
    other = SettingsServer(server.port, echo, Tokens())
    reason = await other.start()
    assert reason is not None and str(server.port) in reason


def test_tokens_keep_the_newest_eight() -> None:
    t = Tokens()
    first = t.issue()
    for _ in range(8):
        t.issue()
    assert not t.valid(first)
    assert t.valid(t.issue())
    assert not t.valid("")


async def test_oversized_head_is_431(server) -> None:
    head = f"GET / HTTP/1.1\nHost: 127.0.0.1:{server.port}\nX-Pad: {'a' * 20000}\n"
    assert (await raw(server, head))[0] == 431


async def test_malformed_request_line_is_400(server) -> None:
    assert (await raw(server, f"NONSENSE\nHost: 127.0.0.1:{server.port}\n"))[0] == 400


async def test_static_post_is_405(server) -> None:
    assert (await raw(server, *req(server, "POST", "/", token=None)))[0] == 405


async def test_head_sends_length_without_body(server) -> None:
    status, headers, body = await raw(server, *req(server, "HEAD", "/", token=None))
    assert status == 200 and headers["content-length"] == str(
        len("<!doctype html><title>t</title>")
    )
    assert body == b""
    assert headers["cache-control"] == "no-cache" and headers["connection"] == "close"


async def test_forbidden_reply_carries_security_headers(server) -> None:
    status, headers, body = await raw(server, *req(server, token=None))
    assert status == 403 and json.loads(body) == {"ok": False, "error": "forbidden"}
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cross-origin-resource-policy"] == "same-origin"


async def test_stream_is_closed_when_the_client_disconnects(tmp_path: Path) -> None:
    closed = asyncio.Event()

    async def endless() -> AsyncIterator[tuple[str, dict[str, Any]]]:
        try:
            while True:
                yield "level", {"x": "y" * 4096}
                await asyncio.sleep(0)
        finally:
            closed.set()

    async def handler(method: str, path: str, query: dict[str, str], body: Any) -> Reply | Stream:
        return Stream(endless())

    tokens = Tokens()
    srv = SettingsServer(0, handler, tokens, web_root=tmp_path)
    assert await srv.start() is None
    live = Live(srv, tokens.issue())
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", srv.port)
        head, _ = req(live, "POST", "/api/mic-test")
        writer.write(head.replace("\n", "\r\n").encode() + b"\r\n")
        await reader.readuntil(b"event: level\n")
        writer.close()
        await asyncio.wait_for(closed.wait(), 5)
    finally:
        await srv.close()


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/%2E%2E%2Fsecret.txt"])
async def test_traversal_to_a_servable_type_is_404(server, tmp_path: Path, path: str) -> None:
    # A .txt outside the root would pass the type filter, so only containment stops it.
    (tmp_path.parent / "secret.txt").write_text("no")
    status, _, body = await raw(server, *req(server, path=path, token=None))
    assert status == 404 and body != b"no"


async def test_body_up_to_the_limit_is_read_whole(server) -> None:
    # Larger than the head limit, so the body is not held to the head's buffer size.
    payload = {"text": "a" * (200 * 1024)}
    _, _, body = await raw(server, *req(server, "PATCH", body=json.dumps(payload).encode()))
    assert json.loads(body)["body"] == payload
