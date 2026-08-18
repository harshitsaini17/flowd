from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from flowd.config import load_config, reload_config, runtime_dir, state_dir


def test_missing_file_yields_spec_defaults(tmp_path: Path) -> None:
    """A fresh install has no config.toml; the daemon must still start."""
    cfg = load_config(tmp_path / "does-not-exist.toml")
    assert cfg.vad.commit_silence_ms == 350
    assert cfg.chunking.max_chunk_words == 25
    assert cfg.inject.order == ("clipboard", "wtype", "ydotool", "xdotool")
    assert cfg.logging.log_transcripts is False


def test_partial_file_overrides_only_named_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = 500\n")
    cfg = load_config(path)
    assert cfg.vad.commit_silence_ms == 500
    assert cfg.vad.tail_ms == 150  # untouched default


def test_xdg_unset_falls_back_to_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under a bare systemd unit XDG_* may be absent; never raise KeyError."""
    for var in ("XDG_RUNTIME_DIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state_dir() == tmp_path / ".local/state/flowd"
    assert runtime_dir().is_absolute()


def test_invalid_value_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = -5\n")
    with pytest.raises(ValueError, match="commit_silence_ms"):
        load_config(path)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\nnot_a_real_key = 1\n")
    with pytest.raises(ValueError, match="not_a_real_key"):
        load_config(path)


def test_reload_keeps_old_config_on_error(tmp_path: Path) -> None:
    """spec 9.5: an invalid reload returns the error and changes nothing."""
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = 400\n")
    good = load_config(path)
    path.write_text("[vad]\ncommit_silence_ms = -1\n")
    new, error = reload_config(good, path)
    assert new is good
    assert error is not None and "commit_silence_ms" in error


def test_boolean_is_not_accepted_as_an_integer(tmp_path: Path) -> None:
    """bool subclasses int in Python, so a bare `true` must not pass as 1."""
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = true\n")
    with pytest.raises(ValueError, match="commit_silence_ms"):
        load_config(path)


def test_config_is_immutable() -> None:
    cfg = load_config(Path("/nonexistent"))
    with pytest.raises(FrozenInstanceError):
        cfg.vad.commit_silence_ms = 1  # type: ignore[misc]
