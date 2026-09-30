from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from flowd import config
from flowd.config import (
    Config,
    Stt,
    load_config,
    reload_config,
    runtime_dir,
    state_dir,
    ui_message,
)


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


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_ui_defaults_match_spec() -> None:
    ui = Config().ui
    assert (ui.enabled, ui.indicator, ui.theme, ui.max_lines, ui.fade_ms, ui.footer) == (
        True,
        True,
        "system",
        4,
        1000,
        True,
    )
    assert ui.notify_on_finish is False
    assert ui.hotkey_label == ""


@pytest.fixture
def overlay_not_yet_warned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The [overlay] warning is once per process; give each test a fresh one."""
    monkeypatch.setattr(config, "_overlay_warned", False)


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_an_overlay_section_still_loads_into_ui(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_config(write_config(tmp_path, "[overlay]\nmax_lines = 6\nfade_ms = 500\n"))
    assert (cfg.ui.max_lines, cfg.ui.fade_ms) == (6, 500)
    assert "[overlay] is deprecated" in caplog.text


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_ui_keys_win_over_overlay_keys(tmp_path: Path) -> None:
    cfg = load_config(
        write_config(tmp_path, '[overlay]\nmax_lines = 6\n[ui]\nmax_lines = 2\ntheme = "dark"\n')
    )
    assert cfg.ui.max_lines == 2
    assert cfg.ui.theme == "dark"


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_a_disabled_overlay_disables_the_ui(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path, "[overlay]\nenabled = false\n")).ui.enabled is False


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_an_overlay_section_keeps_its_old_key_checks(tmp_path: Path) -> None:
    """Only the three legacy keys were ever valid there; [ui]-only keys are not."""
    with pytest.raises(ValueError, match=r"\[overlay\]: unknown key"):
        load_config(write_config(tmp_path, '[overlay]\ntheme = "dark"\n'))


def test_an_unknown_theme_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[ui\] theme"):
        load_config(write_config(tmp_path, '[ui]\ntheme = "neon"\n'))


def test_ui_max_lines_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[ui\] max_lines"):
        load_config(write_config(tmp_path, "[ui]\nmax_lines = 0\n"))


def test_the_ui_message_carries_display_settings_only() -> None:
    msg = ui_message(Config())
    assert msg["theme"] == "system"
    assert msg["max_session_s"] == Config().audio.max_session_s
    assert "enabled" not in msg and "notify_on_finish" not in msg
    assert set(msg) == {
        "indicator",
        "theme",
        "max_lines",
        "fade_ms",
        "footer",
        "hotkey_label",
        "max_session_s",
    }


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_the_overlay_deprecation_is_logged_once_per_process(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write_config(tmp_path, "[overlay]\nmax_lines = 3\n")
    load_config(path)
    load_config(path)  # a reload
    assert caplog.text.count("[overlay] is deprecated") == 1


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("[ui]\nmax_lines = 7\n", "max_lines"),
        ("[ui]\nfade_ms = -1\n", "fade_ms"),
        ("[ui]\nfade_ms = 10001\n", "fade_ms"),
        ("[ui]\nfade_ms = true\n", "fade_ms"),
        ("[audio]\nmax_session_s = 0\n", "max_session_s"),
        ("[audio]\nmax_session_s = 3601\n", "max_session_s"),
    ],
)
def test_out_of_range_ui_and_session_values_are_refused(
    tmp_path: Path, text: str, key: str
) -> None:
    section = text[1 : text.index("]")]
    with pytest.raises(ValueError, match=rf"\[{section}\] {key}"):
        load_config(write_config(tmp_path, text))


@pytest.mark.parametrize(
    ("text", "attr", "value"),
    [
        ("[ui]\nmax_lines = 1\n", ("ui", "max_lines"), 1),
        ("[ui]\nmax_lines = 6\n", ("ui", "max_lines"), 6),
        ("[ui]\nfade_ms = 0\n", ("ui", "fade_ms"), 0),  # no hold
        ("[ui]\nfade_ms = 10000\n", ("ui", "fade_ms"), 10000),
        ("[audio]\nmax_session_s = 1\n", ("audio", "max_session_s"), 1),
        ("[audio]\nmax_session_s = 3600\n", ("audio", "max_session_s"), 3600),
    ],
)
def test_range_bounds_are_accepted(
    tmp_path: Path, text: str, attr: tuple[str, str], value: int
) -> None:
    cfg = load_config(write_config(tmp_path, text))
    assert getattr(getattr(cfg, attr[0]), attr[1]) == value


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_a_bad_overlay_value_is_reported_against_overlay(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[overlay\] max_lines"):
        load_config(write_config(tmp_path, "[overlay]\nmax_lines = 0\n"))


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_a_non_table_ui_next_to_overlay_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[ui\]: expected a table"):
        load_config(write_config(tmp_path, "ui = 3\n[overlay]\nmax_lines = 3\n"))


def test_hotkey_label_must_be_a_string(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[ui\] hotkey_label: must be a string"):
        load_config(write_config(tmp_path, "[ui]\nhotkey_label = 5\n"))


@pytest.mark.usefixtures("overlay_not_yet_warned")
def test_overlay_only_values_reach_the_ui_message(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, "[overlay]\nmax_lines = 5\nfade_ms = 0\n"))
    msg = ui_message(cfg)
    assert (msg["max_lines"], msg["fade_ms"]) == (5, 0)
