"""The app's own account of what it was doing (web/app.html, web/social/
trail.js, "App info" in Profile).

Three fixes for the owner's phone were written blind on 2026-11-14: a
freeze cannot be seen from anywhere but the phone, and the phone kept
nothing. Now the page keeps the last eighty things the app did, notices
when the screen stopped answering, and shows it all to be copied. It names
nobody."""

from .localapp import COLLABORATOR
from .test_member_home import home, open_profile

TRAIL = "JSON.parse(localStorage.getItem('bgucats.trail')).map((line) => line[1])"


def test_app_info_says_what_the_app_did_and_names_nobody(open_member_app, shot):
    page = home(open_member_app)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_profile(page).locator("[data-row=app-info]").click()
    info = page.locator("[data-page=appInfo]")
    info.get_by_role("heading", name="App info").wait_for()
    text = info.locator(".app-info").inner_text()
    head, lines = text.split("\n\n", 1)
    assert "kind: browser tab" in head
    assert "page: /app.html, start: ready" in head
    assert "signed in: yes" in head
    # The start, step by step, in order.
    said = [line.split("  ", 1)[1] for line in lines.splitlines()]
    steps = [line for line in said if line.startswith(("opened", "start:"))]
    assert steps[-6:] == [
        "opened /app.html (browser tab)",
        "start: strings",
        "start: settings",
        "start: sign-in",
        "start: account",
        "start: ready",
    ]
    # Nobody's address, and no token: only that there is a sign-in.
    assert COLLABORATOR not in text
    assert "eyJ" not in text
    page.wait_for_selector("[data-page=appInfo][data-state=shown]")
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-app-info")
    # Copied whole.
    info.get_by_role("button", name="Copy app info").click()
    page.get_by_text("Copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == text


def test_a_screen_that_stops_answering_is_written_down(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    # Two and a half seconds in which the page can do nothing at all.
    page.evaluate("() => { const until = performance.now() + 2500; while (performance.now() < until); }")
    page.wait_for_function(f"{TRAIL}.some((line) => line.startsWith('the screen did not answer for'))")
    held = page.evaluate(f"{TRAIL}.find((line) => line.startsWith('the screen did not answer for'))")
    assert 1.5 <= float(held.split()[-2]) <= 4


def test_the_capture_flow_and_what_it_asks_the_phone_are_written_down(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    page.wait_for_function(f"{TRAIL}.some((line) => line.startsWith('the camera:'))")
    said = page.evaluate(TRAIL)
    opened = said.index("capture flow opened (scan)")
    assert said[opened + 1] == "capture flow drawn"
    assert "asking the phone for the camera" in said[opened:]
    page.locator(".camera-bar").get_by_role("button", name="Close").click()
    page.wait_for_function(f"{TRAIL}.includes('capture flow closed')")


def test_a_failure_nobody_caught_is_written_down(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    # The event a browser sends for a promise nobody caught; sent by hand,
    # because a real one fails every test here, as it should.
    page.evaluate(
        "window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection',"
        " { promise: Promise.resolve(), reason: new Error('the roof fell in') }))"
    )
    page.wait_for_function(f"{TRAIL}.includes('failed: the roof fell in')")


def test_only_the_last_eighty_lines_are_kept(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    page.evaluate("for (let n = 0; n < 200; n++) window.bgucatsMark('line ' + n)")
    said = page.evaluate(TRAIL)
    assert len(said) == 80
    assert said[-1] == "line 199"
    # A line is cut, never the whole record lost to one long message.
    page.evaluate("window.bgucatsMark('x'.repeat(5000))")
    assert len(page.evaluate(TRAIL)[-1]) == 200
