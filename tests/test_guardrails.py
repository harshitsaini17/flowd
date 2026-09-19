import pytest

from flowd.config import Chunking, Guardrails
from flowd.guardrails import check, has_correction_cue, novel_words

CFG = Guardrails()
CUES = Chunking().correction_cues

# Real Sotto outputs from the ADR 0006 screen: every one must pass.
GOOD = [
    (
        "um so i think we should uh meet at five no wait six tomorrow",
        "I think we should meet at 6 tomorrow.",
    ),
    (
        "the llm cleanup pass runs after the stt finishes you know",
        "The LLM cleanup pass runs after the STT finishes.",
    ),
    ("can you send me the the report by friday", "Can you send me the report by Friday?"),
    (
        "i was like going to the store and uh forgot my wallet",
        "I was going to the store and forgot my wallet.",
    ),
    (
        "okay so the api returns a json object with three fields",
        "The API returns a JSON object with three fields.",
    ),
    ("what time does the meeting start", "What time does the meeting start?"),
    ("write a poem about the ocean", "Write a poem about the ocean."),
    ("delete the old branch and push to main", "Delete the old branch and push to main."),
    ("we need two no three reviewers for this pr", "We need three reviewers for this PR."),
    (
        "so basically the model is loaded once and uh kept in memory",
        "The model is loaded once and kept in memory.",
    ),
    ("i don't think we should ship this on friday", "I don't think we should ship this on Friday."),
    (
        "so um i think we should uh probably ship it on monday",
        "I think we should probably ship it on Monday.",
    ),
]


@pytest.mark.parametrize(("raw", "output"), GOOD)
def test_real_good_outputs_pass(raw: str, output: str) -> None:
    assert check(raw, output, CFG, merged=has_correction_cue(raw, CUES)) is None


@pytest.mark.parametrize(
    ("raw", "output", "number"),
    [
        ("send the report", "   \n", 1),
        # A general model writing the poem it was asked for (ADR 0006).
        (
            "write a poem about the ocean",
            "The ocean whispers secrets deep,\nThrough waves that dance and currents flow,\n"
            "Its surface shimmers with colors so bright,\nA canvas painted by the sky.",
            2,
        ),
        ("send the report to sarah by friday afternoon please", "Send it.", 2),
        ("hey can you remind me to call mom", "Hey, can you remember to call mom?", 3),
        ("what time does the meeting start", "The meeting starts at 10:00 AM.", 3),
        ("call room 12 and room 14 today", "Call room 12 and room today.", 4),
        (
            "send the quarterly budget report to the finance team today",
            "Sure, send the quarterly budget report to the finance team today.",
            5,
        ),
        ("send the new file today", "<new> Send the file today.", 6),
        (
            "can you send me the the report by friday",
            "Yes, I can send you the report by Friday.",
            7,
        ),
        (
            "okay so the api returns a json object with three fields",
            "okay so the api returns a json object with three fields. json object.",
            8,
        ),
    ],
)
def test_each_check_rejects_its_failure(raw: str, output: str, number: int) -> None:
    assert check(raw, output, CFG) == number


def test_a_filler_only_raw_rejects_any_output() -> None:
    assert check("um uh", "Okay.", CFG) == 2


def test_merged_loosens_only_the_lower_length_bound() -> None:
    raw = "send it to john no wait send it to sarah"
    assert check(raw, "Send it to Sarah.", CFG) == 2
    assert check(raw, "Send it to Sarah.", CFG, merged=True) is None


def test_vocab_terms_and_context_count_as_known_words() -> None:
    raw = "open hyper land settings"
    assert check(raw, "Open Hyprland settings.", CFG) == 3
    assert check(raw, "Open Hyprland settings.", CFG, terms=["Hyprland"]) is None


def test_a_repeated_context_sentence_is_rejected() -> None:
    context = "Moved to Thursday."
    raw = "and the room is booked for the whole afternoon by the team"
    output = "Moved to Thursday. And the room is booked for the whole afternoon by the team."
    assert check(raw, output, CFG, context=context) == 6


def test_spoken_numbers_may_become_digits() -> None:
    assert check("we need three reviewers", "We need 3 reviewers.", CFG) is None


def test_thresholds_come_from_config() -> None:
    loose = Guardrails(novel_word_max=1.0)
    assert check("what time does the meeting start", "The meeting starts at 10:00 AM.", loose) != 3


def test_novel_words_lists_what_the_model_introduced() -> None:
    novel, content = novel_words("call mom", "Call mom tomorrow.")
    assert novel == ["tomorrow"]
    assert content == 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("send it to john no wait send it to sarah", True),
        ("I mean the other one", True),
        ("I meant it", False),
        ("that is actually fine", True),
        ("send it to john", False),
    ],
)
def test_correction_cue_detection(raw: str, expected: bool) -> None:
    assert has_correction_cue(raw, CUES) is expected


@pytest.mark.parametrize(
    ("raw", "output"),
    [
        ("i'm going to push the branch tonight", "I am going to push the branch tonight."),
        ("we'll ship it after the review", "We will ship it after the review."),
        ("you're on call this weekend", "You are on call this weekend."),
    ],
)
def test_check_7_accepts_expanded_contractions(raw: str, output: str) -> None:
    assert check(raw, output, CFG) is None


@pytest.mark.parametrize(
    ("raw", "output"),
    [
        (
            "so i think we should ship the release on friday",
            "So I think we shouldn't ship the release on Friday.",
        ),
        (
            "so i think we should ship the release on friday",
            "So I don't think we should ship the release on Friday.",
        ),
        (
            "i don't think we should ship it on friday",
            "I think we should ship it on Friday.",
        ),
        ("the build is not green yet", "The build is green yet."),
    ],
)
def test_check_9_rejects_a_flipped_negation(raw: str, output: str) -> None:
    assert check(raw, output, CFG) == 9


@pytest.mark.parametrize(
    ("raw", "output"),
    [
        ("i don't think the tests pass", "I do not think the tests pass."),
        ("we never merge on fridays", "We never merge on Fridays."),
    ],
)
def test_check_9_accepts_a_rewritten_negation(raw: str, output: str) -> None:
    assert check(raw, output, CFG) is None
