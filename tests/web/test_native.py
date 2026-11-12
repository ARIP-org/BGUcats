"""The same web/ packed for the iPhone app (scripts/native_bundle.py), in
the test browser: served from one address, with its API at another, and
Capacitor's bridge present. What a phone shows, without a Mac.

Two things are stood in for. iOS's sign-in sheet (native/plugins/web-auth)
is a few lines of JavaScript that answer the way the sheet would, and
Cognito's token endpoint is answered by the test. Everything between them
is the real page, and everything behind them is the real API handler: the
local app answers another origin the way API Gateway does (localapp.py,
do_OPTIONS), which is what the packed app depends on.
"""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from native_bundle import app_redirect, bundle

from .conftest import PHONE
from .localapp import ADMIN, COLLABORATOR, sample_photo, token_for

REDIRECT = app_redirect()  # org.arip.bgucats://signin
TOKEN_URL = "https://cognito.invalid/oauth2/token"

# What Capacitor injects into its web view before the page's own code runs:
# the bridge, and one object per registered plugin. `sheet` is how the
# stand-in for iOS's sign-in sheet answers `start`.
BRIDGE = """
window.sheetCalls = [];
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => "ios",
  Plugins: %(plugins)s,
};
"""
WEB_AUTH = """{
  WebAuth: {
    start: async (options) => {
      // Kept across the reload that follows a sign-in.
      sessionStorage.setItem("test.sheet", JSON.stringify(options));
      %(sheet)s
    },
  },
}"""
SHEETS = {
    "signs in": f'return {{ url: "{REDIRECT}?code=the-code" }};',
    "is closed": 'throw { message: "Sign-in was cancelled.", code: "CANCELLED" };',
    "is refused": (
        f'return {{ url: "{REDIRECT}?error=invalid_request&error_description="'
        ' + encodeURIComponent("PreSignUp failed with error stranger@example.com is not invited.") };'
    ),
}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def open_native(app, browser, tmp_path):
    """open_native(sheet=..., email=...) -> a page of the packed app, signed
    out. `sheet` names how the sign-in sheet answers (SHEETS), or None for a
    build without the plugin; `email` is who Cognito then says signed in."""
    www = tmp_path / "www"
    bundle(
        app.url,
        {
            "userPoolClientId": "local",
            "cognitoDomain": "cognito.invalid",
            "redirectUri": app.url + "/",
        },
        www,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(www)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    contexts = []
    problems = []

    def open_as(sheet="signs in", email=ADMIN, door="desk"):
        # Service workers are allowed here, unlike in conftest: one test
        # is that the packed app registers none.
        context = browser.new_context(viewport=PHONE, device_scale_factor=2)
        contexts.append(context)
        context.route(
            lambda address: not address.startswith("http://127.0.0.1"),
            lambda route: route.abort(),
        )
        # Cognito trades the code for tokens. It answers any origin, the
        # app's included (checked against staging's on 2026-11-11).
        page_tokens = []

        def tokens(route):
            page_tokens.append(parse_qs(route.request.post_data))
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"access-control-allow-origin": "*"},
                body=json.dumps(
                    {
                        "id_token": token_for(email)["idToken"],
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    }
                ),
            )

        context.route(TOKEN_URL, tokens)
        plugins = WEB_AUTH % {"sheet": SHEETS[sheet]} if sheet else "{}"
        context.add_init_script(BRIDGE % {"plugins": plugins})
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
        page.token_requests = page_tokens
        # No ?browser: being the app is enough. The packed app's front door
        # is the member app (N1); `?desk` keeps the desk, as on the site.
        if door == "desk":
            page.goto(url + "?desk")
            page.wait_for_selector("#login:not([hidden])")
        else:
            page.goto(url)
            page.wait_for_selector("[data-screen=sign-in]")
        return page

    yield open_as
    for context in contexts:
        context.close()
    server.shutdown()
    assert not problems, problems


def test_the_packed_app_opens_on_sign_in_not_on_the_install_page(open_native, shot):
    page = open_native()
    assert page.is_hidden("#install")
    assert page.is_hidden("#app")
    assert page.is_hidden("#login-alert")
    assert page.is_enabled("#login-button")
    shot(page, "native-sign-in")


