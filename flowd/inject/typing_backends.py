"""Typing backends: wtype, ydotool, xdotool (spec 5.7).

Each sends the text as one argv element after a `--` terminator. Dictation is
arbitrary text that can begin with a dash, and every one of these tools parses
its argv for options: `wtype "--version"` exits with "Missing argument to
--version" rather than typing anything.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flowd.inject.base import TYPE_CHUNK_CHARS, Runner, have, run

log = logging.getLogger(__name__)


def _chunks(text: str, size: int = TYPE_CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _ydotool_socket() -> Path:
    """Where ydotool will look for ydotoold: $YDOTOOL_SOCKET, else the runtime dir."""
    explicit = os.environ.get("YDOTOOL_SOCKET")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / ".ydotool_socket"


class _TypingBackend:
    name = "typing"
    tool = ""

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def available(self) -> bool:
        return self.unavailable_reason() is None

    def unavailable_reason(self) -> str | None:
        """Why this backend cannot run here, or None when it can (logged on fall-through)."""
        if not have(self.tool):
            return f"{self.tool} is not installed"
        return None

    def _argv(self, chunk: str) -> list[str]:
        raise NotImplementedError

    def inject(self, text: str, *, is_terminal: bool) -> None:
        # is_terminal is irrelevant: typing backends send characters, not a paste key.
        for chunk in _chunks(text):
            self._run(self._argv(chunk))


class WtypeBackend(_TypingBackend):
    name = "wtype"
    tool = "wtype"

    def unavailable_reason(self) -> str | None:
        if not os.environ.get("WAYLAND_DISPLAY"):
            return "not a Wayland session"
        return super().unavailable_reason()

    def _argv(self, chunk: str) -> list[str]:
        return ["wtype", "--", chunk]


class YdotoolBackend(_TypingBackend):
    name = "ydotool"
    tool = "ydotool"

    def unavailable_reason(self) -> str | None:
        missing = super().unavailable_reason()
        if missing:
            return missing
        # Without the daemon `ydotool type` still exits 0 on some builds while
        # typing nothing, so the socket is checked before the backend's turn
        # is spent (spec 9.4). Setup is the user's; nothing runs as root here.
        sock = _ydotool_socket()
        if not sock.exists():
            return f"ydotoold is not running (no socket at {sock})"
        return None

    def _argv(self, chunk: str) -> list[str]:
        # `-e 0` disables escape processing. ydotool's own --help: "Escape is
        # enabled by default when typing command line arguments", so a dictated
        # `\n` or `\t` would otherwise be typed as a newline or a tab instead of
        # the two characters the speaker said.
        # Version 1.0.4 defaults to 20 ms held + 20 ms between keys: a
        # 200-character chunk needs 8 s, beyond run()'s 5 s deadline. Explicit
        # 2 ms delays leave headroom without emitting a burst of zero-delay keys.
        return ["ydotool", "type", "-d", "2", "-H", "2", "-e", "0", "--", chunk]

    def inject(self, text: str, *, is_terminal: bool) -> None:
        try:
            super().inject(text, is_terminal=is_terminal)
        except Exception as exc:
            # Killing `type` between key down and key up leaves that virtual
            # key repeating. Release keyboard codes only (mouse buttons start
            # at 256), including modifiers. No key is pressed by this cleanup.
            try:
                self._run(["ydotool", "key", "-d", "0", *(f"{k}:0" for k in range(1, 256))])
            except Exception as release_exc:
                log.warning(
                    "could not release virtual keyboard keys (%s)", type(release_exc).__name__
                )
            # Subprocess errors contain argv and therefore dictated text.
            # Keep that out of the ordinary injection-failure log.
            raise RuntimeError(f"ydotool typing failed ({type(exc).__name__})") from exc


class XdotoolBackend(_TypingBackend):
    name = "xdotool"
    tool = "xdotool"

    def unavailable_reason(self) -> str | None:
        if not os.environ.get("DISPLAY"):
            return "no X display"
        return super().unavailable_reason()

    def _argv(self, chunk: str) -> list[str]:
        return ["xdotool", "type", "--clearmodifiers", "--", chunk]
