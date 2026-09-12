from pathlib import Path

import pytest

from flowd.config import config_dir
from flowd.vocab import Vocab, load_vocab, vocab_path


def test_missing_file_is_an_empty_vocab(tmp_path: Path) -> None:
    assert load_vocab(tmp_path / "vocab.toml") == Vocab()


def test_reads_terms_and_replacements(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text('[terms]\nLLM = "LLM"\nhypr = "Hyprland"\n\n[replace]\n"stair-tier" = "STT"\n')
    vocab = load_vocab(path)
    # The value is the canonical spelling; the key only has to be unique.
    assert vocab.terms == ("LLM", "Hyprland")
    assert vocab.replace == {"stair-tier": "STT"}


def test_terms_may_also_be_a_plain_list(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text('terms = ["LLM", "STT"]\n')
    assert load_vocab(path).terms == ("LLM", "STT")


def test_bad_toml_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text("[terms\n")
    with pytest.raises(ValueError, match=r"vocab\.toml"):
        load_vocab(path)


def test_a_term_with_a_comma_is_rejected(tmp_path: Path) -> None:
    # Moonshine joins keyterms with commas, so one containing a comma would
    # silently become two terms, or fail the whole list at the next session.
    path = tmp_path / "vocab.toml"
    path.write_text('terms = ["Smith, John"]\n')
    with pytest.raises(ValueError, match="comma"):
        load_vocab(path)


def test_non_string_values_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "vocab.toml"
    path.write_text('[replace]\n"x" = 3\n')
    with pytest.raises(ValueError, match="replace"):
        load_vocab(path)


def test_vocab_lives_beside_config() -> None:
    assert vocab_path() == config_dir() / "vocab.toml"


def test_shipped_example_loads() -> None:
    example = Path(__file__).resolve().parent.parent / "vocab.toml.example"
    vocab = load_vocab(example)
    assert "Hyprland" in vocab.terms
    assert vocab.replace["hyper land"] == "Hyprland"
