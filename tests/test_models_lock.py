import hashlib
import json
from pathlib import Path

import pytest

from flowd.models import build_lock, verify_models


def _lock(tmp: Path, name: str, sha: str, size: int) -> Path:
    lock = tmp / "models.lock"
    lock.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "name": name,
                        "sha256": sha,
                        "size_bytes": size,
                        "url": "https://example.invalid/x",
                        "license": "MIT",
                    }
                ]
            }
        )
    )
    return lock


def test_reports_nothing_when_file_matches(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    assert verify_models(_lock(tmp_path, "a.bin", sha, 5), models) == []


def test_reports_missing_file(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    problems = verify_models(_lock(tmp_path, "a.bin", "0" * 64, 5), models)
    assert len(problems) == 1
    assert "missing" in problems[0].lower()


def test_reports_hash_mismatch(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"tampered")
    problems = verify_models(_lock(tmp_path, "a.bin", "0" * 64, 8), models)
    assert len(problems) == 1
    assert "sha256" in problems[0].lower()


# --- building the lock (scripts/fetch_models.sh) -----------------------------

SOURCES = {"a.bin": ("https://example.invalid/a.bin", "MIT")}


def test_a_first_run_pins_whatever_was_downloaded(tmp_path: Path) -> None:
    """With no lock yet, the downloaded file is the thing being pinned."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"hello")
    doc = build_lock(models, SOURCES, lock_path=tmp_path / "models.lock")
    assert doc["models"][0]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert doc["models"][0]["size_bytes"] == 5


def test_rerunning_over_an_unchanged_file_pins_the_same_hash(tmp_path: Path) -> None:
    """The script is safe to re-run: a matching file is simply re-pinned."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    doc = build_lock(models, SOURCES, lock_path=_lock(tmp_path, "a.bin", sha, 5))
    assert doc["models"][0]["sha256"] == sha


def test_a_file_that_no_longer_matches_its_pin_is_refused(tmp_path: Path) -> None:
    """The pin must not be rewritten to match a file that changed underneath it.

    The script leaves a file that is already on disk alone, then regenerates the
    lock from disk — so a corrupted, truncated or substituted file had its hash
    promoted to canonical. That destroys the one check that would have caught
    it: `verify_models` then passes, the daemon starts, and spec 3's pin has
    been quietly rewritten to bless the bad file.
    """
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"corrupted on disk")
    lock = _lock(tmp_path, "a.bin", hashlib.sha256(b"hello").hexdigest(), 5)
    before = lock.read_text()

    with pytest.raises(ValueError, match="does not match"):
        build_lock(models, SOURCES, lock_path=lock)
    assert lock.read_text() == before, "the lock was modified despite the refusal"


def test_a_freshly_downloaded_file_may_change_the_pin(tmp_path: Path) -> None:
    """Upgrading a model is the one legitimate way a hash changes.

    The script's own header documents it: delete the file, re-run, review the
    `models.lock` diff. A deleted file is downloaded again from the pinned URL,
    and what arrives is what gets pinned — so the refusal above must not stand
    in the way of it.
    """
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.bin").write_bytes(b"a new upstream revision")
    doc = build_lock(
        models,
        SOURCES,
        lock_path=_lock(tmp_path, "a.bin", hashlib.sha256(b"hello").hexdigest(), 5),
        downloaded=frozenset({"a.bin"}),
    )
    assert doc["models"][0]["sha256"] == hashlib.sha256(b"a new upstream revision").hexdigest()


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    with pytest.raises(ValueError, match=r"a\.bin"):
        build_lock(models, SOURCES, lock_path=tmp_path / "models.lock")
