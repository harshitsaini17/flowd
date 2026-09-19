"""Seed eval/data/ from the LibriSpeech clips in eval/audio/ (a dry run only).

    uv run python eval/seed_librispeech.py

Read audiobook speech is not the owner's dictation: it has no fillers, no
self-corrections and no technical terms, so it exercises the harness and gives
a raw WER floor, not spec 11.3's gate. The reference is the corpus transcript
for both `ref.txt` and `raw.txt`, which is exact for words (WER ignores case
and punctuation). Files are named `ls-<utterance>` so they never collide with
the owner's `NNN` recordings.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def transcripts(corpus: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for trans in corpus.rglob("*.trans.txt"):
        for line in trans.read_text(encoding="utf-8").splitlines():
            utt, _, text = line.partition(" ")
            if text:
                found[utt] = text.lower()
    return found


def main() -> int:
    audio = ROOT / "audio"
    data = ROOT / "data"
    known = transcripts(audio / "LibriSpeech")
    wavs = sorted(audio.glob("*.wav"))
    if not wavs:
        print("seed: no WAVs in eval/audio; run scripts/fetch_eval_audio.sh", file=sys.stderr)
        return 1
    data.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for wav in wavs:
        text = known.get(wav.stem)
        if text is None:
            print(f"seed: no transcript for {wav.name}, skipped", file=sys.stderr)
            continue
        stem = data / f"ls-{wav.stem}"
        shutil.copyfile(wav, stem.with_suffix(".wav"))
        stem.with_suffix(".ref.txt").write_text(text + "\n", encoding="utf-8")
        stem.with_suffix(".raw.txt").write_text(text + "\n", encoding="utf-8")
        seeded += 1
    print(f"seeded {seeded} file(s) into {data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
