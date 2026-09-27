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


def test_a_comma_before_terminal_punctuation_is_dropped() -> None:
    # Seen from the cleanup LLM on the first eval run: "Pale for weariness,?"
    assert join_chunks(["Pale for weariness,?"]) == "Pale for weariness?"
    assert join_chunks(["wait ,. then go"]) == "Wait. Then go."


def test_stitch_drops_a_period_the_llm_added_at_a_mid_sentence_cut() -> None:
    from flowd.joiner import stitch

    pairs = [
        (
            "so I was thinking we should move the meeting",
            "I was thinking we should move the meeting.",
        ),
        ("to friday afternoon.", "To Friday afternoon."),
    ]
    assert stitch(pairs) == "I was thinking we should move the meeting to Friday afternoon."


def test_stitch_keeps_a_boundary_the_speaker_ended() -> None:
    from flowd.joiner import stitch

    pairs = [
        ("We should move the meeting.", "We should move the meeting."),
        ("Friday works for me.", "Friday works for me."),
    ]
    assert stitch(pairs) == "We should move the meeting. Friday works for me."


def test_stitch_keeps_a_question_mark_and_a_capital_i() -> None:
    from flowd.joiner import stitch

    pairs = [
        ("can you send it", "Can you send it?"),
        ("i need it today", "I need it today."),
    ]
    # A question the LLM recognised is kept; "I" is never lowercased.
    assert stitch(pairs) == "Can you send it? I need it today."


def test_stitch_lowercases_only_when_the_raw_continued_in_lowercase() -> None:
    from flowd.joiner import stitch

    pairs = [
        ("we deploy on", "We deploy on."),
        ("Monday morning", "Monday morning."),
    ]
    assert stitch(pairs) == "We deploy on Monday morning."


def test_a_period_the_recognizer_put_at_a_pause_is_repaired_when_the_next_chunk_is_lowercase() -> (
    None
):
    """Moonshine ends each line it commits with a period, even mid-sentence.

    A next chunk that starts in lowercase says the sentence went on, so the
    period is a seam, whether the text came from the LLM or from the fallback.
    """
    from flowd.joiner import stitch

    pairs = [
        ("When we took our seats at the breakfast.", "When we took our seats at the breakfast."),
        ("table, it was", "Table, it was."),
        ("with the feeling of being", "With the feeling of being."),
        ("no longer looked upon.", "No longer looked upon."),
        ("as connected in any way with this case.", "As connected in any way with this case."),
    ]
    assert stitch(pairs) == (
        "When we took our seats at the breakfast table, it was with the feeling of"
        " being no longer looked upon as connected in any way with this case."
    )


def test_a_real_sentence_end_before_a_capitalised_chunk_is_kept() -> None:
    from flowd.joiner import stitch

    pairs = [
        ("Ship it on Friday.", "Ship it on Friday."),
        ("Then tell the team", "Then tell the team."),
    ]
    assert stitch(pairs) == "Ship it on Friday. Then tell the team."


def test_a_question_at_a_seam_is_kept_even_before_lowercase() -> None:
    from flowd.joiner import stitch

    pairs = [("can you ship it?", "Can you ship it?"), ("and tell the team", "And tell the team.")]
    assert stitch(pairs) == "Can you ship it? And tell the team."
