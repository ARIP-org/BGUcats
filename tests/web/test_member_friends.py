"""Friends (B5, E7): Home's card, the friends page with its podium, "Add
friend" (an invite link, D4), and a person's page. The seeded campus has
two people who are not friends yet: the collaborator, who met and posted
Mitzi, and the admin."""

from app import handler as app_handler

from .localapp import ADMIN, COLLABORATOR
from .test_member_home import home, loaded

CLIPBOARD = {"permissions": ["clipboard-read", "clipboard-write"]}


def code_of(app, email):
    return app.api("GET", "/api/v1/me", email=email)[1]["inviteCode"]


def name_of(app, email):
    """The admin's username is "admin" with four digits: the bare word is
    reserved."""
    return app.api("GET", "/api/v1/me", email=email)[1]["username"]


def befriend(app):
    app.api("POST", "/api/v1/me/terms", {"version": "2026-11"}, email=ADMIN)
    status, body = app.api(
        "POST", f"/api/v1/invites/{code_of(app, COLLABORATOR)}/accept", email=ADMIN
    )
    assert status == 200, body


def friends_page(open_member_app, email=COLLABORATOR, **options):
    page = home(open_member_app, email, **options)
    page.locator(".friends-button").click()
    page.wait_for_selector("[data-page=friends][data-state=shown]")
    page.wait_for_selector("[data-page=friends] .podium")
    return page


def podium(page):
    return [
        (
            place.get_attribute("data-place"),
            place.locator(".podium-name").inner_text(),
            place.locator(".podium-found").inner_text(),
        )
        for place in page.locator(".podium-place:not(.empty)").all()
    ]


