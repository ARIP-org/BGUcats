"""The member app's page, app.html (milestone E0): it signs in, asks the
member API who you are, and shows the empty frame; the desk stays the front
door until config.json says otherwise."""

import json

import pytest

from app import handler as app_handler

from .conftest import PHONE
from .localapp import ADMIN, COLLABORATOR, token_for


@pytest.fixture
def open_member_app(app, browser):
    """open_member_app(email) -> a page on app.html for that member (None:
    signed out). Fails the test on any JavaScript error or 5xx."""
    contexts, problems = [], []

    def open_as(email, path="/app.html?browser", wait="[data-screen]"):
        context = browser.new_context(
            viewport=PHONE, device_scale_factor=2, service_workers="block"
        )
        contexts.append(context)
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
        page.goto(app.url + path)
        if wait:
            page.wait_for_selector(wait)
        return page

    yield open_as
    for context in contexts:
        context.close()
    assert not problems, problems


def test_a_member_sees_the_empty_frame(open_member_app, shot):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    assert page.locator(".title").inner_text().startswith("Hi, ")
    assert page.evaluate("document.documentElement.dataset.theme") == "bgu-dark"
    assert page.evaluate("document.documentElement.dir") == "ltr"
    # The theme's tokens reach the page, and the font is the vendored one.
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(20, 20, 20)"
    assert page.evaluate("document.fonts.check('16px Inter')")
    shot(page, "member-frame")


@pytest.mark.parametrize("theme", ["bgu-light", "cats-light", "cats-dark"])
def test_every_theme_draws(open_member_app, shot, theme):
    page = open_member_app(ADMIN)
    page.wait_for_selector("[data-screen=frame]")
    page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != (
        "rgb(20, 20, 20)"
    )
    shot(page, f"member-frame-{theme}")


def test_signed_out_it_offers_sign_in(open_member_app, shot):
    page = open_member_app(None)
    page.wait_for_selector("[data-screen=sign-in]")
    assert page.get_by_role("button", name="Sign in with Google").is_visible()
    shot(page, "member-sign-in")


def test_with_the_app_off_it_says_so_and_points_to_the_desk(
    open_member_app, monkeypatch, shot
):
    monkeypatch.setattr(app_handler, "SOCIAL", False)
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=not-open]")
    assert page.get_by_role("link").get_attribute("href") == "/?desk"
    shot(page, "member-not-open")


def test_the_desk_stays_the_front_door(open_member_app):
    page = open_member_app(COLLABORATOR, path="/?browser", wait="#app:not([hidden])")
    assert page.url.endswith("/?browser")


def test_with_the_front_door_on_the_app_the_site_opens_it(app, open_member_app):
    app.front_door = "app"
    page = open_member_app(COLLABORATOR, path="/?browser", wait="[data-screen=frame]")
    assert "/app.html" in page.url
    # ?desk keeps the desk for an admin.
    desk = open_member_app(ADMIN, path="/?browser&desk", wait="#app:not([hidden])")
    assert "/app.html" not in desk.url


def test_a_browser_tab_gets_the_install_page(open_member_app):
    page = open_member_app(
        COLLABORATOR, path="/app.html", wait="#install:not([hidden])"
    )
    assert "/app.html" not in page.url
