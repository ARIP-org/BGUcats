"""The service worker itself (web/sw.js), run for real: the other screen
tests block it, so until 2026-11-14 nothing here had ever met it.

That day the owner's home-screen app would not open, and the iPhone app,
which has no worker, did. Two faults were found by reading: a page the
network neither answered nor refused was waited on for ever, and both
pages were kept under one name."""

import json

import pytest

from .conftest import PHONE, token_for
from .localapp import COLLABORATOR


@pytest.fixture
def with_worker(app, browser):
    """open() -> a signed-in page on the member app, the worker in control."""
    contexts = []

    def open():
        context = browser.new_context(viewport=PHONE, service_workers="allow")
        contexts.append(context)
        context.route(
            lambda url: not url.startswith("http://127.0.0.1"),
            lambda route: route.abort(),
        )
        tokens = json.dumps(json.dumps(token_for(COLLABORATOR)))
        context.add_init_script(f"localStorage.setItem('bgucats.tokens', {tokens});")
        page = context.new_page()
        page.goto(app.url + "/app.html?browser")
        page.wait_for_selector("[data-screen=frame]")
        page.evaluate("navigator.serviceWorker.register('/sw.js')")
        page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
        page.wait_for_function("!!navigator.serviceWorker.controller")
        return page

    yield open
    for context in contexts:
        context.close()


def test_the_member_app_registers_the_worker_itself(app, browser):
    # The installed app comes straight to this page, and "Reset the app on
    # this phone" removes the worker: the desk's page cannot be the only
    # one that registers it.
    context = browser.new_context(viewport=PHONE, service_workers="allow")
    try:
        tokens = json.dumps(json.dumps(token_for(COLLABORATOR)))
        context.add_init_script(f"localStorage.setItem('bgucats.tokens', {tokens});")
        page = context.new_page()
        page.goto(app.url + "/app.html?browser")
        page.wait_for_selector("[data-screen=frame]")
        assert page.evaluate("navigator.serviceWorker.getRegistration().then((found) => !found)")
        page.wait_for_function(
            "navigator.serviceWorker.getRegistration().then((found) => !!found)", timeout=15000
        )
    finally:
        context.close()


def test_a_page_the_network_never_answers_opens_from_the_kept_copy(app, with_worker):
    page = with_worker()
    # The page was fetched once more under the worker, so there is a copy.
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    # Now the network takes the request for the page and says nothing.
    asked = []
    page.context.route("**/app.html*", lambda route: asked.append(route.request.url))
    page.goto(app.url + "/app.html?browser", wait_until="commit", timeout=20000)
    page.wait_for_selector("[data-screen=frame]", timeout=20000)
    assert asked, "the page was never asked of the network: this test proves nothing"


def test_with_no_signal_each_page_opens_as_itself(app, with_worker):
    page = with_worker()
    # Both pages fetched under the worker, the desk last.
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.goto(app.url + "/?browser&desk")
    page.wait_for_selector("#app:not([hidden]), #login:not([hidden])")
    page.context.set_offline(True)
    page.goto(app.url + "/app.html?browser", wait_until="commit")
    page.wait_for_selector("#starting, [data-screen]")
    assert page.locator("script[src='social/main.js']").count() == 1
    page.goto(app.url + "/?browser&desk", wait_until="commit")
    page.wait_for_selector("#app, #login", state="attached")
    assert page.locator("script[src='social/main.js']").count() == 0
