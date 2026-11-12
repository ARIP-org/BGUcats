"""The capture flow (E3): the camera, "Which cat?", "You met", the new-cat
form and the post, each ending writing what 01-product.md's table says,
through the outbox, so a reload or a dead signal loses nothing."""

import time

from app import handler as app_handler

from .localapp import ADMIN, COLLABORATOR, sample_photo

PHOTO = {"name": "cat.jpg", "mimeType": "image/jpeg", "buffer": sample_photo(77)}


def eventually(page, check, timeout=20):
    """Until `check` holds. It waits through the page, never time.sleep: the
    test's request filter (conftest.py) runs only while Playwright is
    called, so a sleeping test holds every request of the page."""
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"not within the time: {check()!r}")
        page.wait_for_timeout(250)


def frame(open_member_app, email=COLLABORATOR, **options):
    page = open_member_app(email, **options)
    page.wait_for_selector("[data-screen=frame]")
    return page


def shoot(page):
    """A headless browser has no camera: the phone's own, a file input."""
    page.wait_for_selector(".scan[data-step=camera]")
    page.set_input_files(".file-shot input", PHOTO)


def scan_one(page):
    page.get_by_role("button", name="Scan a cat").click()
    shoot(page)
    page.wait_for_selector(".scan[data-step=which]")


def newest_session(app):
    _, queue = app.api("GET", "/api/queue")
    mine = [
        s for s in queue["sessions"] if s["session"].get("startedBy") == COLLABORATOR
    ]
    return max(mine, key=lambda s: s["session"]["startedAt"]) if mine else None


def pick_of(app, session_id):
    return app.table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "PICK"}).get(
        "Item"
    )


def my_posts(app):
    status, body = app.api("GET", "/api/v1/me/posts", email=COLLABORATOR)
    assert status == 200, body
    return body["cards"]


def test_save_without_posting_records_the_encounter_and_the_pick(
    app, open_member_app, shot
):
    page = frame(open_member_app)
    scan_one(page)
    # No model in the local app: "Which cat?" is the grid of every cat.
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-scan-which")
    page.locator(".cat-grid-pick .cat-tile", has_text="Mitzi").click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-scan-met")
    before = len(my_posts(app))
    page.get_by_role("button", name="Save without posting").click()
    page.wait_for_selector(".toast.on")
    assert "Mitzi saved" in page.get_by_role("status").inner_text()

    session = eventually(page, lambda: (s := newest_session(app)) and s["photos"] and s)
    pick = eventually(page, lambda: pick_of(app, session["session"]["sessionId"]))
    assert (pick["choice"], pick["catId"]) == ("cat", app.data["cats"]["Mitzi"])
    assert len(my_posts(app)) == before  # no post


def test_create_a_post_shows_it_at_once_and_sends_it(app, open_member_app, shot):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick .cat-tile", has_text="Shunra").click()
    page.get_by_role("button", name="Create a post").click()
    page.get_by_role("heading", name="New post").wait_for()
    page.fill("textarea", "Guarding the vending machine.")
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-scan-post")
    page.get_by_role("button", name="Post", exact=True).click()
    # In the feed at once, from the phone's memory.
    page.locator("article.post.sending").wait_for()
    assert "Shunra" in page.locator("article.post.sending").inner_text()

    post = eventually(
        page,
        lambda: next(
            (c for c in my_posts(app) if c["text"] == "Guarding the vending machine."),
            None,
        ),
    )
    assert post["cat"]["name"] == "Shunra"
    assert post["state"] == "visible"


def test_a_new_cat_goes_to_the_admins_and_its_post_waits(app, open_member_app, shot):
    page = frame(open_member_app)
    scan_one(page)
    page.get_by_role("button", name="New cat").click()
    page.get_by_role("heading", name="New cat").wait_for()
    page.fill("input[maxlength='24']", "Hummus")
    page.get_by_role("button", name="Ginger").click()
    page.get_by_role("button", name="Kitten").click()
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-scan-new")
    page.get_by_role("button", name="Add cat & create a post").click()
    page.get_by_role("button", name="Post", exact=True).click()
    page.wait_for_selector(".toast.on")
    assert "An admin will look" in page.get_by_role("status").inner_text()
    assert "Waiting for an admin" in page.locator("article.post.sending").inner_text()

    proposals = eventually(
        page, lambda: app.api("GET", "/api/proposals")[1]["proposals"]
    )
    assert (proposals[0]["nameIdea"], proposals[0]["coat"], proposals[0]["traits"]) == (
        "Hummus",
        "ginger",
        ["kitten"],
    )
    post = eventually(
        page, lambda: next((c for c in my_posts(app) if c.get("proposal")), None)
    )
    assert post["state"] == "pending"
    # Nobody else sees it.
    _, feed = app.api("GET", "/api/v1/feed", email=ADMIN)
    assert post["postId"] not in [c["postId"] for c in feed["cards"]]


def test_posting_from_plus_with_no_cat(app, open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()
    assert page.get_by_role("button", name="Post", exact=True).is_disabled()
    page.get_by_role("button", name="Take a photo").click()
    shoot(page)
    page.get_by_role("heading", name="New post").wait_for()
    assert "No cat tagged" in page.locator(".tag-row").inner_text()
    page.get_by_role("button", name="Post", exact=True).click()
    post = eventually(
        page, lambda: next((c for c in my_posts(app) if c["cat"] is None), None)
    )
    assert post["state"] == "visible"


def test_a_reload_lands_back_on_the_same_page(open_member_app):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick .cat-tile", has_text="Mitzi").click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.get_by_role("button", name="Scan a cat").click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()


def test_with_no_signal_everything_arrives_later(app, open_member_app):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick .cat-tile", has_text="Pilpel").click()
    page.get_by_role("button", name="Create a post").click()
    page.fill("textarea", "Posted from under the bridge.")
    page.context.set_offline(True)
    page.get_by_role("button", name="Post", exact=True).click()
    page.wait_for_timeout(1500)
    assert not [
        c for c in my_posts(app) if c["text"] == "Posted from under the bridge."
    ]
    page.context.set_offline(False)
    page.evaluate("dispatchEvent(new Event('online'))")
    post = eventually(
        page,
        lambda: next(
            (c for c in my_posts(app) if c["text"] == "Posted from under the bridge."),
            None,
        ),
        timeout=40,
    )
    assert post["cat"]["name"] == "Pilpel"


def test_new_terms_are_accepted_before_posting(app, open_member_app, monkeypatch):
    monkeypatch.setattr(app_handler, "TERMS_VERSION", "2026-12")
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick .cat-tile", has_text="Mitzi").click()
    page.get_by_role("button", name="Create a post").click()
    page.fill("textarea", "With the new terms.")
    page.get_by_role("button", name="Post", exact=True).click()
    dialog = page.get_by_role("alertdialog")
    assert "Before you post" in dialog.inner_text()
    dialog.get_by_role("button", name="Accept and go on").click()
    eventually(
        page,
        lambda: next(
            (c for c in my_posts(app) if c["text"] == "With the new terms."), None
        ),
    )
