# Phase 2 report

## Summary

- Streaming STT replaces batch: Moonshine's native `create_stream` feeds the
  committer, and `LineCompleted` is the authoritative commit signal (ADR 0001).
  Release → text injected fell from phase 1's ~2,680 ms to a 513 ms p50.
- The VAD needs no model. Speech is inferred from the gap between audio fed and
  the transcript frontier, because the segmenter inside `libmoonshine.so` already
  made that judgement (ADR 0002). One dependency was removed rather than added.
- The overlay is a separate process on the system interpreter, and it never takes
  keyboard focus: 11/11 on `scripts/check_overlay_focus.py`, with the focused
  window's address byte-identical before, during and after.
- `LD_PRELOAD` of `libgtk4-layer-shell.so` is **required**, not optional, and the
  plan named the wrong library. Worse, `init_for_window()` raises nothing when it
  is missing — it silently leaves a focus-stealing toplevel, which spec 5.8 calls
  worse than no overlay (ADR 0003).
- **Two budgets are missed.** Speech → first partial is 1,384 ms p50 against
  300 ms, and it is a structural warm-up floor rather than a tuning problem
  (ADR 0004). Idle RSS is 905.8 MB against a 900 MB allowance that must still fit
  `llama-server`.

## Acceptance criteria

### Phase 2 (section 12)

| Criterion | Result | Evidence |
|---|---|---|
| First partial ≤ 300 ms after speech onset | **Not met — 1,384 ms p50, 4.6× over** | 12 LibriSpeech clips, measured from Moonshine's own `line.start_time` rather than from session start, because the budget is onset-relative and these clips open with room tone (onset p50 240 ms in). p50 1,384 ms, p95 1,531 ms, range 820–1,531 ms. Structural, not tuning: [ADR 0004](../decisions/0004-first-partial-floor.md) records the `update_interval` sweep (no effect), the compute check (0.4–0.5× realtime, so not compute-bound), and an architecture sweep finding the same floor on medium, small and tiny. Escalated under spec 13.3 rather than quietly passed. |
| The overlay never takes focus: paste still lands in the original app | **Pass on focus; injection half deferred to the owner** | `scripts/check_overlay_focus.py`, 11/11: focused window byte-identical before, during, after fade and at the end (`kitty` at `0x56115034e690`); zero entries in `hyprctl clients`; one `gtk4-layer-shell` layer surface at level 3 on eDP-1, keyboard-mode NONE; none left behind. Automated twin in `tests/test_overlay_process.py` asserts the positive log line paired with a forced-fallback test, because a clean exit is what the broken case also produces. Watching dictated text land in three real applications needs a person at a microphone — the checkpoint the owner runs. |
| Committer unit tests pass | **Pass** | `tests/test_committer.py` and `tests/test_vad.py` → 41 passed, covering spec 5.4's three commit rules: engine completion, VAD silence, and the stable-prefix rule with its "keep last 3 words" clause. Full suite `uv run pytest -q` → 298 passed. `ruff check`, `ruff format --check` and `mypy flowd flowctl` (strict) clean. |

### Phase 1, re-verified at this checkpoint

| Criterion | Result | Evidence |
|---|---|---|
| Toggle dictation pastes raw text into a terminal, a browser text field and a code editor | **Still deferred to the owner** | Unchanged from [phase 1](phase-1.md): the daemon path works end to end against a live socket and all four injection backends report available, but the three-application check needs a person speaking. This is the phase 2 checkpoint gate. |
| Every stage is timed in `metrics.jsonl` | **Pass** | `first_partial_ms` now appears alongside `mic_open_ms`, `released_ms`, `finalized_ms` and `inject_ms`. 47 of the 449 logged sessions carry a first partial. See "Known issues" on why the log is not a latency source. |
| Cancel injects nothing | **Pass** | `test_cancel_injects_nothing`, `test_capture_is_released_on_cancel`, and — new in phase 2 — `test_cancel_resets_the_engine_so_nothing_leaks_into_the_next_session`: the daemon holds one engine for its whole life (spec 5.3), so a cancelled session that left a half-formed transcript behind would carry it into the next dictation. |
| Unit tests for the state machine pass | **Pass** | 298 passed, up from phase 1's 204. |

