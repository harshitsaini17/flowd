"""Fixtures for the settings page's browser tests (ADR 0014).

Skipped entirely, not failed, when `playwright` is not installed or no
Chromium is found, so `pytest -q` stays green without them. Uses the plain
`sync_playwright` API in a module-scoped fixture rather than pytest-playwright's
own fixtures, which assume a from-scratch browser context per test and would
collide with the page/server pairing these tests need.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import threading
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Browser, Page, sync_playwright

from flowd.config import load_config
from flowd.settings_api import SettingsApi
from flowd.settings_server import SettingsServer, Tokens
from tests.test_settings_api import FakeBackend

#: `FLOWD_TEST_CHROMIUM` overrides the browser path; otherwise whatever
#: `chromium` resolves to on PATH (the brief's `/usr/sbin/chromium` here).
CHROMIUM_PATH = os.environ.get("FLOWD_TEST_CHROMIUM") or shutil.which("chromium")
if not CHROMIUM_PATH:
    pytest.skip("no Chromium found for the settings page's browser tests", allow_module_level=True)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM_PATH)
        yield b
        b.close()


@dataclass
class PageServer:
    base_url: str
    token: str
    fake: FakeBackend
    page: Page
    _runner: _ServerThread

    def stop_server(self) -> None:
        """Closes the daemon's socket, simulating it going down."""
        self._runner.stop()


class _ServerThread:
    """Runs a `SettingsServer` on its own asyncio loop, in a background thread.

    The page needs a real OS socket to fetch from, so the server cannot share
    the test's own event loop the way `tests/test_settings_server.py` does.
    """

    def __init__(self, fake: FakeBackend) -> None:
        self.fake = fake
        self.tokens = Tokens()
        self.loop = asyncio.new_event_loop()
        self.srv: SettingsServer | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._stopped = False

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)

        async def start() -> None:
            self.srv = SettingsServer(0, SettingsApi(self.fake), self.tokens)
            self._start_error = await self.srv.start()

        self.loop.run_until_complete(start())
        self._ready.set()
        self.loop.run_forever()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._start_error:
            raise RuntimeError(self._start_error)

    @property
    def port(self) -> int:
        assert self.srv is not None
        return self.srv.port

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        srv = self.srv
        if srv is not None:

            async def close() -> None:
                await srv.close()

            fut = asyncio.run_coroutine_threadsafe(close(), self.loop)
            with contextlib.suppress(Exception):
                fut.result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


def _make_fake_backend(tmp_path: Path) -> FakeBackend:
    config_file = tmp_path / "config.toml"
    config_file.write_text('# mine\n[hotkey]\nmode = "toggle"\n')
    return FakeBackend(
        config_file=config_file,
        vocab_file=tmp_path / "vocab.toml",
        metrics_path=tmp_path / "metrics.jsonl",
        cfg=load_config(config_file),
    )


@pytest.fixture
def page_server(tmp_path: Path, browser: Browser) -> Generator[PageServer, None, None]:
    fake = _make_fake_backend(tmp_path)
    runner = _ServerThread(fake)
    runner.start()
    token = runner.tokens.issue()
    base_url = f"http://127.0.0.1:{runner.port}"
    context = browser.new_context()
    page = context.new_page()
    try:
        yield PageServer(base_url, token, fake, page, runner)
    finally:
        context.close()
        with contextlib.suppress(Exception):
            runner.stop()
