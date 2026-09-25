# flowd Phases 0–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build flowd through spec phase 2 — press a hotkey, speak, see a live preview separating committed text from the changing partial, release, and have regex-cleaned text pasted into the focused window with every stage timed.

**Architecture:** Four processes per spec section 4. A resident `flowd` daemon (asyncio main loop + audio callback + STT worker + injector threads) owns audio, VAD, STT, committing, injection and a Unix control socket. A GTK4 overlay runs as a crash-isolated child on the *system* Python, speaking newline-delimited JSON over stdin. `flowctl` is a per-keypress client that exits immediately. `llama-server` is installed and smoke-tested in phase 0 but not wired in until phase 3.

**Tech Stack:** Python ≥3.11 (`uv` venv), `sounddevice`/PortAudio, `moonshine-voice` + `onnxruntime` for STT, Silero VAD ONNX (unless Moonshine ships VAD), GTK4 + `gtk4-layer-shell` via system `python-gobject`, `wl-clipboard`/`wtype`/`ydotool`/`xdotool` for injection, `pytest` + `ruff` + `mypy`.

**Spec:** [`docs/spec.md`](../../spec.md) (authoritative) and the design delta [`docs/superpowers/specs/2026-09-25-flowd-phase-0-2-design.md`](../specs/2026-09-25-flowd-phase-0-2-design.md). Executors read both.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **`requires-python = ">=3.11"`** in `pyproject.toml`. Never pin a contributor's system Python.
- **No network calls at runtime** after model download. No telemetry, no update checks, no cloud fallback. (spec 13.2)
- **No `torch`**, transitively included. A VAD needing PyTorch is an escalation trigger. (spec 13.3)
- **No `sudo`**, no system files, no groups, no udev rules. Manual steps go in the README. (spec 13.2)
- **`log_transcripts = false`** by default; no audio written outside `eval/` and `--replay`. (spec 13.2)
- **No new dependency over 50 MB** without a decision record. (spec 13.3)
- **No magic numbers.** Every tunable lives in `config.toml` with spec section 8.1 defaults. (spec 13.1.4)
- **Never type partial or unpolished text into the target app.** Partials live only in the overlay. (spec 1, non-goals)
- **AVX2 baseline, no AVX-512.** `llama-server -t 4` on the target machine (6 physical cores − 2).
- **Commit messages name phase and component:** `phase2(committer): stable-prefix rule`. (spec 13.1.7)
- **`pytest` green at every commit.** Never silence a failing check to pass a gate. (spec 13.1.5, 13.2)
- **Stop and write `docs/decisions/NNNN-<topic>.md`** on any spec section 13.3 trigger.

## Review Focus

Five input classes the spec implies but that no task's own happy-path tests would exercise. Each has a test pinned to the task owning the code; the spec's silence on an input is not permission for that input to crash the daemon.

1. **No config file at all** (fresh install, `$XDG_CONFIG_HOME/flowd/config.toml` absent) — must load spec defaults and run, not crash. → Task 4.
2. **XDG variables unset** (`XDG_RUNTIME_DIR`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` missing, as under a bare systemd unit) — must fall back per the XDG basedir spec, not raise `KeyError`. → Task 4.
3. **Text containing shell metacharacters or newlines going into a subprocess** (`$(rm -rf ~)`, backticks, embedded `\n`) — injection backends must pass text as argv or stdin, never through a shell string. → Task 11.
4. **A silent or empty recording** (hotkey pressed and released with no speech) — inject nothing, no crash on an empty buffer or empty joiner input. → Task 13.
5. **Two `flowctl` clients at once, and a stale socket from a killed daemon** — second daemon must refuse to start; a stale socket file must be removed and rebound. → Task 6.

## File Structure

Each file has one responsibility. Backends sit behind interfaces so they are swappable and testable with fakes (spec 13.1.3).

| File | Responsibility |
| --- | --- |
| `flowd/config.py` | TOML load, XDG paths, validation, reload-keeps-old-on-error |
| `flowd/metrics.py` | Stage timers, one JSON line per session, `stats` percentiles |
| `flowd/state.py` | Pure state machine: states, events, transitions, debounce |
| `flowd/control.py` | Unix socket server, JSON protocol, single-instance lock |
| `flowd/audio.py` | `sounddevice` stream, lock-free ring buffer, pre-roll |
| `flowd/vad.py` | Speech/silence per 100 ms block, silence run length |
| `flowd/stt.py` | Moonshine wrapper → `Partial` / `Committed` events |
| `flowd/committer.py` | Commit rules: silence, Moonshine completion, stable prefix |
| `flowd/textclean.py` | `basic_clean` (deterministic, <1 ms) |
| `flowd/joiner.py` | Concatenate + normalise spacing, capitals, terminal punctuation |
| `flowd/inject/base.py` | `Injector` protocol, ordered fallthrough |
| `flowd/inject/clipboard.py` | Snapshot, MIME check, set, paste, restore |
| `flowd/inject/{wtype,ydotool,xdotool}.py` | Typing backends, 200-char chunking |
| `flowd/overlay_ipc.py` | Spawn/respawn overlay child, write JSON lines |
| `flowd/session.py` | `Chunk` / `Session` dataclasses (spec 4 data model) |
| `flowd/main.py` | asyncio wiring, state machine driver, `--replay` |
| `overlay/flowd_overlay.py` | GTK4 window, three zones. **System python3, stdlib + `gi` only** |
| `flowctl` | One JSON line to the socket, print, exit <50 ms |

`flowd/guardrails.py` and the chunk scheduler are phase 3 and 4; they are not stubbed, because empty placeholders are noise.

---
## Phase 0 — Setup

### Task 1: Repository scaffold, tooling and CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `.github/workflows/ci.yml`, `flowd/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`
- Delete: `flowd Local Dictation Tool — Architecture & Build Spec.md` (byte-identical duplicate of the committed `docs/spec.md`; verified with `cmp`)

**Interfaces:**
- Consumes: nothing.
- Produces: the `flowd` package root, a green `ruff` / `mypy` / `pytest` baseline, and `uv run` as the command every later task uses.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "flowd"
version = "0.1.0"
description = "Local, offline, streaming dictation for Linux with LLM cleanup"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
dependencies = [
    "sounddevice>=0.5.0",
    "numpy>=1.26",
    "onnxruntime>=1.20",
    "moonshine-voice>=0.1.5",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.6", "mypy>=1.11"]

[project.scripts]
flowd = "flowd.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["flowd"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
# The overlay runs on the system interpreter with pacman's PyGObject and is
# deliberately outside the venv, so its imports are not resolvable here.
exclude = "^overlay/"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `.gitignore`**

Audio, transcripts, models and personal vocabulary must never enter git history.

```gitignore
__pycache__/
*.py[cod]
.venv/
build/
dist/
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/

# Models are fetched and hash-verified, never committed (spec 3)
models/
*.gguf
*.onnx

# Audio, transcripts, metrics and personal vocabulary stay local (spec 13.2)
eval/data/
eval/results/
eval/audio/
*.wav
metrics.jsonl
vocab.toml
```

- [ ] **Step 3: Create `LICENSE`**

MIT, copyright `2026 Harshit Saini`. Use the standard OSI text verbatim.

- [ ] **Step 4: Create the package and a smoke test**

`flowd/__init__.py`:

```python
"""flowd: local, offline, streaming dictation with LLM cleanup."""

__version__ = "0.1.0"
```

`tests/test_smoke.py`:

```python
def test_package_imports() -> None:
    import flowd

    assert flowd.__version__
```

- [ ] **Step 5: Create the venv and verify the toolchain**

```bash
uv venv
uv pip install -e '.[dev]'
uv run pytest -q
uv run ruff check .
uv run mypy flowd
```

Expected: pytest 1 passed; ruff and mypy clean. If `moonshine-voice` or `onnxruntime` fails to resolve on Python 3.14, retry with `uv venv --python 3.13` and **write `docs/decisions/0004-python-version.md`** recording the failure output and the pin.

- [ ] **Step 6: Create `.github/workflows/ci.yml`**

Tests the floor and the ceiling of the declared range. Model-free: no network, no weights.

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.x"]
    steps:
      - uses: actions/checkout@v4
      - name: Install PortAudio (sounddevice runtime dependency)
        run: sudo apt-get update && sudo apt-get install -y libportaudio2
      - uses: astral-sh/setup-uv@v3
      - run: uv venv --python ${{ matrix.python-version }}
      - run: uv pip install -e '.[dev]'
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy flowd
      - run: uv run pytest -q
```

- [ ] **Step 7: Remove the duplicated root spec**

```bash
cmp "flowd Local Dictation Tool — Architecture & Build Spec.md" docs/spec.md \
  && git rm --cached "flowd Local Dictation Tool — Architecture & Build Spec.md" 2>/dev/null; \
  rm -f "flowd Local Dictation Tool — Architecture & Build Spec.md"
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore LICENSE .github flowd tests
git commit -m "phase0(scaffold): package, tooling, MIT license and CI"
```

---

### Task 2: ADR 0001 — verify the Moonshine STT API before writing STT code

Spec rule 13.1.2 forbids guessing at an upstream API. Every later STT and committer decision depends on the answers, so this task produces a **document**, not code.

**Files:**
- Create: `docs/decisions/0001-stt-api.md`

**Interfaces:**
- Consumes: the installed `moonshine-voice` from Task 1.
- Produces: the answers Tasks 9, 15, 16 and 17 build on — whether native streaming commit events exist, and whether built-in VAD exists.

- [ ] **Step 1: Record the installed version and locate the source**

```bash
uv run python -c "import importlib.metadata as m; print(m.version('moonshine-voice'))"
uv run python -c "import moonshine_voice as mv; print(mv.__file__)"
uv run python -c "import moonshine_voice as mv; print([n for n in dir(mv) if not n.startswith('_')])"
```

- [ ] **Step 2: Answer the four required questions from the installed source**

Read the module's own source and docstrings — not a web search, not the spec's link:

```bash
ls "$(uv run python -c 'import moonshine_voice,pathlib;print(pathlib.Path(moonshine_voice.__file__).parent)')"
grep -rniE 'class |def |stream|partial|commit|vad|segment|endpoint' \
  "$(uv run python -c 'import moonshine_voice,pathlib;print(pathlib.Path(moonshine_voice.__file__).parent)')" \
  --include='*.py' | head -60
```

Questions the ADR must answer with evidence:
1. Exact package name, version, upstream repository URL, and license.
2. Is there a **native streaming API with incremental and committed results**? If yes, the exact calls. If no, Task 17 emulates commits per spec 5.3.
3. **Does it expose built-in voice-activity or segmentation support?** Spec 5.2 prefers it. If yes, Task 15 uses it and ships no separate VAD model. If no, Task 15 uses `silero_vad.onnx` via `onnxruntime`.
4. Which model files it downloads, to which paths, and their sizes.

- [ ] **Step 3: Transcribe a real WAV from the command line**

This is a phase 0 acceptance criterion. Fetch a sample via Task 3's script, then:

```bash
uv run python -c "
import moonshine_voice, sys
# Exact call adapted to the API discovered in Step 2; record it verbatim in the ADR.
print(moonshine_voice.transcribe(sys.argv[1]))
" eval/audio/sample.wav
```

- [ ] **Step 4: Write `docs/decisions/0001-stt-api.md`**

Use the spec 13.4 template (`Status: accepted`, `Phase: 0`) with sections Context, Options, Recommendation, Impact on spec. Paste the real command output as evidence. State plainly in Context whether the spec's assumption of a streaming API held.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/0001-stt-api.md
git commit -m "phase0(stt): record moonshine-voice API and VAD support in ADR 0001"
```

- [ ] **Step 6: Escalate if the spec conflicts with reality**

If there is no streaming API *and* no way to emulate commits within the 300 ms budget, stop and hand over ADR 0001 — this is a spec 13.3 trigger. Do not start Task 3.

---

### Task 3: Model fetch, hash pinning and the llama-server smoke test

**Files:**
- Create: `scripts/fetch_models.sh`, `scripts/fetch_eval_audio.sh`, `scripts/smoke_llm.sh`, `models.lock`, `systemd/flowd-llm.service`
- Test: `tests/test_models_lock.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `verify_models(lock_path: Path, models_dir: Path) -> list[str]` in `flowd/models.py`, returning a list of human-readable mismatch messages (empty means every file verified). Task 13 calls it at startup.

- [ ] **Step 1: Write the failing test**

`tests/test_models_lock.py`:

```python
import hashlib
import json
from pathlib import Path

from flowd.models import verify_models


def _lock(tmp: Path, name: str, sha: str, size: int) -> Path:
    lock = tmp / "models.lock"
    lock.write_text(json.dumps({
        "models": [{
            "name": name, "sha256": sha, "size_bytes": size,
            "url": "https://example.invalid/x", "license": "MIT",
        }]
    }))
    return lock


def test_reports_nothing_when_file_matches(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    assert verify_models(_lock(tmp_path, "a.bin", sha, 5), models) == []


def test_reports_missing_file(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    problems = verify_models(_lock(tmp_path, "a.bin", "0" * 64, 5), models)
    assert len(problems) == 1
    assert "missing" in problems[0].lower()


def test_reports_hash_mismatch(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"tampered")
    problems = verify_models(_lock(tmp_path, "a.bin", "0" * 64, 8), models)
    assert len(problems) == 1
    assert "sha256" in problems[0].lower()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_models_lock.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.models'`

- [ ] **Step 3: Implement `flowd/models.py`**

```python
"""Model file verification against the pinned models.lock (spec 3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Stream a file through SHA-256 so large weights never load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def verify_models(lock_path: Path, models_dir: Path) -> list[str]:
    """Return one message per problem. An empty list means every file verified.

    The daemon refuses to start on any problem (spec 9.2), so the caller needs
    every mismatch at once rather than only the first.
    """
    entries = json.loads(lock_path.read_text())["models"]
    problems: list[str] = []
    for entry in entries:
        path = models_dir / entry["name"]
        if not path.is_file():
            problems.append(f"{entry['name']}: missing from {models_dir}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry["size_bytes"]:
            problems.append(
                f"{entry['name']}: size {actual_size} != pinned {entry['size_bytes']}"
            )
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append(f"{entry['name']}: sha256 {actual} != pinned {entry['sha256']}")
    return problems
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_models_lock.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write `scripts/fetch_models.sh`**

Downloads into `$XDG_DATA_HOME/flowd/models/` and regenerates `models.lock` with name, URL, size, SHA-256 and license per spec 3. Never auto-upgrades.

```bash
#!/usr/bin/env bash
set -euo pipefail

MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/flowd/models"
LOCK="$(dirname "$0")/../models.lock"
LFM_URL="https://huggingface.co/LiquidAI/LFM2.5-350M-GGUF/resolve/main/LFM2.5-350M-QAD-Q4_0.gguf"
LFM_FILE="LFM2.5-350M-QAD-Q4_0.gguf"

mkdir -p "$MODELS_DIR"

echo "==> Fetching cleanup LLM (LFM Open License)"
if [[ -f "$MODELS_DIR/$LFM_FILE" ]]; then
  echo "    already present, skipping (models are never auto-upgraded)"
else
  curl -fL --progress-bar -o "$MODELS_DIR/$LFM_FILE" "$LFM_URL"
fi

echo "==> Fetching STT model via moonshine-voice (MIT)"
# moonshine-voice downloads its own weights on first load; the exact call comes
# from ADR 0001. This warms the cache so the daemon never downloads at runtime.
uv run python -c "import moonshine_voice; moonshine_voice.load_model('medium-streaming-en')"

echo "==> Writing $LOCK"
# Regenerate the lock from what is actually on disk. Review the diff before
# committing: a changed hash means the upstream file changed (spec 3).
uv run python - "$MODELS_DIR" "$LOCK" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] if False else "."))
from flowd.models import sha256_file

models_dir, lock_path = Path(sys.argv[1]), Path(sys.argv[2])
licenses = {".gguf": "LFM Open License", ".onnx": "MIT"}
entries = []
for path in sorted(models_dir.rglob("*")):
    if not path.is_file() or path.suffix not in licenses:
        continue
    entries.append({
        "name": path.relative_to(models_dir).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "url": "",  # fill in for files this script did not download
        "license": licenses[path.suffix],
    })
lock_path.write_text(json.dumps({"models": entries}, indent=2) + "\n")
print(f"    pinned {len(entries)} file(s)")
PY

echo "==> Done. Verify with: uv run python -m flowd.models --check"
```

- [ ] **Step 6: Write `scripts/smoke_llm.sh`** — the phase 0 acceptance criterion

`llama-server` is installed (0.4.1-dev build 10964). Threads = physical cores − 2 = 4 on the target machine.

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL="${XDG_DATA_HOME:-$HOME/.local/share}/flowd/models/LFM2.5-350M-QAD-Q4_0.gguf"
PORT=8177
THREADS="$(( $(lscpu -p=Core,Socket | grep -vc '^#') - 2 ))"
(( THREADS < 1 )) && THREADS=1

[[ -f "$MODEL" ]] || { echo "Model missing. Run scripts/fetch_models.sh first." >&2; exit 1; }

echo "==> Starting llama-server on 127.0.0.1:$PORT with -t $THREADS"
llama-server -m "$MODEL" -c 2048 --jinja --host 127.0.0.1 --port "$PORT" -t "$THREADS" \
  >/tmp/flowd-smoke-llm.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

echo "==> Sending a cleanup prompt"
curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {"role": "system", "content": "You clean up dictated speech. Rewrite ONLY the text inside <new>. Remove filler words. Fix grammar, punctuation and capitalization. Do not add information. Output only the rewritten text."},
      {"role": "user", "content": "<new>so um i think we should uh probably ship it on monday</new>"}
    ],
    "temperature": 0,
    "max_tokens": 64
  }' | python3 -c 'import json,sys; print("RESULT:", json.load(sys.stdin)["choices"][0]["message"]["content"].strip())'

echo "==> Smoke test passed. Server log: /tmp/flowd-smoke-llm.log"
```

Expected: `RESULT:` reads roughly `I think we should probably ship it on Monday.`

- [ ] **Step 7: Write `scripts/fetch_eval_audio.sh`**

**LibriSpeech is CC BY 4.0** — the underlying LibriVox readings are public domain, but the corpus itself requires attribution. Samples are never committed; `eval/audio/` is gitignored.

```bash
#!/usr/bin/env bash
set -euo pipefail

DEST="$(dirname "$0")/../eval/audio"
mkdir -p "$DEST"

cat > "$DEST/ATTRIBUTION.txt" <<'TXT'
Audio fetched by scripts/fetch_eval_audio.sh is from LibriSpeech
(https://www.openslr.org/12/), licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/).

V. Panayotov, G. Chen, D. Povey and S. Khudanpur, "Librispeech: an ASR corpus
based on public domain audio books", ICASSP 2015.

These files are NOT redistributed with flowd: eval/audio/ is gitignored.
TXT

echo "==> Fetching LibriSpeech test-clean sample (CC BY 4.0)"
curl -fL --progress-bar -o "$DEST/test-clean.tar.gz" \
  "https://www.openslr.org/resources/12/test-clean.tar.gz"
tar -xzf "$DEST/test-clean.tar.gz" -C "$DEST"

echo "==> Converting a few utterances to 16 kHz mono WAV for --replay"
find "$DEST" -name '*.flac' | head -5 | while read -r flac; do
  ffmpeg -loglevel error -y -i "$flac" -ar 16000 -ac 1 \
    "$DEST/$(basename "${flac%.flac}").wav"
done
echo "==> Done. See $DEST/ATTRIBUTION.txt"
```

