# 0003: The overlay needs `LD_PRELOAD`, and silently does not without it

Status: accepted
Phase: 2

## Context

spec 5.8 makes one property non-negotiable: the overlay must never take
keyboard focus. Everything the user dictates goes to the focused window, so an
overlay that steals focus swallows the dictation it was supposed to preview —
worse than shipping no overlay at all. The user's amendment to the phase 0-2
design asked specifically whether `LD_PRELOAD` of the layer-shell library is
required, and Task 18's plan assumed the preload path merely "exists" and might
be optional.

It is required. And the failure mode when it is missing is the dangerous one.

### Versions

Measured on the reference machine, Arch Linux, Hyprland session:

| Component | Version |
| --- | --- |
| Hyprland | running as `Hyprland --watchdog-fd 4`, `XDG_SESSION_TYPE=wayland` |
| GTK | 4.22.5 (`gtk4 1:4.22.5-1.1`) |
| gtk4-layer-shell | 1.3.0 (`gtk4-layer-shell 1.3.0-1.1`), `zwlr_layer_shell_v1` protocol version 4 |
| PyGObject | 3.56.3 (`python-gobject 3.56.3-1`) |
| System interpreter | `/usr/bin/python3` |

### `is_supported()` is false without a preload, on a compositor that supports it

With the typelib importable and a live `GdkWaylandDisplay`, on Hyprland:

```
LD_PRELOAD=(none)
layer-shell 1.3.0
is_supported() before display: False
display: GdkWaylandDisplay
is_supported() after init: False
init_for_window: ok
is_layer_window: False
keyboard mode read back: 0
window presented: ok
```

Import order does not fix it — importing `Gtk4LayerShell` before `Gtk`, before
any display exists, gives the same `False`. That run does print the reason:

```
** Message: You may be able to fix with without recompiling by setting
   LD_PRELOAD=/path/to/libgtk4-layer-shell.so
** Message: See https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md
```

gtk4-layer-shell has to intercept GTK's Wayland surface creation, so it must be
in the process before GTK opens its display. A C application links it at build
time; under PyGObject nothing links it at all, so it arrives by `LD_PRELOAD` or
not at all.

With the preload, the same probe:

```
LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so
is_supported() pre-init: True
display: GdkWaylandDisplay
is_supported() post-init: True
protocol_version: 4
is_layer_window after init: True
keyboard mode: 0 (NONE == 0)
```

**The plan named the wrong library.** It proposed
`/usr/lib/liblayer-shell-preload.so`, which the package also ships. Tested, it
does not work — `is_layer_window()` stays `False` and the shim itself warns
`GtkWindow is not a layer surface. Make sure you called
gtk_layer_init_for_window()` three times over. The library that works is the
one the warning above names, `/usr/lib/libgtk4-layer-shell.so`.

### The failure is silent, which is what makes this a decision and not a detail

`init_for_window()` **raises nothing** when the preload is absent. It logs a
warning and leaves an ordinary GTK toplevel, which takes keyboard focus the
moment it is shown. Any code that treats "no exception" as success — as the
plan's `_try_layer_shell` did — reports a working overlay and hands the user a
focus-stealing window. Reading `is_layer_window()` back is the only way to know.

### Focus behaviour on Hyprland, with the preload in place

`hyprctl` before, during and after showing the overlay, with a `kitty` window
focused:

```
focused before : class='kitty' addr=0x56115034e690
focused during : class='kitty' addr=0x56115034e690
overlay in `hyprctl clients`: 0 entry(ies)
layer surface: monitor=eDP-1 level=3 namespace='gtk4-layer-shell' w=680 h=39
overlay present as a layer surface: True
focused after  : class='kitty' addr=0x56115034e690

RESULT focus unchanged throughout: True
RESULT overlay is not a client window: True
RESULT overlay is a layer surface: True
```

The overlay does not appear in `hyprctl clients` at all — it is not a window the
compositor can focus, it is a layer surface at level 3 (overlay) with
`keyboard-mode NONE`. The focused window's address is byte-identical before,
during and after.

## Options

1. **The overlay preloads itself, by re-executing once with `LD_PRELOAD` set.**
   Correct however it is launched — by the daemon, by systemd, or by hand while
   debugging. Costs one `execve` at startup (the process has done nothing yet)
   and an environment-variable guard so it cannot loop. Reversible.
2. **The daemon sets `LD_PRELOAD` when it spawns the child.** One less exec, and
   no self-modifying startup. But the requirement then lives in the parent, and
   the failure it guards against is silent: anyone who runs the overlay directly,
   or a future spawn path that forgets the variable, gets a focus-stealing window
   and no error. Cheap to get wrong, expensive to notice.
3. **Require the package to be patched, or link it properly.** Not ours to do,
   and it would make flowd depend on a non-default build of a distro package.

## Decision

**Option 1.** `overlay/flowd_overlay.py` checks `is_supported()` at startup and,
if false, re-executes itself once with `/usr/lib/libgtk4-layer-shell.so` in
`LD_PRELOAD`, guarded by `FLOWD_OVERLAY_PRELOADED` so a machine where the
preload does not help cannot loop. The daemon therefore spawns the overlay
plainly, with no special environment, and the overlay is correct when run by
hand too.

Beyond that, the overlay verifies rather than assumes. After
`init_for_window()` it checks `is_layer_window()`, and after setting the
keyboard mode it reads it back; if either disagrees it disables itself. Tests
assert the positive log line (`layer-shell surface, keyboard focus refused`)
rather than a clean exit, because a clean exit is exactly what the broken case
also produces.

### Where layer-shell is absent

GNOME Wayland (which does not implement `zwlr_layer_shell_v1`), X11, and any
process the library could not be preloaded into are indistinguishable from here
and get the same treatment: the overlay logs
`no layer-shell: overlay disabled to protect injection` at ERROR, ignores
`show` and `render`, and keeps consuming stdin so the daemon's writes never
block. Dictation and injection work normally; there is no preview. spec 5.8
prefers that to a preview that eats the user's keystrokes.

## Impact on spec

- **5.8 (overlay).** Add that the overlay requires `gtk4-layer-shell` **and** a
  preload to use it from Python, and that it self-disables when it cannot
  become a layer surface. The plan's `LD_PRELOAD` question is answered:
  required, and with `libgtk4-layer-shell.so`, not the
  `liblayer-shell-preload.so` shim.
- **13.2 (never do).** Worth stating explicitly: never treat
  `gtk_layer_init_for_window` returning without error as proof that a window is
  a layer surface. It is not, and the difference is a focus-stealing overlay.
- **Testing (11).** The focus property itself needs a compositor and a focused
  client, so it stays a manual `hyprctl` check, scripted for repeatability and
  evidenced above. What CI can hold is the layered-state assertion and its
  negative twin: the fallback path must produce no ready line.
