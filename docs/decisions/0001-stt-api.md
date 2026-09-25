# 0001: Moonshine STT API — streaming commits and built-in VAD

Status: accepted
Phase: 0

## Context

Spec rule 13.1.2 forbids guessing at an upstream API, and spec 5.2/5.3 assume
things about Moonshine that had to be checked before any STT code was written.
Every answer below comes from the installed package on this machine — its own
source, its compiled library's symbol table, and a real transcription run — not
from documentation or a web search.

Evidence was gathered against `moonshine_voice/assets/two_cities.wav`, a 44.4s
fixture that ships with the package, on `moonshine-voice 0.1.5` under CPython
3.12.12. Raw output is quoted verbatim throughout, and the calls that produced
it are given inline below so the findings can be re-run.

### Q1. Package identity

| | |
|---|---|
| Package | `moonshine-voice` |
| Version | `0.1.5` |
| Repository | https://github.com/moonshine-ai/moonshine |
| License | MIT, "Copyright (c) 2025 Moonshine AI" (`dist-info/licenses/LICENSE`) |
| Python support | classifiers list 3.8–3.12 |

The **code** is MIT, but the **weights** are not uniformly so. `download.py`
prints, for any non-English language:

> Using a model released under the non-commercial Moonshine Community License.
> See https://www.moonshine.ai/license for details.

flowd is English-only (spec 5.1), so it stays on the permissively-licensed
path. Anyone adding a language must check that licence themselves. This belongs
in the README before flowd invites contributions.

The package does **not** use the `onnxruntime` Python wheel. It ships its own
12 MB `libmoonshine.so` with ONNX linked inside, loaded via `ctypes`; no module
in the package imports `onnx` or `onnxruntime`. See "Impact on spec".

### Q2. Native streaming with incremental *and* committed results — yes

The spec's assumption held, and more cleanly than it hoped. `Transcriber`
exposes a real streaming API:

```python
t = Transcriber(model_path, arch)          # arch from get_model_for_language()
stream = t.create_stream(update_interval=0.3)
stream.add_listener(fn)                     # fn(event) -> None
stream.start()
stream.add_audio(block, sample_rate)        # list[float], PCM -1.0..1.0
stream.stop()
```

Listeners receive dataclass events carrying a `TranscriptLine`
(`transcriber.py:28-74`). The split between provisional and final is explicit
in `_notify_from_transcript` (`transcriber.py:692-704`):

| Event | Fired when | Meaning for flowd |
|---|---|---|
| `LineStarted` | `line.is_new` | a new segment began |
| `LineUpdated` | `is_updated and not is_new and not is_complete` | provisional revision |
| `LineTextChanged` | `has_text_changed` | provisional revision |
| **`LineCompleted`** | **`is_complete and is_updated`** | **committed — text is final** |

`TranscriptLine.is_complete` is a first-class field of the C struct
(`moonshine_api.py:113`), not something inferred on the Python side.

Observed on the fixture: **43 incremental events and 13 `LineCompleted`
events**, with revision visible before each commit:

```
 1.20s LineStarted     complete=False 'It was.'
 3.33s LineUpdated     complete=False 'It was the best of times,'
 5.16s LineCompleted   complete=True  'It was the best of times, it was the worst of times.'
```

So flowd does **not** need to emulate commits as spec 5.3 contemplated.
`LineCompleted` *is* the commit signal, decided by the model rather than by a
stability heuristic guessing from outside.

### Q3. Built-in voice activity detection — yes, but only as segmentation

This is the question the owner asked to be settled explicitly. The answer has
two halves, and the second half constrains the design.

**It exists.** `libmoonshine.so` embeds Silero VAD as a data symbol and drives
every stream through a detector:

```
0000000000b06680 B _ZN21VoiceActivityDetector10silero_vadE
00000000008b6100 D silero_vad_onnx
00000000008b60c0 D silero_vad_onnx_len
     T _ZN21VoiceActivityDetector13process_audioEPKfmi
     T _ZN21VoiceActivityDetector12on_voice_endEv
     T _ZN17TranscriberStreamC1EP21VoiceActivityDetector...
     T _ZN11Transcriber31update_transcript_from_segmentsERKSt6vectorI20VoiceActivitySegment...
```

`TranscriberStream`'s constructor takes a `VoiceActivityDetector*`, and the
transcript is built *from VAD segments*. The package docstring says as much:
"enabling voice-activity detection, transcription, and other voice processing
capabilities."

**It is not exposed to Python.** There is no `moonshine_vad_*` function in the
stable C API. The full list of streaming/VAD-adjacent exports is:

```
moonshine_create_stream          moonshine_transcribe_add_audio_to_stream
moonshine_start_stream           moonshine_transcribe_stream
moonshine_stop_stream            moonshine_transcribe_without_streaming
moonshine_free_stream            moonshine_extract_speech_clip
```

`moonshine_extract_speech_clip` does run the built-in VAD, but it requires a
**TTS synthesizer handle** and exists for voice cloning
(`moonshine_api.py:629-645`) — it cannot be pointed at a transcriber.

