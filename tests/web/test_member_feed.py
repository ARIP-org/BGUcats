"""The feed (E2): the seeded campus's post, its photo and like, today's cat,
the photo's menu, a cat's page, deleting one's own post, and paging."""

import pytest
from ulid import ULID

from app import handler as app_handler

from .localapp import ADMIN, COLLABORATOR, Campus


def feed(open_member_app, email=ADMIN, **options):
    page = open_member_app(email, **options)
    page.wait_for_selector("[data-screen=frame]")
    page.wait_for_selector("article.post")
    page.wait_for_function(
        "[...document.querySelectorAll('article.post img')].every(i => i.complete && i.naturalWidth)"
    )
    return page


def test_the_seeded_post_is_in_the_feed_with_its_photo_and_likes(open_member_app, shot):
    page = feed(open_member_app)
    post = page.locator("article.post").first
    assert "collaborator" in post.locator(".post-name").inner_text()
    assert post.locator(".post-what").inner_text().startswith("met Mitzi")
    assert post.locator(".post-text").inner_text() == "Asleep on the library steps."
    like = post.locator("button.like")
    # The admin liked it in the seed.
    assert like.get_attribute("aria-pressed") == "true"
    assert like.inner_text().strip() == "1"
    # Three photos in the encounter, shown one at a time.
    assert post.locator(".photo-count").inner_text() == "1/3"
    shot(page, "member-feed")


def test_a_post_of_twelve_photos_fits_the_phone(open_member_app, app, shot):
    # Every photo of an encounter (#105): twelve, newest post first, in the
    # feed, and the cat's page after it, at a phone's width.
    campus = Campus(app.api, ADMIN, COLLABORATOR)
    mitzi = app.data["cats"]["Mitzi"]
    session = campus.add_encounter(photos=12, seed=7)
    campus.post(session, mitzi, "Twelve of Mitzi.", COLLABORATOR)
    campus.label(session, mitzi)

    page = open_member_app(ADMIN)
    page.wait_for_selector("article.post")
    post = page.locator("article.post").first
    assert post.locator(".post-text").inner_text() == "Twelve of Mitzi."
    # The photos far along the strip are lazy and wait until it is swiped
    # towards them, which is right on a phone; the screenshot waits for
    # every picture, so here they are fetched at once.
    loaded = (
        "[...document.querySelectorAll('img')].every(i => { i.loading = 'eager';"
        " return i.complete && i.naturalWidth })"
    )
    page.wait_for_function(loaded)
    assert post.locator(".photo-strip img").count() == 12
    assert post.locator(".photo-count").inner_text() == "1/12"
    width = page.evaluate("document.documentElement.clientWidth")
    for box in (post, post.locator(".photo-count"), post.locator(".photo-strip")):
        edges = box.bounding_box()
        assert -1 < edges["x"] and edges["x"] + edges["width"] < width + 1
    shot(page, "member-feed-twelve-photos")

    post.locator(".cat-link").click()
    cat = page.locator("[data-page=cat]")
    cat.locator("h1").wait_for()
    # The page lists posts by who and when; its strip is the cat's newest
    # labeled photos (CAT_PAGE_PHOTOS, twelve), here all of this encounter.
    cat.locator(".cat-post").first.wait_for()
    assert cat.locator(".cat-post").count() == 2
    strip = cat.locator(".cat-photos")
    assert strip.locator(".photo-strip img").count() == 12
    assert strip.locator(".photo-count").inner_text() == "1/12"
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=cat]').getBoundingClientRect().x) < 1"
    )
    page.wait_for_function(loaded)
    for box in (strip, strip.locator(".photo-count")):
        edges = box.bounding_box()
        assert -1 < edges["x"] and edges["x"] + edges["width"] < width + 1
    shot(page, "member-cat-twelve-photos")


def test_today_s_cat_is_at_the_top(open_member_app):
    page = feed(open_member_app)
    cotd = page.locator("button.cotd")
    assert "Cat of the day" in cotd.inner_text()
    assert cotd.locator(".cotd-name").inner_text() in {"Mitzi", "Shunra", "Pilpel"}


