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

LFM_FILE="LFM2.5-350M-QAD-Q4_0.gguf"
LFM_URL="https://huggingface.co/LiquidAI/LFM2.5-350M-GGUF/resolve/main/$LFM_FILE"

mkdir -p "$MODELS_DIR"

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

echo "==> Warming the STT model cache (MIT code; English weights)"
# moonshine-voice fetches and CRC32C-verifies its own weights on first use, into
# its own cache -- not into MODELS_DIR. Warming it here means the daemon never
# downloads at runtime. The call is the one recorded in ADR 0001.
( cd "$REPO_ROOT" && uv run python -c '
from moonshine_voice.download import get_model_for_language
path, arch = get_model_for_language("en")
print(f"    cached {arch.name} at {path}")
' )

echo "==> Writing $LOCK"
# Regenerate the lock from what is actually on disk. Only files flowd fetches
# itself are pinned here; the STT weights are the concern of moonshine's own
# verified downloader (ADR 0001), so duplicating their hashes would give flowd a
# second, staler source of truth.
#
# The building is `flowd.models.build_lock` rather than logic written out here,
# because a heredoc cannot be tested: the rule that a file which no longer
# matches its pin must not be re-pinned is the kind of thing that needs a test
# more than it needs to be inline.
( cd "$REPO_ROOT" && uv run python - "$MODELS_DIR" "$LOCK" "$LFM_FILE" "$LFM_URL" "$DOWNLOADED" <<'PY'
import json
import sys
from pathlib import Path

from flowd.models import build_lock

models_dir, lock_path, lfm_file, lfm_url, downloaded = (
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    sys.argv[3],
    sys.argv[4],
    sys.argv[5],
)
sources = {lfm_file: (lfm_url, "LFM Open License")}

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
