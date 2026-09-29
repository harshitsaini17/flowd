#!/usr/bin/env bash
# Stop flowd and remove what scripts/install.sh put outside this checkout.
#
#   scripts/uninstall.sh          stop the services, remove the units and the flowctl link
#   scripts/uninstall.sh --purge  also delete the downloaded models (about 1.1 GB)
#
# Your config (~/.config/flowd) and this checkout are always kept.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/flowd"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
LINK="$HOME/.local/bin/flowctl"

PURGE=0
case "${1:-}" in
  "") ;;
  --purge) PURGE=1 ;;
  -h | --help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

echo "==> Stopping and disabling the services"
systemctl --user disable --now flowd.service flowd-llm.service 2>/dev/null || true

echo "==> Removing the units from $UNIT_DIR"
for unit in flowd.service flowd-llm.service; do
  rm -f "$UNIT_DIR/$unit" "$UNIT_DIR/$unit.bak"
done
systemctl --user daemon-reload
systemctl --user reset-failed flowd.service flowd-llm.service 2>/dev/null || true

# Only a link into this checkout is ours to remove.
if [[ -L "$LINK" && "$(readlink "$LINK")" == "$REPO_ROOT/flowctl" ]]; then
  echo "==> Removing $LINK"
  rm -f "$LINK"
fi

if ((PURGE)); then
  echo "==> Deleting the models in $DATA_DIR/models"
  rm -r -- "$DATA_DIR/models" 2>/dev/null || true
else
  echo "    models kept in $DATA_DIR/models (use --purge to delete them)"
fi
echo "    config kept in ${XDG_CONFIG_HOME:-$HOME/.config}/flowd"
