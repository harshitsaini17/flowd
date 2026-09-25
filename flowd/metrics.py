"""Per-session stage timing, written as one JSON line each (spec 10.2)."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionMetrics:
    """Collects stage timings for one dictation session.

    Times are recorded from a monotonic clock and reported in milliseconds
    relative to the first mark, so records are comparable across sessions.
    """

    session_id: str
    mode: str
    clock: Callable[[], float] = time.monotonic
    app_id: str | None = None
    backend: str | None = None
    log_transcripts: bool = False
    text: str | None = None
    errors: list[str] = field(default_factory=list)
    _marks: dict[str, float] = field(default_factory=dict, init=False)
    _counts: Counter[str] = field(default_factory=Counter, init=False)
    _checks: Counter[int] = field(default_factory=Counter, init=False)
    _origin: float | None = field(default=None, init=False)

    def has(self, stage: str) -> bool:
        """True once `stage` has been marked; lets callers mark a stage only once."""
        return stage in self._marks

    def mark(self, stage: str) -> None:
        now = self.clock()
        if self._origin is None:
            self._origin = now
        self._marks[stage] = (now - self._origin) * 1000.0

    def count(self, key: str, n: int = 1) -> None:
        self._counts[key] += n

    def fail(self, check: int) -> None:
        """Record a guardrail rejection by check number (spec 7.4)."""
        self._checks[check] += 1

    def error(self, message: str) -> None:
        self.errors.append(message)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "session_id": self.session_id,
            "ts": time.time(),
            "mode": self.mode,
            "app_id": self.app_id,
            "backend": self.backend,
            "stages": {f"{k}_ms": round(v, 1) for k, v in self._marks.items()},
            "counts": dict(self._counts),
            "fallback_checks": {str(k): v for k, v in self._checks.items()},
            "errors": self.errors,
        }
        # Transcript text is opt-in only: spec 13.2 keeps what was said out of
        # the log unless the user asked for it.
        if self.log_transcripts and self.text is not None:
            record["text"] = self.text
        return record


def write_record(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_records(path: Path, last_n: int = 50) -> list[dict[str, Any]]:
    """Read up to the last `last_n` sessions; a missing log is simply empty."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-last_n:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a truncated final line must not break `flowctl stats`
    return records


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; adequate for the tens of samples we keep."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100.0 * len(ordered)) - 1))
    return ordered[index]


def summarise(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Percentiles per stage over exactly the records given.

    The "last N sessions" window of spec 10.2 is applied by `read_records`,
    which is where the log is actually read; windowing again here would
    silently shrink a caller's deliberately wider request.
    """
    buckets: dict[str, list[float]] = {}
    for record in records:
        for stage, value in record.get("stages", {}).items():
            buckets.setdefault(stage, []).append(float(value))
    return {
        stage: {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}
        for stage, values in buckets.items()
    }
