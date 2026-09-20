"""Seed eval/long/ with ~60 s dictations stitched from LibriSpeech (a dry run only).

    uv run python eval/seed_longform.py [--count 6] [--seconds 60]

Spec 12's phase 4 gate measures release → inject on 60 s dictations, which the
single LibriSpeech utterances (2-20 s) do not reach. Each file here is one
speaker's consecutive utterances joined with 0.6 s of silence, so the committer
sees pauses where a person dictating would take them. Named `lf-<speaker>` so
they never collide with the owner's recordings. Needs `ffmpeg`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RATE = 16_000
GAP_S = 0.6


def decode(flac: Path) -> np.ndarray:
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(flac), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(pcm, dtype=np.int16)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    corpus = ROOT / "audio" / "LibriSpeech" / "test-clean"
    if not corpus.is_dir():
        print("seed: no corpus; run scripts/fetch_eval_audio.sh", file=sys.stderr)
        return 1
    out = ROOT / "long"
    out.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(GAP_S * RATE), dtype=np.int16)
    made = 0
    for trans in sorted(corpus.rglob("*.trans.txt")):
        if made >= args.count:
            break
        pieces: list[np.ndarray] = []
        words: list[str] = []
        total = 0.0
        for line in trans.read_text(encoding="utf-8").splitlines():
            utt, _, text = line.partition(" ")
            pcm = decode(trans.parent / f"{utt}.flac")
            pieces += [pcm, gap]
            words.append(text.lower())
            total += len(pcm) / RATE + GAP_S
            if total >= args.seconds:
                break
        if total < args.seconds * 0.9:
            continue
        stem = out / f"lf-{trans.parent.parent.name}-{trans.parent.name}"
        with wave.open(str(stem.with_suffix(".wav")), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(np.concatenate(pieces).tobytes())
        text = " ".join(words) + "\n"
        stem.with_suffix(".ref.txt").write_text(text, encoding="utf-8")
        stem.with_suffix(".raw.txt").write_text(text, encoding="utf-8")
        print(f"{stem.name}: {total:.1f} s, {len(' '.join(words).split())} words")
        made += 1
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
