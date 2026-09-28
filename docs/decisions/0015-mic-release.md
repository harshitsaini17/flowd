# 0015: flowd never holds the microphone while idle

**Status:** accepted (2026-09-28)

## Context

A report from use: with flowd running, other applications could not use the
microphone. `AudioCapture` already opens the stream on start and closes it on
stop (`flowd/audio.py`), and `always_open` is off by default, so this is not
the designed behaviour. It has not been reproduced yet. Likely causes, in the
order they will be checked:

1. `_release()` abandons a stream whose stop blocks past `RELEASE_WAIT_S`
   (250 ms). An abandoned stream can hold the device until the process exits.
2. PortAudio opening a raw ALSA `hw:` device, which is exclusive, instead of
   going through PipeWire.
3. PortAudio probing every ALSA device when `sounddevice` is first imported.
4. Another flowd process, such as an old overlay or a mic test, holding it.

## Decision

- **Idle means no capture stream.** While idle, `pactl list source-outputs`
  lists nothing from flowd and another program can record at the same time.
  This is an acceptance check after daemon start, after a session, after a
  cancel, after device loss and after resume from suspend.
- **PipeWire or PulseAudio only**, never a raw `hw:` device, unless the user
  names one in `audio.device`. The daemon logs the host API and device it
  opened.
- **An abandoned stream is not left behind.** If a stream does not stop in
  time, the daemon logs it, raises a warning on the indicator and settings
  page, and restarts itself through systemd at the next idle moment, which
  frees the device.
- **PortAudio loads lazily**, on the first dictation, not at daemon start.
- **The recording look follows the stream.** The indicator is red only while a
  stream is open, driven by the stream's own state rather than the session's.

## Consequences

- A regression test drives the fake stream factory through each case above and
  asserts no stream stays open while idle.
- `docs/edge-cases.md` gets a manual check: record with `arecord` while flowd
  is idle.