So flowd can consume the VAD's *conclusions* (segment boundaries, surfaced as
`LineCompleted`) but cannot ask it "is the user speaking right now?" or "how
many ms of silence so far?".

### Q4. Model files

`get_model_for_language("en")` resolves the default English model to
`medium-streaming` — the model spec 5.1 chose — and caches it under
`$XDG_CACHE_HOME/moonshine_voice/`:

```
model_path: ~/.cache/moonshine_voice/download.moonshine.ai/model/medium-streaming-en/quantized_26_08_21
model_arch: medium-streaming
fetch took: 29.3s      on-disk: 269.1 MB
```

| File | Size |
|---|---|
| `decoder_kv.ort` | 147.0 MB |
| `encoder.ort` | 94.7 MB |
| `frontend.weights.ort` | 11.9 MB |
| `cross_kv.ort` | 11.6 MB |
| `adapter.ort` | 3.7 MB |
| `tokenizer.bin` | 0.2 MB |
| `frontend.model.ort`, `streaming_config.json` | < 0.1 MB |
| **Total** | **269.1 MB** |

Five English architectures are published (`medium-streaming` default, plus
`small-streaming`, `tiny-streaming`, `base`, `tiny`), so trading accuracy for
speed is a config change, not a code change.

Two incidental findings worth keeping:

- **Resampling is handled upstream.** The fixture is 48 kHz and transcribed
  correctly when its own rate was passed through, so `sample_rate` must be
  reported honestly rather than assumed to be 16 kHz.
- **Throughput on this machine is marginal.** Batch transcription of 44.4s of
  audio took **39.5s**, and the streaming run, fed as fast as it would accept,
  took **46.8s** — about 1.05× realtime on the Ryzen 5 5600H. It keeps up, with
  little headroom. `Stream.add_audio`'s own docstring describes the adaptive
  backoff built for exactly this: passes grow until each covers its own cost,
  so a machine that cannot afford the nominal cadence degrades by batching
  rather than falling further behind each pass. Not a blocker, but the reason
  the model must stay configurable, and something to re-measure with the
  overlay and `llama-server` competing for cores.

## Options

1. **Use the native streaming API and its built-in VAD segmentation; ship no
   separate VAD model.** Commits come from `LineCompleted`. Cost: flowd cannot
   observe silence duration directly, so any feature wanting "N ms of silence"
   must be expressed in terms of segment boundaries or timed in flowd from its
   own audio. Reversible: the separate-VAD path can be added later without
   disturbing the engine seam.
2. **Use the native streaming API, but add `silero_vad.onnx` via `onnxruntime`
   anyway** for an independent silence signal. Cost: a second copy of the same
   Silero model, a 22.5 MB `onnxruntime` wheel kept in the dependency set, and
   two disagreeing sources of truth about where speech stops. Buys a numeric
   `silence_ms` that only the auto-stop and commit-on-silence features would
   read.
3. **Ignore the native streaming API and emulate commits per spec 5.3**
   (stable-prefix over repeated batch passes). Cost: re-implements, worse, what
   the model already decides, and pays a full pass per update at ~1× realtime.
   No upside now that Q2 is answered.

## Recommendation

**Option 1.** The owner's instruction was to use built-in VAD or segmentation
if it exists and fall back to `silero_vad.onnx` only otherwise. It exists, as
segmentation, so flowd consumes `LineCompleted` and ships no VAD model of its
own. Option 2's independent silence signal is speculative until a feature
actually needs a millisecond count that segment boundaries cannot express;
adding it then is cheap, and adding it now would be a second, quieter source of
truth about the same question.

## Impact on spec

- **5.3 (commit rule).** The stable-prefix heuristic with a stability window is
  not needed for correctness — `LineCompleted` is authoritative. The committer
  narrows to tracking which committed lines have been seen and holding the
  provisional tail for display. Task 16 shrinks accordingly.
- **5.2 (VAD).** No `silero_vad.onnx` entry in `models.lock` and no separate
  VAD model to fetch; the detector is inside `libmoonshine.so`. Task 15's
  subject changes from "load and run a VAD" to "derive speech state from stream
  events". The spec's `vad` config block loses its model path.
- **`onnxruntime` dependency.** Nothing now needs it: Moonshine bundles its own
  runtime, and the separate Silero model is gone. Dropping it removes a 22.5 MB
  wheel from every install. Deferred to Task 15, where the VAD code is written
  and the claim can be proven with the suite rather than asserted here.
- **3 (models).** `models.lock` covers the LLM GGUF and pins Moonshine by
  package version and model architecture; the eight `.ort` files are fetched
  and CRC32C-verified by Moonshine's own downloader, which flowd should not
  duplicate.
- **5.1 (model choice).** `medium-streaming` stands, at ~1.05× realtime here.
  The `stt.model` config key must reach the four alternative architectures so a
  slower machine can drop to `small-streaming` without a code change.
- **README.** Must state that non-English weights carry a non-commercial
  licence, so nobody adds a language without seeing it.

Spec 13.3's escalation trigger — no streaming API *and* no way to emulate
commits inside the 300 ms budget — does **not** fire. Phase 0 continues.
