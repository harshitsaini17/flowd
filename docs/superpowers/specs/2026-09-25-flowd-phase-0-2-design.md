# flowd phases 0–2: design delta

Date: 2026-09-25
Status: approved with amendments
Upstream spec: [docs/spec.md](../../spec.md) (authoritative for architecture, models, thresholds, prompts, config defaults)

## Purpose of this document

`docs/spec.md` is the design. It settles the four-process architecture, the model
choices, the state machine, chunking rules, guardrails, prompt text and every
config default. This document does not restate or re-derive any of it.

It records only the **delta**: what the spec leaves open, where the spec meets
this machine's reality, and what changes because the project ships as a public
repository rather than a single owner's tool. Where this document and
`docs/spec.md` disagree on a fact about the environment, this document wins,
because its claims are measured. Where they disagree on design, the spec wins
unless a decision record supersedes it.

## Scope

**Phases 0, 1 and 2 of spec section 12.** Phase 2 is a spec-mandated review
checkpoint.

End state: press a hotkey, speak, watch a live preview separate committed text
from the changing partial, release, and have regex-cleaned raw text pasted into
the focused window — with every stage timed in `metrics.jsonl`.

Explicitly **not** in scope, deferred to their spec phases:

| Deferred | Phase | Why not now |
| --- | --- | --- |
| LLM cleanup, prompts, guardrails, `basic_clean` beyond the joiner's needs | 3 | Needs the eval loop to gate it |
| Chunk scheduler, single-flight, self-correction merge | 4 | Meaningless without an LLM to schedule |
| App context, modes, `vocab.toml`, injector backends *exercised on their target sessions* | 5 | Phases 0–2 test only the owner's session type; the backends themselves ship in phase 1 (see layout) |
| Section 9 edge cases, soak test, full-rewrite mode | 6 | Hardening comes last |

`basic_clean` arrives in phase 1 in the reduced form the joiner needs (fillers,
repeats, spacing, capitalisation, terminal punctuation). Vocabulary replacement,
its third step, waits for phase 5.

## Verified environment

Measured on the target machine, not assumed. Section 2 of the spec asks for this
confirmation before install docs are written.

| Property | Value |
| --- | --- |
| Compositor / session | Hyprland, Wayland (`WAYLAND_DISPLAY=wayland-1`; XWayland present at `DISPLAY=:1`) |
| CPU | AMD Ryzen 5 5600H, 6 physical cores / 12 logical |
| CPU features | AVX2 yes, FMA yes, F16C yes, **AVX-512 no** |
| `llama-server` | `/usr/bin/llama-server`, 0.4.1-dev build 10964, commit `b29c606e28` |
| System Python | 3.14.7 |
| PyGObject | 3.56.3 at `/usr/lib/python3.14/site-packages/gi` |
| gtk4-layer-shell | 1.3.0-1.1, ships `Gtk4LayerShell-1.0.typelib`, `libgtk4-layer-shell.so`, `liblayer-shell-preload.so` |

This **answers the open question in spec section 2**: the owner runs Hyprland.
Hyprland is the first and only backend tested in phases 0–2. Sway, KDE, GNOME
and X11 backends must still import and be selectable in config, and are
exercised only by unit tests with fakes.

`llama-server` thread count follows the spec's "physical cores − 2" rule:
**`-t 4`** on this machine.

### Dependency install status

All spec section 2 packages are present. `llama-cpp` and `xdotool` were
installed during this design pass; the rest were already present.

| Package | Status | Version |
| --- | --- | --- |
| `llama-cpp` | installed this session | 0.4.1-1.1 (pulled `ggml` 0.24.0-2.1) |
| `xdotool` | installed this session | 4.20260303.1-1 |
| `wl-clipboard` | already present | 1:2.3.0-1.1 |
| `wtype` | already present | 0.4-2.2 |
| `gtk4-layer-shell` | already present | 1.3.0-1.1 |
| `python-gobject` | already present | 3.56.3-1 |
| `portaudio` | already present | 1:19.7.0-4.1 |
| `pipewire`, `pipewire-pulse` | already present | 1:1.6.9-1 |
| `xclip`, `ydotool` | already present | 0.13-6.1, 1.0.4-2.1 |

12 unrelated system updates were pending and were deliberately **not** applied.
None of them touch the dependency closure of the two installed packages
(`glibc`, `gcc-libs`, `openssl`, `ggml` all current), so no partial-upgrade
hazard was created, and a full `-Syu` was outside what the task asked for.

**Spec correction:** section 2 lists the LLM runtime as `llama.cpp` from the
AUR. The real package is **`llama-cpp`**, available in both `extra` and
`cachyos-extra-v3`. No AUR helper and no source build is needed. README install
docs use the correct name.

## Decisions taken on the four spec-meets-reality items

