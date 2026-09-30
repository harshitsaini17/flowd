"""Overview numbers for the settings page (design.md), built from `metrics.jsonl`.

Per-app, "time saved" and "recent" breakdowns are computed in JS from the
"sessions" list this returns (design.md's formula), since typing speed is a
per-browser setting the server has no reason to know. This module only derives
the per-session fields that require the raw stage timings, plus latency and
the fallback rate over the whole log.
"""

from __future__ import annotations

from typing import Any

from flowd.metrics import percentile


def _number(value: Any) -> float | None:
    """`value` as a float, or None if it isn't a plausible number.

    `bool` is a subclass of `int` in Python, so `isinstance(True, (int, float))`
    is True; excluded explicitly so a stray `true`/`false` in the log can never
    be mistaken for a timing or a count.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def overview(records: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
    """Build the settings page's stats overview from raw metrics records.

    `records` is meant to come from `read_records(path, last_n=100_000)`: the
    "All time" window needs more than the usual last-50 default, and at about
    400 bytes a line, 100k lines is tens of MB at most — fine to hold in memory
    for one request.

    A record is skipped, rather than raising, when: `stages` or `counts` isn't
    a dict, a required timing is missing or not a plausible number, or the
    derived `speak_s`/`paste_ms` comes out negative (clock-order corruption —
    e.g. a truncated or otherwise corrupted log line). One bad line must not
    take down the whole overview. `words` of the wrong type counts as 0 rather
    than skipping the record, since a garbled word count doesn't cast doubt on
    the record's timings.
    """
    sessions: list[dict[str, Any]] = []
    paste_latencies_ms: list[float] = []
    fallback_count = 0

    for record in records:
        stages = record.get("stages")
        counts = record.get("counts")
        if not isinstance(stages, dict) or not isinstance(counts, dict):
            continue

        mic_open_ms = _number(stages.get("mic_open_ms"))
        released_ms = _number(stages.get("released_ms"))
        inject_ms = _number(stages.get("inject_ms"))
        if mic_open_ms is None or released_ms is None or inject_ms is None:
            continue

        speak_s = (released_ms - mic_open_ms) / 1000.0
        paste_ms = inject_ms - released_ms
        if speak_s < 0 or paste_ms < 0:
            continue

        fallbacks = _number(counts.get("fallbacks", 0))
        if fallbacks is None:
            continue
        is_fallback = fallbacks > 0
        if is_fallback:
            fallback_count += 1
        paste_latencies_ms.append(paste_ms)

        words = _number(counts.get("words", 0))

        sessions.append(
            {
                "ts": record.get("ts"),
                "app_id": record.get("app_id"),
                "mode": record.get("mode"),
                "words": int(words) if words is not None else 0,
                "speak_s": speak_s,
                "paste_ms": paste_ms,
                "fallback": is_fallback,
                "backend": record.get("backend"),
            }
        )

    n = len(sessions)
    latency = {
        "p50": percentile(paste_latencies_ms, 50) if n else None,
        "p95": percentile(paste_latencies_ms, 95) if n else None,
        "n": n,
    }
    fallback_rate = fallback_count / n if n else None

    return {"sessions": sessions, "latency": latency, "fallback_rate": fallback_rate}
