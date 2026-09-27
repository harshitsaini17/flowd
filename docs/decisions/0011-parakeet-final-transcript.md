# 0011: Commit Parakeet's text, preview Moonshine's

**Status:** accepted (2026-09-28)

## Context

Moonshine Small Streaming scored 3.7% WER on LibriSpeech (ADR 0005), but on the
owner's own voice (Indian English, a 70.5 s recording of five test passages,
105 reference words) it scored 20.0%. It also puts a period and a capital at
every pause, so the cleanup model receives sentence fragments. The microphone
was ruled out: speech at -35 dBFS RMS, noise at -54 dBFS, no clipping.

## Measurement

Same recording, same scoring (word alignment after number normalization), on
the reference machine (Ryzen 5 5600H, no GPU). "Pieces" is how the audio was
cut before decoding.

| Model | Pieces | WER | Worst piece | Peak RSS |
|---|---|---|---|---|
| Moonshine small streaming (before) | live | 20.0% | | |
| Moonshine medium streaming | live | 21.9% | | |
| faster-whisper small.en int8 | whole file | 4.8% | 5.7 s | 854 MB |
| faster-whisper small.en int8 | 20 s | 11.4% | 2.0 s | 1073 MB |
| faster-whisper small.en int8 | 10 s | 21.0% | 1.7 s | |
| faster-whisper large-v3-turbo int8 | whole file | 6.7% | 19.6 s | 2789 MB |
| **Parakeet TDT 0.6B v2 int8** | **20 s** | **6.7%** | **1.0 s** | **~1.1 GB** |
| Parakeet TDT 0.6B v2 int8 | pauses ≥ 1 s | 7.6% | 0.9 s | |
| Parakeet TDT 0.6B v2 int8 | pauses ≥ 0.3 s | 11.4% | 0.26 s | |
| Parakeet TDT 0.6B v3 int8 | 20 s | 14.3% | 1.1 s | 1.27 GB |
| Qwen3-ASR 0.6B int8 | 10 s | 7.6% | 1.4 s | 2.3 GB |
| Nemotron 3.5 streaming 0.6B, `en` | live | 29.5% | 91 ms/block | 980 MB |
| Canary 180M flash int8 | pauses | 45.7% | 0.4 s | 417 MB |

Qwen3-ASR invented a sentence ("Human Rights Watch is a non-profit
organization...") on a 20 s piece. Nemotron switched to Devanagari output
unless forced to English. Whisper needs the whole utterance to be accurate,
which would put its full decode time after release.

## Decision

- Moonshine keeps streaming and drives the overlay preview. Its commits are no
  longer used.
- Parakeet TDT 0.6B v2 int8, run through `sherpa-onnx` 1.13.8, transcribes the
  session in pieces while the user talks (`flowd/hybrid.py`): a piece ends at a
  pause of 600 ms once it holds 8 s of audio, or at its quietest 100 ms block
  by 20 s. Pieces decode on one worker thread, in order. Only Parakeet's text
  is committed, so only it reaches cleanup and injection.
- At release only the last piece (≤ 20 s) is left to decode. On the recording,
  release to finalized took 176 ms, and raw WER through the real replay path
  was 5.7%.
- If a piece fails to decode, the live words covering it are committed
  instead, with a warning.
- `[stt] final_model = ""` restores Moonshine-only commits.
- The four model files are fetched by `scripts/fetch_models.sh` from one pinned
  Hugging Face revision and pinned in `models.lock` like the LLM weights.
  Licence: CC-BY-4.0.

## Memory budget

This raises the idle budget from 900 MB to **1,600 MB** anonymous memory
(same measure as ADR 0006). Measured: the daemon with both models loaded is
about 1,140 MB anon, the overlay about 195 MB and llama-server about 170 MB,
about 1.5 GB in total. After a dictation glibc kept roughly 250 MB of freed
decode buffers; the engine calls `malloc_trim` at the end of each session,
which brings the daemon back to about 1,140 MB and holds it there across
sessions.

Loading Parakeet only while dictating would stay under 900 MB but costs about
2 s at every start. The owner chose accuracy and speed over the lower budget.

## Consequences

- One more dependency, `sherpa-onnx` (about 14 MB of wheels, with its own
  `libonnxruntime.so`; no `onnxruntime` package is installed).
- About 660 MB more on disk.
- Cuts and timing are tuned on one speaker and one machine. The constants in
  `flowd/hybrid.py` say where each number came from.
