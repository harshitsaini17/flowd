#!/usr/bin/env bash
# Install flowd for the current user from this checkout, then start it.
#
# Safe to re-run: every step either checks first or overwrites its own output.
# It never uses sudo. Missing system packages are reported with the command to
# install them, and the script stops there.
#
#   scripts/install.sh            install and start
#   scripts/install.sh --dry-run  print what would happen; change nothing
#
# FLOWD_LLM_THREADS overrides the llama-server thread count (default: physical
# cores minus two, spec 4).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/flowd"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
BIN_DIR="$HOME/.local/bin"
LLM_MODEL="sotto-cleanup-lfm25-350m-q4_k_m.gguf"
# Cores kept free for speech recognition and the rest of the desktop (spec 4).
RESERVED_CORES=2

DRY_RUN=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  -h | --help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

step() { printf '\n==> %s\n' "$*"; }
# Run a command, or only show it under --dry-run.
run() {
  if ((DRY_RUN)); then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

# --- 1. system packages -------------------------------------------------------
step "Checking system packages"
missing=()
need() { command -v "$1" >/dev/null 2>&1 || missing+=("$2"); }
need uv uv
need curl curl
need llama-server llama-cpp
need pw-cli pipewire
# Read once into a variable: `ldconfig -p | grep -q` would trip pipefail, since
# grep exits at the first match and ldconfig then dies of SIGPIPE.
libs="$(ldconfig -p 2>/dev/null || true)"
has_lib() { [[ "$libs" == *"$1"* ]]; }
has_lib libportaudio.so || missing+=(portaudio)
# One clipboard and one typing tool is enough; which ones depends on the session.
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  need wl-copy wl-clipboard
  command -v wtype >/dev/null 2>&1 || command -v ydotool >/dev/null 2>&1 || missing+=(wtype)
else
  need xclip xclip
  need xdotool xdotool
fi
if ((${#missing[@]})); then
  echo "    missing: ${missing[*]}"
  echo "    On Arch Linux: sudo pacman -S --needed ${missing[*]}"
  echo "    (other distributions: see Requirements in README.md)"
  if ((!DRY_RUN)); then exit 1; fi
else
  echo "    all present"
fi
if ! has_lib libgtk4-layer-shell.so; then
  echo "    note: gtk4-layer-shell not found; flowd runs without the preview overlay"
fi

# --- 2. Python environment and models ----------------------------------------
step "Installing flowd into $REPO_ROOT/.venv"
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  run uv venv "$REPO_ROOT/.venv"
fi
run uv pip install --python "$REPO_ROOT/.venv/bin/python" -e "$REPO_ROOT"

step "Fetching models (about 1.1 GB the first time; verified against models.lock)"
run "$REPO_ROOT/scripts/fetch_models.sh"

# --- 3. systemd units ---------------------------------------------------------
cores="$(lscpu -p=Core 2>/dev/null | grep -v '^#' | sort -u | wc -l)"
threads="${FLOWD_LLM_THREADS:-$((cores - RESERVED_CORES))}"
((threads >= 1)) || threads=1
llama_bin="$(command -v llama-server || echo /usr/bin/llama-server)"

# The shipped units carry three values that depend on this machine: where flowd
# was installed, where the model lives, and how many threads llama-server gets.
render_flowd() {
  sed "s|^ExecStart=.*|ExecStart=$REPO_ROOT/.venv/bin/flowd|" "$REPO_ROOT/systemd/flowd.service"
}
render_llm() {
  sed -e "s|^Environment=FLOWD_MODEL=.*|Environment=FLOWD_MODEL=$DATA_DIR/models/$LLM_MODEL|" \
    -e "s|^ExecStart=/usr/bin/llama-server |ExecStart=$llama_bin |" \
    -e "s|-t [0-9][0-9]*$|-t $threads|" \
    "$REPO_ROOT/systemd/flowd-llm.service"
}

step "Writing systemd units to $UNIT_DIR (llama-server threads: $threads)"
install_unit() { # name, renderer
  local dest="$UNIT_DIR/$1" new
  new="$("$2")"
  if ((DRY_RUN)); then
    printf '    would write %s:\n' "$dest"
    printf '%s\n' "$new" | grep -E '^(ExecStart|Environment)=|-t [0-9]+$' | sed 's/^/      /'
    return
  fi
  mkdir -p "$UNIT_DIR"
  # Keep a unit the user edited by hand, rather than silently replacing it.
  if [[ -f "$dest" ]] && ! printf '%s\n' "$new" | cmp -s - "$dest"; then
    cp "$dest" "$dest.bak"
    echo "    saved your previous $1 as $1.bak"
  fi
  printf '%s\n' "$new" >"$dest"
}
install_unit flowd.service render_flowd
install_unit flowd-llm.service render_llm

# --- 4. flowctl on PATH -------------------------------------------------------
step "Linking flowctl into $BIN_DIR"
link="$BIN_DIR/flowctl"
if [[ -e "$link" && ! -L "$link" ]]; then
  echo "    $link exists and is not a link; leaving it alone"
else
  run mkdir -p "$BIN_DIR"
  run ln -sfn "$REPO_ROOT/flowctl" "$link"
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "    note: $BIN_DIR is not on your PATH; add it so your hotkey can find flowctl" ;;
esac

# --- 5. start -----------------------------------------------------------------
step "Starting the services"
run systemctl --user daemon-reload
if [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
  # flowd types into windows, so it needs the compositor's environment.
  vars=()
  for v in WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP; do [[ -n "${!v:-}" ]] && vars+=("$v"); done
  run systemctl --user import-environment "${vars[@]}"
  run systemctl --user enable --now flowd-llm.service flowd.service
else
  echo "    no graphical session here: enabling only; flowd starts at your next login"
  run systemctl --user enable flowd-llm.service flowd.service
fi

# --- 6. what next -------------------------------------------------------------
step "Done. Bind a hotkey to flowctl:"
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
  echo "    ~/.config/hypr/hyprland.conf:"
  echo "      exec-once = systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP"
  echo "      bind = SUPER, D, exec, flowctl toggle"
elif [[ -n "${SWAYSOCK:-}" ]]; then
  echo "    ~/.config/sway/config:"
  echo "      bindsym \$mod+d exec flowctl toggle"
else
  echo "    bind 'flowctl toggle' to a key in your desktop's shortcut settings (see Hotkeys in README.md)"
fi
cat <<'NEXT'

    Try it now:  flowctl toggle, say something, flowctl toggle
    Status:      make status        Logs: make logs
    Uninstall:   make uninstall
NEXT
