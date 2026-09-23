"""Scoring for the personal eval set (spec 11.3).

The pure half of `eval/run_eval.py`: word error rate, the per-file record and
the run summary live here so they are unit-tested and type-checked with the
rest of the package. The runner itself only replays audio and writes JSON.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flowd.guardrails import novel_words, tokens
from flowd.metrics import _percentile


def normalise(text: str) -> list[str]:
    """Lower-cased words without punctuation, so WER scores words, not style.

    The guardrails' tokenizer, so "novel" and "wrong" mean the same word unit.
    """
    return tokens(text)


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """Word-level edit distance and reference length, for pooling across files."""
    ref, hyp = normalise(reference), normalise(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ref_word != hyp_word),  # substitution
                )
            )
        previous = current
    return previous[-1], len(ref)


def wer(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Pooled WER over (reference, hypothesis) pairs, in percent; None if empty."""
    errors = words = 0
    for reference, hypothesis in pairs:
        e, n = word_errors(reference, hypothesis)
        errors += e
        words += n
    return None if words == 0 else round(100.0 * errors / words, 2)


@dataclass(slots=True)
class FileResult:
    """One replayed recording. `raw` is the STT text before any cleanup."""

    name: str
    ref: str
    raw: str
    final: str
    record: dict[str, Any]
    raw_ref: str | None = None
    novel: list[str] = field(default_factory=list)

    @property
    def llm_tried(self) -> bool:
        """Whether a cleanup request was made: the daemon marks `cleaned` then.

        Not "not bypassed": a run without a cleanup client bypasses nothing and
        asks nothing, and would otherwise count every file as an LLM session.
        """
        return "cleaned_ms" in self.record.get("stages", {})

    @property
    def fell_back(self) -> bool:
        return bool(self.record.get("counts", {}).get("fallbacks"))

    @property
    def release_to_inject_ms(self) -> float | None:
        stages = self.record.get("stages", {})
        if "released_ms" not in stages or "inject_ms" not in stages:
            return None
        return float(stages["inject_ms"] - stages["released_ms"])


def flag_novel(result: FileResult, terms: Sequence[str] = ()) -> None:
    """List words an *accepted* LLM output added, for spec 11.3's manual review."""
    if result.llm_tried and not result.fell_back:
        result.novel, _ = novel_words(result.raw, result.final, terms)


def summarise(results: Sequence[FileResult]) -> dict[str, Any]:
    """The run's metrics, in spec 11.3's table order."""
    tried = [r for r in results if r.llm_tried]
    fallbacks = [r for r in tried if r.fell_back]
    # Single-pass records carry no `llm_chunks`: one request per session.
    chunks = sum(r.record.get("counts", {}).get("llm_chunks", 1) for r in tried)
    rejected = sum(r.record.get("counts", {}).get("fallbacks", 0) for r in tried)
    checks: dict[str, int] = {}
    errors: dict[str, int] = {}
    for r in fallbacks:
        for check, n in r.record.get("fallback_checks", {}).items():
            checks[check] = checks.get(check, 0) + n
        for error in r.record.get("errors", []):
            errors[error] = errors.get(error, 0) + 1
    latencies = [ms for r in results if (ms := r.release_to_inject_ms) is not None]
    return {
        "files": len(results),
        "raw_wer": wer([(r.raw_ref, r.raw) for r in results if r.raw_ref is not None]),
        "cleaned_wer": wer([(r.ref, r.final) for r in results]),
        "llm_sessions": len(tried),
        "llm_chunks": chunks,
        "sessions_with_fallback": len(fallbacks),
        "fallbacks": rejected,
        # spec 11.3: chunks rejected / chunks. Short-bypassed sessions never
        # reach the LLM and count in neither term.
        "fallback_rate": round(100.0 * rejected / chunks, 1) if chunks else None,
        "fallback_checks": checks,
        "fallback_errors": errors,
        "flagged_for_review": sum(1 for r in results if r.novel),
        "release_to_inject_ms": {
            "p50": _percentile(latencies, 50) if latencies else None,
            "p95": _percentile(latencies, 95) if latencies else None,
        },
    }


def load_items(data_dir: Path) -> list[tuple[Path, str, str | None]]:
    """(wav, ref, raw_ref) for each `NNN.wav` with a `NNN.ref.txt` (spec 11.3)."""
    items = []
    for wav in sorted(data_dir.glob("*.wav")):
        ref = wav.with_suffix(".ref.txt")
        if not ref.is_file():
            continue
        raw = wav.with_suffix(".raw.txt")
        raw_text = raw.read_text(encoding="utf-8").strip() if raw.is_file() else None
        items.append((wav, ref.read_text(encoding="utf-8").strip(), raw_text))
    return items
