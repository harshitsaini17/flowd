"""Entry point: argument parsing, logging, model verification, run loop."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import numpy as np

from flowd import __version__
from flowd.audio import AudioCapture, MicrophoneStuck, load_wav
from flowd.config import Config, data_dir, load_config, runtime_dir, state_dir
from flowd.context import detect
from flowd.hybrid import HybridSttEngine, load_parakeet
from flowd.inject.base import InjectResult
from flowd.models import verify_models
from flowd.stt import load_engine

log = logging.getLogger(__name__)

#: Distinct exit codes, so `systemctl --user status flowd` says which kind of
#: failure it is restarting from. 2 is `_verify_or_exit`'s hash mismatch.
EXIT_CONFIG = 3
EXIT_STT_LOAD = 4
#: ADR 0015: an audio stream would not stop. Non-zero so systemd restarts us,
#: which releases the device.
EXIT_MIC_STUCK = 5


def _hard_exit(code: int) -> NoReturn:
    """Exit now, skipping atexit handlers (ADR 0015).

    `sounddevice`'s atexit handler calls `Pa_Terminate`, and with a stuck
    microphone an abandoned thread may still be inside `Pa_StopStream`. A
    deadlock there would leave the process running, so systemd would never
    restart it. Logs and stdio are flushed first, since `os._exit` does not.
    """
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


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


def _load_stt(cfg: Config) -> Any:
    """The streaming engine, or None after logging why it could not load.

    spec 9.2: the caller exits non-zero, and systemd's `Restart=on-failure`
    backs off rather than flowd retrying in-process.
    """
    try:
        live = load_engine(
            cfg.stt,
            data_dir() / "models",
            cfg.audio.sample_rate,
            vad_cfg=cfg.vad,
            block_ms=cfg.audio.block_ms,
        )
    except Exception as exc:
        log.error("could not load the STT model %r: %s", cfg.stt.model, exc)
        log.error("check the model name in config.toml and your network for the first download")
        return None
    if not cfg.stt.final_model:
        return live
    try:
        transcribe = load_parakeet(
            data_dir() / "models" / cfg.stt.final_model, cfg.audio.sample_rate
        )
    except Exception as exc:
        log.error("could not load the final STT model %r: %s", cfg.stt.final_model, exc)
        log.error('run scripts/fetch_models.sh, or set [stt] final_model = "" to go without')
        return None
    return HybridSttEngine(live, transcribe, sample_rate=cfg.audio.sample_rate)


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
    from flowd.cleanup import CleanupClient
    from flowd.daemon import Daemon

    pcm = load_wav(path, cfg.audio.sample_rate)
    block = cfg.audio.sample_rate * cfg.audio.block_ms // 1000
    capture = _ReplayCapture(pcm, block, cfg.audio.sample_rate, realtime=not fast)
    # The capture rate must reach the engine: Moonshine resamples from whatever
    # rate it is told, so a wrong value transcribes as gibberish (ADR 0001).
    engine = _load_stt(cfg)
    if engine is None:
        return EXIT_STT_LOAD

    def no_inject(text: str, inject_cfg: Any, **kwargs: Any) -> InjectResult:
        return InjectResult(ok=True, backend="replay")

    # The real cleanup client: a replay measures release → inject, and the LLM
    # pass is the largest part of that.
    daemon = Daemon(
        cfg=replay_config(cfg),
        stt=engine,
        capture=capture,
        injector=no_inject,
        write_metrics=False,
        cleanup=CleanupClient(cfg.llm),
    )
    try:
        await daemon.handle({"cmd": "start"})
        while not capture.exhausted:
            await daemon.pump()
        reply = await daemon.handle({"cmd": "stop"})
    finally:
        if daemon.cleanup is not None:
            await daemon.cleanup.aclose()
    record = daemon.last_record
    print(f"TEXT: {reply.get('text', '')}")
    print(f"STAGES: {record.get('stages', {})}")
    # Which path produced TEXT: the LLM, a bypass, or a fallback and why.
    print(f"COUNTS: {record.get('counts', {})}")
    print(f"FALLBACK: checks={record.get('fallback_checks', {})} errors={record.get('errors', [])}")
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

    try:
        cfg = load_config()
    except (OSError, ValueError) as exc:
        # Before logging is set up, and it is the user's file: say which key.
        print(f"flowd: invalid config: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    _setup_logging(args.log_level or cfg.logging.level)
    if args.fast and args.replay is None:
        log.warning("--fast has no effect without --replay")
    _verify_or_exit(cfg)

    if args.replay is not None:
        return asyncio.run(_replay(cfg, args.replay, args.fast))

    from flowd.cleanup import CleanupClient
    from flowd.control import AlreadyRunning
    from flowd.daemon import Daemon
    from flowd.ui_ipc import UiProcess

    engine = _load_stt(cfg)
    if engine is None:
        return EXIT_STT_LOAD
    capture = AudioCapture(cfg.audio)
    state_dir().mkdir(parents=True, exist_ok=True)
    # flowd-ui dies with the daemon. `--replay` deliberately gets none: it
    # exists to measure latency, and a window competing for cores would skew
    # what it reports.
    ui = UiProcess(cfg.ui, cfg.audio.max_session_s)
    daemon = Daemon(
        cfg=cfg,
        stt=engine,
        capture=capture,
        overlay=ui,
        cleanup=CleanupClient(cfg.llm),
        context=detect,
    )
    ui.on_event = daemon.on_ui_event
    try:
        asyncio.run(daemon.run(runtime_dir() / "flowd.sock"))
    except AlreadyRunning as exc:
        print(f"flowd: {exc}", file=sys.stderr)
        return 1
    except MicrophoneStuck as exc:
        print(f"flowd: {exc}; exiting so the microphone is released", file=sys.stderr)
        _hard_exit(EXIT_MIC_STUCK)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
