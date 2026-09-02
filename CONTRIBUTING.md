# Contributing to flowd

Thanks for looking. flowd is a dictation daemon, which means most of its hard
problems are other people's desktops: a compositor that reports focus
differently, an application that ignores synthetic keystrokes, a microphone that
another process is holding. Bug reports from a setup we have not seen are worth
as much as patches.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

```bash
git clone https://github.com/harshitsaini17/flowd
cd flowd
uv venv
uv pip install -e '.[dev]'
uv run pytest
```

The test suite needs no models, no microphone and no compositor. If it wants any
of those, that is a bug in the test — see "Tests" below. You do not need to run
`scripts/fetch_models.sh` to work on most of the codebase.

## Before you push

Run what CI runs:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy flowd flowctl
```

CI runs these on Python 3.11 and on the latest release. `mypy` is in strict
mode, and `flowctl` is named explicitly because it has no `.py` extension and
mypy's directory walk would otherwise skip the one file that runs on every
keypress.

## Commits

```
phase<N>(component): summary in the imperative
```

For example `phase1(inject): clipboard and typing backends with argv-only
subprocesses`. `<N>` is the build phase from
[`docs/spec.md`](docs/spec.md) section 12; the component is the module or
subsystem. Work that belongs to no phase — tooling, dependency pins, repository
chores — uses `chore:` or `docs:`.

Write the body for someone reading `git log` in a year with no memory of the
conversation. If you changed something because the obvious approach did not
work, say what you measured. Several comments in this codebase exist because a
tool behaved differently from its documentation, and the commit that found it is
the only record of how.

Commit at logical units, not at the end. Do not commit a red suite.

## What the spec is for

[`docs/spec.md`](docs/spec.md) is authoritative. It fixes the architecture, the
stage budgets, the config defaults and the phase order, and code that disagrees
with it is wrong until the spec changes.

The spec is also a document written before the code existed, so parts of it are
wrong. When reality disagrees — an API that does not exist as described, a
default that measurably misbehaves — the answer is a decision record, not a
quiet edit:

**Write a record in [`docs/decisions/`](docs/decisions/) before you change:**

- a default value in `config.toml`
- which model flowd uses, or how it is pinned in `models.lock`
- the process, thread or queue structure of section 4
- anything the spec states as a rule

Number it in sequence (`0004-<topic>.md`), and include the evidence: the command
you ran, its output, the versions involved. A record that says "this seemed
better" is not a record.
[`0001-stt-api.md`](docs/decisions/0001-stt-api.md) is the shape to copy.

## Tests

Written test-first, and the test must fail before the implementation exists. A
test that passed the moment you wrote it has not shown it can catch anything.

Three hard rules:

- **No models.** Loading Moonshine takes seconds and 269 MB. Use
  `FakeSttEngine`, which replays scripted events.
- **No microphone, no compositor, no network.** Every side effect in the daemon
  arrives as an injected collaborator precisely so it can be faked. If you find
  yourself unable to test something without hardware, the seam is missing —
  add it rather than skipping the test.
- **No wall-clock dependence.** Inject a clock. The state machine's debounce is
  measured against one, and a test that races `time.monotonic` will fail on
  someone else's slower runner.

One property resists all of that: whether the overlay takes keyboard focus. Only
a compositor can answer it, and the answer is what stands between a preview and
a window that swallows the dictation (spec 5.8,
[ADR 0003](docs/decisions/0003-overlay-focus.md)). It lives in
`scripts/check_overlay_focus.py` instead — run by hand on a layer-shell
compositor, with a window focused, when you touch the overlay:

```bash
uv run python scripts/check_overlay_focus.py
```

Add to it rather than trusting the unit suite there. `tests/test_overlay_ipc.py`
proves the daemon writes well-formed protocol and
`tests/test_overlay_process.py` proves the child parses it, and both pass
whether or not the window behaves.

Name tests for the behaviour they pin, not the function they call:
`test_silent_session_returns_to_idle`, not `test_finalize_2`. When a test exists
because of a specific defect, say so in its docstring — several here do, and it
is the difference between a future reader deleting a puzzling assertion and
understanding why it guards something.

## Never commit

- **Audio.** No `.wav`, no recordings, not as a fixture and not as an example.
  Evaluation audio is fetched by `scripts/fetch_eval_audio.sh` at the point of
  use, and `eval/audio/` is gitignored.
- **Transcripts.** Not yours, not anyone's. Dictation contains passwords and
  private messages.
- **`metrics.jsonl`.** It is local state about how you use your own machine.
- **Model weights.** They are pinned by hash in `models.lock` and downloaded.
- **`vocab.toml`.** Personal vocabulary is personal; `vocab.toml.example` is the
  committed one.

`.gitignore` covers all of these. If you have to fight it to add a file, that is
the answer.

## Working on the injection path

This is where flowd meets the rest of the desktop, and it is the part most
likely to break on a machine you do not own. Two things to know:

Dictated text reaches every subprocess as an argv element or on stdin, never
interpolated into a shell string, and `subprocess` is always called with a list
and no shell. Someone dictating "delete slash star" must produce those words in
their editor, not an event anywhere else.

The backends are probed, not assumed. Before you trust a tool's documentation,
run it: `wl-copy` deadlocks when its output is captured, `xclip -t TARGETS -o`
reports selection metadata that is not a data format, and `ydotool type`
interprets backslash escapes in its arguments by default. Each of those is a
comment in the code because it cost a debugging session.

If you are adding a backend, it needs: an `available()` that checks the tool for
the *current session type*, a real subprocess probe recorded in the pull
request, and a test that pins its argv.

## Pull requests

Describe what you changed and how you know it works. If you found something
surprising about a tool or a compositor, put it in the description — that is
often the most valuable part.

For a bug fix, include the failing test first. For anything touching the
architecture or a default, link the decision record.

Small, focused pull requests get reviewed faster than large ones, and a pull
request that does one thing is one that can be reverted cleanly if it turns out
to be wrong on a desktop nobody tested.
