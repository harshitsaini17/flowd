"""Tests for the commit rules (spec 5.4). Pure logic, so every rule is direct."""

from __future__ import annotations

from flowd.committer import Committer


def test_silence_commits_everything_uncommitted() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("hello there friend")
    assert c.on_silence(350) == "hello there friend"
    assert c.uncommitted_text == ""


def test_silence_below_threshold_commits_nothing() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("hello there")
    assert c.on_silence(200) is None
    assert c.uncommitted_text == "hello there"


def test_silence_with_nothing_uncommitted_returns_none() -> None:
    c = Committer(commit_silence_ms=350)
    assert c.on_silence(500) is None


def test_engine_completion_commits_the_line() -> None:
    c = Committer()
    assert c.on_complete("the whole line") == "the whole line"
    assert c.uncommitted_text == ""


def test_stable_prefix_commits_only_unchanged_words() -> None:
    """spec 5.4 rule 3: past the word cap, commit the prefix stable across 3 partials."""
    c = Committer(max_uncommitted_words=5, stability_window=3, keep_uncommitted=3)
    c.on_partial("one two three four five")
    c.on_partial("one two three four five six")
    committed = c.on_partial("one two three four five six seven")
    assert committed == "one two three four"
    assert c.uncommitted_text == "five six seven"


def test_stable_prefix_keeps_at_least_three_words_uncommitted() -> None:
    """spec 5.4 rule 3's floor: the last three words stay revisable.

    The rule fires on the *third* partial, which is when the window first holds
    three hypotheses to compare, so what this pins is the promise the rule
    actually makes — the size of the tail left behind — rather than which call
    happens to trip it.
    """
    c = Committer(max_uncommitted_words=4, stability_window=3, keep_uncommitted=3)
    c.on_partial("alpha beta gamma delta epsilon")
    c.on_partial("alpha beta gamma delta epsilon")
    assert c.on_partial("alpha beta gamma delta epsilon") == "alpha beta"
    assert c.uncommitted_text == "gamma delta epsilon"
    # The remainder is back inside the cap, so the rule stops firing.
    assert c.on_partial("alpha beta gamma delta epsilon") is None


def test_no_commit_below_the_word_cap() -> None:
    c = Committer(max_uncommitted_words=25)
    for _ in range(5):
        c.on_partial("just a few words here")
    assert c.uncommitted_text == "just a few words here"


def test_unstable_tail_is_not_committed() -> None:
    """A word that keeps changing must never be committed."""
    c = Committer(max_uncommitted_words=3, stability_window=3, keep_uncommitted=3)
    c.on_partial("one two three four")
    c.on_partial("one two three FOUR")
    committed = c.on_partial("one two three fore")
    assert committed is None or "four" not in committed.lower()


def test_revised_prefix_is_not_committed() -> None:
    """Moonshine may revise earlier words; a changed prefix is not stable."""
    c = Committer(max_uncommitted_words=3, stability_window=3, keep_uncommitted=1)
    c.on_partial("send it to john")
    c.on_partial("send it to sarah")
    committed = c.on_partial("send it to sarah")
    assert committed is None or "john" not in committed


def test_partials_after_commit_are_relative_to_committed_text() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("first part")
    c.on_silence(350)
    c.on_partial("first part second part")
    assert c.uncommitted_text == "second part"
    assert c.committed_text == "first part"


def test_finalize_commits_the_remainder() -> None:
    c = Committer()
    c.on_partial("trailing words")
    assert c.finalize() == "trailing words"
    assert c.finalize() is None


def test_finalize_with_nothing_pending_returns_none() -> None:
    assert Committer().finalize() is None


def test_empty_partial_is_harmless() -> None:
    c = Committer()
    assert c.on_partial("") is None
    assert c.on_partial("   ") is None
    assert c.uncommitted_text == ""


def test_committed_text_accumulates_across_commits() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("one")
    c.on_silence(350)
    c.on_partial("one two")
    c.on_silence(350)
    assert c.committed_text == "one two"


def test_reset_clears_all_state() -> None:
    c = Committer()
    c.on_partial("some words")
    c.reset()
    assert c.committed_text == ""
    assert c.uncommitted_text == ""


# --- Inputs the rules will meet that the rules themselves do not describe ---


def test_a_shrinking_hypothesis_commits_nothing_rather_than_guessing() -> None:
    """The engine can come back with less text than was already committed.

    Committed text is gone — handed to the scheduler and on its way to the
    target app (spec 5.4) — so there is no prefix left to match against. The
    only safe reading of a shorter hypothesis is that nothing is pending, and
    the alternative, stripping by count anyway, would slice into real words and
    commit a fragment.
    """
    c = Committer(commit_silence_ms=350)
    c.on_partial("one two three")
    c.on_silence(350)
    assert c.committed_text == "one two three"
    assert c.on_partial("one two") is None
    assert c.uncommitted_text == ""
    assert c.committed_text == "one two three"


def test_runs_of_whitespace_collapse() -> None:
    """Committed text is injected verbatim, so its spacing is not cosmetic."""
    c = Committer()
    c.on_partial("hello   there\tfriend\n")
    assert c.uncommitted_text == "hello there friend"
    assert c.finalize() == "hello there friend"


def test_completion_with_no_text_still_commits_what_is_pending() -> None:
    """`LineCompleted` is the authoritative commit signal (ADR 0001).

    An empty payload is not a reason to drop text the engine already gave: the
    pending words would otherwise sit uncommitted until finalize, or vanish.
    """
    c = Committer()
    c.on_partial("pending words")
    assert c.on_complete("") == "pending words"
    assert c.uncommitted_text == ""


def test_silence_does_not_commit_twice() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("all of it")
    assert c.on_silence(400) == "all of it"
    assert c.on_silence(900) is None


def test_text_that_never_stabilises_is_never_committed() -> None:
    """Nothing commits while the engine keeps revising, however long it gets.

    spec 5.4 offers no fourth rule, and inventing one — a length ceiling that
    commits regardless — would type text the engine was still changing, which
    spec 13.2 forbids. Release is what flushes it: `finalize`.
    """
    c = Committer(max_uncommitted_words=3, stability_window=3, keep_uncommitted=3)
    for i in range(10):
        assert c.on_partial(f"word{i} one two three four") is None
    assert c.committed_text == ""
    assert c.finalize() == "word9 one two three four"


def test_a_session_can_be_reused_after_reset() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("first session")
    c.on_silence(350)
    c.reset()
    c.on_partial("second session")
    assert c.on_silence(350) == "second session"
    assert c.committed_text == "second session"
