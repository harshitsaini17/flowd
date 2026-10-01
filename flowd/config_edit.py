"""Reads and writes config.toml and vocab.toml for the settings page (ADR 0014).

tomlkit keeps the user's comments and ordering. Every write is validated by
the same code the daemon loads with (`config.build_config`, `vocab.load_vocab`)
before the file is touched, and lands with one `os.replace`, so a reader never
sees half a file. The etag is the SHA-256 of the bytes on disk: a save carries
the etag it read, and a mismatch means someone edited the file meanwhile.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import Array, Table

from flowd.config import Config, applies, build_config
from flowd.vocab import load_vocab


class Conflict(Exception):
    """The file changed on disk since the caller read it."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    etag: str
    values: dict[str, dict[str, Any]]
    in_file: dict[str, dict[str, Any]]


def _etag(data: bytes | None) -> str:
    return "" if data is None else hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _values(cfg: Config) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, section in asdict(cfg).items():
        if name == "modes":
            out["modes"] = {k: v for k, v in cfg.modes}
        else:
            out[name] = {k: _jsonable(v) for k, v in section.items()}
    return out


def defaults() -> dict[str, dict[str, Any]]:
    return _values(Config())


def read_config(path: Path) -> Snapshot:
    data = _read_bytes(path)
    raw = tomllib.loads(data.decode()) if data else {}
    return Snapshot(_etag(data), _values(build_config(raw)), _jsonable(raw))


def _check(path: Path, etag: str) -> tomlkit.TOMLDocument:
    data = _read_bytes(path)
    if _etag(data) != etag:
        raise Conflict(f"{path.name} changed on disk")
    return tomlkit.parse(data.decode()) if data else tomlkit.document()


def _atomic_write(path: Path, text: str) -> None:
    # Write through a symlink (stow, chezmoi, home-manager): replacing the link
    # itself would leave the real file stale and the two silently diverged.
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o600  # may hold transcript and recordings paths; nobody else's business
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _apply(doc: tomlkit.TOMLDocument, changes: dict[str, Any]) -> None:
    for dotted, value in changes.items():
        section, sep, key = dotted.partition(".")
        if not sep or not key:
            raise ValueError(f"{dotted}: expected section.key")
        table = doc.get(section)
        if table is None:
            if value is None:
                continue
            table = tomlkit.table()
            doc.add(section, table)
        if not isinstance(table, Table):
            raise ValueError(f"[{section}]: expected a table")
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
        if not table:
            doc.pop(section)


def patch_config(path: Path, etag: str, changes: dict[str, Any]) -> tuple[Snapshot, dict[str, str]]:
    doc = _check(path, etag)
    _apply(doc, changes)
    text = tomlkit.dumps(doc)
    # The daemon's own loader decides, before anything is written.
    build_config(tomllib.loads(text))
    _atomic_write(path, text)
    return read_config(path), {k: applies(k) for k in changes}


def reset_config(path: Path, etag: str, section: str | None) -> Snapshot:
    doc = _check(path, etag)
    if section is None:
        data = _read_bytes(path)
        if data is not None:
            _atomic_write(path.with_name(path.name + ".bak"), data.decode())
        _atomic_write(path, "")
    else:
        if section not in defaults():
            raise ValueError(f"unknown config section: [{section}]")
        doc.pop(section, None)
        _atomic_write(path, tomlkit.dumps(doc))
    return read_config(path)


def read_vocab(path: Path) -> tuple[str, dict[str, Any]]:
    data = _read_bytes(path)
    vocab = load_vocab(path)
    return _etag(data), {"terms": list(vocab.terms), "replace": dict(vocab.replace)}


def _table(entries: dict[str, str]) -> Table:
    table = tomlkit.table()
    for key, value in entries.items():
        table[key] = value
    return table


def _sync_table(table: Table, wanted: dict[str, str]) -> None:
    """Make `table` hold exactly `wanted`, touching only entries that differ.

    Entries that stay keep their place and their comments; clearing and
    refilling the table would shift comments onto the wrong lines.
    """
    for key in [k for k in table if k not in wanted]:
        del table[key]
    for key, value in wanted.items():
        if key in table:
            if table[key] != value:
                table[key] = value
            continue
        # A plain append lands after the trailing blank line and the comment
        # that heads the next table; slot it in after the last entry instead.
        last = next(reversed(list(table.keys())), None)
        if last is None:
            table[key] = value
        else:
            table.value._insert_after(last, key, value)
            last = key


def write_vocab(path: Path, etag: str, terms: list[str], replace: dict[str, str]) -> str:
    doc = _check(path, etag)

    old_terms = doc.get("terms")
    if isinstance(old_terms, Array):
        # The user wrote `terms = [...]`; keep that style rather than folding
        # it into a `[terms]` table.
        new_array = tomlkit.array()
        new_array.extend(terms)
        doc["terms"] = new_array.multiline(True) if len(terms) > 1 else new_array
    elif isinstance(old_terms, Table):
        _sync_table(old_terms, {term: term for term in terms})
    else:
        doc["terms"] = _table({term: term for term in terms})

    old_replace = doc.get("replace")
    if isinstance(old_replace, Table):
        _sync_table(old_replace, replace)
    else:
        doc["replace"] = _table(replace)

    text = tomlkit.dumps(doc)
    # Validate with the daemon's loader on a scratch copy before replacing.
    with tempfile.TemporaryDirectory() as scratch:
        probe = Path(scratch) / "vocab.toml"
        probe.write_text(text)
        load_vocab(probe)
    _atomic_write(path, text)
    return _etag(path.read_bytes())
