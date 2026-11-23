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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Lets a fixture know, when it is torn down, whether its test failed."""
    outcome = yield
    setattr(item, f"report_{call.when}", outcome.get_result())


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


@pytest.fixture
def open_member_app(app, browser, request):
    """The member app (app.html). open_member_app(email) -> a page on app.html for that member (None:
    signed out). Fails the test on any JavaScript error or 5xx.

    When the test fails, the report gets what the app itself kept: its
    "App info" (the last eighty things it did, never who) and every request
    that failed or was refused. A screen test that fails once in CI and
    never again is otherwise a guess: on 2026-11-23 a post "did not arrive
    within the time" and nothing in the log could say which step waited."""
    contexts, problems, pages, refused = [], [], [], []

    def open_as(email, path="/app.html?browser", wait="[data-screen]", **options):
        context = browser.new_context(
            **{
                "viewport": PHONE,
                "device_scale_factor": 2,
                "service_workers": "block",
                **options,
            }
        )
        contexts.append(context)
        context.route(
            lambda url: not url.startswith("http://127.0.0.1"),
            lambda route: route.abort(),
        )
        if email:
            tokens = json.dumps(json.dumps(token_for(email)))
            # Once per tab, as a real sign-in is: a sign-out must stick.
            context.add_init_script(
                "if (!sessionStorage.getItem('test.signedIn')) {"
                f" localStorage.setItem('bgucats.tokens', {tokens});"
                " sessionStorage.setItem('test.signedIn', '1'); }"
            )
        page = context.new_page()
        pages.append(page)
        page.on("pageerror", lambda err: problems.append(f"JavaScript error: {err}"))
        page.on(
            "response",
            lambda res: (
                problems.append(f"{res.status} {res.url}")
                if res.status >= 500
                else refused.append(f"{res.status} {res.request.method} {res.url}")
                if res.status >= 400
                else None
            ),
        )
        page.on(
            "requestfailed",
            lambda req: refused.append(f"failed ({req.failure}) {req.method} {req.url}"),
        )
        page.goto(app.url + path)
        if wait:
            page.wait_for_selector(wait)
        return page

    yield open_as
    report = getattr(request.node, "report_call", None)
    if report is not None and report.failed:
        from playwright.sync_api import Error as PageError

        for page in pages:
            try:
                info = page.evaluate(
                    "window.bgucatsInfo ? window.bgucatsInfo() : '(this page keeps no app info)'"
                )
            except PageError as err:  # a closed or crashed page says nothing
                info = f"(the page could not say: {err})"
            print(f"\n--- App info of {page.url}\n{info}")
        print("\n--- Requests that failed or were refused")
        print("\n".join(refused) or "(none)")
    for context in contexts:
        context.close()
    assert not problems, problems
