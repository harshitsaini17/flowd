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
  exclusive zone 0:
  - `flowd-indicator`: always present when `[ui] indicator = true`. Accepts
    pointer input only inside its input region.
  - `flowd-popup`: created on `show`, destroyed after the fade. Empty input
    region, fully click-through.
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
  drag moves the indicator by updating its left margin with `LEFT | BOTTOM`
  anchors; Wayland keeps sending pointer events to the pressed surface until
  release, so the input region does not need to grow. The position is stored
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
