"""Configuration: XDG paths, TOML loading, validation and reload (spec 8.1)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

APP = "flowd"


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _xdg(var: str, default: str) -> Path:
    """Resolve an XDG base directory, falling back when the variable is unset."""
    value = os.environ.get(var)
    if value:
        return Path(value)
    return _home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def runtime_dir() -> Path:
    """XDG_RUNTIME_DIR is absent under some systemd units; degrade to /tmp."""
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value) / APP
    return Path(f"/tmp/{APP}-{os.getuid()}")


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass(frozen=True, slots=True)
class Hotkey:
    mode: str = "toggle"  # toggle | ptt
    debounce_ms: int = 200


@dataclass(frozen=True, slots=True)
class Audio:
    device: str = "default"
    sample_rate: int = 16000
    block_ms: int = 100
    always_open: bool = False
    preroll_ms: int = 300
    max_session_s: int = 300


@dataclass(frozen=True, slots=True)
class Vad:
    # Inert since ADR 0002: with Moonshine's own segmentation supplying the
    # speech signal there is no model of ours to threshold. It is still
    # accepted, because `_build` rejects unknown keys and a config written
    # from spec 8's published `[vad]` block would otherwise stop flowd from
    # starting. ADR 0002 records both facts.
    threshold: float = 0.5
    commit_silence_ms: int = 350
    tail_ms: int = 150
    # How far the transcript frontier may trail the audio already fed before
    # the gap counts as silence rather than transcription lag. Swept against a
    # real 44s stream on the reference machine (ADR 0002): per-event lag runs
    # p50 -80 ms, p90 180 ms, max 576 ms, and at 500 ms six stretches of
    # continuously loud audio still accrued enough silence to commit mid-phrase.
    # At 900 ms only the clip's two genuine pauses did. Raising this delays a
    # commit; lowering it invents pauses, which is the worse failure.
    lag_allowance_ms: int = 900


@dataclass(frozen=True, slots=True)
class Stt:
    model: str = "small-streaming-en"  # ADR 0005
    max_uncommitted_words: int = 25


@dataclass(frozen=True, slots=True)
class Chunking:
    min_chunk_words: int = 5
    max_chunk_words: int = 25
    context_sentences: int = 2
    short_bypass_words: int = 5
    correction_cues: tuple[str, ...] = (
        "no wait",
        "no no",
        "actually",
        "i mean",
        "sorry",
        "scratch that",
        "let me rephrase",
    )


@dataclass(frozen=True, slots=True)
class Llm:
    url: str = "http://127.0.0.1:8177"
    timeout_ms: int = 2000
    final_timeout_ms: int = 800
    max_tokens_factor: float = 1.5


@dataclass(frozen=True, slots=True)
class Guardrails:
    len_ratio_min: float = 0.6
    len_ratio_max: float = 1.3
    len_ratio_min_merged: float = 0.3
    novel_word_max: float = 0.20


@dataclass(frozen=True, slots=True)
class Inject:
    order: tuple[str, ...] = ("clipboard", "wtype", "ydotool", "xdotool")
    restore_delay_ms: int = 150
    terminal_apps: tuple[str, ...] = (
        "kitty",
        "Alacritty",
        "foot",
        "org.wezfurlong.wezterm",
        "konsole",
        "org.gnome.Terminal",
    )


@dataclass(frozen=True, slots=True)
class Overlay:
    enabled: bool = True
    max_lines: int = 4
    fade_ms: int = 1000


@dataclass(frozen=True, slots=True)
class Logging:
    level: str = "info"
    log_transcripts: bool = False  # never true by default (spec 13.2)


@dataclass(frozen=True, slots=True)
class Config:
    hotkey: Hotkey = Hotkey()
    audio: Audio = Audio()
    vad: Vad = Vad()
    stt: Stt = Stt()
    chunking: Chunking = Chunking()
    llm: Llm = Llm()
    guardrails: Guardrails = Guardrails()
    inject: Inject = Inject()
    overlay: Overlay = Overlay()
    logging: Logging = Logging()
    modes: tuple[tuple[str, str], ...] = (
        ("code", "code"),
        ("org.telegram.desktop", "chat"),
        ("thunderbird", "email"),
    )

    def mode_for(self, app_id: str | None) -> str:
        """Map an app id to a cleanup mode; unknown or None means default."""
        if app_id is None:
            return "default"
        return dict(self.modes).get(app_id, "default")


_POSITIVE_INT = {
    "debounce_ms",
    "sample_rate",
    "block_ms",
    "preroll_ms",
    "max_session_s",
    "commit_silence_ms",
    "tail_ms",
    "lag_allowance_ms",
    "max_uncommitted_words",
    "min_chunk_words",
    "max_chunk_words",
    "context_sentences",
    "short_bypass_words",
    "timeout_ms",
    "final_timeout_ms",
    "restore_delay_ms",
    "max_lines",
    "fade_ms",
}
_UNIT_FLOAT = {"threshold", "novel_word_max"}
_VALID_HOTKEY_MODES = ("toggle", "ptt")
_VALID_LOG_LEVELS = ("debug", "info", "warning", "error")


def _build(section_type: type, raw: dict[str, Any], name: str) -> Any:
    known = {f.name for f in fields(section_type)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"[{name}]: unknown key(s): {', '.join(sorted(unknown))}")
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        kwargs[key] = tuple(value) if isinstance(value, list) else value
    section = section_type(**kwargs)
    _validate_section(section, name)
    return section


def _validate_section(section: Any, name: str) -> None:
    for field in fields(section):
        value = getattr(section, field.name)
        # bool is a subclass of int, so it must be excluded explicitly or
        # `commit_silence_ms = true` would validate as the integer 1.
        if field.name in _POSITIVE_INT and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError(f"[{name}] {field.name}: must be a positive integer, got {value!r}")
        if field.name in _UNIT_FLOAT:
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError(f"[{name}] {field.name}: must be a number, got {value!r}")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"[{name}] {field.name}: must be between 0 and 1, got {value!r}")


def _validate(cfg: Config) -> None:
    if cfg.hotkey.mode not in _VALID_HOTKEY_MODES:
        raise ValueError(f"[hotkey] mode: must be one of {_VALID_HOTKEY_MODES}")
    if cfg.logging.level not in _VALID_LOG_LEVELS:
        raise ValueError(f"[logging] level: must be one of {_VALID_LOG_LEVELS}")
    if cfg.chunking.min_chunk_words > cfg.chunking.max_chunk_words:
        raise ValueError("[chunking] min_chunk_words must not exceed max_chunk_words")
    if cfg.guardrails.len_ratio_min > cfg.guardrails.len_ratio_max:
        raise ValueError("[guardrails] len_ratio_min must not exceed len_ratio_max")
    if not cfg.inject.order:
        raise ValueError("[inject] order: must list at least one backend")


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, or return spec defaults when the file is absent."""
    path = path or config_path()
    if not path.is_file():
        return Config()
    raw = tomllib.loads(path.read_text())

    defaults = Config()
    section_names = {f.name for f in fields(Config)}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in section_names:
            raise ValueError(f"unknown config section: [{key}]")
        if not isinstance(value, dict):
            raise ValueError(f"[{key}]: expected a table")
        if key == "modes":
            kwargs["modes"] = tuple(sorted((str(k), str(v)) for k, v in value.items()))
            continue
        kwargs[key] = _build(type(getattr(defaults, key)), value, key)

    cfg = replace(defaults, **kwargs)
    _validate(cfg)
    return cfg


def reload_config(current: Config, path: Path | None = None) -> tuple[Config, str | None]:
    """spec 9.5: on a validation error keep the old config and report why."""
    try:
        return load_config(path), None
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return current, str(exc)
