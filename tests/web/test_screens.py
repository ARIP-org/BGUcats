"""The app's screens in a real browser, against the real API handler and
the real process handler (tests/web/localapp.py). No AWS.

These are smoke tests: each screen opens for the right person, shows the
data that is there, and the two things the app exists for work from a tap
to the table: a collaborator's photo arrives, and an admin's label sticks.
"""

from .localapp import ADMIN, COLLABORATOR, sample_photo

PHOTOS_LOADED = (
    "[...document.querySelectorAll('#main img')].length > 0 && "
    "[...document.querySelectorAll('#main img')].every(i => i.complete && i.naturalWidth > 0)"
)


def tabs(page):
    return [
        tab.get_attribute("data-view")
        for tab in page.query_selector_all(".tab")
        if tab.is_visible()
    ]


def shows(page, text):
    """Wait until the screen says this: a screen is drawn after its data
    arrives, so the tab is active before its content is."""
    page.wait_for_function(
        "text => document.querySelector('#main').innerText.includes(text)", arg=text
    )


def go(page, view, title):
    page.click(f".tab[data-view={view}]")
    shows(page, title)


# ---------------------------------------------------------------- front door


def test_a_browser_tab_gets_the_install_page(open_app, shot):
    page = open_app(ADMIN, installed=False)
    page.wait_for_selector("#install:not([hidden])")
    assert page.is_hidden("#app")
    assert page.is_hidden("#login")
    shot(page, "install-page")


def test_signed_out_shows_the_sign_in_button(open_app, shot):
    page = open_app(None)
    page.wait_for_selector("#login:not([hidden])")
    assert page.is_visible("#login-button")
    assert page.is_hidden("#app")
    shot(page, "sign-in")


def test_someone_not_on_the_list_is_sent_back_to_sign_in(open_app):
    page = open_app("stranger@example.com", member=False)
    page.wait_for_selector("#login:not([hidden])")
    assert "not an admin or collaborator" in page.inner_text("#login-alert")
    # The tokens are forgotten, or every launch would try them again.
    assert page.evaluate("localStorage.getItem('bgucats.tokens')") is None


# ------------------------------------------------------------------- admins


def test_an_admin_lands_on_the_queue_with_its_photos(open_app, shot):
    page = open_app(ADMIN)
    assert tabs(page) == ["capture", "queue", "cats", "stats", "admins"]
    shows(page, "2 sessions · 3 photos")
    page.wait_for_function(PHOTOS_LOADED)
    assert page.get_by_role("button", name="Who is this?").count() == 2
    shot(page, "queue")


def test_an_admin_labels_a_session_from_the_picker(app, open_app, shot):
    page = open_app(ADMIN)
    page.get_by_role("button", name="Who is this?").first.click()
    page.wait_for_selector("#picker .pick")
    shot(page, "picker")
    page.locator("#picker .pick", has_text="Mitzi").click()

    shows(page, "1 session ·")
    assert page.get_by_role("button", name="Who is this?").count() == 1
    # And in the table, not only on the screen: Mitzi had 3 photos, the
    # oldest session in the queue had 2.
    _, cats = app.api("GET", "/api/cats")
    assert {c["name"]: c["photoCount"] for c in cats["cats"]}["Mitzi"] == 5


def test_the_cats_screen_lists_every_cat_with_its_cover(open_app, shot):
    page = open_app(ADMIN)
    go(page, "cats", "3 cats known")
    page.wait_for_function(PHOTOS_LOADED)
    text = page.inner_text("#main")
    for name in ("Mitzi", "Shunra", "Pilpel"):
        assert name in text
    shot(page, "cats")


def test_a_screen_that_loads_late_does_not_draw_over_the_one_opened_since(open_app):
    """The Queue waits for its data; tapping Cats meanwhile showed Cats, and
    then the Queue's late answer drew over it (one CI run in six, 2026-11-11).
    Here the Queue's answer is held until Cats is on screen."""
    page = open_app(ADMIN)
    held = []
    page.route(
        lambda url: url.split("?")[0].endswith("/api/queue"),
        lambda route: held.append(route),
    )
    # An action forgets every cached answer, so the Queue asks again.
    go(page, "stats", "Photos & videos")
    page.get_by_role("button", name="Refresh").click()
    shows(page, "Photos & videos")
    page.click(".tab[data-view=queue]")
    for _ in range(100):  # until the Queue's request is waiting on us
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "the Queue did not ask for its data"
    go(page, "cats", "3 cats known")

    with page.expect_response(lambda res: res.url.split("?")[0].endswith("/api/queue")):
        for route in held:
            route.continue_()
    page.wait_for_timeout(500)  # time for a late draw, if there were one
    text = page.inner_text("#main")
    assert "3 cats known" in text
    assert "Labeling queue" not in text


def test_the_stats_screen_counts_what_is_there(open_app, shot):
    page = open_app(ADMIN)
    go(page, "stats", "Photos & videos")
    shows(page, "3 photos waiting in the queue")
    shot(page, "stats")


def test_the_people_screen_lists_both_members(open_app, shot):
    page = open_app(ADMIN)
    go(page, "admins", COLLABORATOR)
    assert ADMIN in page.inner_text("#main")
    shot(page, "people")


# ------------------------------------------------------------ collaborators


def test_a_collaborator_sees_capture_and_cats_only(open_app, shot):
    page = open_app(COLLABORATOR)
    assert tabs(page) == ["capture", "cats"]
    page.get_by_role("button", name="Start an encounter").wait_for()
    shot(page, "capture")


def test_a_photo_taken_in_capture_reaches_the_queue(app, open_app, shot):
    """The path the app exists for, and the one that failed silently in
    October: record, upload to storage, confirm, process."""
    page = open_app(COLLABORATOR)
    page.get_by_role("button", name="Start an encounter").click()
    # A headless browser has no camera, so Capture offers the phone's own:
    # a file input, which is also what many real phones end up using.
    photo = {"name": "cat.jpg", "mimeType": "image/jpeg", "buffer": sample_photo(99)}
    with page.expect_response(lambda res: res.url.endswith("/complete")) as confirmed:
        page.set_input_files(".system-camera input[accept='image/*']", photo)
    assert confirmed.value.status == 200
    camera = page.get_by_role("dialog", name="Camera")
    camera.get_by_text("Everything is uploaded.").wait_for()
    shot(page, "capture-encounter")
    camera.get_by_role("button", name="Done").click()
    page.get_by_text("Who did you meet?").wait_for()
    shot(page, "capture-result")

    _, queue = app.api("GET", "/api/queue")
    assert len(queue["sessions"]) == 3
    newest = max(queue["sessions"], key=lambda s: s["session"]["startedAt"])
    assert newest["session"]["startedBy"] == COLLABORATOR
    assert [p["status"] for p in newest["photos"]] == ["unlabeled"]
    # The process handler ran: the photo has its hash and its size.
    assert newest["photos"][0]["sha256"] and newest["photos"][0]["width"] == 1200
