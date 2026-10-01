"""The shipped settings page: every setting has a control, and nothing the CSP
would block is left in it (ADR 0014)."""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

from flowd.config import Config

WEB = Path(__file__).resolve().parent.parent / "flowd" / "web"
# Keys edited through list/table widgets rather than a single data-key control.
WIDGET_KEYS = {"chunking.correction_cues", "inject.order", "inject.terminal_apps"}
# Keys the page cannot edit. Empty: ui.hotkey_label is the Hotkey section's label field.
HIDDEN: set[str] = set()


def page() -> str:
    return (WEB / "index.html").read_text()


def all_keys() -> set[str]:
    cfg = Config()
    return {
        f"{s.name}.{f.name}"
        for s in fields(cfg)
        if s.name != "modes"
        for f in fields(type(getattr(cfg, s.name)))
    }


def test_every_config_key_has_a_control() -> None:
    html = page()
    shown = set(re.findall(r'data-key="([^"]+)"', html)) | set(
        re.findall(r'data-list-key="([^"]+)"', html)
    )
    assert all_keys() - shown - HIDDEN == set()
    assert shown - all_keys() == set()  # no stale mockup keys


def test_list_keys_are_widgets() -> None:
    assert set(re.findall(r'data-list-key="([^"]+)"', page())) >= WIDGET_KEYS


def test_no_inline_script_or_style_or_handlers() -> None:
    for path in [WEB / "index.html", *sorted((WEB / "assets").glob("*.js"))]:
        text = path.read_text()
        assert "style=" not in text, path
        assert not re.search(r"\son[a-z]+=", text), path
    assert not re.search(r"<script(?![^>]*\bsrc=)", page())


def test_nothing_loads_from_another_origin() -> None:
    for path in [WEB / "index.html", *sorted((WEB / "assets").glob("*.*"))]:
        if path.suffix in {".html", ".css", ".js"}:
            assert not re.search(r"(src|href|url\()\s*=?\s*[\"']?https?://", path.read_text()), path


def test_demo_gallery_is_gone() -> None:
    assert 'id="states"' not in page()