### Phase 0, re-verified at this checkpoint

| Criterion | Result | Evidence |
|---|---|---|
| Both models download and hash-verify | **Pass** | Unchanged from [phase 0](phase-0.md). `verify_models()` against the committed `models.lock` returns `[]`. |
| `llama-server` answers a cleanup prompt | **Pass** | `scripts/smoke_llm.sh` exit 0. Not running during phase 2 measurements; phase 2 does not need it. |
| Moonshine transcribes a sample WAV | **Pass, and now streams** | Phase 0 verified `transcribe_without_streaming`. Phase 2 uses `create_stream`; raw WER over the 12 eval clips is 6.3%. |
| Versions and API notes in `docs/decisions/0001-stt-api.md` | **Pass** | ADR 0001 accepted; ADRs 0002–0004 added in phase 2. |

## Measurements

**Machine.** AMD Ryzen 5 5600H, 6 physical cores / 12 threads, 15.0 GiB RAM,
Arch Linux, Hyprland on Wayland, `/dev/nvme0n1p8` at 93% full.

**Versions.**

| Component | Version |
|---|---|
| `moonshine-voice` | 0.1.5 (medium-streaming-en, quantized_26_08_21) |
| `onnxruntime` | 1.30.0 |
| `numpy` / `sounddevice` | 2.5.3 / 0.5.6 |
| `llama-server` | 0.4.1-dev, build 10964, commit `b29c606e28` |
| Python | 3.12.12 (venv), 3.14.7 (system, runs the overlay) |
| GTK / gtk4-layer-shell / PyGObject | 4.22.5 / 1.3.0 / 3.56.3 |
| PortAudio / wl-clipboard / wtype / xdotool | 19.7.0 / 2.3.0 / 0.4 / 4.20260303.1 |

**Latency, 12 LibriSpeech clips (86.9 s of speech) through `--replay` in real
time.** Every reading carries the load average that produced it, for the reason
in the next paragraph.

| Stage | p50 | p95 | Range | Budget (spec 10.1) | Verdict |
|---|---|---|---|---|---|
| Speech onset → first partial | 1,384 ms | 1,531 ms | 820–1,531 | ≤ 300 ms | **Missed, 4.6×** |
| Release → last chunk committed | 509 ms | 955 ms | 11–955 | ≤ 300 ms | **Missed, 1.7× — but see below** |
| Release → text injected | 513 ms | 957 ms | 12–957 | p50 ≤ 600 ms, p95 ≤ 1,000 ms | **Pass** |
| Injection itself (`finalized` → `inject`) | 1.8 ms | — | 1.1–6.4 | — | — |

**The release → committed figure is measuring the machine, not the code, and
should be re-taken on an idle one.** A training job of the owner's ran throughout,
taking the load average from 0.97 to 14.0 across the sweep. Re-running a single
clip three times gave 935 ms, 11 ms and 723 ms for byte-identical audio — the
spread is not a property of the clips. The mechanism is direct: this stage is the
tail of audio not yet transcribed when the speaker releases, so it grows with
transcription lag, and lag grows with contention. The quieter early sweep
(load 0.97 rising) gave a 449 ms p50 with the same shape. Treat 509 ms as an
upper bound taken under load, not as the machine's figure.

Two things are load-independent and can be trusted. First-partial latency barely
moved (820–1,531 ms across loads 1.4 to 14.0), which is what makes ADR 0004's
warm-up floor a structural finding rather than a contention artifact. And the
end-to-end budget passes with room to spare even at load 14.

**Accuracy, raw streaming output against LibriSpeech's own reference:** 6.3% WER
(14 word edits over 221 reference words), before any LLM cleanup. Phase 2 has no
accuracy criterion — the eval is phase 3's — but a latency number is worthless if
the text is wrong. Per-clip WER ranges from 0.0% on five clips to 37.5% on a
3.3 s fragment (`"'Stuff it into you,' his belly counseled him.` against
`STUFF IT INTO YOU HIS BELLY COUNSELLED HIM`). All three of that clip's edits are
artifacts of the comparison rather than misheard speech: two come from the
quotation marks Moonshine emits and the reference does not have, and the third is
`counseled` against `counselled`. Worth knowing before phase 3's eval treats WER
as a target — the reference is unpunctuated and uppercase, and adding punctuation
is flowd's job.

