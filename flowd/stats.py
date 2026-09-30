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


def overview(records: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
    """Build the settings page's stats overview from raw metrics records.

    `records` is meant to come from `read_records(path, last_n=100_000)`: the
    "All time" window needs more than the usual last-50 default, and at about
    400 bytes a line, 100k lines is tens of MB at most — fine to hold in memory
    for one request.
    """
    sessions: list[dict[str, Any]] = []
    paste_latencies_ms: list[float] = []
    fallback_count = 0

    for record in records:
        stages = record.get("stages", {})
        mic_open_ms = stages.get("mic_open_ms")
        released_ms = stages.get("released_ms")
        inject_ms = stages.get("inject_ms")
        if mic_open_ms is None or released_ms is None or inject_ms is None:
            continue

        speak_s = (released_ms - mic_open_ms) / 1000.0
        paste_ms = inject_ms - released_ms
        fallbacks = record.get("counts", {}).get("fallbacks", 0)
        is_fallback = fallbacks > 0
        if is_fallback:
            fallback_count += 1
        paste_latencies_ms.append(paste_ms)

        sessions.append(
            {
                "ts": record.get("ts"),
                "app_id": record.get("app_id"),
                "mode": record.get("mode"),
                "words": record.get("counts", {}).get("words", 0),
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
