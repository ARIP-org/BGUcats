"""Home and the profile (E6): who you are on a glass pill, the Friends card
with the cat sitting on it, your own posts, and the profile the pill opens.
The seeded campus has one post, the collaborator's, of Mitzi."""

from .localapp import ADMIN, COLLABORATOR


def home(open_member_app, email=COLLABORATOR, **options):
    page = open_member_app(email, **options)
    page.wait_for_selector("[data-screen=frame]")
    page.get_by_role("button", name="Home").click()
    page.wait_for_selector(".home-top .me-pill")
    return page


def loaded(page, selector):
    page.wait_for_selector(f"{selector} img")
    page.wait_for_function(
        f"[...document.querySelectorAll('{selector} img')].every(i => i.complete && i.naturalWidth)"
    )


def scroll_down(page, tab):
    """Room to scroll, as padding on the scroller (which a redraw leaves
    alone), then a few steps down, as a finger makes them."""
    scroller = f"document.querySelector('[data-tab-page={tab}] .scroller')"
    page.evaluate(f"{scroller}.style.paddingBlockEnd = '3000px'")
    for y in (100, 200, 300, 400):
        page.evaluate(f"{scroller}.scrollTo(0, {y})")
        page.wait_for_timeout(50)


def test_home_says_who_you_are_and_how_many_cats_you_met(open_member_app, shot):
    page = home(open_member_app)
    pill = page.locator(".me-pill")
    assert pill.locator(".me-name").inner_text() == "collaborator"
    # One labeled encounter with Mitzi, picked in the seed; the month and
    # year are the day the account was made.
    assert pill.locator(".me-met").inner_text() == "1 cat met"
    assert " · since " in pill.locator(".me-sub").inner_text()
    you = page.locator(".friends-card .friend-row")
    assert you.locator(".friend-name").inner_text() == "You"
    assert you.locator(".friend-found").inner_text() == "found 1 cat"
    assert you.locator(".friend-found b").inner_text() == "1"
    # The cat sits on the card, for the eye only.
    assert page.locator(".friends-card svg.mascot[aria-hidden=true]").count() == 1
    loaded(page, ".my-posts")
    shot(page, "member-home")


def test_your_posts_are_on_home_and_open_the_cat(open_member_app):
    page = home(open_member_app)
    loaded(page, ".my-posts")
    posts = page.locator(".my-posts")
    assert posts.locator(".card-count").inner_text() == "1 total"
    tile = posts.locator(".post-tile")
    assert tile.count() == 1
    assert tile.locator(".post-tile-name").inner_text() == "Mitzi"
    tile.click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    assert page.locator("[data-page=cat] h1").inner_text() == "Mitzi"


def test_someone_with_no_posts_is_told_how_to_make_one(open_member_app, shot):
    page = home(open_member_app, ADMIN)
    posts = page.locator(".my-posts")
    posts.get_by_text("You haven't posted yet.").wait_for()
    assert posts.locator(".post-tile").count() == 0
    assert page.locator(".me-met").inner_text() == "0 cats met"
    shot(page, "member-home-empty")
    posts.get_by_role("button", name="Scan a cat").click()
    page.get_by_role("dialog", name="Scan a cat").wait_for()


def test_friends_are_not_there_yet_and_the_button_says_so(open_member_app):
    page = home(open_member_app)
    page.get_by_role("button", name="Friends").click()
    page.locator(".toast.on").get_by_text("Friends arrive here soon.").wait_for()


def test_the_bar_stays_at_the_top_and_folds_while_scrolling(open_member_app, shot):
    """The glass bar belongs to the screen, not to the page under it: in the
    prototype it never scrolls away, and scrolling down folds the pill to
    the photo and opens the Friends button. Until E6 the feed's bar scrolled
    off with the first card."""
    page = home(open_member_app)
    loaded(page, ".my-posts")
    top = page.evaluate("document.querySelector('.home-top').getBoundingClientRect().y")
    wide = page.evaluate("document.querySelector('.me-pill').getBoundingClientRect().width")
    scroll_down(page, "home")
    page.wait_for_selector(".home-top.collapsed")
    page.wait_for_function(
        "document.querySelector('.me-pill').getBoundingClientRect().width < 60"
    )
    assert wide > 200
    now = page.evaluate("document.querySelector('.home-top').getBoundingClientRect().y")
    assert abs(now - top) <= 12, (top, now)
    page.wait_for_function(
        "document.querySelector('.friends-button').getBoundingClientRect().width > 120"
    )
    shot(page, "member-home-scrolled")


