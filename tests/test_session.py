from flowd.session import Chunk, Session


def test_chunk_ids_start_at_one_and_increase() -> None:
    """spec 4: chunk ids are monotonically increasing within a session."""
    session = Session(id="s1")
    assert [session.add_chunk("a").id, session.add_chunk("b").id] == [1, 2]
    assert [c.raw for c in session.chunks] == ["a", "b"]


def test_chunk_text_prefers_polished_over_raw() -> None:
    chunk = Chunk(id=1, raw="raw words")
    assert chunk.text == "raw words"
    chunk.polished = "Raw words."
    assert chunk.text == "Raw words."


def test_empty_polished_text_is_preferred_over_raw() -> None:
    """The LLM legitimately returns "" for a chunk that was pure filler.

    `polished` is Optional, so "" means "polished to nothing", and falling
    back to raw here would re-inject the filler the cleanup removed.
    """
    chunk = Chunk(id=1, raw="um uh", polished="")
    assert chunk.text == ""


def test_resolved_is_true_only_for_terminal_states() -> None:
    assert Chunk(id=1, raw="x", state="PENDING").resolved is False
    assert Chunk(id=1, raw="x", state="INFLIGHT").resolved is False
    assert Chunk(id=1, raw="x", state="DONE").resolved is True
    assert Chunk(id=1, raw="x", state="FALLBACK").resolved is True
    assert Chunk(id=1, raw="x", state="MERGED").resolved is True


def test_visible_chunks_excludes_merged_ones() -> None:
    """A merged chunk's text now lives in its successor; counting it duplicates."""
    session = Session(id="s1")
    first = session.add_chunk("no wait")
    session.add_chunk("I mean Tuesday")
    first.state = "MERGED"
    assert [c.raw for c in session.visible_chunks()] == ["I mean Tuesday"]
