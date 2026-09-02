"""Clipboard injection with snapshot and restore (spec 5.7)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from flowd.inject.base import Runner, run
from flowd.inject.base import have as _tool_exists

log = logging.getLogger(__name__)

#: Text formats we consider safe to overwrite and restore. Anything offered
#: under `text/` is text; the bare atoms are X11's pre-MIME spellings.
_TEXT_MIME_PREFIX = "text/"
_TEXT_ATOMS = frozenset({"TEXT", "STRING", "UTF8_STRING", "COMPOUND_TEXT"})

#: Selection targets that name no data format at all. `xclip -t TARGETS -o`
#: lists these alongside the real formats: TARGETS is required of every ICCCM
#: selection owner, and TIMESTAMP and MULTIPLE are offered by every toolkit.
#: Judging them by content type would make us refuse every X11 clipboard.
_SELECTION_METADATA = frozenset(
    {
        "TARGETS",
        "TIMESTAMP",
        "MULTIPLE",
        "SAVE_TARGETS",
        "DELETE",
        "INSERT_SELECTION",
        "INSERT_PROPERTY",
    }
)


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _is_text_format(offered: str) -> bool:
    return offered.startswith(_TEXT_MIME_PREFIX) or offered in _TEXT_ATOMS


class ClipboardBackend:
    """Set the clipboard, send a paste keystroke, then put back what was there.

    The session type and the tool lookup are injected rather than read from the
    environment at call time, so both the Wayland and the X11 path are
    exercisable on a machine (or a CI runner) that has only one of them.
    """

    name = "clipboard"

    def __init__(
        self,
        runner: Runner = run,
        sleep: Callable[[float], None] = time.sleep,
        restore_delay_ms: int = 150,
        *,
        wayland: bool | None = None,
        have: Callable[[str], bool] = _tool_exists,
    ) -> None:
        self._run = runner
        self._sleep = sleep
        self._restore_delay_s = restore_delay_ms / 1000.0
        self._wayland = _is_wayland() if wayland is None else wayland
        self._have = have

    def available(self) -> bool:
        # Checked per session type, not "either tool": reporting available and
        # then invoking a tool that is not installed would spend this backend's
        # turn in `inject.order` on a FileNotFoundError.
        #
        # Both tools, because pasting takes two of them and on Wayland they are
        # separate packages: `wl-copy` from wl-clipboard writes the clipboard,
        # `wtype` sends the keystroke. With only the first installed this
        # backend would set the clipboard for a paste that cannot happen, and
        # while `inject` now restores the snapshot either way, declining the
        # turn is better than touching the user's clipboard to no purpose.
        return all(self._have(tool) for tool in self._required_tools())

    def _required_tools(self) -> tuple[str, str]:
        """(clipboard tool, paste-keystroke tool) for this session type."""
        return ("wl-copy", "wtype") if self._wayland else ("xclip", "xdotool")

    def _tools(self) -> tuple[list[str], list[str], list[str]]:
        """Return (list-types, paste, copy) argv prefixes for this session type."""
        if self._wayland:
            return (["wl-paste", "--list-types"], ["wl-paste", "--no-newline"], ["wl-copy"])
        return (
            ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xclip", "-selection", "clipboard", "-i"],
        )

    def _send_paste(self, is_terminal: bool) -> None:
        keys = "ctrl+shift+v" if is_terminal else "ctrl+v"
        if not self._wayland:
            self._run(["xdotool", "key", "--clearmodifiers", keys])
            return
        *mods, key = keys.split("+")
        argv = ["wtype"]
        for mod in mods:
            argv += ["-M", mod]
        argv += ["-k", key]
        for mod in reversed(mods):
            argv += ["-m", mod]
        self._run(argv)

    def _set_clipboard(self, copy: list[str], payload: bytes) -> None:
        # `capture=False` is load-bearing: a clipboard owner forks a process
        # that must outlive this call to serve paste requests, and it inherits
        # our pipes. Captured, this blocks for the whole timeout and then fails.
        self._run(copy, input=payload, capture=False)

    def inject(self, text: str, *, is_terminal: bool) -> None:
        list_types, paste, copy = self._tools()

        types = ""
        try:
            types = self._run(list_types, capture=True).stdout.decode("utf-8", "replace")
        except Exception as exc:  # an empty clipboard is not an error
            log.debug("could not list clipboard types: %s", exc)

        offered = [t.strip() for t in types.splitlines() if t.strip()]
        formats = [t for t in offered if t not in _SELECTION_METADATA]
        if formats and not all(_is_text_format(t) for t in formats):
            # spec 9.4: never destroy an image or other non-text clipboard
            # payload. Raising hands the turn to the next backend in the order.
            raise RuntimeError(f"clipboard holds non-text data ({', '.join(formats)})")

        saved: bytes | None = None
        if formats:
            try:
                saved = self._run(paste, capture=True).stdout
            except Exception as exc:
                log.debug("could not snapshot clipboard: %s", exc)

        # `finally`, because everything from here on can raise and the snapshot
        # must go back regardless: once our text is on the clipboard, an
        # exception on the way out would leave it there permanently. Injection
        # then falls through to a typing backend, so the user gets their text
        # and never learns their clipboard was overwritten (spec 5.7 step 4).
        #
        # The set is inside the `try` rather than above it: if the copy tool can
        # ever fail *after* changing the clipboard, excluding it costs the user
        # their clipboard, while including it costs one misleading log line when
        # the tool was never able to run at all.
        try:
            self._set_clipboard(copy, text.encode("utf-8"))
            self._send_paste(is_terminal)
            # Only reached when the paste succeeded: the delay exists to let the
            # target read the clipboard, and nothing will read it otherwise.
            self._sleep(self._restore_delay_s)
        finally:
            if saved is not None:
                try:
                    self._set_clipboard(copy, saved)
                except Exception as exc:
                    log.warning("could not restore clipboard: %s", exc)
