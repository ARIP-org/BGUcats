"""Reporting (B8b): "Report" in a photo's menu and in a person's, the
sheet with its reasons, and the desk's Reported section at the top of the
Queue with the admin's answers. The seeded collaborator posted Mitzi."""

from .localapp import ADMIN, COLLABORATOR
from .test_screens import go


def desk_reports(app):
    return app.api("GET", "/api/reports")[1]["reports"]


def feed_posts(app, email):
    return [c["postId"] for c in app.api("GET", "/api/v1/feed", email=email)[1]["cards"]]


def test_a_post_is_reported_from_its_photos_menu(app, open_member_app, shot):
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.locator(".photo").first.click()
    menu = page.get_by_role("menu", name="Post options")
    assert menu.get_by_role("menuitem").all_inner_texts() == ["See Mitzi", "Show on map", "Report"]
    menu.get_by_role("menuitem", name="Report").click()

    sheet = page.get_by_role("dialog", name="Report collaborator's post")
    sheet.wait_for()
    send = sheet.get_by_role("button", name="Send report")
    assert send.is_disabled()  # a reason first
    assert [r.inner_text() for r in sheet.get_by_role("radio").all()] == [
        "Spam or advertising",
        "Offensive, hateful or sexual",
        "Harassment or bullying",
        "Shows a person or private details",
        "Not about a campus cat",
        "Something else",
    ]
    sheet.get_by_role("radio", name="Not about a campus cat").click()
    sheet.get_by_label("Anything to add? (optional)").fill("This is a dog.")
    page.wait_for_timeout(400)  # the sheet has settled
    shot(page, "member-report")
    send.click()
    page.locator(".toast.on").get_by_text("Thank you. Someone looks at every report within a day.").wait_for()
    sheet.wait_for(state="detached")

    (entry,) = desk_reports(app)
    assert entry["target"]["type"] == "post" and entry["people"] == 1
    assert [(r["reason"], r["note"]) for r in entry["reports"]] == [("not_cat", "This is a dog.")]


def test_your_own_post_has_no_report_and_the_sheet_can_be_left(app, open_member_app):
    mine = open_member_app(COLLABORATOR)
    mine.locator("article.post .photo").first.click()
    menu = mine.get_by_role("menu", name="Post options")
    assert "Report" not in menu.get_by_role("menuitem").all_inner_texts()
    mine.keyboard.press("Escape")

    page = open_member_app(ADMIN)
    page.locator("article.post .photo").first.click()
    page.get_by_role("menuitem", name="Report").click()
    sheet = page.get_by_role("dialog", name="Report collaborator's post")
    sheet.get_by_role("radio", name="Something else").click()
    sheet.get_by_role("button", name="Cancel").click()
    sheet.wait_for(state="detached")
    assert desk_reports(app) == []


def test_a_person_is_reported_from_their_page(app, open_member_app):
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.get_by_role("button", name="collaborator", exact=True).click()
    person = page.locator("[data-page=person]")
    person.locator(".person-name").wait_for()
    page.wait_for_timeout(600)
    person.get_by_role("button", name="Options for collaborator").click()
    menu = page.get_by_role("menu", name="Options for collaborator")
    assert menu.get_by_role("menuitem").all_inner_texts() == ["Block", "Report"]
    menu.get_by_role("menuitem", name="Report").click()
    sheet = page.get_by_role("dialog", name="Report collaborator")
    sheet.get_by_role("radio", name="Harassment or bullying").click()
    sheet.get_by_role("button", name="Send report").click()
    page.locator(".toast.on").get_by_text("Thank you.").wait_for()
    (entry,) = desk_reports(app)
    assert (entry["target"]["type"], entry["target"]["username"]) == ("user", "collaborator")


def report_post(app, reason="spam", note=None):
    from ulid import ULID

    post = feed_posts(app, ADMIN)[0]
    body = {"reportId": str(ULID()), "targetType": "post", "targetId": post, "reason": reason}
    if note:
        body["note"] = note
    assert app.api("POST", "/api/v1/reports", body, email=ADMIN)[0] == 200
    return post


def test_the_desk_shows_what_was_reported_and_hides_it(app, open_app, shot):
    post = report_post(app, note="Advertising a shop")
    page = open_app(ADMIN)
    card = page.locator("article.report")
    card.wait_for()
    text = card.inner_text()
    assert "Post by @collaborator of Mitzi" in text
    assert "1 person reported it" in text
    assert "spam · “Advertising a shop”" in text
    # The pictures have no "Delete photo" on them: that would take a photo
    # out of the dataset.
    assert card.locator(".thumb img").count() == 3
    assert card.locator(".thumb .kill").count() == 0
    assert [b.inner_text() for b in card.locator(".card-actions button").all()] == [
        "Leave it",
        "Hide post",
        "Remove post",
    ]
    page.wait_for_function("[...document.querySelectorAll('article.report img')].every(i => i.complete)")
    shot(page, "queue-report")

    card.get_by_role("button", name="Hide post").click()
    page.wait_for_selector(".toast:has-text('Post hidden')")
    card.wait_for(state="detached")
    assert desk_reports(app) == []
    assert feed_posts(app, ADMIN) == []
    # Its author still has it, and sees that it is hidden.
    mine = app.api("GET", "/api/v1/me/posts", email=COLLABORATOR)[1]["cards"]
    assert [(c["postId"], c["state"]) for c in mine] == [(post, "hidden")]


def test_leaving_a_report_closes_it_and_the_post_stays(app, open_app):
    post = report_post(app)
    page = open_app(ADMIN)
    card = page.locator("article.report")
    card.get_by_role("button", name="Leave it").click()
    page.wait_for_selector(".toast:has-text('Reports closed')")
    card.wait_for(state="detached")
    assert feed_posts(app, ADMIN) == [post]


def test_a_user_sees_no_reports_in_the_desk(app, open_app):
    report_post(app)
    page = open_app(COLLABORATOR)
    go(page, "cats", "3 cats known")
    assert page.locator("article.report").count() == 0
