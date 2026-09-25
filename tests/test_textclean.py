import pytest

from flowd.textclean import basic_clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("so um i think we should ship it", "So I think we should ship it."),
        ("uh hello there", "Hello there."),
        ("the the meeting is monday", "The meeting is monday."),
        ("i went to, like, the store", "I went to the store."),
        ("i like pizza", "I like pizza."),  # 'like' as a verb survives
        ("already done.", "Already done."),
        ("is it ready?", "Is it ready?"),
        ("i think i am right", "I think I am right."),  # standalone I capitalised
        ("", ""),
        ("   ", ""),
        ("um uh er", ""),  # nothing but fillers
        ("hello    world", "Hello world."),
    ],
)
def test_basic_clean(raw: str, expected: str) -> None:
    assert basic_clean(raw) == expected


def test_applies_replacements() -> None:
    assert basic_clean("i use hyper land", {"hyper land": "Hyprland"}) == "I use Hyprland."


def test_replacement_is_case_insensitive_on_input() -> None:
    assert basic_clean("Hyper Land rocks", {"hyper land": "Hyprland"}) == "Hyprland rocks."


def test_replacement_target_is_literal_text() -> None:
    """A vocab entry is text the user typed, not a regex replacement template.

    `re.sub` reads backslashes in the replacement as group references, so a
    target like `\\d` would raise `re.error` and take down the cleanup path
    for every later chunk in the session.
    """
    assert basic_clean("match slash d", {"slash d": r"\d"}) == r"Match \d."
    assert basic_clean("match group", {"group": r"\1"}) == r"Match \1."


def test_is_fast_enough() -> None:
    """spec 7.5: deterministic and under 1 ms."""
    import time

    text = "so um i think we should uh probably ship it on monday " * 20
    start = time.perf_counter()
    for _ in range(100):
        basic_clean(text)
    assert (time.perf_counter() - start) / 100 < 0.001
