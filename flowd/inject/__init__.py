"""Ordered injection with fallthrough (spec 5.7)."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from flowd.config import Inject
from flowd.inject.base import Backend, InjectResult
from flowd.inject.clipboard import ClipboardBackend
from flowd.inject.typing_backends import WtypeBackend, XdotoolBackend, YdotoolBackend

log = logging.getLogger(__name__)

__all__ = [
    "Backend",
    "ClipboardBackend",
    "InjectResult",
    "WtypeBackend",
    "XdotoolBackend",
    "YdotoolBackend",
    "default_backends",
    "inject_text",
]


def default_backends(cfg: Inject) -> list[Backend]:
    return [
        ClipboardBackend(restore_delay_ms=cfg.restore_delay_ms),
        WtypeBackend(),
        YdotoolBackend(),
        XdotoolBackend(),
    ]


def inject_text(
    text: str,
    cfg: Inject,
    backends: Sequence[Backend] | None = None,
    *,
    is_terminal: bool = False,
) -> InjectResult:
    """Try each backend in cfg.order until one succeeds.

    `cfg.order` drives the attempt sequence, not the order of `backends`: the
    list is a pool to resolve names against. A name in the order with no
    matching backend is skipped, so a typo in one entry cannot silence the rest.
    """
    if not text:
        return InjectResult(ok=True)

    pool = {b.name: b for b in (backends if backends is not None else default_backends(cfg))}
    errors: list[str] = []
    for name in _attempt_order(text, cfg.order):
        backend = pool.get(name)
        if backend is None:
            log.debug("no injector named %s, skipping", name)
            continue
        if not backend.available():
            reason = _reason(backend)
            log.info("injector %s unavailable (%s), trying the next one", name, reason)
            errors.append(f"{name}: {reason}")
            continue
        try:
            backend.inject(text, is_terminal=is_terminal)
        except Exception as exc:
            log.warning("injector %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
            continue
        return InjectResult(ok=True, backend=name)
    return InjectResult(ok=False, error="; ".join(errors) or "no backend configured")


def _reason(backend: Backend) -> str:
    # Optional on the protocol: a backend without it still falls through, unexplained.
    explain = getattr(backend, "unavailable_reason", None)
    return (explain() if callable(explain) else None) or "unavailable"


def _attempt_order(text: str, order: Sequence[str]) -> list[str]:
    """cfg.order, except that X11 pastes non-ASCII text before typing it.

    spec 9.4: `xdotool type` mangles Unicode on X11, so the clipboard goes first
    there. Wayland's typing tools handle it, and ASCII keeps the user's order.
    """
    names = list(order)
    if text.isascii() or os.environ.get("WAYLAND_DISPLAY") or "clipboard" not in names:
        return names
    names.remove("clipboard")
    return ["clipboard", *names]
