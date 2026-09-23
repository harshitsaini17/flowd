from pathlib import Path
from typing import Any

import pytest

from flowd.evaluation import (
    FileResult,
    flag_novel,
    load_items,
    normalise,
    summarise,
    wer,
    word_errors,
)


def result(
    name: str = "001",
    *,
    ref: str = "ship it on friday",
    raw: str = "ship it on friday",
    final: str = "Ship it on Friday.",
    raw_ref: str | None = None,
    counts: dict[str, int] | None = None,
    checks: dict[str, int] | None = None,
    errors: list[str] | None = None,
    stages: dict[str, float] | None = None,
) -> FileResult:
    record: dict[str, Any] = {
        "counts": counts or {},
        "fallback_checks": checks or {},
        "errors": errors or [],
        "stages": stages
        if stages is not None
        else {"released_ms": 1000.0, "cleaned_ms": 1300.0, "inject_ms": 1400.0},
    }
    return FileResult(name=name, ref=ref, raw=raw, final=final, record=record, raw_ref=raw_ref)


def test_normalise_ignores_case_and_punctuation() -> None:
    assert normalise("Ship it, on Friday\u2019s build!") == [
        "ship",
        "it",
        "on",
        "friday's",
        "build",
    ]


def test_word_errors_counts_each_edit_kind() -> None:
    assert word_errors("a b c", "a b c") == (0, 3)
    assert word_errors("a b c", "a x c") == (1, 3)  # substitution
    assert word_errors("a b c", "a c") == (1, 3)  # deletion
    assert word_errors("a b c", "a b c d") == (1, 3)  # insertion
    assert word_errors("", "anything") == (1, 0)


def test_wer_pools_across_files_rather_than_averaging() -> None:
    # 1 error in 1 word and 0 in 9: pooled is 10%, a per-file mean would say 50%.
    pairs = [("one", "two"), ("a b c d e f g h i", "a b c d e f g h i")]
    assert wer(pairs) == 10.0
    assert wer([]) is None


def test_summary_rates_fallbacks_over_llm_sessions_only() -> None:
    results = [
        result("001"),
        result("002", counts={"fallbacks": 1}, checks={"3": 1}),
        result("003", counts={"fallbacks": 1}, errors=["llm: timeout"]),
        # Never reached the LLM: short-bypassed, and a run with no client at all.
        result("004", counts={"bypassed": 1}, stages={"released_ms": 0.0, "inject_ms": 9.0}),
        result("005", stages={"released_ms": 0.0, "inject_ms": 9.0}),
    ]
    summary = summarise(results)
    assert summary["llm_sessions"] == 3
    assert summary["fallbacks"] == 2
    assert summary["fallback_rate"] == pytest.approx(66.7)
    assert summary["fallback_checks"] == {"3": 1}
    assert summary["fallback_errors"] == {"llm: timeout": 1}


def test_summary_reports_both_wers_and_latency() -> None:
    results = [
        result("001", raw_ref="ship it on friday", raw="ship it on friday"),
        result("002", ref="send the file", final="Send the fire.", raw_ref=None),
    ]
    summary = summarise(results)
    assert summary["raw_wer"] == 0.0  # only files with a raw.txt count
    assert summary["cleaned_wer"] == pytest.approx(100 * 1 / 7, abs=0.01)
    assert summary["release_to_inject_ms"] == {"p50": 400.0, "p95": 400.0}


def test_summary_of_nothing_is_empty_not_a_crash() -> None:
    summary = summarise([])
    assert summary["fallback_rate"] is None
    assert summary["cleaned_wer"] is None
    assert summary["release_to_inject_ms"] == {"p50": None, "p95": None}


def test_only_accepted_llm_outputs_are_flagged_for_review() -> None:
    accepted = result(raw="ship it friday", final="Ship it on Friday morning.")
    flag_novel(accepted)
    assert accepted.novel == ["morning"]

    fallback = result(raw="ship it", final="Ship it tomorrow.", counts={"fallbacks": 1})
    flag_novel(fallback)
    assert fallback.novel == []  # basic_clean's text; nothing for a human to check


def test_vocab_terms_are_not_flagged() -> None:
    r = result(raw="open the config", final="Open the Hyprland config.")
    flag_novel(r, terms=["Hyprland"])
    assert r.novel == []


def test_load_items_pairs_audio_with_references(tmp_path: Path) -> None:
    (tmp_path / "001.wav").write_bytes(b"")
    (tmp_path / "001.ref.txt").write_text("Ship it.\n")
    (tmp_path / "001.raw.txt").write_text("ship it\n")
    (tmp_path / "002.wav").write_bytes(b"")
    (tmp_path / "002.ref.txt").write_text("Send it.\n")
    (tmp_path / "003.wav").write_bytes(b"")  # no reference: skipped
    items = load_items(tmp_path)
    assert [(w.name, ref, raw) for w, ref, raw in items] == [
        ("001.wav", "Ship it.", "ship it"),
        ("002.wav", "Send it.", None),
    ]


def test_fallback_rate_is_per_chunk_when_sessions_are_chunked() -> None:
    """spec 11.3: chunks rejected ÷ chunks. Chunked cleanup sends several per session."""
    results = [
        result("001", counts={"llm_chunks": 10, "fallbacks": 1}, checks={"3": 1}),
        result("002", counts={"llm_chunks": 10}),
    ]
    summary = summarise(results)
    assert summary["llm_chunks"] == 20
    assert summary["fallbacks"] == 1
    assert summary["fallback_rate"] == pytest.approx(5.0)
