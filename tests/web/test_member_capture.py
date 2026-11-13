"""The capture flow (E3): the camera, "Which cat?", "You met", the new-cat
form and the post, each ending writing what 01-product.md's table says,
through the outbox, so a reload or a dead signal loses nothing."""

import json
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
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()
    # The cat as the app knows it, your photo over its corner, and its name
    # poll: a vote from here counts like one from the cat's page.
    assert page.locator(".met-yours img").get_attribute("alt") == "Your photo"
    poll = page.locator(".scan .poll")
    poll.get_by_role("radio", name="Mitzi").click()
    poll.locator(".poll-option[aria-checked=true]").wait_for()
    cat = app.data["cats"]["Mitzi"]
    eventually(
        page,
        lambda: app.api("GET", f"/api/v1/cats/{cat}/names", email=COLLABORATOR)[1][
            "myVote"
        ],
    )
    page.wait_for_timeout(600)  # the page's slide
    shot(page, "member-scan-met")
    # Back is "not this cat": the grid again, and another choice.
    page.locator(".scan-top").get_by_role("button", name="Back").click()
    page.get_by_role("heading", name="Which cat?").wait_for()
    assert page.locator(".scan-top").get_by_role("button", name="Close").count() == 1
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()
    before = len(my_posts(app))
    page.get_by_role("button", name="Just save").click()
    page.wait_for_selector(".toast.on")
    assert "Mitzi saved" in page.get_by_role("status").inner_text()

    session = eventually(page, lambda: (s := newest_session(app)) and s["photos"] and s)
    pick = eventually(page, lambda: pick_of(app, session["session"]["sessionId"]))
    assert (pick["choice"], pick["catId"]) == ("cat", app.data["cats"]["Mitzi"])
    assert len(my_posts(app)) == before  # no post


def with_a_model(page, ranked):
    """The recognition model is not served here (localapp.py). This stands
    in for its module, at the one place scan.js meets it: the model is
    ready, and it ranks every photo the same way."""
    stub = (
        "export function createRecognition() { return {"
        " state: { version: 'test-model' },"
        " prepareForCapture: async () => true,"
        f" guessShots: async () => ({{ ranked: {json.dumps(ranked)} }}),"
        " encountersOf: () => 0 }; }"
    )
    page.route(
        "**/recognition.js",
        lambda route: route.fulfill(content_type="text/javascript", body=stub),
    )
    page.reload()
    page.wait_for_selector("[data-screen=frame]")


def test_the_models_closest_cats_are_offered_first(app, open_member_app, shot):
    cats = dict(app.data["cats"])
    for name in ("Ziggy", "Luna", "Kfir", "Tutit", "Shemesh"):
        status, body = app.api("POST", "/api/cats", {"name": name}, email=ADMIN)
        assert status == 200, body
        cats[name] = body["catId"]
    order = ["Shunra", "Mitzi", "Pilpel", "Luna"]
    page = frame(open_member_app)
    with_a_model(
        page, [{"catId": cats[n], "score": 0.9 - i / 10} for i, n in enumerate(order)]
    )
    scan_one(page)

    # The three closest, large, in the model's order; a cat with no photo
    # yet is known by its name.
    big = page.locator(".candidates .cat-tile")
    page.wait_for_function(
        "document.querySelectorAll('.candidates .cat-tile').length === 3"
    )
    assert [b.get_attribute("aria-label") for b in big.all()] == order[:3]
    assert big.nth(2).inner_text() == "Pilpel"
    page.get_by_role("heading", name="Not one of these?").wait_for()
    # Below: a new cat first, then the model's next guess, then the rest.
    rest = page.locator(".cat-grid-pick .cat-tile")
    assert [b.get_attribute("aria-label") or b.inner_text() for b in rest.all()][:2] == [
        "New cat",
        "Luna",
    ]
    assert rest.count() == 1 + len(cats) - 3
    # The prototype's layout: two matches side by side and one centred
    # under them, then four to a row.
    page.wait_for_timeout(600)  # the page's slide
    boxes = [b.bounding_box() for b in big.all()]
    assert boxes[0]["y"] == boxes[1]["y"] < boxes[2]["y"]
    centre = page.viewport_size["width"] / 2
    assert abs(boxes[2]["x"] + boxes[2]["width"] / 2 - centre) < 1
    row = [b.bounding_box()["y"] for b in rest.all()]
    assert row[0] == row[3] < row[4]
    # The photo just taken, at the top between Close and Retake.
    assert page.locator(".scan-top .scan-shot img").get_attribute("alt") == "Your photo"
    shot(page, "member-scan-which-matches")

    page.get_by_role("button", name="Retake photo").click()
    shoot(page)
    page.wait_for_selector(".scan[data-step=which]")
    page.locator(".candidates").get_by_role("button", name="Shunra").click()
    page.get_by_role("heading", name="You met Shunra").wait_for()
    assert page.locator(".scan-top .scan-shot").count() == 0
    page.get_by_role("button", name="Just save").click()
    session = eventually(page, lambda: (s := newest_session(app)) and s["photos"] and s)
    pick = eventually(page, lambda: pick_of(app, session["session"]["sessionId"]))
    assert (pick["choice"], pick["catId"]) == ("cat", cats["Shunra"])
    assert pick["shown"] == [cats[n] for n in order[:3]]
    assert pick["modelVersion"] == "test-model"


