"""Replay the personal eval set and record the results (spec 11.3).

    uv run python eval/run_eval.py [--data eval/data] [--realtime] [--no-llm]

Needs both models and a running `llama-server` (systemd/flowd-llm.service);
`--no-llm` skips the server and scores `basic_clean` alone, the "before" of a
spec 11.4 comparison. Writes `eval/results/<date>-<git sha>[-nollm].json`.
The file holds transcripts, so it stays local like the audio: `eval/results/`
is gitignored (spec 13.2).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flowd.audio import load_wav
from flowd.cleanup import CleanupClient
from flowd.config import Config, data_dir, load_config
from flowd.daemon import Daemon
from flowd.evaluation import FileResult, flag_novel, load_items, summarise
from flowd.inject.base import InjectResult
from flowd.main import _ReplayCapture, replay_config
from flowd.stt import SttEngine, load_engine
from flowd.vocab import load_vocab

ROOT = Path(__file__).resolve().parent


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
    except (OSError, subprocess.CalledProcessError):
        return "nogit"
    return out.stdout.strip()


def no_inject(text: str, inject_cfg: Any, **kwargs: Any) -> InjectResult:
    return InjectResult(ok=True, backend="eval")


def describe(result: FileResult, *, use_llm: bool) -> str:
    """Which path produced the file's text, for the progress line."""
    if not use_llm:
        return "basic"
    if not result.llm_tried:
        return "bypass"
    return "fallback" if result.fell_back else "llm"


async def replay_one(
    cfg: Config, engine: SttEngine, cleanup: CleanupClient | None, wav: Path, realtime: bool
) -> tuple[str, str, dict[str, Any]]:
    pcm = load_wav(wav, cfg.audio.sample_rate)
    block = cfg.audio.sample_rate * cfg.audio.block_ms // 1000
    capture = _ReplayCapture(pcm, block, cfg.audio.sample_rate, realtime=realtime)
    daemon = Daemon(
        cfg=cfg,
        stt=engine,
        capture=capture,
        injector=no_inject,
        write_metrics=False,
        vocab=load_vocab(),
        cleanup=cleanup,
    )
    await daemon.handle({"cmd": "start"})
    while not capture.exhausted:
        await daemon.pump()
    reply = await daemon.handle({"cmd": "stop"})
    return daemon.last_raw, str(reply.get("text", "")), daemon.last_record


async def run(data: Path, realtime: bool, use_llm: bool) -> int:
    items = load_items(data)
    if not items:
        print(f"run_eval: no NNN.wav + NNN.ref.txt pairs in {data}", file=sys.stderr)
        return 1
    cfg = replay_config(load_config())
    engine = load_engine(
        cfg.stt,
        data_dir() / "models",
        cfg.audio.sample_rate,
        vad_cfg=cfg.vad,
        block_ms=cfg.audio.block_ms,
    )
    cleanup = CleanupClient(cfg.llm) if use_llm else None
    if cleanup is not None and not await cleanup.check_health():
        print(f"run_eval: llama-server is not answering at {cfg.llm.url}", file=sys.stderr)
        await cleanup.aclose()
        return 1
    terms = load_vocab().terms
    results: list[FileResult] = []
    try:
        for wav, ref, raw_ref in items:
            raw, final, record = await replay_one(cfg, engine, cleanup, wav, realtime)
            result = FileResult(wav.stem, ref, raw, final, record, raw_ref)
            flag_novel(result, terms)
            results.append(result)
            status = describe(result, use_llm=cleanup is not None)
            print(f"{wav.stem}: {status}{'  REVIEW ' + str(result.novel) if result.novel else ''}")
    finally:
        if cleanup is not None:
            await cleanup.aclose()

    summary = summarise(results)
    today = datetime.date.today().isoformat()
    suffix = "" if use_llm else "-nollm"
    out = ROOT / "results" / f"{today}-{git_sha()}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": today,
        "git_sha": git_sha(),
        "data": str(data),
        "realtime": realtime,
        "llm": use_llm,
        "summary": summary,
        "files": [asdict(r) for r in results],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="pace audio at real time, so latencies match live dictation",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="basic_clean only: the baseline for a before-and-after comparison",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.data, args.realtime, use_llm=not args.no_llm))


if __name__ == "__main__":
    sys.exit(main())
