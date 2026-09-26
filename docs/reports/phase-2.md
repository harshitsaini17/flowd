# Phase 2 report

## Summary

- Streaming STT replaces batch: Moonshine's native `create_stream` feeds the
  committer, and `LineCompleted` is the authoritative commit signal (ADR 0001).
  Release → text injected fell from phase 1's ~2,680 ms to a 288 ms p50 on an
  idle machine (513 ms under the load the first sweep ran at).
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
time, first sweep.** Taken while a training job of the owner's was running; the
idle re-measurement is below. Every reading carries the load average that
produced it, for the reason in the next paragraph.

| Stage | p50 | p95 | Range | Budget (spec 10.1) | Verdict |
|---|---|---|---|---|---|
| Speech onset → first partial | 1,384 ms | 1,531 ms | 820–1,531 | ≤ 300 ms | **Missed, 4.6×** |
| Release → last chunk committed | 509 ms | 955 ms | 11–955 | ≤ 300 ms | **Missed, 1.7× — but see below** |
| Release → text injected | 513 ms | 957 ms | 12–957 | p50 ≤ 600 ms, p95 ≤ 1,000 ms | **Pass** |
| Injection itself (`finalized` → `inject`) | 1.8 ms | — | 1.1–6.4 | — | — |

**The release → committed figure was measuring the machine, not the code.** A
training job of the owner's ran throughout, taking the load average from 0.97 to
14.0 across the sweep. Re-running a single
clip three times gave 935 ms, 11 ms and 723 ms for byte-identical audio — the
spread is not a property of the clips. The mechanism is direct: this stage is the
tail of audio not yet transcribed when the speaker releases, so it grows with
transcription lag, and lag grows with contention. The quieter early sweep
(load 0.97 rising) gave a 449 ms p50 with the same shape. Treat 509 ms as an
upper bound taken under load, not as the machine's figure.

**Re-measured on an idle machine** — same 12 clips, same harness, load 0.10 and
98.5% idle at the start, no training job:

| Stage | p50 | p95 | Range | Budget (spec 10.1) | Verdict |
|---|---|---|---|---|---|
| Release → last chunk committed | 287 ms | 806 ms | 7–806 | ≤ 300 ms | **p50 passes, p95 does not** |
| Release → text injected | 288 ms | 806 ms | 7–806 | p50 ≤ 600 ms, p95 ≤ 1,000 ms | **Pass** |
| First partial (session-relative) | 1,454 ms | 1,512 ms | 901–1,512 | — | see note |

Release → committed halves, from 509 ms to 287 ms, which confirms the mechanism
above: the stage is transcription lag, and lag is contention. **Whether that
counts as meeting the budget depends on a reading of spec 10.1.** Its row is
written `≤ 300 ms` with no qualifier, while the two rows around it carry
explicit ones (`p50 ≤ 400 ms`, and `p50 ≤ 600 ms, p95 ≤ 1,000 ms`). Taking the
unqualified form at its word, the p95 governs and 806 ms misses by 2.7×; taking
it as a median like its siblings, 287 ms passes. This report does not decide
that — see known issue 5.

The load column in this sweep still climbs, 0.14 to 10.2. That is flowd's own
onnxruntime thread pool rather than a competing job, so unlike the first sweep
it is the system under test and not noise in it. First partial is quoted
session-relative here because that is what `metrics.jsonl` records; it is not
comparable to the 1,384 ms onset-relative figure above, which subtracts each
clip's own room tone.

Two things are load-independent and can be trusted. First-partial latency barely
moved — 820–1,531 ms across loads 1.4 to 14.0, and 901–1,512 ms on the idle
machine — which is what makes ADR 0004's warm-up floor a structural finding
rather than a contention artifact. And the end-to-end budget passes with room to
spare at both ends of that range.

