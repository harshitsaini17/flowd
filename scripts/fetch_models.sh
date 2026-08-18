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
if [[ -f "$MODELS_DIR/$LFM_FILE" ]]; then
  echo "    already present, skipping (models are never auto-upgraded)"
else
  curl -fL --progress-bar -o "$MODELS_DIR/$LFM_FILE.part" "$LFM_URL"
  mv "$MODELS_DIR/$LFM_FILE.part" "$MODELS_DIR/$LFM_FILE"
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
( cd "$REPO_ROOT" && uv run python - "$MODELS_DIR" "$LOCK" "$LFM_FILE" "$LFM_URL" <<'PY'
import json
import sys
from pathlib import Path

from flowd.models import sha256_file

models_dir, lock_path, lfm_file, lfm_url = (
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    sys.argv[3],
    sys.argv[4],
)
sources = {lfm_file: (lfm_url, "LFM Open License")}

entries = []
for name, (url, licence) in sorted(sources.items()):
    path = models_dir / name
    if not path.is_file():
        sys.exit(f"expected {path} to exist; run this script from the top")
    entries.append(
        {
            "name": name,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "url": url,
            "license": licence,
        }
    )

lock_path.write_text(json.dumps({"models": entries}, indent=2) + "\n")
print(f"    pinned {len(entries)} file(s)")
PY
)

echo "==> Done. Pinned hashes are in models.lock; the daemon verifies them at startup."
