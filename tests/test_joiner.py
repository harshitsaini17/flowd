from flowd.joiner import join_chunks


def test_joins_with_single_spaces() -> None:
    assert join_chunks(["Hello there.", "How are you?"]) == "Hello there. How are you?"


def test_removes_space_before_punctuation() -> None:
    assert join_chunks(["Hello ,", "world ."]) == "Hello, world."


def test_capitalises_sentence_starts() -> None:
    assert join_chunks(["hello there. how are you?"]) == "Hello there. How are you?"


def test_adds_terminal_punctuation_when_missing() -> None:
    assert join_chunks(["hello there"]) == "Hello there."


def test_keeps_existing_terminal_punctuation() -> None:
    assert join_chunks(["Stop!"]) == "Stop!"


def test_empty_input_yields_empty_string() -> None:
    assert join_chunks([]) == ""
    assert join_chunks(["", "  "]) == ""


def test_collapses_internal_whitespace_and_newlines() -> None:
    assert join_chunks(["hello\n  world", "again"]) == "Hello world again."


def test_does_not_double_terminal_punctuation() -> None:
    assert join_chunks(["Done.", "Really?"]) == "Done. Really?"


def test_trailing_comma_becomes_a_full_stop() -> None:
    """A comma never ends a sentence, and appending gives the visible ",." """
    assert join_chunks(["hello there,"]) == "Hello there."
    assert join_chunks(["hello there;"]) == "Hello there."


def test_trailing_colon_is_kept() -> None:
    """A colon does legitimately end dictated text that introduces a list."""
    assert join_chunks(["the steps are:"]) == "The steps are:"


def test_mid_sentence_capitals_are_preserved() -> None:
    """Proper nouns and acronyms must survive; the joiner only ever adds case."""
    assert join_chunks(["i use Hyprland with PipeWire"]) == "I use Hyprland with PipeWire."
