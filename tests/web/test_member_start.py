"""The member app's start (web/app.html, web/social/main.js).

On 2026-11-14 the owner's phone showed a black screen for three minutes:
the start was waiting on something and had no way to say so, and three of
its requests had no time limit. The page now says it is loading before any
of the app's files have arrived, every step is named and bounded, and a
start that fails says where, with the ways out."""

from .localapp import COLLABORATOR

# What a phone's browser keeps for the app, recorded instead of done.
KEPT = """
window.reset = { unregistered: 0, deleted: [] };
Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: {
  getRegistrations: async () => [{ unregister: async () => { window.reset.unregistered += 1; return true; } }],
  register: async () => ({}), ready: new Promise(() => {}), controller: null,
}});
Object.defineProperty(window, "caches", { configurable: true, value: {
  keys: async () => ["bgucats-shell-v19", "bgucats-model-v1"],
  delete: async (key) => { window.reset.deleted.push(key); sessionStorage.setItem("test.deleted", JSON.stringify(window.reset.deleted)); return true; },
  open: async () => ({ match: async () => undefined, put: async () => {}, keys: async () => [] }),
  match: async () => undefined,
}});
"""


def hang(route):
    """A request that never answers."""


def test_the_page_says_loading_until_the_app_draws_and_then_gets_out_of_the_way(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    # Held at its last step, the page's own words are what is on screen.
    page.route("**/api/v1/me", hang)
    page.reload()
    line = page.locator("#starting-line")
    line.wait_for()
    assert line.inner_text() == "Loading…"
    assert page.locator("#starting-help").is_hidden()
    page.wait_for_function("document.documentElement.dataset.boot === 'account'")
    # The request answers: the app's first screen, and no trace of the start.
    page.unroute("**/api/v1/me")
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    assert page.locator("#starting").count() == 0
    assert page.evaluate("document.documentElement.dataset.boot") == "ready"


def test_a_slow_start_says_which_step_and_offers_the_ways_out(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    page.context.add_init_script(
        "window.bgucatsStartWaitMs = 600; window.bgucatsStepMs = 60000;"
        # A phone that will not copy for the page.
        "Object.defineProperty(navigator, 'clipboard', { configurable: true,"
        " value: { writeText: () => Promise.reject(new Error('not allowed')) } });"
    )
    # The settings never answer until "Try again" is tapped. Taking the
    # block off instead would let the waiting request through, and the app
    # would start by itself before the tap.
    tapped = []

    def answers_once_tapped(route):
        if tapped:
            route.continue_()

    page.route("**/config.json", answers_once_tapped)
    page.reload()
    help = page.locator("#starting-help")
    help.wait_for(state="visible")
    assert page.locator("#starting-line").inner_text() == (
        "Still loading the app's settings. This is taking longer than it should."
    )
    assert help.get_by_role("button").all_inner_texts() == [
        "Try again",
        "Reset the app on this phone",
        "Copy app info",
    ]
    # What the phone kept can be had from here too, with no app to show it:
    # copied, or shown to be copied by hand where the phone will not.
    help.get_by_role("button", name="Copy app info").click()
    box = page.locator("#starting-info-text")
    box.wait_for(state="visible")
    assert "still loading the app's settings" in box.input_value()
    # "Try again" is the page again; this time the request answers.
    tapped.append(True)
    help.get_by_role("button", name="Try again").click()
    page.wait_for_selector("[data-screen=frame]")


def test_a_step_that_never_answers_fails_by_name(open_member_app, shot):
    page = open_member_app(COLLABORATOR, wait=None)
    page.context.add_init_script("window.bgucatsStepMs = 500;")
    page.route("**/api/v1/me", hang)
    page.reload()
    failed = page.locator("[data-screen=start-failed]")
    failed.wait_for()
    assert failed.get_attribute("data-step") == "account"
    assert failed.get_by_role("heading").inner_text() == "The app could not start"
    assert failed.get_by_role("alert").inner_text() == "It stopped while reading your account."
    assert "It took too long." in failed.inner_text()
    # Someone signed in is not shown the sign-in screen: they can sign out.
    assert failed.get_by_role("button").all_inner_texts() == [
        "Try again",
        "Reset the app on this phone",
        "Copy app info",
        "Sign out",
    ]
    assert "start failed at account: It took too long." in page.evaluate("window.bgucatsInfo()")
    shot(page, "member-start-failed")


def test_a_request_that_fails_at_the_start_is_said_not_shown_as_signed_out(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    page.route("**/api/v1/me", lambda route: route.abort())
    page.reload()
    failed = page.locator("[data-screen=start-failed]")
    failed.wait_for()
    assert failed.get_attribute("data-step") == "account"
    assert page.locator("[data-screen=sign-in]").count() == 0


def test_the_words_of_a_failed_start_do_not_need_the_strings_file(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    page.route("**/i18n/*.json", lambda route: route.abort())
    page.reload()
    failed = page.locator("[data-screen=start-failed]")
    failed.wait_for()
    assert failed.get_attribute("data-step") == "strings"
    assert failed.get_by_role("alert").inner_text() == "It stopped while loading its words."
    assert failed.get_by_role("button", name="Try again").count() == 1


def test_reset_fetches_the_app_again_and_keeps_the_sign_in_and_the_model(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    page.context.add_init_script(KEPT + "window.bgucatsStepMs = 500;")
    page.route("**/api/v1/me", hang)
    page.reload()
    failed = page.locator("[data-screen=start-failed]")
    failed.wait_for()
    page.unroute("**/api/v1/me")
    with page.expect_navigation():
        failed.get_by_role("button", name="Reset the app on this phone").click()
    # The app's files went; the model's 40 MB and the sign-in stayed.
    assert page.evaluate("JSON.parse(sessionStorage.getItem('test.deleted'))") == ["bgucats-shell-v19"]
    assert page.evaluate("!!localStorage.getItem('bgucats.tokens')")
    page.wait_for_selector("[data-screen=frame]")


def test_the_installed_app_goes_straight_to_its_front_door(app, browser):
    """The site's root hands an installed app over to the member app before
    anything else of the desk has arrived, so a launch does not wait on the
    desk's script, its stylesheet or the fonts from another site."""
    app.front_door = "app"
    context = browser.new_context(service_workers="block")
    try:
        context.add_init_script("Object.defineProperty(navigator, 'standalone', { value: true });")
        context.route(lambda url: not url.startswith("http://127.0.0.1"), lambda route: route.abort())
        page = context.new_page()
        # The first launch reads the settings from the desk's page and remembers.
        page.goto(app.url + "/")
        page.wait_for_url("**/app.html")
        page.wait_for_selector("[data-screen=sign-in]")
        assert page.evaluate("localStorage.getItem('bgucats.frontDoor')") == "app"
        # Every launch after it, with the desk's own files never answering.
        page.route("**/app.js", hang)
        page.route("**/styles.css", hang)
        page.goto(app.url + "/", wait_until="commit")
        page.wait_for_url("**/app.html")
        page.wait_for_selector("[data-screen=sign-in]")
        page.unroute("**/app.js")
        page.unroute("**/styles.css")
        # The desk is still one address away, and so is a sign-in coming back.
        page.goto(app.url + "/?desk")
        page.wait_for_selector("#login:not([hidden]), #app:not([hidden])")
        assert page.url.endswith("/?desk")
    finally:
        context.close()
