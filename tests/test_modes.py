"""Phase 5: per-app modes as pipeline styles (spec 7.3, ADR 0009)."""

import pytest

from flowd.joiner import stitch
from flowd.modes import finish, style_for
from flowd.textclean import minimal_clean


def test_code_mode_skips_the_llm_and_sentence_casing() -> None:
    style = style_for("code")
    assert style.use_llm is False
    assert style.sentence is False


@pytest.mark.parametrize("mode", ["default", "email", "chat"])
def test_prose_modes_use_the_llm(mode: str) -> None:
    assert style_for(mode).use_llm is True


def test_an_unknown_mode_behaves_as_default() -> None:
    assert style_for("nonsense") == style_for("default")


def test_minimal_clean_removes_only_fillers() -> None:
    assert minimal_clean("um git status uh --short") == "git status --short"
    # Repeats are kept: in a command they are often meant.
    assert minimal_clean("dash dash short") == "dash dash short"
    assert minimal_clean("  ") == ""


def test_minimal_clean_applies_vocab_replacements() -> None:
    assert minimal_clean("open hyper land config", {"hyper land": "Hyprland"}) == (
        "open Hyprland config"
    )


def test_stitch_without_sentence_rules_only_joins() -> None:
    pairs = [("git commit", "git commit"), ("dash m fix", "dash m fix")]
    assert stitch(pairs, sentence=False) == "git commit dash m fix"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sounds good, see you at 6.", "Sounds good, see you at 6"),
        ("Are we still on?", "Are we still on?"),
        ("First part. Second part.", "First part. Second part"),
        ("Wait...", "Wait..."),
    ],
)
def test_chat_mode_drops_only_a_final_period(text: str, expected: str) -> None:
    assert finish(text, style_for("chat")) == expected


def test_default_and_email_leave_the_text_alone() -> None:
    for mode in ("default", "email"):
        assert finish("Hello there.", style_for(mode)) == "Hello there."


def test_config_accepts_exactly_the_modes_that_have_a_style() -> None:
    from flowd.config import _VALID_APP_MODES
    from flowd.modes import _STYLES

    assert set(_VALID_APP_MODES) == set(_STYLES)
