import json
from pathlib import Path

from flowd.metrics import SessionMetrics, read_records, summarise, write_record


def test_marks_are_relative_to_the_session_start() -> None:
    clock = iter([100.0, 100.25, 100.9])
    m = SessionMetrics(session_id="s1", mode="default", clock=lambda: next(clock))
    m.mark("mic_open")
    m.mark("first_partial")
    record = m.to_record()
    assert record["stages"]["mic_open_ms"] == 250.0
    assert record["stages"]["first_partial_ms"] == 900.0


def test_the_first_mark_is_measured_not_assumed_to_be_zero() -> None:
    """spec 10.1's first row is `t_mic_open - t_cmd` with a 100 ms budget.

    Taking the first mark as the origin reported that stage as 0.0 ms however
    long the microphone actually took to open, so the stage with the tightest
    budget in the spec was the one stage whose budget could never be checked —
    and phase 1's acceptance criterion is that every stage is timed.
    """
    clock = iter([50.0, 50.4])
    m = SessionMetrics(session_id="s1", mode="default", clock=lambda: next(clock))
    m.mark("mic_open")
    assert m.to_record()["stages"]["mic_open_ms"] == 400.0


def test_record_excludes_transcript_by_default() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    m.text = "secret words"
    assert "text" not in m.to_record()
    m.log_transcripts = True
    assert m.to_record()["text"] == "secret words"


def test_counts_and_guardrail_failures() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    m.count("words", 12)
    m.count("chunks")
    m.fail(3)
    m.fail(3)
    record = m.to_record()
    assert record["counts"]["words"] == 12
    assert record["counts"]["chunks"] == 1
    assert record["fallback_checks"] == {"3": 2}


def test_has_reports_whether_a_stage_was_marked() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    assert m.has("first_partial") is False
    m.mark("first_partial")
    assert m.has("first_partial") is True


def test_write_record_appends_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "metrics.jsonl"
    write_record({"session_id": "a"}, path)
    write_record({"session_id": "b"}, path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["session_id"] == "b"


def test_read_records_returns_empty_for_a_missing_log(tmp_path: Path) -> None:
    """`flowctl stats` runs before the first session has ever been logged."""
    assert read_records(tmp_path / "never-written.jsonl") == []


def test_read_records_skips_a_truncated_final_line(tmp_path: Path) -> None:
    """A crash mid-write leaves a partial line; stats must still report the rest."""
    path = tmp_path / "metrics.jsonl"
    path.write_text('{"session_id":"a"}\n{"session_id":"b"\n', encoding="utf-8")
    assert read_records(path) == [{"session_id": "a"}]


def test_read_records_keeps_only_the_last_n(tmp_path: Path) -> None:
    path = tmp_path / "metrics.jsonl"
    for i in range(10):
        write_record({"session_id": str(i)}, path)
    assert [r["session_id"] for r in read_records(path, last_n=3)] == ["7", "8", "9"]


def test_summarise_computes_p50_and_p95() -> None:
    records = [{"stages": {"inject_ms": float(i)}} for i in range(1, 101)]
    stats = summarise(records)
    assert stats["inject_ms"]["p50"] == 50.0
    assert stats["inject_ms"]["p95"] == 95.0


def test_summarise_handles_no_records() -> None:
    assert summarise([]) == {}
