"""The settings page's JSON API, served by `settings_server` (ADR 0014).

Routes map `(method, path)` to a coroutine. Every error reply is
`{"ok": false, "error": str}`; an unknown path is 404 and a known path with
the wrong method is 405.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, TypeGuard

from flowd import audio, config_edit, stats, status
from flowd.config import RESTART_KEYS, Config, applies
from flowd.config_edit import Conflict, Snapshot
from flowd.metrics import read_records
from flowd.settings_server import Reply, Stream
from flowd.textclean import basic_clean

#: The page's memory budget line, in MB of anonymous memory across processes.
BUDGET_MB = 1600
#: Longest text `POST /api/vocab/test` accepts.
MAX_TEST_TEXT = 2000
#: How many metrics records the stats overview reads ("All time").
STATS_RECORDS = 100_000


class Backend(Protocol):
    """What the API needs from the daemon."""

    cfg: Config
    config_file: Path
    vocab_file: Path

    @property
    def metrics_file(self) -> Path: ...

    @property
    def recording(self) -> bool:
        """True while a capture stream is open, including the idle stream kept
        when `audio.always_open` is true. Listing devices releases PortAudio,
        which would cut such a stream off, so it is refused while this holds."""
        ...

    async def reload(self) -> str | None:
        """Reload config and vocab; None, or the error text."""
        ...

    def daemon_status(self) -> dict[str, Any]:
        """`{"state", "stt_model", "final_model", "cleanup"}`."""
        ...


class Busy(Exception):
    """The microphone is in use by a dictation."""


Route = Callable[[dict[str, str], Any], Awaitable[Reply | Stream]]


def _ok(**body: Any) -> Reply:
    return Reply(200, {"ok": True, **body})


def _error(code: int, message: str, **extra: Any) -> Reply:
    return Reply(code, {"ok": False, "error": message, **extra})


def _io_error(verb: str, path: Path, exc: OSError) -> Reply:
    return _error(500, f"could not {verb} {path.name}: {exc.strerror or exc}")


def _comparable(value: Any) -> Any:
    """Config holds tuples where the JSON values hold lists."""
    if isinstance(value, tuple | list):
        return [_comparable(v) for v in value]
    return value


def _is_str_dict(value: Any) -> TypeGuard[dict[str, str]]:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


class SettingsApi:
    """The `Handler` behind the settings server.

    `restart_pending` holds the restart-only keys whose saved value differs
    from what the daemon is running. The running values are the `backend.cfg`
    seen at construction, i.e. the config the daemon started with: `reload`
    replaces `backend.cfg` even for restart-only keys, so comparing against
    the post-reload config would always clear the banner. It is recomputed
    over every restart-only key after each write, so a reset or a value set
    back to its running one drops out too.
    """

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._running = backend.cfg
        self.restart_pending: set[str] = set()
        self._routes: dict[tuple[str, str], Route] = {
            ("GET", "/api/config"): self._get_config,
            ("PATCH", "/api/config"): self._patch_config,
            ("POST", "/api/config/reset"): self._reset_config,
            ("GET", "/api/vocab"): self._get_vocab,
            ("PATCH", "/api/vocab"): self._patch_vocab,
            ("POST", "/api/vocab/test"): self._test_vocab,
            ("GET", "/api/stats"): self._stats,
            ("GET", "/api/status"): self._status,
            ("GET", "/api/inject-backends"): self._inject_backends,
        }
        self._paths = {path for _, path in self._routes}

    async def __call__(
        self, method: str, path: str, query: dict[str, str], body: Any
    ) -> Reply | Stream:
        route = self._routes.get((method, path))
        if route is not None:
            return await route(query, body)
        if path in self._paths:
            return _error(405, f"{method} is not allowed on {path}")
        return _error(404, f"no such endpoint: {path}")

    # -- config -------------------------------------------------------------

    def _update_pending(self, snapshot: Snapshot) -> None:
        pending: set[str] = set()
        for key in RESTART_KEYS:
            section, _, name = key.partition(".")
            saved = snapshot.values[section][name]
            running = getattr(getattr(self._running, section), name)
            if _comparable(saved) != _comparable(running):
                pending.add(key)
        self.restart_pending = pending

    def _config_reply(self, snapshot: Snapshot) -> Reply:
        keys = {
            f"{section}.{name}": applies(f"{section}.{name}")
            for section, values in snapshot.values.items()
            if section != "modes"
            for name in values
        }
        return _ok(
            etag=snapshot.etag,
            values=snapshot.values,
            defaults=config_edit.defaults(),
            in_file=snapshot.in_file,
            applies=keys,
            restart_pending=sorted(self.restart_pending),
        )

    def _config_conflict(self) -> Reply:
        path = self._backend.config_file
        try:
            current = config_edit.read_config(path).etag
        except OSError as exc:
            return _io_error("read", path, exc)
        except ValueError as exc:
            return _error(422, str(exc))
        return _error(409, "conflict", etag=current)

    async def _reload_after_write(self, etag: str) -> Reply | None:
        failure = await self._backend.reload()
        if failure is not None:
            # The file did change: the page needs the new etag to keep saving.
            return _error(500, f"saved, but flowd could not apply it: {failure}", etag=etag)
        return None

    async def _get_config(self, query: dict[str, str], body: Any) -> Reply:
        path = self._backend.config_file
        try:
            snapshot = config_edit.read_config(path)
        except OSError as exc:
            return _io_error("read", path, exc)
        except ValueError as exc:
            return _error(422, str(exc))
        return self._config_reply(snapshot)

    async def _patch_config(self, query: dict[str, str], body: Any) -> Reply:
        if not isinstance(body, dict) or not isinstance(body.get("etag"), str):
            return _error(422, "etag must be a string")
        changes = body.get("changes")
        if not isinstance(changes, dict):
            return _error(422, "changes must be an object of section.key to value")
        path = self._backend.config_file
        try:
            snapshot, applied = config_edit.patch_config(path, body["etag"], changes)
        except Conflict:
            return self._config_conflict()
        except OSError as exc:
            return _io_error("write", path, exc)
        except (ValueError, TypeError, AttributeError) as exc:
            # TypeError/AttributeError: a value of a type the validators did
            # not expect. The write never happened, so it is the body's fault.
            return _error(422, str(exc))
        self._update_pending(snapshot)
        failed = await self._reload_after_write(snapshot.etag)
        if failed is not None:
            return failed
        return _ok(
            applied=applied,
            etag=snapshot.etag,
            values=snapshot.values,
            restart_pending=sorted(self.restart_pending),
        )

    async def _reset_config(self, query: dict[str, str], body: Any) -> Reply:
        if not isinstance(body, dict) or not isinstance(body.get("etag"), str):
            return _error(422, "etag must be a string")
        section = body.get("section")
        if section is not None and not isinstance(section, str):
            return _error(422, "section must be a section name or null")
        path = self._backend.config_file
        try:
            snapshot = config_edit.reset_config(path, body["etag"], section)
        except Conflict:
            return self._config_conflict()
        except OSError as exc:
            return _io_error("write", path, exc)
        except (ValueError, TypeError, AttributeError) as exc:
            return _error(422, str(exc))
        self._update_pending(snapshot)
        failed = await self._reload_after_write(snapshot.etag)
        if failed is not None:
            return failed
        return self._config_reply(snapshot)

    # -- vocab --------------------------------------------------------------

    async def _get_vocab(self, query: dict[str, str], body: Any) -> Reply:
        path = self._backend.vocab_file
        try:
            etag, vocab = config_edit.read_vocab(path)
        except OSError as exc:
            return _io_error("read", path, exc)
        except ValueError as exc:
            return _error(422, str(exc))
        return _ok(etag=etag, terms=vocab["terms"], replace=vocab["replace"])

    async def _patch_vocab(self, query: dict[str, str], body: Any) -> Reply:
        if not isinstance(body, dict) or not isinstance(body.get("etag"), str):
            return _error(422, "etag must be a string")
        terms, replace = body.get("terms"), body.get("replace")
        # write_vocab assumes these types; anything else must not reach it.
        if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
            return _error(422, "terms must be a list of strings")
        if not _is_str_dict(replace):
            return _error(422, "replace must be an object of spoken text to written text")
        path = self._backend.vocab_file
        try:
            etag = config_edit.write_vocab(path, body["etag"], terms, replace)
        except Conflict:
            try:
                current, _ = config_edit.read_vocab(path)
            except OSError as exc:
                return _io_error("read", path, exc)
            except ValueError as exc:
                return _error(422, str(exc))
            return _error(409, "conflict", etag=current)
        except OSError as exc:
            return _io_error("write", path, exc)
        except ValueError as exc:
            return _error(422, str(exc))
        failed = await self._reload_after_write(etag)
        if failed is not None:
            return failed
        return _ok(etag=etag)

    async def _test_vocab(self, query: dict[str, str], body: Any) -> Reply:
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return _error(422, "text must be a string")
        text: str = body["text"]
        if len(text) > MAX_TEST_TEXT:
            return _error(422, f"text must be at most {MAX_TEST_TEXT} characters")
        replace = body.get("replace")
        if replace is None:
            path = self._backend.vocab_file
            try:
                _, vocab = config_edit.read_vocab(path)
            except OSError as exc:
                return _io_error("read", path, exc)
            except ValueError as exc:
                return _error(422, str(exc))
            replace = vocab["replace"]
        elif not _is_str_dict(replace):
            return _error(422, "replace must be an object of spoken text to written text")
        return _ok(text=basic_clean(text, replace))

    # -- stats, status, paste tools -----------------------------------------

    async def _stats(self, query: dict[str, str], body: Any) -> Reply:
        # Up to tens of MB of JSON lines: kept off the event loop.
        records = await asyncio.to_thread(
            read_records, self._backend.metrics_file, last_n=STATS_RECORDS
        )
        return _ok(**stats.overview(records, now=time.time()))

    async def _devices(self) -> list[dict[str, Any]]:
        # Listing releases PortAudio afterwards, which would cut off a live stream.
        if self._backend.recording:
            raise Busy("the microphone is in use by a dictation")
        return await asyncio.to_thread(audio.input_devices)

    async def _status(self, query: dict[str, str], body: Any) -> Reply:
        extra: dict[str, Any] = {}
        if query.get("devices") == "1":
            try:
                extra["devices"] = await self._devices()
            except Busy as exc:
                return _error(409, str(exc))
        memory = await asyncio.to_thread(status.memory)
        return _ok(
            daemon=self._backend.daemon_status(),
            memory=[{"name": m.name, "pid": m.pid, "anon_mb": m.anon_mb} for m in memory],
            budget_mb=BUDGET_MB,
            desktop=status.desktop(),
            **extra,
        )

    async def _inject_backends(self, query: dict[str, str], body: Any) -> Reply:
        order = self._backend.cfg.inject.order
        return _ok(backends=await asyncio.to_thread(status.backends, order))