def test_with_no_friends_the_page_says_how_to_get_one(app, open_member_app, shot):
    page = home(open_member_app, **CLIPBOARD)
    card = page.locator(".friends-card")
    card.get_by_text("Invite friends to see who finds the most cats.").wait_for()
    assert card.locator(".friend-row").count() == 1

    card.click()  # the whole card opens the page, as the button beside it does
    page.wait_for_selector("[data-page=friends][data-state=shown]")
    friends = page.locator("[data-page=friends]")
    friends.locator(".podium").wait_for()
    assert podium(page) == [("1", "You", "1 cat")]
    friends.get_by_text("No friends here yet.").wait_for()
    assert friends.locator(".friends-search").count() == 0
    shot(page, "member-friends-empty")

    friends.get_by_role("button", name="Invite friends").click()
    sheet = page.get_by_role("dialog", name="Invite friends")
    sheet.wait_for()
    link = sheet.locator(".invite-address").inner_text()
    assert link.endswith(f"/app.html?invite={code_of(app, COLLABORATOR)}")
    shot(page, "member-friends-invite")
    sheet.get_by_role("button", name="Copy link").click()
    sheet.get_by_role("button", name="Copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == f"http://{link}"
    sheet.get_by_role("button", name="Close").click()
    sheet.wait_for(state="detached")


def test_a_friends_link_pasted_in_makes_a_friend(app, open_member_app, shot):
    page = friends_page(open_member_app)
    page.get_by_role("button", name="Add friend").click()
    sheet = page.get_by_role("dialog", name="Invite friends")
    field = sheet.get_by_label("Got a link from a friend?")

    field.fill("https://example.com/app.html?invite=nobodyhasthis")
    sheet.get_by_role("button", name="Add", exact=True).click()
    page.locator(".toast.on").get_by_text("That link does not work.").wait_for()
    field.fill(code_of(app, COLLABORATOR))
    sheet.get_by_role("button", name="Add", exact=True).click()
    page.locator(".toast.on").get_by_text("That is your own link.").wait_for()

    field.fill(f"https://example.com/app.html?invite={code_of(app, ADMIN)}")
    sheet.get_by_role("button", name="Add", exact=True).click()
    admin = name_of(app, ADMIN)
    page.locator(".toast.on").get_by_text(f"You and {admin} are friends now").wait_for()
    sheet.wait_for(state="detached")

    friends = page.locator("[data-page=friends]")
    row = friends.locator(".friends-row")
    row.wait_for()
    assert friends.locator(".friends-head .card-count").inner_text() == "1 friend"
    assert row.locator(".friend-name").inner_text() == admin
    assert row.locator(".friend-found").inner_text() == f"@{admin} · found 0 cats"
    # The collaborator met Mitzi; the admin met nobody.
    assert podium(page) == [("2", admin, "0 cats"), ("1", "You", "1 cat")]
    shot(page, "member-friends")

    # The other one has it too, without doing anything.
    theirs = app.api("GET", "/api/v1/friends", email=ADMIN)[1]["people"]
    assert [p["username"] for p in theirs] == ["collaborator", admin]


def test_the_list_is_searched_and_a_friend_can_be_removed(app, open_member_app):
    befriend(app)
    page = friends_page(open_member_app)
    friends = page.locator("[data-page=friends]")
    row = friends.locator(".friends-row")
    row.wait_for()

    search = friends.get_by_role("searchbox", name="Search by name or username")
    search.fill("zzz")
    friends.get_by_text("No friends match “zzz”.").wait_for()
    assert row.count() == 0
    search.fill("ADM")
    row.wait_for()

    # All time and this month are asked for separately.
    with page.expect_request(lambda r: "/api/v1/friends?period=all" in r.url):
        friends.get_by_role("tab", name="All time").click()
    assert friends.get_by_role("tab", name="All time").get_attribute("aria-selected") == "true"
    row.wait_for()

    admin = name_of(app, ADMIN)
    row.get_by_role("button", name=f"Options for {admin}").click()
    page.get_by_role("menuitem", name="Remove from friends").click()
    dialog = page.get_by_role("alertdialog")
    assert f"Remove {admin} from friends?" in dialog.inner_text()
    dialog.get_by_role("button", name="Remove").click()
    friends.get_by_text("No friends here yet.").wait_for()
    assert [p["me"] for p in app.api("GET", "/api/v1/friends", email=ADMIN)[1]["people"]] == [True]


def test_a_link_opened_on_the_phone_makes_a_friend_at_once(app, open_member_app):
    code = code_of(app, ADMIN)
    page = open_member_app(COLLABORATOR, path=f"/app.html?browser&invite={code}")
    admin = name_of(app, ADMIN)
    page.locator(".toast.on").get_by_text(f"You and {admin} are friends now").wait_for()
    page.wait_for_selector("[data-page=friends][data-state=shown]")
    page.locator("[data-page=friends] .friends-row").wait_for()
    assert "invite" not in page.url
    # Used once: opening the app again does not ask again.
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.wait_for_timeout(400)
    assert page.locator(".toast.on").count() == 0
    assert page.locator("[data-page=friends]").count() == 0


def test_home_shows_you_and_your_friends_by_cats_found(app, open_member_app, shot):
    befriend(app)
    page = home(open_member_app)
    rows = page.locator(".friends-card .friend-row")
    rows.nth(1).wait_for()
    assert [r.locator(".friend-name").inner_text() for r in rows.all()] == [
        "You",
        name_of(app, ADMIN),
    ]
    assert rows.nth(0).locator(".friend-found").inner_text() == "found 1 cat"
    # Beside each, the cats they met last: Mitzi for you, none for the admin.
    loaded(page, ".friends-card .friend-cats")
    assert rows.nth(0).locator(".friend-cats img").count() == 1
    assert rows.nth(1).locator(".friend-cats img").count() == 0
    assert page.locator(".friends-card .card-note").count() == 0
    loaded(page, ".my-posts")
    shot(page, "member-home-friends")


def test_a_posts_author_opens_their_page(app, open_member_app, shot):
    befriend(app)
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.get_by_role("button", name="collaborator", exact=True).click()
    page.wait_for_selector("[data-page=person][data-state=shown]")
    person = page.locator("[data-page=person]")
    person.locator(".person-name").wait_for()
    assert person.locator(".person-name").inner_text() == "collaborator"
    assert person.locator(".person-username").inner_text() == "@collaborator"
    chips = [c.inner_text() for c in person.locator(".person-chip").all()]
    assert chips[0] == "1 cat found" and chips[1].startswith("Friends since ")
    loaded(page, "[data-page=person] .person-posts")
    assert person.locator(".person-posts img").count() == 1
    page.wait_for_timeout(600)  # the page has slid in
    shot(page, "member-person")
    # A post of a cat opens the cat.
    person.locator(".person-posts button").click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    assert page.locator("[data-page=cat] h1").inner_text() == "Mitzi"


def test_a_persons_page_says_how_many_friends_you_share(app, open_member_app):
    # A third member, a friend of both the admin and the collaborator.
    third = "third@example.com"
    status, body = app.api("POST", "/api/admins", {"email": third, "role": "user"}, email=ADMIN)
    assert status == 200, body
    for who in (ADMIN, third):
        assert app.api("GET", "/api/v1/me", email=who)[0] == 200  # their account
        status, body = app.api(
            "POST", "/api/v1/me/terms", {"version": app_handler.TERMS_VERSION}, email=who
        )
        assert status == 200, body
    for other in (ADMIN, COLLABORATOR):
        status, body = app.api(
            "POST", f"/api/v1/invites/{code_of(app, other)}/accept", email=third
        )
        assert status == 200, body
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.get_by_role("button", name="Open collaborator's page").click()
    person = page.locator("[data-page=person]")
    person.locator(".person-name").wait_for()
    # How many, never who.
    assert person.locator(".person-chip[data-chip=mutual]").inner_text() == "1 friend in common"
    assert "third" not in person.inner_text()


def test_someone_who_is_not_a_friend_shows_no_friendship(app, open_member_app):
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.get_by_role("button", name="Open collaborator's page").click()
    person = page.locator("[data-page=person]")
    person.locator(".person-name").wait_for()
    assert [c.inner_text() for c in person.locator(".person-chip").all()] == ["1 cat found"]


# ------------------------------------------------- friends' votes in the feed


def test_a_friends_vote_is_a_card_in_the_feed_and_a_tap_votes(app, open_member_app, shot):
    """The prototype's name-vote card: who voted for what, the poll's names
    with the friends who chose each, and a tap votes."""
    befriend(app)
    cat = app.data["cats"]["Mitzi"]
    status, _ = app.api("POST", f"/api/v1/cats/{cat}/names", {"name": "Mango"}, email=COLLABORATOR)
    assert status == 200

    page = open_member_app(ADMIN)
    card = page.locator("article.vote-card")
    card.wait_for()
    # Mango leads with its one vote, so that is what the cat is called.
    assert card.locator(".vote-words").inner_text() == "collaborator voted to call this cat “Mango”"
    assert card.get_attribute("aria-label") == "Name vote for Mango"
    mango = card.locator(".vote-option[data-name=mango]")
    mitzi = card.locator(".vote-option[data-name=mitzi]")
    assert mango.locator(".vote-pct").inner_text() == "100%"
    assert mango.locator(".vote-friends .avatar").count() == 1
    assert mitzi.locator(".vote-friends .avatar").count() == 0
    assert card.locator(".vote-foot span").inner_text() == "1 vote · 1 friend voted"
    page.wait_for_function("[...document.querySelectorAll('.vote-card img')].every(i => i.complete)")
    shot(page, "member-feed-vote")

    # The admin votes to keep the name the cat had.
    with page.expect_response(lambda r: r.url.endswith("/vote") and r.request.method == "PUT") as sent:
        mitzi.click()
    assert sent.value.status == 200
    page.wait_for_function(
        "document.querySelector('.vote-foot span').innerText === '2 votes · You and 1 friend voted'"
    )
    assert mitzi.get_attribute("aria-checked") == "true"
    assert mitzi.locator(".vote-pct").inner_text() == "50%"
    # The friend's mark stays on the name they chose.
    assert mango.locator(".vote-friends .avatar").count() == 1

    card.get_by_role("button", name="All names").click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    page.wait_for_selector("[data-page=cat] .poll")


def test_someone_who_is_not_a_friend_makes_no_card(app, open_member_app):
    cat = app.data["cats"]["Mitzi"]
    app.api("POST", f"/api/v1/cats/{cat}/names", {"name": "Mango"}, email=COLLABORATOR)
    page = open_member_app(ADMIN)
    page.wait_for_selector("article.post")
    assert page.locator("article.vote-card").count() == 0
