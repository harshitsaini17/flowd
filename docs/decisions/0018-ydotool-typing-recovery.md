# 0018: Bounded ydotool typing and key recovery

Status: proposed

Date: 2026-10-25

## Context

On an Ubuntu GNOME Wayland laptop, a clipboard read timed out and flowd fell
back to `ydotool type`. The 200-character typing subprocess then exceeded
`run()`'s five-second deadline. The user's E key kept repeating until an
explicit `ydotool key 18:0` released it. The user confirmed that the keyboard
returned to normal after the release.

The installed package is `ydotool 1.0.4-3`. Read-only inspection with
`ydotool type --help` reports these defaults:

```text
-d, --key-delay=N   Delay N milliseconds between keys (default: 20)
-H, --key-hold=N    Hold each key for N milliseconds (default: 20)
```

At those defaults, 200 characters need approximately 8,000 ms before command
startup or modifier overhead. Chunking by 200 characters therefore does not
keep this backend within the five-second subprocess deadline. A timeout can
terminate the sender between a key-down event and its matching key-up.

## Decision

Keep the 200-character chunks and five-second subprocess deadline, and pass
explicit 2 ms key-delay and 2 ms key-hold options to `ydotool type`. The base
delay for 200 characters becomes approximately 800 ms, leaving headroom for
startup and modifier events. Keep escape processing disabled and text after
the argv option terminator.

If typing raises, stop sending subsequent chunks and attempt a release of
keyboard codes 1 through 255 using `ydotool key -d 0`. Send only key-up events;
mouse-button codes start at 256. This repairs held letters and modifiers
without relying on the subprocess to have reached its release event.

If recovery also fails, log that failure without hiding the original typing
failure. Do not include the typing subprocess's argv in the normal failure
message, because it contains the dictated text.

## Verification and limits

The new deadline and recovery tests fail against the original implementation.
The regression tests use a fake runner: they exercise both first- and
second-chunk failures, key-up-only recovery, recovery failure, literal text,
and successful multi-chunk ordering without a microphone or compositor.

The nominal delay calculation is not a measured application throughput claim.
Real target-app delivery needs a user-operated desktop test. Recovery is
best effort if ydotoold itself becomes unavailable, and cannot run after a
hard kill of the entire flowd process.

On the affected laptop, the full suite passed 1,063 tests with one browser
group skipped. Ruff, formatting, and strict mypy passed. A separate real-tool
probe simulated the typing failure without emitting any characters, then
successfully sent all 255 key-up events through the recovery path.

Clipboard image preservation and the cleanup model/guardrails are unchanged.
