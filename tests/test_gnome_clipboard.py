"""GNOME can paste immediately through ydotool without wtype's protocol."""

from flowd.inject.clipboard import ClipboardBackend
from tests.test_inject import Recorder, clipboard_writes


def backend(
    rec: Recorder,
    *,
    ready: bool = True,
    x_display: bool = False,
    tools: frozenset[str] = frozenset({"wl-copy", "wl-paste", "ydotool"}),
) -> ClipboardBackend:
    return ClipboardBackend(
        runner=rec.run,
        sleep=lambda _: None,
        wayland=True,
        gnome=True,
        have=lambda tool: tool in tools,
        ydotool=lambda: ready,
        x_display=x_display,
    )


XWAYLAND_TOOLS = frozenset({"wl-copy", "wl-paste", "xclip", "ydotool"})


def test_gnome_clipboard_uses_ctrl_v_and_restores_the_original() -> None:
    rec = Recorder()
    paste = backend(rec)
    assert paste.available()
    paste.inject("A complete sentence.", is_terminal=False)
    assert ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"] in rec.calls
    assert not any(call[0] == "wtype" for call in rec.calls)
    assert clipboard_writes(rec, wayland=True) == [b"A complete sentence.", b"previous clipboard"]


def test_gnome_terminal_paste_keeps_shift() -> None:
    rec = Recorder()
    backend(rec).inject("echo hello", is_terminal=True)
    assert ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"] in rec.calls


def test_gnome_clipboard_declines_before_touching_clipboard_without_the_daemon() -> None:
    rec = Recorder()
    paste = backend(rec, ready=False)
    assert not paste.available()
    assert "ydotoold" in (paste.unavailable_reason() or "")
    assert not rec.calls


def test_gnome_with_xwayland_uses_the_x11_selection_and_never_wl_clipboard() -> None:
    """Mutter has no data-control protocol, so wl-copy and wl-paste map a window
    and wait for focus on every call. XWayland's CLIPBOARD is the same selection
    without that, so the paste neither moves focus nor hangs."""
    rec = Recorder(types=b"UTF8_STRING\nTARGETS\n")
    paste = backend(rec, x_display=True, tools=XWAYLAND_TOOLS)
    assert paste.available()
    paste.inject("A complete sentence.", is_terminal=False)
    assert not any(call[0] in {"wl-copy", "wl-paste"} for call in rec.calls)
    assert ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"] in rec.calls
    assert ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"] in rec.calls
    assert clipboard_writes(rec, wayland=False) == [b"A complete sentence.", b"previous clipboard"]


def test_gnome_xwayland_paste_still_refuses_to_overwrite_an_image() -> None:
    rec = Recorder(types=b"image/png\nTARGETS\nTIMESTAMP\n")
    paste = backend(rec, x_display=True, tools=XWAYLAND_TOOLS)
    try:
        paste.inject("text", is_terminal=False)
    except RuntimeError as exc:
        assert "non-text" in str(exc)
    else:
        raise AssertionError("an image clipboard was overwritten")
    assert clipboard_writes(rec, wayland=False) == []


def test_gnome_without_xclip_keeps_wl_clipboard() -> None:
    rec = Recorder()
    backend(rec, x_display=True).inject("text", is_terminal=False)
    assert any(call[0] == "wl-copy" for call in rec.calls)
    assert not any(call[0] == "xclip" for call in rec.calls)


def test_gnome_without_an_x_display_keeps_wl_clipboard() -> None:
    rec = Recorder()
    backend(rec, x_display=False, tools=XWAYLAND_TOOLS).inject("text", is_terminal=False)
    assert any(call[0] == "wl-copy" for call in rec.calls)
