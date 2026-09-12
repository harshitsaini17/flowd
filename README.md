# flowd

Local, offline, streaming dictation for Linux.

Press a hotkey, speak, and watch the text appear live in a small overlay. When
you release, the transcript is typed into whatever window you had focused.

Everything runs on your machine. flowd makes no network calls at runtime, has no
telemetry and no update check, and writes neither audio nor transcript text to
disk unless you explicitly turn that on.

## Status

flowd is under active development. What works today:

| | |
|---|---|
| Hotkey → speak → text lands in the focused window | **works** |
| Live preview overlay while you speak | **works** |
| Streaming transcription with incremental commits | **works** |
| Per-session latency metrics (`flowctl stats`) | **works** |
| LLM cleanup of filler words, punctuation and casing | **not yet** — phase 3 |
| Per-application modes, personal vocabulary | **not yet** — phase 5 |

Transcripts currently get rule-based tidying only: sentence casing, spacing
around punctuation, a terminal full stop. The local language model that removes
"um" and repairs half-finished sentences is the next phase. The
[`flowd-llm`](systemd/flowd-llm.service) unit ships now so the model is in place
when that lands.

The full architecture and build specification is [`docs/spec.md`](docs/spec.md);
decisions that diverge from it are recorded in
[`docs/decisions/`](docs/decisions/), and each phase has a report in
[`docs/reports/`](docs/reports/). The smaller judgement calls made while building
phases 0-2 — the ones too small for a decision record but not obvious from the
code — are collected in
[`docs/reports/phase-0-2-rulings.md`](docs/reports/phase-0-2-rulings.md).

## Requirements

A Linux desktop, Python 3.11 or newer, and a CPU with AVX2. AVX-512 is not
required. flowd was developed on a 6-core Ryzen 5 5600H, where streaming
transcription runs at about 1.05× realtime — enough to keep up with live speech,
with little headroom. On a slower machine, set `stt.model` to
`small-streaming-en` or `tiny-streaming-en` in your config.

On Arch Linux:

```bash
sudo pacman -S --needed pipewire pipewire-pulse portaudio llama-cpp \
  wl-clipboard wtype ydotool xclip xdotool gtk4 gtk4-layer-shell python-gobject
```

The package is `llama-cpp` from `extra`, not `llama.cpp` from the AUR.

Not all of these are needed at once. `wl-clipboard` and `wtype` are the Wayland
path; `xclip` and `xdotool` are the X11 path; `ydotool` is a fallback for
applications that ignore the other two. `gtk4`, `gtk4-layer-shell` and
`python-gobject` are only for the preview overlay, which flowd disables cleanly
if they are missing.

On other distributions the names differ but the set does not: PipeWire (or
PulseAudio), PortAudio, llama.cpp, the clipboard and typing tools for your
session type, and GTK4 with the layer-shell library.

## Install

```bash
git clone https://github.com/harshitsaini17/flowd
cd flowd
uv venv
uv pip install -e .
scripts/fetch_models.sh
```

`fetch_models.sh` downloads the cleanup language model, verifies it against the
SHA-256 pinned in [`models.lock`](models.lock), and warms the speech model
cache. It never upgrades a model behind your back: if a checksum does not match,
it stops and tells you. About 480 MB in total.

flowd refuses to start if a pinned model fails verification. Run
`scripts/fetch_models.sh` again to repair it.

## Run

