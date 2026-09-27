#!/usr/bin/env bash
# Fetch flowd's models and regenerate models.lock (spec 3).
#
# Models are never auto-upgraded: a file already on disk is left alone. To move
# to a new revision, delete it and re-run, then review the models.lock diff --
# a changed hash means the upstream file changed.
set -euo pipefail

MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/flowd/models"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$REPO_ROOT/models.lock"

# Sotto, a dictation-cleanup fine-tune of LFM2.5-350M-Base (ADR 0006).
LFM_FILE="sotto-cleanup-lfm25-350m-q4_k_m.gguf"
LFM_URL="https://huggingface.co/baddu/sotto-cleanup-lfm25-350m-GGUF/resolve/main/$LFM_FILE"

# Parakeet TDT 0.6B v2, int8, as sherpa-onnx exports it (ADR 0011). Pinned to
# one revision of the repository, so the URLs never move under the lock.
PARAKEET_DIR="parakeet-tdt-0.6b-v2-int8"
PARAKEET_REV="1ab9323565ddb038682214b292f588070a538ce2"
PARAKEET_URL="https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/$PARAKEET_REV"
PARAKEET_FILES=(encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt)

mkdir -p "$MODELS_DIR/$PARAKEET_DIR"

echo "==> Fetching cleanup LLM (LFM Open License)"
# Which files this run actually downloaded. Only these may change a hash that is
# already pinned: anything else that no longer matches its pin has changed
# underneath us, and re-pinning it would bless a possibly-corrupt file.
DOWNLOADED=""
if [[ -f "$MODELS_DIR/$LFM_FILE" ]]; then
  echo "    already present, skipping (models are never auto-upgraded)"
else
  curl -fL --progress-bar -o "$MODELS_DIR/$LFM_FILE.part" "$LFM_URL"
  mv "$MODELS_DIR/$LFM_FILE.part" "$MODELS_DIR/$LFM_FILE"
  DOWNLOADED="$LFM_FILE"
fi

echo "==> Fetching the final STT model, Parakeet TDT 0.6B v2 (CC-BY-4.0, ~660 MB)"
for file in "${PARAKEET_FILES[@]}"; do
  target="$MODELS_DIR/$PARAKEET_DIR/$file"
  if [[ -f "$target" ]]; then
    echo "    $file already present, skipping"
  else
    curl -fL --progress-bar -o "$target.part" "$PARAKEET_URL/$file"
    mv "$target.part" "$target"
    DOWNLOADED="$DOWNLOADED $PARAKEET_DIR/$file"
  fi
done

echo "==> Warming the STT model cache (MIT code; English weights)"
# moonshine-voice fetches and CRC32C-verifies its own weights on first use, into
# its own cache -- not into MODELS_DIR. Warming it here means the daemon never
# downloads at runtime. The call is the one recorded in ADR 0001, pinned to the
# default model (ADR 0005); moonshine's own default for "en" is medium.
( cd "$REPO_ROOT" && uv run python -c '
from moonshine_voice import string_to_model_arch
from moonshine_voice.download import get_model_for_language
path, arch = get_model_for_language("en", string_to_model_arch("small-streaming"))
print(f"    cached {arch.name} at {path}")
' )

echo "==> Writing $LOCK"
# Regenerate the lock from what is actually on disk. Only files flowd fetches
# itself are pinned here; Moonshine's weights are the concern of its own
# verified downloader (ADR 0001), so duplicating their hashes would give flowd a
# second, staler source of truth.
#
# The building is `flowd.models.build_lock` rather than logic written out here,
# because a heredoc cannot be tested: the rule that a file which no longer
# matches its pin must not be re-pinned is the kind of thing that needs a test
# more than it needs to be inline.
( cd "$REPO_ROOT" && uv run python - "$MODELS_DIR" "$LOCK" "$LFM_FILE" "$LFM_URL" "$DOWNLOADED" \
    "$PARAKEET_DIR" "$PARAKEET_URL" "${PARAKEET_FILES[@]}" <<'PY'
import json
import sys
from pathlib import Path

from flowd.models import build_lock

models_dir, lock_path, lfm_file, lfm_url, downloaded, parakeet_dir, parakeet_url = (
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    sys.argv[3],
    sys.argv[4],
    sys.argv[5],
    sys.argv[6],
    sys.argv[7],
)
sources = {lfm_file: (lfm_url, "LFM Open License v1.0")}
for name in sys.argv[8:]:
    sources[f"{parakeet_dir}/{name}"] = (f"{parakeet_url}/{name}", "CC-BY-4.0")

try:
    doc = build_lock(
        models_dir,
        sources,
        lock_path=lock_path,
        downloaded=frozenset(n for n in downloaded.split() if n),
    )
except ValueError as exc:
    # A message, not a traceback: the reader has to act on this.
    sys.exit(f"    {exc}")

lock_path.write_text(json.dumps(doc, indent=2) + "\n")
print(f"    pinned {len(doc['models'])} file(s)")
PY
)

echo "==> Done. Pinned hashes are in models.lock; the daemon verifies them at startup."
