"""Suite-wide fixtures."""

import os
from pathlib import Path
from typing import Any

import pytest

from flowd.config import Settings
from flowd.settings_server import SettingsServer


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every XDG directory flowd resolves at a throwaway tree.

    A `Daemon` built without `metrics_path` appends to `state_dir()`. Without
    this, each test run wrote fake sessions into the user's real metrics file,
    and `flowctl stats` counted them as dictation.

    `XDG_RUNTIME_DIR` moves too: the daemon keeps its socket and the settings
    page's saved tokens there, and a test must never adopt or delete the live
    daemon's. Wayland clients find the compositor's socket through it, so a
    relative `WAYLAND_DISPLAY` is made absolute first and nothing that talks
    to the compositor notices the move.
    """
    root = tmp_path_factory.mktemp("xdg")
    for var, sub in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_DATA_HOME", "data"),
    ):
        (root / sub).mkdir()
        monkeypatch.setenv(var, str(root / sub))
    real_runtime = os.environ.get("XDG_RUNTIME_DIR")
    display = os.environ.get("WAYLAND_DISPLAY")
    if real_runtime and display and not os.path.isabs(display):
        monkeypatch.setenv("WAYLAND_DISPLAY", os.path.join(real_runtime, display))
    (root / "runtime").mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root / "runtime"))
    return root


#: The settings page's default port, where the user's own daemon listens.
LIVE_SETTINGS_PORT = Settings().port


@pytest.fixture(autouse=True)
def no_live_settings_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test whose settings server would listen on the default port,
    next to the user's running daemon. Tests use port 0."""
    real_start = SettingsServer.start

    async def start(self: SettingsServer) -> Any:
        if self._requested_port == LIVE_SETTINGS_PORT:
            pytest.fail(
                f"a test tried to serve the settings page on port {LIVE_SETTINGS_PORT}, "
                "where the user's daemon listens; use port 0"
            )
        return await real_start(self)

    monkeypatch.setattr(SettingsServer, "start", start)
