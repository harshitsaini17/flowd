"""The shipped settings page: every setting has a control, and nothing the CSP
would block is left in it (ADR 0014)."""

from __future__ import annotations

import re
from dataclasses import fields
from html.parser import HTMLParser
from pathlib import Path

from flowd.config import _INT_RANGES, _POSITIVE_FLOAT, _POSITIVE_INT, _UNIT_FLOAT, Config

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


def without_comments(text: str) -> str:
    """Drops /* */ and whole-line // comments, which may mention URLs harmlessly."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_nothing_loads_from_another_origin() -> None:
    for path in [WEB / "index.html", *sorted((WEB / "assets").glob("*.*"))]:
        if path.suffix in {".html", ".css", ".js"}:
            text = path.read_text()
            assert not re.search(r"(src|href|url\()\s*=?\s*[\"']?https?://", text), path
            assert "@import" not in text, path
            if path.suffix in {".css", ".js"}:
                # fetch("https://…"), new EventSource("http://…") and the like.
                # The cleanup server's loopback example is the only URL allowed.
                rest = without_comments(text).replace("http://127.0.0.1:", "")
                assert not re.search(r"https?://", rest), path


class _Controls(HTMLParser):
    """Collects the attributes of every element carrying a data-key."""

    def __init__(self) -> None:
        super().__init__()
        self.by_key: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("data-key"):
            self.by_key[str(a["data-key"])] = a


def test_numeric_bounds_match_config_validation() -> None:
    """A control narrower than config.py would rewrite valid values; a wider one would
    let the page send values the daemon rejects."""
    parser = _Controls()
    parser.feed(page())
    checked = 0
    for key, a in parser.by_key.items():
        name = key.split(".", 1)[1]
        lo, hi, gt = a.get("data-min"), a.get("data-max"), a.get("data-gt")
        scale = float(a.get("data-scale") or 1)
        if name in _POSITIVE_INT:
            assert (lo, hi, gt) == ("1", None, None), key
            assert "data-int" in a or "data-slider" in a, key
        elif name in _INT_RANGES:
            low, high = _INT_RANGES[name]
            assert (lo, hi, gt) == (str(low), str(high), None), key
        elif name in _UNIT_FLOAT:
            assert (lo, gt) == ("0", None) and hi is not None and float(hi) / scale == 1, key
        elif name in _POSITIVE_FLOAT:
            assert (lo, hi, gt) == (None, None, "0"), key
        else:
            assert lo is None and hi is None and gt is None, f"{key} has bounds config.py lacks"
            continue
        checked += 1
    numeric = _POSITIVE_INT | set(_INT_RANGES) | _UNIT_FLOAT | _POSITIVE_FLOAT
    assert checked == sum(1 for k in all_keys() if k.split(".", 1)[1] in numeric)


# Values that come from config.toml, vocab.toml, metrics or the API.
_TAINTED = re.compile(
    r"\b(?:it\.name|it\.cap|s\.mode|s\.name|r\.name|r\.mode|r\.k|r\.v|o\.name|o\.node|stt_model)\b"
)
# Interpolations reviewed as safe: comparisons, lookups into constant tables, and calls
# that escape inside.
_REVIEWED = {
    "grabbed === it.name ? ' grabbed' : ''",
    "grabbed === it.name",
    "mName[r.mode] || esc(r.mode)",
    "mName[s.mode] || esc(s.mode)",
    "I(mIcon[r.mode] || 'file-text', 12)",
    "I(mIcon[s.mode] || 'file-text', 12)",
    "w.badge('ok', 'circle-check', esc(d.stt_model || 'Ready'))",
    "type === 'text' ? esc(r.v) : modeSeg(r.v, r.k)",  # modeSeg escapes its id
}


def test_template_interpolations_escape_outside_values() -> None:
    """Outside values reach markup only through esc() or CSS.escape(). Lines that assign
    textContent are exempt, since the browser never parses them as HTML."""
    bad = []
    for path in sorted((WEB / "assets").glob("*.js")):
        for line in without_comments(path.read_text()).splitlines():
            if ".textContent =" in line:
                continue
            for expr in re.findall(r"\$\{([^{}`]*)\}", line):
                if expr in _REVIEWED or re.match(r"^(esc|F\.esc|CSS\.escape)\(", expr):
                    continue
                if _TAINTED.search(expr):
                    bad.append(f"{path.name}: ${{{expr}}}")
    assert bad == []


def test_demo_gallery_is_gone() -> None:
    assert 'id="states"' not in page()
