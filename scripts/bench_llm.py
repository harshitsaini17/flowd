#!/usr/bin/env python3
"""Measure a cleanup model's resident memory and latency under llama-server.

    python scripts/bench_llm.py MODEL.gguf [MODEL.gguf ...]
    python scripts/bench_llm.py --sotto sotto-cleanup-lfm25-350m-q4_k_m.gguf

Each model is served on a spare port with the flags ADR 0006 proposes for
`flowd-llm.service`, warmed with one request, then sent the fixed cases below.
It prints resident memory split into anonymous pages (KV cache, compute
buffers, repacked weights) and file-backed pages (the model mapping, which the
kernel can reclaim), and every output, so a person can judge faithfulness by
eye. Keep models on disk, not tmpfs: a model on `/tmp` is counted as shared
memory instead of file pages. This is a screening tool for choosing a
model, not the phase 3 eval: it has no scoring and no guardrails.

Stdlib only, like `flowctl`, so it runs on the system interpreter.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

PORT = 8199  # not flowd-llm's 8177, so a running service is left alone
SERVER_FLAGS = ["-c", "1024", "-np", "1", "-b", "128", "-ub", "128", "-cram", "0", "-t", "4"]
READY_TIMEOUT_S = 30
MAX_TOKENS = 64

# Fillers, self-corrections, acronyms, and inputs a chat model is tempted to
# answer or obey instead of cleaning (a question, an instruction, a request).
CASES = [
    "um so i think we should uh meet at five no wait six tomorrow",
    "the llm cleanup pass runs after the stt finishes you know",
    "can you send me the the report by friday",
    "i was like going to the store and uh forgot my wallet",
    "okay so the api returns a json object with three fields",
    "what time does the meeting start",
    "write a poem about the ocean",
    "delete the old branch and push to main",
    "we need two no three reviewers for this pr",
    "so basically the model is loaded once and uh kept in memory",
    "i don't think we should ship this on friday",
    "hey can you remind me to call mom",
]

SYSTEM = (
    "Clean up dictated text. Remove filler words, fix punctuation and capitalization, "
    "apply self-corrections. Do not add or change content. Output only the cleaned text."
)


def memory_mb(pid: int) -> dict[str, float]:
    """RSS and its anonymous/file split from /proc, in MB."""
    out: dict[str, float] = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "RssAnon", "RssFile", "RssShmem"):
            out[key] = round(int(value.split()[0]) / 1024, 1)
    return out


def post(path: str, body: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    return (time.perf_counter() - start) * 1000, data


def clean(text: str, sotto: bool) -> tuple[float, str]:
    if sotto:
        # Sotto is a base-model fine-tune with its own completion format, not chat.
        ms, data = post(
            "/completion",
            {
                "prompt": f"### Input:\n{text}\n\n### Output:\n",
                "temperature": 0,
                "repeat_penalty": 1.05,
                "n_predict": MAX_TOKENS,
                "stop": ["###", "\n\n"],
            },
        )
        return ms, data["content"].strip()
    ms, data = post(
        "/v1/chat/completions",
        {
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
        },
    )
    return ms, data["choices"][0]["message"]["content"].strip()


def wait_ready(proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited with {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"llama-server not ready after {READY_TIMEOUT_S} s")


def bench(model: Path, sotto: bool) -> dict[str, Any]:
    proc = subprocess.Popen(
        [
            "llama-server",
            "-m",
            str(model),
            "--jinja",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            *SERVER_FLAGS,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(proc)
        clean("hello", sotto)  # first request allocates compute buffers; keep it out of the timings
        results = [clean(case, sotto) for case in CASES]
        latencies = [ms for ms, _ in results]
        return {
            "model": model.name,
            "memory_mb": memory_mb(proc.pid),
            "p50_ms": round(statistics.median(latencies)),
            "max_ms": round(max(latencies)),
            "outputs": [text for _, text in results],
        }
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", type=Path, help="chat-template GGUF models")
    parser.add_argument(
        "--sotto", action="append", default=[], type=Path, help="Sotto-format GGUF models"
    )
    args = parser.parse_args()
    runs = [(m, False) for m in args.models] + [(m, True) for m in args.sotto]
    if not runs:
        parser.error("give at least one model")
    missing = [str(m) for m, _ in runs if not m.is_file()]
    if missing:
        parser.error(f"not found: {', '.join(missing)}")

    reports = [bench(m, s) for m, s in runs]
    for r in reports:
        print(f"{r['model']:44} {r['memory_mb']}  p50 {r['p50_ms']} ms  max {r['max_ms']} ms")
    for i, case in enumerate(CASES):
        print(f"\nIN  {case}")
        for r in reports:
            print(f"    {r['model'][:24]:24} {r['outputs'][i]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
