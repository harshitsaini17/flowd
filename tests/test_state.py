from flowd.state import Action, Event, Machine, State


def machine(clock_values: list[float] | None = None, debounce_ms: int = 200) -> Machine:
    values = iter(clock_values or [i * 10.0 for i in range(1000)])
    return Machine(debounce_ms=debounce_ms, clock=lambda: next(values))


def test_starts_idle() -> None:
    assert machine().state is State.IDLE


def test_idle_start_opens_mic() -> None:
    m = machine()
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.state is State.RECORDING


def test_recording_stop_finalizes() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE
    assert m.state is State.FINALIZING


def test_recording_cancel_discards() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.CANCEL) is Action.DISCARD
    assert m.state is State.IDLE


def test_recording_max_duration_finalizes_like_stop() -> None:
    m = machine()
    m.handle(Event.START)
    assert m.handle(Event.MAX_DURATION) is Action.FLUSH_AND_FINALIZE
    assert m.state is State.FINALIZING


def test_finalizing_resolved_joins() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.CHUNKS_RESOLVED) is Action.JOIN
    assert m.state is State.INJECTING


def test_finalizing_cancel_discards() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.CANCEL) is Action.DISCARD
    assert m.state is State.IDLE


def test_injecting_done_returns_to_idle() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    m.handle(Event.CHUNKS_RESOLVED)
    assert m.handle(Event.INJECT_DONE) is Action.HIDE_OVERLAY
    assert m.state is State.IDLE


def test_start_is_ignored_while_finalizing() -> None:
    """spec 4: a start during FINALIZING is ignored and logged, never queued."""
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    assert m.handle(Event.START) is None
    assert m.state is State.FINALIZING


def test_start_is_ignored_while_injecting() -> None:
    m = machine()
    m.handle(Event.START)
    m.handle(Event.STOP)
    m.handle(Event.CHUNKS_RESOLVED)
    assert m.handle(Event.START) is None
    assert m.state is State.INJECTING


def test_double_press_within_debounce_is_one_command() -> None:
    """spec 9.1: two commands within debounce_ms count as one.

    Two presses of the *same* toggle key, which is what a key bounce or a
    fumbled double-tap produces. The second resolves to `stop`, and swallowing
    it is the point: a bounce must not end the session the first press began.
    """
    m = machine(clock_values=[0.0, 0.05, 1.0])  # seconds
    assert m.handle(Event.TOGGLE) is Action.OPEN_MIC
    assert m.handle(Event.TOGGLE) is None  # 50 ms later, debounced
    assert m.state is State.RECORDING


def test_a_quick_push_to_talk_tap_still_finalizes() -> None:
    """A short tap in `ptt` mode must not leave the microphone open.

    The compositor sends `start` on press and `stop` on release, so a tap
    shorter than `debounce_ms` delivers both inside the debounce window. These
    are two halves of one gesture, not a repeated one: spec 4 debounces "a
    `start` within 200 ms of the previous command", not a stop.

    Swallowing the release is unrecoverable from the user's side — the session
    stays in RECORDING with the mic open until `max_session_s` (default 300 s),
    and their next `start` is inside the window too, so it is debounced as well.
    The README's own `bindr`/`--release` bindings produce exactly this.
    """
    m = machine(clock_values=[0.0, 0.08, 1.0])
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE, "release swallowed; mic left open"
    assert m.state is State.FINALIZING


def test_a_repeated_start_within_debounce_is_still_swallowed() -> None:
    """The fix must not disarm debounce for the event the spec does name.

    Paired with the test above: that one proves `stop` gets through, this one
    proves `start` still does not, so neither assertion can pass by the
    debounce check having been removed altogether.
    """
    m = machine(clock_values=[0.0, 0.05, 1.0])
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.START) is None
    assert m.state is State.RECORDING


def test_stop_sets_the_debounce_window_for_the_next_start() -> None:
    """spec 4 measures the window from "the previous command", whatever it was.

    A press-release-press faster than the window is a retrigger, so the second
    `start` is debounced even though the command before it was a `stop`.

    The timings discriminate deliberately: the second `start` is 250 ms after
    the first (outside the window) but 100 ms after the `stop` (inside it), so
    this fails if `stop` is merely exempted from debounce instead of also
    recording when it happened.

    The session is driven back to IDLE before that second `start`, because
    `start` is ignored in FINALIZING anyway (spec 4) — asserting there would
    pass for that reason instead of the one under test. Neither intervening
    event is debounced, so neither consumes a clock reading.
    """
    m = machine(clock_values=[0.0, 0.15, 0.25])
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE
    assert m.handle(Event.CHUNKS_RESOLVED) is Action.JOIN
    assert m.handle(Event.INJECT_DONE) is Action.HIDE_OVERLAY
    assert m.state is State.IDLE, "prep did not return to idle"
    assert m.handle(Event.START) is None, "start 100 ms after the stop was not debounced"


def test_commands_outside_debounce_both_apply() -> None:
    m = machine(clock_values=[0.0, 0.5])
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is Action.FLUSH_AND_FINALIZE


def test_toggle_starts_then_stops() -> None:
    m = machine(clock_values=[0.0, 1.0])
    assert m.handle(Event.TOGGLE) is Action.OPEN_MIC
    assert m.handle(Event.TOGGLE) is Action.FLUSH_AND_FINALIZE


def test_fatal_error_from_any_state_releases_mic() -> None:
    """spec 4: the fatal row is "Any", so every state must release the mic."""
    paths = {
        State.IDLE: [],
        State.RECORDING: [Event.START],
        State.FINALIZING: [Event.START, Event.STOP],
        State.INJECTING: [Event.START, Event.STOP, Event.CHUNKS_RESOLVED],
    }
    for expected_state, prep in paths.items():
        m = machine()
        for event in prep:
            m.handle(event)
        assert m.state is expected_state, f"prep for {expected_state} did not arrive"
        assert m.handle(Event.FATAL) is Action.RELEASE_MIC
        assert m.state is State.IDLE


def test_stop_in_idle_is_ignored() -> None:
    m = machine()
    assert m.handle(Event.STOP) is None
    assert m.state is State.IDLE


def test_debounce_does_not_block_cancel() -> None:
    """Cancel is a safety valve and must never be swallowed by debounce."""
    m = machine(clock_values=[0.0, 0.01])
    m.handle(Event.START)
    assert m.handle(Event.CANCEL) is Action.DISCARD
