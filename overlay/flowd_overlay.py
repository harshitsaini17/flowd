#!/usr/bin/env python3
"""flowd preview overlay (spec 5.8).

A separate process because GTK wants the main thread and an overlay crash must
never kill a dictation. Runs on the SYSTEM interpreter with pacman's
python-gobject, so it imports only the standard library and gi — never anything
from the flowd package or its venv.

Protocol: newline-delimited JSON on stdin.
  {"type": "show"}
  {"type": "render", "polished": "...", "pending": "...", "live": "..."}
  {"type": "fade"}
  {"type": "hide"}
  {"type": "quit"}

The overlay must never take keyboard focus. Everything it types would go to the
overlay instead of the user's text box, so a focus-stealing preview is worse
than no preview at all and this process disables itself rather than risk it
(ADR 0003).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

log = logging.getLogger("flowd-overlay")

MAX_LINES = 4
FADE_MS = 1000

# gtk4-layer-shell has to intercept GTK's Wayland surface creation, so it must
# be in the process before GTK opens its display. Under PyGObject nothing links
# it at build time, so it arrives by LD_PRELOAD or not at all (ADR 0003).
PRELOAD_LIB = "/usr/lib/libgtk4-layer-shell.so"
_REEXEC_GUARD = "FLOWD_OVERLAY_PRELOADED"

_CSS = """
.flowd-overlay {
  background-color: rgba(20, 20, 24, 0.88);
  border-radius: 12px;
  padding: 10px 16px;
}
.flowd-polished { color: #f2f2f7; font-size: 15px; }
.flowd-pending  { color: #f2f2f7; opacity: 0.55; font-size: 15px; }
.flowd-live     { color: #9ad2ff; font-style: italic; font-size: 15px; }
"""


def ensure_preload() -> None:
    """Re-exec with the layer-shell library preloaded, once, if that is needed.

    The alternative is for whoever spawns us to set `LD_PRELOAD`, which was
    rejected: the variable is easy to drop, and dropping it does not fail
    loudly — `init_for_window()` still returns without error and quietly leaves
    an ordinary, focusable toplevel (ADR 0003). Doing it here keeps the overlay
    correct however it is launched, including by hand while debugging.

    A missing library is not an error to raise: `main` disables the overlay
    rather than take the risk, and the daemon keeps dictating without a preview.
    """
    if layer_shell_supported() or os.environ.get(_REEXEC_GUARD):
        return
    if not os.path.exists(PRELOAD_LIB):
        log.warning("%s not found; overlay cannot use layer-shell", PRELOAD_LIB)
        return

    env = dict(os.environ)
    env[_REEXEC_GUARD] = "1"
    existing = env.get("LD_PRELOAD", "")
    env["LD_PRELOAD"] = f"{PRELOAD_LIB} {existing}".strip() if existing else PRELOAD_LIB
    log.info("re-executing with LD_PRELOAD=%s", env["LD_PRELOAD"])
    try:
        argv = [sys.executable, os.path.abspath(__file__), *sys.argv[1:]]
        os.execve(sys.executable, argv, env)
    except OSError as exc:
        # Carry on unlayered; `main` will disable the overlay and say why.
        log.warning("could not re-exec with preload: %s", exc)


def layer_shell_supported() -> bool:
    """Whether wlr-layer-shell is usable in this process, right now.

    False on GNOME Wayland (no protocol), on X11, and in a process the library
    was not preloaded into — the three cases are indistinguishable here and get
    the same treatment.
    """
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError):
        return False
    return bool(LayerShell.is_supported())


def _init_layer_shell(window: Gtk.Window) -> bool:
    """Anchor the window bottom-centre and refuse keyboard focus.

    Returns whether the window really became a layer surface. That is checked
    with `is_layer_window()` and not by the absence of an exception, because
    `init_for_window()` raises nothing when it has not worked: it logs a warning
    and leaves a normal toplevel, which would take focus the moment it is shown.
    """
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError) as exc:
        log.warning("gtk4-layer-shell unavailable: %s", exc)
        return False

    try:
        LayerShell.init_for_window(window)
        if not LayerShell.is_layer_window(window):
            log.warning("layer-shell did not take: window is still a plain toplevel")
            return False
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(window, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_margin(window, LayerShell.Edge.BOTTOM, 80)
        # The whole point: never accept keyboard focus, or injection breaks.
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
        if LayerShell.get_keyboard_mode(window) != LayerShell.KeyboardMode.NONE:
            log.warning("compositor did not honour keyboard-mode NONE")
            return False
    except Exception as exc:
        log.warning("could not initialise layer-shell: %s", exc)
        return False
    return True


class Overlay:
    def __init__(self, max_lines: int = MAX_LINES, fade_ms: int = FADE_MS) -> None:
        self._fade_ms = fade_ms
        self.window = Gtk.Window()
        self.window.set_decorated(False)
        self.window.set_default_size(680, -1)
        self.window.set_can_focus(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("flowd-overlay")
        self.labels: dict[str, Gtk.Label] = {}
        for zone, css in (
            ("polished", "flowd-polished"),
            ("pending", "flowd-pending"),
            ("live", "flowd-live"),
        ):
            label = Gtk.Label(label="", wrap=True, xalign=0.0)
            label.set_lines(max_lines)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.add_css_class(css)
            label.set_visible(False)
            box.append(label)
            self.labels[zone] = label
        self.window.set_child(box)

        provider = Gtk.CssProvider()
        provider.load_from_string(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.layered = _init_layer_shell(self.window)
        if self.layered:
            # Worth a line: it is the difference between a working preview and a
            # disabled one, and it is the first thing to look for in a bug report.
            log.info("overlay ready: layer-shell surface, keyboard focus refused")
        else:
            # Without layer-shell we cannot guarantee the window never takes
            # focus, and a focus-stealing overlay is worse than none (spec 5.8).
            log.error("no layer-shell: overlay disabled to protect injection")
        self._fade_source: int | None = None

    def show(self) -> None:
        if not self.layered:
            return
        self._cancel_fade()
        self.window.set_visible(True)

    def hide(self) -> None:
        self._cancel_fade()
        self.window.set_visible(False)

    def render(self, zones: dict[str, str]) -> None:
        if not self.layered:
            return
        self._cancel_fade()
        for zone, label in self.labels.items():
            text = str(zones.get(zone) or "").strip()
            label.set_text(text)
            label.set_visible(bool(text))
        self.window.set_visible(True)

    def fade(self) -> None:
        """Hide shortly after injection (spec 5.8)."""
        self._cancel_fade()
        self._fade_source = GLib.timeout_add(self._fade_ms, self._on_fade)

    def _on_fade(self) -> bool:
        self.window.set_visible(False)
        self._fade_source = None
        return GLib.SOURCE_REMOVE

    def _cancel_fade(self) -> None:
        if self._fade_source is not None:
            GLib.source_remove(self._fade_source)
            self._fade_source = None


def _apply(overlay: Overlay, message: dict[str, object]) -> bool:
    """Apply one message on the GTK main thread. Returns False to quit.

    Unknown types are logged and ignored rather than fatal: the daemon is the
    only writer today, and an overlay that dies on an unrecognised message would
    take the preview down for the rest of the session over a version skew.
    """
    kind = str(message.get("type", ""))
    if kind == "quit":
        return False
    if kind == "show":
        GLib.idle_add(overlay.show)
    elif kind == "hide":
        GLib.idle_add(overlay.hide)
    elif kind == "fade":
        GLib.idle_add(overlay.fade)
    elif kind == "render":
        zones = {k: message.get(k, "") for k in ("polished", "pending", "live")}
        GLib.idle_add(overlay.render, zones)
    else:
        log.warning("ignoring unknown message type: %r", kind)
    return True


def _reader(overlay: Overlay, app: Gtk.Application) -> None:
    """Read stdin on a worker thread, applying changes on the GTK main thread."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            log.warning("ignoring malformed message: %s", exc)
            continue
        if not isinstance(message, dict):
            # Valid JSON, but not a message: a list, a bare string, null.
            log.warning("ignoring non-object message: %.60s", line)
            continue
        if not _apply(overlay, message):
            GLib.idle_add(app.quit)
            return
    # The daemon closed our stdin, which means it exited or dropped us. Quitting
    # keeps spec 5.8's crash isolation from leaving a window nobody owns.
    GLib.idle_add(app.quit)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the `[overlay]` settings the daemon passes on argv (spec 8).

    On argv rather than in the stdin protocol because both values are needed
    before the first message can arrive: `max_lines` is applied while the labels
    are built, which happens before the window exists.

    Unknown flags are ignored rather than fatal, for the same reason `_apply`
    ignores unknown message types: a newer daemon passing a flag this overlay
    does not know would otherwise exit 2 on every spawn, and the user would lose
    the preview entirely over a version skew.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--fade-ms", type=int, default=FADE_MS)
    args, extra = parser.parse_known_args(argv)
    if extra:
        log.warning("ignoring unrecognised arguments: %s", " ".join(extra))
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="overlay: %(message)s", stream=sys.stderr)
    # Parsed before the re-exec so a bad argument fails here rather than in a
    # second process. `ensure_preload` forwards argv, so the values survive it.
    args = parse_args(sys.argv[1:])
    ensure_preload()  # may replace this process; nothing below runs if it does

    # NON_UNIQUE: a stale overlay holding the bus name would otherwise swallow
    # this one's activation, and the daemon would wait for a preview that the
    # previous session's window is quietly answering for.
    app = Gtk.Application(application_id="dev.flowd.Overlay", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(_app: Gtk.Application) -> None:
        overlay = Overlay(max_lines=args.max_lines, fade_ms=args.fade_ms)
        app.add_window(overlay.window)
        threading.Thread(target=_reader, args=(overlay, app), daemon=True).start()

    app.connect("activate", on_activate)
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
