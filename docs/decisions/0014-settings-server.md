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
