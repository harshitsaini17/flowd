"""Ordered injection with fallthrough (spec 5.7)."""

from __future__ import annotations

import logging
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
    for name in cfg.order:
        backend = pool.get(name)
        if backend is None:
            log.debug("no injector named %s, skipping", name)
            continue
        if not backend.available():
            log.debug("injector %s unavailable, skipping", name)
            errors.append(f"{name}: unavailable")
            continue
        try:
            backend.inject(text, is_terminal=is_terminal)
        except Exception as exc:
            log.warning("injector %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
            continue
        return InjectResult(ok=True, backend=name)
    return InjectResult(ok=False, error="; ".join(errors) or "no backend configured")
