"""Personal vocabulary, `$XDG_CONFIG_HOME/flowd/vocab.toml` (spec 7.6).

`[terms]` are canonical spellings. Before the LLM stage exists they bias the
speech recognizer directly (Moonshine keyterms), which is what makes acronyms
such as "LLM" come out as letters rather than as a similar-sounding word.
`[replace]` maps a known mishearing to the intended text, applied in
`basic_clean`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flowd.config import config_dir


@dataclass(frozen=True, slots=True)
class Vocab:
    terms: tuple[str, ...] = ()
    replace: Mapping[str, str] = field(default_factory=dict)


def vocab_path() -> Path:
    return config_dir() / "vocab.toml"


def _strings(value: Any, where: str) -> list[str]:
    if not all(isinstance(v, str) for v in value):
        raise ValueError(f"vocab.toml: every value in [{where}] must be a string")
    return list(value)


def load_vocab(path: Path | None = None) -> Vocab:
    """Read the vocabulary file. A missing file is an empty vocabulary.

    Raises ValueError for a file that exists but cannot be used, so `flowctl
    reload` can report it and keep the vocabulary it already has.
    """
    path = path or vocab_path()
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Vocab()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"vocab.toml: {exc}") from exc

    terms_raw = raw.get("terms", {})
    # The example file keys terms by name ("Hyprland" = "Hyprland"); a plain
    # list is the natural thing to write too, so both are accepted.
    terms = _strings(terms_raw.values() if isinstance(terms_raw, dict) else terms_raw, "terms")
    for term in terms:
        # Moonshine joins keyterms with commas internally and refuses any term
        # that contains one, which would fail every later session, not just this.
        if "," in term:
            raise ValueError(f"vocab.toml: term {term!r} contains a comma")

    replace_raw = raw.get("replace", {})
    if not isinstance(replace_raw, dict):
        raise ValueError("vocab.toml: [replace] must be a table")
    _strings(replace_raw.values(), "replace")

    return Vocab(terms=tuple(t for t in terms if t.strip()), replace=dict(replace_raw))
