# 0005: Default to Moonshine Small Streaming

**Status:** accepted (owner-approved, 2026-09-26)
**Date:** 2026-09-26

## Context

spec 3 fixes the STT model as Moonshine Medium Streaming and allows a
substitution only through an approved decision record. This is that record.

The owner's first real use was "working superb but ... too much slow". Measured
through the real `--replay` path, paced in real time, on the reference machine
(Ryzen 5 5600H, 6 cores / 12 threads):

- **Medium spends ~19.5 s of CPU on 25 s of audio.** Moonshine re-decodes the
  whole current segment on every update, so a single update grows from
  200–400 ms at the start of a segment to 1.0–1.8 s after ~15 s of unbroken
  speech. The overlay falls behind the speaker, and whatever backlog is left at
  release is decoded then: release → text ranged from ~30 ms to ~850 ms.
- **Any other load pushes it further behind.** With 0.8× realtime of headroom
  consumed by the model, a background job on the same CPU is enough to turn the
  backlog into seconds.
- **Injection is not the problem**: ~80 ms of subprocesses plus the fixed
  150 ms `restore_delay_ms`.
- **First partial is not the problem either**: ADR 0004's ~0.8–1.5 s floor is
  the same on all three models.

## Measurement

80 LibriSpeech test-clean clips (two per speaker, 40 speakers, 732 s, 1,889
reference words), the real replay path at fast pacing, same clips per model.
Text is lowercased and stripped of punctuation before scoring.

| Model | WER | Errors | Wall clock | × realtime |
|---|---|---|---|---|
| `tiny-streaming-en` | 5.93% | 112 | 217 s | 0.30 |
| `small-streaming-en` | **3.71%** | 70 | 554 s | 0.76 |
| `medium-streaming-en` | 4.50% | 85 | 665 s | 0.91 |

The machine was under heavy unrelated load (load average 18–25) for the small
and medium runs, so their wall-clock figures are inflated; WER is unaffected by
load. A 25 s continuous-speech replay taken at lower load gives the relative
cost more fairly: medium 19.7 s of decode, small 16.4–18.9 s, tiny 11.9 s, with
the worst single update at 1,669 ms, 827–1,107 ms and 800 ms respectively.

Medium scoring worse than small here runs against the upstream Open ASR figures
the spec cites. Those are for the float models on a different benchmark; these
are the quantized builds `moonshine-voice` ships, through flowd's own
segmentation and committing, on the audio class flowd is meant for.

## Options considered

1. **Keep medium.** The slowest option, and not more accurate on this data.
2. **Tiny.** The fastest, but 60% more errors than small. A dictation tool that
   is quick and wrong costs more in corrections than it saves in waiting.
3. **Cap segment length** (`vad_max_segment_duration`). Bounds the per-update
   cost, but cuts sentences mid-phrase: a 3 s cap produced 113 words for a
   92-word clip, duplicating words at every cut. Rejected.
4. **Slower `update_interval`.** 0.5 s instead of 0.2 s made medium no faster
   (22.1 s of decode) and delayed the first partial. Rejected.
5. **Small.** The most accurate model measured, cheaper than medium, and it
   halves medium's worst stall.

## Decision

**Option 5.** `stt.model` defaults to `small-streaming-en`, and
`scripts/fetch_models.sh` warms that model. Medium and tiny stay selectable in
`config.toml` and are fetched on first use by `moonshine-voice`'s own verified
downloader, as ADR 0001 describes.

## Consequences

- Spec 3's model table no longer describes the default. The spec is left as
  written and this record is the deviation from it.
- Small is 136 MB on disk against medium's 257 MB, so it should be smaller in memory too, which would help phase
  2's resident-memory finding; resident memory has not been re-measured.
- Owners on slower machines who still see lag can drop to tiny with one line of
  config, at the accuracy cost shown above.
- Not re-measured with small: spec 10.1's release-to-commit percentiles. The
  phase 2 report's figures are medium's.
