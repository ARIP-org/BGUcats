"""The same web/ packed for the iPhone app (scripts/native_bundle.py), in
the test browser: served from one address, with its API at another, and
Capacitor's bridge present. What a simulator shows on launch, without a Mac.

Sign-in itself, and anything behind it, is not here yet: the API does not
answer another origin until the app signs in through the system browser
(docs/ROADMAP.md, 2e).
"""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from native_bundle import bundle

from .conftest import PHONE
from .localapp import ADMIN, token_for

# Where the packed config says the API is. Nothing listens there: the tests
# only look at where the page tries to go.
API = "http://127.0.0.1:9"
# What Capacitor injects into its web view before the page's own code runs.
BRIDGE = "window.Capacitor = { isNativePlatform: () => true, getPlatform: () => 'ios' }"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def open_native(browser, tmp_path):
    """open_native(email) -> a page of the packed app, as that member or
    signed out."""
    www = tmp_path / "www"
    bundle(
        API,
        {
            "userPoolClientId": "local",
            "cognitoDomain": "cognito.invalid",
            "redirectUri": "https://app.invalid/",
        },
        www,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(www)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    contexts = []
    problems = []

    def open_as(email=None, wait_until="load"):
        # Service workers are allowed here, unlike in conftest: one test
        # is that the packed app registers none.
        context = browser.new_context(viewport=PHONE, device_scale_factor=2)
        contexts.append(context)
        context.route(
            lambda address: not address.startswith("http://127.0.0.1"),
            lambda route: route.abort(),
        )
        context.add_init_script(BRIDGE)
        if email:
            tokens = json.dumps(json.dumps(token_for(email)))
            context.add_init_script(f"localStorage.setItem('bgucats.tokens', {tokens})")
        page = context.new_page()
        page.on("pageerror", lambda err: problems.append(f"JavaScript error: {err}"))
        page.native_url = url
        return page

    yield open_as
    for context in contexts:
        context.close()
    server.shutdown()
    assert not problems, problems


def test_the_packed_app_opens_on_sign_in_not_on_the_install_page(open_native, shot):
    page = open_native()
    page.goto(page.native_url)  # no ?browser: being the app is enough
    page.wait_for_selector("#login:not([hidden])")

    assert page.is_hidden("#install")
    assert page.is_hidden("#app")
    # Until it signs in through the system browser, it says so and offers
    # no button that leads nowhere.
    assert "not connected in the iPhone app yet" in page.inner_text("#login-alert")
    assert page.is_disabled("#login-button")
    shot(page, "native-sign-in")


def test_the_packed_app_registers_no_service_worker(open_native):
    page = open_native()
    page.goto(page.native_url)
    page.wait_for_selector("#login:not([hidden])")
    registrations = page.evaluate(
        "navigator.serviceWorker.getRegistrations().then(all => all.length)"
    )
    assert registrations == 0


def test_the_packed_app_calls_the_api_at_the_address_in_its_config(open_native):
    page = open_native(ADMIN)
    with page.expect_request(lambda request: "/api/" in request.url) as first:
        page.goto(page.native_url)
    assert first.value.url == f"{API}/api/me"
