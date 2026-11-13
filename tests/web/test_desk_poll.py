"""The desk's half of the name poll (B4b), on a cat's page: what the app
calls the cat and why, every suggested name, and an admin's two answers to
one that should not be there. Mitzi was named by the admins."""

from .localapp import ADMIN, COLLABORATOR
from .test_screens import go, shows

TERMS = {"version": "2026-11"}


def suggest(app, name, email):
    app.api("POST", "/api/v1/me/terms", TERMS, email=email)
    cat = app.data["cats"]["Mitzi"]
    status, body = app.api("POST", f"/api/v1/cats/{cat}/names", {"name": name}, email=email)
    assert status == 200, body
    return cat


def members_view(app, email=COLLABORATOR):
    cat = app.data["cats"]["Mitzi"]
    poll = app.api("GET", f"/api/v1/cats/{cat}/names", email=email)[1]
    return poll["name"], {o["name"]: o["votes"] for o in poll["options"]}


def mitzis_poll(open_app):
    page = open_app(ADMIN)
    go(page, "cats", "3 cats known")
    page.click(".cat-card:has-text('Mitzi')")
    panel = page.locator(".name-poll")
    panel.locator("h3", has_text="Name poll").wait_for()
    return page, panel


def test_a_cat_nobody_named_in_the_app_says_so(app, open_app):
    panel = mitzis_poll(open_app)[1]
    text = panel.inner_text()
    assert "The app shows “Mitzi”, the name given here." in text
    assert "Nobody has suggested a name yet." in text
    assert panel.locator(".poll-name").count() == 0


def test_an_admin_removes_a_name_and_its_votes_go_with_it(app, open_app, shot):
    suggest(app, "Stinky", COLLABORATOR)
    assert members_view(app) == ("Stinky", {"Stinky": 1, "Mitzi": 0})

    page, panel = mitzis_poll(open_app)
    assert "The app shows “Stinky”: it leads the poll." in panel.inner_text()
    row = panel.locator(".poll-name[data-name=stinky]")
    assert "by @collaborator" in row.inner_text()
    assert "leading" in row.inner_text() and "1 vote" in row.inner_text()
    shot(page, "cat-name-poll")

    row.get_by_role("button", name="Remove").click()
    assert "Its 1 vote goes with it" in page.inner_text("#ask")
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('“Stinky” removed')")
    text = panel.inner_text()
    assert "The app shows “Mitzi”, the name given here." in text
    assert "Removed: Stinky" in text
    assert panel.locator(".poll-name").count() == 0

    # For the members too: the name is gone, and so is the vote.
    assert members_view(app) == ("Mitzi", {"Mitzi": 0})


def test_an_admin_locks_the_name_and_gives_it_back(app, open_app, shot):
    suggest(app, "Stinky", COLLABORATOR)
    page, panel = mitzis_poll(open_app)
    panel.get_by_role("button", name="Lock the name").click()
    # The name the app shows now is offered; the admin types the right one.
    assert page.input_value("#ask input[name=name]") == "Stinky"
    page.fill("#ask input[name=name]", "Mitzi")
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('The app now shows “Mitzi”')")
    assert f"The app shows “Mitzi”: locked by {ADMIN}." in panel.inner_text()
    # The poll is still there, with its votes, and changes nothing.
    assert "1 vote" in panel.locator(".poll-name[data-name=stinky]").inner_text()
    assert members_view(app) == ("Mitzi", {"Stinky": 1, "Mitzi": 0})
    shot(page, "cat-name-locked")

    panel.get_by_role("button", name="Unlock").click()
    page.wait_for_selector(".toast:has-text('The poll names the cat again')")
    assert "The app shows “Stinky”: it leads the poll." in panel.inner_text()
    assert members_view(app)[0] == "Stinky"


def test_a_user_sees_no_poll_on_the_cats_page(app, open_app):
    page = open_app(COLLABORATOR)
    go(page, "cats", "3 cats known")
    page.click(".cat-card:has-text('Mitzi')")
    shows(page, "All cats")
    page.wait_for_timeout(300)
    assert page.locator(".name-poll h3").count() == 0
