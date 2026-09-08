import asyncio
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from flowd.control import AlreadyRunning, parse_command, probe, send, serve


def test_parse_accepts_valid_command() -> None:
    assert parse_command(b'{"cmd": "toggle"}\n') == {"cmd": "toggle"}


def test_parse_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="unknown command"):
        parse_command(b'{"cmd": "selfdestruct"}')


def test_parse_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_command(b"not json at all")


def test_parse_rejects_missing_cmd() -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_command(b'{"args": []}')


@pytest.mark.parametrize("cmd", ["[]", "{}", "5", "true", '["toggle"]'])
def test_parse_rejects_a_cmd_that_is_not_a_string(cmd: str) -> None:
    """A `cmd` of the wrong JSON type must be rejected, not crash the handler.

    `VALID_COMMANDS` is a frozenset, so the membership test hashes `cmd`, and an
    unhashable value raises TypeError instead of failing the test. `on_client`
    answers ValueError; a TypeError escapes it, so the client gets no reply at
    all — the connection just closes.
    """
    with pytest.raises(ValueError, match="unknown command"):
        parse_command(f'{{"cmd": {cmd}}}'.encode())


async def test_a_wrongly_typed_cmd_still_gets_an_error_reply(tmp_path: Path) -> None:
    """Every request gets an answer, including a nonsensical one.

    A client that receives nothing has to wait out its own timeout to learn the
    request failed, and cannot tell "the daemon rejected this" from "the daemon
    is wedged" — which is the difference `flowctl` reports to the user.
    """
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        reply = await send(sock, {"cmd": []})
        assert reply["ok"] is False
        assert "unknown command" in reply["error"]
    finally:
        server.close()
        await server.wait_closed()


async def _echo(request: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "cmd": request["cmd"]}


async def test_round_trip(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        assert await send(sock, {"cmd": "status"}) == {"ok": True, "cmd": "status"}
    finally:
        server.close()
        await server.wait_closed()


async def test_second_daemon_refuses_to_start(tmp_path: Path) -> None:
    """spec 9.5: a live socket means a daemon is already running."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        with pytest.raises(AlreadyRunning):
            await serve(sock, _echo)
    finally:
        server.close()
        await server.wait_closed()


async def test_busy_daemon_still_blocks_a_second_daemon(tmp_path: Path) -> None:
    """A daemon too busy to reply is still a daemon: its socket is not stale.

    Liveness is decided by whether the socket accepts a connection, not by
    whether a reply arrives in time; otherwise a daemon stalled mid-session
    would have its socket stolen and two processes would own the microphone.
    """

    async def hang(request: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {"ok": True}

    sock = tmp_path / "flowd.sock"
    server = await serve(sock, hang)
    try:
        with pytest.raises(AlreadyRunning):
            await serve(sock, _echo)
    finally:
        server.close()
        await server.wait_closed()


async def test_stale_socket_is_removed_and_rebound(tmp_path: Path) -> None:
    """spec 9.5: a socket file left by a killed daemon must not block startup."""
    sock = tmp_path / "flowd.sock"
    sock.write_bytes(b"")  # a plain file that nothing is listening on
    server = await serve(sock, _echo)
    try:
        assert await send(sock, {"cmd": "status"}) == {"ok": True, "cmd": "status"}
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_is_owner_only(tmp_path: Path) -> None:
    """The socket controls the microphone, so no other user may connect."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
    finally:
        server.close()
        await server.wait_closed()


async def test_probe_false_when_nothing_listening(tmp_path: Path) -> None:
    assert await probe(tmp_path / "absent.sock") is False


async def test_handler_error_returns_error_reply(tmp_path: Path) -> None:
    async def boom(request: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    sock = tmp_path / "flowd.sock"
    server = await serve(sock, boom)
    try:
        reply = await send(sock, {"cmd": "status"})
        assert reply["ok"] is False and "kaboom" in reply["error"]
    finally:
        server.close()
        await server.wait_closed()


async def test_oversized_request_is_refused_and_the_daemon_survives(tmp_path: Path) -> None:
    """A client that never sends a newline must not leave an unhandled error."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        try:
            writer.write(b"x" * (70 * 1024))  # over the line limit, no newline
            await writer.drain()
            reply = json.loads(await asyncio.wait_for(reader.readline(), timeout=2.0))
            assert reply["ok"] is False and "too large" in reply["error"]
        finally:
            writer.close()
        assert await send(sock, {"cmd": "status"}) == {"ok": True, "cmd": "status"}
    finally:
        server.close()
        await server.wait_closed()


async def test_concurrent_clients_are_all_served(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        replies = await asyncio.gather(*(send(sock, {"cmd": "status"}) for _ in range(5)))
        assert all(r["ok"] for r in replies)
    finally:
        server.close()
        await server.wait_closed()
