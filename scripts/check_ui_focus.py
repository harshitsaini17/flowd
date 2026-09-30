#!/usr/bin/env python3
"""Manual check: flowd-ui shows its indicator and popup without ever taking
keyboard focus.

Run this on a `zwlr_layer_shell_v1` compositor, with a window focused, after
`make ui`:

    uv run python scripts/check_ui_focus.py

It drives the real `build/ui/flowd-ui` through `UiProcess` — a session's worth
of states, levels and renders, an end and a stop — and asks `hyprctl` what the
compositor thinks after each step. The unit suite cannot answer this:
`tests/test_ui_ipc.py` proves the daemon writes well-formed protocol to a fake,
and `ctest` proves the UI core parses it, but neither can see whether the
surfaces that land on screen steal the focus the dictation is aimed at. spec
5.8 calls a preview that does that worse than no preview, so the property gets
a check that a person can re-run rather than an argument.

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

from flowd.config import Ui
from flowd.ui_ipc import DEFAULT_BINARY, UiProcess

#: The layer-shell namespaces flowd-ui gives its two surfaces.
NAMESPACES = ("flowd-indicator", "flowd-popup")

#: Long enough for GTK to start and map a surface the compositor will report.
STARTUP_S = 1.5

#: What the check passes as `[audio] max_session_s`; only the popup's time
#: limit hint reads it.
MAX_SESSION_S = 120


def hyprctl(*args: str) -> Any:
    result = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"hyprctl {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def focused() -> str | None:
    """The focused window's address, or None with nothing focused."""
    window = hyprctl("activewindow")
    return str(window.get("address")) if window else None


def describe_focus() -> str:
    window = hyprctl("activewindow")
    if not window:
        return "(nothing focused)"
    return f"class={window.get('class')!r} addr={window.get('address')}"


def layer_surfaces() -> dict[str, list[dict[str, Any]]]:
    """flowd-ui's layer surfaces, by namespace."""
    found: dict[str, list[dict[str, Any]]] = {ns: [] for ns in NAMESPACES}
    for info in (hyprctl("layers") or {}).values():
        for surfaces in (info.get("levels") or {}).values():
            for surface in surfaces:
                namespace = surface.get("namespace")
                if namespace in found:
                    found[namespace].append(surface)
    return found


def interactivity(surfaces: list[dict[str, Any]]) -> list[int] | None:
    """Each surface's `keyboardInteractivity`, or None when the compositor
    does not report it (Hyprland 0.56 does not)."""
    values = [s["keyboardInteractivity"] for s in surfaces if "keyboardInteractivity" in s]
    return values if len(values) == len(surfaces) and values else None


def flowd_clients() -> list[Any]:
    """flowd entries among the windows the compositor can focus. Should be
    none: a layer surface is not a client window."""
    return [c for c in (hyprctl("clients") or []) if "flowd" in str(c.get("class", "")).lower()]


def main() -> int:
    if not DEFAULT_BINARY.exists():
        print(f"{DEFAULT_BINARY} not found; run `make ui` first.")
        return 2

    results: dict[str, bool] = {}

    # The injectable spawn is how the child is kept in reach: `UiProcess`
    # drops its reference in `stop`, and this script has to poll the process
    # afterwards to see whether it exited on its own or had to be signalled.
    children: list[Any] = []

    def spawn(*args: Any, **kwargs: Any) -> Any:
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    before = focused()
    print(f"focused before      : {describe_focus()}")
    if before is None:
        print("\nFocus something first — with nothing focused there is nothing to steal.")
        return 2

    ui = UiProcess(Ui(), MAX_SESSION_S, binary=DEFAULT_BINARY, spawn=spawn)
    results["nothing spawned before start"] = ui.alive is False

    ui.start()
    time.sleep(STARTUP_S)
    results["focus unchanged with the indicator up"] = focused() == before

    # One scripted session, as the daemon drives it.
    ui.show()
    ui.meta(mode="dictate", app="check", hotkey="")
    ui.state("recording")
    ui.render(polished="Polished text.", pending="pending words", live="live words")
    time.sleep(STARTUP_S)

    during = focused()
    surfaces = layer_surfaces()
    print(f"focused during      : {describe_focus()}")
    for namespace, found in surfaces.items():
        for s in found:
            where = f"{s.get('x')},{s.get('y')} {s.get('w')}x{s.get('h')}"
            print(f"layer surface       : {namespace} at {where}")
    clients = flowd_clients()
    print(f"focusable windows   : {len(clients)} (want 0)")

    results["child is running"] = ui.alive is True
    for namespace, found in surfaces.items():
        results[f"{namespace} is a layer surface"] = len(found) >= 1
        values = interactivity(found)
        if values is None:
            print(f"interactivity       : {namespace}: not reported by this compositor")
        else:
            print(f"interactivity       : {namespace}: {values} (want all 0)")
            results[f"{namespace} takes no keyboard"] = all(v == 0 for v in values)
    results["flowd-ui is not a focusable window"] = len(clients) == 0
    results["focus unchanged while shown"] = during == before

    # A session's worth of previews: `render` runs on every STT event and
    # `level` at 20 Hz.
    for i in range(20):
        ui.level(rms_db=-30.0 + i, peak_db=-20.0 + i)
        ui.render(polished="Polished text.", pending="pending words", live=f"partial {i}")
        time.sleep(0.05)
    results["child survives a session of renders"] = ui.alive is True

    ui.state("finishing")
    time.sleep(0.2)
    ui.end("done", fade=True)
    time.sleep(1.0)
    results["focus unchanged after the session"] = focused() == before
    results["popup gone after the fade"] = not layer_surfaces()["flowd-popup"]

    ui.stop()
    time.sleep(0.5)
    codes = [child.poll() for child in children]
    print(f"child exit codes    : {codes} (0 means it obeyed `quit` rather than SIGTERM)")
    results["stop reaps the child"] = all(code is not None for code in codes)
    results["child exits on `quit`, not a signal"] = codes == [0]
    results["no layer surface left behind"] = not any(layer_surfaces().values())
    results["focus unchanged at the end"] = focused() == before

    print()
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
