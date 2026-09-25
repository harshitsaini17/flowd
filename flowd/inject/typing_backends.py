"""Typing backends: wtype, ydotool, xdotool (spec 5.7).

Each sends the text as one argv element after a `--` terminator. Dictation is
arbitrary text that can begin with a dash, and every one of these tools parses
its argv for options: `wtype "--version"` exits with "Missing argument to
--version" rather than typing anything.
"""

from __future__ import annotations

import os

from flowd.inject.base import TYPE_CHUNK_CHARS, Runner, have, run


def _chunks(text: str, size: int = TYPE_CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


class _TypingBackend:
    name = "typing"
    tool = ""

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def available(self) -> bool:
        return have(self.tool)

    def _argv(self, chunk: str) -> list[str]:
        raise NotImplementedError

    def inject(self, text: str, *, is_terminal: bool) -> None:
        # is_terminal is irrelevant: typing backends send characters, not a paste key.
        for chunk in _chunks(text):
            self._run(self._argv(chunk))


class WtypeBackend(_TypingBackend):
    name = "wtype"
    tool = "wtype"

    def available(self) -> bool:
        return have(self.tool) and bool(os.environ.get("WAYLAND_DISPLAY"))

    def _argv(self, chunk: str) -> list[str]:
        return ["wtype", "--", chunk]


class YdotoolBackend(_TypingBackend):
    name = "ydotool"
    tool = "ydotool"

    def _argv(self, chunk: str) -> list[str]:
        # `-e 0` disables escape processing. ydotool's own --help: "Escape is
        # enabled by default when typing command line arguments", so a dictated
        # `\n` or `\t` would otherwise be typed as a newline or a tab instead of
        # the two characters the speaker said.
        return ["ydotool", "type", "-e", "0", "--", chunk]


class XdotoolBackend(_TypingBackend):
    name = "xdotool"
    tool = "xdotool"

    def available(self) -> bool:
        return have(self.tool) and bool(os.environ.get("DISPLAY"))

    def _argv(self, chunk: str) -> list[str]:
        return ["xdotool", "type", "--clearmodifiers", "--", chunk]
