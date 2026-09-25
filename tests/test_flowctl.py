import asyncio
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from flowd.config import runtime_dir
from flowd.control import serve

FLOWCTL = Path(__file__).resolve().parents[1] / "flowctl"


def load_flowctl() -> ModuleType:
    """Import `flowctl` as a module despite having no .py extension.

    Importing it lets the socket-path test compare the client's own logic
    against the daemon's, which is the only thing keeping the deliberate
    duplication in `flowctl` honest.
    """
    loader = importlib.machinery.SourceFileLoader("flowctl_under_test", str(FLOWCTL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


async def _handler(request: dict[str, Any]) -> dict[str, Any]:
    if request["cmd"] == "last":
        return {"ok": True, "text": "hello world"}
    if request["cmd"] == "stats":
        return {"ok": True, "stats": {"total_ms": {"p50": 900.0}}}
    if request["cmd"] == "cancel":
        return {"ok": False, "error": "nothing to cancel"}
    return {"ok": True, "state": "idle", "rewrite": request.get("rewrite", False)}


def _run(args: list[str], sock: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FLOWCTL), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env={"FLOWD_SOCKET": str(sock), "PATH": "/usr/bin:/bin"},
        check=False,
    )


async def test_toggle_prints_reply(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        result = await asyncio.to_thread(_run, ["toggle"], sock)
        assert result.returncode == 0
        assert "idle" in result.stdout
    finally:
        server.close()
        await server.wait_closed()


async def test_last_prints_bare_text(tmp_path: Path) -> None:
    """`flowctl last` is meant for piping, so it prints text with no JSON."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        result = await asyncio.to_thread(_run, ["last"], sock)
        assert result.stdout.strip() == "hello world"
    finally:
        server.close()
        await server.wait_closed()


async def test_rewrite_flag_reaches_the_daemon(tmp_path: Path) -> None:
    """`--rewrite` is a modifier on the request, not a command of its own."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        plain = await asyncio.to_thread(_run, ["toggle"], sock)
        flagged = await asyncio.to_thread(_run, ["toggle", "--rewrite"], sock)
        assert json.loads(plain.stdout)["rewrite"] is False
        assert json.loads(flagged.stdout)["rewrite"] is True
    finally:
        server.close()
        await server.wait_closed()


async def test_refusal_from_the_daemon_exits_nonzero(tmp_path: Path) -> None:
    """A hotkey script needs `ok: false` to be a failing exit status."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        result = await asyncio.to_thread(_run, ["cancel"], sock)
        assert result.returncode != 0
        assert "nothing to cancel" in result.stdout
    finally:
        server.close()
        await server.wait_closed()


def test_no_daemon_exits_nonzero_with_message(tmp_path: Path) -> None:
    result = _run(["status"], tmp_path / "absent.sock")
    assert result.returncode != 0
    assert "not running" in result.stderr.lower()


def test_unknown_command_exits_nonzero(tmp_path: Path) -> None:
    result = _run(["explode"], tmp_path / "absent.sock")
    assert result.returncode != 0
    assert "usage" in (result.stderr + result.stdout).lower()


def test_no_arguments_reports_usage_on_stderr(tmp_path: Path) -> None:
    """A usage error must not reach stdout, which callers pipe as data."""
    result = _run([], tmp_path / "absent.sock")
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""


def test_help_is_not_an_error(tmp_path: Path) -> None:
    result = _run(["--help"], tmp_path / "absent.sock")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_malformed_reply_is_reported(tmp_path: Path) -> None:
    """A daemon mid-upgrade could answer with something that is not JSON."""
    sock = tmp_path / "flowd.sock"

    async def scenario() -> subprocess.CompletedProcess[str]:
        async def on_client(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(b"not json at all\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(on_client, path=str(sock))
        try:
            return await asyncio.to_thread(_run, ["status"], sock)
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(scenario())
    assert result.returncode != 0
    assert "malformed" in result.stderr.lower()


def test_reply_that_is_valid_json_but_not_an_object_is_reported(tmp_path: Path) -> None:
    """`json.loads("123")` succeeds, and a bare int has no `.get`.

    Without a type check that is an AttributeError traceback in the user's
    terminal on every hotkey press, rather than a diagnosable message.
    """
    sock = tmp_path / "flowd.sock"

    async def scenario() -> subprocess.CompletedProcess[str]:
        async def on_client(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(b"123\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(on_client, path=str(sock))
        try:
            return await asyncio.to_thread(_run, ["status"], sock)
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(scenario())
    assert result.returncode != 0
    assert "malformed" in result.stderr.lower()
    assert "Traceback" not in result.stderr


# --- The duplication contract -----------------------------------------------


def test_imports_nothing_heavy() -> None:
    """The 50 ms budget (spec 5.9) rules out numpy and onnxruntime."""
    source = FLOWCTL.read_text()
    for banned in ("import numpy", "import onnxruntime", "from flowd", "import flowd"):
        assert banned not in source, f"flowctl must not {banned}"


@pytest.mark.parametrize("xdg", ["/run/user/1000", None])
def test_socket_path_matches_the_daemon(monkeypatch: pytest.MonkeyPatch, xdg: str | None) -> None:
    """flowctl must dial exactly where the daemon listens, in both XDG states.

    `flowctl` cannot import `flowd.config` — that would pull in numpy and blow
    the 50 ms budget — so it reimplements `runtime_dir()`. This test is what
    keeps the copy correct, and it caught a real divergence: with
    XDG_RUNTIME_DIR unset (spec 9: absent under some systemd units) the daemon
    listens on /tmp/flowd-<uid>/flowd.sock, because that fallback directory
    already carries the app name, while appending "flowd" again dials
    /tmp/flowd-<uid>/flowd/flowd.sock and every hotkey press reports that flowd
    is not running.
    """
    monkeypatch.delenv("FLOWD_SOCKET", raising=False)
    if xdg is None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    else:
        monkeypatch.setenv("XDG_RUNTIME_DIR", xdg)

    flowctl = load_flowctl()
    assert flowctl.socket_path() == str(runtime_dir() / "flowd.sock")


def test_flowd_socket_env_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLOWD_SOCKET", "/tmp/explicit.sock")
    assert load_flowctl().socket_path() == "/tmp/explicit.sock"


def test_every_daemon_command_is_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command the daemon accepts but flowctl rejects is unreachable by hotkey."""
    from flowd.control import VALID_COMMANDS

    assert set(load_flowctl().COMMANDS) == set(VALID_COMMANDS)
