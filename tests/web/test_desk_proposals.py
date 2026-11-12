"""The desk's new-cat proposals (B6): at the top of the Queue, with the
person's photos and words, and the three answers. Nothing about a proposed
cat is public until one is given (D7)."""

from ulid import ULID

from .localapp import ADMIN, COLLABORATOR

PHOTOS_LOADED = "[...document.querySelectorAll('#main img')].every(i => i.complete)"


def propose(app, **fields):
    """The collaborator says the first queue encounter is a cat that isn't
    there, and posts it, as the capture flow will (E3)."""
    session = app.data["queue"][0]
    proposal_id = str(ULID())
    status, _ = app.api(
        "POST",
        "/api/v1/proposals",
        {
            "proposalId": proposal_id,
            "sessionId": session,
            "nameIdea": "Hummus",
            "coat": "ginger",
            "regionId": "library",
            "traits": ["kitten"],
            **fields,
        },
        email=COLLABORATOR,
    )
    assert status == 200
    _, detail = app.api("GET", f"/api/sessions/{session}")
    status, _ = app.api(
        "POST",
        "/api/v1/posts",
        {
            "postId": str(ULID()),
            "sessionId": session,
            "photoIds": [detail["photos"][0]["photoId"]],
            "claim": {"proposalId": proposal_id},
        },
        email=COLLABORATOR,
    )
    assert status == 200
    return proposal_id


def feed_cats(app):
    _, feed = app.api("GET", "/api/v1/feed", email=ADMIN)
    return [c["cat"] and c["cat"]["name"] for c in feed["cards"]]


def test_a_proposal_waits_at_the_top_of_the_queue_and_is_approved(app, open_app, shot):
    propose(app)
    assert feed_cats(app) == ["Mitzi"]  # the seed's post; the new one waits
    page = open_app(ADMIN)
    card = page.locator("article.proposal")
    card.wait_for()
    assert "New cat from @collaborator" in card.inner_text()
    assert "“Hummus” · Ginger · near" in card.inner_text()
    page.wait_for_function(PHOTOS_LOADED)
    shot(page, "queue-proposal")

    card.get_by_role("button", name="Add as a new cat").click()
    assert page.input_value("#ask input[name=name]") == "Hummus"
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('Hummus added')")
    page.locator("article.proposal").wait_for(state="detached")

    _, cats = app.api("GET", "/api/cats")
    assert "Hummus" in {c["name"] for c in cats["cats"]}
    assert feed_cats(app) == ["Hummus", "Mitzi"]


def test_a_proposal_merged_into_a_known_cat(app, open_app):
    propose(app)
    page = open_app(ADMIN)
    card = page.locator("article.proposal")
    card.get_by_role("button", name="It's a cat we know…").click()
    page.select_option("#ask select[name=catId]", label="Shunra")
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('Merged')")
    assert feed_cats(app) == ["Shunra", "Mitzi"]


def test_a_proposal_turned_down(app, open_app):
    propose(app)
    page = open_app(ADMIN)
    page.locator("article.proposal").get_by_role("button", name="Not a new cat").click()
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('turned down')")
    page.locator("article.proposal").wait_for(state="detached")
    assert feed_cats(app) == ["Mitzi"]
    # The encounter is still in the queue, to label there.
    assert page.get_by_role("button", name="Who is this?").count() == 2


def test_a_user_never_sees_the_proposals(app, open_app):
    propose(app)
    page = open_app(COLLABORATOR)
    page.wait_for_timeout(500)
    assert page.locator("article.proposal").count() == 0


def test_with_nothing_proposed_the_queue_starts_with_its_title(open_app):
    page = open_app(ADMIN)
    page.wait_for_selector("#main h2")
    assert page.locator("#main").inner_text().startswith("Labeling queue")
