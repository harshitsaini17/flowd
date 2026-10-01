"""Browser tests for the settings page (ADR 0014): saving, conflicts, offline
and narrow screens, through a real Chromium against a real `SettingsServer`.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.web.conftest import PageServer

pytestmark = pytest.mark.web


def _open(ps: PageServer, with_token: bool = True) -> None:
    url = f"{ps.base_url}/#token={ps.token}" if with_token else ps.base_url
    ps.page.goto(url)


def test_loads_values_from_config(page_server: PageServer) -> None:
    _open(page_server)
    toggle = page_server.page.locator('.segmented[data-key="hotkey.mode"] button[data-v="toggle"]')
    expect(toggle).to_have_attribute("aria-checked", "true")
    ptt = page_server.page.locator('.segmented[data-key="hotkey.mode"] button[data-v="ptt"]')
    expect(ptt).to_have_attribute("aria-checked", "false")


def test_toggle_saves_and_file_keeps_comments(page_server: PageServer) -> None:
    _open(page_server)
    page = page_server.page
    switch = page.locator('button[data-key="ui.footer"]')
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    feedback = switch.locator("xpath=following-sibling::span[contains(@class,'feedback')]")
    expect(feedback).to_contain_text("Saved")
    text = page_server.fake.config_file.read_text()
    assert "# mine" in text
    assert "footer = false" in text


def test_invalid_number_shows_error_and_writes_nothing(page_server: PageServer) -> None:
    _open(page_server)
    page = page_server.page
    before = page_server.fake.config_file.read_text()
    debounce = page.locator('input[data-key="hotkey.debounce_ms"]')
    debounce.fill("0")
    debounce.blur()
    err = page.locator(".field-err")
    expect(err).to_be_visible()
    assert page_server.fake.config_file.read_text() == before


def test_conflict_banner_on_external_edit(page_server: PageServer) -> None:
    _open(page_server)
    page = page_server.page
    # Edit the file behind the page's back: this changes the etag the page holds.
    page_server.fake.config_file.write_text(
        '# mine\n[hotkey]\nmode = "toggle"\ndebounce_ms = 250\n'
    )
    switch = page.locator('button[data-key="ui.footer"]')
    switch.click()
    banner = page.locator("#conflictBanner")
    expect(banner).to_be_visible()
    keep = page.locator("#cfKeep")
    keep.click()
    expect(banner).to_be_hidden()
    feedback = switch.locator("xpath=following-sibling::span[contains(@class,'feedback')]")
    expect(feedback).to_contain_text("Saved")
    text = page_server.fake.config_file.read_text()
    assert "footer = false" in text
    assert "debounce_ms = 250" in text


def test_restart_key_shows_banner(page_server: PageServer) -> None:
    _open(page_server)
    page = page_server.page
    select = page.locator('select[data-key="stt.model"]')
    select.select_option("medium-streaming-en")
    banner = page.locator("#restartBanner")
    expect(banner).to_be_visible()


def test_daemon_down_makes_page_read_only(page_server: PageServer) -> None:
    _open(page_server)
    page = page_server.page
    switch = page.locator('button[data-key="ui.footer"]')
    expect(switch).not_to_be_disabled()
    # Stop the daemon's HTTP server; the page's poll (every 5 s) hits a
    # connection error and goes read-only.
    page_server.stop_server()
    banner = page.locator("#roBanner")
    expect(banner).to_be_visible(timeout=8000)
    expect(banner).to_contain_text("systemctl")
    expect(switch).to_be_disabled()


def test_no_token_is_read_only_with_instructions(page_server: PageServer) -> None:
    _open(page_server, with_token=False)
    page = page_server.page
    banner = page.locator("#roBanner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("flowctl settings")
    switch = page.locator('button[data-key="ui.footer"]')
    expect(switch).to_be_disabled()


def test_320px_no_horizontal_scroll(page_server: PageServer) -> None:
    page_server.page.set_viewport_size({"width": 320, "height": 800})
    _open(page_server)
    width = page_server.page.evaluate("document.documentElement.scrollWidth")
    assert width <= 320


def test_no_csp_violations(page_server: PageServer) -> None:
    page = page_server.page
    violations: list[str] = []
    page.on(
        "console",
        lambda msg: violations.append(msg.text) if "Content Security Policy" in msg.text else None,
    )
    _open(page_server)
    page.wait_for_timeout(500)
    assert violations == []
