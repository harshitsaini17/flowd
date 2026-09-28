# 0012: Ship native binaries built with mypyc and Nuitka

**Status:** accepted (2026-09-28)

## Context

flowd runs from a `uv` virtualenv. Installing it means Python, a venv and a
wheel set, and every start imports the package from source. The goal is a
native `flowd` and `flowctl` that are easy to package (AUR, no venv) and start
and run with less overhead.

A C++ rewrite of the daemon was considered and rejected. The heavy work already
runs in native code (Moonshine and Parakeet through ONNX Runtime, the LLM in
llama.cpp), and model weights are about 1.3 GB of the 1.5 GB idle total
(ADR 0011). A rewrite would cost months to save an estimated 100–150 MB.

## Decision

- **mypyc** compiles the modules that run on every audio block or text update:
  `joiner`, `committer`, `textclean`, `guardrails`, `scheduler`, `vad`, and the
  ring buffer in `audio`. The code is already `mypy --strict`. Other modules
  stay bytecode; compiling them gains nothing measurable.
- **Nuitka** builds `dist/flowd` and `dist/flowctl`, bundling the compiled
  modules, numpy, sounddevice, moonshine-voice and sherpa-onnx with their
  shared libraries.
- **Layout:** `--standalone` into a directory (`/usr/lib/flowd/` in a package,
  with `/usr/bin` symlinks). `--onefile` unpacks to a temp directory on every
  start; it is only used if a measurement shows the cost is negligible.
- Model files stay outside the binary, fetched and hash-checked by
  `scripts/fetch_models.sh` as today.
- `make dist` runs all of it. The venv workflow stays for development.
- `flowctl` is also built as a Nuitka binary. If it misses the 20 ms round trip,
  it is replaced by a small C++ client over the same socket protocol.

## Targets

Measured before and after on the reference machine (Ryzen 5 5600H):

| Metric | Before | Target |
| --- | --- | --- |
| Daemon start → ready | measured first | no worse than before |
| `flowctl` round trip | ~20 ms | ≤ 20 ms |
| Release → inject p50 | ~400 ms | no regression |
| Idle anonymous memory, all processes | ~1.5 GB | ≤ 1.35 GB (with ADR 0013) |

The full pytest suite runs against the compiled build as well as against source.

## Consequences

- Build dependencies: `mypy` (already dev), `nuitka`, a C compiler. Pinned.
- Tests that monkeypatch module globals of compiled modules may need to patch
  through an injected dependency instead; mypyc freezes module attributes.
- Further optimizations, kept as follow-up work so this build is measured on
  its own: one shared ONNX Runtime for Moonshine and Parakeet (both bundle
  their own, roughly 50–100 MB), and the ~2.2 s from mic open to first preview
  word.
