"""Overlay child-process management (spec 4, 9.5).

The overlay is a separate process because GTK wants the main thread and because
its crash must not take a dictation with it (ADR 0003). That makes this file's
whole job error suppression: every failure is logged and swallowed, so a missing
interpreter, a compositor without layer-shell, or a child that segfaults
mid-sentence costs the user their preview and nothing else.

The child is spawned plainly, with no special environment. It needs
`LD_PRELOAD` to become a layer surface, but it arranges that itself by
re-executing once, because a requirement living in the spawner fails silently
when a spawner forgets it (ADR 0003).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flowd.config import Overlay as OverlayCfg

log = logging.getLogger(__name__)

#: The overlay needs pacman's python-gobject, which is not in the venv (ADR 0003).
SYSTEM_PYTHON = "/usr/bin/python3"

DEFAULT_SCRIPT = Path(__file__).resolve().parent.parent / "overlay" / "flowd_overlay.py"

#: Consecutive spawns that died immediately before we stop trying. `render` runs
#: on every STT event, so an overlay that cannot start would otherwise have the
#: daemon forking ten times a second, competing for the cores STT needs.
MAX_SPAWN_FAILURES = 3

#: How long `stop` waits for the child to act on `quit` before signalling it.
#: Short on purpose: this runs while the daemon is shutting down, usually
#: because the user pressed Ctrl-C and wants it gone. Quitting is an
#: `idle_add` and a main loop return, so a healthy overlay needs far less.
QUIT_GRACE_S = 1.0


class OverlayProcess:
    """The daemon's half of the overlay protocol (spec 4.4).

    Nothing is spawned until the first message: `main` builds this at daemon
    start, long before a dictation exists, and a user who never presses the
    hotkey should never pay for a GTK process.
    """

    def __init__(
        self,
        cfg: OverlayCfg,
        script: Path | None = None,
        python: str = SYSTEM_PYTHON,
        spawn: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._cfg = cfg
        self._script = script or DEFAULT_SCRIPT
        self._python = python
        self._spawn = spawn
        self._proc: Any = None
        self._failures = 0

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # --- protocol (spec 4.4) ---

    def show(self) -> None:
        """Start a session's preview.

        Also the moment to forgive a failed overlay: the user may have installed
        the package or moved to a compositor that supports layer-shell, and a
        daemon that runs for weeks should not stay preview-less for the rest of
        its life because of one bad minute.
        """
        self._failures = 0
        self._send({"type": "show"})

    def hide(self) -> None:
        self._send({"type": "hide"})

    def fade(self) -> None:
        self._send({"type": "fade"})

    def render(self, **zones: str) -> None:
        self._send({"type": "render", **zones})

    def stop(self) -> None:
        """Shut the child down. Never starts one: there is nothing to tell to
        quit, and a daemon on its way out should not fork on the way."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        self._write(proc, {"type": "quit"})
        try:
            # `quit` is in the protocol and the overlay obeys it, so let it: GTK
            # drops its layer surface itself instead of being cut off mid-frame.
            # Signalling in the same breath as the message would make `quit`
            # dead weight, since the child would be on SIGTERM before it had
            # read a byte.
            proc.wait(timeout=QUIT_GRACE_S)
            log.debug("overlay exited on request")
            return
        except Exception as exc:
            log.debug("overlay ignored quit (%s); terminating", exc)
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception as exc:  # a child that will not die must not block exit
            log.debug("overlay did not exit cleanly: %s", exc)

    # --- internals ---

    def _ensure(self) -> bool:
        """Return whether there is a live child to write to, spawning if needed."""
        if not self._cfg.enabled:
            return False
        if self.alive:
            return True
        if self._failures >= MAX_SPAWN_FAILURES:
            return False
        if not self._script.exists():
            # `python3 /missing.py` spawns happily and exits 2, so without this
            # check the failure is invisible: writes land in a pipe buffer that
            # nobody is reading and the user sees no preview and no reason why.
            log.warning("overlay script not found at %s; continuing without it", self._script)
            self._failures = MAX_SPAWN_FAILURES
            return False
        try:
            self._proc = self._spawn(
                [
                    self._python,
                    str(self._script),
                    # On argv rather than in the protocol: the child applies
                    # `max_lines` while building its labels, before it can have
                    # read a message. The overlay defaults to the same values,
                    # so a hand-launched one still behaves (ADR 0003).
                    "--max-lines",
                    str(self._cfg.max_lines),
                    "--fade-ms",
                    str(self._cfg.fade_ms),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
            )
        except (OSError, ValueError) as exc:
            log.warning("could not start overlay: %s", exc)
            self._proc = None
            self._failures += 1
            return False
        log.debug("overlay started")
        return True

    def _send(self, message: dict[str, Any]) -> None:
        if not self._ensure():
            return
        self._write(self._proc, message)

    def _write(self, proc: Any, message: dict[str, Any]) -> None:
        """One line of JSON. `json.dumps` escapes newlines inside the values, so
        a multi-line preview stays a single message the child can parse."""
        payload = json.dumps(message).encode("utf-8") + b"\n"
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError, ValueError) as exc:
            log.warning("overlay died (%s); continuing without it", exc)
            if proc is self._proc:
                self._proc = None
                self._failures += 1
