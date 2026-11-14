"""Achievements (B7, E8): the card on Home and the sheet it opens. The
seeded collaborator met Mitzi and posted her: five points and "First Meow".
The seed's encounter is made now, whenever now is, so after ten at night in
Israel it also earns "Night Owl"; the numbers here are asked of the API."""

from .localapp import ADMIN, COLLABORATOR
from .test_member_home import home


def from_api(app, email=COLLABORATOR):
    body = app.api("GET", "/api/v1/achievements", email=email)[1]
    return body, [b["id"] for b in body["badges"] if b["earned"]]


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def open_sheet(page):
    page.locator(".achievements-card").click()
    sheet = page.get_by_role("dialog", name="Achievements")
    sheet.locator(".ach-number").wait_for()
    return sheet


def test_homes_card_says_the_points_and_the_badges(app, open_member_app, shot):
    body, earned = from_api(app)
    assert body["points"] == 5 and "first-meow" in earned
    page = home(open_member_app)
    card = page.locator(".achievements-card")
    card.locator(".achievements-sub").wait_for()
    assert card.locator(".achievements-title").inner_text() == "Achievements"
    assert card.locator(".achievements-sub").inner_text() == f"5 points · {plural(len(earned), 'badge')}"
    assert card.locator(".achievements-sub b").inner_text() == "5"
    assert card.locator(".achievements-newest .badge-disc").count() == len(earned)
    shot(page, "member-home-achievements")


def test_the_sheet_shows_the_level_the_badges_and_how_points_are_earned(app, open_member_app, shot):
    earned = from_api(app)[1]
    page = home(open_member_app)
    page.locator(".achievements-card .achievements-sub").wait_for()
    sheet = open_sheet(page)
    assert sheet.locator(".ach-number").inner_text() == "5"
    assert sheet.locator(".ach-number-label").inner_text() == "social points"
    assert sheet.locator(".ach-level-name").inner_text() == "Level 1 · New Arrival"
    assert sheet.locator(".ach-level-next").inner_text() == "45 to Level 2"
    assert sheet.get_by_role("progressbar").get_attribute("aria-valuenow") == "10"
    assert [t.inner_text().split("\n") for t in sheet.locator(".ach-tile").all()] == [
        ["1", "Cat met"],
        ["0", "Cats fed"],
        ["1", "Post"],
    ]
    assert sheet.locator(".ach-section-head span").inner_text() == f"{len(earned)} of 7"
    names = [b.inner_text() for b in sheet.locator(".ach-badge").all()]
    assert names == [
        "First Meow",
        "Snack Giver",
        "Night Owl",
        "Explorer",
        "Name Giver",
        "Dean’s List",
        "Cat Whisperer",
    ]
    got = [
        b.get_attribute("data-badge")
        for b in sheet.locator(".ach-badge[data-earned=true]").all()
    ]
    assert got == earned
    # The prototype's order: the largest reward first.
    rules = [r.inner_text().split("\n") for r in sheet.locator(".ach-rule").all()]
    assert [(r[0], r[-1]) for r in rules] == [
        ("Feed a cat", "+10"),
        ("Meet & post a cat", "+5"),
    ]
    page.wait_for_timeout(500)  # the sheet has settled
    shot(page, "member-achievements")

    # A badge says how it is earned.
    sheet.locator(".ach-badge[data-badge=cat-whisperer]").click()
    page.locator(".toast.on").get_by_text("Not yet. Meet the same cat on 10 different days.").wait_for()
    sheet.locator(".ach-badge[data-badge=first-meow]").click()
    page.locator(".toast.on").get_by_text("Earned. Save your first encounter with a cat.").wait_for()

    sheet.get_by_role("button", name="Close").click()
    sheet.wait_for(state="detached")
    # And it closes with Escape, like every sheet.
    open_sheet(page)
    page.keyboard.press("Escape")
    page.get_by_role("dialog", name="Achievements").wait_for(state="detached")


def test_someone_who_has_done_nothing_yet_starts_at_zero(app, open_member_app):
    page = home(open_member_app, ADMIN)
    card = page.locator(".achievements-card")
    card.locator(".achievements-sub").wait_for()
    assert card.locator(".achievements-sub").inner_text() == "0 points · 0 badges"
    assert card.locator(".badge-disc").count() == 0
    sheet = open_sheet(page)
    assert sheet.locator(".ach-number").inner_text() == "0"
    assert sheet.locator(".ach-level-next").inner_text() == "50 to Level 2"
    assert sheet.locator(".ach-section-head span").inner_text() == "0 of 7"
    assert sheet.locator(".ach-badge.locked").count() == 7
