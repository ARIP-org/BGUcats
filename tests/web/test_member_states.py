"""The states the design does not draw (E9; docs/app-plan/05-client.md):
nothing here yet, no signal, a post on its way, a post that was not
published. Each is built from the app's own pieces and leaves a picture
for the owner (`make screenshots`)."""

from .localapp import ADMIN, COLLABORATOR
from .test_member_capture import eventually, frame, my_posts, scan_one
from .test_member_home import home


def the_post(app):
    return app.api("GET", "/api/v1/me/posts", email=COLLABORATOR)[1]["cards"][0]


def test_an_empty_feed_shows_the_mascot_and_the_next_thing_to_do(app, open_member_app, shot):
    app.api("DELETE", f"/api/v1/posts/{the_post(app)['postId']}", email=COLLABORATOR)
    page = frame(open_member_app)
    empty = page.locator(".feed .empty-state")
    assert "No posts yet" in empty.locator(".empty").inner_text()
    assert empty.locator("svg.mascot").count() == 1
    shot(page, "member-feed-empty")
    empty.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")


def test_with_no_signal_the_feed_is_shown_from_memory(app, open_member_app, shot):
    page = frame(open_member_app)
    page.wait_for_selector("article.post")
    # The feed cannot be reached any more: what this phone last saw stays.
    page.route("**/api/v1/feed*", lambda route: route.abort())
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    note = page.locator(".feed-note")
    note.wait_for()
    assert note.inner_text() == "No signal. This is the feed as you last saw it."
    assert page.locator("article.post").count() == 1
    assert page.locator(".feed .empty-state").count() == 0
    shot(page, "member-feed-no-signal")
    # A like says it did not go through.
    page.route("**/api/v1/posts/*/like", lambda route: route.abort())
    page.locator("article.post .like").click()
    page.locator(".toast.on").get_by_text("didn't go through").wait_for()
    # The signal is back: the feed is asked for again, and the note goes.
    page.unroute("**/api/v1/feed*")
    page.evaluate("dispatchEvent(new Event('online'))")
    note.wait_for(state="detached")
    assert page.locator("article.post").count() == 1


def test_a_feed_that_cannot_be_loaded_offers_to_try_again(app, open_member_app, shot):
    page = open_member_app(COLLABORATOR, wait=None)
    page.route("**/api/v1/feed*", lambda route: route.abort())
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    # A phone that has never seen the feed has no memory of it.
    page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('bgucats.feed')).forEach(k => localStorage.removeItem(k))")
    page.reload()
    empty = page.locator(".feed .empty-state")
    empty.get_by_role("alert").wait_for()
    assert "could not be loaded" in empty.inner_text()
    shot(page, "member-feed-failed")
    page.unroute("**/api/v1/feed*")
    empty.get_by_role("button", name="Try again").click()
    page.wait_for_selector("article.post")
    assert page.locator(".feed .empty-state").count() == 0


def test_a_search_with_no_match_says_so(open_member_app, shot):
    page = frame(open_member_app)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Search cats").click()
    page.get_by_role("searchbox").fill("zzz")
    empty = page.locator("[data-page=gallery] .empty-state")
    empty.wait_for()
    assert "zzz" in empty.inner_text()
    assert empty.get_by_role("button").count() == 0
    page.wait_for_timeout(500)
    shot(page, "member-gallery-no-match")


def test_a_post_on_its_way_says_how_far_and_why_it_waits(app, open_member_app, shot):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick").get_by_role("button", name="Shunra", exact=True).click()
    page.get_by_role("button", name="Create a post").click()
    page.fill("textarea", "Held up at the gate.")
    page.context.set_offline(True)
    page.get_by_role("button", name="Post", exact=True).click()
    card = page.locator("article.post.sending")
    card.wait_for()
    assert card.get_by_role("progressbar", name="Sending the photos").count() == 1
    page.wait_for_function(
        "document.querySelector('.sending-why')?.innerText.startsWith('No signal')"
    )
    page.wait_for_timeout(500)
    shot(page, "member-post-sending")
    page.context.set_offline(False)
    page.evaluate("dispatchEvent(new Event('online'))")
    eventually(
        page,
        lambda: next((c for c in my_posts(app) if c["text"] == "Held up at the gate."), None),
        timeout=40,
    )


def test_a_post_that_was_not_published_says_so_and_goes_in_one_tap(app, open_member_app, open_app, shot):
    post = the_post(app)
    status, body = app.api("POST", f"/api/posts/{post['postId']}/hide", {"reason": "a test"}, email=ADMIN)
    assert status == 200, body
    assert the_post(app)["state"] == "hidden"

    page = home(open_member_app)
    tile = page.locator(".my-posts .post-tile[data-state=hidden]")
    tile.wait_for()
    assert tile.locator(".badge").inner_text() == "Not published"
    shot(page, "member-post-not-published")
    tile.click()
    dialog = page.get_by_role("alertdialog")
    assert "This wasn't published" in dialog.inner_text()
    # No reason is given: only that it is theirs alone, and how to remove it.
    assert "Only you can see this post" in dialog.inner_text()
    dialog.get_by_role("button", name="Remove post").click()
    page.locator(".toast.on").get_by_text("Post deleted").wait_for()
    tile.wait_for(state="detached")
    assert not app.api("GET", "/api/v1/me/posts", email=COLLABORATOR)[1]["cards"]
