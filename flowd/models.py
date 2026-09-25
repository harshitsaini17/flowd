"""Model file verification against the pinned models.lock (spec 3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Stream a file through SHA-256 so large weights never load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


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
