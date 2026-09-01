"""Entry point: argument parsing, logging, model verification, run loop."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from flowd import __version__
from flowd.audio import AudioCapture, load_wav
from flowd.config import Config, data_dir, load_config, runtime_dir, state_dir
from flowd.inject.base import InjectResult
from flowd.models import verify_models
from flowd.stt import load_engine

log = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,  # journald captures stdout (spec 10.3)
    )


def lock_path() -> Path:
    """Where `models.lock` lives in a source checkout.

    An installed wheel packages only `flowd/`, so this path does not exist
    there and verification is skipped with a warning rather than refusing to
    start.
    """
    return Path(__file__).resolve().parent.parent / "models.lock"


def _verify_or_exit(cfg: Config) -> None:
    lock = lock_path()
    models = data_dir() / "models"
    if not lock.is_file():
        log.warning("no models.lock at %s; skipping verification", lock)
        return
    problems = verify_models(lock, models)
    if problems:
        for problem in problems:
            log.error("model verification: %s", problem)
        log.error("refusing to start; run scripts/fetch_models.sh")
        raise SystemExit(2)


class _ReplayCapture:
    """Feeds a WAV through the real pipeline (spec 11.2)."""

    def __init__(
        self,
        pcm: np.ndarray,
        block: int,
        sample_rate: int,
        realtime: bool,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._pcm = pcm
        self._block = block
        self._sample_rate = sample_rate
        self._realtime = realtime
        self._clock = clock
        self._sleep = sleep
        self._pos = 0
        self._started_at = clock()

    def start(self) -> None:
        self._pos = 0
        self._started_at = self._clock()

    def stop(self) -> None:
        pass

    def read(self) -> np.ndarray:
        if self._pos >= len(self._pcm):
            return np.empty(0, dtype=np.float32)
        chunk = self._pcm[self._pos : self._pos + self._block]
        if self._realtime:
            # Pace playback at the configured rate so measured latencies mean
            # something. `--fast` skips this.
            #
            # The deadline is absolute — start plus the audio delivered so far —
            # not "a block after the previous wait". A microphone keeps its own
            # schedule, and Moonshine decodes in bursts: a relative deadline adds
            # every burst that outran a block to the clip instead of catching up
            # on the cheap blocks after it, so a 12 s clip took 16 s and every
            # latency reported was inflated by however slow the machine was.
            due = self._started_at + (self._pos + len(chunk)) / self._sample_rate
            now = self._clock()
            if now < due:
                self._sleep(due - now)
        self._pos += self._block
        return chunk

    def pending_seconds(self) -> float:
        return 0.0

    @property
    def exhausted(self) -> bool:
        return self._pos >= len(self._pcm)


def replay_config(cfg: Config) -> Config:
    """Disable hotkey debounce for a replay run.

    Debounce exists to swallow a double hotkey press (spec 9.1). A replay issues
    `start` and `stop` programmatically, microseconds apart with `--fast`, so the
    debounce window would swallow the `stop` and the run would print no text at
    all.
    """
    return dataclasses.replace(cfg, hotkey=dataclasses.replace(cfg.hotkey, debounce_ms=0))


async def _replay(cfg: Config, path: Path, fast: bool) -> int:
    from flowd.daemon import Daemon

    pcm = load_wav(path, cfg.audio.sample_rate)
    block = cfg.audio.sample_rate * cfg.audio.block_ms // 1000
    capture = _ReplayCapture(pcm, block, cfg.audio.sample_rate, realtime=not fast)
    # The capture rate must reach the engine: Moonshine resamples from whatever
    # rate it is told, so a wrong value transcribes as gibberish (ADR 0001).
    engine = load_engine(
        cfg.stt,
        data_dir() / "models",
        cfg.audio.sample_rate,
        vad_cfg=cfg.vad,
        block_ms=cfg.audio.block_ms,
    )

    def no_inject(text: str, inject_cfg: Any, **kwargs: Any) -> InjectResult:
        return InjectResult(ok=True, backend="replay")

    daemon = Daemon(
        cfg=replay_config(cfg),
        stt=engine,
        capture=capture,
        injector=no_inject,
        metrics_path=None,
    )
    await daemon.handle({"cmd": "start"})
    while not capture.exhausted:
        await daemon.pump()
    reply = await daemon.handle({"cmd": "stop"})
    print(f"TEXT: {reply.get('text', '')}")
    print(f"STAGES: {daemon.last_record.get('stages', {})}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flowd", description="Local dictation daemon")
    parser.add_argument("--replay", type=Path, help="feed a mono WAV through the pipeline")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="with --replay, run as fast as possible instead of real time",
    )
    parser.add_argument("--log-level", default=None, choices=["debug", "info", "warning", "error"])
    # Bug reports ask for this, so it prints without touching config, the
    # models or the socket: `--version` must answer on a machine where the
    # thing being reported is that flowd will not start.
    parser.add_argument("--version", action="version", version=f"flowd {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = load_config()
    _setup_logging(args.log_level or cfg.logging.level)
    if args.fast and args.replay is None:
        log.warning("--fast has no effect without --replay")
    _verify_or_exit(cfg)

    if args.replay is not None:
        return asyncio.run(_replay(cfg, args.replay, args.fast))

    from flowd.control import AlreadyRunning
    from flowd.daemon import Daemon

    engine = load_engine(
        cfg.stt,
        data_dir() / "models",
        cfg.audio.sample_rate,
        vad_cfg=cfg.vad,
        block_ms=cfg.audio.block_ms,
    )
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