Each becomes a numbered decision record under `docs/decisions/`, per spec
section 13.4, rather than a silent choice in code.

### 1. STT API shape — ADR 0001, written before any STT code

The one genuine unknown, and all of phase 2 depends on it. To be resolved by
reading the **installed** `moonshine-voice` source and docs, never by guessing,
per spec rule 13.1.2.

ADR 0001 must state, with evidence:

1. The exact package name, version and upstream repository. The spec's source
   link may point at a fork; this is verified rather than inherited.
2. Whether a **native streaming API with incremental and committed results**
   exists. If it does, use it. If it does not, emulate commit events per spec
   section 5.3: re-transcribe the current utterance incrementally and commit on
   `commit_silence_ms` of VAD silence.
3. **Whether `moonshine-voice` exposes built-in voice-activity or segmentation
   support.** Spec section 5.2 prefers it if present. If present, use it and
   ship no separate VAD model. If absent, fall back to Silero (item 2 below).
4. The precise API calls used, and the model files the library downloads.

### 2. VAD without PyTorch — ADR 0002 (conditional on ADR 0001 item 3)

The PyPI `silero-vad` package (6.2.3) pulls `torch`. Spec section 13.3 names
"wanting PyTorch for VAD" as an escalation trigger, and section 5.2 already
specifies ONNX at a few megabytes.

Resolution, only if `moonshine-voice` has no usable built-in VAD: fetch
`silero_vad.onnx` directly and run it through the `onnxruntime` that Moonshine
already requires. **The ONNX file is pinned in `models.lock`** with source URL,
size, SHA-256 and license, exactly like the two primary models. No `torch`
anywhere in the dependency tree, transitively included.

### 3. Overlay runs outside the venv — ADR 0003

The overlay is a separate process (spec section 4) and needs pacman's
`python-gobject`, which is built against the system Python and is not installable
into a `uv` venv.

Design: `overlay/flowd_overlay.py` is launched with **`/usr/bin/python3`
explicitly**, imports only the standard library plus `gi`, and shares no code
with the daemon package. Its entire contract with the daemon is the
newline-delimited JSON protocol on stdin from spec section 4, so the process
boundary doubles as the test seam — the daemon is tested against a fake overlay,
the overlay against recorded JSON lines.

ADR 0003 must record **whether `LD_PRELOAD` of `libgtk4-layer-shell.so` is
required** for the GI bindings to work, or whether importing
`gi.repository.Gtk4LayerShell` suffices on its own. Both `liblayer-shell-preload.so`
and the typelib ship in the package, so the preload path demonstrably exists;
what is unverified is whether it is mandatory. The finding determines how
`flowd` spawns the child and what the README documents. Verified by running a
real overlay window on Hyprland and confirming, per spec section 5.8, that it
anchors bottom-center and **never takes keyboard focus** — a focus-stealing
overlay breaks injection and is worse than no overlay.

### 4. Python version — ADR 0004 if a pin is needed

System Python is 3.14.7 and spec section 2 says use the system version.
`onnxruntime` 1.30.0 publishes cp314 wheels and declares `>=3.11`, so 3.14 is
plausible; `moonshine-voice` 0.1.5 is sdist-only and its transitive deps on 3.14
are unverified.

Plan: attempt 3.14 first. If resolution or import fails, pin 3.13 through `uv`
and record which, and why, in ADR 0004. Either way `pyproject.toml` declares
**`requires-python = ">=3.11"`** so the public repo is not bound to one
contributor's system Python.

## Public-repository seams

The spec is written for "the owner". These are the changes that make it usable
by anyone, and they are additive — no spec behaviour changes.

- **`LICENSE`**: MIT. Model licenses stay separately recorded in `models.lock`
  (Moonshine MIT, LFM Open License) because they bind the downloaded weights,
  not this source.
- **`README.md`** addressed to any user, not the owner: install with the
  corrected package names, `fetch_models.sh`, hotkey setup for Hyprland `bind`
  plus Sway `bindsym`, KDE, GNOME and `sxhkd` for X11, both toggle and
  push-to-talk, `ydotool` uinput setup as a **manual** step the user runs,
  and troubleshooting.
- **`CONTRIBUTING.md`**, **`CODE_OF_CONDUCT.md`**, issue and PR templates.
- **CI** (GitHub Actions): `ruff`, `mypy` and the model-free `pytest` suite, on
  **Python 3.11 and the latest release**, so the floor and the ceiling of the
  declared range are both covered.
- **`.gitignore`** excludes models, `eval/data/`, `eval/results/`,
  `metrics.jsonl` and `vocab.toml`, so audio, transcripts and personal
  vocabulary can never enter git history.
- **Privacy defaults unchanged from spec section 13.2**: no network calls at
  runtime after model download, no telemetry, `log_transcripts = false`.

## Eval approach for this checkpoint

