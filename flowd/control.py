"""Unix socket control protocol: newline-delimited JSON (spec 4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VALID_COMMANDS = frozenset(
    {"start", "stop", "toggle", "cancel", "status", "last", "stats", "reload"}
)
_MAX_LINE = 64 * 1024

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class AlreadyRunning(Exception):
    """Another daemon is listening on the socket (spec 9.5)."""


def parse_command(line: bytes) -> dict[str, Any]:
    try:
        request = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed request: {exc}") from exc
    if not isinstance(request, dict):
        raise ValueError("malformed request: expected a JSON object")
    cmd = request.get("cmd")
    if cmd is None:
        raise ValueError("missing 'cmd' field")
    if cmd not in VALID_COMMANDS:
        raise ValueError(f"unknown command: {cmd!r}")
    return request


async def _is_listening(path: Path) -> bool:
    """True when something accepts a connection on `path`.

    This, not `probe`, decides whether an existing socket file is stale.
    A daemon busy in a long handler cannot reply promptly, but it still owns
    the microphone: judging liveness by a reply would let a second daemon
    unlink its socket and start alongside it.
    """
    try:
        _, writer = await asyncio.open_unix_connection(str(path))
    except (OSError, ConnectionError):
        return False  # refused, not a socket, or gone: nothing is listening
    writer.close()
    with contextlib.suppress(OSError, ConnectionError):
        await writer.wait_closed()
    return True


async def probe(path: Path, timeout: float = 1.0) -> bool:
    """True when a daemon is listening and answers a status request."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
    except (OSError, ConnectionError):
        return False
    try:
        writer.write(b'{"cmd": "status"}\n')
        await writer.drain()
        return bool(await asyncio.wait_for(reader.readline(), timeout=timeout))
    except (OSError, ConnectionError, TimeoutError, ValueError):
        return False
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()


@contextlib.contextmanager
def _owner_only_umask() -> Iterator[None]:
    """Create the socket unreachable by other users from the moment it exists.

    chmod after binding would leave a window in which the permissions come
    from the inherited umask, and this socket controls the microphone.
    """
    previous = os.umask(0o177)
    try:
        yield
    finally:
        os.umask(previous)


async def serve(path: Path, handler: Handler) -> asyncio.Server:
    """Bind the control socket, clearing a stale file left by a dead daemon."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if await _is_listening(path):
            raise AlreadyRunning(f"flowd is already running on {path}")
        log.info("removing stale socket %s", path)
        path.unlink(missing_ok=True)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                line = await reader.readline()
            except ValueError:
                # The line exceeded the stream limit; readline raises rather
                # than returning it, so this is the only place to catch it.
                reply: dict[str, Any] = {"ok": False, "error": "request too large"}
            else:
                if not line:
                    return
                try:
                    request = parse_command(line)
                except ValueError as exc:
                    reply = {"ok": False, "error": str(exc)}
                else:
                    try:
                        reply = await handler(request)
                    except Exception as exc:  # a bad command must not kill the daemon
                        log.exception("control handler failed")
                        reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            writer.write(json.dumps(reply).encode("utf-8") + b"\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass  # client hung up; flowctl exits immediately by design
        finally:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()

    with _owner_only_umask():
        server = await asyncio.start_unix_server(on_client, path=str(path), limit=_MAX_LINE)
    return server


async def send(path: Path, request: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    """Client side: one request, one reply. Used by flowctl and the tests."""
    reader, writer = await asyncio.open_unix_connection(str(path))
    try:
        writer.write(json.dumps(request).encode("utf-8") + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return dict(json.loads(line.decode("utf-8")))
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()
