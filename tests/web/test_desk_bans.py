"""Bans (B8c): "People in the app" on the desk's People screen, with Ban and
Unban; Ban on a reported person's card; and what a banned person then sees
in the member app. The seeded collaborator posted Mitzi."""

from ulid import ULID

from .localapp import ADMIN, COLLABORATOR
from .test_screens import go


def status_of(app, email):
    people = app.api("GET", "/api/people")[1]["people"]
    return next(p["status"] for p in people if p["email"] == email)


def feed_posts(app, email):
    return [c["postId"] for c in app.api("GET", "/api/v1/feed", email=email)[1]["cards"]]


def test_an_admin_bans_and_unbans_a_person(app, open_app, shot):
    assert len(feed_posts(app, ADMIN)) == 1
    page = open_app(ADMIN)
    go(page, "admins", "Only these Google accounts can sign in.")
    panel = page.locator(".app-people")
    panel.wait_for()
    assert "2 accounts" in panel.inner_text()
    row = panel.locator(".row.person", has_text="@collaborator")
    assert COLLABORATOR in row.inner_text()
    # An admin has no Ban button: neither oneself nor another admin.
    assert panel.locator(".row.person", has_text=ADMIN).get_by_role("button").count() == 0
    shot(page, "people-app")

    row.get_by_role("button", name="Ban").click()
    assert "Ban @collaborator?" in page.inner_text("#ask")
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('@collaborator is banned')")
    row = page.locator(".app-people .row.person", has_text="@collaborator")
    row.get_by_text("banned", exact=True).wait_for()
    assert status_of(app, COLLABORATOR) == "banned"
    assert feed_posts(app, ADMIN) == []  # their post is hidden from everyone

    row.get_by_role("button", name="Unban").click()
    page.wait_for_selector(".toast:has-text('@collaborator is unbanned')")
    page.locator(".app-people .row.person", has_text="@collaborator").get_by_role("button", name="Ban").wait_for()
    assert status_of(app, COLLABORATOR) == "active"
    assert len(feed_posts(app, ADMIN)) == 1


def test_a_reported_person_is_banned_from_the_queue(app, open_app):
    collaborator = app.api("GET", "/api/v1/me", email=COLLABORATOR)[1]["userId"]
    body = {"reportId": str(ULID()), "targetType": "user", "targetId": collaborator, "reason": "harassment"}
    assert app.api("POST", "/api/v1/reports", body, email=ADMIN)[0] == 200
    page = open_app(ADMIN)
    card = page.locator("article.report")
    card.wait_for()
    assert "Person @collaborator" in card.inner_text()
    assert [b.inner_text() for b in card.locator(".card-actions button").all()] == ["Leave it", "Ban"]
    card.get_by_role("button", name="Ban").click()
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('@collaborator is banned')")
    card.wait_for(state="detached")
    assert status_of(app, COLLABORATOR) == "banned"


def test_a_banned_person_is_told_so_in_the_app(app, open_member_app, shot):
    collaborator = app.api("GET", "/api/v1/me", email=COLLABORATOR)[1]["userId"]
    assert app.api("POST", f"/api/people/{collaborator}/ban")[0] == 200
    page = open_member_app(COLLABORATOR, wait="[data-screen=banned]")
    assert page.locator("h1").inner_text() == "This account is blocked"
    assert page.get_by_role("button", name="Sign out").is_visible()
    shot(page, "member-banned")
