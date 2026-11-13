"""The name poll on a cat's page (B4, E4): vote, change your mind, take the
vote back, suggest a name. Mitzi was named by the admins, so that name
stands in her poll from the start."""

import json

from .localapp import ADMIN, COLLABORATOR


def cat_page(open_member_app, email=COLLABORATOR, name="Mitzi"):
    page = open_member_app(email)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Open the cat gallery").click()
    page.get_by_role("button", name=f"Open {name}").click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    page.wait_for_selector("[data-page=cat] .poll")
    return page


def option(page, name):
    return page.locator(".poll-option", has=page.locator(".poll-name", has_text=name))


def test_the_admins_name_can_be_voted_for_and_the_vote_taken_back(open_member_app, shot):
    page = cat_page(open_member_app)
    cat = page.locator("[data-page=cat]")
    poll = cat.get_by_role("region", name="Name poll")
    assert poll.locator(".card-count").inner_text() == "0 votes"
    mitzi = option(page, "Mitzi")
    assert mitzi.get_attribute("aria-checked") == "false"
    assert mitzi.locator(".poll-count").inner_text() == "0"
    assert cat.locator(".cat-named").inner_text() == "Named by the people who look after the cats"

    with page.expect_response(lambda r: r.url.endswith("/vote") and r.request.method == "PUT") as sent:
        mitzi.click()
    assert sent.value.status == 200
    page.wait_for_function("document.querySelector('.poll .card-count').innerText === '1 vote'")
    assert mitzi.get_attribute("aria-checked") == "true"
    assert mitzi.locator(".poll-count").inner_text() == "1"
    assert mitzi.get_by_text("LEADING").count() == 1
    # The page that just voted already says so, before any list catches up.
    assert cat.locator(".cat-named").inner_text() == "Named by vote · 1 of 1"
    shot(page, "member-cat-poll")

    # A tap on your own choice takes the vote back.
    with page.expect_response(lambda r: r.url.endswith("/vote") and r.request.method == "DELETE"):
        mitzi.click()
    page.wait_for_function("document.querySelector('.poll .card-count').innerText === '0 votes'")
    assert mitzi.get_attribute("aria-checked") == "false"
    assert cat.locator(".cat-named").inner_text() == "Named by the people who look after the cats"


def test_a_suggested_name_joins_the_poll_and_another_member_votes_for_it(open_member_app, app, shot):
    page = cat_page(open_member_app)
    field = page.get_by_label("Suggest a name")
    field.fill("  mango ")
    with page.expect_response(lambda r: r.url.endswith("/names") and r.request.method == "POST") as sent:
        field.press("Enter")
    assert sent.value.status == 200
    page.locator(".toast.on").get_by_text("Your name is in").wait_for()
    assert field.input_value() == ""
    mango = option(page, "mango")
    # Its author's at once, with their vote, and marked while it is checked.
    assert mango.get_attribute("aria-checked") == "true"
    assert mango.get_by_text("Being checked").count() == 1
    shot(page, "member-cat-poll-suggested")

    # Checked (here at once), it is everyone's, and with the only vote it
    # leads: the gallery already lists the cat under it. Another member
    # votes for it.
    other = cat_page(open_member_app, ADMIN, name="mango")
    theirs = option(other, "mango")
    assert theirs.locator(".poll-count").inner_text() == "1"
    assert theirs.get_by_text("Being checked").count() == 0
    theirs.click()
    other.wait_for_function("document.querySelector('.poll .card-count').innerText === '2 votes'")
    assert other.locator("[data-page=cat] h1").inner_text() == "mango"
    assert other.locator("[data-page=cat] .cat-named").inner_text() == "Named by vote · 2 of 2"
    # And the campus's lists follow: the gallery names the cat by its poll.
    _, cats = app.api("GET", "/api/v1/cats", email=ADMIN)
    assert "mango" in [c["name"] for c in cats["cats"]]


def test_changing_your_mind_moves_one_vote(open_member_app, app):
    _, me = app.api("GET", "/api/v1/me", email=ADMIN)
    app.api("POST", "/api/v1/me/terms", {"version": me["terms"]["current"]}, email=ADMIN)
    _, mitzi = app.api("GET", "/api/v1/cats", email=ADMIN)
    cat_id = next(c["catId"] for c in mitzi["cats"] if c["name"] == "Mitzi")
    assert app.api("POST", f"/api/v1/cats/{cat_id}/names", {"name": "Mango"}, email=ADMIN)[0] == 200

    page = cat_page(open_member_app, name="Mango")  # the one vote leads
    option(page, "Mango").click()
    page.wait_for_function("document.querySelector('.poll .card-count').innerText === '2 votes'")
    option(page, "Mitzi").click()
    page.wait_for_function(
        "document.querySelector('.poll-option[data-name=mitzi]').getAttribute('aria-checked') === 'true'"
    )
    page.wait_for_function(
        "[...document.querySelectorAll('.poll-option')].map(o => o.dataset.name + ':' + o.querySelector('.poll-count').innerText).sort().join() === 'mango:1,mitzi:1'"
    )
    assert page.locator(".poll .card-count").inner_text() == "2 votes"


def test_a_refused_vote_puts_the_poll_back_and_says_why(open_member_app):
    page = cat_page(open_member_app)
    page.route(
        "**/api/v1/cats/*/vote",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": "this name was not accepted", "code": "not_accepted"}),
        ),
    )
    mitzi = option(page, "Mitzi")
    mitzi.click()
    page.locator(".toast.on").get_by_text("That name was not accepted.").wait_for()
    assert mitzi.get_attribute("aria-checked") == "false"
    assert page.locator(".poll .card-count").inner_text() == "0 votes"
