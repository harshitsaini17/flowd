# Phase 1 report

## Summary

- The daemon exists end to end: config with XDG fallbacks, the control socket doubling as a single-instance lock, the session state machine with debounce, audio capture, batch STT, rule-based cleanup, the injection backends, `flowctl`, and `--replay`.
- `flowctl` is stdlib-only and answers in 25.9 ms p50, half of spec 5.9's 50 ms budget. The daemon's own response is 0.1 ms; the rest is Python interpreter startup.
- Injection is argv-only. Dictated text reaches every subprocess as an argument or on stdin, never interpolated into a shell string.
- Five latent runtime defects were found by probing the real binaries rather than trusting their documentation: `wl-copy` deadlocks when its output is captured, `xclip -t TARGETS -o` reports ICCCM selection metadata that is not a data format, `ydotool type` interprets backslash escapes in argv, and `available()` reported a tool that was not installed for the running session type.
- Three metrics defects were found while writing this report, and all three are fixed: `mic_open_ms` was structurally `0.0`, a cancelled session wrote no record at all, and nothing marked the release instant, which left two of spec 10.1's budgets uncomputable.
- Batch STT means the whole utterance is transcribed at release. That misses one spec 10.1 budget by design; streaming in phase 2 is the fix, not a tuning exercise.

## Acceptance criteria

| Criterion (from section 12) | Result | Evidence |
|---|---|---|
| Toggle dictation pastes raw text into a terminal, a browser text field and a code editor | **Deferred to the owner** | The full path works against a live daemon: `flowctl start` → `{"ok": true, "session": "7a71945d7448"}`, `flowctl stop` → a reply and an IDLE state, with the microphone really opened (`flowd.audio: mic open: 16000 Hz, 100 ms blocks`). Transcription is verified separately through `--replay` on real speech. The three-application check needs a person speaking into a microphone and watching where the text lands, which is the phase 2 checkpoint the owner runs. All four injection backends report available on this machine (clipboard, wtype, ydotool, xdotool). |
| Every stage is timed in `metrics.jsonl` | **Pass, after three fixes** | 8 real sessions logged. A line now carries `mic_open_ms`, `released_ms`, `finalized_ms` and `inject_ms`. Before the fixes `mic_open_ms` was `0.0` by construction, `released_ms` did not exist, and a cancelled session wrote nothing. See "Deviations". |
| Cancel injects nothing | **Pass** | `test_cancel_injects_nothing` and `test_capture_is_released_on_cancel`. Verified against the live daemon: `flowctl cancel` → `{"ok": true, "cancelled": true}`, state back to IDLE, `mic closed` in the log, and the session's record carries `errors: ["cancelled"]` with no text. `test_cancelling_keeps_the_previous_text_for_flowctl_last` pins that cancelling does not erase what `flowctl last` already held. |
| Unit tests for the state machine pass | **Pass** | `uv run pytest -q` → 204 passed. The state machine has its own file; the daemon's 25 tests drive every command through it with an injected clock. `ruff check`, `ruff format --check` and `mypy flowd flowctl` (strict) all clean on Python 3.11 and latest. |

## Measurements

**Machine.** AMD Ryzen 5 5600H, 6 physical cores / 12 threads, 15 GiB RAM, AVX2 (no AVX-512). Arch Linux, kernel 7.2.6-arch2-1. Wayland under Hyprland.

**Versions.**

| | |
|---|---|
| `moonshine-voice` | 0.1.5 |
| STT model | `medium-streaming-en`, revision `quantized_26_08_21` |
| `llama-server` | 0.4.1-dev, build 10964, commit `b29c606e28` |
| Python (venv) | CPython 3.12.12 |
| Python (system, for the overlay) | 3.14.7 |
| `numpy` / `sounddevice` / `httpx` | 2.5.3 / 0.5.6 / 0.28.1 |

**Control path.** 20 trials each, timed in-process rather than by wrapping each call in `date`:

