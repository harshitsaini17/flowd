#!/usr/bin/env bash
# Fetch a few LibriSpeech utterances for `flowd --replay` evaluation.
#
# LibriSpeech is CC BY 4.0: the underlying LibriVox readings are public domain,
# but the corpus itself requires attribution. These files are NOT redistributed
# with flowd -- eval/audio/ is gitignored -- so every user fetches their own copy
# and the attribution notice is written alongside them.
#
# The upstream tarball is ~350 MB and only a handful of utterances are converted.
set -euo pipefail

DEST="$(cd "$(dirname "$0")/.." && pwd)/eval/audio"
TARBALL="$DEST/test-clean.tar.gz"
UTTERANCES="${FLOWD_EVAL_UTTERANCES:-5}"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found (pacman -S ffmpeg)." >&2; exit 1; }

mkdir -p "$DEST"

cat > "$DEST/ATTRIBUTION.txt" <<'TXT'
Audio fetched by scripts/fetch_eval_audio.sh is from LibriSpeech
(https://www.openslr.org/12/), licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/).

V. Panayotov, G. Chen, D. Povey and S. Khudanpur, "Librispeech: an ASR corpus
based on public domain audio books", ICASSP 2015.

These files are NOT redistributed with flowd: eval/audio/ is gitignored.
TXT

echo "==> Fetching LibriSpeech test-clean (CC BY 4.0, ~350 MB)"
if [[ -f "$TARBALL" ]]; then
  echo "    already present, skipping download"
else
  curl -fL --progress-bar -o "$TARBALL.part" \
    "https://www.openslr.org/resources/12/test-clean.tar.gz"
  mv "$TARBALL.part" "$TARBALL"
fi

echo "==> Extracting"
tar -xzf "$TARBALL" -C "$DEST"

echo "==> Converting $UTTERANCES utterance(s) to 16 kHz mono WAV for --replay"
converted=0
while IFS= read -r flac; do
  out="$DEST/$(basename "${flac%.flac}").wav"
  ffmpeg -loglevel error -y -i "$flac" -ar 16000 -ac 1 "$out"
  echo "    $(basename "$out")"
  converted=$(( converted + 1 ))
done < <(find "$DEST" -name '*.flac' | sort | head -n "$UTTERANCES")

(( converted > 0 )) || { echo "No .flac files found under $DEST." >&2; exit 1; }

echo "==> Done. $converted WAV file(s) in $DEST. See $DEST/ATTRIBUTION.txt"
