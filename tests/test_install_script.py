"""scripts/install.sh --dry-run: the units it would write for this machine."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def dry_run(tmp_path: Path, **env: str) -> str:
    """Run the installer with a throwaway HOME, so nothing real is touched."""
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        **env,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def test_the_daemon_unit_runs_flowd_from_this_checkout(tmp_path: Path) -> None:
    """The shipped ExecStart is a placeholder; the installer points it here."""
    out = dry_run(tmp_path)
    assert f"ExecStart={REPO}/.venv/bin/flowd" in out


def test_the_model_path_follows_xdg_data_home(tmp_path: Path) -> None:
    """systemd cannot read XDG_DATA_HOME, so the installer writes the path out."""
    out = dry_run(tmp_path)
    model = tmp_path / "data" / "flowd" / "models" / "sotto-cleanup-lfm25-350m-q4_k_m.gguf"
    assert f"Environment=FLOWD_MODEL={model}" in out


def test_llama_server_threads_can_be_overridden(tmp_path: Path) -> None:
    out = dry_run(tmp_path, FLOWD_LLM_THREADS="3")
    assert "llama-server threads: 3" in out
    assert "--port 8177 -t 3" in out


def test_a_dry_run_changes_nothing(tmp_path: Path) -> None:
    dry_run(tmp_path)
    assert not (tmp_path / "config" / "systemd").exists()
    assert not (tmp_path / "home" / ".local" / "bin").exists()


def test_an_unknown_option_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_the_ui_build_is_planned_or_explained(tmp_path: Path) -> None:
    out = dry_run(tmp_path)
    assert "would run: cmake -S" in out or "flowd-ui not built" in out


def test_skipping_the_ui_build_is_not_fatal(tmp_path: Path) -> None:
    out = dry_run(tmp_path, FLOWD_UI_BUILD="0")
    assert "flowd-ui not built" in out
    assert "Writing systemd units" in out