**Accuracy, raw streaming output against LibriSpeech's own reference:** 6.3% WER
(14 word edits over 221 reference words), before any LLM cleanup. The idle
re-measurement of the same 12 clips gave 5.9% (13 edits), and an intermediate
sweep 7.2% — see known issue 9 on why identical audio does not give an identical
transcript here. Phase 2 has no accuracy criterion — the eval is phase 3's — but
a latency number is worthless if
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
[ADR 0002](../decisions/0002-vad-from-segmentation.md) asked this report to do.** The
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
- **No VAD model** — [ADR 0002](../decisions/0002-vad-from-segmentation.md). Spec 5.2
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
5. **Which reading of the release → committed budget governs, and therefore
   whether it escalates.** Spec 10.1 writes this row `≤ 300 ms` with no
   qualifier, where the row above it says `p50 ≤ 400 ms` and the row below says
   `p50 ≤ 600 ms, p95 ≤ 1,000 ms`. On an idle machine p50 is 287 ms (passes) and
   p95 is 806 ms (2.7× over). The two readings disagree about whether phase 2
   met this criterion, so the owner's reading decides it.

   **It does not escalate under spec 13.3 yet either way**, and the reason is
   worth recording. That row triggers on "a budget missed by > 25% *after the
   section 10.4 steps*", and step 1 — "ONNX Runtime intra-op threads set
   explicitly" — has never been performed: nothing in flowd configures ORT
   threading. Before escalating, someone has to try it. What was found about how
   far it can be tried:

   - Inference does not run through the venv's `onnxruntime` at all. It runs
     inside `libmoonshine.so`, which links its own vendored
     `libonnxruntime-13ab8084.so.1`, so a Python `SessionOptions` never reaches
     the session that matters. Any thread setting has to go through the library.
   - The library does expose one lever: an exported
     `ort_maybe_force_single_thread(const OrtApi*, OrtSessionOptions*)` that
     reads the environment variable `MOONSHINE_ORT_SINGLE_THREAD` and mutates
     the session options. That is a real, reachable ORT thread setting — but it
     only forces *one* thread, which on a 6-core machine is the wrong direction
     for a latency budget. Worth measuring rather than assuming (thread-sync
     overhead can dominate on models this small), and it is a one-line
     experiment, but it is not a thread *count*.
   - No intra-op or inter-op thread-count key appears anywhere in the library's
     strings. `Transcriber(options=...)` is documented as taking "advanced C API
     options", and the option keys visible in the binary are session-level ones
     (`session.load_model_format`, `session.use_env_allocators`,
     `session.disable_prepacking`) rather than threading. A thread count may
     simply not be reachable without rebuilding the library.

   So the honest status is: step 1 is untried, partly reachable, and possibly
   not fully reachable. Phase 3 should try the env variable and record the
   result, and if a thread count turns out to be unreachable, that is itself a
   spec-versus-reality finding for 13.3's first row rather than a budget one.

**Known and recorded, no decision needed:**

6. **`flowctl stats` is not a usable latency source yet.** All 449 sessions in
   `metrics.jsonl` have `words = 0` — they are test and probe traffic, not
   dictation — and `--replay` deliberately writes no metrics. The figures above
   come from the replay sweep instead. Real percentiles need the owner dictating,
   which is the checkpoint.
