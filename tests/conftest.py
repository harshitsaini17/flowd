"""Suite-wide fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every XDG directory flowd resolves at a throwaway tree.

    A `Daemon` built without `metrics_path` appends to `state_dir()`. Without
    this, each test run wrote fake sessions into the owner's real metrics file,
    and `flowctl stats` counted them as dictation.

    `XDG_RUNTIME_DIR` is left alone: Wayland clients find the compositor's
    socket through it, so moving it disconnects the overlay tests. It lives
    under /run/user, not the home directory, so nothing persists there.
    """
    root = tmp_path_factory.mktemp("xdg")
    for var, sub in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_DATA_HOME", "data"),
    ):
        (root / sub).mkdir()
        monkeypatch.setenv(var, str(root / sub))
    return root
