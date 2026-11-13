"""Blocks (B8): "Block" in a friend's menu and on anyone's page, and the
list of blocked people in the profile, with "Unblock". Blocking hides two
people from each other everywhere. The seeded collaborator posted Mitzi."""

from .localapp import ADMIN, COLLABORATOR
from .test_member_friends import befriend, friends_page, name_of
from .test_member_home import home


def blocked(app, email):
    return [p["username"] for p in app.api("GET", "/api/v1/blocks", email=email)[1]["people"]]


def test_blocking_from_a_persons_page_takes_their_posts_out_of_the_feed(app, open_member_app, shot):
    page = open_member_app(ADMIN)
    post = page.locator("article.post").first
    post.wait_for()
    post.get_by_role("button", name="collaborator", exact=True).click()
    person = page.locator("[data-page=person]")
    person.locator(".person-name").wait_for()
    page.wait_for_timeout(600)  # the page has slid in

    person.get_by_role("button", name="Options for collaborator").click()
    menu = page.get_by_role("menu", name="Options for collaborator")
    # Not a friend: there is nothing to remove, only to block.
    assert menu.get_by_role("menuitem").all_inner_texts() == ["Block"]
    shot(page, "member-person-menu")
    menu.get_by_role("menuitem", name="Block").click()
    dialog = page.get_by_role("alertdialog")
    assert "Block collaborator?" in dialog.inner_text()
    assert "They are not told." in dialog.inner_text()
    dialog.get_by_role("button", name="Block").click()
    page.locator(".toast.on").get_by_text("collaborator is blocked").wait_for()

    # Their page closes, and the feed already on screen has lost the post.
    page.wait_for_function("document.querySelectorAll('[data-page=person]').length === 0")
    page.get_by_text("No posts yet").wait_for()
    assert page.locator("article.post").count() == 0
    assert blocked(app, ADMIN) == ["collaborator"]
    # The other one's side: nothing of the admin, and nothing said.
    admin = app.api("GET", "/api/v1/me", email=ADMIN)[1]["userId"]
    assert app.api("GET", f"/api/v1/users/{admin}", email=COLLABORATOR)[0] == 404
    assert blocked(app, COLLABORATOR) == []


def test_a_friend_is_blocked_from_the_friends_list(app, open_member_app):
    befriend(app)
    admin = name_of(app, ADMIN)
    page = friends_page(open_member_app)
    friends = page.locator("[data-page=friends]")
    row = friends.locator(".friends-row")
    row.wait_for()
    row.get_by_role("button", name=f"Options for {admin}").click()
    menu = page.get_by_role("menu", name=f"Options for {admin}")
    assert menu.get_by_role("menuitem").all_inner_texts() == ["Remove from friends", "Block"]
    menu.get_by_role("menuitem", name="Block").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Block").click()
    page.locator(".toast.on").get_by_text(f"{admin} is blocked").wait_for()
    friends.get_by_text("No friends here yet.").wait_for()
    assert blocked(app, COLLABORATOR) == [admin]
    assert [p["me"] for p in app.api("GET", "/api/v1/friends", email=ADMIN)[1]["people"]] == [True]


def test_the_profile_lists_blocked_people_and_unblocks_them(app, open_member_app, shot):
    collaborator = app.api("GET", "/api/v1/me", email=COLLABORATOR)[1]["userId"]
    assert app.api("PUT", f"/api/v1/blocks/{collaborator}", email=ADMIN)[0] == 200

    page = home(open_member_app, ADMIN)
    page.locator(".me-pill").click()
    page.wait_for_selector("[data-page=profile][data-state=shown]")
    page.locator("[data-page=profile] [data-row=blocked]").click()
    page.wait_for_selector("[data-page=blocked][data-state=shown]")
    listed = page.locator("[data-page=blocked]")
    row = listed.locator(".friends-row")
    row.wait_for()
    assert row.locator(".friend-name").inner_text() == "collaborator"
    page.wait_for_timeout(600)
    shot(page, "member-blocked")

    row.get_by_role("button", name="Unblock").click()
    page.locator(".toast.on").get_by_text("collaborator is unblocked").wait_for()
    listed.get_by_text("You have not blocked anyone.").wait_for()
    assert blocked(app, ADMIN) == []
    assert app.api("GET", f"/api/v1/users/{collaborator}", email=ADMIN)[0] == 200