7. **CI now runs, and is green on both legs** — run 36215389148 on commit
   `3e03f7f`, Python 3.11 and the 3.14.7 that `3.x` resolves to. This item
   previously said CI had never executed and named 3.11 as the leg at risk.
   Both halves turned out wrong. 3.11 passed on the first PR run; the leg that
   failed was `3.x`, and not for a version incompatibility: `3.x` is
   `setup-python` syntax that `uv` cannot parse ("No interpreter found for
   executable name `3.x`"), so that leg never selected an interpreter at all and
   tested nothing. Fixed in `354e218` by resolving the version through
   `setup-python` and handing `uv` the exact interpreter path it produced — the
   comment there records why `uv --python 3` is not a substitute, since it
   prefers uv's own managed build and would quietly test whatever was cached.
   Spec 13.2's floor is untouched.
8. **The three-application injection check remains the owner's**, as it was in
   phase 1. It needs a person speaking into a microphone and watching where the
   text lands.
9. **Identical audio does not give an identical transcript, which constrains how
   phase 3 can measure accuracy.** The same 12 clips scored 6.3%, 7.2% and 5.9%
   WER across three sweeps. This is not model nondeterminism: `--replay` feeds
   audio in real time by default, so where a commit boundary falls depends on how
   far transcription has lagged at that instant, and lag depends on machine load.
   Different boundaries mean a differently segmented transcript, and the segments
   are what `basic_clean` and the joiner see.

   The consequence for phase 3 is concrete: a real-time replay cannot be the
   basis of a reproducible WER number, and phase 3's eval set needs `--fast`
   (which bypasses the pacing) or an explicitly fixed chunking. **Phase 3 should
   confirm that `--fast` actually produces byte-identical transcripts across runs
   before building an eval on it** — that has not been tested, and if it does not,
   the eval needs a determinism fix before it needs accuracy targets.

### Deferred review findings

Findings from the two code reviews that were graded Minor and deliberately not
fixed, kept here because they are the ones an owner would otherwise only find by
hitting them. They are numbered as the reviewers filed them, so they match the
`Final: minor (deferred)` lines in
[`phase-0-2-rulings.md`](phase-0-2-rulings.md)'s sibling ledger; the gaps in the
sequence are findings that were fixed or promoted instead. All six were
re-checked against the code at this commit and all six are still open.

- **#5 — a corrupt `models.lock` raises instead of explaining.**
  `verify_models` (`flowd/models.py:95`) parses the lock with
  `json.loads(...)["models"]` and no guard, so a truncated or hand-edited file
  reaches `_verify_or_exit` as a `JSONDecodeError` or `KeyError` traceback rather
  than spec 3's "clear error". The message it should route through —
  "refusing to start; run scripts/fetch_models.sh" — is already on the line
  below. `build_lock` gained this tolerance in the second review round; that is a
  different function with a different caller and does not cover this path.
- **#6 — `FLOWD_SOCKET` moves the client but not the daemon.** It is read at
  `flowctl:36` and has no counterpart in `flowd.config.runtime_dir()`, so setting
  it points `flowctl` at a socket the daemon never creates and the two stop
  seeing each other. Either honour it on both sides or name it test-only in the
  docstring.
- **#7 — the `/tmp` runtime fallback is pre-creatable.**
  `flowd/config.py:43` degrades to `/tmp/flowd-<uid>` when `XDG_RUNTIME_DIR` is
  unset, and another local user can create that directory first and own it, or
  squat the socket path. The socket's own mode is 0o600 and pinned by a test, and
  the fallback is unreachable under a normal user session, which is why this is
  Minor rather than higher.
- **#8 — `Chunk.t_committed` uses a different clock from the rest of the
  session.** It defaults to `time.monotonic` (`flowd/session.py:22`) while
  `Session.started_at` takes the injected clock — the same two-time-bases
  mismatch a Task 19 ruling fixed for `started_at`. Harmless today because
  nothing reads it; phase 3's `t_resolved − t_committed` budget will.
- **#10 — `metrics.jsonl` has no rotation** and `flowctl stats` reads the whole
  file to take the last 50 lines (`flowd/metrics.py:90`). Forward-looking hygiene
  only at 449 sessions, but it grows without bound.
- **#11 — `Session.mode` is hardcoded and `hotkey.mode` has no consumer.**
  `flowd/session.py:43` writes the literal `"default"` on every metrics line, so
  spec 10.2's `mode` field cannot distinguish a `ptt` session from a `toggle`
  one. `cfg.hotkey.mode` is validated against `("toggle", "ptt")` and then read
  nowhere, which is why the second review round's debounce fix had to be reasoned
  about from the compositor's event sequence rather than from a mode flag in the
  code. Found while checking a reviewer's note, not filed by a reviewer.

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
