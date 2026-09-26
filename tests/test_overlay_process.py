"""Tests for the overlay child process (spec 5.8).

The overlay's contract is a process boundary, not a Python API: it runs on the
*system* interpreter with pacman's PyGObject, outside this venv, so nothing here
can import it. These tests drive it the way the daemon does — newline-delimited
JSON on stdin — and check the properties that do not need a compositor.

The acceptance criterion (the overlay never takes keyboard focus) cannot be
automated without a compositor and a focused client to steal focus from; it is
verified by hand on Hyprland and recorded in ADR 0003.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay" / "flowd_overlay.py"
SYSTEM_PYTHON = "/usr/bin/python3"
HAS_DISPLAY = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
HAS_SYSTEM_PYTHON = Path(SYSTEM_PYTHON).exists()
# Must match the overlay's own constant; ADR 0003 explains why a preload is
# the only way layer-shell reaches a PyGObject process.
PRELOAD_LIB = "/usr/lib/libgtk4-layer-shell.so"

# Everything the overlay is allowed to import beyond the standard library. `gi`
# is pacman's PyGObject; Pango and GLib arrive through `gi.repository`, which
# is not a real import path and so never appears here.
ALLOWED_THIRD_PARTY = {"gi"}

needs_display = pytest.mark.skipif(not HAS_DISPLAY, reason="needs a compositor")
needs_system_python = pytest.mark.skipif(not HAS_SYSTEM_PYTHON, reason=f"no {SYSTEM_PYTHON}")


def run_overlay(
    messages: str, timeout: int = 20, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Drive the overlay exactly as the daemon does: JSON lines on stdin."""
    return subprocess.run(
        [SYSTEM_PYTHON, str(OVERLAY)],
        input=messages,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def layer_shell_available() -> bool:
    """Whether this session can host a layer surface at all.

    Asked of a preloaded interpreter, because that is the only kind of process in
    which the answer can be yes — see ADR 0003.
    """
    probe = (
        "import gi; gi.require_version('Gtk4LayerShell', '1.0');"
        "from gi.repository import Gtk4LayerShell as LS;"
        "raise SystemExit(0 if LS.is_supported() else 1)"
    )
    try:
        return (
            subprocess.run(
                [SYSTEM_PYTHON, "-c", probe],
                capture_output=True,
                env={**os.environ, "LD_PRELOAD": PRELOAD_LIB},
                timeout=30,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def imported_roots() -> set[str]:
    """Top-level module names the overlay imports, read from its syntax tree.

    An AST walk rather than a substring search: the property under test is that
    every import resolves on a bare system interpreter, and a blacklist of a few
    names cannot say that — it passes any dependency nobody thought to ban.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(OVERLAY.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_overlay_imports_only_the_stdlib_and_gi() -> None:
    """It runs on the system interpreter, so it cannot import from the venv.

    `flowd` itself is the one that would be easiest to reach for and would fail
    only at runtime, on the user's machine, with the overlay already spawned.
    """
    outside = imported_roots() - sys.stdlib_module_names - ALLOWED_THIRD_PARTY
    assert outside == set(), f"overlay imports unavailable outside the venv: {outside}"


@needs_system_python
def test_overlay_compiles_under_the_system_interpreter() -> None:
    result = subprocess.run(
        [SYSTEM_PYTHON, "-m", "py_compile", str(OVERLAY)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@needs_system_python
def test_overlay_is_executable_with_a_shebang() -> None:
    """The daemon spawns it as a child; a missing bit or shebang fails at spawn."""
    assert os.access(OVERLAY, os.X_OK), "overlay is not executable"
    assert OVERLAY.read_text().startswith("#!"), "overlay has no shebang"


@needs_system_python
@needs_display
def test_overlay_exits_on_quit_message() -> None:
    proc = run_overlay('{"type": "show"}\n{"type": "render", "live": "hi"}\n{"type": "quit"}\n')
    assert proc.returncode == 0, proc.stderr
    # Nothing may go to stdout. The daemon does not drain it, so a chatty
    # overlay would eventually fill the pipe and block on its own print.
    assert proc.stdout == "", proc.stdout


@needs_system_python
@needs_display
def test_overlay_survives_malformed_input() -> None:
    """A bad line must be logged and skipped, never crash the child.

    Every shape that is valid JSON but not a message is here too: the daemon is
    the only writer today, and an overlay that dies on a malformed line takes
    the preview down for the rest of the session.
    """
    proc = run_overlay(
        "not json\n"
        '{"type": "nonsense"}\n'
        "[1, 2, 3]\n"
        '"just a string"\n'
        "null\n"
        "\n"
        '{"no_type": true}\n'
        '{"type": "render"}\n'  # no zones at all
        '{"type": "render", "live": null}\n'
        '{"type": "quit"}\n'
    )
    assert proc.returncode == 0, proc.stderr


@needs_system_python
@needs_display
def test_overlay_exits_when_its_stdin_closes() -> None:
    """The daemon died or dropped us, so there is nobody left to preview for.

    Without this the overlay outlives the daemon, and spec 5.8's crash isolation
    turns into a window the user cannot get rid of.
    """
    proc = run_overlay("")
    assert proc.returncode == 0, proc.stderr


@needs_system_python
@needs_display
def test_overlay_renders_before_being_shown() -> None:
    """`render` arriving first must not be an error.

    The daemon sends `show` on session start and renders on each event, but the
    order is not guaranteed by anything in the protocol, and a first partial
    dropped because `show` had not arrived yet would be invisible to debug.
    """
    proc = run_overlay('{"type": "render", "live": "early"}\n{"type": "quit"}\n')
    assert proc.returncode == 0, proc.stderr


needs_layer_shell = pytest.mark.skipif(
    not (HAS_SYSTEM_PYTHON and HAS_DISPLAY and layer_shell_available()),
    reason="needs a compositor with wlr-layer-shell",
)


@needs_layer_shell
def test_overlay_becomes_a_layer_surface_that_refuses_focus() -> None:
    """The acceptance criterion, as far as it can be automated (spec 5.8).

    Exiting cleanly proves nothing about focus: `init_for_window()` returns
    without error even when it did not work, leaving an ordinary toplevel that
    takes focus the moment it is shown (ADR 0003). So this asserts the overlay
    reached the layered state — the state in which the compositor has been told
    to refuse it keyboard focus — rather than merely surviving.

    That the focused window is genuinely unchanged is verified by hand on
    Hyprland with `hyprctl` and recorded in ADR 0003; no compositor-agnostic
    interface reports it.
    """
    proc = run_overlay('{"type": "show"}\n{"type": "render", "live": "x"}\n{"type": "quit"}\n')
    assert proc.returncode == 0, proc.stderr
    assert "layer-shell surface, keyboard focus refused" in proc.stderr, proc.stderr
    assert "overlay disabled" not in proc.stderr, proc.stderr


@needs_system_python
@needs_display
def test_overlay_disables_itself_when_layer_shell_is_unavailable() -> None:
    """spec 5.8: no layer-shell means no overlay, not an unlayered window.

    Setting the re-exec guard is how a caller reaches the unpreloaded path on a
    machine that does support layer-shell; it leaves the process in the same
    state GNOME Wayland and X11 do. The overlay must still consume its input and
    exit 0 — the daemon carries on dictating, just without a preview.
    """
    proc = run_overlay(
        '{"type": "show"}\n{"type": "render", "live": "x"}\n{"type": "quit"}\n',
        env={"FLOWD_OVERLAY_PRELOADED": "1", "LD_PRELOAD": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert "overlay disabled" in proc.stderr, proc.stderr
