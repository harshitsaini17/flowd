"""The settings page's writes to config.toml and vocab.toml (ADR 0014)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flowd.config import load_config
from flowd.config_edit import (
    Conflict,
    defaults,
    patch_config,
    read_config,
    read_vocab,
    reset_config,
    write_vocab,
)
from flowd.vocab import load_vocab

COMMENTED = """\
# my flowd config
[hotkey]
mode = "toggle"   # I use Super+D

[logging]
level = "info"
# keep this note
"""


def test_read_absent_file_gives_defaults_and_empty_etag(tmp_path: Path) -> None:
    snap = read_config(tmp_path / "config.toml")
    assert snap.etag == ""
    assert snap.values["hotkey"]["debounce_ms"] == 200
    assert snap.in_file == {}


def test_save_keeps_comments_and_unrelated_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED)
    snap = read_config(path)
    patch_config(path, snap.etag, {"hotkey.debounce_ms": 250})
    text = path.read_text()
    assert "# my flowd config" in text
    assert 'mode = "toggle"   # I use Super+D' in text
    assert "# keep this note" in text
    assert "debounce_ms = 250" in text
    assert load_config(path).hotkey.debounce_ms == 250


def test_new_section_is_appended(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED)
    patch_config(path, read_config(path).etag, {"ui.max_lines": 2})
    assert load_config(path).ui.max_lines == 2


def test_patch_with_stale_etag_is_409_and_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED)
    stale = read_config(path).etag
    path.write_text(COMMENTED + '\n[ui]\ntheme = "dark"\n')
    before = path.read_bytes()
    with pytest.raises(Conflict):
        patch_config(path, stale, {"hotkey.debounce_ms": 250})
    assert path.read_bytes() == before


def test_invalid_value_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="positive integer"):
        patch_config(path, read_config(path).etag, {"hotkey.debounce_ms": -1})
    assert path.read_bytes() == before


def test_cross_field_error_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    before = b""
    with pytest.raises(ValueError, match="min_chunk_words"):
        patch_config(path, "", {"chunking.min_chunk_words": 30})
    assert not path.exists() or path.read_bytes() == before


def test_non_loopback_llm_url_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must point at this machine"):
        patch_config(tmp_path / "config.toml", "", {"llm.url": "http://example.com:8177"})


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown"):
        patch_config(tmp_path / "config.toml", "", {"hotkey.nope": 1})


def test_none_removes_the_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[hotkey]\ndebounce_ms = 300\n")
    patch_config(path, read_config(path).etag, {"hotkey.debounce_ms": None})
    assert "debounce_ms" not in path.read_text()


def test_modes_entry_set_and_remove(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    snap, _ = patch_config(path, "", {"modes.obsidian": "email"})
    assert load_config(path).mode_for("obsidian") == "email"
    patch_config(path, snap.etag, {"modes.obsidian": None})
    assert load_config(path).mode_for("obsidian") == "default"


def test_applies_is_reported_per_key(tmp_path: Path) -> None:
    _, applied = patch_config(
        tmp_path / "config.toml", "", {"stt.model": "medium-streaming-en", "ui.fade_ms": 500}
    )
    assert applied == {"stt.model": "restart", "ui.fade_ms": "live"}


def test_write_is_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    patch_config(path, "", {"ui.theme": "dark"})
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]  # no temp file left


def test_existing_file_mode_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("")
    os.chmod(path, 0o644)
    patch_config(path, read_config(path).etag, {"ui.theme": "dark"})
    assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_reset_all_writes_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED)
    reset_config(path, read_config(path).etag, None)
    assert (tmp_path / "config.toml.bak").read_text() == COMMENTED
    assert load_config(path) == load_config(tmp_path / "absent.toml")


def test_reset_one_section_keeps_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(COMMENTED + '\n[ui]\ntheme = "dark"\n')
    reset_config(path, read_config(path).etag, "ui")
    assert load_config(path).ui.theme == "system"
    assert "# my flowd config" in path.read_text()


def test_defaults_are_json_shaped() -> None:
    d = defaults()
    assert d["inject"]["order"] == ["clipboard", "wtype", "ydotool", "xdotool"]
    assert "modes" in d and d["modes"]["code"] == "code"


def test_vocab_round_trip_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text(
        '# mine\n[terms]\nHyprland = "Hyprland"\n\n[replace]\n"hyper land" = "Hyprland"\n'
    )
    etag, data = read_vocab(path)
    assert data == {"terms": ["Hyprland"], "replace": {"hyper land": "Hyprland"}}
    write_vocab(path, etag, ["Hyprland", "PipeWire"], {"pipe wire": "PipeWire"})
    assert "# mine" in path.read_text()
    v = load_vocab(path)
    assert v.terms == ("Hyprland", "PipeWire")
    assert v.replace == {"pipe wire": "PipeWire"}


def test_vocab_term_with_comma_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comma"):
        write_vocab(tmp_path / "vocab.toml", "", ["a,b"], {})


def test_vocab_stale_etag_conflicts(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text("[terms]\n")
    etag, _ = read_vocab(path)
    path.write_text('[terms]\nX = "X"\n')
    with pytest.raises(Conflict):
        write_vocab(path, etag, [], {})


def test_vocab_plain_list_style_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text('# mine\nterms = ["Hyprland"]\n')
    etag, data = read_vocab(path)
    assert data["terms"] == ["Hyprland"]
    write_vocab(path, etag, ["Hyprland", "PipeWire"], {})
    text = path.read_text()
    assert "# mine" in text
    assert "terms = [" in text
    v = load_vocab(path)
    assert v.terms == ("Hyprland", "PipeWire")


def test_save_writes_through_a_symlinked_config(tmp_path: Path) -> None:
    """Dotfile managers link config.toml into place: the save must land in
    the real file and leave the link a link."""
    real = tmp_path / "dotfiles" / "config.toml"
    real.parent.mkdir()
    real.write_text('[hotkey]\nmode = "toggle"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(real)
    snap = read_config(link)
    patch_config(link, snap.etag, {"hotkey.mode": "ptt"})
    assert link.is_symlink()
    assert 'mode = "ptt"' in real.read_text()


def test_vocab_save_through_a_symlink_keeps_the_link(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "vocab.toml"
    real.parent.mkdir()
    real.write_text('[terms]\nkubectl = "kubectl"\n')
    link = tmp_path / "vocab.toml"
    link.symlink_to(real)
    etag, _ = read_vocab(link)
    write_vocab(link, etag, ["kubectl", "Hyprland"], {})
    assert link.is_symlink()
    assert "Hyprland" in real.read_text()


def test_vocab_save_keeps_comments_on_their_entries(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text(
        "# my words\n"
        "[terms]\n"
        "# cluster tool\n"
        'kubectl = "kubectl"  # always lower case\n'
        'nginx = "nginx"\n'
        "\n"
        "# fixes\n"
        "[replace]\n"
        '"pie torch" = "PyTorch"  # common miss\n'
    )
    etag, _ = read_vocab(path)
    write_vocab(path, etag, ["kubectl", "Hyprland"], {"pie torch": "PyTorch", "jason": "JSON"})
    text = path.read_text()
    assert '# cluster tool\nkubectl = "kubectl"  # always lower case\n' in text
    assert '"pie torch" = "PyTorch"  # common miss' in text
    assert "nginx" not in text
    # New entries land in their own table, not after the next table's comment.
    terms_part, replace_part = text.split("[replace]")
    assert "Hyprland" in terms_part
    assert "# fixes" in terms_part and terms_part.index("Hyprland") < terms_part.index("# fixes")
    assert "jason" in replace_part
    _, vocab = read_vocab(path)
    assert vocab["terms"] == ["kubectl", "Hyprland"]
    assert vocab["replace"] == {"pie torch": "PyTorch", "jason": "JSON"}
