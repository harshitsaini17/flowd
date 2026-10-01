# 0014: A settings page served by the daemon on loopback

**Status:** accepted (2026-09-28)

## Context

Every setting lives in `~/.config/flowd/config.toml` and `vocab.toml`, edited
by hand. The design adds a settings web page (`docs/design/settings.html`)
with auto-save, live status and statistics. A browser page cannot write files,
so something local has to serve it and save changes.

A separate settings process and a native settings window were considered. The
daemon already owns config validation, reload and status, so it serves the
page.

## Decision

- The daemon runs a small HTTP/1.1 server on its asyncio loop, standard library
  only, bound to `127.0.0.1` (never `0.0.0.0`). Port `[settings] port`,
  default 8178. If the port is taken, the page is off, dictation is
  unaffected, and the reason is logged.
- `flowctl settings` requests a token over the control socket and opens
  `http://127.0.0.1:8178/#token=…` with `xdg-open`. The token is in the
  fragment, so browsers never send or log it.
- Every `/api/` request must pass all three checks, or gets `403`:
  1. `Authorization: Bearer <token>`, compared in constant time. Tokens are 32
     random bytes; each `flowctl settings` issues a new one and they live only
     in daemon memory.
  2. `Host` is `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding).
  3. `Origin` is absent or equals the page's own origin (cross-site requests).
- Static assets are served without a token. Every response carries
  `Content-Security-Policy: default-src 'self'`; the page loads nothing from
  another origin.
- Config is written with `tomlkit` (pinned exact version), which keeps comments
  and ordering. Writes are atomic (temp file + rename). A `PATCH` carries the
  etag it read; if the file changed on disk since, the server returns `409`
  and writes nothing. Values are validated by the same code as `config.py`
  before anything is written.
- API:

  | Endpoint | Purpose |
  | --- | --- |
  | `GET /api/config` | Values, defaults, live-or-restart per key, etag |
  | `PATCH /api/config` | Change keys; validate, write, reload |
  | `GET /api/status` | Daemon, models, cleanup, anonymous memory per process |
  | `GET /api/stats` | Overview numbers from `metrics.jsonl` |
  | `GET` / `PATCH /api/vocab` | `vocab.toml`, same rules as config |
  | `POST /api/vocab/test` | Run `basic_clean` on a sample sentence |
  | `POST /api/mic-test` | Open the mic ≤ 15 s, stream levels (server-sent events) |
  | `POST /api/detect-app` | Return the focused app id after 3 s |
  | `GET /api/inject-backends` | Which paste tools are installed and running |
  | `POST /api/restart` | Restart `flowd-ui`, or the daemon via systemd |

- New config: `[settings] enabled = true`, `port = 8178`, and
  `[llm] enabled = true` (false always pastes rule-based text).
- The page is the design's `settings.html` with its assets, served from the
  package. If the daemon stops while the page is open, the page turns
  read-only and says so; it cannot save without the daemon.

## Consequences

- A listening TCP socket on loopback while the daemon runs, which the privacy
  statement must mention. `[settings] enabled = false` removes it.
- New runtime dependency: `tomlkit`.
- Tests cover each of the three checks, the `409` conflict, invalid values,
  atomic writes, and that comments survive a save.

## Notes from building it

- The CSP stays strict (no `unsafe-inline`); the inline `style="…"` attributes
  the design called for were moved to CSS classes instead.
- The microphone test uses the daemon's own capture (`Daemon.mic_test`), so
  there is one device path, not a second one for the page; a dictation that
  starts mid-test preempts it.
- Tokens survive a daemon restart through a 0600 file in `$XDG_RUNTIME_DIR`
  (`/tmp/flowd-<uid>` when that variable is unset) that is adopted only if it
  is younger than 60 s, a regular file, owned by our uid and unreachable by
  anyone else; it is deleted once read either way.
- One request per connection; there is no keep-alive.
- Devices are listed through a short-lived PortAudio session
  (`audio.input_devices`), opened for the query and released straight after,
  the same as after a dictation (ADR 0015).

The token itself travels in the URL fragment (`#token=…`), which browsers
never send to a server or log; the page reads it with `location.hash` and then
strips it from the address bar with `history.replaceState`. That only hides it
from the visible bar — the browser's own history can still hold the full URL,
same as any other fragment-carried secret. The token is a loopback-only
credential good for one `flowctl settings` launch, and the daemon keeps the
newest 8 so an old tab doesn't go stale the moment a new one opens.

A daemon restart from the page runs
`systemctl --user --no-block restart flowd.service`, and the "Restart flowd"
action is only offered when flowd is running under systemd
(`INVOCATION_ID` set) — there is nobody to start it again otherwise. Before
restarting, the daemon writes its live tokens to
`$XDG_RUNTIME_DIR/settings-tokens.json` (mode 0600) so the open tab stays
signed in once the new process comes up and adopts them.

Each section's "Reset to defaults" clears only that section's keys through
`POST /api/config/reset`; "Reset all" clears the whole file the same way with
no section given.
