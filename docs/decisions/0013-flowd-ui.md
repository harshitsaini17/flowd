# 0013: Replace the overlay with `flowd-ui`, a C++ indicator and popup

**Status:** accepted (2026-09-28)

## Context

The overlay (`overlay/flowd_overlay.py`) is a Python + PyGObject GTK4 process
using about 195 MB of anonymous memory, most of the non-model memory flowd
uses. It only shows a preview; there is no way to start dictation without a
hotkey. The new design (`docs/design/design.md`) adds an always-present
indicator at the bottom of the screen that expands on hover into a mic button,
can be dragged along the bottom edge, and shows recording, finishing and
warning states.

## Decision

- A new program, `flowd-ui`, in C++20 with gtkmm-4.0 and gtk4-layer-shell,
  built with CMake (`-O2`, LTO, stripped). It replaces `overlay/`. Target:
  ≤ 40 MB anonymous memory.
- Two layer surfaces, both `OVERLAY` layer, keyboard interactivity `NONE`,
  exclusive zone -1: they reserve no space, and they ignore the space other
  panels reserve, so surface x is output x on every compositor. With zone 0
  a bar's reserved edge shifts the surface off where the pill is drawn. The
  cost: with a bar on the bottom edge, the indicator and the popup draw over
  it rather than above it.
  - `flowd-indicator`: always present when `[ui] indicator = true`. It spans
    the output's bottom edge and accepts pointer input only inside its input
    region, so everything but the pill is click-through. On X11 it spans the
    monitor's workarea instead, and without a compositing manager, which
    would paint its transparent area opaque, it stays pill-sized and moves.
  - `flowd-popup`: created on the first `show`, then unmapped (not
    destroyed) after the fade, with no tick while hidden. Reusing it avoids
    re-running surface creation and the focus checks on every dictation.
    Empty input region, fully click-through.
- ADR 0003 still holds: if a surface cannot be guaranteed never to take
  keyboard focus (GNOME Wayland), `flowd-ui` disables itself and logs why.
- On X11 (GNOME on Xorg included) both surfaces are override-redirect
  windows with `WM_HINTS` `input=False`, and both properties are read back
  from the X server before a window is shown; a mismatch or X error disables
  the overlay as on Wayland. Override-redirect windows are never managed by
  the window manager, so it never focuses them, and they are shown without
  `present()`, which would request focus. That is the same guarantee ADR 0003
  asks of a layer surface, so this supersedes 0003's "X11 gets no overlay".
- Click toggles dictation. A press that moves more than 4 px is a drag. The
  drag only redraws the pill and moves the input region inside the
  output-wide surface; the surface itself never moves or resizes. Moving or
  widening it under a held pointer failed on Hyprland: the compositor
  animates the change, events in between are read against the wrong
  origin, and the pill leaves the pointer and can miss the release. Wayland
  keeps sending pointer events to the pressed surface until release, so the
  input region does not need to grow. The position is stored
  per output as a fraction of its width in
  `$XDG_STATE_HOME/flowd/indicator.json`.
- The daemon still spawns `flowd-ui` and restarts it if it dies; a UI crash
  never ends a dictation.
- Protocol, newline-delimited JSON. Existing messages on stdin keep their
  meaning (`show`, `render`, `fade`, `hide`, `quit`). New daemon → UI messages:
  - `{"type":"state","state":"idle|recording|finishing|done|fallback|error|cancelled|nospeech|timelimit","reason":"…"}`
  - `{"type":"level","rms_db":-23.5,"peak_db":-9.1}`, 20 Hz while recording
  - `{"type":"meta","mode":"code","app":"kitty","hotkey":"Super D"}`
  - `{"type":"warn","reason":"…"}`, and `"reason":null` to clear
  - `{"type":"config", ...}` with the `[ui]` values, sent on start and reload

  UI → daemon on stdout: `{"event":"click"}` (handled as `toggle`) and
  `{"event":"moved","x":0.42,"output":"eDP-1"}`. Unknown types are ignored in
  both directions.
- Process contract. stdin and stdout are pipes owned by `flowd-ui`, which
  sets `O_NONBLOCK` on both. Exit codes:
  - 0: normal end: `quit`, stdin EOF, SIGTERM, or stdout closed (a signal
    that lands before start-up finishes installing its handlers ends the
    process with 143).
  - 1: crash or init failure, such as a display that will not open. The
    daemon may respawn it.
  - 3: unsupported, after writing
    `{"event":"unsupported","reason":"…"}`. The daemon must not respawn it
    until the config is reloaded. For `flowd-ui` this replaces ADR 0003's
    "keep consuming stdin": it exits rather than idling on a pipe.
- `GDK_BACKEND` is set from the backend decision before GTK starts, so a
  session meant for Wayland never falls back to Xwayland.
- Popup text is drawn with a Pango layout in a custom widget, not a
  `Gtk::Label`, so the three zones, the pending → polished crossfade and the
  self-correction highlight can be animated per run.
- Fonts: Inter and JetBrains Mono ship as TTF next to the binary and are
  registered with Pango at start; failure falls back to the system font.
- Hiding over fullscreen windows and following the focused output are best
  effort, on Hyprland and Sway only, through the same compositor queries
  `context.py` already runs.

## Consequences

- New build dependencies: CMake, a C++20 compiler, `gtkmm-4.0`. Runtime
  dependencies are the same as today (`gtk4`, `gtk4-layer-shell`); PyGObject
  is no longer needed.
- Drag and snap logic and the protocol parser are pure functions tested with
  `doctest` (single header, MIT, vendored at a pinned version). Visuals are
  checked by hand, listed in `docs/edge-cases.md`.
- `[overlay]` config keys move to `[ui]`; `[overlay]` is still read for one
  release.

## Notes from building it

- Fonts are the design page's woff2 files (`flowd/web/assets/fonts`),
  copied next to the binary at build time and registered with Pango
  directly; there is no TTF copy. An installed build falls back to
  `FLOWD_FONTS_DIR` (default `<datadir>/flowd/fonts`), then to the system
  font.
- The GSK renderer defaults to cairo unless `GSK_RENDERER` is set: GL and
  Vulkan map several MB of driver state each. On X11, GDK creates a GL context
  even for cairo, so `flowd-ui` also sets `GDK_DISABLE=gl` there, which took
  anonymous memory from 36 MB to about 20 MB. Measured anonymous memory is
  about 20 MB on both Wayland and X11, against the 40 MB target; an idle
  indicator on Hyprland, before its first popup, measured 10 MB.
- X11 is supported as the Decision describes: override-redirect windows with
  `input=False`, both read back from the X server before showing.
  `GDK_BACKEND` is pinned from the backend decision; the exit codes are the
  ones under "Process contract" above.
- Two protocol additions. `warn` carries `"blocking": true` when the
  microphone itself is the problem, which makes the indicator show `mic-off`
  and ignore clicks. On stdout, `{"event":"unsupported","reason":"…"}` joins
  `click` and `moved`; it is written just before exit 3 (see "Process
  contract"), so the daemon logs the reason and stops respawning.
- `state.reason` is a code (`offline`, `timeout`, `mic_lost`,
  `paste_failed`, ...), not text. `flowd-ui` owns the wording and falls back
  to a generic line for a code it does not know. `warn.reason` is still sent
  as the text to show.
