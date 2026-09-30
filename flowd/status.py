"""Process memory, paste-tool availability and desktop name for the settings page."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from flowd.config import Inject
from flowd.inject import default_backends

#: Known desktop names `desktop()` recognises in `XDG_CURRENT_DESKTOP`, casefolded.
_KNOWN_DESKTOPS = frozenset({"hyprland", "sway", "kde", "gnome"})

#: How each process is recognised: its executable's name, then a script
#: argument. Copied from scripts/idle_check.py's `PATTERNS`/`find()`, since
#: scripts/ isn't importable from the package; kept in sync by hand.
_PATTERNS = {
    "flowd": ("python", "/bin/flowd"),
    "flowd-ui": ("flowd-ui", ""),
    "llama-server": ("llama-server", ""),
}


@dataclass(frozen=True, slots=True)
class ProcMem:
    name: str
    pid: int
    anon_mb: float


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def _rss_anon_mb(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("RssAnon:"):
            return float(line.split()[1]) / 1024
    return 0.0


def memory() -> list[ProcMem]:
    """Anonymous memory of the flowd, flowd-ui and llama-server processes, via /proc.

    Matching logic copied from scripts/idle_check.py's `PATTERNS`/`find()`.
    """
    me = os.getpid()
    found: list[ProcMem] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        pid = int(entry.name)
        argv = _cmdline(pid).split()
        if len(argv) < 1:
            continue
        exe, script = os.path.basename(argv[0]), argv[1] if len(argv) > 1 else ""
        for name, (exe_prefix, script_suffix) in _PATTERNS.items():
            if exe.startswith(exe_prefix) and script.endswith(script_suffix):
                with contextlib.suppress(OSError):  # exited while we looked
                    found.append(ProcMem(name, pid, _rss_anon_mb(pid)))
                break
    return found


def backends(order: tuple[str, ...]) -> list[dict[str, str]]:
    """Paste-tool availability, in `order`, for the settings page's status panel."""
    pool = {b.name: b for b in default_backends(Inject(order=order))}
    result: list[dict[str, str]] = []
    for name in order:
        backend = pool.get(name)
        if backend is None:
            continue
        reason = backend.unavailable_reason() if hasattr(backend, "unavailable_reason") else None
        if reason is None:
            status = "available"
        elif "not running" in reason:
            status = "stopped"
        else:
            status = "missing"
        entry: dict[str, str] = {"name": name, "status": status}
        if reason is not None:
            entry["reason"] = reason
        result.append(entry)
    return result


def desktop() -> str:
    """Lowercased XDG_CURRENT_DESKTOP first known token, else x11 or other."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    for token in raw.split(":"):
        folded = token.casefold()
        if folded in _KNOWN_DESKTOPS:
            return folded
    if not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
        return "x11"
    return "other"
