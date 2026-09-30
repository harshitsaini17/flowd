"""Loopback HTTP/1.1 server for the settings page (ADR 0014).

Standard library only, on the daemon's asyncio loop, bound to 127.0.0.1.
One request per connection. Static files are served without a token; every
`/api/` request must pass three checks or it gets 403:

- The bearer token stops other local users and processes. Only whoever ran
  `flowctl settings` has it, and it lives in daemon memory only.
- The `Host` check stops DNS rebinding: a site that points its own name at
  127.0.0.1 still sends its own name as `Host`. It applies to static files
  too, so a rebound page cannot even load ours.
- The `Origin` check stops a page on another origin that somehow has the
  token. Browsers always send `Origin` on cross-origin requests.

There is no CORS, so preflights are refused. Every response carries a strict
Content-Security-Policy. The token and request bodies are never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hmac
import json
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).parent / "web"
MAX_BODY = 256 * 1024
_MAX_HEAD = 16 * 1024
_READ_TIMEOUT = 10.0
_MAX_TOKENS = 8
_HOST = "127.0.0.1"

_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
}

# Headers that change how a request is authorised or framed. A second copy
# could make two parsers disagree, so a repeat is a malformed request.
_SINGLE_HEADERS = frozenset({"host", "origin", "authorization", "content-length", "content-type"})


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Stream:
    """Server-sent events: (event name, data) pairs."""

    events: AsyncIterator[tuple[str, dict[str, Any]]]


# (method, path without query, query params, decoded JSON body or None)
Handler = Callable[[str, str, dict[str, str], Any], Awaitable[Reply | Stream]]


class Tokens:
    """Bearer tokens held in memory; the newest few stay valid."""

    def __init__(self) -> None:
        self._tokens: list[str] = []

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens = [*self._tokens, token][-_MAX_TOKENS:]
        return token

    def valid(self, candidate: str) -> bool:
        if not candidate:
            return False
        given = candidate.encode("utf-8", "surrogateescape")
        # Compare against every token so timing does not reveal which matched.
        found = False
        for token in self._tokens:
            found |= hmac.compare_digest(given, token.encode())
        return found

    def export(self) -> list[str]:
        return list(self._tokens)

    def adopt(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)[-_MAX_TOKENS:]


class _BadRequest(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]


class SettingsServer:
    def __init__(
        self, port: int, handler: Handler, tokens: Tokens, web_root: Path | None = None
    ) -> None:
        self._requested_port = port
        self._handler = handler
        self._tokens = tokens
        self._web_root = web_root if web_root is not None else WEB_ROOT
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[Any]] = set()

    async def start(self) -> str | None:
        """Listen on loopback. Returns None, or why listening failed."""
        try:
            self._server = await asyncio.start_server(
                self._connection, host=_HOST, port=self._requested_port, limit=_MAX_HEAD
            )
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return f"port {self._requested_port} is in use"
            return f"cannot listen on {_HOST}:{self._requested_port}: {exc.strerror or exc}"
        return None

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self._requested_port

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        # Open event streams would otherwise keep wait_closed() waiting.
        for task in list(self._connections):
            task.cancel()
        await asyncio.gather(*self._connections, return_exceptions=True)
        await self._server.wait_closed()
        self._server = None

    # -- connection handling ---------------------------------------------

    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            await self._serve(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass  # the client went away or stalled; nothing to answer
        except Exception:
            log.exception("settings server: request failed")
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await self._read_head(reader)
        except _BadRequest as bad:
            await self._send_error(writer, bad.status)
            return
        except TimeoutError:
            await self._send_error(writer, HTTPStatus.REQUEST_TIMEOUT)
            return

        if not self._host_ok(request.headers.get("host")):
            await self._send_error(writer, HTTPStatus.FORBIDDEN)
            return

        if request.path.startswith("/api/"):
            await self._serve_api(request, reader, writer)
        else:
            await self._serve_static(request, writer)

    async def _read_head(self, reader: asyncio.StreamReader) -> _Request:
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _READ_TIMEOUT)
        except asyncio.LimitOverrunError:
            raise _BadRequest(HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE) from None
        except asyncio.IncompleteReadError as exc:
            if len(exc.partial) > _MAX_HEAD:
                raise _BadRequest(HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE) from None
            raise
        if len(raw) > _MAX_HEAD:
            raise _BadRequest(HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE)

        # latin-1 decodes any byte, so a hostile head cannot raise here.
        lines = raw[:-4].decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if (
            len(parts) != 3
            or not parts[0].isalpha()
            or not parts[0].isupper()
            or not parts[1].startswith("/")
            or parts[2] not in ("HTTP/1.0", "HTTP/1.1")
        ):
            raise _BadRequest(HTTPStatus.BAD_REQUEST)
        method, target, _ = parts

        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            name = name.lower()
            if not sep or not name or name != name.strip():
                raise _BadRequest(HTTPStatus.BAD_REQUEST)
            if name in _SINGLE_HEADERS and name in headers:
                raise _BadRequest(HTTPStatus.BAD_REQUEST)
            headers[name] = value.strip()

        path, _, query_string = target.partition("?")
        # dict() keeps the last value for a repeated key.
        query = dict(parse_qsl(query_string, keep_blank_values=True))
        return _Request(method, path, query, headers)

    def _host_ok(self, host: str | None) -> bool:
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _api_allowed(self, request: _Request) -> bool:
        if request.method == "OPTIONS":
            return False  # no CORS, ever
        origin = request.headers.get("origin")
        if origin is not None and origin != "http://" + request.headers["host"]:
            return False
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and self._tokens.valid(token)

    # -- /api/ -----------------------------------------------------------

    async def _serve_api(
        self, request: _Request, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if not self._api_allowed(request):
            await self._send_error(writer, HTTPStatus.FORBIDDEN)
            return
        try:
            body = await self._read_body(request, reader)
        except _BadRequest as bad:
            await self._send_error(writer, bad.status)
            return

        try:
            result = await self._handler(request.method, request.path, request.query, body)
        except Exception:
            log.exception("settings server: handler failed for %s %s", request.method, request.path)
            await self._send_json(
                writer, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal error"}
            )
            return

        if isinstance(result, Stream):
            await self._send_stream(writer, result)
        else:
            await self._send_json(writer, result.status, result.body)

    async def _read_body(self, request: _Request, reader: asyncio.StreamReader) -> Any:
        if "transfer-encoding" in request.headers:
            raise _BadRequest(HTTPStatus.BAD_REQUEST)  # no chunked bodies
        length_header = request.headers.get("content-length", "0")
        if not length_header.isdigit() or not length_header.isascii():
            raise _BadRequest(HTTPStatus.BAD_REQUEST)
        length = int(length_header)
        if length > MAX_BODY:
            raise _BadRequest(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if length == 0:
            return None
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise _BadRequest(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        data = await asyncio.wait_for(reader.readexactly(length), _READ_TIMEOUT)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _BadRequest(HTTPStatus.BAD_REQUEST) from None

    async def _send_stream(self, writer: asyncio.StreamWriter, stream: Stream) -> None:
        events = stream.events
        try:
            await self._send_head(
                writer,
                HTTPStatus.OK,
                [("Content-Type", "text/event-stream"), ("Cache-Control", "no-store")],
            )
            async for name, data in events:
                writer.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                await writer.drain()
        except ConnectionError:
            pass  # the page closed; aclose() below releases whatever the stream holds
        except Exception:
            # Headers are already sent, so all that can be done is to end the stream.
            log.exception("settings server: event stream failed")
        finally:
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()

    # -- static files ----------------------------------------------------

    async def _serve_static(self, request: _Request, writer: asyncio.StreamWriter) -> None:
        if request.method not in ("GET", "HEAD"):
            await self._send_error(writer, HTTPStatus.METHOD_NOT_ALLOWED)
            return
        file = self._resolve_static(request.path)
        content_type = _CONTENT_TYPES.get(file.suffix) if file is not None else None
        if file is None or content_type is None:
            await self._send_error(writer, HTTPStatus.NOT_FOUND)
            return
        try:
            data = await asyncio.to_thread(file.read_bytes)
        except OSError:
            await self._send_error(writer, HTTPStatus.NOT_FOUND)
            return
        headers = [
            ("Content-Type", content_type),
            ("Cache-Control", "no-cache"),
            ("Content-Length", str(len(data))),
        ]
        await self._send_head(writer, HTTPStatus.OK, headers)
        if request.method == "GET":
            writer.write(data)
        await writer.drain()

    def _resolve_static(self, path: str) -> Path | None:
        # Decode first so an encoded `..` is caught by the containment check.
        rel = unquote(path).lstrip("/") or "index.html"
        if "\x00" in rel:
            return None
        root = self._web_root.resolve()
        try:
            candidate = (root / rel).resolve()
        except (OSError, RuntimeError):
            return None
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate

    # -- writing responses -----------------------------------------------

    async def _send_head(
        self, writer: asyncio.StreamWriter, status: int, headers: list[tuple[str, str]]
    ) -> None:
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = ""
        lines = [f"HTTP/1.1 {status} {phrase}".rstrip()]
        lines += [f"{name}: {value}" for name, value in (*_SECURITY_HEADERS, *headers)]
        lines.append("Connection: close")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()

    async def _send_json(
        self, writer: asyncio.StreamWriter, status: int, body: dict[str, Any]
    ) -> None:
        data = json.dumps(body).encode()
        headers = [
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-store"),
            ("Content-Length", str(len(data))),
        ]
        await self._send_head(writer, status, headers)
        writer.write(data)
        await writer.drain()

    async def _send_error(self, writer: asyncio.StreamWriter, status: int) -> None:
        error = "forbidden" if status == HTTPStatus.FORBIDDEN else HTTPStatus(status).phrase.lower()
        await self._send_json(writer, status, {"ok": False, "error": error})
