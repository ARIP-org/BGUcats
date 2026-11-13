"""Languages and right to left (E10): the profile's menu, a language kept
with the account and on the phone, and every screen in Hebrew and in
Arabic, where the page runs the other way. Each screen is held to one
thing a test can see: nothing spills past the sides."""

import json
from pathlib import Path

import pytest

from .localapp import COLLABORATOR
from .test_member_capture import PHOTO
from .test_member_home import home

I18N = Path(__file__).resolve().parents[2] / "web" / "i18n"


def words(code):
    return json.loads((I18N / f"{code}.json").read_text())


def in_language(app, open_member_app, code, **options):
    status, body = app.api("PATCH", "/api/v1/me", {"language": code}, email=COLLABORATOR)
    assert status == 200, body
    page = open_member_app(COLLABORATOR, **options)
    page.wait_for_selector("[data-screen=frame]")
    return page


def fits(page):
    """Nothing wider than the screen, the commonest way a mirrored layout
    breaks: no page scrolls sideways, and nothing that can be seen hangs
    past an edge (outside the strips made to be scrolled sideways)."""
    page.wait_for_timeout(700)  # a page or a sheet has finished arriving
    wide = page.evaluate(
        """() => {
          const out = [];
          for (const e of [document.scrollingElement, ...document.querySelectorAll('.scroller')]) {
            if (e.scrollWidth > e.clientWidth + 1) out.push(`${e.className || 'page'} scrolls sideways: ${e.scrollWidth} > ${e.clientWidth}`);
          }
          const seen = (e) => { for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
            const s = getComputedStyle(n); if (s.opacity === '0' || s.visibility === 'hidden' || s.display === 'none') return false; } return true; };
          for (const e of document.querySelectorAll('.frame *, .scan *')) {
            const r = e.getBoundingClientRect();
            if (!r.width || !r.height || (r.right <= innerWidth + 1 && r.left >= -1)) continue;
            if (e.closest('[data-hscroll], .shots, .campus, [data-page=map], [hidden]') || !seen(e)) continue;
            out.push(`${e.className || e.tagName}: ${Math.round(r.left)}..${Math.round(r.right)}`);
          }
          return out.slice(0, 6);
        }"""
    )
    assert wide == [], wide


def test_the_profile_offers_each_language_by_its_own_name(app, open_member_app, shot):
    page = home(open_member_app)
    page.locator(".home-top .me-pill").click()
    row = page.locator(".row[data-row=language]")
    assert row.locator(".row-value").inner_text() == "English"
    row.click()
    menu = page.get_by_role("menu", name="Language")
    assert menu.get_by_role("menuitemradio").all_inner_texts() == [
        "English",
        "עברית",
        "Русский",
        "العربية",
    ]
    page.wait_for_timeout(450)
    shot(page, "member-language-menu")
    with page.expect_navigation():
        menu.get_by_role("menuitemradio", name="עברית").click()
    page.wait_for_selector("[data-screen=frame]")
    # The whole app again, in Hebrew and from the right.
    assert page.evaluate("[document.documentElement.lang, document.documentElement.dir]") == ["he", "rtl"]
    he = words("he")
    assert page.locator(".tabbar [data-tab=home] .tab-label").inner_text() == he["tab.home"]
    assert app.api("GET", "/api/v1/me", email=COLLABORATOR)[1]["language"] == "he"

    # Another phone of theirs opens in it too.
    other = open_member_app(COLLABORATOR)
    other.wait_for_selector("[data-screen=frame]")
    assert other.evaluate("document.documentElement.dir") == "rtl"
    assert other.locator(".tabbar [data-tab=home] .tab-label").inner_text() == he["tab.home"]