flowd expects to run as a user service, not as root.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/flowd.service systemd/flowd-llm.service ~/.config/systemd/user/
```

Edit `flowd.service` so `ExecStart` points at the virtualenv you just created —
the shipped path (`%h/.local/share/flowd/.venv/bin/flowd`) is a suggestion, not
a guess about where you cloned the repo.

Then set `-t` in `flowd-llm.service` to your physical cores minus two, which
leaves a core for speech recognition and a core for everything else. systemd
cannot count them for you, and the shipped `4` suits a 6-core machine:

```bash
lscpu -p=Core | grep -v '^#' | sort -u | wc -l
```

If you have moved `XDG_DATA_HOME`, edit that unit's `FLOWD_MODEL` path too —
`scripts/fetch_models.sh` follows the variable and the unit file cannot.

```bash
systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP
systemctl --user enable --now flowd-llm flowd
```

The `import-environment` step matters. A user service started before you log in
inherits none of your compositor's environment, and without
`WAYLAND_DISPLAY`/`DISPLAY` flowd cannot reach the clipboard, cannot type into a
window, and cannot show the overlay — it will start and then fail at every
injection. Run it once per login, or add it to your compositor's startup config.

Check it came up:

```bash
flowctl status
```

## Hotkeys

flowd does not grab keys itself. Your compositor already does that well, and a
daemon that competes with it for a global hotkey is a daemon that fights your
desktop. Bind `flowctl` instead.

Two styles: **toggle** (press to start, press again to stop) and
**push-to-talk** (hold to speak, release to stop). Push-to-talk needs the
release edge, which not every compositor exposes.

**Hyprland** — `~/.config/hypr/hyprland.conf`:

```ini
# Toggle
bind = SUPER, D, exec, flowctl toggle

# Or push-to-talk: bindr fires on release
bind  = SUPER, D, exec, flowctl start
bindr = SUPER, D, exec, flowctl stop
```

**Sway** — `~/.config/sway/config`:

```
# Toggle
bindsym $mod+d exec flowctl toggle

# Or push-to-talk
bindsym $mod+d exec flowctl start
bindsym --release $mod+d exec flowctl stop
```

**KDE Plasma** — System Settings → Shortcuts → Add New → Command/URL, with the
command `flowctl toggle`. Plasma's custom shortcuts fire on press only, so
push-to-talk is not available this way; use toggle.

**GNOME** — custom keybindings live in `gsettings`:

```bash
path=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flowd/
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings \
  "['$path']"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \
  name 'flowd dictation'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \
  command 'flowctl toggle'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \
  binding '<Super>d'
```

On GNOME under Wayland the preview overlay is **disabled**, and flowd logs why
when it starts. GNOME's compositor does not implement `wlr-layer-shell`, the
protocol that lets a window promise never to take keyboard focus. An overlay
that might take focus would steal it from the window you are dictating into, and
your text would land in the overlay instead of your editor. Dictation itself
works normally; you just do not get the live preview. GNOME under X11 is fine.

**X11, any window manager** — with `sxhkd`:

```
super + d
    flowctl toggle
```

`flowctl` is a plain stdlib Python script with no imports beyond the standard
library, so a keypress does not pay for loading numpy. It answers in about 20 ms.

## ydotool setup (optional)

Most applications accept text from the clipboard or from `wtype`/`xdotool`.
A few — some Electron apps, some games, some terminals in exotic modes — accept
only kernel-level input events, which is what `ydotool` provides.

`ydotool` needs write access to `/dev/uinput`. **flowd will not set this up for
you.** It touches device permissions and a system group, and a dictation daemon
has no business editing udev rules or running `sudo`. If you want the
`ydotool` backend, do it yourself, deliberately:

```bash
sudo groupadd -f uinput
sudo usermod -aG uinput "$USER"

sudo tee /etc/udev/rules.d/80-uinput.rules >/dev/null <<'RULE'
KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"
RULE

sudo udevadm control --reload-rules
sudo udevadm trigger
systemctl --user enable --now ydotoold
```

Log out and back in for the group change to take effect. Understand what this
grants before you run it: membership in that group lets any process you run
synthesise keyboard and mouse input for your whole session.

If you skip this, flowd simply never selects the `ydotool` backend. Remove it
from `inject.order` in your config to stop flowd trying.

## Configuration

flowd reads `~/.config/flowd/config.toml` if it exists, and otherwise uses
built-in defaults; there is nothing you must configure to start. Every tunable
and its default is listed in [`docs/spec.md`](docs/spec.md) section 8.

```toml
[hotkey]
mode = "toggle"        # or "ptt"

