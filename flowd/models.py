"""Model file verification against the pinned models.lock (spec 3)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Stream a file through SHA-256 so large weights never load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def build_lock(
    models_dir: Path,
    sources: Mapping[str, tuple[str, str]],
    lock_path: Path,
    downloaded: frozenset[str] = frozenset(),
) -> dict[str, list[dict[str, object]]]:
    """Build the models.lock document from the files on disk (spec 3).

    `sources` maps a file name to its `(url, license)`. `downloaded` names the
    files this run actually fetched.

    The refusal is the point. `scripts/fetch_models.sh` leaves a file that is
    already present alone and then regenerates the lock from disk, so a file
    that was corrupted, truncated or swapped after it was pinned had its new
    hash written in as canonical — destroying the one check that would have
    caught it. `verify_models` would then pass and the daemon would start
    happily on a bad model.

    A freshly downloaded file is the exception, because that is the upgrade path
    the script's own header documents: delete the file, re-run, review the
    models.lock diff. What arrives from the pinned URL is what gets pinned.

    Raises ValueError rather than returning problems, unlike `verify_models`:
    this runs in a script that must stop, and there is nothing useful to do with
    a half-built lock.
    """
    pinned: dict[str, dict[str, object]] = {}
    if lock_path.is_file():
        try:
            pinned = {str(e["name"]): e for e in json.loads(lock_path.read_text())["models"]}
        except (ValueError, KeyError, TypeError) as exc:
            # A lock we cannot read pins nothing, so there is nothing to
            # contradict. Rebuilding is the documented repair for it.
            pinned = {}
            log.warning("ignoring unreadable %s: %s", lock_path, exc)

    entries: list[dict[str, object]] = []
    for name, (url, licence) in sorted(sources.items()):
        path = models_dir / name
        if not path.is_file():
            raise ValueError(
                f"{name}: expected at {path}; run scripts/fetch_models.sh from the top"
            )
        sha = sha256_file(path)
        previous = pinned.get(name)
        if previous is not None and name not in downloaded and previous["sha256"] != sha:
            raise ValueError(
                f"{name}: on-disk sha256 {sha} does not match pinned {previous['sha256']}. "
                "The file changed after it was pinned, so re-pinning it would bless a file "
                "that may be corrupt. To upgrade deliberately, delete it and re-run; to "
                "repair it, delete it and re-run."
            )
        entries.append(
            {
                "name": name,
                "size_bytes": path.stat().st_size,
                "sha256": sha,
                "url": url,
                "license": licence,
            }
        )
    return {"models": entries}


def verify_models(lock_path: Path, models_dir: Path) -> list[str]:
    """Return one message per problem. An empty list means every file verified.

    The daemon refuses to start on any problem (spec 9.2), so the caller needs
    every mismatch at once rather than only the first.
    """
    entries = json.loads(lock_path.read_text())["models"]
    problems: list[str] = []
    for entry in entries:
        path = models_dir / entry["name"]
        if not path.is_file():
            problems.append(f"{entry['name']}: missing from {models_dir}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry["size_bytes"]:
            problems.append(f"{entry['name']}: size {actual_size} != pinned {entry['size_bytes']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append(f"{entry['name']}: sha256 {actual} != pinned {entry['sha256']}")
    return problems
