# Phase 0 report

## Summary

- Repository scaffold: `pyproject.toml`, MIT licence, `.gitignore` that keeps audio, transcripts, weights and personal vocabulary out of git, and CI testing Python 3.11 and latest.
- `flowd/models.py` verifies every pinned file against `models.lock` by size and SHA-256, returning all mismatches at once so the daemon can refuse to start with a complete list (spec 9.2).
- `scripts/fetch_models.sh` fetches the cleanup LLM and warms the STT cache, never auto-upgrading; `scripts/smoke_llm.sh` proves `llama-server` cleans up dictated speech; `scripts/fetch_eval_audio.sh` fetches CC BY 4.0 evaluation audio that is never committed.
- ADR 0001 answers the four questions spec 13.1.2 forbids guessing at. Two answers change the design: Moonshine **has** native streaming commits, and its VAD **exists but is not reachable from Python**.
- No `flowd` daemon yet. Phase 0 is scaffolding and verification; the mic path is phase 1.

## Acceptance criteria

| Criterion (from section 12) | Result | Evidence |
|---|---|---|
| Both models download and hash-verify | **Pass** | `scripts/fetch_models.sh` exit 0. `LFM2.5-350M-QAD-Q4_0.gguf`, 219,312,832 bytes, `sha256:3d10b6ab8fc91a919534b9558e266255aca0bbc7f6d015963599aa9e74e05b1d`; `verify_models()` against the real file and the committed `models.lock` returns `[]`. STT weights (269.1 MB, 8 files) are fetched and CRC32C-verified by Moonshine's own downloader — see "Deviations". |
| `llama-server` answers a cleanup prompt | **Pass, with a finding** | `scripts/smoke_llm.sh` exit 0: `RESULT: So I think we should ship it on Monday.` from `so um i think we should uh probably ship it on monday`. The spec's `<new></new>` prompt shape had to be dropped to get this — see "Known issues". |
| Moonshine transcribes a sample WAV from the command line | **Pass** | `Transcriber(...).transcribe_without_streaming()` on `moonshine_voice/assets/two_cities.wav` (44.4 s, 48 kHz) returned 13 complete lines, first being `It was the best of times, it was the worst of times.` Full output in ADR 0001. |
| Versions and API notes recorded in `docs/decisions/0001-stt-api.md` | **Pass** | ADR 0001, `Status: accepted`, answers Q1–Q4 with verbatim command output and symbol-table evidence. |
| Automated tests green | **Pass** | `uv run pytest -q` → 4 passed. `ruff check`, `ruff format --check`, `mypy flowd` (strict) all clean. |

## Measurements

**Machine.** AMD Ryzen 5 5600H, 6 physical cores / 12 threads, 15 GiB RAM, AVX2 (no AVX-512). Arch Linux, kernel 7.2.6-arch2-1. Wayland session under Hyprland — this answers the spec's own open question about the compositor.

**Versions.**

| | |
|---|---|
| `moonshine-voice` | 0.1.5 (MIT; bundles its own `libmoonshine.so`) |
| STT model | `medium-streaming-en`, revision `quantized_26_08_21`, 269.1 MB |
| `llama-server` | 0.4.1-dev, build 10964, commit `b29c606e28` (pacman `llama-cpp 0.4.1-1.1`) |
| Cleanup LLM | LFM2.5-350M-QAD-Q4_0, 209 MB |
| Python (venv) | CPython 3.12.12 |
| Python (system, for the overlay) | 3.14.7 |

**STT throughput**, on `two_cities.wav` (44.4 s of speech):

| Path | Wall clock | Ratio to audio duration |
|---|---|---|
| Batch (`transcribe_without_streaming`) | 39.5 s | 0.89× |
| Streaming, fed as fast as accepted | 46.8 s | 1.05× |

The streaming figure is compute-bound wall clock, not observed lag: audio was pushed in a tight loop rather than paced to realtime, so 1.05× is the cost of keeping up with live speech on this CPU, with roughly no headroom. `Stream.add_audio`'s own documented backoff means a machine that cannot afford the nominal cadence degrades by batching rather than falling further behind each pass. Model fetch took 29.3 s on this connection.

**Not measured, and why.** Latency p50/p95 per stage, eval WER, fallback and clip rates, and idle RSS and CPU are all absent from this report because nothing that produces them exists yet: there is no daemon, no `metrics.jsonl`, no `flowctl` and no cleanup pass. They arrive in phases 1 and 3. Spec 13.1 forbids inventing them, and a guessed number here would be worse than a gap.