Adjusted from spec section 11.3 on the owner's instruction: the owner's
verification is pass/fail — does dictation work as expected — not a metrics
matrix. The WER, fallback-rate and invented-content gates are defined in the
spec and stay defined, but they only become enforceable in phase 3 when there is
an LLM to measure.

- `scripts/fetch_eval_audio.sh` fetches public speech samples for replay.
  **LibriSpeech is CC BY 4.0** — the underlying LibriVox readings are public
  domain, but the corpus itself carries an attribution requirement. The script
  records that attribution, and **no sample is ever committed**: the fetch
  directory is gitignored.
- `flowd --replay file.wav` runs the real pipeline and prints final text plus
  stage timings instead of injecting. **Real time by default**, so measured
  latencies mean something, with **`--fast`** to run as fast as the CPU allows
  for tests.
- At the phase 2 checkpoint the owner also replays a few of their own clips.

## Testing strategy

Test-driven where behaviour is deterministic; the spec's own unit-test list
(section 11.1) scoped to phases 0–2.

| Unit | Tests |
| --- | --- |
| State machine | Every row of the spec section 4 table, including 200 ms debounce and `start` ignored while FINALIZING or INJECTING |
| Committer | Silence commit, stable-prefix rule, "keep at least the last 3 words uncommitted" |
| Injector | Clipboard snapshot and restore, **non-text MIME skips the clipboard method**, backend fallthrough — subprocesses mocked |
| `basic_clean` + joiner | Fillers, immediate repeats, spacing, capitalisation, terminal punctuation |
| Config | TOML load, validation, invalid reload keeps the old config |
| Control protocol | Each command, single-instance lock, stale socket removal |

Real models are exercised through `--replay`, outside the model-free CI suite.
The microphone path cannot be automated and is what the checkpoint verifies.

## Repository layout for phases 0–2

Spec section 8.2, restricted to what these phases create. Files the later
phases add are not stubbed out; empty placeholders are noise.

```text
flowd/
├── LICENSE  README.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md
├── pyproject.toml  models.lock  vocab.toml.example  .gitignore
├── .github/workflows/ci.yml, ISSUE_TEMPLATE/
├── flowd/
│   ├── main.py  control.py  config.py  state.py
│   ├── audio.py  vad.py  stt.py  committer.py
│   ├── joiner.py  guardrails.py      # basic_clean only; checks land in phase 3
│   ├── inject/  base.py  clipboard.py  wtype.py  ydotool.py  xdotool.py
│   ├── overlay_ipc.py  metrics.py
├── overlay/flowd_overlay.py          # system python3, stdlib + gi only
├── flowctl
├── systemd/  flowd.service  flowd-llm.service
├── scripts/  fetch_models.sh  fetch_eval_audio.sh  smoke_llm.sh
├── docs/  spec.md  decisions/  reports/  superpowers/specs/
├── tests/
└── eval/                              # fetch target for replay audio; gitignored, run_eval.py lands in phase 3
```

Injector backends beyond clipboard ship as thin, tested implementations in
phase 1 because the base interface and fallthrough logic need them to be real to
be meaningful; phase 5 is where they get exercised on their target sessions.

## Acceptance criteria

Straight from spec section 12, with the one environment-driven adjustment noted.

**Phase 0** — both models download and hash-verify against `models.lock`;
`llama-server` answers a cleanup prompt (**retained in phase 0**, since
`llama-cpp` is now installed); Moonshine transcribes a sample WAV from the
command line; ADR 0001 records versions and API notes.

**Phase 1** — toggle dictation pastes raw text into a terminal, a browser text
field and a code editor; every stage timed in `metrics.jsonl`; cancel injects
nothing; state-machine unit tests pass.

**Phase 2** — first partial ≤ 300 ms after speech onset; the overlay never takes
focus and paste still lands in the original app; committer unit tests pass.

Then stop, write `docs/reports/phase-2.md` per the spec section 14.1 template,
and hand it over. Measured numbers only, from `metrics.jsonl` — never estimates,
per spec rule 13.1.6. Any criterion that cannot be met is reported as unmet with
its reason, not quietly passed, per spec rule 13.2.

## Commit and repository conventions

- Commit messages name phase and component, per spec rule 13.1.7:
  `phase2(committer): stable-prefix rule`.
- Small commits, `pytest` green at each one.
- Repository created public via `gh` as `harshitsaini17/flowd` once the
  implementation plan is approved.

## Escalation triggers carried forward

Per spec section 13.3, work stops and a decision record is written if: the spec
conflicts with reality (no streaming API; the overlay cannot avoid taking focus
on Hyprland), a budget is missed by more than 25% after the section 10.4 steps,
a new dependency exceeds 50 MB, root or udev changes become necessary beyond the
documented manual `ydotool` step, or the same failure survives three fix
attempts.
