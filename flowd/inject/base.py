"""Injection backend protocol and shared subprocess helpers (spec 5.7)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

#: Typing backends are given at most this many characters per invocation.
TYPE_CHUNK_CHARS = 200

Runner = Callable[..., Any]


def run(
    argv: Sequence[str],
    *,
    input: bytes | None = None,  # shadows the builtin to mirror subprocess.run's own name
    capture: bool = True,
    timeout: float = 5.0,
) -> Any:
    """Run a command with an argv list.

    Never uses a shell: dictated text is arbitrary, and `shell=True` would make
    a spoken sentence executable.

    `capture=False` sends stdout and stderr to /dev/null instead of to pipes.
    Clipboard owners such as `wl-copy` and `xclip -i` fork a background process
    that must survive to serve paste requests, and that child inherits the
    pipes. Nothing then reaches EOF, so a captured `wl-copy` blocks until
    `timeout` and raises, instead of returning in a fraction of a second.
    """
    redirect: dict[str, Any] = (
        {"capture_output": True}
        if capture
        else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    )
    # An argv list with shell=False by construction: there is no shell to which
    # the text could be syntax.
    return subprocess.run(
        list(argv),
        input=input,
        timeout=timeout,
        check=True,
        **redirect,
    )


@dataclass(frozen=True, slots=True)
class InjectResult:
    ok: bool
    backend: str | None = None
    error: str | None = None


@runtime_checkable
class Backend(Protocol):
    name: str

    def available(self) -> bool:
        """True when this backend's tools exist and its session type matches."""

    def inject(self, text: str, *, is_terminal: bool) -> None:
        """Deliver text to the focused window, or raise on failure."""


def have(tool: str) -> bool:
    return shutil.which(tool) is not None