- [ ] **Step 8: Write `systemd/flowd-llm.service`**

```ini
[Unit]
Description=flowd cleanup LLM (llama-server, LFM2.5-350M)
Documentation=https://github.com/harshitsaini17/flowd

[Service]
Type=simple
Environment=FLOWD_MODEL=%h/.local/share/flowd/models/LFM2.5-350M-QAD-Q4_0.gguf
ExecStart=/usr/bin/llama-server -m ${FLOWD_MODEL} -c 2048 --jinja \
          --host 127.0.0.1 --port 8177 -t 4
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

Document in the README that `-t` is physical cores − 2 and users should adjust it.

- [ ] **Step 9: Run everything and commit**

```bash
chmod +x scripts/*.sh
uv run pytest -q && uv run ruff check . && uv run mypy flowd
bash scripts/fetch_models.sh
bash scripts/smoke_llm.sh
git add scripts models.lock systemd flowd/models.py tests/test_models_lock.py
git commit -m "phase0(models): pinned fetch, hash verification and llama-server smoke test"
```

- [ ] **Step 10: Write `docs/reports/phase-0.md`**

Use the spec 14.1 template. Record the real `smoke_llm.sh` output, the model hashes, and `llama-server` build 10964. Measured numbers only.

---
## Phase 1 — Baseline

### Task 4: Config loading, XDG paths and reload

Owns **Review Focus 1** (no config file) and **Review Focus 2** (XDG variables unset). A fresh install has neither; the daemon must still start.

**Files:**
- Create: `flowd/config.py`, `vocab.toml.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_config(path: Path | None = None) -> Config`; `Config` is a frozen dataclass with one nested frozen dataclass per spec 8.1 table (`hotkey`, `audio`, `vad`, `stt`, `chunking`, `llm`, `guardrails`, `inject`, `overlay`, `modes`, `logging`). Also `config_path() -> Path`, `runtime_dir() -> Path`, `state_dir() -> Path`, `data_dir() -> Path`, and `reload_config(current: Config) -> tuple[Config, str | None]` returning the new config and `None`, or the unchanged config and an error message.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from flowd.config import Config, load_config, reload_config, runtime_dir, state_dir


def test_missing_file_yields_spec_defaults(tmp_path: Path) -> None:
    """A fresh install has no config.toml; the daemon must still start."""
    cfg = load_config(tmp_path / "does-not-exist.toml")
    assert cfg.vad.commit_silence_ms == 350
    assert cfg.chunking.max_chunk_words == 25
    assert cfg.inject.order == ("clipboard", "wtype", "ydotool", "xdotool")
    assert cfg.logging.log_transcripts is False


def test_partial_file_overrides_only_named_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = 500\n")
    cfg = load_config(path)
    assert cfg.vad.commit_silence_ms == 500
    assert cfg.vad.tail_ms == 150  # untouched default


def test_xdg_unset_falls_back_to_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under a bare systemd unit XDG_* may be absent; never raise KeyError."""
    for var in ("XDG_RUNTIME_DIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state_dir() == tmp_path / ".local/state/flowd"
    assert runtime_dir().is_absolute()


def test_invalid_value_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = -5\n")
    with pytest.raises(ValueError, match="commit_silence_ms"):
        load_config(path)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\nnot_a_real_key = 1\n")
    with pytest.raises(ValueError, match="not_a_real_key"):
        load_config(path)


def test_reload_keeps_old_config_on_error(tmp_path: Path) -> None:
    """spec 9.5: an invalid reload returns the error and changes nothing."""
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = 400\n")
    good = load_config(path)
    path.write_text("[vad]\ncommit_silence_ms = -1\n")
    new, error = reload_config(good, path)
    assert new is good
    assert error is not None and "commit_silence_ms" in error


def test_config_is_immutable() -> None:
    cfg = load_config(Path("/nonexistent"))
    with pytest.raises(Exception):
        cfg.vad.commit_silence_ms = 1  # type: ignore[misc]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.config'`

- [ ] **Step 3: Implement `flowd/config.py`**

Defaults are transcribed from spec 8.1 exactly. Sequences are tuples so `Config` is deeply immutable.

```python
"""Configuration: XDG paths, TOML loading, validation and reload (spec 8.1)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

APP = "flowd"


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _xdg(var: str, default: str) -> Path:
    """Resolve an XDG base directory, falling back when the variable is unset."""
    value = os.environ.get(var)
    if value:
        return Path(value)
    return _home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def runtime_dir() -> Path:
    """XDG_RUNTIME_DIR is absent under some systemd units; degrade to /tmp."""
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value) / APP
    return Path(f"/tmp/{APP}-{os.getuid()}")


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass(frozen=True, slots=True)
class Hotkey:
    mode: str = "toggle"  # toggle | ptt
    debounce_ms: int = 200


@dataclass(frozen=True, slots=True)
class Audio:
    device: str = "default"
    sample_rate: int = 16000
    block_ms: int = 100
    always_open: bool = False
    preroll_ms: int = 300
    max_session_s: int = 300


@dataclass(frozen=True, slots=True)
class Vad:
    threshold: float = 0.5
    commit_silence_ms: int = 350
    tail_ms: int = 150


@dataclass(frozen=True, slots=True)
class Stt:
    model: str = "medium-streaming-en"
    max_uncommitted_words: int = 25


@dataclass(frozen=True, slots=True)
class Chunking:
    min_chunk_words: int = 5
    max_chunk_words: int = 25
    context_sentences: int = 2
    short_bypass_words: int = 5
    correction_cues: tuple[str, ...] = (
        "no wait", "no no", "actually", "i mean", "sorry",
        "scratch that", "let me rephrase",
    )


@dataclass(frozen=True, slots=True)
class Llm:
    url: str = "http://127.0.0.1:8177"
    timeout_ms: int = 2000
    final_timeout_ms: int = 800
    max_tokens_factor: float = 1.5


@dataclass(frozen=True, slots=True)
class Guardrails:
    len_ratio_min: float = 0.6
    len_ratio_max: float = 1.3
    len_ratio_min_merged: float = 0.3
    novel_word_max: float = 0.20


@dataclass(frozen=True, slots=True)
class Inject:
    order: tuple[str, ...] = ("clipboard", "wtype", "ydotool", "xdotool")
    restore_delay_ms: int = 150
    terminal_apps: tuple[str, ...] = (
        "kitty", "Alacritty", "foot", "org.wezfurlong.wezterm",
        "konsole", "org.gnome.Terminal",
    )


@dataclass(frozen=True, slots=True)
class Overlay:
    enabled: bool = True
    max_lines: int = 4
    fade_ms: int = 1000


@dataclass(frozen=True, slots=True)
class Logging:
    level: str = "info"
    log_transcripts: bool = False  # never true by default (spec 13.2)


@dataclass(frozen=True, slots=True)
class Config:
    hotkey: Hotkey = Hotkey()
    audio: Audio = Audio()
    vad: Vad = Vad()
    stt: Stt = Stt()
    chunking: Chunking = Chunking()
    llm: Llm = Llm()
    guardrails: Guardrails = Guardrails()
    inject: Inject = Inject()
    overlay: Overlay = Overlay()
    logging: Logging = Logging()
    modes: tuple[tuple[str, str], ...] = (
        ("code", "code"),
        ("org.telegram.desktop", "chat"),
        ("thunderbird", "email"),
    )

    def mode_for(self, app_id: str | None) -> str:
        """Map an app id to a cleanup mode; unknown or None means default."""
        if app_id is None:
            return "default"
        return dict(self.modes).get(app_id, "default")


_POSITIVE_INT = {
    "debounce_ms", "sample_rate", "block_ms", "preroll_ms", "max_session_s",
    "commit_silence_ms", "tail_ms", "max_uncommitted_words", "min_chunk_words",
    "max_chunk_words", "context_sentences", "short_bypass_words", "timeout_ms",
    "final_timeout_ms", "restore_delay_ms", "max_lines", "fade_ms",
}
_UNIT_FLOAT = {"threshold", "novel_word_max"}
_VALID_HOTKEY_MODES = ("toggle", "ptt")
_VALID_LOG_LEVELS = ("debug", "info", "warning", "error")


def _build(section_type: type, raw: dict[str, Any], name: str) -> Any:
    known = {f.name: f for f in fields(section_type)}
    unknown = set(raw) - set(known)
    if unknown:
        raise ValueError(f"[{name}]: unknown key(s): {', '.join(sorted(unknown))}")
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    section = section_type(**kwargs)
    _validate_section(section, name)
    return section


def _validate_section(section: Any, name: str) -> None:
    for field in fields(section):
        value = getattr(section, field.name)
        if field.name in _POSITIVE_INT and (not isinstance(value, int) or value <= 0):
            raise ValueError(f"[{name}] {field.name}: must be a positive integer, got {value!r}")
        if field.name in _UNIT_FLOAT and not (0.0 <= float(value) <= 1.0):
            raise ValueError(f"[{name}] {field.name}: must be between 0 and 1, got {value!r}")


def _validate(cfg: Config) -> None:
    if cfg.hotkey.mode not in _VALID_HOTKEY_MODES:
        raise ValueError(f"[hotkey] mode: must be one of {_VALID_HOTKEY_MODES}")
    if cfg.logging.level not in _VALID_LOG_LEVELS:
        raise ValueError(f"[logging] level: must be one of {_VALID_LOG_LEVELS}")
    if cfg.chunking.min_chunk_words > cfg.chunking.max_chunk_words:
        raise ValueError("[chunking] min_chunk_words must not exceed max_chunk_words")
    if cfg.guardrails.len_ratio_min > cfg.guardrails.len_ratio_max:
        raise ValueError("[guardrails] len_ratio_min must not exceed len_ratio_max")
    if not cfg.inject.order:
        raise ValueError("[inject] order: must list at least one backend")


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, or return spec defaults when the file is absent."""
    path = path or config_path()
    if not path.is_file():
        return Config()
    raw = tomllib.loads(path.read_text())

    sections = {f.name: f.type for f in fields(Config)}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "modes":
            kwargs["modes"] = tuple(sorted((str(k), str(v)) for k, v in value.items()))
            continue
        if key not in sections:
            raise ValueError(f"unknown config section: [{key}]")
        section_type = type(getattr(Config(), key))
        if not isinstance(value, dict):
            raise ValueError(f"[{key}]: expected a table")
        kwargs[key] = _build(section_type, value, key)

    cfg = replace(Config(), **kwargs)
    _validate(cfg)
    return cfg


def reload_config(current: Config, path: Path | None = None) -> tuple[Config, str | None]:
    """spec 9.5: on a validation error keep the old config and report why."""
    try:
        return load_config(path), None
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return current, str(exc)
```

Note `is_dataclass` is imported for the type checker's benefit only if used; drop the import if `ruff` flags it as unused.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: 7 passed.

- [ ] **Step 5: Create `vocab.toml.example`**

```toml
# Copy to $XDG_CONFIG_HOME/flowd/vocab.toml and edit.
# Reload without restarting: flowctl reload

[terms]
# Canonical spellings, passed to the LLM as <vocab> (phase 3+).
Hyprland = "Hyprland"
PipeWire = "PipeWire"
flowd = "flowd"

[replace]
# Fuzzy STT fixes, applied deterministically in basic_clean.
"hyper land" = "Hyprland"
"pipe wire" = "PipeWire"
"flow d" = "flowd"
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/config.py tests/test_config.py vocab.toml.example
git commit -m "phase1(config): TOML loading, XDG fallbacks, validation and reload"
```

---

### Task 5: Metrics log and percentiles

**Files:**
- Create: `flowd/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `state_dir()` from Task 4.
- Produces: `SessionMetrics` with `mark(stage: str) -> None`, `has(stage: str) -> bool`, `count(key: str, n: int = 1) -> None`, `fail(check: int) -> None`, `error(message: str) -> None`, and `to_record() -> dict[str, Any]`; `write_record(record: dict, path: Path) -> None`; `summarise(records: list[dict], last_n: int = 50) -> dict[str, dict[str, float]]` returning `{stage: {"p50": ms, "p95": ms}}`.

- [ ] **Step 1: Write the failing test**

`tests/test_metrics.py`:

```python
import json
from pathlib import Path

from flowd.metrics import SessionMetrics, summarise, write_record


def test_marks_are_relative_and_monotonic() -> None:
    clock = iter([100.0, 100.25, 100.9])
    m = SessionMetrics(session_id="s1", mode="default", clock=lambda: next(clock))
    m.mark("mic_open")
    m.mark("first_partial")
    record = m.to_record()
    assert record["stages"]["mic_open_ms"] == 0.0
    assert record["stages"]["first_partial_ms"] == 250.0


def test_record_excludes_transcript_by_default() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    m.text = "secret words"
    assert "text" not in m.to_record()
    m.log_transcripts = True
    assert m.to_record()["text"] == "secret words"


def test_counts_and_guardrail_failures() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    m.count("words", 12)
    m.count("chunks")
    m.fail(3)
    m.fail(3)
    record = m.to_record()
    assert record["counts"]["words"] == 12
    assert record["counts"]["chunks"] == 1
    assert record["fallback_checks"] == {"3": 2}


def test_has_reports_whether_a_stage_was_marked() -> None:
    m = SessionMetrics(session_id="s1", mode="default")
    assert m.has("first_partial") is False
    m.mark("first_partial")
    assert m.has("first_partial") is True


def test_write_record_appends_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "metrics.jsonl"
    write_record({"session_id": "a"}, path)
    write_record({"session_id": "b"}, path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["session_id"] == "b"


def test_summarise_computes_p50_and_p95() -> None:
    records = [{"stages": {"inject_ms": float(i)}} for i in range(1, 101)]
    stats = summarise(records)
    assert stats["inject_ms"]["p50"] == 50.0
    assert stats["inject_ms"]["p95"] == 95.0


def test_summarise_handles_no_records() -> None:
    assert summarise([]) == {}
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.metrics'`

- [ ] **Step 3: Implement `flowd/metrics.py`**

```python
"""Per-session stage timing, written as one JSON line each (spec 10.2)."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionMetrics:
    """Collects stage timings for one dictation session.

    Times are recorded from a monotonic clock and reported in milliseconds
    relative to the first mark, so records are comparable across sessions.
    """

    session_id: str
    mode: str
    clock: Callable[[], float] = time.monotonic
    app_id: str | None = None
    backend: str | None = None
    log_transcripts: bool = False
    text: str | None = None
    errors: list[str] = field(default_factory=list)
    _marks: dict[str, float] = field(default_factory=dict, init=False)
    _counts: Counter[str] = field(default_factory=Counter, init=False)
    _checks: Counter[int] = field(default_factory=Counter, init=False)
    _origin: float | None = field(default=None, init=False)

    def has(self, stage: str) -> bool:
        """True once `stage` has been marked; lets callers mark a stage only once."""
        return stage in self._marks

    def mark(self, stage: str) -> None:
        now = self.clock()
        if self._origin is None:
            self._origin = now
        self._marks[stage] = (now - self._origin) * 1000.0

    def count(self, key: str, n: int = 1) -> None:
        self._counts[key] += n

    def fail(self, check: int) -> None:
        """Record a guardrail rejection by check number (spec 7.4)."""
        self._checks[check] += 1

    def error(self, message: str) -> None:
        self.errors.append(message)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "session_id": self.session_id,
            "ts": time.time(),
            "mode": self.mode,
            "app_id": self.app_id,
            "backend": self.backend,
            "stages": {f"{k}_ms": round(v, 1) for k, v in self._marks.items()},
            "counts": dict(self._counts),
            "fallback_checks": {str(k): v for k, v in self._checks.items()},
            "errors": self.errors,
        }
        if self.log_transcripts and self.text is not None:
            record["text"] = self.text
        return record


def write_record(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_records(path: Path, last_n: int = 50) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-last_n:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a truncated final line must not break `flowctl stats`
    return records


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; adequate for the tens of samples we keep."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100.0 * len(ordered)) - 1))
    return ordered[index]


def summarise(records: list[dict[str, Any]], last_n: int = 50) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[float]] = {}
    for record in records[-last_n:]:
        for stage, value in record.get("stages", {}).items():
            buckets.setdefault(stage, []).append(float(value))
    return {
        stage: {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}
        for stage, values in buckets.items()
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/metrics.py tests/test_metrics.py
git commit -m "phase1(metrics): session stage timing and percentile summary"
```

---

### Task 6: Control socket, single-instance lock and stale socket recovery

Owns **Review Focus 5**. The socket doubles as the single-instance lock (spec 4).

**Files:**
- Create: `flowd/control.py`
- Test: `tests/test_control.py`

**Interfaces:**
- Consumes: `runtime_dir()` from Task 4.
- Produces: `VALID_COMMANDS: frozenset[str]`; `parse_command(line: bytes) -> dict[str, Any]` raising `ValueError` on bad input; `async def serve(path: Path, handler: Callable[[dict], Awaitable[dict]]) -> asyncio.Server`; `AlreadyRunning(Exception)`; `async def probe(path: Path) -> bool` — true when a live daemon answers.

- [ ] **Step 1: Write the failing test**

`tests/test_control.py`:

```python
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from flowd.control import AlreadyRunning, parse_command, probe, send, serve


def test_parse_accepts_valid_command() -> None:
    assert parse_command(b'{"cmd": "toggle"}\n') == {"cmd": "toggle"}


def test_parse_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="unknown command"):
        parse_command(b'{"cmd": "selfdestruct"}')


def test_parse_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_command(b"not json at all")


def test_parse_rejects_missing_cmd() -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_command(b'{"args": []}')


async def _echo(request: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "cmd": request["cmd"]}


async def test_round_trip(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        assert await send(sock, {"cmd": "status"}) == {"ok": True, "cmd": "status"}
    finally:
        server.close()
        await server.wait_closed()


async def test_second_daemon_refuses_to_start(tmp_path: Path) -> None:
    """spec 9.5: a live socket means a daemon is already running."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        with pytest.raises(AlreadyRunning):
            await serve(sock, _echo)
    finally:
        server.close()
        await server.wait_closed()


async def test_stale_socket_is_removed_and_rebound(tmp_path: Path) -> None:
    """spec 9.5: a socket file left by a killed daemon must not block startup."""
    sock = tmp_path / "flowd.sock"
    sock.write_bytes(b"")  # a plain file that nothing is listening on
    server = await serve(sock, _echo)
    try:
        assert await send(sock, {"cmd": "status"}) == {"ok": True, "cmd": "status"}
    finally:
        server.close()
        await server.wait_closed()


async def test_probe_false_when_nothing_listening(tmp_path: Path) -> None:
    assert await probe(tmp_path / "absent.sock") is False


async def test_handler_error_returns_error_reply(tmp_path: Path) -> None:
    async def boom(request: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    sock = tmp_path / "flowd.sock"
    server = await serve(sock, boom)
    try:
        reply = await send(sock, {"cmd": "status"})
        assert reply["ok"] is False and "kaboom" in reply["error"]
    finally:
        server.close()
        await server.wait_closed()


async def test_concurrent_clients_are_all_served(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _echo)
    try:
        replies = await asyncio.gather(*(send(sock, {"cmd": "status"}) for _ in range(5)))
        assert all(r["ok"] for r in replies)
    finally:
        server.close()
        await server.wait_closed()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_control.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.control'`

- [ ] **Step 3: Implement `flowd/control.py`**

```python
"""Unix socket control protocol: newline-delimited JSON (spec 4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VALID_COMMANDS = frozenset(
    {"start", "stop", "toggle", "cancel", "status", "last", "stats", "reload"}
)
_MAX_LINE = 64 * 1024

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class AlreadyRunning(Exception):
    """Another daemon is listening on the socket (spec 9.5)."""


def parse_command(line: bytes) -> dict[str, Any]:
    try:
        request = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed request: {exc}") from exc
    if not isinstance(request, dict):
        raise ValueError("malformed request: expected a JSON object")
    cmd = request.get("cmd")
    if cmd is None:
        raise ValueError("missing 'cmd' field")
    if cmd not in VALID_COMMANDS:
        raise ValueError(f"unknown command: {cmd!r}")
    return request


async def probe(path: Path) -> bool:
    """True when a daemon is listening and answers a status request."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
    except (OSError, ConnectionError):
        return False
    try:
        writer.write(b'{"cmd": "status"}\n')
        await writer.drain()
        return bool(await asyncio.wait_for(reader.readline(), timeout=1.0))
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()


async def serve(path: Path, handler: Handler) -> asyncio.Server:
    """Bind the control socket, clearing a stale file left by a dead daemon."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if await probe(path):
            raise AlreadyRunning(f"flowd is already running on {path}")
        log.info("removing stale socket %s", path)
        path.unlink(missing_ok=True)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            if len(line) > _MAX_LINE:
                reply = {"ok": False, "error": "request too large"}
            else:
                try:
                    request = parse_command(line)
                except ValueError as exc:
                    reply = {"ok": False, "error": str(exc)}
                else:
                    try:
                        reply = await handler(request)
                    except Exception as exc:  # a bad command must not kill the daemon
                        log.exception("control handler failed")
                        reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            writer.write(json.dumps(reply).encode("utf-8") + b"\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass  # client hung up; flowctl exits immediately by design
        finally:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_unix_server(on_client, path=str(path))
    # Owner-only: the socket controls the microphone.
    path.chmod(0o600)
    return server


async def send(path: Path, request: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    """Client side: one request, one reply. Used by flowctl and the tests."""
    reader, writer = await asyncio.open_unix_connection(str(path))
    try:
        writer.write(json.dumps(request).encode("utf-8") + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return dict(json.loads(line.decode("utf-8")))
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()
```

Remove the `socket` import if `ruff` reports it unused.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_control.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/control.py tests/test_control.py
git commit -m "phase1(control): socket protocol, single-instance lock, stale socket recovery"
```

---

### Task 7: State machine and session data model

Every row of the spec section 4 transition table is a test. This is a phase 1 acceptance criterion.

**Files:**
- Create: `flowd/state.py`, `flowd/session.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `State` and `Event` string enums; `Machine(debounce_ms: int, clock: Callable[[], float])` with `handle(event: Event) -> Action | None` and a `state` property; `Action` enum naming the side effect the caller performs (`OPEN_MIC`, `FLUSH_AND_FINALIZE`, `DISCARD`, `JOIN`, `HIDE_OVERLAY`, `RELEASE_MIC`). `flowd/session.py` provides the spec 4 `Chunk` and `Session` dataclasses.

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
import pytest

from flowd.state import Action, Event, Machine, State


def machine(clock_values: list[float] | None = None, debounce_ms: int = 200) -> Machine:
    values = iter(clock_values or [i * 10.0 for i in range(1000)])
    return Machine(debounce_ms=debounce_ms, clock=lambda: next(values))


def test_starts_idle() -> None:
    assert machine().state is State.IDLE


def test_idle_start_opens_mic() -> None:
    m = machine()
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.state is State.RECORDING


def test_recording_stop_finalizes() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE
    assert m.state is State.FINALIZING


def test_recording_cancel_discards() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.CANCEL) is Action.DISCARD
    assert m.state is State.IDLE


def test_recording_max_duration_finalizes_like_stop() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.MAX_DURATION) is Action.FLUSH_AND_FINALIZE
    assert m.state is State.FINALIZING


def test_finalizing_resolved_joins() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.CHUNKS_RESOLVED) is Action.JOIN
    assert m.state is State.INJECTING


def test_finalizing_cancel_discards() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.CANCEL) is Action.DISCARD
    assert m.state is State.IDLE


def test_injecting_done_returns_to_idle() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    m.handle(Event.CHUNKS_RESOLVED)
    assert m.handle(Event.INJECT_DONE) is Action.HIDE_OVERLAY
    assert m.state is State.IDLE


def test_start_is_ignored_while_finalizing() -> None:
    """spec 4: a start during FINALIZING is ignored and logged, never queued."""
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.START) is None
    assert m.state is State.FINALIZING


def test_start_is_ignored_while_injecting() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    m.handle(Event.CHUNKS_RESOLVED)
    assert m.handle(Event.START) is None
    assert m.state is State.INJECTING


def test_double_press_within_debounce_is_one_command() -> None:
    """spec 9.1: two commands within debounce_ms count as one."""
    m = machine(clock_values=[0.0, 0.05, 1.0])  # seconds
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is None  # 50 ms later, debounced
    assert m.state is State.RECORDING


def test_commands_outside_debounce_both_apply() -> None:
    m = machine(clock_values=[0.0, 0.5])
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE


def test_toggle_starts_then_stops() -> None:
    m = machine(clock_values=[0.0, 1.0])
    assert m.handle(Event.TOGGLE) is Action.OPEN_MIC
    assert m.handle(Event.TOGGLE) is Action.FLUSH_AND_FINALIZE


def test_fatal_error_from_any_state_releases_mic() -> None:
    for prep in ([], [Event.START], [Event.START, Event.STOP]):
        m = machine()
        for event in prep:
            m.handle(event)
        assert m.handle(Event.FATAL) is Action.RELEASE_MIC
        assert m.state is State.IDLE


def test_stop_in_idle_is_ignored() -> None:
    m = machine()
    assert m.handle(Event.STOP) is None
    assert m.state is State.IDLE


def test_debounce_does_not_block_cancel() -> None:
    """Cancel is a safety valve and must never be swallowed by debounce."""
    m = machine(clock_values=[0.0, 0.01])
    m.handle(Event.START)
    assert m.handle(Event.CANCEL) is Action.DISCARD
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.state'`

- [ ] **Step 3: Implement `flowd/state.py`**

```python
"""The session state machine (spec 4).

Pure logic: it decides transitions and names the side effect to perform, but
performs none itself, so every row of the spec table is directly testable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum

log = logging.getLogger(__name__)


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    INJECTING = "injecting"


class Event(StrEnum):
    START = "start"
    STOP = "stop"
    TOGGLE = "toggle"
    CANCEL = "cancel"
    MAX_DURATION = "max_duration"
    CHUNKS_RESOLVED = "chunks_resolved"
    INJECT_DONE = "inject_done"
    FATAL = "fatal"


class Action(StrEnum):
    OPEN_MIC = "open_mic"
    FLUSH_AND_FINALIZE = "flush_and_finalize"
    DISCARD = "discard"
    JOIN = "join"
    HIDE_OVERLAY = "hide_overlay"
    RELEASE_MIC = "release_mic"


#: Events a user can trigger by keypress, and so subject to debounce (spec 9.1).
_DEBOUNCED = frozenset({Event.START, Event.STOP, Event.TOGGLE})


class Machine:
    def __init__(self, debounce_ms: int = 200, clock: Callable[[], float] = time.monotonic) -> None:
        self._state = State.IDLE
        self._debounce_s = debounce_ms / 1000.0
        self._clock = clock
        self._last_command: float | None = None

    @property
    def state(self) -> State:
        return self._state

    def handle(self, event: Event) -> Action | None:
        """Apply an event. Returns the side effect to perform, or None to ignore."""
        if event in _DEBOUNCED:
            now = self._clock()
            if self._last_command is not None and now - self._last_command < self._debounce_s:
                log.debug("debounced %s", event)
                return None
            self._last_command = now

        if event is Event.FATAL:
            self._state = State.IDLE
            return Action.RELEASE_MIC

        if event is Event.TOGGLE:
            event = Event.START if self._state is State.IDLE else Event.STOP

        match (self._state, event):
            case (State.IDLE, Event.START):
                self._state = State.RECORDING
                return Action.OPEN_MIC
            case (State.RECORDING, Event.STOP) | (State.RECORDING, Event.MAX_DURATION):
                self._state = State.FINALIZING
                return Action.FLUSH_AND_FINALIZE
            case (State.RECORDING, Event.CANCEL) | (State.FINALIZING, Event.CANCEL):
                self._state = State.IDLE
                return Action.DISCARD
            case (State.FINALIZING, Event.CHUNKS_RESOLVED):
                self._state = State.INJECTING
                return Action.JOIN
            case (State.INJECTING, Event.INJECT_DONE):
                self._state = State.IDLE
                return Action.HIDE_OVERLAY
            case _:
                log.info("ignoring %s in state %s", event, self._state)
                return None
```

- [ ] **Step 4: Implement `flowd/session.py`** — the spec 4 data model

```python
"""Session and chunk data model (spec 4)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

ChunkState = Literal["PENDING", "INFLIGHT", "DONE", "FALLBACK", "MERGED"]


@dataclass
class Chunk:
    id: int
    raw: str
    polished: str | None = None
    state: ChunkState = "PENDING"
    version: int = 1
    t_committed: float = field(default_factory=time.monotonic)
    t_resolved: float | None = None

    @property
    def resolved(self) -> bool:
        return self.state in ("DONE", "FALLBACK", "MERGED")

    @property
    def text(self) -> str:
        """The best available text: polished when it passed, else raw."""
        return self.polished if self.polished is not None else self.raw


@dataclass
class Session:
    id: str
    mode: str = "default"
    app_id: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    chunks: list[Chunk] = field(default_factory=list)
    live_partial: str = ""
    pending_raw: list[str] = field(default_factory=list)

    def add_chunk(self, raw: str) -> Chunk:
        chunk = Chunk(id=len(self.chunks) + 1, raw=raw)
        self.chunks.append(chunk)
        return chunk

    def visible_chunks(self) -> list[Chunk]:
        """Chunks that contribute text; merged ones have been folded away."""
        return [c for c in self.chunks if c.state != "MERGED"]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_state.py -v`
Expected: 16 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/state.py flowd/session.py tests/test_state.py
git commit -m "phase1(state): session state machine with debounce, and data model"
```

---
### Task 8: `basic_clean` and the joiner

Phase 1 needs the deterministic text path: fillers, repeats, spacing, capitals, terminal punctuation. Vocabulary replacement (spec 7.5 step 3) is wired in but the table stays empty until phase 5.

**Files:**
- Create: `flowd/textclean.py`, `flowd/joiner.py`
- Test: `tests/test_textclean.py`, `tests/test_joiner.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `basic_clean(raw: str, replacements: Mapping[str, str] | None = None) -> str`; `join_chunks(texts: Sequence[str]) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_textclean.py`:

```python
import pytest

from flowd.textclean import basic_clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("so um i think we should ship it", "So i think we should ship it."),
        ("uh hello there", "Hello there."),
        ("the the meeting is monday", "The meeting is monday."),
        ("i went to, like, the store", "I went to the store."),
        ("i like pizza", "I like pizza."),  # 'like' as a verb survives
        ("already done.", "Already done."),
        ("is it ready?", "Is it ready?"),
        ("i think i am right", "I think I am right."),  # standalone I capitalised
        ("", ""),
        ("   ", ""),
        ("um uh er", ""),  # nothing but fillers
        ("hello    world", "Hello world."),
    ],
)
def test_basic_clean(raw: str, expected: str) -> None:
    assert basic_clean(raw) == expected


def test_applies_replacements() -> None:
    assert basic_clean("i use hyper land", {"hyper land": "Hyprland"}) == "I use Hyprland."


def test_replacement_is_case_insensitive_on_input() -> None:
    assert basic_clean("Hyper Land rocks", {"hyper land": "Hyprland"}) == "Hyprland rocks."


def test_is_fast_enough() -> None:
    """spec 7.5: deterministic and under 1 ms."""
    import time

    text = "so um i think we should uh probably ship it on monday " * 20
    start = time.perf_counter()
    for _ in range(100):
        basic_clean(text)
    assert (time.perf_counter() - start) / 100 < 0.001
```

`tests/test_joiner.py`:

```python
from flowd.joiner import join_chunks


def test_joins_with_single_spaces() -> None:
    assert join_chunks(["Hello there.", "How are you?"]) == "Hello there. How are you?"


def test_removes_space_before_punctuation() -> None:
    assert join_chunks(["Hello ,", "world ."]) == "Hello, world."


def test_capitalises_sentence_starts() -> None:
    assert join_chunks(["hello there. how are you?"]) == "Hello there. How are you?"


def test_adds_terminal_punctuation_when_missing() -> None:
    assert join_chunks(["hello there"]) == "Hello there."


def test_keeps_existing_terminal_punctuation() -> None:
    assert join_chunks(["Stop!"]) == "Stop!"


def test_empty_input_yields_empty_string() -> None:
    assert join_chunks([]) == ""
    assert join_chunks(["", "  "]) == ""


def test_collapses_internal_whitespace_and_newlines() -> None:
    assert join_chunks(["hello\n  world", "again"]) == "Hello world again."


def test_does_not_double_terminal_punctuation() -> None:
    assert join_chunks(["Done.", "Really?"]) == "Done. Really?"
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/test_textclean.py tests/test_joiner.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `flowd/textclean.py`**

```python
"""Deterministic fallback cleanup, under 1 ms (spec 7.5)."""

from __future__ import annotations

import re
from collections.abc import Mapping

#: Fillers removed wherever they stand alone as a word.
_ALWAYS_FILLERS = ("um", "uh", "er", "ah", "hmm", "mm", "erm")
#: Removed only when set off by commas or sentence edges, so "I like pizza" survives.
_HEDGED_FILLERS = ("like", "you know", "sort of", "kind of", "i mean")

_FILLER_RE = re.compile(
    r"\b(?:" + "|".join(_ALWAYS_FILLERS) + r")\b[,]?\s*", re.IGNORECASE
)
_HEDGED_RE = re.compile(
    r"(?:(?<=,)|(?<=^))\s*(?:" + "|".join(_HEDGED_FILLERS) + r")\s*,",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_MULTISPACE_RE = re.compile(r"\s+")
_STANDALONE_I_RE = re.compile(r"\bi\b")


def basic_clean(raw: str, replacements: Mapping[str, str] | None = None) -> str:
    """Regex-clean dictated text. Used whenever the LLM is unavailable or rejected."""
    text = raw.strip()
    if not text:
        return ""

    text = _HEDGED_RE.sub(" ", text)
    text = _FILLER_RE.sub("", text)
    text = _REPEAT_RE.sub(r"\1", text)

    for source, target in (replacements or {}).items():
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)

    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _MULTISPACE_RE.sub(" ", text).strip(" ,")
    if not text:
        return ""

    text = _STANDALONE_I_RE.sub("I", text)
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text
```

- [ ] **Step 4: Implement `flowd/joiner.py`**

```python
"""Join resolved chunks into the final text with code, never the LLM (spec 6.5)."""

from __future__ import annotations

import re
from collections.abc import Sequence

_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_MULTISPACE_RE = re.compile(r"\s+")
#: Start of a sentence: string start, or terminal punctuation plus whitespace.
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+)([a-z])")


def join_chunks(texts: Sequence[str]) -> str:
    joined = " ".join(t.strip() for t in texts if t and t.strip())
    if not joined:
        return ""
    joined = _MULTISPACE_RE.sub(" ", joined)
    joined = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", joined).strip()
    joined = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), joined)
    if joined[-1] not in ".!?":
        joined += "."
    return joined
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_textclean.py tests/test_joiner.py -v`
Expected: 22 passed. If a parametrised filler case fails, fix the regex — never weaken the test.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/textclean.py flowd/joiner.py tests/test_textclean.py tests/test_joiner.py
git commit -m "phase1(textclean): basic_clean and deterministic joiner"
```

---

### Task 9: Audio capture and ring buffer

The PortAudio callback copies frames and does nothing else (spec 4).

**Files:**
- Create: `flowd/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `Audio` config from Task 4.
- Produces: `RingBuffer(capacity_frames: int)` with `write(frames: np.ndarray) -> None`, `read_available() -> np.ndarray`, `pending_seconds(sample_rate: int) -> float`, `clear() -> None`; `AudioCapture(cfg, on_status=None)` with `start()`, `stop()`, `read()`, and `preroll()`. Also `load_wav(path: Path, sample_rate: int) -> np.ndarray` for `--replay`.

- [ ] **Step 1: Write the failing test**

`tests/test_audio.py`:

```python
import numpy as np

from flowd.audio import RingBuffer


def test_write_then_read_returns_same_frames() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(rb.read_available(), [1.0, 2.0, 3.0])


def test_read_drains_the_buffer() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(3, dtype=np.float32))
    rb.read_available()
    assert rb.read_available().size == 0


def test_wraps_and_keeps_newest_when_overrun() -> None:
    """Overrun drops the oldest audio, never blocks the callback."""
    rb = RingBuffer(capacity_frames=4)
    rb.write(np.array([1, 2, 3, 4, 5, 6], dtype=np.float32))
    out = rb.read_available()
    assert out.size == 4
    assert np.allclose(out, [3, 4, 5, 6])


def test_pending_seconds_reflects_sample_rate() -> None:
    rb = RingBuffer(capacity_frames=32000)
    rb.write(np.zeros(16000, dtype=np.float32))
    assert rb.pending_seconds(16000) == 1.0


def test_clear_empties_buffer() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(5, dtype=np.float32))
    rb.clear()
    assert rb.read_available().size == 0


def test_preserves_float32_dtype() -> None:
    rb = RingBuffer(capacity_frames=10)
    rb.write(np.ones(3, dtype=np.float32))
    assert rb.read_available().dtype == np.float32
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_audio.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.audio'`

- [ ] **Step 3: Implement `flowd/audio.py`**

```python
"""Microphone capture: 16 kHz mono float32, 100 ms blocks (spec 5.1)."""

from __future__ import annotations

import logging
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from flowd.config import Audio

log = logging.getLogger(__name__)


class RingBuffer:
    """Fixed-capacity float32 ring buffer.

    The audio callback only writes; the STT worker only reads. A lock guards the
    indices, held for a bounded copy so the callback never waits on real work
    (spec 4). On overrun the oldest audio is dropped, which is logged by the
    caller — the callback must never block the device.
    """

    def __init__(self, capacity_frames: int) -> None:
        self._buf = np.zeros(capacity_frames, dtype=np.float32)
        self._capacity = capacity_frames
        self._write = 0
        self._available = 0
        self._lock = threading.Lock()
        self.overruns = 0

    def write(self, frames: np.ndarray) -> None:
        data = np.asarray(frames, dtype=np.float32).reshape(-1)
        if data.size >= self._capacity:
            data = data[-self._capacity :]
        with self._lock:
            end = self._write + data.size
            if end <= self._capacity:
                self._buf[self._write : end] = data
            else:
                split = self._capacity - self._write
                self._buf[self._write :] = data[:split]
                self._buf[: end - self._capacity] = data[split:]
            self._write = end % self._capacity
            total = self._available + data.size
            if total > self._capacity:
                self.overruns += 1
                total = self._capacity
            self._available = total

    def read_available(self) -> np.ndarray:
        with self._lock:
            count = self._available
            if count == 0:
                return np.empty(0, dtype=np.float32)
            start = (self._write - count) % self._capacity
            if start + count <= self._capacity:
                out = self._buf[start : start + count].copy()
            else:
                split = self._capacity - start
                out = np.concatenate((self._buf[start:], self._buf[: count - split]))
            self._available = 0
            return out

    def pending_seconds(self, sample_rate: int) -> float:
        with self._lock:
            return self._available / float(sample_rate)

    def clear(self) -> None:
        with self._lock:
            self._available = 0


class AudioCapture:
    """Opens the mic on start and closes it on stop, so the indicator is off when idle."""

    def __init__(self, cfg: Audio, on_status: Callable[[str], None] | None = None) -> None:
        self._cfg = cfg
        self._on_status = on_status
        self._stream: Any = None
        capacity = cfg.sample_rate * 30  # 30 s headroom; overrun is logged, never fatal
        self._ring = RingBuffer(capacity)
        self._preroll = RingBuffer(max(1, cfg.sample_rate * cfg.preroll_ms // 1000))

    @property
    def blocksize(self) -> int:
        return self._cfg.sample_rate * self._cfg.block_ms // 1000

    def _callback(self, indata: np.ndarray, _frames: int, _time: Any, status: Any) -> None:
        """PortAudio thread: copy only (spec 4)."""
        if status and self._on_status is not None:
            self._on_status(str(status))
        self._ring.write(indata[:, 0])

    def start(self) -> None:
        import sounddevice as sd

        device = None if self._cfg.device == "default" else self._cfg.device
        self._ring.clear()
        self._stream = sd.InputStream(
            samplerate=self._cfg.sample_rate,
            blocksize=self.blocksize,
            device=device,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        log.info("mic open: %d Hz, %d ms blocks", self._cfg.sample_rate, self._cfg.block_ms)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("mic closed")

    def read(self) -> np.ndarray:
        return self._ring.read_available()

    def pending_seconds(self) -> float:
        return self._ring.pending_seconds(self._cfg.sample_rate)

    @property
    def overruns(self) -> int:
        return self._ring.overruns


def load_wav(path: Path, sample_rate: int) -> np.ndarray:
    """Load a mono 16-bit WAV for --replay. Rejects mismatched rates loudly."""
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != sample_rate:
            raise ValueError(
                f"{path}: {handle.getframerate()} Hz, expected {sample_rate} Hz "
                f"(convert with: ffmpeg -i in.wav -ar {sample_rate} -ac 1 out.wav)"
            )
        if handle.getnchannels() != 1:
            raise ValueError(f"{path}: {handle.getnchannels()} channels, expected mono")
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_audio.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/audio.py tests/test_audio.py
git commit -m "phase1(audio): ring buffer and PortAudio capture"
```

---

### Task 10: STT wrapper (non-streaming, phase 1)

Phase 1 transcribes a finished utterance. Streaming arrives in Task 16. The interface is the streaming one from the start so Task 16 changes the implementation only.

**Files:**
- Create: `flowd/stt.py`
- Test: `tests/test_stt.py`

**Interfaces:**
- Consumes: ADR 0001's findings, `Stt` config.
- Produces: `Partial(text: str)` and `Committed(text: str)` frozen dataclasses; `Event = Partial | Committed`; protocol `SttEngine` with `feed(pcm: np.ndarray) -> list[Event]` and `finalize() -> list[Event]`; `BatchSttEngine` (phase 1, buffers then transcribes on `finalize`); `FakeSttEngine` for tests; `load_engine(cfg: Stt, model_dir: Path) -> SttEngine`. **Task 17 extends this signature** to `load_engine(cfg, model_dir, vad_cfg: Vad | None = None, block_ms: int = 100)`, returning the batch engine when `vad_cfg` is None and the streaming engine otherwise.

- [ ] **Step 1: Write the failing test**

`tests/test_stt.py`:

```python
import numpy as np

from flowd.stt import BatchSttEngine, Committed, FakeSttEngine, Partial


def test_fake_engine_emits_scripted_events() -> None:
    engine = FakeSttEngine([[Partial("hello")], [Committed("hello there")]])
    assert engine.feed(np.zeros(160, dtype=np.float32)) == [Partial("hello")]
    assert engine.feed(np.zeros(160, dtype=np.float32)) == [Committed("hello there")]
    assert engine.feed(np.zeros(160, dtype=np.float32)) == []


def test_batch_engine_buffers_until_finalize() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: f"{pcm.size} frames")
    assert engine.feed(np.zeros(100, dtype=np.float32)) == []
    assert engine.feed(np.zeros(60, dtype=np.float32)) == []
    assert engine.finalize() == [Committed("160 frames")]


def test_batch_engine_finalize_with_no_audio_emits_nothing() -> None:
    """A hotkey press with no speech must not produce a bogus commit."""
    engine = BatchSttEngine(transcribe=lambda pcm: "should not be called")
    assert engine.finalize() == []


def test_batch_engine_ignores_empty_transcription() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: "   ")
    engine.feed(np.zeros(100, dtype=np.float32))
    assert engine.finalize() == []


def test_batch_engine_resets_after_finalize() -> None:
    engine = BatchSttEngine(transcribe=lambda pcm: f"{pcm.size}")
    engine.feed(np.zeros(100, dtype=np.float32))
    engine.finalize()
    engine.feed(np.zeros(50, dtype=np.float32))
    assert engine.finalize() == [Committed("50")]


def test_events_are_comparable_and_frozen() -> None:
    assert Partial("a") == Partial("a")
    assert Partial("a") != Committed("a")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_stt.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.stt'`

- [ ] **Step 3: Implement `flowd/stt.py`**

The `load_engine` body uses the exact API recorded in ADR 0001; the call below is the shape to adapt, not a guess to ship unverified.

```python
"""Speech-to-text behind a streaming-shaped interface (spec 5.3)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias

import numpy as np

from flowd.config import Stt

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Partial:
    """A still-changing hypothesis. Never leaves the overlay (spec 1)."""

    text: str


@dataclass(frozen=True, slots=True)
class Committed:
    """Text the engine will no longer revise."""

    text: str


Event: TypeAlias = Partial | Committed


class SttEngine(Protocol):
    def feed(self, pcm: np.ndarray) -> list[Event]:
        """Accept audio and return any events it produced."""

    def finalize(self) -> list[Event]:
        """Flush at end of session, committing whatever remains."""


class FakeSttEngine:
    """Scripted engine for deterministic tests; no model needed."""

    def __init__(self, script: Sequence[list[Event]]) -> None:
        self._script = list(script)
        self._index = 0

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if self._index >= len(self._script):
            return []
        events = self._script[self._index]
        self._index += 1
        return list(events)

    def finalize(self) -> list[Event]:
        remaining: list[Event] = []
        while self._index < len(self._script):
            remaining.extend(self._script[self._index])
            self._index += 1
        return remaining


class BatchSttEngine:
    """Phase 1: buffer the utterance, transcribe once at finalize.

    Emits no partials, so phase 1 has no live preview. Task 16 replaces this
    with the streaming engine behind the same interface.
    """

    def __init__(self, transcribe: Callable[[np.ndarray], str]) -> None:
        self._transcribe = transcribe
        self._buffer: list[np.ndarray] = []

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if pcm.size:
            self._buffer.append(np.asarray(pcm, dtype=np.float32))
        return []

    def finalize(self) -> list[Event]:
        if not self._buffer:
            return []
        audio = np.concatenate(self._buffer)
        self._buffer.clear()
        text = self._transcribe(audio).strip()
        return [Committed(text)] if text else []


def load_engine(cfg: Stt, model_dir: Path) -> SttEngine:
    """Load Moonshine once at daemon start; never reload per session (spec 5.3).

    The call below must match ADR 0001 exactly. If ADR 0001 records a native
    streaming API, Task 16 adds StreamingSttEngine here and this stays as the
    --replay and fallback path.
    """
    import moonshine_voice

    model = moonshine_voice.load_model(cfg.model)
    log.info("loaded STT model %s from %s", cfg.model, model_dir)

    def transcribe(pcm: np.ndarray) -> str:
        return str(model.transcribe(pcm))

    return BatchSttEngine(transcribe=transcribe)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_stt.py -v`
Expected: 6 passed.

- [ ] **Step 5: Verify `load_engine` against the real model**

```bash
uv run python -c "
from pathlib import Path
from flowd.config import Stt
from flowd.stt import load_engine
from flowd.audio import load_wav
engine = load_engine(Stt(), Path('.'))
engine.feed(load_wav(Path('eval/audio/sample.wav'), 16000))
print(engine.finalize())
"
```

Expected: one `Committed(...)` with plausible text. If the API differs from ADR 0001, fix the ADR and the code together.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/stt.py tests/test_stt.py
git commit -m "phase1(stt): streaming-shaped interface with batch engine and fake"
```

---

### Task 11: Injection backends

Owns **Review Focus 3**. Dictated text is attacker-influenced in the sense that it is arbitrary: it must reach subprocesses as argv or stdin, never inside a shell string. A single `shell=True` here would turn a spoken sentence into command execution.

**Files:**
- Create: `flowd/inject/__init__.py`, `flowd/inject/base.py`, `flowd/inject/clipboard.py`, `flowd/inject/typing_backends.py`
- Test: `tests/test_inject.py`

**Interfaces:**
- Consumes: `Inject` config.
- Produces: `InjectResult(ok: bool, backend: str | None, error: str | None)`; protocol `Backend` with `name: str`, `available() -> bool`, `inject(text: str, *, is_terminal: bool) -> None`; `ClipboardBackend`, `WtypeBackend`, `YdotoolBackend`, `XdotoolBackend`; `inject_text(text, cfg, backends=None, is_terminal=False) -> InjectResult` trying `cfg.order` in turn.

- [ ] **Step 1: Write the failing test**

`tests/test_inject.py`:

```python
from typing import Any

import pytest

from flowd.config import Inject
from flowd.inject import InjectResult, inject_text
from flowd.inject.clipboard import ClipboardBackend
from flowd.inject.typing_backends import WtypeBackend


class Recorder:
    """Captures subprocess invocations instead of running them."""

    def __init__(self, *, mime: str = "text/plain", fail: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.stdins: list[bytes | None] = []
        self._mime = mime
        self._fail = fail or set()

    def run(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append(list(argv))
        self.stdins.append(kwargs.get("input"))
        if argv[0] in self._fail:
            raise FileNotFoundError(argv[0])
        stdout = self._mime.encode() if "--list-types" in argv else b"previous clipboard"

        class Completed:
            returncode = 0

            def __init__(self, out: bytes) -> None:
                self.stdout = out

        return Completed(stdout)


DANGEROUS = "text; rm -rf ~ && echo $(whoami) `id` | tee /tmp/x\nsecond line"


def test_clipboard_never_uses_a_shell() -> None:
    """Dictated text must never be interpolated into a shell command."""
    rec = Recorder()
    ClipboardBackend(runner=rec.run, sleep=lambda _s: None).inject(DANGEROUS, is_terminal=False)
    for argv in rec.calls:
        assert isinstance(argv, list), "argv must be a list, never a shell string"
        assert DANGEROUS not in " ".join(argv), "text must go via stdin, not argv"


def test_clipboard_passes_text_on_stdin() -> None:
    rec = Recorder()
    ClipboardBackend(runner=rec.run, sleep=lambda _s: None).inject(DANGEROUS, is_terminal=False)
    assert DANGEROUS.encode() in [s for s in rec.stdins if s is not None]


def test_typing_backend_passes_text_as_single_argv_element() -> None:
    rec = Recorder()
    WtypeBackend(runner=rec.run).inject("a; rm -rf ~", is_terminal=False)
    assert rec.calls[0][0] == "wtype"
    assert "a; rm -rf ~" in rec.calls[0]


def test_clipboard_restores_previous_text() -> None:
    rec = Recorder()
    ClipboardBackend(runner=rec.run, sleep=lambda _s: None).inject("new", is_terminal=False)
    copies = [c for c in rec.calls if c[0] == "wl-copy"]
    assert len(copies) == 2, "must set the text, then restore the snapshot"
    assert rec.stdins[rec.calls.index(copies[1])] == b"previous clipboard"


def test_clipboard_refuses_when_clipboard_holds_an_image() -> None:
    """spec 9.4: never destroy non-text clipboard contents."""
    rec = Recorder(mime="image/png")
    backend = ClipboardBackend(runner=rec.run, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="non-text"):
        backend.inject("hello", is_terminal=False)
    assert not any(c[0] == "wl-copy" for c in rec.calls)


def test_terminal_uses_ctrl_shift_v() -> None:
    rec = Recorder()
    ClipboardBackend(runner=rec.run, sleep=lambda _s: None).inject("hi", is_terminal=True)
    keys = [c for c in rec.calls if c[0] in ("wtype", "xdotool")]
    assert any("shift" in " ".join(c).lower() for c in keys)


def test_falls_through_to_next_backend_on_failure() -> None:
    class Failing:
        name = "clipboard"

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise RuntimeError("no clipboard tool")

    class Working:
        name = "wtype"
        used = False

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            type(self).used = True

    result = inject_text("hi", Inject(order=("clipboard", "wtype")), backends=[Failing(), Working()])
    assert result == InjectResult(ok=True, backend="wtype", error=None)
    assert Working.used


def test_reports_failure_when_every_backend_fails() -> None:
    class Failing:
        name = "clipboard"

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise RuntimeError("nope")

    result = inject_text("hi", Inject(order=("clipboard",)), backends=[Failing()])
    assert result.ok is False
    assert result.error is not None and "nope" in result.error


def test_unavailable_backend_is_skipped() -> None:
    class Absent:
        name = "clipboard"

        def available(self) -> bool:
            return False

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise AssertionError("must not be called")

    assert inject_text("hi", Inject(order=("clipboard",)), backends=[Absent()]).ok is False


def test_long_text_is_chunked_for_typing_backends() -> None:
    rec = Recorder()
    WtypeBackend(runner=rec.run).inject("x" * 450, is_terminal=False)
    assert len(rec.calls) == 3  # 200-char chunks (spec 5.7)


def test_empty_text_injects_nothing() -> None:
    rec = Recorder()
    result = inject_text("", Inject(), backends=[ClipboardBackend(runner=rec.run)])
    assert result.ok is True
    assert rec.calls == []
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_inject.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.inject'`

- [ ] **Step 3: Implement `flowd/inject/base.py`**

```python
"""Injection backend protocol and shared subprocess helpers (spec 5.7)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

#: Typing backends are given at most this many characters per invocation.
TYPE_CHUNK_CHARS = 200

Runner = Callable[..., Any]


def run(argv: Sequence[str], *, input: bytes | None = None, timeout: float = 5.0) -> Any:
    """Run a command with an argv list.

    Never uses a shell: dictated text is arbitrary, and `shell=True` would make
    a spoken sentence executable.
    """
    return subprocess.run(  # noqa: S603 - argv list, shell=False by construction
        list(argv),
        input=input,
        capture_output=True,
        timeout=timeout,
        check=True,
    )


@dataclass(frozen=True, slots=True)
class InjectResult:
    ok: bool
    backend: str | None = None
    error: str | None = None


@runtime_checkable
class Backend(Protocol):
    name: str

    def available(self) -> bool:
        """True when this backend's tools exist and its session type matches."""

    def inject(self, text: str, *, is_terminal: bool) -> None:
        """Deliver text to the focused window, or raise on failure."""


def have(tool: str) -> bool:
    return shutil.which(tool) is not None
```

- [ ] **Step 4: Implement `flowd/inject/clipboard.py`**

```python
"""Clipboard injection with snapshot and restore (spec 5.7)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from flowd.inject.base import Runner, have, run

log = logging.getLogger(__name__)

#: MIME types we consider safe to overwrite and restore.
_TEXT_MIME_PREFIXES = ("text/", "TEXT", "STRING", "UTF8_STRING")


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


class ClipboardBackend:
    name = "clipboard"

    def __init__(
        self,
        runner: Runner = run,
        sleep: Callable[[float], None] = time.sleep,
        restore_delay_ms: int = 150,
    ) -> None:
        self._run = runner
        self._sleep = sleep
        self._restore_delay_s = restore_delay_ms / 1000.0

    def available(self) -> bool:
        return have("wl-copy") or have("xclip")

    def _tools(self) -> tuple[list[str], list[str], list[str]]:
        """Return (list-types, paste, copy) argv prefixes for this session type."""
        if _is_wayland():
            return (["wl-paste", "--list-types"], ["wl-paste", "--no-newline"], ["wl-copy"])
        return (
            ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xclip", "-selection", "clipboard", "-i"],
        )

    def _send_paste(self, is_terminal: bool) -> None:
        keys = "ctrl+shift+v" if is_terminal else "ctrl+v"
        if _is_wayland():
            parts = keys.split("+")
            argv = ["wtype"]
            for mod in parts[:-1]:
                argv += ["-M", mod]
            argv += ["-k", parts[-1]]
            for mod in reversed(parts[:-1]):
                argv += ["-m", mod]
            self._run(argv)
        else:
            self._run(["xdotool", "key", "--clearmodifiers", keys])

    def inject(self, text: str, *, is_terminal: bool) -> None:
        list_types, paste, copy = self._tools()

        types = ""
        try:
            types = self._run(list_types).stdout.decode("utf-8", "replace")
        except Exception as exc:  # an empty clipboard is not an error
            log.debug("could not list clipboard types: %s", exc)

        offered = [t.strip() for t in types.splitlines() if t.strip()]
        if offered and not all(t.startswith(_TEXT_MIME_PREFIXES) for t in offered):
            # spec 9.4: never destroy an image or other non-text clipboard payload.
            raise RuntimeError(f"clipboard holds non-text data ({', '.join(offered)})")

        saved: bytes | None = None
        if offered:
            try:
                saved = self._run(paste).stdout
            except Exception as exc:
                log.debug("could not snapshot clipboard: %s", exc)

        self._run(copy, input=text.encode("utf-8"))
        self._send_paste(is_terminal)
        self._sleep(self._restore_delay_s)

        if saved is not None:
            try:
                self._run(copy, input=saved)
            except Exception as exc:
                log.warning("could not restore clipboard: %s", exc)
```

- [ ] **Step 5: Implement `flowd/inject/typing_backends.py`**

```python
"""Typing backends: wtype, ydotool, xdotool (spec 5.7)."""

from __future__ import annotations

import os

from flowd.inject.base import TYPE_CHUNK_CHARS, Runner, have, run


def _chunks(text: str, size: int = TYPE_CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or []


class _TypingBackend:
    name = "typing"
    tool = ""

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def available(self) -> bool:
        return have(self.tool)

    def _argv(self, chunk: str) -> list[str]:
        raise NotImplementedError

    def inject(self, text: str, *, is_terminal: bool) -> None:
        # is_terminal is irrelevant: typing backends send characters, not a paste key.
        for chunk in _chunks(text):
            self._run(self._argv(chunk))


class WtypeBackend(_TypingBackend):
    name = "wtype"
    tool = "wtype"

    def available(self) -> bool:
        return have(self.tool) and bool(os.environ.get("WAYLAND_DISPLAY"))

    def _argv(self, chunk: str) -> list[str]:
        return ["wtype", "--", chunk]


class YdotoolBackend(_TypingBackend):
    name = "ydotool"
    tool = "ydotool"

    def _argv(self, chunk: str) -> list[str]:
        return ["ydotool", "type", "--", chunk]


class XdotoolBackend(_TypingBackend):
    name = "xdotool"
    tool = "xdotool"

    def available(self) -> bool:
        return have(self.tool) and bool(os.environ.get("DISPLAY"))

    def _argv(self, chunk: str) -> list[str]:
        return ["xdotool", "type", "--clearmodifiers", "--", chunk]
```

- [ ] **Step 6: Implement `flowd/inject/__init__.py`**

```python
"""Ordered injection with fallthrough (spec 5.7)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from flowd.config import Inject
from flowd.inject.base import Backend, InjectResult
from flowd.inject.clipboard import ClipboardBackend
from flowd.inject.typing_backends import WtypeBackend, XdotoolBackend, YdotoolBackend

log = logging.getLogger(__name__)

__all__ = [
    "Backend",
    "ClipboardBackend",
    "InjectResult",
    "WtypeBackend",
    "XdotoolBackend",
    "YdotoolBackend",
    "inject_text",
]


def default_backends(cfg: Inject) -> list[Backend]:
    return [
        ClipboardBackend(restore_delay_ms=cfg.restore_delay_ms),
        WtypeBackend(),
        YdotoolBackend(),
        XdotoolBackend(),
    ]


def inject_text(
    text: str,
    cfg: Inject,
    backends: Sequence[Backend] | None = None,
    *,
    is_terminal: bool = False,
) -> InjectResult:
    """Try each backend in cfg.order until one succeeds."""
    if not text:
        return InjectResult(ok=True)

    pool = {b.name: b for b in (backends if backends is not None else default_backends(cfg))}
    errors: list[str] = []
    for name in cfg.order:
        backend = pool.get(name)
        if backend is None:
            continue
        if not backend.available():
            log.debug("injector %s unavailable, skipping", name)
            errors.append(f"{name}: unavailable")
            continue
        try:
            backend.inject(text, is_terminal=is_terminal)
        except Exception as exc:
            log.warning("injector %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
            continue
        return InjectResult(ok=True, backend=name)
    return InjectResult(ok=False, error="; ".join(errors) or "no backend configured")
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_inject.py -v`
Expected: 11 passed.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/inject tests/test_inject.py
git commit -m "phase1(inject): clipboard and typing backends with argv-only subprocesses"
```

---
### Task 12: `flowctl` client

Must finish in under 50 ms (spec 5.9), so it is **stdlib-only and imports nothing from `flowd`**. Importing the package would pull in `numpy` and `onnxruntime` and blow the budget by an order of magnitude. The ~15 duplicated socket lines are the price of that budget, and the file says so.

**Files:**
- Create: `flowctl`
- Test: `tests/test_flowctl.py`

**Interfaces:**
- Consumes: the socket protocol from Task 6 (by wire format, not by import).
- Produces: a `flowctl` executable.

- [ ] **Step 1: Write the failing test**

`tests/test_flowctl.py`:

```python
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from flowd.control import serve

FLOWCTL = Path(__file__).resolve().parents[1] / "flowctl"


async def _handler(request: dict[str, Any]) -> dict[str, Any]:
    if request["cmd"] == "last":
        return {"ok": True, "text": "hello world"}
    return {"ok": True, "state": "idle"}


def _run(args: list[str], sock: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FLOWCTL), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env={"FLOWD_SOCKET": str(sock), "PATH": "/usr/bin:/bin"},
    )


async def test_toggle_prints_reply(tmp_path: Path) -> None:
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        result = await asyncio.to_thread(_run, ["toggle"], sock)
        assert result.returncode == 0
        assert "idle" in result.stdout
    finally:
        server.close()
        await server.wait_closed()


async def test_last_prints_bare_text(tmp_path: Path) -> None:
    """`flowctl last` is meant for piping, so it prints text with no JSON."""
    sock = tmp_path / "flowd.sock"
    server = await serve(sock, _handler)
    try:
        result = await asyncio.to_thread(_run, ["last"], sock)
        assert result.stdout.strip() == "hello world"
    finally:
        server.close()
        await server.wait_closed()


def test_no_daemon_exits_nonzero_with_message(tmp_path: Path) -> None:
    result = _run(["status"], tmp_path / "absent.sock")
    assert result.returncode != 0
    assert "not running" in result.stderr.lower()


def test_unknown_command_exits_nonzero(tmp_path: Path) -> None:
    result = _run(["explode"], tmp_path / "absent.sock")
    assert result.returncode != 0
    assert "usage" in (result.stderr + result.stdout).lower()


def test_imports_nothing_heavy() -> None:
    """The 50 ms budget (spec 5.9) rules out numpy and onnxruntime."""
    source = FLOWCTL.read_text()
    for banned in ("import numpy", "import onnxruntime", "from flowd", "import flowd"):
        assert banned not in source, f"flowctl must not {banned}"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_flowctl.py -v`
Expected: FAIL — `flowctl` does not exist.

- [ ] **Step 3: Implement `flowctl`**

```python
#!/usr/bin/env python3
"""flowd control client.

Deliberately stdlib-only, importing nothing from the flowd package: it runs on
every hotkey press and must finish in under 50 ms (spec 5.9). Importing flowd
would load numpy and onnxruntime and blow that budget, so the few lines of
socket code below are duplicated from flowd/control.py on purpose.
"""

from __future__ import annotations

import json
import os
import socket
import sys

COMMANDS = ("start", "stop", "toggle", "cancel", "status", "last", "stats", "reload")
USAGE = f"usage: flowctl {{{'|'.join(COMMANDS)}}} [--rewrite]"


def socket_path() -> str:
    override = os.environ.get("FLOWD_SOCKET")
    if override:
        return override
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/flowd-{os.getuid()}"
    return os.path.join(runtime, "flowd", "flowd.sock")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0 if len(argv) >= 2 else 2
    cmd = argv[1]
    if cmd not in COMMANDS:
        print(f"flowctl: unknown command {cmd!r}\n{USAGE}", file=sys.stderr)
        return 2

    request: dict[str, object] = {"cmd": cmd}
    if "--rewrite" in argv[2:]:
        request["rewrite"] = True

    path = socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(path)
            sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
            chunks = []
            while not (chunks and chunks[-1].endswith(b"\n")):
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
    except (FileNotFoundError, ConnectionRefusedError):
        print(f"flowctl: flowd is not running (no socket at {path})", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"flowctl: {exc}", file=sys.stderr)
        return 1

    try:
        reply = json.loads(b"".join(chunks).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("flowctl: malformed reply from daemon", file=sys.stderr)
        return 1

    # `last` and `stats` are meant for piping, so print their payload bare.
    if cmd == "last" and "text" in reply:
        print(reply["text"])
    elif cmd == "stats" and "stats" in reply:
        print(json.dumps(reply["stats"], indent=2))
    else:
        print(json.dumps(reply))
    return 0 if reply.get("ok", False) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run the tests and measure the latency**

```bash
chmod +x flowctl
uv run pytest tests/test_flowctl.py -v
python3 -c "
import subprocess, time
start = time.perf_counter()
subprocess.run(['./flowctl', '--help'], capture_output=True)
print(f'{(time.perf_counter()-start)*1000:.1f} ms')"
```

Expected: 5 passed; the timing under 50 ms. If it exceeds 50 ms, the cause is an import — remove it.

- [ ] **Step 5: Commit**

```bash
git add flowctl tests/test_flowctl.py
git commit -m "phase1(flowctl): stdlib-only control client under the 50 ms budget"
```

---

### Task 13: Daemon wiring, `--replay`, and the empty-recording case

Owns **Review Focus 4**. This is where phase 1 becomes usable.

**Files:**
- Create: `flowd/daemon.py`, `flowd/main.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: everything from Tasks 4–11.
- Produces: `Daemon(cfg, stt, capture, overlay=None, injector=inject_text, metrics_path: Path | None = None, clock=time.monotonic, config_file: Path | None = None)` with `async def handle(request: dict) -> dict`, `async def pump() -> None`, `async def run(socket_path: Path) -> None`, and the attributes `last_text: str`, `last_record: dict`, `cfg`, `config_file`. Passing `metrics_path=None` keeps metrics out of the real state directory during tests. `main(argv: list[str] | None = None) -> int` parses `--replay PATH`, `--fast`, `--log-level`.

- [ ] **Step 1: Write the failing test**

`tests/test_daemon.py`:

```python
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flowd.config import Config, Inject
from flowd.daemon import Daemon
from flowd.inject.base import InjectResult
from flowd.stt import Committed, FakeSttEngine, Partial


class FakeCapture:
    def __init__(self, blocks: list[np.ndarray] | None = None) -> None:
        self.blocks = blocks or [np.zeros(1600, dtype=np.float32)]
        self.started = False
        self.stopped = False
        self.overruns = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def read(self) -> np.ndarray:
        return self.blocks.pop(0) if self.blocks else np.empty(0, dtype=np.float32)

    def pending_seconds(self) -> float:
        return 0.0


class FakeOverlay:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def render(self, **zones: str) -> None:
        self.messages.append(dict(zones))

    def stop(self) -> None:
        pass


def daemon(stt: Any, capture: Any = None, injected: list[str] | None = None) -> Daemon:
    sink = injected if injected is not None else []

    def fake_inject(text: str, cfg: Inject, **kwargs: Any) -> InjectResult:
        sink.append(text)
        return InjectResult(ok=True, backend="fake")

    return Daemon(
        cfg=Config(),
        stt=stt,
        capture=capture or FakeCapture(),
        overlay=FakeOverlay(),
        injector=fake_inject,
        metrics_path=None,
    )


async def test_toggle_records_then_injects_cleaned_text() -> None:
    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("so um i think we should ship it")]]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == ["So i think we should ship it."]


async def test_cancel_injects_nothing() -> None:
    injected: list[str] = []
    d = daemon(FakeSttEngine([[Committed("discard me")]]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "cancel"})
    assert injected == []


async def test_silent_session_injects_nothing() -> None:
    """Review Focus 4: hotkey pressed and released with no speech."""
    injected: list[str] = []
    d = daemon(FakeSttEngine([]), injected=injected)
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == []


async def test_silent_session_reports_no_speech() -> None:
    d = daemon(FakeSttEngine([]))
    await d.handle({"cmd": "start"})
    reply = await d.handle({"cmd": "stop"})
    assert reply["ok"] is True
    assert reply.get("reason") == "no speech"


async def test_partials_never_reach_the_injector() -> None:
    """spec 1 non-goals: partial text must never be typed into the target app."""
    injected: list[str] = []
    d = daemon(
        FakeSttEngine([[Partial("half a sen")], [Committed("half a sentence")]]),
        injected=injected,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert injected == ["Half a sentence."]


async def test_start_while_finalizing_is_ignored() -> None:
    d = daemon(FakeSttEngine([[Committed("one")]]))
    await d.handle({"cmd": "start"})
    reply = await d.handle({"cmd": "start"})
    assert reply["ok"] is False


async def test_status_reports_state() -> None:
    d = daemon(FakeSttEngine([]))
    assert (await d.handle({"cmd": "status"}))["state"] == "idle"
    await d.handle({"cmd": "start"})
    assert (await d.handle({"cmd": "status"}))["state"] == "recording"


async def test_last_returns_previous_text_after_failed_injection() -> None:
    """spec 5.7: the text is never lost even if injection lands nowhere."""

    def failing_inject(text: str, cfg: Inject, **kwargs: Any) -> InjectResult:
        return InjectResult(ok=False, error="no backend")

    d = Daemon(
        cfg=Config(),
        stt=FakeSttEngine([[Committed("kept anyway")]]),
        capture=FakeCapture(),
        overlay=FakeOverlay(),
        injector=failing_inject,
        metrics_path=None,
    )
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert (await d.handle({"cmd": "last"}))["text"] == "Kept anyway."


async def test_reload_with_bad_config_keeps_old(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vad]\ncommit_silence_ms = -1\n")
    d = daemon(FakeSttEngine([]))
    d.config_file = path
    reply = await d.handle({"cmd": "reload"})
    assert reply["ok"] is False
    assert d.cfg.vad.commit_silence_ms == 350


async def test_mic_open_is_timed() -> None:
    d = daemon(FakeSttEngine([[Committed("hi there friend")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert "mic_open_ms" in d.last_record["stages"]
    assert "inject_ms" in d.last_record["stages"]


async def test_capture_is_released_on_cancel() -> None:
    capture = FakeCapture()
    d = daemon(FakeSttEngine([]), capture=capture)
    await d.handle({"cmd": "start"})
    await d.handle({"cmd": "cancel"})
    assert capture.stopped is True


async def test_overlay_hidden_after_session() -> None:
    d = daemon(FakeSttEngine([[Committed("some words here now")]]))
    await d.handle({"cmd": "start"})
    await d.pump()
    await d.handle({"cmd": "stop"})
    assert d.overlay.visible is False
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.daemon'`

- [ ] **Step 3: Implement `flowd/daemon.py`**

```python
"""The daemon: state machine driver and command handler (spec 4)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from flowd.config import Config, Inject, config_path, load_config, reload_config, state_dir
from flowd.inject import inject_text as real_inject
from flowd.inject.base import InjectResult
from flowd.joiner import join_chunks
from flowd.metrics import SessionMetrics, read_records, summarise, write_record
from flowd.session import Session
from flowd.state import Action, Event, Machine, State
from flowd.stt import Committed, Partial, SttEngine
from flowd.textclean import basic_clean

log = logging.getLogger(__name__)

Injector = Callable[..., InjectResult]


class Capture(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read(self) -> np.ndarray: ...
    def pending_seconds(self) -> float: ...


class OverlayLike(Protocol):
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def render(self, **zones: str) -> None: ...
    def stop(self) -> None: ...


class Daemon:
    """Owns the session lifecycle. Every side effect goes through an injected
    collaborator, so the whole class is testable with fakes and no hardware."""

    def __init__(
        self,
        cfg: Config,
        stt: SttEngine,
        capture: Capture,
        overlay: OverlayLike | None = None,
        injector: Injector = real_inject,
        metrics_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        config_file: Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.stt = stt
        self.capture = capture
        self.overlay = overlay
        self.inject = injector
        self.clock = clock
        self.config_file = config_file or config_path()
        self.metrics_path = metrics_path
        self.machine = Machine(debounce_ms=cfg.hotkey.debounce_ms, clock=clock)
        self.session: Session | None = None
        self.metrics: SessionMetrics | None = None
        self.last_text: str = ""
        self.last_record: dict[str, Any] = {}
        self._stop_reason: str | None = None

    # --- command handling -------------------------------------------------

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = str(request["cmd"])
        if cmd == "status":
            return {"ok": True, "state": str(self.machine.state)}
        if cmd == "last":
            return {"ok": True, "text": self.last_text}
        if cmd == "stats":
            path = self.metrics_path or (state_dir() / "metrics.jsonl")
            return {"ok": True, "stats": summarise(read_records(path))}
        if cmd == "reload":
            new_cfg, error = reload_config(self.cfg, self.config_file)
            if error is not None:
                return {"ok": False, "error": error}
            self.cfg = new_cfg
            return {"ok": True}

        event = {
            "start": Event.START,
            "stop": Event.STOP,
            "toggle": Event.TOGGLE,
            "cancel": Event.CANCEL,
        }.get(cmd)
        if event is None:
            return {"ok": False, "error": f"unsupported command: {cmd}"}

        action = self.machine.handle(event)
        if action is None:
            return {"ok": False, "error": f"ignored in state {self.machine.state}"}
        return await self._perform(action)

    async def _perform(self, action: Action) -> dict[str, Any]:
        match action:
            case Action.OPEN_MIC:
                return self._begin()
            case Action.FLUSH_AND_FINALIZE:
                return await self._finalize()
            case Action.DISCARD:
                self._discard()
                return {"ok": True, "cancelled": True}
            case Action.RELEASE_MIC:
                self._discard()
                return {"ok": False, "error": "fatal error; microphone released"}
            case _:
                return {"ok": True}

    # --- lifecycle --------------------------------------------------------

    def _begin(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        self.session = Session(id=session_id)
        self.metrics = SessionMetrics(
            session_id=session_id,
            mode=self.session.mode,
            clock=self.clock,
            log_transcripts=self.cfg.logging.log_transcripts,
        )
        self._stop_reason = None
        try:
            self.capture.start()
        except Exception as exc:
            log.error("could not open microphone: %s", exc)
            self.machine.handle(Event.FATAL)
            self._notify(f"flowd: microphone unavailable ({exc})")
            return {"ok": False, "error": str(exc)}
        self.metrics.mark("mic_open")
        if self.overlay is not None:
            self.overlay.show()
        return {"ok": True, "session": session_id}

    async def pump(self) -> None:
        """Move one block of audio through STT. Called by the run loop and tests."""
        if self.session is None or self.machine.state is not State.RECORDING:
            return
        pcm = self.capture.read()
        for event in self.stt.feed(pcm):
            self._on_stt_event(event)
        if self.capture.pending_seconds() > 2.0:
            log.warning("STT is behind real time: %.1f s queued", self.capture.pending_seconds())

    def _on_stt_event(self, event: Partial | Committed) -> None:
        assert self.session is not None and self.metrics is not None
        if isinstance(event, Partial):
            self.session.live_partial = event.text
            if not self.metrics.has("first_partial"):
                self.metrics.mark("first_partial")
        else:
            self.session.live_partial = ""
            if event.text.strip():
                self.session.add_chunk(event.text)
                self.metrics.count("chunks")
        self._render()

    def _render(self) -> None:
        if self.overlay is None or self.session is None:
            return
        # Phase 1 has no LLM: every chunk shows as pending until the final join.
        pending = " ".join(c.raw for c in self.session.visible_chunks())
        self.overlay.render(polished="", pending=pending, live=self.session.live_partial)

    async def _finalize(self) -> dict[str, Any]:
        assert self.session is not None and self.metrics is not None
        self.capture.stop()
        for event in self.stt.finalize():
            self._on_stt_event(event)
        self.metrics.mark("finalized")

        raw_parts = [c.raw for c in self.session.visible_chunks()]
        if not any(part.strip() for part in raw_parts):
            # spec 9.1: no speech at all means inject nothing.
            self._show_status("No speech")
            self._end_session(text="", reason="no speech")
            return {"ok": True, "reason": "no speech"}

        cleaned = [basic_clean(part) for part in raw_parts]
        final = join_chunks(cleaned)
        self.metrics.count("words", len(final.split()))
        self.metrics.text = final

        self.machine.handle(Event.CHUNKS_RESOLVED)
        result = await asyncio.to_thread(
            self.inject, final, self.cfg.inject, is_terminal=False
        )
        self.metrics.mark("inject")
        self.metrics.backend = result.backend
        if not result.ok:
            log.warning("injection failed: %s; text kept for `flowctl last`", result.error)
            self.metrics.error(f"inject: {result.error}")

        self.machine.handle(Event.INJECT_DONE)
        self._end_session(text=final, reason=None)
        return {"ok": True, "text": final, "backend": result.backend}

    def _discard(self) -> None:
        try:
            self.capture.stop()
        except Exception as exc:
            log.warning("error closing microphone: %s", exc)
        if self.overlay is not None:
            self.overlay.hide()
        self.session = None
        self.metrics = None

    def _end_session(self, text: str, reason: str | None) -> None:
        assert self.metrics is not None
        if text:
            self.last_text = text
        if reason:
            self.metrics.error(reason)
        self.last_record = self.metrics.to_record()
        path = self.metrics_path or (state_dir() / "metrics.jsonl")
        if self.metrics_path is not None or path.parent.exists():
            try:
                write_record(self.last_record, path)
            except OSError as exc:
                log.warning("could not write metrics: %s", exc)
        if self.overlay is not None:
            self.overlay.hide()
        self.session = None
        self.metrics = None

    # --- helpers ----------------------------------------------------------

    def _show_status(self, message: str) -> None:
        if self.overlay is not None:
            self.overlay.render(polished="", pending="", live=message)

    def _notify(self, message: str) -> None:
        """Desktop notification; failure to notify is never fatal."""
        import subprocess

        try:
            subprocess.run(["notify-send", "flowd", message], check=False, timeout=2)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("notify-send unavailable: %s", exc)

    async def run(self, socket_path: Path) -> None:
        from flowd.control import serve

        server = await serve(socket_path, self.handle)
        log.info("flowd listening on %s", socket_path)
        block_s = self.cfg.audio.block_ms / 1000.0
        try:
            while True:
                await self.pump()
                await self._check_max_duration()
                await asyncio.sleep(block_s if self.session is not None else 0.2)
        finally:
            server.close()
            await server.wait_closed()

    async def _check_max_duration(self) -> None:
        if self.session is None or self.machine.state is not State.RECORDING:
            return
        elapsed = self.clock() - self.session.started_at
        if elapsed >= self.cfg.audio.max_session_s:
            log.info("session hit max_session_s; finalizing")
            if self.machine.handle(Event.MAX_DURATION) is Action.FLUSH_AND_FINALIZE:
                await self._finalize()
```

- [ ] **Step 4: Implement `flowd/main.py`**

```python
"""Entry point: argument parsing, logging, model verification, run loop."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from flowd.audio import AudioCapture, load_wav
from flowd.config import Config, data_dir, load_config, runtime_dir, state_dir
from flowd.models import verify_models
from flowd.stt import load_engine


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,  # journald captures stdout (spec 10.3)
    )


def _verify_or_exit(cfg: Config) -> None:
    lock = Path(__file__).resolve().parent.parent / "models.lock"
    models = data_dir() / "models"
    if not lock.is_file():
        logging.warning("no models.lock; skipping verification")
        return
    problems = verify_models(lock, models)
    if problems:
        for problem in problems:
            logging.error("model verification: %s", problem)
        logging.error("refusing to start; run scripts/fetch_models.sh")
        raise SystemExit(2)


class _ReplayCapture:
    """Feeds a WAV through the real pipeline (spec 11.2)."""

    def __init__(self, pcm, block: int, realtime: bool) -> None:
        self._pcm = pcm
        self._block = block
        self._realtime = realtime
        self._pos = 0
        self._last = time.monotonic()

    def start(self) -> None:
        self._pos = 0

    def stop(self) -> None:
        pass

    def read(self):
        import numpy as np

        if self._pos >= len(self._pcm):
            return np.empty(0, dtype="float32")
        if self._realtime:
            # Pace playback so measured latencies mean something.
            due = self._last + self._block / 16000.0
            now = time.monotonic()
            if now < due:
                time.sleep(due - now)
            self._last = time.monotonic()
        chunk = self._pcm[self._pos : self._pos + self._block]
        self._pos += self._block
        return chunk

    def pending_seconds(self) -> float:
        return 0.0

    @property
    def exhausted(self) -> bool:
        return self._pos >= len(self._pcm)


async def _replay(cfg: Config, path: Path, fast: bool) -> int:
    from flowd.daemon import Daemon

    pcm = load_wav(path, cfg.audio.sample_rate)
    block = cfg.audio.sample_rate * cfg.audio.block_ms // 1000
    capture = _ReplayCapture(pcm, block, realtime=not fast)
    engine = load_engine(cfg.stt, data_dir() / "models")

    def no_inject(text, inject_cfg, **kwargs):
        from flowd.inject.base import InjectResult

        return InjectResult(ok=True, backend="replay")

    daemon = Daemon(cfg=cfg, stt=engine, capture=capture, injector=no_inject, metrics_path=None)
    await daemon.handle({"cmd": "start"})
    while not capture.exhausted:
        await daemon.pump()
    reply = await daemon.handle({"cmd": "stop"})
    print(f"TEXT: {reply.get('text', '')}")
    print(f"STAGES: {daemon.last_record.get('stages', {})}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flowd", description="Local dictation daemon")
    parser.add_argument("--replay", type=Path, help="feed a 16 kHz mono WAV through the pipeline")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="with --replay, run as fast as possible instead of real time",
    )
    parser.add_argument("--log-level", default=None, choices=["debug", "info", "warning", "error"])
    args = parser.parse_args(argv)

    cfg = load_config()
    _setup_logging(args.log_level or cfg.logging.level)
    _verify_or_exit(cfg)

    if args.replay is not None:
        return asyncio.run(_replay(cfg, args.replay, args.fast))

    from flowd.control import AlreadyRunning
    from flowd.daemon import Daemon

    engine = load_engine(cfg.stt, data_dir() / "models")
    capture = AudioCapture(cfg.audio)
    state_dir().mkdir(parents=True, exist_ok=True)
    daemon = Daemon(cfg=cfg, stt=engine, capture=capture)
    try:
        asyncio.run(daemon.run(runtime_dir() / "flowd.sock"))
    except AlreadyRunning as exc:
        print(f"flowd: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: 12 passed.

- [ ] **Step 6: Verify `--replay` end to end**

```bash
uv run flowd --replay eval/audio/sample.wav --fast
```

Expected: a `TEXT:` line with plausible text and a `STAGES:` line with timings.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/daemon.py flowd/main.py tests/test_daemon.py
git commit -m "phase1(daemon): state machine wiring, replay mode and no-speech handling"
```

---

### Task 14: Public-repo documentation, systemd unit, and the phase 1 report

**Files:**
- Create: `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/feature_request.md`, `.github/pull_request_template.md`, `systemd/flowd.service`, `docs/reports/phase-1.md`

**Interfaces:**
- Consumes: the working daemon from Task 13.
- Produces: documentation only.

- [ ] **Step 1: Write `README.md`**

Written for any user, not "the owner". Required sections:

1. **What it is** — one paragraph plus the core promise: fully local, no telemetry, no network at runtime.
2. **Status** — phases 0–2 complete; LLM cleanup is phase 3. Be honest about what does not exist yet.
3. **Requirements** — Arch packages with the **corrected name `llama-cpp`** (not `llama.cpp` from the AUR):
   ```bash
   sudo pacman -S --needed pipewire pipewire-pulse portaudio llama-cpp \
     wl-clipboard wtype ydotool xclip xdotool gtk4 gtk4-layer-shell python-gobject
   ```
   Note AVX2 as the baseline and that AVX-512 is not required.
4. **Install** — `uv venv && uv pip install -e .`, then `scripts/fetch_models.sh`.
5. **Run** — `systemctl --user enable --now flowd-llm flowd`, plus the
   `systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP`
   step and why it is needed.
6. **Hotkeys** — one working example per compositor:
   - Hyprland: `bind = SUPER, D, exec, flowctl toggle` and push-to-talk with
     `bindr` for the release edge.
   - Sway: `bindsym $mod+d exec flowctl toggle` and `bindsym --release`.
   - KDE: System Settings → Shortcuts → Custom.
   - GNOME: `gsettings` custom keybinding, with a note that the overlay is
     disabled on GNOME Wayland (spec 5.8) and why.
   - X11: `sxhkd` example.
7. **`ydotool` setup** — the uinput permission step, as commands **the user runs
   themselves**. flowd never does this (spec 13.2).
8. **Troubleshooting** — paste lands nowhere (`flowctl last`), no mic, overlay
   missing, `journalctl --user -u flowd -u flowd-llm`, model hash mismatch.
9. **Privacy** — what is stored, where, and that `log_transcripts` is off by
   default.
10. **License** — MIT, and the separate model licenses in `models.lock`.

- [ ] **Step 2: Write `CONTRIBUTING.md`**

Covers: `uv venv && uv pip install -e '.[dev]'`; run `uv run pytest`,
`uv run ruff check .`, `uv run mypy flowd` before pushing; the commit-message
convention `phase<N>(component): summary`; that `docs/spec.md` is authoritative
and changing a default or a model needs a decision record in
`docs/decisions/`; that tests must not need models or a microphone; and that
audio, transcripts and metrics must never be committed.

- [ ] **Step 3: Write `CODE_OF_CONDUCT.md`**

Contributor Covenant 2.1 verbatim, with a real contact address.

- [ ] **Step 4: Write the issue and PR templates**

`bug_report.md` asks for: compositor and session type, `flowd --version`,
output of `journalctl --user -u flowd -n 50`, whether the LLM was running, and
reproduction steps. It states explicitly: **do not paste transcript text you
would not want public.**

- [ ] **Step 5: Write `systemd/flowd.service`**

```ini
[Unit]
Description=flowd dictation daemon
Documentation=https://github.com/harshitsaini17/flowd
Wants=flowd-llm.service pipewire.service
After=flowd-llm.service pipewire.service graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/flowd/.venv/bin/flowd
Restart=on-failure
RestartSec=2
# The daemon needs the compositor's environment to inject text and show the
# overlay. Import it before starting:
#   systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP

[Install]
WantedBy=default.target
```

Document in the README that `ExecStart` must point at the user's actual venv.

- [ ] **Step 6: Run the full suite and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy flowd
git add README.md CONTRIBUTING.md CODE_OF_CONDUCT.md .github systemd/flowd.service
git commit -m "phase1(docs): README, contributing guide, issue templates and unit"
```

- [ ] **Step 7: Write `docs/reports/phase-1.md`**

Use the spec 14.1 template. Verify each phase 1 acceptance criterion by hand:
paste into a terminal, a browser text field and a code editor; confirm cancel
injects nothing; confirm `metrics.jsonl` has a line per session. Record real
numbers from `metrics.jsonl`. Mark anything unmet as unmet.

```bash
git add docs/reports/phase-1.md
git commit -m "phase1(report): handoff report with measured latencies"
```

---
## Phase 2 — Streaming and preview

### Task 15: VAD and silence tracking

Which engine runs here is decided by **ADR 0001 item 3**. If `moonshine-voice`
exposes usable voice-activity or segmentation, use it and ship no second model.
Otherwise use `silero_vad.onnx` through the `onnxruntime` already present, write
**ADR 0002**, and pin the ONNX file in `models.lock`. **No `torch` either way.**

**Files:**
- Create: `flowd/vad.py`
- Modify: `scripts/fetch_models.sh` (add the Silero download, only if ADR 0002 applies)
- Test: `tests/test_vad.py`

**Interfaces:**
- Consumes: `Vad` config from Task 4.
- Produces: `VadFrame(speech: bool, silence_ms: int)`; protocol `VadEngine` with `process(block: np.ndarray) -> VadFrame` and `reset() -> None`; `SilenceTracker(block_ms: int)` with `update(speech: bool) -> int`; `FakeVad(script: Sequence[bool])`; `SileroOnnxVad(model_path, threshold, block_ms)`; `load_vad(cfg, model_dir) -> VadEngine`.

- [ ] **Step 1: Write the failing test**

`tests/test_vad.py`:

```python
import numpy as np

from flowd.vad import FakeVad, SilenceTracker, VadFrame


def test_silence_tracker_counts_consecutive_silence() -> None:
    tracker = SilenceTracker(block_ms=100)
    assert tracker.update(speech=True) == 0
    assert tracker.update(speech=False) == 100
    assert tracker.update(speech=False) == 200
    assert tracker.update(speech=False) == 300


def test_silence_tracker_resets_on_speech() -> None:
    tracker = SilenceTracker(block_ms=100)
    tracker.update(speech=False)
    tracker.update(speech=False)
    assert tracker.update(speech=True) == 0
    assert tracker.update(speech=False) == 100


def test_silence_tracker_starts_at_zero() -> None:
    assert SilenceTracker(block_ms=100).silence_ms == 0


def test_silence_tracker_honours_block_size() -> None:
    tracker = SilenceTracker(block_ms=30)
    tracker.update(speech=False)
    assert tracker.update(speech=False) == 60


def test_fake_vad_reports_scripted_frames() -> None:
    vad = FakeVad([True, True, False], block_ms=100)
    block = np.zeros(1600, dtype=np.float32)
    assert vad.process(block) == VadFrame(speech=True, silence_ms=0)
    assert vad.process(block) == VadFrame(speech=True, silence_ms=0)
    assert vad.process(block) == VadFrame(speech=False, silence_ms=100)


def test_fake_vad_treats_exhausted_script_as_silence() -> None:
    vad = FakeVad([True], block_ms=100)
    block = np.zeros(1600, dtype=np.float32)
    vad.process(block)
    assert vad.process(block).speech is False


def test_reset_clears_silence_run() -> None:
    vad = FakeVad([False, False], block_ms=100)
    block = np.zeros(1600, dtype=np.float32)
    vad.process(block)
    vad.reset()
    assert vad.process(block).silence_ms == 100
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_vad.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.vad'`

- [ ] **Step 3: Implement `flowd/vad.py`**

```python
"""Voice activity detection: speech/silence per block (spec 5.2).

The engine choice is recorded in ADR 0001 (Moonshine's own segmentation, if it
has any) or ADR 0002 (Silero ONNX). Either way no PyTorch is involved: a VAD
that needs it is an escalation trigger (spec 13.3).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from flowd.config import Vad

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VadFrame:
    speech: bool
    silence_ms: int


class SilenceTracker:
    """Counts the current run of consecutive silent blocks in milliseconds."""

    def __init__(self, block_ms: int) -> None:
        self._block_ms = block_ms
        self.silence_ms = 0

    def update(self, speech: bool) -> int:
        self.silence_ms = 0 if speech else self.silence_ms + self._block_ms
        return self.silence_ms

    def reset(self) -> None:
        self.silence_ms = 0


class VadEngine(Protocol):
    def process(self, block: np.ndarray) -> VadFrame: ...
    def reset(self) -> None: ...


class FakeVad:
    """Scripted engine for deterministic tests; no model needed."""

    def __init__(self, script: Sequence[bool], block_ms: int = 100) -> None:
        self._script = list(script)
        self._index = 0
        self._tracker = SilenceTracker(block_ms)

    def process(self, block: np.ndarray) -> VadFrame:
        speech = self._script[self._index] if self._index < len(self._script) else False
        self._index += 1
        return VadFrame(speech=speech, silence_ms=self._tracker.update(speech))

    def reset(self) -> None:
        self._tracker.reset()


class SileroOnnxVad:
    """Silero VAD via onnxruntime — a few MB, no torch (spec 5.2).

    Silero expects 512-sample windows at 16 kHz. A 100 ms block is 1600 samples,
    so each block is scored as several windows and counted as speech when any
    window crosses the threshold; a 100 ms block containing a single word should
    not be discarded because most of it is quiet.
    """

    WINDOW = 512

    def __init__(self, model_path: Path, threshold: float, block_ms: int, sample_rate: int = 16000):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._threshold = threshold
        self._sample_rate = sample_rate
        self._tracker = SilenceTracker(block_ms)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._tail = np.empty(0, dtype=np.float32)

    def _score(self, window: np.ndarray) -> float:
        inputs: dict[str, Any] = {
            "input": window.reshape(1, -1).astype(np.float32),
            "state": self._state,
            "sr": np.array(self._sample_rate, dtype=np.int64),
        }
        outputs = self._session.run(None, inputs)
        self._state = outputs[1]
        return float(outputs[0].reshape(-1)[0])

    def process(self, block: np.ndarray) -> VadFrame:
        samples = np.concatenate((self._tail, np.asarray(block, dtype=np.float32).reshape(-1)))
        count = len(samples) // self.WINDOW
        self._tail = samples[count * self.WINDOW :]
        speech = False
        for i in range(count):
            window = samples[i * self.WINDOW : (i + 1) * self.WINDOW]
            if self._score(window) >= self._threshold:
                speech = True
        return VadFrame(speech=speech, silence_ms=self._tracker.update(speech))

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._tail = np.empty(0, dtype=np.float32)
        self._tracker.reset()


def load_vad(cfg: Vad, model_dir: Path, block_ms: int = 100) -> VadEngine:
    """Load the VAD engine chosen in ADR 0001/0002."""
    path = model_dir / "silero_vad.onnx"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run scripts/fetch_models.sh")
    return SileroOnnxVad(path, threshold=cfg.threshold, block_ms=block_ms)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_vad.py -v`
Expected: 7 passed.

- [ ] **Step 5: If ADR 0002 applies, add Silero to the fetch script and lock**

Append to `scripts/fetch_models.sh` before the lock is written:

```bash
echo "==> Fetching Silero VAD (MIT, ONNX, ~2 MB)"
SILERO_URL="https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
if [[ -f "$MODELS_DIR/silero_vad.onnx" ]]; then
  echo "    already present, skipping"
else
  curl -fL --progress-bar -o "$MODELS_DIR/silero_vad.onnx" "$SILERO_URL"
fi
```

Then `bash scripts/fetch_models.sh` to regenerate `models.lock`, and **review the
diff** before committing: a changed hash means the upstream file changed.

- [ ] **Step 6: Verify against real audio**

```bash
uv run python -c "
from pathlib import Path
from flowd.config import Vad, data_dir
from flowd.vad import load_vad
from flowd.audio import load_wav
vad = load_vad(Vad(), data_dir() / 'models')
pcm = load_wav(Path('eval/audio/sample.wav'), 16000)
frames = [vad.process(pcm[i:i+1600]) for i in range(0, len(pcm) - 1600, 1600)]
speech = sum(f.speech for f in frames)
print(f'{speech}/{len(frames)} blocks speech')
"
```

Expected: a clear majority of blocks are speech for a spoken-sentence WAV. If
every block reads speech or none do, the threshold or the input shape is wrong —
fix it before Task 17 depends on it.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/vad.py tests/test_vad.py scripts/fetch_models.sh models.lock
git commit -m "phase2(vad): silence tracking and Silero ONNX engine"
```

---

### Task 16: Committer — the stable-prefix rule

Pure logic, so every spec 5.4 rule is directly testable. A phase 2 acceptance criterion.

**Files:**
- Create: `flowd/committer.py`
- Test: `tests/test_committer.py`

**Interfaces:**
- Consumes: `Stt` and `Vad` config.
- Produces: `Committer(max_uncommitted_words=25, stability_window=3, keep_uncommitted=3, commit_silence_ms=350)` with `on_partial(text: str) -> str | None`, `on_silence(silence_ms: int) -> str | None`, `on_complete(text: str) -> str | None`, `finalize() -> str | None`, and properties `committed_text: str` / `uncommitted_text: str`. Each method returns newly committed text, or `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_committer.py`:

```python
from flowd.committer import Committer


def test_silence_commits_everything_uncommitted() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("hello there friend")
    assert c.on_silence(350) == "hello there friend"
    assert c.uncommitted_text == ""


def test_silence_below_threshold_commits_nothing() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("hello there")
    assert c.on_silence(200) is None
    assert c.uncommitted_text == "hello there"


def test_silence_with_nothing_uncommitted_returns_none() -> None:
    c = Committer(commit_silence_ms=350)
    assert c.on_silence(500) is None


def test_engine_completion_commits_the_line() -> None:
    c = Committer()
    assert c.on_complete("the whole line") == "the whole line"
    assert c.uncommitted_text == ""


def test_stable_prefix_commits_only_unchanged_words() -> None:
    """spec 5.4 rule 3: past the word cap, commit the prefix stable across 3 partials."""
    c = Committer(max_uncommitted_words=5, stability_window=3, keep_uncommitted=3)
    c.on_partial("one two three four five")
    c.on_partial("one two three four five six")
    committed = c.on_partial("one two three four five six seven")
    assert committed == "one two three four"
    assert c.uncommitted_text == "five six seven"


def test_stable_prefix_keeps_at_least_three_words_uncommitted() -> None:
    c = Committer(max_uncommitted_words=4, stability_window=3, keep_uncommitted=3)
    c.on_partial("alpha beta gamma delta epsilon")
    c.on_partial("alpha beta gamma delta epsilon")
    c.on_partial("alpha beta gamma delta epsilon")
    assert c.on_partial("alpha beta gamma delta epsilon") == "alpha beta"
    assert len(c.uncommitted_text.split()) == 3


def test_no_commit_below_the_word_cap() -> None:
    c = Committer(max_uncommitted_words=25)
    for _ in range(5):
        c.on_partial("just a few words here")
    assert c.uncommitted_text == "just a few words here"


def test_unstable_tail_is_not_committed() -> None:
    """A word that keeps changing must never be committed."""
    c = Committer(max_uncommitted_words=3, stability_window=3, keep_uncommitted=3)
    c.on_partial("one two three four")
    c.on_partial("one two three FOUR")
    committed = c.on_partial("one two three fore")
    assert committed is None or "four" not in committed.lower()


def test_revised_prefix_is_not_committed() -> None:
    """Moonshine may revise earlier words; a changed prefix is not stable."""
    c = Committer(max_uncommitted_words=3, stability_window=3, keep_uncommitted=1)
    c.on_partial("send it to john")
    c.on_partial("send it to sarah")
    committed = c.on_partial("send it to sarah")
    assert committed is None or "john" not in committed


def test_partials_after_commit_are_relative_to_committed_text() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("first part")
    c.on_silence(350)
    c.on_partial("first part second part")
    assert c.uncommitted_text == "second part"
    assert c.committed_text == "first part"


def test_finalize_commits_the_remainder() -> None:
    c = Committer()
    c.on_partial("trailing words")
    assert c.finalize() == "trailing words"
    assert c.finalize() is None


def test_finalize_with_nothing_pending_returns_none() -> None:
    assert Committer().finalize() is None


def test_empty_partial_is_harmless() -> None:
    c = Committer()
    assert c.on_partial("") is None
    assert c.on_partial("   ") is None
    assert c.uncommitted_text == ""


def test_committed_text_accumulates_across_commits() -> None:
    c = Committer(commit_silence_ms=350)
    c.on_partial("one")
    c.on_silence(350)
    c.on_partial("one two")
    c.on_silence(350)
    assert c.committed_text == "one two"


def test_reset_clears_all_state() -> None:
    c = Committer()
    c.on_partial("some words")
    c.reset()
    assert c.committed_text == ""
    assert c.uncommitted_text == ""
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_committer.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.committer'`

- [ ] **Step 3: Implement `flowd/committer.py`**

```python
"""Deciding when raw text stops changing (spec 5.4).

Moonshine revises its hypothesis as more audio arrives, so text is committed
only once it is stable — by an explicit engine signal, by a VAD pause, or by the
stable-prefix rule during continuous speech.
"""

from __future__ import annotations

import logging
from collections import deque

log = logging.getLogger(__name__)


class Committer:
    def __init__(
        self,
        max_uncommitted_words: int = 25,
        stability_window: int = 3,
        keep_uncommitted: int = 3,
        commit_silence_ms: int = 350,
    ) -> None:
        self._max_uncommitted = max_uncommitted_words
        self._keep = keep_uncommitted
        self._commit_silence_ms = commit_silence_ms
        self._committed: list[str] = []
        self._uncommitted: list[str] = []
        #: Recent uncommitted word lists, newest last, for the stability check.
        self._stability_window = stability_window
        self._history: deque[list[str]] = deque(maxlen=stability_window)

    @property
    def committed_text(self) -> str:
        return " ".join(self._committed)

    @property
    def uncommitted_text(self) -> str:
        return " ".join(self._uncommitted)

    def reset(self) -> None:
        self._committed.clear()
        self._uncommitted.clear()
        self._history.clear()

    def on_partial(self, text: str) -> str | None:
        """Accept a new hypothesis for the whole utterance.

        The engine reports the full utterance, so the already-committed prefix is
        stripped before the remainder is considered.
        """
        words = text.split()
        if not words:
            return None
        self._uncommitted = self._strip_committed(words)
        self._history.append(list(self._uncommitted))
        return self._maybe_commit_stable_prefix()

    def _strip_committed(self, words: list[str]) -> list[str]:
        """Drop the committed prefix, tolerating engine revisions of later words."""
        n = len(self._committed)
        if n == 0:
            return words
        if len(words) < n:
            # The engine shrank its hypothesis; keep nothing rather than guess.
            return []
        return words[n:]

    def _maybe_commit_stable_prefix(self) -> str | None:
        """spec 5.4 rule 3: past the cap, commit the prefix unchanged across the window."""
        if len(self._uncommitted) <= self._max_uncommitted:
            return None
        if len(self._history) < self._stability_window:
            return None

        stable = self._stable_prefix_length()
        # Always leave a tail uncommitted: the engine may still revise it.
        commit_count = min(stable, len(self._uncommitted) - self._keep)
        if commit_count <= 0:
            return None
        return self._commit(commit_count)

    def _stable_prefix_length(self) -> int:
        """How many leading words are identical across every remembered partial."""
        snapshots = list(self._history)
        shortest = min(len(s) for s in snapshots)
        length = 0
        while length < shortest and len({s[length] for s in snapshots}) == 1:
            length += 1
        return length

    def _commit(self, count: int) -> str:
        taken = self._uncommitted[:count]
        self._uncommitted = self._uncommitted[count:]
        self._committed.extend(taken)
        # History entries describe the old split, so they no longer apply.
        self._history.clear()
        text = " ".join(taken)
        log.debug("committed %d word(s) by stable prefix", count)
        return text

    def on_silence(self, silence_ms: int) -> str | None:
        """spec 5.4 rule 2: a VAD pause commits everything outstanding."""
        if silence_ms < self._commit_silence_ms or not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))

    def on_complete(self, text: str) -> str | None:
        """spec 5.4 rule 1: the engine says the line is done."""
        words = text.split()
        if words:
            self._uncommitted = self._strip_committed(words)
        if not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))

    def finalize(self) -> str | None:
        """Commit the remainder at release (spec 6.5 step 2)."""
        if not self._uncommitted:
            return None
        return self._commit(len(self._uncommitted))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_committer.py -v`
Expected: 15 passed. If the stable-prefix tests fail, fix the implementation — the tests encode the spec.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/committer.py tests/test_committer.py
git commit -m "phase2(committer): silence, completion and stable-prefix commit rules"
```

---

### Task 17: Streaming STT engine

Replaces `BatchSttEngine` behind the interface Task 10 defined. The implementation
follows **ADR 0001**: a native streaming API if one exists, otherwise emulated
commits via incremental re-transcription plus VAD (spec 5.3).

**Files:**
- Modify: `flowd/stt.py`
- Test: `tests/test_stt_streaming.py`

**Interfaces:**
- Consumes: `Committer` (Task 16), `VadEngine` (Task 15), ADR 0001.
- Produces: `StreamingSttEngine(transcribe, vad, committer, block_ms=100)` satisfying `SttEngine`, plus the extended `load_engine(cfg, model_dir, vad_cfg: Vad | None = None, block_ms: int = 100)` that supersedes Task 10's two-argument form, emitting `Partial` on every hypothesis change and `Committed` when the committer commits.

- [ ] **Step 1: Write the failing test**

`tests/test_stt_streaming.py`:

```python
import numpy as np

from flowd.committer import Committer
from flowd.stt import Committed, Partial, StreamingSttEngine
from flowd.vad import FakeVad

BLOCK = np.zeros(1600, dtype=np.float32)


def engine(texts: list[str], speech: list[bool]) -> StreamingSttEngine:
    """Build an engine whose transcriber returns `texts` in order."""
    seq = iter(texts)
    last = {"text": ""}

    def transcribe(_pcm: np.ndarray) -> str:
        last["text"] = next(seq, last["text"])
        return last["text"]

    return StreamingSttEngine(
        transcribe=transcribe,
        vad=FakeVad(speech, block_ms=100),
        committer=Committer(commit_silence_ms=350),
        block_ms=100,
    )


def test_emits_partial_as_hypothesis_grows() -> None:
    e = engine(["hello", "hello there"], [True, True])
    assert e.feed(BLOCK) == [Partial("hello")]
    assert e.feed(BLOCK) == [Partial("hello there")]


def test_unchanged_hypothesis_emits_nothing() -> None:
    e = engine(["hello", "hello"], [True, True])
    e.feed(BLOCK)
    assert e.feed(BLOCK) == []


def test_silence_run_commits_and_emits_committed() -> None:
    """350 ms of silence at 100 ms blocks means four silent blocks."""
    e = engine(["hello there"], [True, False, False, False, False])
    e.feed(BLOCK)
    events: list[object] = []
    for _ in range(4):
        events.extend(e.feed(BLOCK))
    assert Committed("hello there") in events


def test_committed_text_is_not_repeated_in_later_partials() -> None:
    e = engine(["one two", "one two three"], [True, False, False, False, False, True])
    e.feed(BLOCK)
    for _ in range(4):
        e.feed(BLOCK)
    later = e.feed(BLOCK)
    partials = [ev.text for ev in later if isinstance(ev, Partial)]
    assert all(not p.startswith("one two three") or p == "three" for p in partials) or partials == [
        "three"
    ]


def test_no_speech_at_all_emits_nothing() -> None:
    e = engine([""], [False, False, False, False])
    events: list[object] = []
    for _ in range(4):
        events.extend(e.feed(BLOCK))
    assert events == []


def test_finalize_commits_the_remainder() -> None:
    e = engine(["trailing words"], [True])
    e.feed(BLOCK)
    assert e.finalize() == [Committed("trailing words")]


def test_finalize_twice_is_safe() -> None:
    e = engine(["words here"], [True])
    e.feed(BLOCK)
    e.finalize()
    assert e.finalize() == []


def test_finalize_with_no_audio_emits_nothing() -> None:
    e = engine([], [])
    assert e.finalize() == []


def test_empty_block_is_ignored() -> None:
    e = engine(["hello"], [True])
    assert e.feed(np.empty(0, dtype=np.float32)) == []


def test_partial_never_contains_committed_prefix_twice() -> None:
    e = engine(["a b c d e f"], [True])
    events = e.feed(BLOCK)
    assert len([ev for ev in events if isinstance(ev, Partial)]) == 1
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_stt_streaming.py -v`
Expected: FAIL, `ImportError: cannot import name 'StreamingSttEngine'`

- [ ] **Step 3: Add `StreamingSttEngine` to `flowd/stt.py`**

```python
class StreamingSttEngine:
    """Streaming STT with VAD-driven commits (spec 5.3).

    If ADR 0001 found a native streaming API with commit events, `transcribe` is
    that API's incremental call and the committer only enforces the stable-prefix
    rule. If it did not, this emulates commits per spec 5.3: re-transcribe the
    current utterance each block and commit on a VAD pause.
    """

    def __init__(
        self,
        transcribe: Callable[[np.ndarray], str],
        vad: "VadEngine",
        committer: "Committer",
        block_ms: int = 100,
    ) -> None:
        self._transcribe = transcribe
        self._vad = vad
        self._committer = committer
        self._block_ms = block_ms
        self._buffer: list[np.ndarray] = []
        self._last_partial = ""

    def feed(self, pcm: np.ndarray) -> list[Event]:
        if pcm.size == 0:
            return []
        self._buffer.append(np.asarray(pcm, dtype=np.float32))
        frame = self._vad.process(pcm)
        events: list[Event] = []

        if frame.speech:
            hypothesis = self._transcribe(np.concatenate(self._buffer)).strip()
            if hypothesis and hypothesis != self._last_partial:
                self._last_partial = hypothesis
                committed = self._committer.on_partial(hypothesis)
                if committed:
                    events.append(Committed(committed))
                remainder = self._committer.uncommitted_text
                if remainder:
                    events.append(Partial(remainder))

        committed = self._committer.on_silence(frame.silence_ms)
        if committed:
            events.append(Committed(committed))
            # The utterance ended: start the next one from a clean buffer so
            # re-transcription cost stays bounded (spec 10.1).
            self._buffer.clear()
            self._last_partial = ""
            self._vad.reset()
        return events

    def finalize(self) -> list[Event]:
        committed = self._committer.finalize()
        self._buffer.clear()
        self._last_partial = ""
        return [Committed(committed)] if committed else []
```

Add the imports at the top of `flowd/stt.py`:

```python
from flowd.committer import Committer
from flowd.vad import VadEngine
```

Then extend `load_engine` to build the streaming engine:

```python
def load_engine(
    cfg: Stt, model_dir: Path, vad_cfg: "Vad | None" = None, block_ms: int = 100
) -> SttEngine:
    """Load Moonshine once at daemon start; never reload per session (spec 5.3)."""
    import moonshine_voice

    from flowd.config import Vad
    from flowd.vad import load_vad

    model = moonshine_voice.load_model(cfg.model)
    log.info("loaded STT model %s", cfg.model)

    def transcribe(pcm: np.ndarray) -> str:
        return str(model.transcribe(pcm))

    if vad_cfg is None:
        return BatchSttEngine(transcribe=transcribe)
    committer = Committer(
        max_uncommitted_words=cfg.max_uncommitted_words,
        commit_silence_ms=vad_cfg.commit_silence_ms,
    )
    return StreamingSttEngine(
        transcribe=transcribe,
        vad=load_vad(vad_cfg, model_dir, block_ms=block_ms),
        committer=committer,
        block_ms=block_ms,
    )
```

Update `flowd/main.py` to pass `cfg.vad` and `cfg.audio.block_ms` so the daemon
gets the streaming engine while `--replay` can still use either.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_stt_streaming.py -v`
Expected: 10 passed.

- [ ] **Step 5: Measure first-partial latency on real audio**

```bash
uv run flowd --replay eval/audio/sample.wav
```

Expected: `STAGES:` shows `first_partial_ms` **≤ 300** (spec 10.1). If it exceeds
300 ms, follow the spec 10.4 optimisation order — set ONNX Runtime intra-op
threads explicitly, then lower the re-transcription window — before considering a
smaller model, which needs a decision record.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/stt.py flowd/main.py tests/test_stt_streaming.py
git commit -m "phase2(stt): streaming engine with VAD-driven commits"
```

---
### Task 18: GTK4 overlay process and ADR 0003

**The overlay must never take keyboard focus.** A focus-stealing overlay breaks
injection and is worse than no overlay (spec 5.8), so that property is the
acceptance criterion, verified by hand on Hyprland.

This file runs on `/usr/bin/python3` with pacman's `python-gobject`, **outside the
venv**, and imports only the standard library plus `gi`. `mypy` excludes it
(Task 1) because its imports are not resolvable from the venv.

**Files:**
- Create: `overlay/flowd_overlay.py`, `docs/decisions/0003-overlay-focus.md`
- Test: `tests/test_overlay_process.py`

**Interfaces:**
- Consumes: newline-delimited JSON on stdin — `{"type": "render", "polished": …, "pending": …, "live": …}`, plus `{"type": "show"}`, `{"type": "hide"}`, `{"type": "quit"}`.
- Produces: an executable script. No Python API; the process boundary is the contract.

- [ ] **Step 1: Write the failing test**

The GTK window needs a compositor, so CI tests the parts that do not: the script
parses, refuses to crash on malformed input, and exits cleanly.

`tests/test_overlay_process.py`:

```python
import os
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay" / "flowd_overlay.py"
HAS_DISPLAY = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def test_overlay_uses_only_stdlib_and_gi() -> None:
    """It runs on the system interpreter, so it cannot import from the venv."""
    source = OVERLAY.read_text()
    for banned in ("from flowd", "import flowd", "import numpy", "import sounddevice"):
        assert banned not in source, f"overlay must not {banned}"


def test_overlay_compiles_under_the_system_interpreter() -> None:
    result = subprocess.run(
        ["/usr/bin/python3", "-m", "py_compile", str(OVERLAY)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not HAS_DISPLAY, reason="needs a compositor")
def test_overlay_exits_on_quit_message() -> None:
    proc = subprocess.run(
        ["/usr/bin/python3", str(OVERLAY)],
        input='{"type": "show"}\n{"type": "render", "live": "hi"}\n{"type": "quit"}\n',
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not HAS_DISPLAY, reason="needs a compositor")
def test_overlay_survives_malformed_input() -> None:
    """A bad line must be logged and skipped, never crash the child."""
    proc = subprocess.run(
        ["/usr/bin/python3", str(OVERLAY)],
        input='not json\n{"type": "nonsense"}\n{"type": "quit"}\n',
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_overlay_process.py -v`
Expected: FAIL — the overlay does not exist.

- [ ] **Step 3: Implement `overlay/flowd_overlay.py`**

```python
#!/usr/bin/env python3
"""flowd preview overlay (spec 5.8).

A separate process because GTK wants the main thread and an overlay crash must
never kill a dictation. Runs on the SYSTEM interpreter with pacman's
python-gobject, so it imports only the standard library and gi — never anything
from the flowd package or its venv.

Protocol: newline-delimited JSON on stdin.
  {"type": "show"}
  {"type": "render", "polished": "...", "pending": "...", "live": "..."}
  {"type": "hide"}
  {"type": "quit"}
"""

from __future__ import annotations

import json
import logging
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

log = logging.getLogger("flowd-overlay")

MAX_LINES = 4
FADE_MS = 1000

_CSS = b"""
.flowd-overlay {
  background-color: rgba(20, 20, 24, 0.88);
  border-radius: 12px;
  padding: 10px 16px;
}
.flowd-polished { color: #f2f2f7; font-size: 15px; }
.flowd-pending  { color: #f2f2f7; opacity: 0.55; font-size: 15px; }
.flowd-live     { color: #9ad2ff; font-style: italic; font-size: 15px; }
"""


def _try_layer_shell(window: Gtk.Window) -> bool:
    """Anchor the window bottom-center with keyboard interactivity NONE.

    Returns False when layer-shell is unavailable (notably GNOME Wayland), where
    spec 5.8 requires the overlay be disabled rather than risk stealing focus.
    """
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError) as exc:
        log.warning("gtk4-layer-shell unavailable: %s", exc)
        return False

    try:
        LayerShell.init_for_window(window)
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(window, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_margin(window, LayerShell.Edge.BOTTOM, 80)
        # The whole point: never accept keyboard focus, or injection breaks.
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
    except Exception as exc:
        log.warning("could not initialise layer-shell: %s", exc)
        return False
    return True


class Overlay:
    def __init__(self) -> None:
        self.window = Gtk.Window()
        self.window.set_decorated(False)
        self.window.set_default_size(680, -1)
        self.window.set_can_focus(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("flowd-overlay")
        self.labels: dict[str, Gtk.Label] = {}
        for zone, css in (
            ("polished", "flowd-polished"),
            ("pending", "flowd-pending"),
            ("live", "flowd-live"),
        ):
            label = Gtk.Label(label="", wrap=True, xalign=0.0)
            label.set_lines(MAX_LINES)
            label.set_ellipsize(3)  # Pango.EllipsizeMode.END, without importing Pango
            label.add_css_class(css)
            label.set_visible(False)
            box.append(label)
            self.labels[zone] = label
        self.window.set_child(box)

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.layered = _try_layer_shell(self.window)
        if not self.layered:
            # Without layer-shell we cannot guarantee the window never takes
            # focus, and a focus-stealing overlay is worse than none (spec 5.8).
            log.error("no layer-shell: overlay disabled to protect injection")
        self._fade_source: int | None = None

    def show(self) -> None:
        if not self.layered:
            return
        self._cancel_fade()
        self.window.set_visible(True)

    def hide(self) -> None:
        self._cancel_fade()
        self.window.set_visible(False)

    def render(self, zones: dict[str, str]) -> None:
        if not self.layered:
            return
        self._cancel_fade()
        for zone, label in self.labels.items():
            text = (zones.get(zone) or "").strip()
            label.set_text(text)
            label.set_visible(bool(text))
        self.window.set_visible(True)

    def fade(self) -> None:
        """Hide shortly after injection (spec 5.8)."""
        self._cancel_fade()
        self._fade_source = GLib.timeout_add(FADE_MS, self._on_fade)

    def _on_fade(self) -> bool:
        self.window.set_visible(False)
        self._fade_source = None
        return GLib.SOURCE_REMOVE

    def _cancel_fade(self) -> None:
        if self._fade_source is not None:
            GLib.source_remove(self._fade_source)
            self._fade_source = None


def _reader(overlay: Overlay, app: Gtk.Application) -> None:
    """Read stdin on a worker thread, applying changes on the GTK main thread."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            kind = str(message.get("type", ""))
        except (json.JSONDecodeError, AttributeError) as exc:
            log.warning("ignoring malformed message: %s", exc)
            continue

        if kind == "quit":
            GLib.idle_add(app.quit)
            return
        if kind == "show":
            GLib.idle_add(overlay.show)
        elif kind == "hide":
            GLib.idle_add(overlay.hide)
        elif kind == "fade":
            GLib.idle_add(overlay.fade)
        elif kind == "render":
            zones = {k: message.get(k, "") for k in ("polished", "pending", "live")}
            GLib.idle_add(overlay.render, zones)
        else:
            log.warning("ignoring unknown message type: %r", kind)
    # The daemon closed our stdin, which means it exited or dropped us.
    GLib.idle_add(app.quit)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="overlay: %(message)s", stream=sys.stderr)
    app = Gtk.Application(application_id="dev.flowd.Overlay")
    holder: dict[str, Overlay] = {}

    def on_activate(_app: Gtk.Application) -> None:
        overlay = Overlay()
        holder["overlay"] = overlay
        app.add_window(overlay.window)
        threading.Thread(target=_reader, args=(overlay, app), daemon=True).start()

    app.connect("activate", on_activate)
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

```bash
chmod +x overlay/flowd_overlay.py
uv run pytest tests/test_overlay_process.py -v
```

Expected: 4 passed on Hyprland (2 passed, 2 skipped in CI).

- [ ] **Step 5: Determine whether `LD_PRELOAD` is required**

The package ships both a typelib and `liblayer-shell-preload.so`, so the preload
path exists; what is unknown is whether it is mandatory. Test both:

```bash
echo '{"type":"show"}
{"type":"render","live":"without preload"}
{"type":"quit"}' | /usr/bin/python3 overlay/flowd_overlay.py; echo "exit=$?"

echo '{"type":"show"}
{"type":"render","live":"with preload"}
{"type":"quit"}' | \
  LD_PRELOAD=/usr/lib/liblayer-shell-preload.so /usr/bin/python3 overlay/flowd_overlay.py
echo "exit=$?"
```

- [ ] **Step 6: Verify the overlay never takes focus** — the acceptance criterion

With the overlay visible, confirm the focused window is unchanged:

```bash
# Before showing the overlay
hyprctl activewindow -j | python3 -c 'import json,sys; print("before:", json.load(sys.stdin)["class"])'
# Show the overlay in another terminal, then re-check
hyprctl activewindow -j | python3 -c 'import json,sys; print("after: ", json.load(sys.stdin)["class"])'
hyprctl clients -j | python3 -c '
import json, sys
for c in json.load(sys.stdin):
    if "flowd" in (c.get("class") or "").lower():
        print("overlay focusable:", c.get("focusHistoryID"), c.get("class"))'
```

Expected: the focused window is identical before and after, and typing still goes
to the original app. **If the overlay takes focus, stop** — that is a spec 13.3
trigger. Disable the overlay, log why, and escalate in ADR 0003.

- [ ] **Step 7: Write `docs/decisions/0003-overlay-focus.md`**

Spec 13.4 template, `Status: accepted`, `Phase: 2`. It must record, with the real
command output as evidence:
1. Whether `LD_PRELOAD=/usr/lib/liblayer-shell-preload.so` is **required**,
   merely optional, or harmful. State how `flowd` spawns the child accordingly.
2. That the overlay does not take focus on Hyprland, with the `hyprctl` evidence.
3. The GTK4, `gtk4-layer-shell` and PyGObject versions used.
4. The documented behaviour where layer-shell is absent (GNOME Wayland): the
   overlay disables itself and logs why.

- [ ] **Step 8: Commit**

```bash
git add overlay/flowd_overlay.py tests/test_overlay_process.py docs/decisions/0003-overlay-focus.md
git commit -m "phase2(overlay): GTK4 layer-shell preview that never takes focus"
```

---

### Task 19: Overlay IPC and daemon wiring

**Files:**
- Create: `flowd/overlay_ipc.py`
- Modify: `flowd/daemon.py` (render the three zones), `flowd/main.py` (construct the overlay)
- Test: `tests/test_overlay_ipc.py`

**Interfaces:**
- Consumes: the overlay's stdin protocol (Task 18), `Overlay` config.
- Produces: `OverlayProcess(cfg, python="/usr/bin/python3", script=…, spawn=subprocess.Popen)` with `show()`, `hide()`, `fade()`, `render(**zones)`, `stop()`, and `alive: bool`. A dead child is respawned on the next session; every failure is swallowed and logged, because the overlay is optional (spec 9.5).

- [ ] **Step 1: Write the failing test**

`tests/test_overlay_ipc.py`:

```python
import json
from typing import Any

from flowd.config import Overlay as OverlayCfg
from flowd.overlay_ipc import OverlayProcess


class FakeProc:
    def __init__(self, alive: bool = True) -> None:
        self.written = b""
        self._alive = alive
        self.terminated = False
        self.stdin = self

    # stdin duck-typing
    def write(self, data: bytes) -> int:
        if not self._alive:
            raise BrokenPipeError("child is gone")
        self.written += data
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def poll(self) -> int | None:
        return None if self._alive else 1

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def overlay(proc: FakeProc, spawns: list[int] | None = None) -> OverlayProcess:
    counter = spawns if spawns is not None else []

    def spawn(*_args: Any, **_kwargs: Any) -> FakeProc:
        counter.append(1)
        return proc

    return OverlayProcess(OverlayCfg(), spawn=spawn)


def _messages(proc: FakeProc) -> list[dict[str, Any]]:
    return [json.loads(line) for line in proc.written.decode().splitlines() if line]


def test_show_spawns_and_sends_show() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    assert _messages(proc) == [{"type": "show"}]


def test_render_sends_three_zones() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.render(polished="done", pending="soon", live="now")
    assert _messages(proc)[-1] == {
        "type": "render",
        "polished": "done",
        "pending": "soon",
        "live": "now",
    }


def test_disabled_overlay_never_spawns() -> None:
    proc = FakeProc()
    spawns: list[int] = []
    o = OverlayProcess(OverlayCfg(enabled=False), spawn=lambda *a, **k: proc)
    o.show()
    o.render(live="x")
    assert proc.written == b""


def test_dead_child_is_respawned_on_next_show() -> None:
    """spec 9.5: an overlay crash must not end the session; respawn next time."""
    dead, alive = FakeProc(alive=False), FakeProc()
    procs = iter([dead, alive])
    spawns: list[int] = []

    def spawn(*_a: Any, **_k: Any) -> FakeProc:
        spawns.append(1)
        return next(procs)

    o = OverlayProcess(OverlayCfg(), spawn=spawn)
    o.show()          # spawns `dead`; the write fails
    o.show()          # notices it died and spawns `alive`
    assert len(spawns) == 2
    assert _messages(alive) == [{"type": "show"}]


def test_broken_pipe_is_swallowed() -> None:
    """A failing overlay must never raise into the dictation path."""
    o = overlay(FakeProc(alive=False))
    o.show()
    o.render(live="still fine")  # must not raise


def test_spawn_failure_is_swallowed() -> None:
    def spawn(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("/usr/bin/python3")

    o = OverlayProcess(OverlayCfg(), spawn=spawn)
    o.show()
    o.render(live="x")
    assert o.alive is False


def test_stop_terminates_child() -> None:
    proc = FakeProc()
    o = overlay(proc)
    o.show()
    o.stop()
    assert {"type": "quit"} in _messages(proc)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_overlay_ipc.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'flowd.overlay_ipc'`

- [ ] **Step 3: Implement `flowd/overlay_ipc.py`**

```python
"""Overlay child process management (spec 4, 9.5).

The overlay is optional: every failure here is logged and swallowed so a crashed
or missing overlay can never break a dictation.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from flowd.config import Overlay as OverlayCfg

log = logging.getLogger(__name__)

#: The overlay needs pacman's python-gobject, which is not in the venv (ADR 0003).
SYSTEM_PYTHON = "/usr/bin/python3"
DEFAULT_SCRIPT = Path(__file__).resolve().parent.parent / "overlay" / "flowd_overlay.py"


class OverlayProcess:
    def __init__(
        self,
        cfg: OverlayCfg,
        script: Path | None = None,
        python: str = SYSTEM_PYTHON,
        spawn: Callable[..., Any] = subprocess.Popen,
        preload: str | None = None,
    ) -> None:
        self._cfg = cfg
        self._script = script or DEFAULT_SCRIPT
        self._python = python
        self._spawn = spawn
        # Set only if ADR 0003 finds the preload is required.
        self._preload = preload
        self._proc: Any = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure(self) -> bool:
        if not self._cfg.enabled:
            return False
        if self.alive:
            return True
        env = dict(os.environ)
        if self._preload:
            env["LD_PRELOAD"] = self._preload
        try:
            self._proc = self._spawn(
                [self._python, str(self._script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                env=env,
            )
        except (OSError, ValueError) as exc:
            log.warning("could not start overlay: %s", exc)
            self._proc = None
            return False
        log.debug("overlay started")
        return True

    def _send(self, message: dict[str, Any]) -> None:
        if not self._ensure():
            return
        payload = json.dumps(message).encode("utf-8") + b"\n"
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError) as exc:
            log.warning("overlay died (%s); continuing without it", exc)
            self._proc = None

    def show(self) -> None:
        self._send({"type": "show"})

    def hide(self) -> None:
        self._send({"type": "hide"})

    def fade(self) -> None:
        self._send({"type": "fade"})

    def render(self, **zones: str) -> None:
        self._send({"type": "render", **{k: v for k, v in zones.items()}})

    def stop(self) -> None:
        if self._proc is None:
            return
        self._send({"type": "quit"})
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception as exc:
            log.debug("overlay did not exit cleanly: %s", exc)
        self._proc = None
```

- [ ] **Step 4: Wire the three zones into `flowd/daemon.py`**

Phase 2 has no LLM, so committed text shows in the **pending** zone (dimmed) and
the polished zone stays empty until phase 3 fills it. Replace `_render`:

```python
    def _render(self) -> None:
        """Paint the three preview zones (spec 6.1).

        Phase 2 has no LLM, so committed text is 'pending' — dimmed — and the
        polished zone stays empty until phase 3 resolves chunks.
        """
        if self.overlay is None or self.session is None:
            return
        polished = " ".join(
            c.text for c in self.session.visible_chunks() if c.state in ("DONE", "FALLBACK")
        )
        pending = " ".join(
            c.raw for c in self.session.visible_chunks() if c.state in ("PENDING", "INFLIGHT")
        )
        self.overlay.render(polished=polished, pending=pending, live=self.session.live_partial)
```

And in `_end_session`, fade rather than hide abruptly when text was injected:

```python
        if self.overlay is not None:
            self.overlay.fade() if text else self.overlay.hide()
```

- [ ] **Step 5: Construct the overlay in `flowd/main.py`**

```python
    from flowd.overlay_ipc import OverlayProcess

    overlay = OverlayProcess(cfg.overlay)
    daemon = Daemon(cfg=cfg, stt=engine, capture=capture, overlay=overlay)
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes, including the 7 new ones.

- [ ] **Step 7: Verify the live preview by hand on Hyprland**

```bash
uv run flowd &
./flowctl toggle    # speak a sentence
./flowctl toggle    # release
```

Expected: the overlay appears bottom-center, the live zone updates in italics as
you speak, committed text moves to the dimmed zone, the text lands in the focused
window, and the overlay fades about a second later. **Confirm the focused window
never changed** — that is the phase 2 gate.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . && uv run mypy flowd
git add flowd/overlay_ipc.py flowd/daemon.py flowd/main.py tests/test_overlay_ipc.py
git commit -m "phase2(overlay): child process management and three-zone rendering"
```

---

### Task 20: Phase 2 report and GitHub publication

**Files:**
- Create: `docs/reports/phase-2.md`

**Interfaces:**
- Consumes: the working daemon.
- Produces: the public repository.

- [ ] **Step 1: Measure the real numbers**

```bash
uv run flowd --replay eval/audio/sample.wav        # real time, for honest timings
./flowctl stats
systemd-cgtop --user 2>/dev/null | head -5 || ps -o rss=,comm= -C flowd
```

Record `first_partial_ms` against the 300 ms budget and RSS against 900 MB. The
900 MB figure assumes `llama-server` is resident; note whether it was running,
since phase 2 does not require it.

- [ ] **Step 2: Write `docs/reports/phase-2.md`**

Spec 14.1 template. Every acceptance criterion for phases 0, 1 and 2 gets a
Result and Evidence column. Real measurements only (spec 13.1.6). Record:
machine (Ryzen 5 5600H, 6 cores, Hyprland/Wayland), versions
(`moonshine-voice`, `llama-cpp` 0.4.1-dev build 10964, Python), latency per
stage, idle RSS and CPU, and deviations with their ADR links. **Any criterion not
met is listed as not met** — never quietly passed.

- [ ] **Step 3: Verify nothing private is about to be published**

```bash
git status --porcelain
git ls-files | grep -iE '\.(wav|flac|gguf|onnx)$|metrics\.jsonl|^vocab\.toml$' \
  && echo "STOP: private or large files are staged" || echo "clean: no audio, models or transcripts tracked"
```

Expected: `clean`. If anything is listed, remove it from the index and fix
`.gitignore` **before** the repo is created.

- [ ] **Step 4: Create the public repository**

One-time, outward-facing action. The full local commit history is pushed intact,
so the published history is identical to having created the repo on day one.

```bash
gh repo create flowd --public \
  --description "Local, offline, streaming dictation for Linux with on-device LLM cleanup" \
  --source=. --remote=origin --push
```

- [ ] **Step 5: Set the repository metadata**

```bash
gh repo edit --add-topic dictation,speech-to-text,linux,wayland,hyprland,local-first,privacy,llama-cpp,whisper-alternative
gh repo edit --enable-issues --enable-discussions=false --enable-wiki=false
gh repo view --web
```

- [ ] **Step 6: Confirm CI passed on the published repo**

```bash
gh run list --limit 3
gh run watch
```

If CI fails on 3.11 but passes locally on 3.14, fix the incompatibility — do not
raise the floor to make the gate pass (spec 13.2).

- [ ] **Step 7: Commit the report**

```bash
git add docs/reports/phase-2.md
git commit -m "phase2(report): handoff report with measured latencies"
git push
```

---

## Checkpoint

Phases 0–2 are complete when every box above is ticked and `docs/reports/phase-2.md`
exists with measured numbers. **Stop there.** Spec section 12 makes phase 2 a
review checkpoint: hand over the report, the ADRs (0001–0004) and any failing
logs before phase 3 begins.

Phase 3 (LLM cleanup, prompts, guardrails) and phase 4 (the chunk scheduler with
single-flight dispatch and self-correction merges) get their own plans.
