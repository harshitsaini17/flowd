from collections.abc import Callable
from subprocess import CalledProcessError
from typing import Any

import pytest

from flowd.config import Inject
from flowd.inject import InjectResult, inject_text
from flowd.inject.clipboard import ClipboardBackend
from flowd.inject.typing_backends import WtypeBackend, XdotoolBackend, YdotoolBackend

#: What `wl-paste --list-types` really prints for a text clipboard, captured
#: from this machine. Every entry must be recognised as text, or injection
#: would refuse to touch an ordinary clipboard.
WAYLAND_TEXT_TYPES = (
    b"text/plain\ntext/plain\ntext/plain;charset=utf-8\nTEXT\nSTRING\nUTF8_STRING\n"
)

#: The X11 equivalent. `xclip -t TARGETS -o` lists *selection targets*, not
#: MIME types, and ICCCM requires TARGETS while TIMESTAMP and MULTIPLE are
#: conventional on every toolkit. None of them name a data format.
X11_TEXT_TARGETS = b"TIMESTAMP\nTARGETS\nMULTIPLE\nSTRING\nUTF8_STRING\ntext/plain\n"


class Recorder:
    """Captures subprocess invocations instead of running them."""

    def __init__(
        self,
        *,
        types: bytes = WAYLAND_TEXT_TYPES,
        fail_on: Callable[[list[str]], bool] | None = None,
        error: Callable[[list[str]], Exception] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.stdins: list[bytes | None] = []
        self._types = types
        self._fail_on = fail_on
        # Which exception a failing call raises, because the kind is the whole
        # signal: `FileNotFoundError` means the tool never ran, while
        # `CalledProcessError` means it ran and reported a non-zero exit. A
        # recorder that could only raise one of them could not tell the
        # clipboard code's two branches apart.
        self._error = error or (lambda argv: FileNotFoundError(f"{argv[0]} not installed"))

    def run(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append(list(argv))
        self.kwargs.append(dict(kwargs))
        self.stdins.append(kwargs.get("input"))
        # Recorded before raising, so a test can assert what was attempted as
        # well as what came back. A recorder that can never fail would leave
        # every cleanup path in `inject` untested.
        if self._fail_on is not None and self._fail_on(argv):
            raise self._error(argv)
        listing = "--list-types" in argv or "TARGETS" in argv
        stdout = self._types if listing else b"previous clipboard"

        class Completed:
            returncode = 0

            def __init__(self, out: bytes) -> None:
                self.stdout = out

        return Completed(stdout)

    def kwargs_for(self, tool: str, *, occurrence: int = 0) -> dict[str, Any]:
        """The kwargs of the nth invocation of `tool`."""
        matches = [kw for argv, kw in zip(self.calls, self.kwargs, strict=True) if argv[0] == tool]
        return matches[occurrence]

    def stdins_where(self, predicate: Callable[[list[str]], bool]) -> list[bytes | None]:
        """Every matching call's stdin, in call order.

        Paired positionally rather than looked up by argv: the two clipboard
        writes have identical argv, so `calls.index()` would return the first
        one twice and the restore assertion would silently test the set step.
        """
        return [
            stdin for argv, stdin in zip(self.calls, self.stdins, strict=True) if predicate(argv)
        ]


def clipboard_writes(rec: Recorder, *, wayland: bool) -> list[bytes | None]:
    """Stdin of every call that *writes* the clipboard, in call order.

    Identified by flags, not by tool name: `xclip` reads with `-o` and writes
    with `-i`, so matching on `argv[0]` alone picks up the snapshot read as well
    and the assertion drifts by one.
    """
    if wayland:
        return rec.stdins_where(lambda argv: argv[0] == "wl-copy")
    return rec.stdins_where(lambda argv: argv[0] == "xclip" and "-i" in argv)


def wayland_clipboard(rec: Recorder, **kw: Any) -> ClipboardBackend:
    kw.setdefault("ydotool", lambda: True)
    return ClipboardBackend(runner=rec.run, sleep=lambda _s: None, wayland=True, **kw)


def x11_clipboard(rec: Recorder, **kw: Any) -> ClipboardBackend:
    return ClipboardBackend(runner=rec.run, sleep=lambda _s: None, wayland=False, **kw)


TypingBackend = type[WtypeBackend] | type[YdotoolBackend] | type[XdotoolBackend]

DANGEROUS = "text; rm -rf ~ && echo $(whoami) `id` | tee /tmp/x\nsecond line"


# --- Dictated text must never reach a shell ---------------------------------


@pytest.mark.parametrize("wayland", [True, False])
def test_clipboard_never_uses_a_shell(wayland: bool) -> None:
    """Dictated text must never be interpolated into a shell command."""
    rec = Recorder(types=WAYLAND_TEXT_TYPES if wayland else X11_TEXT_TARGETS)
    ClipboardBackend(runner=rec.run, sleep=lambda _s: None, wayland=wayland).inject(
        DANGEROUS, is_terminal=False
    )
    assert rec.calls, "the backend must have run something"
    for argv in rec.calls:
        assert isinstance(argv, list), "argv must be a list, never a shell string"
        assert DANGEROUS not in " ".join(argv), "text must go via stdin, not argv"


def test_clipboard_passes_text_on_stdin() -> None:
    rec = Recorder()
    wayland_clipboard(rec).inject(DANGEROUS, is_terminal=False)
    assert DANGEROUS.encode() in [s for s in rec.stdins if s is not None]


@pytest.mark.parametrize(
    ("backend_cls", "tool"),
    [(WtypeBackend, "wtype"), (YdotoolBackend, "ydotool"), (XdotoolBackend, "xdotool")],
)
def test_typing_backend_passes_text_as_single_argv_element(
    backend_cls: TypingBackend, tool: str
) -> None:
    rec = Recorder()
    backend_cls(runner=rec.run).inject("a; rm -rf ~", is_terminal=False)
    assert rec.calls[0][0] == tool
    assert "a; rm -rf ~" in rec.calls[0]


@pytest.mark.parametrize("backend_cls", [WtypeBackend, YdotoolBackend, XdotoolBackend])
def test_typing_backend_ends_options_before_the_text(backend_cls: TypingBackend) -> None:
    """Dictation can start with a dash; without `--` it would be read as a flag.

    Verified against the real binaries: `wtype "--version"` fails with
    "Missing argument to --version", while `wtype -- "--version"` gets as far as
    the compositor. The text must always follow a `--` terminator.
    """
    rec = Recorder()
    backend_cls(runner=rec.run).inject("--version", is_terminal=False)
    argv = rec.calls[0]
    assert "--" in argv, "options must be terminated before arbitrary text"
    assert argv.index("--") == len(argv) - 2, "`--` must sit immediately before the text"


def test_ydotool_disables_escape_processing() -> None:
    r"""`ydotool type` interprets backslash escapes in argv text by default.

    Its own --help says "Escape is enabled by default when typing command line
    arguments", so a dictated Windows path or code snippet containing `\n` would
    be typed as a newline. `-e 0` turns that off and keeps the text literal.
    """
    rec = Recorder()
    YdotoolBackend(runner=rec.run).inject(r"C:\new\table", is_terminal=False)
    argv = rec.calls[0]
    assert "-e" in argv and argv[argv.index("-e") + 1] == "0"
    assert argv[-1] == r"C:\new\table"


# --- Clipboard snapshot and restore -----------------------------------------


def test_clipboard_restores_previous_text_on_wayland() -> None:
    rec = Recorder()
    wayland_clipboard(rec).inject("new", is_terminal=False)
    written = rec.stdins_where(lambda argv: argv[0] == "wl-copy")
    assert written == [b"new", b"previous clipboard"], "set the text, then restore the snapshot"


def test_clipboard_restores_previous_text_on_x11() -> None:
    """The X11 path must work without a Wayland session; CI has neither."""
    rec = Recorder(types=X11_TEXT_TARGETS)
    x11_clipboard(rec).inject("new", is_terminal=False)
    assert not any(c[0].startswith("wl-") for c in rec.calls), "must not call Wayland tools"
    written = rec.stdins_where(lambda argv: argv[0] == "xclip" and "-i" in argv)
    assert written == [b"new", b"previous clipboard"], "set the text, then restore the snapshot"


@pytest.mark.parametrize(("wayland", "paste_tool"), [(True, "wtype"), (False, "xdotool")])
def test_clipboard_is_restored_when_the_paste_keystroke_fails(
    wayland: bool, paste_tool: str
) -> None:
    """The snapshot must come back even when the paste step raises.

    This is the case where restore matters most and the only one where it can
    be skipped: the dictated text is already on the clipboard by then, so an
    exception between setting and restoring leaves the user's clipboard
    holding our text permanently. `inject_text` catches the exception and falls
    through to a typing backend, so the user still gets their text and never
    learns their clipboard was eaten (spec 5.7 step 4, spec 14.2).
    """
    rec = Recorder(
        types=WAYLAND_TEXT_TYPES if wayland else X11_TEXT_TARGETS,
        fail_on=lambda argv: argv[0] == paste_tool,
    )
    backend = (wayland_clipboard if wayland else x11_clipboard)(rec)
    with pytest.raises(FileNotFoundError):
        backend.inject("new", is_terminal=False)
    written = clipboard_writes(rec, wayland=wayland)
    assert written == [b"new", b"previous clipboard"], "clipboard left holding the dictated text"


def test_clipboard_declines_when_the_paste_tool_is_missing() -> None:
    """`available()` must check the tool that sends the keystroke, not only the
    one that writes the clipboard.

    On Wayland the two are different packages: `wl-copy` ships in
    `wl-clipboard` and the keystroke needs `wtype`. Claiming availability with
    `wtype` absent spends this backend's turn in `inject.order` and touches the
    user's clipboard for a paste that cannot happen — which is exactly what the
    comment in `available()` already says it exists to avoid.
    """
    rec = Recorder()
    backend = wayland_clipboard(rec, have=lambda tool: tool == "wl-copy")
    assert backend.available() is False, "claimed available without the paste tool"
    assert rec.calls == [], "touched the clipboard while merely reporting availability"


def test_clipboard_declines_without_the_tool_that_reads_the_clipboard() -> None:
    """`available()` must also check the tool it reads the clipboard *with*.

    Snapshotting is what makes this backend safe to use at all, and on Wayland
    the read is `wl-paste` while the write is `wl-copy` — two commands, not one.
    With `wl-paste` unusable the backend can neither see what it is about to
    destroy nor put it back, so it must not take its turn.

    In practice both ship in `wl-clipboard`, so this exact combination is rare;
    it is checked because `available()` claims to check the tools it invokes,
    and because the same read failing at call time (below) needs no missing
    package at all.
    """
    rec = Recorder()
    backend = wayland_clipboard(rec, have=lambda tool: tool != "wl-paste")
    assert backend.available() is False, "claimed available without the clipboard read tool"
    assert rec.calls == [], "touched the clipboard while merely reporting availability"


def test_clipboard_declines_when_the_type_listing_cannot_run() -> None:
    """A listing that never ran leaves the clipboard's contents unknowable.

    Proceeding would overwrite an unknown payload — possibly an image, which
    spec 9.4 forbids destroying — with no snapshot to restore, so the dictated
    text would sit on the user's clipboard permanently. Declining hands the
    turn to a typing backend, which still delivers the text.
    """
    rec = Recorder(fail_on=lambda argv: "--list-types" in argv)
    with pytest.raises(RuntimeError, match="could not read the clipboard"):
        wayland_clipboard(rec).inject("new", is_terminal=False)
    assert clipboard_writes(rec, wayland=True) == [], "overwrote a clipboard it could not read"


def test_clipboard_proceeds_when_the_clipboard_is_empty() -> None:
    """An empty clipboard is not a failure, and must not be treated as one.

    `wl-paste --list-types` exits non-zero with "Nothing is copied" when the
    clipboard is empty — the same failing exit as a tool that is broken. The
    difference is that this one *ran*, so what it reports is true: there is
    nothing to preserve, and nothing to restore afterwards. Discriminating on
    failure alone would make this backend decline on the commonest case there
    is, which is why the exception kind is what decides.
    """
    rec = Recorder(
        fail_on=lambda argv: "--list-types" in argv,
        error=lambda argv: CalledProcessError(1, argv, stderr=b"Nothing is copied"),
    )
    wayland_clipboard(rec).inject("new", is_terminal=False)
    assert clipboard_writes(rec, wayland=True) == [b"new"], "declined on an empty clipboard"


@pytest.mark.parametrize("wayland", [True, False])
def test_clipboard_declines_when_the_snapshot_cannot_be_read(wayland: bool) -> None:
    """Text is on the clipboard, but reading it back failed.

    The listing already proved there is a payload, so this is not the empty
    case and no exception kind excuses it: without the snapshot there is
    nothing to restore, and overwriting it would destroy the user's clipboard
    permanently. This needs no missing package — one timed-out read is enough.
    """
    read_argv = (
        ["wl-paste", "--no-newline"] if wayland else ["xclip", "-selection", "clipboard", "-o"]
    )
    rec = Recorder(
        types=WAYLAND_TEXT_TYPES if wayland else X11_TEXT_TARGETS,
        fail_on=lambda argv: argv == read_argv,
        error=lambda argv: CalledProcessError(1, argv),
    )
    backend = wayland_clipboard(rec) if wayland else x11_clipboard(rec)
    with pytest.raises(RuntimeError, match="could not read the clipboard"):
        backend.inject("new", is_terminal=False)
    assert clipboard_writes(rec, wayland=wayland) == [], "overwrote a clipboard it could not save"


def test_x11_selection_targets_are_recognised_as_text() -> None:
    """`xclip -t TARGETS -o` lists atoms like TIMESTAMP, TARGETS and MULTIPLE.

    Those are selection targets, not MIME types, and every X11 clipboard offers
    them. Judging them "non-text" would make the clipboard backend refuse every
    ordinary X11 clipboard and fall through to a typing backend every time.
    """
    rec = Recorder(types=X11_TEXT_TARGETS)
    x11_clipboard(rec).inject("hello", is_terminal=False)
    assert any(c[0] == "xclip" and "-i" in c for c in rec.calls), "clipboard was refused"


def test_clipboard_refuses_when_clipboard_holds_an_image() -> None:
    """spec 9.4: never destroy non-text clipboard contents."""
    rec = Recorder(types=b"image/png\ntext/plain\n")
    with pytest.raises(RuntimeError, match="non-text"):
        wayland_clipboard(rec).inject("hello", is_terminal=False)
    assert not any(c[0] == "wl-copy" for c in rec.calls)


def test_empty_clipboard_is_not_an_error() -> None:
    """Nothing to snapshot means nothing to restore, not a refusal."""
    rec = Recorder(types=b"")
    wayland_clipboard(rec).inject("hello", is_terminal=False)
    copies = [c for c in rec.calls if c[0] == "wl-copy"]
    assert len(copies) == 1, "no snapshot to restore, so exactly one copy"


def test_copy_does_not_capture_the_subprocess_output() -> None:
    """`wl-copy` and `xclip -i` fork a daemon that holds the clipboard open.

    Verified against the real binaries: with `capture_output=True` the forked
    daemon inherits the pipes, nothing ever reaches EOF, and `subprocess.run`
    blocks until its timeout. With the output discarded, wl-copy returns in
    0.27s and xclip in 0.07s. Capturing here would make every clipboard
    injection take the full timeout and then fail, so the copy step must
    discard its output.
    """
    rec = Recorder()
    wayland_clipboard(rec).inject("hello", is_terminal=False)
    assert rec.kwargs_for("wl-copy").get("capture") is False


def test_reading_the_clipboard_still_captures_stdout() -> None:
    """The listing and paste steps are read for their output, so they capture."""
    rec = Recorder()
    wayland_clipboard(rec).inject("hello", is_terminal=False)
    assert rec.kwargs_for("wl-paste")["capture"] is not False


def test_terminal_uses_ctrl_shift_v() -> None:
    rec = Recorder()
    x11_clipboard(rec).inject("hi", is_terminal=True)
    keys = [c for c in rec.calls if c[0] == "xdotool"]
    assert keys == [["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"]]


def test_wayland_terminal_paste_goes_through_ydotool() -> None:
    """kitty ignores Shift from wtype's virtual keyboard, so wtype's Ctrl+Shift+V
    is a silent no-op there (checked live, kitty 0.48). Kernel events from
    ydotool arrive with the modifier intact."""
    rec = Recorder()
    wayland_clipboard(rec).inject("hi", is_terminal=True)
    keys = [c for c in rec.calls if c[0] in ("wtype", "ydotool")]
    # KEY_LEFTCTRL 29, KEY_LEFTSHIFT 42, KEY_V 47: press in order, release reversed.
    assert keys == [["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]]


def test_wayland_terminal_without_ydotool_leaves_the_clipboard_alone() -> None:
    """Without a working paste key the text must reach a typing backend, and the
    clipboard must not be touched on the way."""
    rec = Recorder()
    backend = wayland_clipboard(rec, ydotool=lambda: False)
    with pytest.raises(RuntimeError, match="ydotool"):
        backend.inject("hi", is_terminal=True)
    assert rec.calls == []


def test_wayland_terminal_without_ydotool_falls_through_to_typing() -> None:
    rec = Recorder()
    typed = Recorder()
    result = inject_text(
        "hi",
        Inject(order=("clipboard", "wtype")),
        backends=[wayland_clipboard(rec, ydotool=lambda: False), _AlwaysWtype(typed)],
        is_terminal=True,
    )
    assert result.backend == "wtype"
    assert typed.calls == [["wtype", "--", "hi"]]


class _AlwaysWtype(WtypeBackend):
    def __init__(self, rec: Recorder) -> None:
        super().__init__(runner=rec.run)

    def available(self) -> bool:
        return True


def test_a_browser_copy_is_recognised_as_text() -> None:
    """Captured from this machine after copying text in Brave: Chromium lists
    its own bookkeeping entries next to the text."""
    types = (
        b"text/plain\ntext/plain;charset=utf-8\nUTF8_STRING\n"
        b"chromium/x-internal-source-rfh-token\ntext/plain;charset=utf-8\n"
        b"TEXT\nSTRING\nchromium/x-source-url\n"
    )
    rec = Recorder(types=types)
    wayland_clipboard(rec).inject("hi", is_terminal=False)
    assert clipboard_writes(rec, wayland=True) == [b"hi", b"previous clipboard"]


def test_non_terminal_paste_has_no_shift() -> None:
    rec = Recorder()
    wayland_clipboard(rec).inject("hi", is_terminal=False)
    keys = [c for c in rec.calls if c[0] in ("wtype", "xdotool")]
    assert keys and not any("shift" in " ".join(c).lower() for c in keys)


def test_clipboard_availability_follows_the_session_type() -> None:
    """The session type decides which tools are needed, and pasting needs all of them.

    On Wayland that is three commands from two packages — `wl-copy` and
    `wl-paste` write and read the clipboard, `wtype` sends the keystroke — while
    on X11 `xclip` does both halves of the clipboard work. Reporting available
    and then calling a tool that is not installed would burn the clipboard
    backend's turn in `inject.order` on a FileNotFoundError — and for the
    keystroke half it would do so *after* overwriting the clipboard.
    """
    rec = Recorder()

    def having(*tools: str) -> Callable[[str], bool]:
        return lambda tool: tool in tools

    assert x11_clipboard(rec, have=having("xclip", "xdotool")).available() is True
    assert wayland_clipboard(rec, have=having("wl-copy", "wl-paste", "wtype")).available() is True
    # The other session's tools, however completely installed.
    assert wayland_clipboard(rec, have=having("xclip", "xdotool")).available() is False
    assert x11_clipboard(rec, have=having("wl-copy", "wl-paste", "wtype")).available() is False
    # Half-installed: the clipboard tools present, the keystroke tool absent.
    assert wayland_clipboard(rec, have=having("wl-copy", "wl-paste")).available() is False
    assert x11_clipboard(rec, have=having("xclip")).available() is False
    assert rec.calls == [], "availability must not touch the clipboard"


# --- Ordered fallthrough ----------------------------------------------------


def test_falls_through_to_next_backend_on_failure() -> None:
    class Failing:
        name = "clipboard"

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise RuntimeError("no clipboard tool")

    class Working:
        name = "wtype"
        used = False

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            type(self).used = True

    result = inject_text(
        "hi", Inject(order=("clipboard", "wtype")), backends=[Failing(), Working()]
    )
    assert result == InjectResult(ok=True, backend="wtype", error=None)
    assert Working.used


def test_reports_failure_when_every_backend_fails() -> None:
    class Failing:
        name = "clipboard"

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise RuntimeError("nope")

    result = inject_text("hi", Inject(order=("clipboard",)), backends=[Failing()])
    assert result.ok is False
    assert result.error is not None and "nope" in result.error


def test_unavailable_backend_is_skipped() -> None:
    class Absent:
        name = "clipboard"

        def available(self) -> bool:
            return False

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise AssertionError("must not be called")

    assert inject_text("hi", Inject(order=("clipboard",)), backends=[Absent()]).ok is False


def test_order_is_honoured_not_the_backend_list_order() -> None:
    """`inject.order` is the user's preference; the backend list is just a pool."""
    used: list[str] = []

    class Stub:
        def __init__(self, name: str) -> None:
            self.name = name

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            used.append(self.name)

    result = inject_text(
        "hi", Inject(order=("xdotool", "clipboard")), backends=[Stub("clipboard"), Stub("xdotool")]
    )
    assert used == ["xdotool"]
    assert result.backend == "xdotool"


def test_unknown_backend_name_in_order_is_ignored() -> None:
    """A typo in `inject.order` must not silence the backends that do exist."""

    class Stub:
        name = "wtype"

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            pass

    result = inject_text("hi", Inject(order=("nonsense", "wtype")), backends=[Stub()])
    assert result == InjectResult(ok=True, backend="wtype", error=None)


def test_long_text_is_chunked_for_typing_backends() -> None:
    rec = Recorder()
    WtypeBackend(runner=rec.run).inject("x" * 450, is_terminal=False)
    assert len(rec.calls) == 3  # 200-char chunks (spec 5.7)
    assert "".join(c[-1] for c in rec.calls) == "x" * 450, "chunking must not lose characters"


def test_empty_text_injects_nothing() -> None:
    rec = Recorder()
    result = inject_text("", Inject(), backends=[ClipboardBackend(runner=rec.run)])
    assert result.ok is True
    assert rec.calls == []


# --- Logged fall-through reasons (spec 9.4) ---------------------------------


def test_an_unavailable_backend_logs_why_it_was_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Absent:
        name = "ydotool"

        def available(self) -> bool:
            return False

        def unavailable_reason(self) -> str:
            return "ydotoold is not running"

        def inject(self, text: str, *, is_terminal: bool) -> None:
            raise AssertionError("must not be called")

    with caplog.at_level("INFO", logger="flowd.inject"):
        result = inject_text("hi", Inject(order=("ydotool",)), backends=[Absent()])
    assert result.error == "ydotool: ydotoold is not running"
    assert "ydotool" in caplog.text
    assert "ydotoold is not running" in caplog.text


def test_typing_backends_name_the_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    # The session checks come first, so pin a session: CI runners have neither.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("flowd.inject.typing_backends.have", lambda tool: False)
    assert WtypeBackend().unavailable_reason() == "wtype is not installed"
    assert XdotoolBackend().unavailable_reason() == "xdotool is not installed"


def test_wtype_needs_a_wayland_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flowd.inject.typing_backends.have", lambda tool: True)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert WtypeBackend().available() is False
    assert WtypeBackend().unavailable_reason() == "not a Wayland session"


def test_ydotool_needs_the_ydotoold_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """spec 9.4: ydotool without ydotoold is a fall-through, not a failed paste."""
    monkeypatch.setattr("flowd.inject.typing_backends.have", lambda tool: True)
    monkeypatch.setenv("YDOTOOL_SOCKET", str(tmp_path / "missing.sock"))
    backend = YdotoolBackend()
    assert backend.available() is False
    assert "ydotoold" in (backend.unavailable_reason() or "")

    sock = tmp_path / "live.sock"
    sock.touch()
    monkeypatch.setenv("YDOTOOL_SOCKET", str(sock))
    assert backend.available() is True
    assert backend.unavailable_reason() is None


def test_ydotool_finds_the_default_socket_in_the_runtime_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr("flowd.inject.typing_backends.have", lambda tool: True)
    monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / ".ydotool_socket").touch()
    assert YdotoolBackend().available() is True


def test_clipboard_names_the_missing_tools() -> None:
    backend = wayland_clipboard(Recorder(), have=lambda tool: tool == "wl-copy")
    assert backend.unavailable_reason() == "missing wl-paste, wtype"


def _order_recorder() -> tuple[list[str], list[Any]]:
    used: list[str] = []

    class Stub:
        def __init__(self, name: str) -> None:
            self.name = name

        def available(self) -> bool:
            return True

        def inject(self, text: str, *, is_terminal: bool) -> None:
            used.append(self.name)

    return used, [Stub("clipboard"), Stub("xdotool")]


def test_non_ascii_text_prefers_the_clipboard_on_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    """spec 9.4: `xdotool type` mangles Unicode, so X11 pastes it instead."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    used, pool = _order_recorder()
    inject_text("café", Inject(order=("xdotool", "clipboard")), backends=pool)
    assert used == ["clipboard"]


def test_ascii_text_keeps_the_configured_order_on_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    used, pool = _order_recorder()
    inject_text("cafe", Inject(order=("xdotool", "clipboard")), backends=pool)
    assert used == ["xdotool"]


def test_non_ascii_text_keeps_the_configured_order_on_wayland(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    used, pool = _order_recorder()
    inject_text("café", Inject(order=("xdotool", "clipboard")), backends=pool)
    assert used == ["xdotool"]