def test_a_like_counts_at_once_and_stays(open_member_app, app):
    page = feed(open_member_app, COLLABORATOR)
    like = page.locator("article.post").first.locator("button.like")
    assert like.get_attribute("aria-pressed") == "false"
    # The count on screen changes before the request is sent: "at once".
    # So the screen saying 2 says nothing about the API yet, and asking it
    # then was a race (lost once in CI, 2026-11-22). The answer is waited for.
    with page.expect_response(lambda r: r.url.endswith("/like") and r.request.method == "PUT"):
        like.click()
    page.wait_for_function(
        "document.querySelector('article.post button.like').innerText.trim() === '2'"
    )
    assert like.get_attribute("aria-pressed") == "true"
    # The API agrees.
    _, body = app.api("GET", "/api/v1/feed", email=COLLABORATOR)
    assert body["cards"][0]["likes"] == 2 and body["cards"][0]["liked"]
    like.click()
    page.wait_for_function(
        "document.querySelector('article.post button.like').innerText.trim() === '1'"
    )


def test_a_like_with_no_signal_is_taken_back(open_member_app):
    page = feed(open_member_app, COLLABORATOR)
    page.route("**/api/v1/posts/*/like", lambda route: route.abort())
    like = page.locator("article.post").first.locator("button.like")
    like.click()
    page.wait_for_function("document.querySelector('.toast.on')")
    assert "didn't go through" in page.get_by_role("status").inner_text()
    assert like.get_attribute("aria-pressed") == "false"
    assert like.inner_text().strip() == "1"


def test_the_cat_s_name_opens_its_page(open_member_app, shot):
    page = feed(open_member_app, COLLABORATOR)
    page.locator("article.post .cat-link").first.click()
    cat = page.locator("[data-page=cat]")
    cat.locator("h1").wait_for()
    assert cat.locator("h1").inner_text() == "Mitzi"
    # The collaborator met Mitzi: picked, posted, labeled (the seed).
    page.wait_for_function(
        "document.querySelector('.cat-met')?.innerText.includes('once')"
    )
    page.wait_for_function(
        "[...document.querySelectorAll('[data-page=cat] img')].every(i => i.complete)"
    )
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=cat]').getBoundingClientRect().x) < 1"
    )
    shot(page, "member-cat")


def test_the_photo_s_menu_offers_the_cat_and_for_its_author_deleting(
    open_member_app, shot
):
    page = feed(open_member_app, ADMIN)
    page.locator("article.post .photo").first.click()
    menu = page.get_by_role("menu", name="Post options")
    # Someone else's post can be reported; one's own can be deleted.
    assert menu.get_by_role("menuitem").all_inner_texts() == ["See Mitzi", "Show on map", "Report"]
    page.keyboard.press("Escape")

    mine = feed(open_member_app, COLLABORATOR)
    mine.locator("article.post .photo").first.click()
    menu = mine.get_by_role("menu", name="Post options")
    assert menu.get_by_role("menuitem").all_inner_texts() == [
        "See Mitzi",
        "Show on map",
        "Delete post",
    ]
    mine.wait_for_timeout(450)
    shot(mine, "member-post-menu")
    menu.get_by_role("menuitem", name="Delete post").click()
    mine.get_by_role("alertdialog").get_by_role("button", name="Delete post").click()
    mine.locator("article.post").wait_for(state="detached")
    assert "No posts yet" in mine.locator(".feed .empty").inner_text()


def test_the_feed_pages_as_it_scrolls(open_member_app, app, monkeypatch):
    # A page of one card, so the seed's single post and two more make three.
    monkeypatch.setattr(app_handler, "FEED_PAGE", 1)
    for n in range(2):
        session = app.data["queue"][n]
        _, detail = app.api("GET", f"/api/sessions/{session}")
        status, answer = app.api(
            "POST",
            "/api/v1/posts",
            {
                "postId": str(ULID()),
                "sessionId": session,
                "photoIds": [detail["photos"][0]["photoId"]],
                "claim": None,
                "text": f"Post {n}",
            },
            email=COLLABORATOR,
        )
        assert status == 200, answer
    assert len(app.api("GET", "/api/v1/feed", email=ADMIN)[1]["cards"]) == 1
    page = feed(open_member_app, ADMIN)
    # Pages of one card: the second arrives before the first is read to its
    # end; the third once the feed is scrolled down.
    page.wait_for_function("document.querySelectorAll('article.post').length >= 2")
    page.evaluate(
        "document.querySelector('[data-tab-page=feed] .scroller').scrollTo(0, 99999)"
    )
    page.wait_for_function("document.querySelectorAll('article.post').length === 3")


def test_the_plus_button_opens_a_new_post(open_member_app):
    # The gallery button and the search bar: tests/web/test_member_gallery.py.
    page = feed(open_member_app)
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()


@pytest.mark.parametrize("theme", ["bgu-light", "cats-dark"])
def test_the_feed_in_other_themes(open_member_app, shot, theme):
    page = feed(open_member_app)
    page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
    page.wait_for_timeout(400)  # the colours' transitions
    shot(page, f"member-feed-{theme}")
