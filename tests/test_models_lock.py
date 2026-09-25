import hashlib
import json
from pathlib import Path

from flowd.models import verify_models


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