def test_signing_in_goes_through_the_sheet_and_lands_in_the_app(open_native, shot):
    page = open_native()
    page.click("#login-button")
    page.wait_for_selector("#app:not([hidden])")

    # The sheet was sent to Cognito, and told which scheme means "done".
    asked = json.loads(page.evaluate("sessionStorage.getItem('test.sheet')"))
    assert asked["callbackScheme"] == "org.arip.bgucats"
    authorize = urlsplit(asked["url"])
    assert (authorize.scheme, authorize.netloc, authorize.path) == (
        "https",
        "cognito.invalid",
        "/oauth2/authorize",
    )
    query = parse_qs(authorize.query)
    assert query["redirect_uri"] == [REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["select_account"]

    # The code it came back with was traded once, with the PKCE verifier and
    # the same address Cognito was told to answer at.
    [traded] = page.token_requests
    assert traded["grant_type"] == ["authorization_code"]
    assert traded["code"] == ["the-code"]
    assert traded["redirect_uri"] == [REDIRECT]
    assert len(traded["code_verifier"][0]) >= 43

    # And the API, which is at another address, answered the packed pages:
    # the admin's queue with its photos.
    page.wait_for_function(
        "[...document.querySelectorAll('#main img')].length > 0 && "
        "[...document.querySelectorAll('#main img')].every(i => i.complete && i.naturalWidth > 0)"
    )
    assert "labeling desk" in page.inner_text("#brand-role")
    shot(page, "native-queue")


def test_closing_the_sheet_leaves_the_sign_in_screen_as_it_was(open_native):
    page = open_native(sheet="is closed")
    page.click("#login-button")
    page.wait_for_function("sessionStorage.getItem('test.sheet') !== null")
    page.wait_for_timeout(300)
    assert page.is_visible("#login-button")
    assert page.is_hidden("#login-alert")
    assert page.query_selector_all(".toast") == []
    assert page.token_requests == []


def test_someone_not_invited_is_told_so_on_the_sign_in_screen(open_native):
    page = open_native(sheet="is refused")
    page.click("#login-button")
    page.wait_for_selector("#login-alert:not([hidden])")
    said = page.inner_text("#login-alert")
    assert "stranger@example.com is not invited." in said
    assert "PreSignUp" not in said
    assert page.token_requests == []


def test_a_build_without_the_sign_in_plugin_says_it_cannot_sign_in(open_native):
    page = open_native(sheet=None)
    assert "cannot sign in" in page.inner_text("#login-alert")
    assert page.is_disabled("#login-button")


def test_the_packed_app_registers_no_service_worker(open_native):
    page = open_native()
    registrations = page.evaluate(
        "navigator.serviceWorker.getRegistrations().then(all => all.length)"
    )
    assert registrations == 0


def test_a_photo_taken_in_the_packed_app_reaches_the_queue(app, open_native):
    """Capture from inside the app: the record and the confirmation go to an
    API at another address, the photo itself straight to storage."""
    page = open_native(email=COLLABORATOR)
    page.click("#login-button")
    page.get_by_role("button", name="Start an encounter").click()
    photo = {"name": "cat.jpg", "mimeType": "image/jpeg", "buffer": sample_photo(98)}
    with page.expect_response(lambda res: res.url.endswith("/complete")) as confirmed:
        page.set_input_files(".system-camera input[accept='image/*']", photo)
    assert confirmed.value.status == 200
    page.get_by_role("dialog", name="Camera").get_by_text(
        "Everything is uploaded."
    ).wait_for()

    _, queue = app.api("GET", "/api/queue")
    newest = max(queue["sessions"], key=lambda s: s["session"]["startedAt"])
    assert newest["session"]["startedBy"] == COLLABORATOR
    assert [p["status"] for p in newest["photos"]] == ["unlabeled"]


def test_the_packed_app_opens_the_member_app_and_signs_in_there(open_native, shot):
    page = open_native(door="app", email=COLLABORATOR)
    assert page.url.endswith("/app.html")
    shot(page, "native-member-sign-in")
    page.get_by_role("button", name="Sign in with Google").click()
    page.wait_for_selector("[data-screen=frame]")
    asked = json.loads(page.evaluate("sessionStorage.getItem('test.sheet')"))
    assert asked["callbackScheme"] == "org.arip.bgucats"
    page.wait_for_selector(".feed")
    shot(page, "native-member-feed")


def test_the_packed_app_asks_the_site_for_the_model(app, open_native, shot):
    """The model is published to the site's /model/, which the app's pages
    reach at the packed config's apiBase (N1), never at their own address.
    With no model there, nothing on the screen breaks: Capture uploads, and
    Done asks who it was, as on the site when the model is missing."""
    page = open_native(email=ADMIN)
    asked = []
    page.on(
        "request", lambda req: asked.append(req.url) if "/model/" in req.url else None
    )
    page.click("#login-button")
    page.click(".tab[data-view=queue]")
    page.wait_for_selector(".session-list")

    page.click(".tab[data-view=capture]")
    page.get_by_role("button", name="Start an encounter").click()
    photo = {"name": "cat.jpg", "mimeType": "image/jpeg", "buffer": sample_photo(97)}
    page.set_input_files(".system-camera input[accept='image/*']", photo)
    camera = page.get_by_role("dialog", name="Camera")
    camera.get_by_text("Everything is uploaded.").wait_for()
    camera.get_by_role("button", name="Done").click()
    page.get_by_text("Who did you meet?").wait_for()
    shot(page, "native-capture-done")
    assert asked, "the app never asked for the model"
    assert all(url.startswith(app.url + "/model/") for url in asked), asked