| | p50 | p95 |
|---|---|---|
| `flowctl status`, full round trip | 25.9 ms | 27.5 ms |
| Daemon response alone, no process start | 0.1 ms | 0.2 ms |
| Bare `python3 -c pass` for comparison | 15.8 ms | 18.2 ms |

Against spec 5.9's 50 ms budget, with 16 ms of that being the interpreter starting and 0.1 ms being the daemon. `flowctl`'s own work is about 10 ms. This is why it imports nothing beyond the standard library; a single `import numpy` would spend the whole budget.

**Hotkey → mic open**, spec 10.1's first row, budget ≤ 100 ms:

| `audio.always_open` | Samples | p50 | Worst |
|---|---|---|---|
| `false` (default) | 8 | 121.8 ms | 138.0 ms |
| `true` | 8 | 26.1 ms | 31.0 ms |

**The default misses this budget.** Opening a PortAudio stream costs 80–140 ms on this machine, and the default closes the stream between sessions. Setting `always_open = true` keeps it open and brings the figure to 26 ms, comfortably inside. The miss is 21.8% over budget, just under spec 13.3's 25% escalation threshold, and it has a config-level mitigation, so it is recorded here rather than escalated. Phase 2 should consider whether `always_open` deserves to be the default; the cost is a permanently held microphone, which is a privacy decision rather than a performance one.

**Release → text injected**, on 12 s of real speech through `--replay`:

| Stage | Value |
|---|---|
| `released_ms` → `finalized_ms` | ~2,680 ms |
| `finalized_ms` → `inject_ms` | ~1.1 ms |

**This misses spec 10.1's ≤ 300 ms "release → last chunk committed" budget by roughly 9×, and it is structural rather than a tuning problem.** Phase 1 ships batch STT: nothing is transcribed until the speaker stops, so the entire utterance's compute lands after release and the figure scales with how long you spoke. Phase 2's streaming engine transcribes during speech and leaves only the tail at release, which is the whole reason it is a separate phase. Recording the number here so phase 2 has a baseline to beat.

Two cautions on these figures. They were taken on a machine with other work running; at load average 15 the same clip finalized in 16.0 s against 2.7 s at load 6.1, so any single reading is worth less than the shape. And `--replay` reports `mic_open_ms: 0.0` legitimately — there is no device to open, the replay capture is an array.

**Idle resource use**, daemon alone with the model loaded:

| | Measured | Budget |
|---|---|---|
| RSS | 631 MB | ≤ 900 MB for flowd + llama-server + overlay |
| CPU, 60 s average | 0.6% | < 1% |

Both inside budget, but the RSS figure is the daemon alone. `llama-server` (phase 3) and the overlay (phase 2) are not yet in it, and 631 MB of the 900 MB allowance is already spent. Worth watching rather than celebrating.

**`flowctl stats` against the real log:**

```json
{
  "mic_open_ms": { "p50": 26.1, "p95": 31.0 },
  "finalized_ms": { "p50": 800.4, "p95": 807.5 }
}
```

**Not measured, and why.** Eval WER, fallback rate and clip rate need the cleanup pass, which is phase 3. First-partial latency needs streaming STT, which is phase 2 — batch STT emits no partials at all, by design. A guessed number in any of these rows would be worse than a gap.

## Deviations from spec

