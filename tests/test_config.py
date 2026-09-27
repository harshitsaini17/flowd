from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from flowd.config import Config, Stt, load_config, reload_config, runtime_dir, state_dir


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


def test_default_stt_model_is_small_streaming() -> None:
    # Measured on a Ryzen 5 5600H over 80 LibriSpeech test-clean clips:
    # small scored 3.71% WER against medium's 4.50% and decodes faster, so the
    # overlay keeps up with continuous speech. See ADR 0005.
    assert Stt().model == "small-streaming-en"


def test_llm_health_defaults_follow_spec_5_5() -> None:
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.llm.health_interval_s == 30
    assert cfg.llm.down_after_failures == 2
    assert cfg.llm.context_tokens == 1024


@pytest.mark.parametrize(
    "url", ["http://example.com:8177", "http://192.168.1.5:8177", "http://10.0.0.2"]
)
def test_llm_url_must_be_loopback(tmp_path: Path, url: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f'[llm]\nurl = "{url}"\n')
    with pytest.raises(ValueError, match="llm"):
        load_config(path)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9000", "http://localhost:8177", "http://[::1]:8177"]
)
def test_loopback_llm_urls_are_accepted(tmp_path: Path, url: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f'[llm]\nurl = "{url}"\n')
    assert load_config(path).llm.url == url


def test_a_non_positive_length_ratio_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[guardrails]\nlen_ratio_min = 0\n")
    with pytest.raises(ValueError, match="len_ratio_min"):
        load_config(path)


def test_default_modes_cover_common_chat_mail_and_editor_apps() -> None:
    cfg = Config()
    assert cfg.mode_for("code") == "code"
    assert cfg.mode_for("Slack") == "chat"
    assert cfg.mode_for("discord") == "chat"
    assert cfg.mode_for("thunderbird") == "email"
    assert cfg.mode_for("dev.zed.Zed") == "code"


def test_user_modes_extend_the_defaults_instead_of_replacing_them(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[modes]\n"Kiro" = "code"\n"slack" = "default"\n')
    cfg = load_config(path)
    assert cfg.mode_for("kiro") == "code"
    assert cfg.mode_for("Slack") == "default", "a user entry overrides the default"
    assert cfg.mode_for("discord") == "chat", "defaults the user did not name survive"


def test_an_unknown_mode_name_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[modes]\n"kiro" = "shouty"\n')
    with pytest.raises(ValueError, match="shouty"):
        load_config(path)


def test_the_final_model_defaults_to_parakeet() -> None:
    """ADR 0011: Moonshine previews, Parakeet commits."""
    assert Config().stt.final_model == "parakeet-tdt-0.6b-v2-int8"


def test_an_empty_final_model_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[stt]\nfinal_model = ""\n')
    assert load_config(path).stt.final_model == ""
