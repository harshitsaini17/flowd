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
# FLOWD_UI_BUILD=0 skips building flowd-ui, the indicator and preview popup;
# dictation works without it.
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
  -h | --help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# Package names differ between distributions. uv and llama-server are not in
# every Ubuntu release, so do not suggest an apt command that cannot work.
package_hint() {
  if command -v apt-get >/dev/null 2>&1; then
    local packages=() package
    for package in "$@"; do
      case "$package" in
        uv) echo "    Install uv: https://docs.astral.sh/uv/getting-started/installation/" ;;
        llama-cpp) echo "    Install llama-server: apt install llama.cpp (Ubuntu 25.10+), or build it (see Ubuntu / Debian in README.md)" ;;
        portaudio) packages+=(libportaudio2) ;;
        gtkmm-4.0) packages+=(g++ pkg-config libgtkmm-4.0-dev) ;;
        gtk4-layer-shell) packages+=(libgtk4-layer-shell-dev) ;;
        *) packages+=("$package") ;;
      esac
    done
    if ((${#packages[@]})); then
      echo "    On Ubuntu / Debian: sudo apt install ${packages[*]}"
    fi
  elif command -v pacman >/dev/null 2>&1; then
    echo "    On Arch Linux: sudo pacman -S --needed $*"
  else
    echo "    Install these system packages for your distribution: $* (see README.md)"
  fi
}

# Ubuntu reports ubuntu:GNOME; match a desktop token, not only an exact value.
GNOME_WAYLAND=0
desktop="${XDG_CURRENT_DESKTOP:-}"
if [[ -n "${WAYLAND_DISPLAY:-}" && ":${desktop,,}:" == *:gnome:* ]]; then
  GNOME_WAYLAND=1
fi

# --- 1. system packages -------------------------------------------------------
step "Checking system packages"
missing=()
need() { command -v "$1" >/dev/null 2>&1 || missing+=("$2"); }
need uv uv
need curl curl
# A llama-server built from source (Ubuntu 24.04) lives in ~/.local/bin.
command -v llama-server >/dev/null 2>&1 || [[ -x "$BIN_DIR/llama-server" ]] || missing+=(llama-cpp)
need pw-cli pipewire
# Read once into a variable: `ldconfig -p | grep -q` would trip pipefail, since
# grep exits at the first match and ldconfig then dies of SIGPIPE.
libs="$(ldconfig -p 2>/dev/null || true)"
has_lib() { [[ "$libs" == *"$1"* ]]; }
has_lib libportaudio.so || missing+=(portaudio)
# One clipboard and one typing tool is enough; which ones depends on the session.
if ((GNOME_WAYLAND)); then
  # Mutter does not implement the virtual-keyboard protocol used by wtype.
  need ydotool ydotool
  # With XWayland, flowd pastes through its X11 clipboard: Mutter has no
  # data-control protocol, so wl-copy must map a window and wait for focus.
  [[ -n "${DISPLAY:-}" ]] && need xclip xclip
elif [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  need wl-copy wl-clipboard
  command -v wtype >/dev/null 2>&1 || command -v ydotool >/dev/null 2>&1 || missing+=(wtype)
else
  need xclip xclip
  need xdotool xdotool
fi
if ((${#missing[@]})); then
  echo "    missing: ${missing[*]}"
  package_hint "${missing[@]}"
  if ((!DRY_RUN)); then exit 1; fi
else
  echo "    all present"
fi
# ydotool 0.x (Ubuntu 24.04's package) has no ydotoold, rejects the options
# flowd passes and still exits 0, so dictation would silently type nothing.
# Told apart by the bare command list, which needs no daemon: 0.x offers a
# `recorder` command that 1.x dropped. (`ydotool type --help` cannot be used:
# 1.x connects to ydotoold before parsing it and prints only a socket error.)
if command -v ydotool >/dev/null 2>&1; then
  ydotool_commands="$(ydotool 2>&1 || true)"
  if [[ "$ydotool_commands" == *recorder* ]]; then
    echo "    ydotool is older than 1.0 (0.x); flowd needs ydotool 1.x."
    echo "    Install it from https://github.com/ReimuNotMoe/ydotool (see Ubuntu 24.04 in README.md)"
    if ((GNOME_WAYLAND && !DRY_RUN)); then exit 1; fi
  fi
fi
if ((GNOME_WAYLAND)); then
  echo "    GNOME Wayland needs ydotoold running and /dev/uinput access."
  echo "    See the GNOME / Ubuntu setup in README.md; no device permissions are changed here."
fi

# --- 2. Python environment and models ----------------------------------------
step "Installing flowd into $REPO_ROOT/.venv"
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  run uv venv --python '>=3.11' "$REPO_ROOT/.venv"
fi
run uv pip install --python "$REPO_ROOT/.venv/bin/python" -e "$REPO_ROOT"

step "Fetching models (about 1.1 GB the first time; verified against models.lock)"
run "$REPO_ROOT/scripts/fetch_models.sh"

# Not fatal either way: without flowd-ui there is no indicator or preview, and
# dictation works the same.
step "Building flowd-ui"
if ((GNOME_WAYLAND)) && [[ -z "${DISPLAY:-}" ]]; then
  echo "    note: flowd-ui not built (GNOME Wayland without XWayland); dictation uses ydotool"
elif [[ "${FLOWD_UI_BUILD:-1}" != 0 ]] && command -v cmake >/dev/null 2>&1 &&
  command -v g++ >/dev/null 2>&1 &&
  pkg-config --exists gtkmm-4.0 gtk4-layer-shell-0 2>/dev/null; then
  run cmake -S "$REPO_ROOT/ui" -B "$REPO_ROOT/build/ui" -DCMAKE_BUILD_TYPE=Release
  run cmake --build "$REPO_ROOT/build/ui" -j
else
  echo "    note: flowd-ui not built (needs cmake gtkmm-4.0 gtk4-layer-shell); flowd runs without the indicator"
  package_hint cmake gtkmm-4.0 gtk4-layer-shell
  echo "    If gtk4-layer-shell is not packaged by your release, skip the optional UI (see README.md)."
fi

# --- 3. systemd units ---------------------------------------------------------
cores="$(lscpu -p=Core 2>/dev/null | grep -v '^#' | sort -u | wc -l)"
threads="${FLOWD_LLM_THREADS:-$((cores - RESERVED_CORES))}"
((threads >= 1)) || threads=1
llama_bin="$(command -v llama-server || true)"
if [[ -z "$llama_bin" && -x "$BIN_DIR/llama-server" ]]; then llama_bin="$BIN_DIR/llama-server"; fi
llama_bin="${llama_bin:-/usr/bin/llama-server}"
# `-cram` (prompt cache size) is newer than some distribution packages, e.g.
# Ubuntu 25.10's llama.cpp, which would refuse to start with it. It only saves
# memory, so drop it there.
cram_flag="-cram 0 "
# Captured first, for the same pipefail reason as the ldconfig check above.
if [[ -x "$llama_bin" ]]; then
  llama_help="$("$llama_bin" --help 2>&1 || true)"
  [[ "$llama_help" == *--cache-ram* ]] || cram_flag=""
fi

# The shipped units carry three values that depend on this machine: where flowd
# was installed, where the model lives, and how many threads llama-server gets.
render_flowd() {
  sed "s|^ExecStart=.*|ExecStart=$REPO_ROOT/.venv/bin/flowd|" "$REPO_ROOT/systemd/flowd.service"
}
render_llm() {
  sed -e "s|^Environment=FLOWD_MODEL=.*|Environment=FLOWD_MODEL=$DATA_DIR/models/$LLM_MODEL|" \
    -e "s|^ExecStart=/usr/bin/llama-server |ExecStart=$llama_bin |" \
    -e "s|-t [0-9][0-9]*$|-t $threads|" \
    -e "s|-cram 0 |$cram_flag|" \
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
# llama-server exits at once if its port is taken, and systemd then restarts
# it every 2 s forever while flowd quietly uses basic cleanup. Say so here.
if command -v ss >/dev/null 2>&1 && ss -Hltn 'sport = :8177' 2>/dev/null | grep -q .; then
  if ! systemctl --user is-active --quiet flowd-llm.service 2>/dev/null; then
    echo "    warning: port 8177 is already in use; flowd-llm will not start until it is free"
    echo "    (find the process with: ss -ltnp 'sport = :8177')"
  fi
fi
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
