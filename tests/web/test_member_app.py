"""The member app's page, app.html: it signs in, asks the member API who you
are (E0), and shows the frame (E1): tabs, pages over them, the theme menu,
sign-out. The desk stays the front door until config.json says otherwise."""

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


def test_a_member_sees_the_frame(open_member_app, shot):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    tabs = page.get_by_role("navigation", name="Main")
    assert tabs.get_by_role("button").all_inner_texts() == [
        "Cats",
        "Scan a cat",
        "Home",
    ]
    assert tabs.locator("[aria-current=page]").inner_text() == "Cats"
    assert page.evaluate("document.documentElement.dataset.theme") == "bgu-dark"
    assert page.evaluate("document.documentElement.dir") == "ltr"
    # The theme's tokens reach the page, and the font is the vendored one.
    background = page.evaluate(
        "getComputedStyle(document.querySelector('.tab-page')).backgroundColor"
    )
    assert background == "rgb(20, 20, 20)"
    assert page.evaluate("document.fonts.check('16px Inter')")
    shot(page, "member-frame")


@pytest.mark.parametrize("theme", ["bgu-light", "cats-light", "cats-dark"])
def test_every_theme_draws(open_member_app, shot, theme):
    page = open_member_app(ADMIN)
    page.wait_for_selector("[data-screen=frame]")
    page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
    page.get_by_role("button", name="Home").click()
    background = page.evaluate(
        "getComputedStyle(document.querySelector('.tab-page')).backgroundColor"
    )
    assert background != "rgb(20, 20, 20)"
    shot(page, f"member-home-{theme}")


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


# ---------------------------------------------------------------- the frame (E1)


def frame(open_member_app, email=COLLABORATOR, **options):
    page = open_member_app(email, **options)
    page.wait_for_selector("[data-screen=frame]")
    return page


def lens_x(page):
    return page.evaluate("document.querySelector('.lens').getBoundingClientRect().x")


def test_the_tabs_switch_and_the_lens_follows(open_member_app):
    page = frame(open_member_app)
    before = lens_x(page)
    page.get_by_role("button", name="Home").click()
    assert (
        page.get_by_role("navigation", name="Main")
        .locator("[aria-current=page]")
        .inner_text()
        == "Home"
    )
    page.wait_for_function(
        f"document.querySelector('.lens').getBoundingClientRect().x > {before + 100}"
    )
    assert page.locator("[data-tab-page=home]").is_visible()
    assert not page.locator("[data-tab-page=feed]").is_visible()


def test_scan_says_it_is_coming(open_member_app, shot):
    page = frame(open_member_app)
    page.get_by_role("button", name="Scan a cat").click()
    status = page.get_by_role("status")
    page.wait_for_function("document.querySelector('.toast.on')")
    assert "capture flow" in status.inner_text()
    shot(page, "member-toast")


def test_a_page_slides_in_and_the_back_button_takes_it_away(open_member_app, shot):
    page = frame(open_member_app)
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    profile = page.locator("[data-page=profile]")
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=profile]').getBoundingClientRect().x) < 1"
    )
    shot(page, "member-profile")
    page.get_by_role("button", name="Back").click()
    profile.wait_for(state="detached")


def open_profile(page):
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    # Until the slide ends, the page is not yet under the screen's edge.
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=profile]').getBoundingClientRect().x) < 1"
    )


def test_a_swipe_from_the_edge_goes_back(open_member_app):
    page = frame(open_member_app)
    open_profile(page)
    page.mouse.move(6, 400)
    page.mouse.down()
    for x in range(20, 300, 40):
        page.mouse.move(x, 400)
    # The page follows the finger.
    assert (
        page.evaluate(
            "document.querySelector('[data-page=profile]').getBoundingClientRect().x"
        )
        > 100
    )
    page.mouse.up()
    page.locator("[data-page=profile]").wait_for(state="detached")


def test_a_swipe_that_does_not_start_at_the_edge_does_nothing(open_member_app):
    page = frame(open_member_app)
    open_profile(page)
    page.mouse.move(120, 400)
    page.mouse.down()
    page.mouse.move(360, 400)
    page.mouse.up()
    page.wait_for_timeout(600)
    assert page.locator("[data-page=profile]").count() == 1


