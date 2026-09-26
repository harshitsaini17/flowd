# 0004: The first-partial budget cannot be met by Moonshine streaming

**Status:** accepted
**Date:** 2026-09-26
**Task:** 17 (streaming STT engine)

## Context

spec 10.1 budgets **≤ 300 ms** from speech onset to the first partial rendered
in the overlay. With the streaming engine wired up, a real replay missed it:

```
$ uv run flowd --replay <12s clip>
TEXT: It was the best of times, it was the worst of times. ...
STAGES: {'mic_open_ms': 0.0, 'first_partial_ms': 2043.2, ...}
```

spec 13.3 makes a miss of this size an escalation trigger, and the Task 17
brief requires spec 10.4's optimisation order to be worked through before any
model change. This record is the result of doing that.

That first run also took 16 s of wall clock for 12 s of audio, which turned out
to be a defect in `--replay`'s pacer rather than anything about the engine: each
block's deadline was measured from the end of the previous wait, so a decode
burst longer than one block was added to the clip instead of caught up on the
cheap blocks after it. Fixed in this task, the same clip now releases at
12,335 ms — real time — and `first_partial_ms` reads 2,021.8 ms, unchanged,
confirming the floor below is the model's and not the harness's. The corrected
run also showed STT finalize at 13 ms, but that one reading was not
representative, and an earlier version of this record called spec 10.1's
300 ms release-to-commit budget "met with room to spare" on the strength of it.
Finalize decodes whatever audio is still behind when the key is released, so it
ranges from ~10 ms to ~850 ms on this machine depending on backlog and load; the
phase 2 report's idle sweep puts it at p50 287 ms, p95 806 ms.

Two corrections to the headline number first, because both were needed before
the miss could be sized honestly:

- **`first_partial_ms` is session-relative, not onset-relative.** It counts from
  the hotkey, so it includes however long the user waited before speaking. spec
  10.1's stage is "speech onset to first render". The clip carries ~1 s of
  leading room, which is why 2043 ms overstates the miss.
- **Speech onset in that clip is ~992 ms**, per Moonshine's own
  `line.start_time`, not the ~500 ms an RMS threshold suggested (a low-level
  blip at 500 ms trips the threshold before the speaker starts).

Onset-relative, the real miss is **~810 ms against a 300 ms budget**.

## Measurements

All on the reference machine, `medium-streaming-en`, 100 ms blocks, fed as fast
as the stream accepts. Two clips of different phrasing: a 12 s narration clip
and `beckett.wav` from the package's own assets (10 s, short phrases).

### 1. `update_interval` does not move the first event

| `update_interval` | first event (audio fed) | events | compute | xRT |
| --- | --- | --- | --- | --- |
| 200 ms | 1800 ms | 38 | 6.07 s | 0.51 |
| 300 ms | 2000 ms | 32 | 5.53 s | 0.46 |
| 500 ms | 1600 ms | 39 | 5.95 s | 0.50 |
| 800 ms | 1700 ms | 27 | 4.64 s | 0.39 |

The cadence changes how *often* lines update and not when the first one
arrives. It also shows there is no compute problem to optimise: the decoder
runs at **0.4-0.5× realtime**, so the daemon is waiting on the model's own
gating, not on cores.

### 2. The gate is a warm-up floor, not phrase completion

Per-event trace, latencies relative to Moonshine's reported onset:

| clip | onset | first event | first non-empty text | `is_complete` at first text |
| --- | --- | --- | --- | --- |
| 12 s narration | 992 ms | +808 ms | +808 ms | false |
| `beckett.wav` | 96 ms | +604 ms | +1104 ms | false |

Both clips emit their first line **mid-phrase, uncompleted**, so the stream is
not withholding text until a segment closes — it withholds until it has
~600-800 ms of audio. On `beckett.wav` the first event carries empty text and
usable text arrives 500 ms later still.

### 3. A smaller architecture buys CPU and no latency

| arch | clip | first event | first text | xRT |
| --- | --- | --- | --- | --- |
| `medium-streaming` | narration | +808 ms | +808 ms | 0.49 |
| `medium-streaming` | `beckett` | +604 ms | +1104 ms | 0.34 |
| `small-streaming` | narration | +808 ms | +808 ms | 0.39 |
| `small-streaming` | `beckett` | +604 ms | +1104 ms | 0.26 |
| `tiny-streaming` | narration | +808 ms | +808 ms | 0.20 |
| `tiny-streaming` | `beckett` | +604 ms | +604 ms | 0.15 |

First-event latency is **identical to the millisecond** across three
architectures spanning a 2.5× spread in compute. The floor is a property of the
streaming frontend, not of model size: `streaming_config.json` declares
`frame_len: 80` and `total_lookahead: 16`, and the frontend's convolution
buffers have to fill before the decoder is fed at all.

This is the measurement that matters for spec 10.4, whose remaining step is a
fallback model. There is no accuracy-for-latency trade to make here — a smaller
model trades accuracy for CPU headroom flowd does not currently need.

## Options

1. **Accept the floor; record the achievable budget.** ~800-1100 ms from onset
   to first partial, on an engine that runs at 0.4-0.5× realtime with correct
   text. Costs: the overlay is blank for ~0.8 s after the user starts talking,
   which reads as an unresponsive tool unless the overlay says it is listening.
2. **Drop to `small-` or `tiny-streaming`.** Rejected on measurement 3: zero
   latency benefit, real accuracy cost.
3. **Add a warm-up decode.** Batch-transcribe the first few hundred ms
   alongside the stream and show that as the first partial. Feasible —
   `transcribe_without_streaming` on 1 s of audio takes ~10 ms here — but it
   means two decoders producing text for the same words, a reconciliation rule
   for when the stream's first line disagrees, and double CPU at the moment of
   session start. It is a second architecture in service of one number.

## Decision

**Option 1 for phase 2.** The streaming engine keeps `medium-streaming-en` and
the honest number goes in the phase 2 report: first partial lands ~800-1100 ms
after speech onset, against a 300 ms budget written before the engine was
chosen.

Option 3 is the identified remedy and is deliberately **not** taken as a side
effect of Task 17. Adding a shadow decoder changes the pipeline's shape, and
spec 13.3 exists so that a miss this size reaches the owner as a decision
rather than being absorbed by an implementation. It is on the table at the
phase 2 checkpoint with its cost already measured.

## Impact on spec

- **10.1 (stage budgets).** "Speech → first partial ≤ 300 ms" is not
  achievable with Moonshine streaming and no model choice changes that. The
  measured floor is ~600-800 ms to any line and ~800-1100 ms to renderable
  text. The budget needs revising to the engine's reality, or the engine needs
  option 3, which is the checkpoint's call.
- **10.2 (session metrics).** `first_partial_ms` is session-relative and so is
  not the stage 10.1 defines. Reading it as the budget overstates the miss by
  however long the user paused before speaking. Either the metric should be
  re-based on the first line's `start_time`, or 10.1 should say plainly that
  the logged figure includes lead-in silence.
- **5.2 / overlay.** The ~0.8 s of blank overlay is now a known property, not a
  bug to chase. The overlay wants a visible listening state for that window
  (Task 18/19), which is what keeps the floor from reading as a hang.
- **10.4 (optimisation order).** Steps 1-2 are LLM-side; ONNX Runtime thread
  counts are not exposed by `moonshine-voice`, which ships its own runtime
  inside `libmoonshine.so`, and measurement 1 shows compute is not the
  constraint in any case. Step 5's fallback model is measured here and does not
  help. For this budget the order is exhausted.
