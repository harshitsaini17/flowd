# 0002: VAD from Moonshine segmentation, and dropping `onnxruntime`

Status: accepted
Phase: 2

## Context

ADR 0001 settled the question spec 5.2 asks — prefer Moonshine's own
voice-activity or segmentation support, fall back to Silero otherwise — and
found segmentation but no queryable detector. This record covers what Task 15
then had to build on that answer, because the plan's Task 15 brief was written
before ADR 0001 existed and still prescribes the Silero path it ruled out.

Re-confirmed against the installed package rather than taken from ADR 0001:

- `TranscriptLine` exposes `start_time`, `duration` and per-word `words`
  timings; `Stream` exposes `add_audio`, `start`, `stop`, `update_transcription`
  and listener management.
- Nothing in the API surface answers "is the user speaking now?". The only
  speech-adjacent exports are `moonshine_extract_speech_clip`, `SpeechClip` and
  the TTS entry points, none of which can be pointed at a transcriber.

So flowd sees the embedded detector's conclusions as line timestamps, and spec
5.2's required per-block output (`speech`/`silence` plus the current silence run)
has to be inferred from them.

### The signal

`SegmentationVad` tracks two clocks: audio fed (advanced by `block_ms` per
block) and the **frontier**, the end of the furthest line seen so far. Because
every line comes from a voice-activity segment, the frontier is the last instant
the detector judged to be speech. While someone talks it chases the fed clock;
when they stop it freezes while audio keeps arriving, and the growing gap is the
silence evidence.

Transcription lag opens the same gap, so gaps under `lag_allowance_ms` count as
speech.

### Measurement 1: how far the frontier trails

44.4s fixture (`two_cities.wav`, 48 kHz), `medium-streaming`, 100 ms blocks fed
as fast as the stream accepted them, 128 line events:

```
lag (fed - frontier): min -100 ms   p50 -80 ms   p90 180 ms   max 576 ms
```

Negative values are the frontier *ahead* of the fed clock: a line's segment
extends past the block that triggered the event.

### Measurement 2: choosing `lag_allowance_ms`

One real trace, swept offline (the VAD is pure arithmetic over it). "false runs"
are silence runs of ≥ `commit_silence_ms` (350 ms) occurring *inside* continuous
speech, each of which would commit mid-phrase:

| allowance | speech during speech | runs ≥ 350 ms |
|---|---|---|
| 300 ms | 40% | 30 |
| 500 ms | 68% | 8 |
| 700 ms | 85% | 4 |
| **900 ms** | **91%** | **2** |
| 1100 ms | 93% | 2 |
| 1800 ms | 94% | 2 |

The count stops falling at 2, which suggested those two were real pauses rather
than artifacts. Checked against per-block RMS of the same WAV — evidence
independent of Moonshine — at a threshold of 15% of the clip's own p90:

```
allowance 500 ms, runs >= 350 ms inside speech:
   0.1-  2.0s (1900 ms) mean RMS 0.0085  quiet 53%   REAL pause
   7.1-  7.5s ( 400 ms) mean RMS 0.0149  quiet  0%   ARTIFACT (audio is loud)
   9.1-  9.6s ( 500 ms) mean RMS 0.0140  quiet  0%   ARTIFACT
  15.7- 16.2s ( 500 ms) mean RMS 0.0155  quiet  0%   ARTIFACT
  17.4- 18.3s ( 900 ms) mean RMS 0.0152  quiet 11%   ARTIFACT
  21.1- 21.9s ( 800 ms) mean RMS 0.0178  quiet 12%   ARTIFACT
  29.2- 29.7s ( 500 ms) mean RMS 0.0189  quiet 20%   ARTIFACT
  42.5- 44.4s (1874 ms) mean RMS 0.0018  quiet 94%   REAL pause

allowance 900 ms: only the two REAL pauses remain.
```

Six of the eight runs at 500 ms sat over loud audio. They were manufactured by
event cadence, not by pauses.

**The first default written was 500 ms, and it was wrong** — below the 576 ms
worst-case lag already measured. The sweep is what caught it; a test now pins
the value against both numbers so it cannot drift back.

### Measurement 3: does it generalise

The default was tuned on one clip, so it was checked against two more at
different sample rates. Each clip had 3s of true silence appended:

