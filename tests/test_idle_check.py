"""scripts/idle_check.py: the idle microphone check (ADR 0015)."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "idle_check.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("idle_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def client(obj_id: int, pid: int, api: str) -> dict[str, Any]:
    return {
        "id": obj_id,
        "type": "PipeWire:Interface:Client",
        "info": {"props": {"application.process.id": pid, "client.api": api}},
    }


def test_clients_owned_by_flowd_are_reported() -> None:
    """`Pa_Initialize` registers a JACK client that holds no stream but keeps
    a node running; while idle there should be none at all."""
    dump = [client(48, 1234, "jack"), client(69, 1234, "alsa"), client(7, 99, "pipewire-pulse")]
    try:
        assert load().flowd_clients(dump, {1234}) == [
            "jack client 48 (pid 1234)",
            "alsa client 69 (pid 1234)",
        ]
    finally:
        sys.modules.pop("idle_check", None)


def test_other_objects_and_processes_are_ignored() -> None:
    node = {"id": 86, "type": "PipeWire:Interface:Node", "info": {"props": {}}}
    no_info = {"id": 3, "type": "PipeWire:Interface:Client", "info": None}
    try:
        assert load().flowd_clients([node, no_info, client(7, 99, "pulse")], {1234}) == []
    finally:
        sys.modules.pop("idle_check", None)


def test_pw_dump_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """When pw-dump fails, mic_clients returns a failure string instead of raising."""
    module = load()
    try:

        def mock_run(*args: Any, **kwargs: Any) -> NoReturn:
            raise subprocess.CalledProcessError(1, "pw-dump", stderr="PipeWire not running")

        monkeypatch.setattr("idle_check.subprocess.run", mock_run)
        # CI runners have no PipeWire; pretend pw-dump is installed so the
        # failure path is reached instead of the "not installed" one.
        monkeypatch.setattr("idle_check.shutil.which", lambda name: f"/usr/bin/{name}")

        class MockProc:
            pid = 1234

        result = module.mic_clients([MockProc()])
        assert isinstance(result, str)
        assert "pw-dump failed" in result
    finally:
        sys.modules.pop("idle_check", None)
