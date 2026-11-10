"""Fixtures for the browser tests: the local app (localapp.py), a headless
Chromium the size of a phone, and a page that is already signed in.

Every test that opens a page also checks, when it ends, that the page threw
no JavaScript error and that the API never answered 5xx. A screen that
renders but logs an exception is a broken screen.
"""

import json
import os
from pathlib import Path

import pytest

from .localapp import LocalApp, token_for

SCREENSHOTS = Path(__file__).resolve().parents[2] / "build" / "screenshots"

# An iPhone-sized viewport: the app is used on phones.
PHONE = {"width": 390, "height": 844}


@pytest.fixture(scope="session")
def browser():
    playwright_api = pytest.importorskip(
        "playwright.sync_api", reason="pip install -r requirements-dev.txt"
    )
    with playwright_api.sync_playwright() as playwright:
        try:
            # Claude Code's cloud sessions ship a Chrome and say where it is.
            chrome = os.environ.get("CHROME_PATH")
            browser = playwright.chromium.launch(executable_path=chrome or None)
        except playwright_api.Error as err:
            # CI sets this, so a missing browser fails there, not skips.
            if os.environ.get("BGUCATS_REQUIRE_BROWSER"):
                raise
            pytest.skip(f"no browser to run (playwright install chromium): {err}")
        yield browser
        browser.close()


@pytest.fixture
def app():
    """The app on localhost with a small campus in it (LocalApp.seed)."""
    with LocalApp() as local:
        local.data = local.seed()
        yield local


@pytest.fixture
def open_app(app, browser):
    """open_app(email) -> a page with the app loaded for that member.
    open_app(None) is signed out, installed=False is a plain browser tab,
    and member=False is someone the allowlist will refuse."""
    contexts = []
    problems = []

    def open_as(email, installed=True, member=True):
        context = browser.new_context(
            viewport=PHONE, device_scale_factor=2, service_workers="block"
        )
        contexts.append(context)
        # Nothing but the local app: no fonts from Google, no real AWS.
        context.route(
            lambda url: not url.startswith("http://127.0.0.1"),
            lambda route: route.abort(),
        )
        if email:
            tokens = json.dumps(json.dumps(token_for(email)))
            context.add_init_script(f"localStorage.setItem('bgucats.tokens', {tokens})")
        page = context.new_page()
        page.on("pageerror", lambda err: problems.append(f"JavaScript error: {err}"))
        page.on(
            "response",
            lambda res: (
                problems.append(f"{res.status} {res.url}")
                if res.status >= 500
                else None
            ),
        )
        # ?browser is what lets the app run in a tab (web/install.js).
        page.goto(app.url + ("/?browser" if installed else "/"))
        if email and installed and member:
            page.wait_for_selector("#app:not([hidden])")
        return page

    yield open_as
    for context in contexts:
        context.close()
    assert not problems, problems


@pytest.fixture
def shot():
    """shot(page, "name") saves build/screenshots/name.png once the photos
    on screen have loaded. CI uploads the folder with every run."""

    def save(page, name):
        page.wait_for_function(
            "[...document.querySelectorAll('img')].every(i => i.complete)"
        )
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=SCREENSHOTS / f"{name}.png")

    return save
