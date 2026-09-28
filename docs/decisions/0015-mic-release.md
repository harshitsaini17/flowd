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
- `docs/edge-cases.md` gets a manual check: record with `pw-record` while flowd
  is idle.
- PortAudio is terminated when a stream is released and no abandoned stop is
  still running, and re-initialised before the next open. While an abandoned
  stop runs it is inside `Pa_StopStream`, so PortAudio is kept; the skipped
  release happens once that stop finishes, checked while idle.
- A slow stop is not a stuck one. PortAudio's stop on a restarted audio
  server took 8 s live and then completed, so an abandoned stop gets
  `LEAK_GRACE_S` (10 s) to finish. Only one still running after that makes
  the daemon exit with code 5 once idle, so systemd restarts it and the
  device is freed. A PipeWire restart mid-dictation therefore does not
  restart flowd.
- That exit is `os._exit`, after flushing logs and stdio. A normal exit runs
  `sounddevice`'s atexit handler, whose `Pa_Terminate` could deadlock against
  the stop still in progress and keep the process, and so the device, alive.
- A failed open (device busy, permission denied, or `start()` failing) closes
  whatever stream was created and releases PortAudio before the error
  propagates, so the idle daemon holds no PipeWire client.
- The warning is a desktop notification until `flowd-ui` (ADR 0013) can show
  it.

## Findings

Measured 2026-09-28, this machine:

- The default input resolves to the ALSA `default` device (index 5), which
  routes through `pipewire-alsa`. With `audio.device = "default"` PortAudio
  does not open a raw `hw:` device, so cause 2 above is ruled out for the
  default config.
- `import sounddevice` runs `Pa_Initialize`, which registers a PipeWire JACK
  client and a node named `PortAudio` in state `running`, with 0 ports and no
  links. It stays until `Pa_Terminate` removes it; closing the stream alone
  leaves the client behind.
- Re-initialising PortAudio (`_terminate` then `_initialize`) costs about
  17 ms, added to mic open on the next session.