def test_the_feeds_bar_stays_at_the_top_too(open_member_app):
    page = open_member_app(ADMIN)
    page.wait_for_selector("article.post")
    scroll_down(page, "feed")
    page.wait_for_selector(".top-buttons.collapsed")
    y = page.evaluate("document.querySelector('.top-buttons').getBoundingClientRect().y")
    assert 0 <= y <= 30, y


def test_the_pill_opens_the_profile_with_your_posts(open_member_app, shot):
    page = home(open_member_app)
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    profile = page.locator("[data-page=profile]")
    assert profile.locator(".profile-name").inner_text() == "collaborator"
    assert profile.locator(".profile-sub").inner_text().startswith("@collaborator · since ")
    assert profile.get_by_label("Display name").input_value() == "collaborator"
    loaded(page, "[data-page=profile] .my-posts")
    assert profile.locator(".my-posts .card-count").inner_text() == "1 post"
    # Four to a row, the photo alone: its cat and day are its name.
    photo = profile.locator(".my-posts .post-tile img")
    assert photo.get_attribute("alt").startswith("Mitzi, ")
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=profile]').getBoundingClientRect().x) < 1"
    )
    shot(page, "member-profile")


def open_profile(page):
    page.get_by_role("button", name="Your profile").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    return page.locator("[data-page=profile]")


def test_a_new_name_is_saved_and_everyone_sees_it(open_member_app, app, shot):
    """Typed into its row on the profile and saved on "done" (B1a): its
    owner sees it at once, on the profile and on Home's pill, and the
    campus sees it on their posts once it has been checked."""
    page = home(open_member_app)
    profile = open_profile(page)
    name = profile.get_by_label("Display name")
    name.fill("  Dana   of the Library ")
    # Home asked who you are again as the profile opened, and the answer
    # redraws the page. What was typed must still be there: it once was not.
    page.evaluate(
        "import('/social/data.js').then(async (d) => (await import('/social/store.js')).set({ me: await d.me() }))"
    )
    assert name.input_value() == "  Dana   of the Library "
    with page.expect_response(
        lambda res: res.url.endswith("/api/v1/me") and res.request.method == "PATCH"
    ) as saved:
        name.press("Enter")
    assert saved.value.status == 200
    page.locator(".toast.on").get_by_text("Name saved").wait_for()
    # Cleaned by the server, and shown as it was stored.
    assert name.input_value() == "Dana of the Library"
    assert profile.locator(".profile-name").inner_text() == "Dana of the Library"
    shot(page, "member-profile-renamed")
    page.get_by_role("button", name="Back").click()
    assert page.locator(".me-pill .me-name").inner_text() == "Dana of the Library"

    # The events Lambda has published it: another member reads it on the post.
    _, feed = app.api("GET", "/api/v1/feed", email=ADMIN)
    assert feed["cards"][0]["author"]["displayName"] == "Dana of the Library"


def test_an_emptied_name_goes_back_to_what_it_was(open_member_app, app):
    page = home(open_member_app)
    profile = open_profile(page)
    name = profile.get_by_label("Display name")
    name.fill("   ")
    name.press("Enter")
    page.wait_for_function(
        "document.querySelector('[data-row=name] input').value === 'collaborator'"
    )
    _, me = app.api("GET", "/api/v1/me", email=COLLABORATOR)
    assert (me["displayName"], me["namePending"]) == ("collaborator", False)


def test_the_theme_follows_the_account_to_another_phone(open_member_app, app):
    page = home(open_member_app)
    profile = open_profile(page)
    with page.expect_response(
        lambda res: res.url.endswith("/api/v1/me") and res.request.method == "PATCH"
    ):
        profile.locator("[data-row=theme]").click()
        page.get_by_role("menuitemradio", name="Cat coat light").click()
    _, me = app.api("GET", "/api/v1/me", email=COLLABORATOR)
    assert me["theme"] == "cats-light"
    # A phone that has never chosen opens in the account's theme.
    other = open_member_app(COLLABORATOR)
    other.wait_for_selector("[data-screen=frame]")
    other.wait_for_function("document.documentElement.dataset.theme === 'cats-light'")
