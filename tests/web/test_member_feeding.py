"""Feeding (B7c): "I fed this cat" on a cat's page, the cat's "last fed",
what it earns, and the desk's remove."""

from .localapp import ADMIN, COLLABORATOR
from .test_member_poll import cat_page
from .test_screens import go


def last_fed(app, name="Mitzi"):
    cat = app.data["cats"][name]
    return app.api("GET", f"/api/v1/cats/{cat}", email=COLLABORATOR)[1]["cat"]["lastFedAt"]


def log_a_feeding(page, spot=None):
    page.locator(".fed-card").get_by_role("button", name="I fed this cat").click()
    sheet = page.get_by_role("dialog", name="You fed Mitzi?")
    if spot:
        sheet.get_by_role("button", name=spot).click()
    return sheet


def test_a_feeding_is_logged_from_the_cats_page(app, open_member_app, shot):
    page = cat_page(open_member_app)
    card = page.locator(".fed-card")
    assert card.locator(".fed-last").inner_text() == "No feeding logged yet"
    assert card.locator(".fed-by").count() == 0

    sheet = log_a_feeding(page)
    # The campus's spots are offered; naming one is optional.
    sheet.locator(".chip").first.wait_for()
    spots = [c.inner_text() for c in sheet.locator(".chip").all()]
    assert sorted(spots) == ["Dorms gate", "Library steps", "Student Union yard"]
    sheet.get_by_role("button", name="Library steps").click()
    assert sheet.locator(".chip[aria-pressed=true]").inner_text() == "Library steps"
    page.wait_for_timeout(400)  # the sheet has settled
    shot(page, "member-feeding-sheet")
    sheet.get_by_role("button", name="Log feeding").click()
    page.locator(".toast.on").get_by_text("feeding is logged").wait_for()
    sheet.wait_for(state="detached")
    page.wait_for_function(
        "document.querySelector('.fed-last').innerText === 'Last fed just now'"
    )
    assert card.locator(".fed-by").inner_text() == "Logged by people using the app"
    assert last_fed(app)
    shot(page, "member-cat-fed")

    # The same cat again, minutes later: said plainly, and not counted.
    log_a_feeding(page).get_by_role("button", name="Log feeding").click()
    page.locator(".toast.on").get_by_text("a short while ago").wait_for()

    # What it earned: ten points, a cat fed, and Snack Giver.
    body = app.api("GET", "/api/v1/achievements", email=COLLABORATOR)[1]
    assert (body["points"], body["counters"]["catsFed"]) == (15, 1)
    assert "snack-giver" in [b["id"] for b in body["badges"] if b["earned"]]


def test_the_sheet_closes_without_logging(app, open_member_app):
    page = cat_page(open_member_app)
    sheet = log_a_feeding(page)
    sheet.get_by_role("button", name="Cancel").click()
    sheet.wait_for(state="detached")
    log_a_feeding(page)
    page.keyboard.press("Escape")
    page.get_by_role("dialog", name="You fed Mitzi?").wait_for(state="detached")
    assert last_fed(app) is None


def test_an_admin_removes_a_feeding_in_the_desk(app, open_app, shot):
    cat = app.data["cats"]["Mitzi"]
    feeding = "01JF0000000000000000000001"
    status, body = app.api(
        "POST",
        f"/api/v1/cats/{cat}/feedings",
        {"feedingId": feeding, "spotId": "library-steps"},
        email=COLLABORATOR,
    )
    assert status == 200, body
    assert last_fed(app) == body["lastFedAt"]

    page = open_app(ADMIN)
    go(page, "cats", "3 cats known")
    page.click(".cat-card:has-text('Mitzi')")
    panel = page.locator(".cat-feedings")
    panel.locator("h3", has_text="Feedings").wait_for()
    row = panel.locator(f".feeding[data-feeding='{feeding}']")
    assert "by @collaborator · at library-steps" in row.inner_text()
    shot(page, "cat-feedings")
    row.get_by_role("button", name="Remove").click()
    assert "points it earned are taken back" in page.inner_text("#ask")
    page.click("#ask button[value=ok]")
    page.wait_for_selector(".toast:has-text('Feeding removed')")
    assert "removed" in row.inner_text()
    assert "The app shows no feeding for this cat." in panel.inner_text()
    assert last_fed(app) is None
    body = app.api("GET", "/api/v1/achievements", email=COLLABORATOR)[1]
    assert body["counters"]["catsFed"] == 0


def test_a_cat_nobody_fed_has_no_feedings_panel(app, open_app):
    page = open_app(ADMIN)
    go(page, "cats", "3 cats known")
    page.click(".cat-card:has-text('Mitzi')")
    page.locator(".name-poll h3", has_text="Name poll").wait_for()
    page.wait_for_timeout(300)
    assert page.locator(".cat-feedings h3").count() == 0
