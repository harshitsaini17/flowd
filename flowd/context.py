"""Which app has focus, and what that means for cleanup and paste (spec 5.6).

Read once, at session start: spec 9.4 keeps the mode chosen then even if focus
moves during dictation. Every failure is None, never an exception, because
not knowing the app only costs the `default` mode.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flowd.config import Config

log = logging.getLogger(__name__)

#: The query runs on the `start` path, before the microphone opens.
_TIMEOUT_S = 0.5

Runner = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AppContext:
    app_id: str | None
    mode: str
    is_terminal: bool


def _run(argv: list[str]) -> Any:
    # Fixed argv, no shell, nothing from the user in it.
    return subprocess.run(argv, capture_output=True, timeout=_TIMEOUT_S, check=True)


def _sway_focused(node: Mapping[str, Any]) -> str | None:
    if node.get("focused"):
        app_id = node.get("app_id")
        if app_id:
            return str(app_id)
        cls = (node.get("window_properties") or {}).get("class")  # XWayland window
        return str(cls) if cls else None
    for child in [*node.get("nodes", []), *node.get("floating_nodes", [])]:
        found = _sway_focused(child)
        if found is not None:
            return found
    return None


def focused_app_id(env: Mapping[str, str] | None = None, runner: Runner = _run) -> str | None:
    """The focused window's app id, or None when it cannot be told.

    Hyprland and Sway are asked directly; any other X11 or XWayland session
    falls back to `xdotool`. KDE and GNOME on Wayland have no unprivileged
    query, so they get None and the default mode (spec 5.6).
    """
    env = os.environ if env is None else env
    try:
        if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            out = runner(["hyprctl", "activewindow", "-j"]).stdout
            cls = json.loads(out).get("class")
            return str(cls) if cls else None
        if env.get("SWAYSOCK"):
            out = runner(["swaymsg", "-t", "get_tree"]).stdout
            return _sway_focused(json.loads(out))
        if env.get("DISPLAY"):
            out = runner(["xdotool", "getactivewindow", "getwindowclassname"]).stdout
            name = out.decode("utf-8", "replace").strip()
            return name or None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as exc:
        log.debug("focused app unknown: %s", exc)
    return None


def detect(cfg: Config, env: Mapping[str, str] | None = None, runner: Runner = _run) -> AppContext:
    """The session's app id, cleanup mode and paste style."""
    app_id = focused_app_id(env, runner)
    if app_id is None:
        return AppContext(None, "default", False)
    key = app_id.casefold()
    # Case-insensitive: X11 reports "Thunderbird" where Wayland says
    # "thunderbird", and a user writing [modes] should not need to know which.
    modes = {k.casefold() for k, _ in cfg.modes}
    terminals = {t.casefold() for t in cfg.inject.terminal_apps}
    is_terminal = key in terminals
    # spec 7.3 chooses code mode for terminals; [modes] can still say otherwise.
    mode = cfg.mode_for(app_id) if key in modes else ("code" if is_terminal else "default")
    return AppContext(app_id, mode, is_terminal)
