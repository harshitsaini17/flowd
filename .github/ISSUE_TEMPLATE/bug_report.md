---
name: Bug report
about: Something does not work
labels: bug
---

**Before you paste anything:** logs and transcripts can contain what you
dictated. Please do not paste transcript text you would not want to be public,
and redact anything private from the journal output below. flowd does not log
transcripts by default, but `logging.log_transcripts = true` makes it, so check
if you have turned that on.

## What happened

What you did, what you expected, what happened instead.

## Environment

- flowd version (`flowd --version`):
- Compositor / desktop (Hyprland, Sway, KDE, GNOME, i3, …):
- Session type (`echo $XDG_SESSION_TYPE`):
- Distribution and kernel:
- Was `flowd-llm` running? (`systemctl --user status flowd-llm`):
- Which application were you dictating into?

## Steps to reproduce

1.
2.
3.

Does it happen every time, or intermittently?

## Logs

```
# paste the output of:
#   journalctl --user -u flowd -n 50
```

If the problem is that text landed in the wrong place or nowhere at all, the
backend flowd chose is the interesting part — it is named in the log, and
`flowctl last` will tell you whether the text was captured even though it was
never inserted.

## Anything else

Config changes you have made, other software that grabs the microphone or the
clipboard, a custom hotkey binding.