def test_reduce_motion_turns_the_slide_into_a_fade(open_member_app):
    page = frame(open_member_app, reduced_motion="reduce")
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile]")
    style = page.evaluate(
        "(() => { const s = getComputedStyle(document.querySelector('[data-page=profile]'));"
        " return [s.transform, s.transitionProperty]; })()"
    )
    assert style == ["none", "opacity"]


def test_the_theme_menu_changes_the_theme_and_keeps_it(open_member_app, shot):
    page = frame(open_member_app)
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    page.locator("[data-row=theme]").click()
    menu = page.get_by_role("menu", name="Interface theme")
    assert menu.get_by_role("menuitemradio").all_inner_texts() == [
        "BGU light",
        "BGU dark",
        "Cat coat light",
        "Cat coat dark",
    ]
    assert menu.get_by_role("menuitemradio", checked=True).inner_text() == "BGU dark"
    page.wait_for_timeout(450)  # the menu's spring
    shot(page, "member-theme-menu")
    menu.get_by_role("menuitemradio", name="Cat coat light").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "cats-light"
    assert "Cat coat light" in page.locator("[data-row=theme]").inner_text()
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    assert page.evaluate("document.documentElement.dataset.theme") == "cats-light"


def test_escape_closes_a_menu(open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    page.locator("[data-row=theme]").click()
    page.get_by_role("menu").wait_for()
    # The menu takes the focus once drawn, and keys work from there.
    page.wait_for_function("document.activeElement.closest('[role=menu]')")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    page.get_by_role("menu").wait_for(state="detached")


def test_sign_out_asks_first(open_member_app, shot):
    page = frame(open_member_app)
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    page.locator(".group").last.get_by_role("button", name="Sign out").click()
    dialog = page.get_by_role("alertdialog")
    assert dialog.get_by_role("heading").inner_text() == "Sign out of BGU Cats?"
    page.wait_for_timeout(450)  # the dialog's spring
    shot(page, "member-sign-out")
    dialog.get_by_role("button", name="Cancel").click()
    dialog.wait_for(state="detached")
    assert page.locator("[data-page=profile]").count() == 1

    page.locator(".group").last.get_by_role("button", name="Sign out").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Sign out").click()
    page.wait_for_selector("[data-screen=sign-in]")
    assert page.evaluate("localStorage.getItem('bgucats.tokens')") is None


def test_the_tab_bar_shrinks_while_scrolling_down(open_member_app, shot):
    page = frame(open_member_app)
    # Enough to scroll: the feed's posts arrive in E2.
    page.evaluate(
        "document.querySelector('[data-tab-page=feed] .tab-content')"
        ".insertAdjacentHTML('beforeend', '<div style=\\'block-size: 3000px\\'></div>')"
    )
    scroller = "document.querySelector('[data-tab-page=feed] .scroller')"
    for y in (100, 200, 300):
        page.evaluate(f"{scroller}.scrollTo(0, {y})")
        page.wait_for_timeout(50)
    page.wait_for_selector(".tabbar.collapsed")
    page.wait_for_timeout(600)
    shot(page, "member-tabbar-collapsed")
    for y in (250, 200, 150):
        page.evaluate(f"{scroller}.scrollTo(0, {y})")
        page.wait_for_timeout(50)
    page.wait_for_selector(".tabbar:not(.collapsed)")


def test_the_frame_flows_at_three_widths(open_member_app, shot):
    for width in (375, 402, 430):
        page = frame(open_member_app, viewport={"width": width, "height": 844})
        bar = page.locator(".tabbar").bounding_box()
        assert bar["x"] >= 16 and bar["x"] + bar["width"] <= width - 16 + 0.5
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        shot(page, f"member-frame-{width}")


def test_right_to_left_mirrors_the_frame(open_member_app, shot):
    page = frame(open_member_app)
    page.evaluate("document.documentElement.dir = 'rtl'")
    page.wait_for_timeout(600)
    bar = page.locator(".tabbar").bounding_box()
    lens = page.locator(".lens").bounding_box()
    cats = page.get_by_role("button", name="Cats").bounding_box()
    # The first tab, and the lens on it, are at the bar's right end.
    assert cats["x"] > bar["x"] + bar["width"] / 2
    assert abs((lens["x"] + lens["width"]) - (bar["x"] + bar["width"] - 6)) < 2
    shot(page, "member-frame-rtl")