## Deviations from spec

| What | Why | Record |
|---|---|---|
| Commits come from Moonshine's `LineCompleted` event; the stable-prefix emulation of spec 5.3 is not implemented | The native streaming API exposes provisional and final results directly, decided by the model rather than by a heuristic guessing from outside. Measured: 43 incremental events, 13 commits. | ADR 0001 Q2 |
| No `silero_vad.onnx`, no VAD entry in `models.lock` | Per the owner's instruction to prefer built-in VAD: it exists inside `libmoonshine.so` (Silero embedded as a data symbol; `TranscriberStream` takes a `VoiceActivityDetector*`) but is not exposed through the stable C API. flowd consumes its conclusions as segment boundaries. Consequence: flowd cannot query a live `silence_ms`. | ADR 0001 Q3 |
| `onnxruntime` is still a declared dependency but nothing uses it | Moonshine bundles its own ONNX runtime and imports neither `onnx` nor `onnxruntime`; with the separate Silero model gone, the 22.5 MB wheel is dead weight. Removal deferred to the task that writes the VAD code, where the suite can prove it. | ADR 0001 |
| `models.lock` pins only the GGUF, not the STT weights | Moonshine's downloader already verifies its own files by CRC32C. Pinning them again would give flowd a second, staler source of truth about the same bytes. | ADR 0001 Q4 |
| Smoke test sends a plain cleanup prompt, not spec 6's `<new></new>` wrapper | On this 350M model the tag reliably derails output. See "Known issues". | Below |
| Install docs say `llama-cpp`, not spec 2's `llama.cpp` from the AUR | The package is `llama-cpp` in `extra`; the spec's name and source are both wrong. | Design doc, spec corrections |

## Known issues and open questions

**The spec's cleanup prompt shape defeats the cleanup model.** Wrapping the text in `<new></new>` as spec 6 prescribes made LFM2.5-350M answer in Portuguese: `so um i penso que devemos enviar em monday`, fillers intact. The identical prompt without the tags returned `So I think we should ship it on Monday.` Five prompt shapes were probed at temperature 0; the tag was the variable. The model is capable — the prompt shape is the problem, and it is a real problem for phases 3 and 4, which need those tags for the self-correction merge. They will need either a different delimiter, a worked example in the prompt, or a larger model. The finding is recorded in the smoke test's own comment so it cannot be lost.

Worth noting how this surfaced: the original smoke test exited 0 on that Portuguese output, because it only checked that curl got HTTP 200. It now asserts that fillers are gone and the meaning survived, and that gate was verified in both directions — it rejects the recorded bad output and accepts the good one. A smoke test that cannot fail is not evidence.

**STT headroom is thin.** 1.05× realtime for streaming compute, measured with nothing else running. The overlay and `llama-server` will compete for the same cores. `stt.model` must reach the four alternative architectures (`small-streaming`, `tiny-streaming`, `base`, `tiny`) so a slower machine can downgrade by config rather than by code change. Re-measure at the phase 2 checkpoint with the full pipeline live.

**Non-English weights are not MIT.** The `moonshine-voice` code is MIT, but `download.py` prints a non-commercial Moonshine Community Licence notice for every non-English language. flowd is English-only, so it stays on the permissive path, but the README must say this before flowd invites contributions.

**Sample rate must be passed honestly.** The 48 kHz fixture transcribed correctly when its own rate was reported, so Moonshine resamples internally. Code must pass the device's real rate rather than assuming 16 kHz.

**Open question for the owner, not blocking.** `verify_models` is written and tested but has no caller until the daemon exists; if phase 1's startup check should also verify the STT cache, that needs a Moonshine-side hook rather than a `models.lock` entry.

## Next phase plan

Phase 1 builds the baseline daemon end to end: config with XDG fallbacks, metrics, the control socket, the state machine, `basic_clean` and the joiner, audio capture, batch STT, the injection backends, `flowctl`, and `--replay`. Its acceptance criterion is the first real one — toggle dictation and have raw text land in a terminal, a browser field and an editor, with every stage timed and cancel injecting nothing.

Two phase-0 findings shape it: batch STT is what phase 1 ships (streaming is phase 2), and the `onnxruntime` dependency comes out when the VAD task proves nothing needs it.