**Idle resident memory**, from `smaps_rollup`, daemon with the model loaded and
the overlay showing a layer surface:

| Process | RSS | PSS | Private |
|---|---|---|---|
| `flowd` (daemon, model loaded, idle) | 711.4 MB | 704.0 MB | 700.3 MB |
| `flowd-overlay` (layer surface shown) | 194.4 MB | 151.9 MB | 139.2 MB |
| `llama-server` | not running (phase 3) | — | — |
| **Total** | **905.8 MB** | 855.9 MB | — |

**This is already over spec 10.1's 900 MB allowance with `llama-server` absent,**
and that allowance is meant to cover all three processes. Phase 3 adds a 219 MB
Q4_0 model plus the server's own footprint. PSS — which splits shared pages
between the processes mapping them, and is what the machine actually pays — is
855.9 MB, so the honest reading is "at the budget, not comfortably inside it".
A naive process-tree sum reports 949.9 MB; 44.1 MB of that is the `uv` launcher
holding the daemon open, which is an artifact of how it was started and is
excluded above.

Where the daemon's 711 MB goes: 241.6 MB of memory-mapped streaming model files
(`decoder_kv.ort` 140.2 MB, `encoder.ort` 90.3 MB, `cross_kv.ort` 11.1 MB) and a
188.3 MB heap. Phase 1 measured 631 MB for batch STT, so streaming costs about
80 MB more — the streaming architecture keeps a decoder KV cache that the batch
one did not.

**Idle CPU:** 0.00% over 60 s at load 1.94, against a < 1% budget. **Pass.** The
daemon between sessions is a socket `accept` and a 200 ms sleep.

**`lag_allowance_ms` re-measured with the overlay competing for cores, which
[ADR 0002](../decisions/0002-vad-segmentation.md) asked this report to do.** The
quantity is the peak gap between audio fed and transcript frontier *during*
speech; anything above the allowance commits mid-phrase, and spec 13.2 forbids
typing partial text into the target app.

| Condition | Peak lag during speech | False commits at 900 ms |
|---|---|---|
| No overlay (load 12.3) | 1,412 ms | 5 |
| Overlay running and rendering (load 12.6) | 2,024 ms | 5 |

**The overlay makes no material difference**, which was the open question: it
renders on a separate process and the GTK work does not contend with ONNX for
the cores STT needs. The allowance sweep over the recorded traces:

| Allowance | False commits (no overlay / with overlay) |
|---|---|
| 300 ms | 23 / 17 |
| 500 ms | 14 / 10 |
| 700 ms | 7 / 5 |
| **900 ms (configured)** | **5 / 5** |
| 1,100 ms | 4 / 5 |
| 1,500 ms | 3 / 5 |

900 ms sits where the curve flattens, so the default is well chosen — but it does
not reach zero under contention, and the peak lag of 1,412–2,024 ms at load 12 is
above it. On an idle machine ADR 0002 measured this comfortably; under load the
value is not conservative enough. It is a config knob, documented as
machine-dependent, so this is a note for the owner rather than a code change.

## Deviations from spec

Each has an accepted decision record.

- **STT API and the commit signal** — [ADR 0001](../decisions/0001-stt-api.md).
  `moonshine-voice` exposes native streaming through `create_stream`, and
  `LineCompleted` is authoritative rather than a heuristic over partials.
- **No VAD model** — [ADR 0002](../decisions/0002-vad-segmentation.md). Spec 5.2
  called for `silero_vad.onnx` via `onnxruntime`; the segmenter inside
  `libmoonshine.so` already does the work, so nothing was added to
  `models.lock`. `[vad]` gains `lag_allowance_ms` (900); `threshold` is kept and
  accepted but inert, because `_build` rejects unknown keys and removing it would
  stop flowd starting for anyone who wrote a config from the spec's own text.
