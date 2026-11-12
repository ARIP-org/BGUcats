"""The feed (E2): the seeded campus's post, its photo and like, today's cat,
the photo's menu, a cat's page, deleting one's own post, and paging."""

import pytest
from ulid import ULID

from app import handler as app_handler

from .localapp import ADMIN, COLLABORATOR


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


def test_today_s_cat_is_at_the_top(open_member_app):
    page = feed(open_member_app)
    cotd = page.locator("button.cotd")
    assert "Cat of the day" in cotd.inner_text()
    assert cotd.locator(".cotd-name").inner_text() in {"Mitzi", "Shunra", "Pilpel"}


def test_a_like_counts_at_once_and_stays(open_member_app, app):
    page = feed(open_member_app, COLLABORATOR)
    like = page.locator("article.post").first.locator("button.like")
    assert like.get_attribute("aria-pressed") == "false"
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
    assert menu.get_by_role("menuitem").all_inner_texts() == ["See Mitzi"]
    page.keyboard.press("Escape")

    mine = feed(open_member_app, COLLABORATOR)
    mine.locator("article.post .photo").first.click()
    menu = mine.get_by_role("menu", name="Post options")
    assert menu.get_by_role("menuitem").all_inner_texts() == [
        "See Mitzi",
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


def test_the_top_buttons_say_what_they_will_open(open_member_app):
    page = feed(open_member_app)
    page.get_by_role("button", name="Search cats").click()
    page.wait_for_function("document.querySelector('.toast.on')")
    assert "gallery" in page.get_by_role("status").inner_text()


@pytest.mark.parametrize("theme", ["bgu-light", "cats-dark"])
def test_the_feed_in_other_themes(open_member_app, shot, theme):
    page = feed(open_member_app)
    page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
    page.wait_for_timeout(400)  # the colours' transitions
    shot(page, f"member-feed-{theme}")
