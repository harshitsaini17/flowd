"""The suite must never touch the user's real XDG directories."""

from pathlib import Path

import pytest

from flowd.config import config_path, data_dir, runtime_dir, state_dir

# Resolved at import, before any fixture can redirect `HOME`.
REAL_HOME = Path.home().resolve()


def test_suite_never_resolves_xdg_dirs_under_the_real_home() -> None:
    # Daemons built without `metrics_path` append to `state_dir()`; pointed at
    # the real home, every test run lands fake sessions in the user's metrics
    # and `flowctl stats` reports them as dictation.
    for path in (state_dir(), data_dir(), runtime_dir(), config_path()):
        assert REAL_HOME not in path.resolve().parents


def test_the_suite_never_uses_the_real_runtime_dir() -> None:
    """The live daemon's socket and saved settings tokens live there."""
    from flowd.config import runtime_dir

    assert not str(runtime_dir()).startswith("/run/user/")


async def test_serving_the_settings_page_on_the_default_port_fails_the_test() -> None:
    from flowd.config import Settings
    from flowd.settings_server import SettingsServer, Tokens

    async def handler(*args: object) -> object:
        raise AssertionError

    server = SettingsServer(Settings().port, handler, Tokens())  # type: ignore[arg-type]
    with pytest.raises(pytest.fail.Exception, match="port 0"):
        await server.start()
