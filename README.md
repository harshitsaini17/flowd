<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-wordmark-dark.svg">
  <img src="docs/assets/logo-wordmark.svg" alt="flowd" width="320">
</picture>

**Local, offline, streaming dictation for Linux.**

Press a hotkey, speak, and watch your words appear live. Release, and clean,
punctuated text is typed into whatever window you had focused.

[![CI](https://github.com/harshitsaini17/flowd/actions/workflows/ci.yml/badge.svg)](https://github.com/harshitsaini17/flowd/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)
![Wayland and X11](https://img.shields.io/badge/session-Wayland%20%7C%20X11-lightgrey.svg)

[Features](#features) ·
[Installation](#installation) ·
[Usage](#usage) ·
[Configuration](#configuration) ·
[Troubleshooting](#troubleshooting) ·
[Privacy](#privacy)

</div>

<!-- DEMO: replace this comment with the GitHub video URL on its own line, e.g.
https://github.com/user-attachments/assets/<id>
-->

---

## Why flowd

- **Private by design.** Speech recognition and text cleanup both run on your
  machine. No network calls at runtime, no telemetry, no update check, and no
  audio or transcripts written to disk unless you turn that on.
- **Fast.** Text streams in while you speak, and dictation never waits more than
  800 ms on the language model after you stop.
- **Works where you type.** Editors, browsers, chat apps and terminals, on
  Wayland and X11, through your compositor's own hotkeys.

## Features

| Feature | What it does |
|---|---|
| Live preview | A small indicator pill at the bottom of the screen and a popup that shows the text as you speak |
| Streaming transcription | Moonshine streams a draft while you talk; Parakeet commits the final text |
| Smart cleanup | A small local LLM removes fillers, fixes punctuation and casing, and applies self-corrections ("five, no wait, six" → "6") |
| Guardrails | Model output is checked for invented content; if it fails, or the model is slow or down, rule-based tidying is pasted instead |
| Per-application modes | `code`, `chat`, `email` and `default`, picked from the focused window. Terminals paste with Ctrl+Shift+V |
| Personal vocabulary | Bias recognition toward your acronyms and names, and fix recurring mishearings |
| Full-rewrite pass | `flowctl stop --rewrite` runs one more pass over the whole text for corrections that span sentences |
| Settings page | A local browser page for config, vocabulary, a microphone test and stats |
| Robust | Recovers from a lost microphone, suspend and an audio server restart; a crashed indicator never stops dictation |
| Clipboard safe | Your clipboard is restored after pasting, and never overwritten if it holds an image or files |
| Metrics | `flowctl stats` summarises per-session latency, with timings only, never text |

## How it works

```
 hotkey ──► flowctl ──► flowd daemon
                          │
   microphone ──► Moonshine (streaming draft) ──► live popup (flowd-ui)
                          │
                          ▼
                 Parakeet (final transcript)
                          │
                          ▼
           local LLM cleanup (flowd-llm, llama.cpp)
           └─ guardrails, fallback to rule-based tidying
                          │
                          ▼
     injection: clipboard · wtype · ydotool · xdotool ──► focused window
```

`flowd` runs as a user service. `flowctl` is a tiny stdlib-only client your
hotkey calls; it answers in about 20 ms. `flowd-llm` is a `llama-server` bound
to `127.0.0.1`. `flowd-ui` is a separate process, so if it crashes, dictation
keeps working.

The full architecture is in [`docs/spec.md`](docs/spec.md), edge cases in
[`docs/edge-cases.md`](docs/edge-cases.md), and design decisions in
[`docs/decisions/`](docs/decisions/).

## Installation

### Requirements

- A Linux desktop (Hyprland, Sway, KDE Plasma, GNOME or any X11 window manager)
- Python 3.11 or newer
- A CPU with AVX2 (AVX-512 is not required)
- About 1.1 GB of disk space for the models

flowd was developed on a 6-core Ryzen 5 5600H, where streaming transcription
runs at about 1.05× realtime. On a slower machine, set `stt.model` to
`small-streaming-en` or `tiny-streaming-en` (see [Configuration](#configuration)).

### Quick install (Arch Linux)

```bash
sudo pacman -S --needed uv pipewire pipewire-pulse portaudio llama-cpp \
  wl-clipboard wtype cmake gtkmm-4.0 gtk4-layer-shell
git clone https://github.com/harshitsaini17/flowd
cd flowd
make install
```

The package is `llama-cpp` from `extra`, not `llama.cpp` from the AUR. For X11,
also install `xclip` and `xdotool`.

`make install`:

- sets up a virtualenv in the checkout,
- downloads the models and verifies them against [`models.lock`](models.lock),
- installs the `flowd` and `flowd-llm` user services, tuned to your CPU,
- puts `flowctl` on your `PATH` and starts flowd.

It never uses `sudo`, stops with a clear message if a system package is missing,
and is safe to run again. It finishes by printing the hotkey line for your
compositor. Continue with [Set up a hotkey](#1-set-up-a-hotkey).

<details>
<summary><b>Which packages do I need?</b></summary>

| Package | Purpose |
|---|---|
| `pipewire`, `pipewire-pulse`, `portaudio` | Microphone capture |
| `llama-cpp` | Runs the local cleanup model |
| `wl-clipboard`, `wtype` | Typing and pasting on Wayland |
| `xclip`, `xdotool` | Typing and pasting on X11 |
| `ydotool` | Optional fallback for apps that ignore the others ([setup](#ydotool-optional)) |
| `cmake`, `gtkmm-4.0`, `gtk4-layer-shell` | Optional: build `flowd-ui`, the indicator and popup |

Without the `flowd-ui` packages the installer skips it, and dictation works the
same with no indicator.

**Other distributions:** the names differ but the set does not: PipeWire (or
PulseAudio), PortAudio, llama.cpp, the clipboard and typing tools for your
session type, and, for the indicator, CMake, a C++ compiler, gtkmm 4 and
gtk4-layer-shell.

</details>

<details>
<summary><b>Manual install</b> (what <code>make install</code> does, step by step)</summary>

```bash
git clone https://github.com/harshitsaini17/flowd
cd flowd
uv venv
uv pip install -e .
scripts/fetch_models.sh
```

`fetch_models.sh` downloads the cleanup model and the Parakeet speech model,
verifies them against the SHA-256 pinned in [`models.lock`](models.lock), and
warms the Moonshine model cache. It never upgrades a model behind your back: if
a checksum does not match, it stops. flowd refuses to start if a pinned model
fails verification; run the script again to repair it.

Install the user services (flowd must not run as root):

```bash
mkdir -p ~/.config/systemd/user
cp systemd/flowd.service systemd/flowd-llm.service ~/.config/systemd/user/
```

Then edit them:

- In `flowd.service`, point `ExecStart` at your virtualenv. The shipped path
  (`%h/.local/share/flowd/.venv/bin/flowd`) is only a suggestion.
- In `flowd-llm.service`, set `-t` to your physical cores minus two. The shipped
  `4` suits a 6-core machine. Count your cores with:

  ```bash
  lscpu -p=Core | grep -v '^#' | sort -u | wc -l
  ```

- If you moved `XDG_DATA_HOME`, update the `FLOWD_MODEL` path in
  `flowd-llm.service` too.

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable flowd-llm flowd
systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP
systemctl --user start flowd-llm flowd
flowctl status
```

`flowd.service` belongs to `graphical-session.target`: it starts after you log
in and stops when you log out. `flowd-llm` starts with it.

flowd needs your compositor's environment to reach the clipboard, type into
windows and show the indicator. Most compositors import it at login. If yours
does not, add the `import-environment` line to its startup config. On Hyprland:

```ini
exec-once = systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP
```

If flowd fails to start, systemd retries, and gives up after five failures in
two minutes. A model hash mismatch is not retried.

</details>

### Uninstall

```bash
make uninstall              # stop flowd and remove its services; keeps models and config
scripts/uninstall.sh --purge  # also delete the models
```

## Usage

### 1. Set up a hotkey

flowd does not grab keys itself; your compositor already does that well. Bind
`flowctl` instead. There are two styles:

- **Toggle:** press to start, press again to stop.
- **Push-to-talk:** hold to speak, release to stop. This needs a compositor that
  exposes key release.

**Hyprland** (`~/.config/hypr/hyprland.conf`):

```ini
# Toggle
bind = SUPER, D, exec, flowctl toggle

# Or push-to-talk: bindr fires on release
bind  = SUPER, D, exec, flowctl start
bindr = SUPER, D, exec, flowctl stop
```

<details>
<summary><b>Sway</b></summary>

`~/.config/sway/config`:

```
# Toggle
bindsym $mod+d exec flowctl toggle

# Or push-to-talk
bindsym $mod+d exec flowctl start
bindsym --release $mod+d exec flowctl stop
```

</details>

<details>
<summary><b>KDE Plasma</b></summary>

System Settings → Shortcuts → Add New → Command/URL, with the command
`flowctl toggle`. Plasma's custom shortcuts fire on press only, so use toggle.

</details>

<details>
<summary><b>GNOME</b></summary>

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

On GNOME under Wayland the indicator and preview popup are **disabled**, and
flowd logs why at startup. GNOME's compositor does not implement
`wlr-layer-shell`, the protocol that lets a window promise never to take
keyboard focus. Without it, the popup could steal focus and your text would land
in the popup instead of your editor. Dictation itself works normally. GNOME
under X11 is fine.

</details>

<details>
<summary><b>X11 (any window manager, with sxhkd)</b></summary>

```
super + d
    flowctl toggle
```

</details>

**Optional second hotkey for a full rewrite.** `flowctl stop --rewrite` ends a
dictation, then sends the whole text (up to 300 words) through one more pass of
the local model, which can fix corrections that span sentences. It adds up to
`[llm] timeout_ms` before the text lands, must pass the same guardrails, and is
skipped in code mode.

```ini
bind = SUPER SHIFT, D, exec, flowctl stop --rewrite
```

### 2. Dictate

1. Focus the window you want to type into.
2. Press the hotkey. The indicator lights up and the popup shows your words live.
3. Speak naturally. Fillers ("um", "uh") and self-corrections are cleaned up.
4. Press the hotkey again (or release it, for push-to-talk). The text is typed
   into the focused window.

Changed your mind? `flowctl cancel` discards the current dictation. If the text
went missing, `flowctl last` prints the most recent transcript.

### `flowctl` commands

| Command | What it does |
|---|---|
| `flowctl toggle` | Start dictating, or stop if already dictating |
| `flowctl start` / `flowctl stop` | Start or stop explicitly (push-to-talk) |
| `flowctl stop --rewrite` | Stop, then run the full-rewrite pass |
| `flowctl cancel` | Discard the current dictation without typing anything |
| `flowctl status` | Show whether flowd is running and what it is doing |
| `flowctl last` | Print the most recent transcript |
| `flowctl stats` | Summarise per-session latency metrics |
| `flowctl reload` | Apply a changed config or vocabulary without restarting |
| `flowctl settings` | Open the settings page in your browser |

### `make` commands

| Command | What it does |
|---|---|
| `make status` | Is flowd running, and what is it doing |
| `make logs` | Follow the daemon log |
| `make restart` | Restart after a `git pull` or a config change |
| `make stop` / `make start` | Stop or start the services |
| `make run` | Run flowd in this terminal instead (stop the service first) |
| `make check` | Idle memory and CPU, and that flowd is not holding the microphone |
| `make ui` | Build the indicator and popup (`flowd-ui`) |
| `make uninstall` | Stop flowd and remove its services; keeps models and config |
| `make test` | Linters, type checks and tests, as CI runs them |

`make` on its own lists them all.

## Configuration

There is nothing you must configure to start. flowd reads
`~/.config/flowd/config.toml` if it exists and otherwise uses built-in defaults.
Every option and its default is listed in [`docs/spec.md`](docs/spec.md)
section 8.

Apply changes with `flowctl reload`. A config that fails validation is rejected
and the running one is kept, so a typo cannot take dictation down mid-session.

### Settings page

```bash
flowctl settings
```

Opens a page in your browser for everything in `config.toml` and `vocab.toml`:
live status, a microphone test, personal vocabulary and stats. Changes are saved
straight back to the files.

The daemon serves it on `127.0.0.1:8178` only. `flowctl settings` hands your
browser a fresh sign-in token through a launcher file only you can read, never
on a command line, so nothing else on the machine can open it. Set
`[settings] enabled = false` to turn it off; dictation is unaffected.

### Example config

```toml
[hotkey]
mode = "toggle"        # or "ptt"

[audio]
device = "default"
max_session_s = 300

[stt]
model = "small-streaming-en"    # or medium-streaming-en, tiny-streaming-en
final_model = "parakeet-tdt-0.6b-v2-int8"  # commits the text; "" lets Moonshine commit

[inject]
order = ["clipboard", "wtype", "ydotool", "xdotool"]

[modes]                # app id → mode; ids match case-insensitively
"kiro" = "code"
"firefox" = "default"

[ui]
enabled = true         # false: no indicator and no popup
indicator = true       # the pill at the bottom edge; false shows the popup only while dictating
theme = "system"       # or "light", "dark"
max_lines = 4          # lines of text in the popup (1-6)
fade_ms = 1000         # how long the popup stays after the text is typed
footer = true          # mode and app under the text
notify_on_finish = false
hotkey_label = ""      # shown in hints, e.g. "Super D"
```

> [!NOTE]
> The `[ui]` section used to be called `[overlay]`. flowd still reads
> `[overlay]` for one more release and logs a deprecation warning.

### Per-application modes

When dictation starts, flowd reads the focused window's app id (via
`hyprctl activewindow`, `swaymsg -t get_tree` or `xdotool`) and picks a mode:

| Mode | Behaviour |
|---|---|
| `code` | No LLM. Fillers are removed and everything else is pasted as said. Default for terminals, which always paste with Ctrl+Shift+V |
| `chat` | Normal cleanup, without the final period |
| `email`, `default` | Normal cleanup |

The built-in table covers common editors, chat apps and mail clients. Add your
own under `[modes]`. Browsers report one id for every site, so a web app takes
the browser's mode.

### Personal vocabulary

Acronyms and product names are where speech recognition slips: "LLM" comes out
as "allyl m". List the spellings you want in `~/.config/flowd/vocab.toml`
(start from [`vocab.toml.example`](vocab.toml.example)):

```toml
terms = ["LLM", "STT", "Hyprland"]

[replace]
"stair-tier" = "STT"
```

- `terms` bias the recognizer towards those spellings.
- `[replace]` fixes a mishearing the model keeps making. Check `flowctl last` to
  see what it actually wrote, and only add phrases you would never mean
  literally.

Both apply on `flowctl reload`. A broken file is rejected and the old vocabulary
kept. Entries must be non-empty and on a single line.

### Cleanup model

The `[llm]` table points at the local `llama-server`. The URL must be on this
machine; flowd refuses to start with any other host. `final_timeout_ms` (800) is
how long a release waits for the model before pasting the fallback. Dictations
under five words skip the model (`[chunking] short_bypass_words`).

### ydotool (optional)

Most applications accept text from the clipboard or from `wtype`/`xdotool`. A
few (some Electron apps, games and terminals in unusual modes) accept only
kernel-level input events, which is what `ydotool` provides. It needs write
access to `/dev/uinput`, and **flowd will not set this up for you**, since it
touches device permissions and a system group.

<details>
<summary><b>Enable the ydotool backend</b></summary>

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

Log out and back in for the group change to take effect.

> [!WARNING]
> Membership in the `uinput` group lets any process you run synthesise keyboard
> and mouse input for your whole session.

If you skip this, flowd never selects the `ydotool` backend. Remove it from
`inject.order` to stop flowd trying.

</details>

## Troubleshooting

Start with the logs:

```bash
journalctl --user -u flowd -u flowd-llm -f
```

Raise the detail with `[logging] level = "debug"`, or run the daemon in the
foreground with `flowd --log-level debug`.

<details>
<summary><b>The text landed nowhere</b></summary>

It is not lost: `flowctl last` prints the most recent transcript so you can paste
it by hand. Then check which backend failed with
`journalctl --user -u flowd -n 50`. Each skipped backend logs why, for example
`injector ydotool unavailable (ydotoold is not running ...)`. The usual cause is
a missing tool: Wayland needs `wl-clipboard` and `wtype`, X11 needs `xclip` and
`xdotool`. On X11, non-ASCII text is always pasted through the clipboard,
because `xdotool type` mangles it.

</details>

<details>
<summary><b>Nothing happens on the hotkey</b></summary>

Confirm the daemon is up with `flowctl status`. If it says flowd is not running
while the service is active, the two are looking at different sockets, usually
because the service started without `XDG_RUNTIME_DIR`. Re-run the
`import-environment` step from the manual install.

</details>

<details>
<summary><b>No microphone</b></summary>

flowd reports the error and sends a desktop notification. Check
`flowctl status`, then that PipeWire is running
(`systemctl --user status pipewire`) and that no other application holds the
device exclusively. Set `audio.device` if the default is not the microphone you
meant.

</details>

<details>
<summary><b>The indicator is missing</b></summary>

On GNOME/Wayland this is deliberate (see the GNOME hotkey section). Elsewhere,
check that `flowd-ui` was built (`make ui` puts it in `build/ui/flowd-ui`), and
look for the reason in the log:

```bash
journalctl --user -u flowd | grep flowd-ui
```

flowd looks for the binary in `$FLOWD_UI`, then `build/ui/flowd-ui` in this
checkout, then `flowd-ui` on `PATH`.

</details>

<details>
<summary><b>Text arrives without cleanup</b></summary>

You get fillers and lowercase names when the model is not answering, and a
desktop notification says so once per dictation. Check
`systemctl --user status flowd-llm`. flowd probes it every 30 s and picks it up
again once it is back. A single dictation without cleanup is usually a guardrail
rejecting the model's output, which is intended. `~/.local/state/flowd/metrics.jsonl`
records each one by check number, never with the text.

</details>

<details>
<summary><b>The service will not start</b></summary>

`systemctl --user status flowd` shows the exit code:

| Exit | Meaning | Fix |
|---|---|---|
| 2 | A model file does not match `models.lock` | Run `scripts/fetch_models.sh`. systemd does not retry this one. |
| 3 | The config file is invalid | The reason is on the line above, e.g. `flowd: invalid config: block_ms ...`. Fix `~/.config/flowd/config.toml`. |
| 4 | A speech model failed to load | Usually a partial download: run `scripts/fetch_models.sh`. To run on Moonshine alone, set `[stt] final_model = ""`. |
| 5 | An audio stream would not stop | systemd restarts flowd, which releases the microphone. If it repeats, check the log for the device that hung. |

After fixing it, `systemctl --user reset-failed flowd` lets systemd try again.

</details>

<details>
<summary><b>The microphone went away mid-dictation</b></summary>

Unplugging it, or restarting PipeWire, ends the dictation early: flowd pastes
what it heard so far and notifies you. Press the hotkey again to continue.

</details>

<details>
<summary><b>A dictation vanished after sleep</b></summary>

Suspending mid-dictation cancels it, by design. By the time you resume, the
words are stale and focus may be elsewhere, so pasting them would be a guess.

</details>

<details>
<summary><b>Measuring idle cost</b></summary>

`scripts/idle_check.py` samples memory and CPU of the daemon, `flowd-ui` and
`llama-server` for a minute and checks them against the budget (1,600 MB
anonymous memory, 1 % CPU). `scripts/idle_check.py --soak 24` samples every 30
minutes for a day and flags memory growth or a restarted process.

</details>

**Reporting a bug.** Include `flowd --version`, your compositor and session
type, and the last 50 journal lines. Please do not paste transcript text you
would not want to be public.

## Privacy

flowd is built to be boring about your data.

- **No network at runtime.** `llama-server` listens on `127.0.0.1` only, and so
  does the settings page (`127.0.0.1:8178`), which also requires a token from
  `flowctl settings`. Model downloads are a separate step you run yourself.
- **No transcripts on disk by default.** `logging.log_transcripts` is `false`.
  Dictation contains passwords, addresses and private messages; the default
  assumes that.
- **No audio on disk.** Audio lives in memory for the length of a session. The
  only audio files flowd reads are ones you pass to `--replay` yourself.
- **Metrics contain timings, not text.** `~/.local/state/flowd/metrics.jsonl`
  gets one line per session: durations, word count and the backend used.
- **Your clipboard is put back.** The clipboard backend snapshots, pastes and
  restores it. If it holds something other than text, flowd leaves it alone and
  uses a typing backend instead.

## Evaluating changes

Changing a prompt, a threshold or a model needs a before-and-after run on your
own recordings (spec 11.4). Put `NNN.wav` (16 kHz mono) and `NNN.ref.txt` (the
text you wanted) in `eval/data/`, optionally with `NNN.raw.txt` (exactly what
you said), then:

```bash
uv run python eval/run_eval.py --no-llm   # baseline: rule-based cleanup only
uv run python eval/run_eval.py            # with the model; needs flowd-llm running
```

Each run writes `eval/results/<date>-<sha>.json` with WER before and after
cleanup, the fallback rate and which checks fired, release-to-paste latency, and
every accepted output that added a word. Results hold your transcripts, so
`eval/data/` and `eval/results/` are gitignored.
`uv run python eval/seed_librispeech.py` fills `eval/data/` from the LibriSpeech
clips that `scripts/fetch_eval_audio.sh` fetches, which is useful for checking
the harness, but read audiobooks are not dictation.

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Bug reports about a compositor or
application flowd handles badly are especially useful: the injection path is
where the hard cases live, and no one has every desktop.

## License

flowd is MIT licensed. See [`LICENSE`](LICENSE).

The models are separately licensed and are **not** covered by flowd's licence:

- **Moonshine** (speech recognition): the `moonshine-voice` package is MIT, and
  the English weights flowd uses ship under the same terms. Moonshine's
  **non-English** weights use a Moonshine Community Licence that forbids
  commercial use; if you point `stt.model` at one, that licence is yours to
  honour.
- **Parakeet TDT 0.6B v2** (final transcript): NVIDIA's model, converted to int8
  ONNX by the sherpa-onnx project, under CC-BY-4.0 (attribution required). It
  runs through `sherpa-onnx`, which is Apache-2.0.
- **Sotto cleanup LFM2.5-350M** (text cleanup): a community fine-tune of Liquid
  AI's LFM2.5-350M-Base under the LFM Open License v1.0, which limits commercial
  use by larger companies. See the model card linked in
  [`models.lock`](models.lock).

`models.lock` records the exact revision and SHA-256 of every pinned file.
