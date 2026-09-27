from flowd.suspend import SleepDetector


class Clocks:
    """Monotonic and boot-time clocks; boot time alone runs during suspend."""

    def __init__(self) -> None:
        self.mono = 100.0
        self.boot = 100.0

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.boot += seconds

    def sleep(self, seconds: float) -> None:
        self.boot += seconds


def detector(clocks: Clocks) -> SleepDetector:
    return SleepDetector(monotonic=lambda: clocks.mono, boottime=lambda: clocks.boot)


def test_ordinary_time_passing_is_not_a_suspend() -> None:
    clocks = Clocks()
    d = detector(clocks)
    d.arm()
    clocks.advance(600)
    assert d.slept() is False


def test_a_suspend_longer_than_five_seconds_is_detected() -> None:
    """spec 9.1: a monotonic clock jump > 5 s means the machine slept."""
    clocks = Clocks()
    d = detector(clocks)
    d.arm()
    clocks.advance(2)
    clocks.sleep(30)
    assert d.slept() is True


def test_a_short_stall_is_tolerated() -> None:
    clocks = Clocks()
    d = detector(clocks)
    d.arm()
    clocks.sleep(4)
    assert d.slept() is False


def test_rearming_forgets_an_earlier_suspend() -> None:
    """Sleeping while idle must not cancel the next session."""
    clocks = Clocks()
    d = detector(clocks)
    d.arm()
    clocks.sleep(60)
    d.arm()
    clocks.advance(1)
    assert d.slept() is False
