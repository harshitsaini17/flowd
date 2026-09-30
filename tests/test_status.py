import os

import pytest

from flowd import status


def test_memory_finds_this_interpreter_as_nothing() -> None:
    # The test runner is neither flowd, flowd-ui nor llama-server.
    assert all(p.pid != os.getpid() for p in status.memory())


def test_backends_report_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr("flowd.inject.base.shutil.which", lambda tool: None)
    out = status.backends(("wtype", "clipboard"))
    assert [b["name"] for b in out] == ["wtype", "clipboard"]
    assert all(b["status"] == "missing" for b in out)


def test_ydotool_without_daemon_is_stopped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr("flowd.inject.base.shutil.which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setenv("YDOTOOL_SOCKET", str(tmp_path / "none"))
    (b,) = status.backends(("ydotool",))
    assert b["status"] == "stopped" and "ydotoold" in b["reason"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hyprland", "hyprland"),
        ("sway", "sway"),
        ("KDE", "kde"),
        ("ubuntu:GNOME", "gnome"),
        ("", "other"),
    ],
)
def test_desktop(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", value)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert status.desktop() == expected
