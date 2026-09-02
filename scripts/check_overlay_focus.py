#!/usr/bin/env python3
"""The phase 2 gate: the overlay previews without ever taking keyboard focus.

Run this on a `zwlr_layer_shell_v1` compositor, with a window focused:

    uv run python scripts/check_overlay_focus.py

It drives the real child through `OverlayProcess` — a session's worth of
renders, a fade and a stop — and asks `hyprctl` what the compositor thinks
after each step. The unit suite cannot answer this: `tests/test_overlay_ipc.py`
proves the daemon writes well-formed protocol to a fake, and
`tests/test_overlay_process.py` proves the child parses it, but neither can see
whether the window that lands on screen steals the focus the dictation is aimed
at. spec 5.8 calls an overlay that does that worse than no overlay, so the
property gets a check that a person can re-run rather than an argument.

Hyprland-specific, because `hyprctl` is how you interrogate it. The property is
not: any compositor implementing the protocol should pass, with the queries
swapped for its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from flowd.config import Overlay as OverlayCfg
from flowd.overlay_ipc import OverlayProcess

#: Long enough for GTK to start, re-exec itself with LD_PRELOAD (ADR 0003) and
#: map a surface the compositor will report.
STARTUP_S = 1.5


def hyprctl(*args: str) -> Any:
    result = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"hyprctl {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def focused() -> str:
    window = hyprctl("activewindow")
    if not window:
        return "(nothing focused)"
    return f"class={window.get('class')!r} addr={window.get('address')}"


def layer_surfaces() -> list[tuple[str, str, int, int]]:
    """Every `gtk4-layer-shell` surface the compositor currently has."""
    found = []
    for monitor, info in (hyprctl("layers") or {}).items():
        for level, surfaces in (info.get("levels") or {}).items():
            for surface in surfaces:
                if surface.get("namespace") == "gtk4-layer-shell":
                    found.append((monitor, level, surface.get("w"), surface.get("h")))
    return found


def flowd_clients() -> list[Any]:
    """Overlay entries among the windows the compositor can focus. Should be none:
    a layer surface is not a client window."""
    return [c for c in (hyprctl("clients") or []) if "flowd" in str(c.get("class", "")).lower()]


def main() -> int:
    results: dict[str, bool] = {}

    # The injectable spawn is how the child is kept in reach: `OverlayProcess`
    # drops its reference in `stop`, and this script has to poll the process
    # afterwards to see whether it exited on its own or had to be signalled.
    children: list[Any] = []

    def spawn(*args: Any, **kwargs: Any) -> Any:
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    before = focused()
    print(f"focused before      : {before}")
    if before == "(nothing focused)":
        print("\nFocus something first — with nothing focused there is nothing to steal.")
        return 2

    overlay = OverlayProcess(OverlayCfg(), spawn=spawn)
    results["nothing spawned before the first message"] = overlay.alive is False

    overlay.show()
    overlay.render(polished="Polished text.", pending="pending words", live="live words")
    time.sleep(STARTUP_S)

    during = focused()
    surfaces = layer_surfaces()
    clients = flowd_clients()
    print(f"focused during      : {during}")
    for monitor, level, width, height in surfaces:
        print(f"layer surface       : monitor={monitor} level={level} {width}x{height}")
    print(f"focusable windows   : {len(clients)} (want 0)")

    results["child is running"] = overlay.alive is True
    results["overlay is a layer surface"] = len(surfaces) >= 1
    results["overlay is not a focusable window"] = len(clients) == 0
    results["focus unchanged while shown"] = during == before

    # A session's worth of previews: `render` runs on every STT event.
    for i in range(20):
        overlay.render(polished="Polished text.", pending="pending words", live=f"partial {i}")
        time.sleep(0.05)
    results["child survives a session of renders"] = overlay.alive is True

    overlay.fade()
    time.sleep(0.5)
    results["focus unchanged after fade"] = focused() == before

    overlay.stop()
    time.sleep(0.5)
    codes = [child.poll() for child in children]
    print(f"child exit codes    : {codes} (0 means it obeyed `quit` rather than SIGTERM)")
    results["stop reaps the child"] = all(code is not None for code in codes)
    results["child exits on `quit`, not a signal"] = codes == [0]
    results["no layer surface left behind"] = not layer_surfaces()
    results["focus unchanged at the end"] = focused() == before

    print()
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