| What | Why | Record |
|---|---|---|
| `mic_open_ms` was `0.0` in every record | The first mark was taken as the timing origin, so the first stage always reported zero — and the first stage is the one with the tightest budget in the whole spec. The origin now fixes when the session object is built, which is when the command arrives: spec 10.1's own `t_cmd`. | This report; `test_the_first_mark_is_measured_not_assumed_to_be_zero` |
| A cancelled session wrote no metrics line | spec 10.2 asks for one line per session, and an abandoned session is a session. How often dictation is cancelled is the signal that a hotkey is misfiring or a microphone is opening slowly, and dropping it left `flowctl stats` reporting a clean history. Cancelled sessions now log with `errors: ["cancelled"]` and no text. | This report; `test_cancelled_session_is_still_logged` |
| Nothing marked the release instant | Two spec 10.1 budgets are deltas from release, including the end-to-end "release → text injected" that is the headline number for the product. Every mark is relative to session start, so neither delta existed. `released_ms` is now marked before any finalize work. | This report; `test_the_release_instant_is_marked` |
| `--version` did not exist | The bug report template instructs reporters to run `flowd --version`. A template naming a command that does not exist wastes the first round trip of every bug report. | `phase1(main): report the version with --version` |
| Commits come from Moonshine's `LineCompleted` event, not the stable-prefix emulation of spec 5.3 | Carried from phase 0: the native streaming API decides commits in the model rather than by a heuristic guessing from outside. | ADR 0001 Q2 |
| No `silero_vad.onnx`, no VAD entry in `models.lock` | Carried from phase 0: Moonshine's VAD exists inside `libmoonshine.so` but is not reachable through the stable C API, so flowd consumes its conclusions as segment boundaries instead. | ADR 0001 Q3 |
| `onnxruntime` is still declared but nothing imports it | Still true, and still dead weight. Removal belongs to the phase 2 VAD task, where the suite can prove nothing needs it. | ADR 0001 |
| Install docs say `llama-cpp`, not spec 2's `llama.cpp` from the AUR | The package is `llama-cpp` in `extra`. Every package name in the README was checked against the repositories before being written down. | Phase 0 report |
| `basic_clean` capitalises the standalone pronoun "i" | Not in the spec's text, but a transcript that says "i think" is wrong in every target application. Pinned by test. | `tests/test_textclean.py` |

## Known issues and open questions

**The default mic-open path misses its budget.** 121 ms against 100 ms. `always_open = true` fixes it at the cost of holding the microphone open for the session's lifetime. That trade is a privacy decision, not a performance one, so it is the owner's call rather than a default I should change unilaterally — spec 13.2 forbids changing a default without a record, and this one deserves the owner's opinion first.

**Batch STT puts all transcription after release.** ~2.7 s for a 12 s clip. Phase 2's streaming engine is the fix. Until then, longer dictations feel proportionally slower at the end, and there is no live preview at all because batch STT emits no partials.

**Idle RSS is 631 MB of a 900 MB budget with two processes still to come.** `llama-server` with a 209 MB Q4_0 model and the GTK4 overlay both land in that allowance. It should fit, but there is less headroom than the number suggests at first glance.

**Three metrics defects in one subsystem, all found by reading real output.** All three passed their unit tests: the tests pinned the behaviour the code had rather than the behaviour the spec asked for. The one that pinned `mic_open_ms == 0.0` was the clearest case — an assertion that documented a defect. Generating real data and comparing it against the spec's budget table is what found them, and it is worth repeating at every checkpoint rather than trusting a green suite.

**One test of mine was flaky and I had written it in the previous task.** The two `flowctl` malformed-reply tests used a fake server that replied without reading the request, which raced the client's `sendall` and failed with EPIPE roughly half the time. A fake that does not follow the protocol tests the timing of the test. Fixed, and verified 10 consecutive runs.

**Not verified on this machine.** `xdotool`'s behaviour under a real X11 session — there is no X display here, so its argv is pinned by test but never executed against a compositor. The overlay's focus behaviour is phase 2 and needs manual Hyprland verification.

## Next phase plan

Phase 2 builds streaming and preview: VAD-derived silence tracking from Moonshine's own segment boundaries, the streaming STT engine behind the existing interface, the committer that tracks which lines are final, the GTK4 overlay as a crash-isolated process, and the daemon wiring that feeds it.

Its acceptance criteria are the first partial within 300 ms of speech onset, and an overlay that never takes focus so paste still lands in the original application. Both need manual verification on a real compositor, which is the checkpoint the owner runs.

Three phase-1 findings shape it: `onnxruntime` comes out when the VAD task proves nothing needs it, `always_open` needs a decision before the mic-open budget can be called met, and the release-relative budgets are now measurable, so phase 2 can be held to them rather than argued about.