| clip | rate | speech during speech | speech during appended silence |
|---|---|---|---|
| `two_cities.wav` (44.4s) | 48 kHz | 91% | 0/30 blocks |
| `beckett.wav` (10.0s) | 16 kHz | 87% | 1/30 blocks |
| `endgame_nagg_nell.wav` (28.3s) | 24 kHz | 90% | 13/30 blocks |

The speech figure holds across all three. The third row is the honest cost:
silence took 1300 ms to begin accruing, because the frontier ended *ahead* of
the fed clock (measurement 1's negative lag), so the gap started negative.
Silence-detection latency after true speech ends therefore ranges 100–1300 ms
across these clips.

## Options

1. **Infer speech from the frontier** (this record). No second model, no extra
   dependency, one source of truth about where speech stops. Cost: silence is
   late by up to ~1.3s, and the allowance is machine-dependent.
2. **Add `silero_vad.onnx` via `onnxruntime`**, as the Task 15 brief prescribes.
   Buys a millisecond-accurate silence signal. Costs a second copy of the same
   Silero model Moonshine already embeds, a 22.5 MB wheel, and two disagreeing
   sources of truth — the objection ADR 0001 raised, unchanged.
3. **Keep `onnxruntime` declared but unused**, deferring the choice again. Pays
   option 2's install cost for none of its benefit.

## Decision

**Option 1**, and `onnxruntime` is dropped from `pyproject.toml`.

The late-silence cost is acceptable because ADR 0001 made `LineCompleted` the
authoritative commit signal: silence is spec 5.4's *secondary* commit trigger,
so a late silence commit means text commits a moment later, not wrongly. What it
must never do is fire *early*, mid-utterance — spec 13.2 forbids typing partial
text into the target app — which is why the allowance is deliberately generous
and why the six artifact runs mattered more than the latency.

`onnxruntime` removal was deferred through phases 0 and 1 "to the task that
writes the VAD code, where the suite can prove it". It is proven here:
`tests/test_vad.py` imports `flowd.vad`, `flowd.stt` and `flowd.daemon` in fresh
interpreters and asserts `onnxruntime` is absent from `sys.modules`, and asserts
it is absent from pyproject's declared dependencies. `moonshine-voice`'s own
metadata requires it only under the `lora` and `finetune` extras, which flowd
does not install. Installs lose a 22.5 MB wheel.

## Impact on spec

- **5.2 (VAD).** No `silero_vad.onnx`, no threshold of ours, nothing added to
  `scripts/fetch_models.sh` or `models.lock`. The required per-block output is
  unchanged.
- **8 (config).** `[vad]` gains `lag_allowance_ms` (900), which the spec's
  published block does not list; it is the one tunable this inference needs, and
  spec 13.1.4 forbids leaving it as a magic number. `threshold` is kept and
  accepted but is now **inert** — there is no model of ours to threshold. It is
  not removed because `_build` rejects unknown keys, so deleting it would stop
  flowd starting for anyone who wrote a config from the spec's own text.
- **5.5 (no speech at all).** `SegmentationVad.saw_speech` distinguishes "no
  speech yet" from "lagging", which is what keeps a silent session reporting
  "No speech" instead of injecting an empty string.
- **Task 15 brief.** Its Silero implementation, its `scripts/fetch_models.sh`
  addition and its `models.lock` entry do not apply. Its `SileroOnnxVad` class
  is not written. `load_vad` keeps the brief's signature but raises no
  `FileNotFoundError`: there is no file to miss.
- **Task 17.** `observe_frontier` is on `SegmentationVad`, not on the
  `VadEngine` protocol. The wiring from Moonshine line events to the frontier
  belongs in `load_engine`, where the real stream exists; `FakeVad` scripts
  speech directly and needs no frontier.

`lag_allowance_ms` is machine-dependent: the lag it absorbs is transcription
lag, and ADR 0001 measured this machine at ~1.05× realtime with little headroom.
A slower machine lags more and may need a larger value or a smaller model. That
is a config change, not a code change, and the phase 2 report should re-measure
it with the overlay and `llama-server` competing for cores.

Spec 13.3's escalation triggers do not fire: no new dependency (one is removed),
no PyTorch, no budget miss — the commit path's budget is driven by
`LineCompleted`, not by this signal.