def test_create_a_post_shows_it_at_once_and_sends_it(app, open_member_app, shot):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick").get_by_role("button", name="Shunra", exact=True).click()
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
    page.locator(".scan .scroller").evaluate("e => e.scrollTo(0, 0)")
    shot(page, "member-scan-new")
    # The coats carry their colour; a chosen chip is marked.
    ginger = page.get_by_role("button", name="Ginger")
    assert ginger.get_attribute("aria-pressed") == "true"
    assert ginger.locator(".chip-swatch").count() == 1
    assert "1 of 4" in page.locator(".shot.add").inner_text()
    # Back to the grid and in again: the form is as it was left.
    page.locator(".scan-top").get_by_role("button", name="Back").click()
    page.get_by_role("heading", name="Which cat?").wait_for()
    page.get_by_role("button", name="New cat").click()
    assert page.input_value("input[maxlength='24']") == "Hummus"
    page.get_by_role("button", name="Add & post").click()
    page.get_by_role("heading", name="New post").wait_for()
    page.locator(".scan-top").get_by_role("button", name="Back").click()
    page.get_by_role("heading", name="New cat").wait_for()
    page.get_by_role("button", name="Add & post").click()
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


def test_tagging_a_post_comes_back_to_the_post(app, open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="New post").click()
    page.get_by_role("button", name="Take a photo").click()
    shoot(page)
    page.fill("textarea", "Tagged on the way.")
    top = page.locator(".scan-top")
    # The flow's first page here is the post: its button closes.
    assert top.get_by_role("button", name="Close").count() == 1
    page.get_by_role("button", name="Tag a cat").click()
    page.get_by_role("heading", name="Which cat?").wait_for()
    top.get_by_role("button", name="Back").click()
    page.get_by_role("heading", name="New post").wait_for()
    assert "No cat tagged" in page.locator(".tag-row").inner_text()
    page.get_by_role("button", name="Tag a cat").click()
    page.locator(".cat-grid-pick").get_by_role("button", name="Shunra", exact=True).click()
    # Straight back to the post, with what was written.
    page.get_by_role("heading", name="New post").wait_for()
    assert "Shunra" in page.locator(".tag-row").inner_text()
    assert page.input_value("textarea") == "Tagged on the way."
    page.get_by_role("button", name="Post", exact=True).click()
    post = eventually(
        page,
        lambda: next(
            (c for c in my_posts(app) if c["text"] == "Tagged on the way."), None
        ),
    )
    assert post["cat"]["name"] == "Shunra"


def test_changing_the_cat_from_the_post_comes_back_to_it(open_member_app):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
    page.get_by_role("button", name="Create a post").click()
    page.get_by_role("heading", name="New post").wait_for()
    page.get_by_role("button", name="Change").click()
    page.locator(".cat-grid-pick").get_by_role("button", name="Shunra", exact=True).click()
    page.get_by_role("heading", name="New post").wait_for()
    assert "Shunra" in page.locator(".tag-row").inner_text()
    # And back from the post is the cat just chosen.
    page.locator(".scan-top").get_by_role("button", name="Back").click()
    page.get_by_role("heading", name="You met Shunra").wait_for()


def test_a_reload_lands_back_on_the_same_page(open_member_app):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.get_by_role("button", name="Scan a cat").click()
    page.get_by_role("heading", name="You met Mitzi").wait_for()


def test_with_no_signal_everything_arrives_later(app, open_member_app):
    page = frame(open_member_app)
    scan_one(page)
    page.locator(".cat-grid-pick").get_by_role("button", name="Pilpel", exact=True).click()
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
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
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