[audio]
device = "default"
max_session_s = 300

[stt]
model = "small-streaming-en"    # or medium-streaming-en, tiny-streaming-en (ADR 0005)

[inject]
order = ["clipboard", "wtype", "ydotool", "xdotool"]

[overlay]
enabled = true
```

`flowctl reload` applies a changed config without restarting. A config that
fails validation is rejected and the running one is kept, so a typo cannot take
dictation down mid-session.

## Troubleshooting

**The text landed nowhere.** It is not lost. `flowctl last` prints the most
recent transcript, so you can paste it by hand. Then find out which backend
failed: `journalctl --user -u flowd -n 50`. The usual cause is a missing tool
for your session type — Wayland needs `wl-clipboard` or `wtype`, X11 needs
`xclip` or `xdotool`.

**No microphone.** flowd reports the error and sends a desktop notification
rather than failing silently. Check `flowctl status`, then that PipeWire is
running (`systemctl --user status pipewire`) and that your input device is not
held exclusively by another application. Set `audio.device` if the default is
not the microphone you meant.

**Nothing happens on the hotkey.** Confirm the daemon is up with
`flowctl status`. If that says flowd is not running while the service is
active, the two are looking at different sockets — usually because the service
started without `XDG_RUNTIME_DIR`. Re-run the `import-environment` step.

**The overlay is missing.** On GNOME/Wayland this is deliberate; see the
hotkeys section. Elsewhere, check that `gtk4-layer-shell` and `python-gobject`
are installed, and look for the overlay's reason in the log. The overlay is a
separate process on purpose: if it crashes, dictation keeps working.

**A model fails verification.** Run `scripts/fetch_models.sh`. flowd refuses to
start on a hash mismatch rather than running a model it cannot identify.

**Logs, in general.**

```bash
journalctl --user -u flowd -u flowd-llm -f
```

Raise the detail with `[logging] level = "debug"`, or run the daemon in the
foreground with `flowd --log-level debug`.

**Reporting a bug.** Include the output of `flowd --version`, your compositor
and session type, and the last 50 journal lines. Please do not paste transcript
text you would not want to be public.

## Privacy

flowd is built to be boring about your data.

- **No network at runtime.** The only thing listening is `llama-server`, on
  `127.0.0.1`. Model downloads are a separate, explicit step you run yourself.
- **No transcripts on disk by default.** `logging.log_transcripts` is `false`,
  and turning it on is the only way flowd writes what you said to a file.
  Dictation contains passwords, addresses and private messages; the default
  assumes that.
- **No audio on disk.** Recorded audio exists in memory for the length of a
  session and is then gone. The only files flowd will ever read are ones you
  pass to `--replay` yourself.
- **Metrics contain timings, not text.** `~/.local/state/flowd/metrics.jsonl`
  gets one line per session: durations, word count, which backend was used. No
  transcript. This is what `flowctl stats` summarises.
- **Your clipboard is put back.** The clipboard injection backend snapshots what
  was there, pastes, and restores it. If the clipboard holds something that is
  not text — an image, a file list — flowd refuses to overwrite it and falls
  through to a typing backend instead.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports about a compositor or
application flowd handles badly are especially useful: the injection path is
where the hard cases live, and no one has every desktop.

## License

flowd is MIT licensed. See [`LICENSE`](LICENSE).

The models are separately licensed and are **not** covered by flowd's licence:

- **Moonshine** (speech recognition) — the `moonshine-voice` package is MIT, and
  the English weights flowd uses ship under the same permissive terms.
  Moonshine's **non-English** weights are released under a Moonshine Community
  Licence that forbids commercial use. flowd is English-only today, so it stays
  on the permissive path; if you point `stt.model` at a non-English model, that
  licence is yours to honour.
- **LFM2.5-350M** (cleanup, phase 3) — see the model card linked in
  [`models.lock`](models.lock) for its terms.

`models.lock` records the exact revision and SHA-256 of every pinned file.
