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
    """spec 9.1: two commands within debounce_ms count as one."""
    m = machine(clock_values=[0.0, 0.05, 1.0])  # seconds
    assert m.handle(Event.START) is Action.OPEN_MIC
    assert m.handle(Event.STOP) is None  # 50 ms later, debounced
    assert m.state is State.RECORDING


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
