import pytest

from flowd.stats import overview


def rec(ts: float, words: int, mic: float, rel: float, inj: float, fb: int = 0) -> dict:
    return {
        "ts": ts,
        "mode": "code",
        "app_id": "kitty",
        "backend": "clipboard",
        "stages": {"mic_open_ms": mic, "released_ms": rel, "inject_ms": inj},
        "counts": {"words": words, "fallbacks": fb},
    }


def test_overview_derives_speaking_and_paste_times() -> None:
    out = overview([rec(100.0, 20, 0.0, 8000.0, 8450.0)], now=200.0)
    s = out["sessions"][0]
    assert s["speak_s"] == 8.0 and s["paste_ms"] == 450.0 and s["words"] == 20
    assert s["fallback"] is False


def test_overview_skips_records_without_timings() -> None:
    bad = {"ts": 1.0, "stages": {}, "counts": {}}
    assert overview([bad], now=2.0)["sessions"] == []


def test_latency_and_fallback_rate() -> None:
    recs = [rec(float(i), 5, 0, 1000, 1000 + ms) for i, ms in enumerate([400, 500, 900], 1)]
    recs[2]["counts"]["fallbacks"] = 1
    out = overview(recs, now=10.0)
    assert out["latency"] == {"p50": 500.0, "p95": 900.0, "n": 3}
    assert abs(out["fallback_rate"] - 1 / 3) < 1e-9


def test_empty_log() -> None:
    assert overview([], now=0.0) == {
        "sessions": [],
        "latency": {"p50": None, "p95": None, "n": 0},
        "fallback_rate": None,
    }


def test_no_text_is_ever_returned() -> None:
    r = rec(1.0, 3, 0, 100, 200)
    r["text"] = "secret words"
    assert "secret" not in repr(overview([r], now=2.0))


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"ts": 1.0, "stages": None, "counts": {}}, id="stages-none"),
        pytest.param({"ts": 1.0, "stages": {}, "counts": None}, id="counts-none"),
        pytest.param(
            {
                "ts": 1.0,
                "stages": {"mic_open_ms": "soon", "released_ms": 100, "inject_ms": 200},
                "counts": {},
            },
            id="string-timing",
        ),
        pytest.param(
            {
                "ts": 1.0,
                "stages": {"mic_open_ms": True, "released_ms": 100, "inject_ms": 200},
                "counts": {},
            },
            id="bool-timing",
        ),
        pytest.param(
            {
                "ts": 1.0,
                "stages": {"mic_open_ms": 0, "released_ms": 100, "inject_ms": 200},
                "counts": {"fallbacks": "yes"},
            },
            id="string-fallbacks",
        ),
        pytest.param(
            # released_ms before mic_open_ms: speak_s would be negative.
            {
                "ts": 1.0,
                "stages": {"mic_open_ms": 500, "released_ms": 100, "inject_ms": 200},
                "counts": {},
            },
            id="negative-duration",
        ),
    ],
)
def test_overview_skips_malformed_records_without_crashing(bad: dict) -> None:
    good = rec(2.0, 5, 0, 100, 200)
    out = overview([bad, good], now=3.0)
    assert len(out["sessions"]) == 1
    assert out["sessions"][0]["ts"] == 2.0
