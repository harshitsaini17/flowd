"""The suite must never touch the owner's real XDG directories."""

from pathlib import Path

from flowd.config import config_path, data_dir, runtime_dir, state_dir

# Resolved at import, before any fixture can redirect `HOME`.
REAL_HOME = Path.home().resolve()


def test_suite_never_resolves_xdg_dirs_under_the_real_home() -> None:
    # Daemons built without `metrics_path` append to `state_dir()`; pointed at
    # the real home, every test run lands fake sessions in the owner's metrics
    # and `flowctl stats` reports them as dictation.
    for path in (state_dir(), data_dir(), runtime_dir(), config_path()):
        assert REAL_HOME not in path.resolve().parents