def test_a_language_this_account_is_not_offered_falls_back_to_english(app, open_member_app, monkeypatch):
    from app import handler

    monkeypatch.setattr(handler, "FLAGS", {**handler.FLAGS, "languages": ["en"]})
    page = in_language(app, open_member_app, "he")
    assert page.evaluate("[document.documentElement.lang, document.documentElement.dir]") == ["en", "ltr"]
    page.locator(".tabbar [data-tab=home]").click()
    page.locator(".home-top .me-pill").click()
    page.locator(".row[data-row=language]").click()
    assert page.get_by_role("menu").get_by_role("menuitemradio").all_inner_texts() == ["English"]


@pytest.mark.parametrize("code", ["he", "ar", "ru"])
def test_every_screen_in_each_draft(app, open_member_app, shot, code):
    """Hebrew and Arabic from the right; Russian for its longer words."""
    s = words(code)
    page = in_language(app, open_member_app, code)
    assert page.evaluate("document.documentElement.dir") == ("ltr" if code == "ru" else "rtl")
    page.wait_for_selector("article.post")
    fits(page)
    shot(page, f"member-feed-{code}")

    # A cat's page, with its feeding card and its poll.
    page.get_by_role("button", name=s["feed.gallery"]).click()
    fits(page)
    shot(page, f"member-gallery-{code}")
    page.locator("[data-page=gallery] button[aria-label]").filter(has_text="").first.wait_for()
    page.get_by_role("button", name=s["gallery.open"].replace("{name}", "Mitzi")).click()
    page.wait_for_selector("[data-page=cat] .poll")
    fits(page)
    shot(page, f"member-cat-{code}")

    # Home, the achievements sheet, the profile.
    page.goto(page.url)
    page.wait_for_selector("[data-screen=frame]")
    page.locator(".tabbar [data-tab=home]").click()
    page.wait_for_selector(".home-top .me-pill")
    page.locator(".achievements-card .achievements-sub").wait_for()
    fits(page)
    shot(page, f"member-home-{code}")
    page.locator(".achievements-card").click()
    page.get_by_role("dialog", name=s["ach.title"]).locator(".ach-number").wait_for()
    fits(page)
    shot(page, f"member-achievements-{code}")
    page.keyboard.press("Escape")
    page.locator(".home-top .me-pill").click()
    fits(page)
    shot(page, f"member-profile-{code}")

    # Friends and the map.
    page.goto(page.url)
    page.wait_for_selector("[data-screen=frame]")
    page.locator(".tabbar [data-tab=home]").click()
    page.locator(".friends-card").click()
    page.wait_for_selector("[data-page=friends]")
    fits(page)
    shot(page, f"member-friends-{code}")
    page.goto(page.url)
    page.wait_for_selector("[data-screen=frame]")
    page.wait_for_selector("article.post")
    page.locator("article.post .photo").first.click()
    page.get_by_role("menuitem", name=s["post.showOnMap"]).click()
    page.wait_for_selector("[data-page=map]")
    page.wait_for_timeout(900)
    shot(page, f"member-map-{code}")

    # The capture flow: which cat, you met, the post, a new cat.
    page.goto(page.url)
    page.wait_for_selector("[data-screen=frame]")
    page.locator(".tabbar [data-tab=scan]").click()
    page.wait_for_selector(".scan[data-step=camera]")
    page.set_input_files(".file-shot input", PHOTO)
    page.wait_for_selector(".scan[data-step=which]")
    fits(page)
    shot(page, f"member-scan-which-{code}")
    page.locator(".cat-grid-pick .cat-tile[aria-label=Mitzi]").click()
    page.wait_for_selector(".scan .poll")
    fits(page)
    shot(page, f"member-scan-met-{code}")
    page.locator(".scan-way.main").click()
    page.wait_for_selector(".scan[data-step=post]")
    fits(page)
    shot(page, f"member-scan-post-{code}")
    page.locator(".tagged-button").first.click()
    page.locator(".cat-tile.new").click()
    page.wait_for_selector(".scan[data-step=new]")
    fits(page)
    page.locator(".scan .scroller").evaluate("e => e.scrollTo(0, 0)")
    shot(page, f"member-scan-new-{code}")
