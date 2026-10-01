"""The settings page's JSON API over a fake daemon."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from flowd import settings_api, status
from flowd.config import Config, load_config
from flowd.config_edit import read_config
from flowd.settings_api import SettingsApi
from flowd.settings_server import Reply


@dataclass
class FakeBackend:
    config_file: Path
    vocab_file: Path
    metrics_path: Path
    cfg: Config = field(default_factory=Config)
    reloads: int = 0
    reload_error: str | None = None
    recording: bool = False

    @property
    def metrics_file(self) -> Path:
        return self.metrics_path

    async def reload(self) -> str | None:
        self.reloads += 1
        if self.reload_error is not None:
            return self.reload_error
        self.cfg = load_config(self.config_file)
        return None

    def daemon_status(self) -> dict[str, Any]:
        return {"state": "idle", "stt_model": "tiny", "final_model": "base", "cleanup": "ready"}


@pytest.fixture
def backend(tmp_path: Path) -> FakeBackend:
    config_file = tmp_path / "config.toml"
    config_file.write_text('# mine\n[hotkey]\nmode = "toggle"\n')
    return FakeBackend(
        config_file=config_file,
        vocab_file=tmp_path / "vocab.toml",
        metrics_path=tmp_path / "metrics.jsonl",
        cfg=load_config(config_file),
    )


@pytest.fixture
def api(backend: FakeBackend) -> SettingsApi:
    return SettingsApi(backend)


async def call(
    api: SettingsApi, method: str, path: str, body: Any = None, query: dict[str, str] | None = None
) -> Reply:
    reply = await api(method, path, query or {}, body)
    assert isinstance(reply, Reply)
    # Everything the page gets must survive JSON encoding.
    json.dumps(reply.body)
    return reply


async def etag(api: SettingsApi) -> str:
    return str((await call(api, "GET", "/api/config")).body["etag"])


# -- config ---------------------------------------------------------------


async def test_get_config_has_values_defaults_and_etag(api: SettingsApi) -> None:
    reply = await call(api, "GET", "/api/config")
    body = reply.body
    assert reply.status == 200 and body["ok"] is True
    assert body["etag"] and body["values"]["hotkey"]["mode"] == "toggle"
    assert body["defaults"]["settings"]["port"] == 8178
    assert body["in_file"] == {"hotkey": {"mode": "toggle"}}
    assert body["applies"]["stt.model"] == "restart"
    assert body["applies"]["hotkey.mode"] == "live"
    assert "modes" not in {k.partition(".")[0] for k in body["applies"]}
    assert body["restart_pending"] == []


async def test_patch_writes_and_reloads(api: SettingsApi, backend: FakeBackend) -> None:
    body = {"etag": await etag(api), "changes": {"hotkey.debounce_ms": 120}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.status == 200 and reply.body["ok"] is True
    assert reply.body["applied"] == {"hotkey.debounce_ms": "live"}
    assert reply.body["values"]["hotkey"]["debounce_ms"] == 120
    assert reply.body["etag"] == read_config(backend.config_file).etag
    assert backend.reloads == 1
    text = backend.config_file.read_text()
    assert "debounce_ms = 120" in text and "# mine" in text


async def test_patch_stale_etag_is_409_and_nothing_written(
    api: SettingsApi, backend: FakeBackend
) -> None:
    before = backend.config_file.read_text()
    reply = await call(api, "PATCH", "/api/config", {"etag": "stale", "changes": {"x.y": 1}})
    assert reply.status == 409
    assert reply.body == {"ok": False, "error": "conflict", "etag": await etag(api)}
    assert backend.config_file.read_text() == before and backend.reloads == 0


async def test_conflict_etag_matches_a_fresh_read_of_a_missing_file(
    api: SettingsApi, backend: FakeBackend
) -> None:
    backend.config_file.unlink()
    reply = await call(api, "PATCH", "/api/config", {"etag": "stale", "changes": {}})
    assert reply.status == 409 and reply.body["etag"] == read_config(backend.config_file).etag


async def test_patch_invalid_is_422_with_config_message(
    api: SettingsApi, backend: FakeBackend
) -> None:
    before = backend.config_file.read_text()
    body = {"etag": await etag(api), "changes": {"hotkey.debounce_ms": 0}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.status == 422 and reply.body["ok"] is False
    assert "debounce_ms" in reply.body["error"]
    assert backend.config_file.read_text() == before and backend.reloads == 0


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "x",
        {"etag": "e"},
        {"changes": {}},
        {"etag": "e", "changes": []},
        {"etag": 1, "changes": {}},
    ],
)
async def test_patch_malformed_body_is_422(api: SettingsApi, body: Any) -> None:
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.status == 422 and reply.body["ok"] is False and reply.body["error"]


async def test_patch_restart_key_is_pending_and_clears_when_set_back(
    api: SettingsApi, backend: FakeBackend
) -> None:
    body = {"etag": await etag(api), "changes": {"settings.port": 9000}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.body["applied"] == {"settings.port": "restart"}
    assert reply.body["restart_pending"] == ["settings.port"]
    assert api.restart_pending == {"settings.port"}
    # The reload moved `backend.cfg` on, but the running daemon still listens on 8178.
    assert backend.cfg.settings.port == 9000

    body = {"etag": reply.body["etag"], "changes": {"settings.port": 8178}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.body["restart_pending"] == [] and api.restart_pending == set()


async def test_restart_key_saved_at_its_running_value_is_not_pending(api: SettingsApi) -> None:
    body = {"etag": await etag(api), "changes": {"stt.model": Config().stt.model}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.status == 200 and reply.body["restart_pending"] == []


async def test_reload_failure_after_write_is_500_saying_it_was_saved(
    api: SettingsApi, backend: FakeBackend
) -> None:
    backend.reload_error = "model not found"
    body = {"etag": await etag(api), "changes": {"hotkey.debounce_ms": 90}}
    reply = await call(api, "PATCH", "/api/config", body)
    assert reply.status == 500
    assert reply.body == {
        "ok": False,
        "error": "saved, but flowd could not apply it: model not found",
    }
    assert "debounce_ms = 90" in backend.config_file.read_text()


async def test_reset_section(api: SettingsApi, backend: FakeBackend) -> None:
    body = {"etag": await etag(api), "changes": {"stt.model": "other", "hotkey.debounce_ms": 90}}
    tag = (await call(api, "PATCH", "/api/config", body)).body["etag"]
    assert api.restart_pending == {"stt.model"}
    reply = await call(api, "POST", "/api/config/reset", {"etag": tag, "section": "stt"})
    assert reply.status == 200 and reply.body["ok"] is True
    assert (
        "stt" not in reply.body["in_file"] and reply.body["in_file"]["hotkey"]["debounce_ms"] == 90
    )
    assert "defaults" in reply.body and "applies" in reply.body
    assert reply.body["restart_pending"] == []
    assert backend.reloads == 2


async def test_reset_everything(api: SettingsApi, backend: FakeBackend) -> None:
    reply = await call(api, "POST", "/api/config/reset", {"etag": await etag(api), "section": None})
    assert reply.status == 200 and reply.body["in_file"] == {}


async def test_reset_conflict_and_unknown_section(api: SettingsApi) -> None:
    reply = await call(api, "POST", "/api/config/reset", {"etag": "stale", "section": None})
    assert reply.status == 409 and reply.body["error"] == "conflict"
    reply = await call(
        api, "POST", "/api/config/reset", {"etag": await etag(api), "section": "nope"}
    )
    assert reply.status == 422 and "nope" in reply.body["error"]
    reply = await call(api, "POST", "/api/config/reset", {"etag": await etag(api), "section": 3})
    assert reply.status == 422


async def test_unreadable_config_is_422(api: SettingsApi, backend: FakeBackend) -> None:
    backend.config_file.write_text("[hotkey\n")
    reply = await call(api, "GET", "/api/config")
    assert reply.status == 422 and reply.body["ok"] is False


# -- vocab ----------------------------------------------------------------


async def test_vocab_get_patch_roundtrip(api: SettingsApi, backend: FakeBackend) -> None:
    reply = await call(api, "GET", "/api/vocab")
    assert reply.body == {"ok": True, "etag": "", "terms": [], "replace": {}}
    body = {"etag": "", "terms": ["Hyprland"], "replace": {"hyper land": "Hyprland"}}
    reply = await call(api, "PATCH", "/api/vocab", body)
    assert reply.status == 200 and reply.body["ok"] is True and reply.body["etag"]
    got = (await call(api, "GET", "/api/vocab")).body
    assert got == {
        "ok": True,
        "etag": reply.body["etag"],
        **{k: body[k] for k in ("terms", "replace")},
    }


async def test_vocab_patch_conflict(api: SettingsApi, backend: FakeBackend) -> None:
    backend.vocab_file.write_text('terms = ["a"]\n')
    reply = await call(api, "PATCH", "/api/vocab", {"etag": "", "terms": [], "replace": {}})
    assert reply.status == 409 and reply.body["error"] == "conflict"
    assert reply.body["etag"] == (await call(api, "GET", "/api/vocab")).body["etag"]
    assert backend.vocab_file.read_text() == 'terms = ["a"]\n'


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"etag": "", "terms": "a", "replace": {}},
        {"etag": "", "terms": [1], "replace": {}},
        {"etag": "", "terms": [], "replace": {"a": 1}},
        {"etag": "", "terms": [], "replace": []},
        {"terms": [], "replace": {}},
        {"etag": "", "terms": ["a,b"], "replace": {}},
    ],
)
async def test_vocab_patch_bad_body_is_422(
    api: SettingsApi, backend: FakeBackend, body: Any
) -> None:
    reply = await call(api, "PATCH", "/api/vocab", body)
    assert reply.status == 422 and reply.body["ok"] is False
    assert not backend.vocab_file.exists()


async def test_invalid_vocab_file_is_422(api: SettingsApi, backend: FakeBackend) -> None:
    backend.vocab_file.write_text("replace = 3\n")
    reply = await call(api, "GET", "/api/vocab")
    assert reply.status == 422 and "replace" in reply.body["error"]


async def test_vocab_test_applies_replacements(api: SettingsApi) -> None:
    body = {"text": "open hyper land", "replace": {"hyper land": "Hyprland"}}
    reply = await call(api, "POST", "/api/vocab/test", body)
    assert reply.body == {"ok": True, "text": "Open Hyprland."}


async def test_vocab_test_uses_the_saved_vocab_by_default(
    api: SettingsApi, backend: FakeBackend
) -> None:
    backend.vocab_file.write_text('[replace]\n"hyper land" = "Hyprland"\n')
    reply = await call(api, "POST", "/api/vocab/test", {"text": "um open hyper land"})
    assert reply.body == {"ok": True, "text": "Open Hyprland."}


async def test_vocab_test_rejects_long_text(api: SettingsApi) -> None:
    reply = await call(api, "POST", "/api/vocab/test", {"text": "a" * 2001})
    assert reply.status == 422 and reply.body["ok"] is False
    reply = await call(api, "POST", "/api/vocab/test", {"text": "a" * 2000})
    assert reply.status == 200


@pytest.mark.parametrize("body", [None, {"text": 3}, {"text": "a", "replace": {"a": 1}}])
async def test_vocab_test_bad_body_is_422(api: SettingsApi, body: Any) -> None:
    assert (await call(api, "POST", "/api/vocab/test", body)).status == 422


# -- stats, status, paste tools -------------------------------------------


async def test_stats_from_metrics_file(api: SettingsApi, backend: FakeBackend) -> None:
    record = {
        "ts": 1_700_000_000.0,
        "app_id": "kitty",
        "mode": "code",
        "stages": {"mic_open_ms": 0.0, "released_ms": 2000.0, "inject_ms": 2150.0},
        "counts": {"words": 5, "fallbacks": 0},
    }
    backend.metrics_path.write_text(json.dumps(record) + "\n")
    reply = await call(api, "GET", "/api/stats")
    assert reply.status == 200 and reply.body["ok"] is True
    assert set(reply.body) == {"ok", "sessions", "latency", "fallback_rate"}
    [session] = reply.body["sessions"]
    assert session["app_id"] == "kitty" and session["words"] == 5
    assert session["speak_s"] == 2.0 and session["paste_ms"] == 150.0


async def test_stats_with_no_metrics_file(api: SettingsApi) -> None:
    reply = await call(api, "GET", "/api/stats")
    assert reply.status == 200 and reply.body["sessions"] == []


async def test_status_shape(api: SettingsApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "memory", lambda: [status.ProcMem("flowd", 42, 123.5)])
    monkeypatch.setattr(status, "desktop", lambda: "hyprland")
    reply = await call(api, "GET", "/api/status")
    assert reply.body == {
        "ok": True,
        "daemon": {"state": "idle", "stt_model": "tiny", "final_model": "base", "cleanup": "ready"},
        "memory": [{"name": "flowd", "pid": 42, "anon_mb": 123.5}],
        "budget_mb": 1600,
        "desktop": "hyprland",
    }


async def test_status_with_devices(api: SettingsApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "memory", lambda: [])
    devices = [{"name": "Mic", "default": True}]
    monkeypatch.setattr(settings_api.audio, "input_devices", lambda: devices)
    reply = await call(api, "GET", "/api/status", query={"devices": "1"})
    assert reply.body["devices"] == devices


async def test_devices_refused_while_recording(
    api: SettingsApi, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> list[dict[str, Any]]:
        raise AssertionError("must not touch PortAudio during a dictation")

    monkeypatch.setattr(status, "memory", lambda: [])
    monkeypatch.setattr(settings_api.audio, "input_devices", fail)
    backend.recording = True
    reply = await call(api, "GET", "/api/status", query={"devices": "1"})
    assert reply.status == 409 and reply.body["ok"] is False and reply.body["error"]


async def test_inject_backends_follow_order(
    api: SettingsApi, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, ...]] = []

    def fake(order: tuple[str, ...]) -> list[dict[str, str]]:
        seen.append(order)
        return [{"name": n, "status": "available"} for n in order]

    monkeypatch.setattr(status, "backends", fake)
    reply = await call(api, "GET", "/api/inject-backends")
    order = backend.cfg.inject.order
    assert seen == [order]
    assert reply.body == {
        "ok": True,
        "backends": [{"name": n, "status": "available"} for n in order],
    }


# -- routing --------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/nope", "/api/config/", "/api/mic-test", "/api/restart"])
async def test_unknown_route_is_404(api: SettingsApi, path: str) -> None:
    reply = await call(api, "GET", path)
    assert reply.status == 404 and reply.body["ok"] is False


@pytest.mark.parametrize(
    ("method", "path"),
    [("DELETE", "/api/config"), ("GET", "/api/config/reset"), ("POST", "/api/stats")],
)
async def test_wrong_method_is_405(api: SettingsApi, method: str, path: str) -> None:
    reply = await call(api, method, path)
    assert reply.status == 405 and reply.body["ok"] is False