- **Overlay preload** — [ADR 0003](../decisions/0003-overlay-focus.md).
  `LD_PRELOAD` is required, with `libgtk4-layer-shell.so` rather than the
  `liblayer-shell-preload.so` the plan named. The overlay preloads itself by
  re-executing once rather than relying on its spawner, because the failure it
  guards against is silent. Spec 13.2 gains an entry: never treat
  `gtk_layer_init_for_window` returning without error as proof of a layer surface.
- **First-partial budget** — [ADR 0004](../decisions/0004-first-partial-floor.md).
  Spec 10.1's 300 ms is unreachable with this model on this machine, and the
  measurements say why. The warm-up-decoder mitigation is deferred to this
  checkpoint rather than built speculatively.

## Known issues and open questions

**For the owner to decide:**

1. **First partial misses its budget by 4.6× and there is no tuning fix.**
   ADR 0004 measured a warm-up floor that is identical across medium, small and
   tiny, so a smaller model does not buy it back. The candidate mitigation is a
   warm-up decoder pass at session start, which trades idle CPU for first-partial
   latency — deferred here because it is speculative work against a budget the
   owner may prefer to relax. Spec 13.3 says a > 25% miss escalates; this is
   360%.
2. **RSS is at the 900 MB allowance before `llama-server` exists.** 905.8 MB RSS
   / 855.9 MB PSS for daemon + overlay. Phase 3 adds a 219 MB model plus server
   overhead. Something has to give: a smaller STT model, a smaller LLM, or a
   raised budget. Worth settling before phase 3 builds against the current one.
3. **`audio.always_open` default** — carried over unresolved from phase 1. The
   default (`false`) misses the 100 ms hotkey → mic budget at 121.8 ms p50;
   `true` brings it to 26.1 ms but holds the microphone open permanently. That is
   a privacy decision, not a performance one.
4. **`lag_allowance_ms` under contention.** 900 ms is right on an idle machine and
   short of the 1,412–2,024 ms peak lag at load 12. Raising it delays commits;
   leaving it risks committing mid-phrase on a busy machine.

**Known and recorded, no decision needed:**

5. **`flowctl stats` is not a usable latency source yet.** All 449 sessions in
   `metrics.jsonl` have `words = 0` — they are test and probe traffic, not
   dictation — and `--replay` deliberately writes no metrics. The figures above
   come from the replay sweep instead. Real percentiles need the owner dictating,
   which is the checkpoint.
6. **`released_ms` → `finalized_ms` needs re-measuring on an idle machine.** The
   509 ms p50 above was taken at load averages up to 14 and varies 11–955 ms on
   identical audio. The early quieter sweep gave 449 ms. Either way it is over the
   300 ms budget, but by how much is currently unknown.
7. **CI has never run.** `.github/workflows/ci.yml` triggers on pushes to `main`
   and on pull requests; all of phases 0–2 lives on `worktree-phase-0-2`, well
   ahead of `main`, with the PR still to open. The matrix (Python 3.11 and 3.x)
   will first execute on that PR, and this report is written before that evidence
   exists. Locally the suite is green on 3.12 only — 3.11 is untested here, so if
   anything breaks it will be a version incompatibility that must be fixed rather
   than a floor to raise (spec 13.2).
8. **The three-application injection check remains the owner's**, as it was in
   phase 1. It needs a person speaking into a microphone and watching where the
   text lands.

## Next phase plan

Phase 3 is LLM cleanup: `cleanup.py`, the prompts, the guardrails, `basic_clean`
and the joiner, with one LLM pass over the whole text at release. Its criteria are
a first recorded eval run, a fallback rate ≤ 10%, zero accepted invented-content
cases, and dictation still working when `llama-server` is down.

Two things from this report should be settled first, because phase 3 builds
against both: the RSS allowance (issue 2 — `llama-server` has to fit inside
whatever is left), and whether the first-partial budget is relaxed or the warm-up
decoder is built (issue 1).

The `<new></new>` prompt shape from phase 0's smoke test is still unresolved and
belongs to phase 3: spec 6.2's shape had to be dropped to get a working cleanup
response, and phase 3 needs a prompt that works and is recorded.
