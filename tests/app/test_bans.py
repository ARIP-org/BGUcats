"""Bans (B8c): an admin bans a person from the desk. Every write of theirs
is refused by both APIs, and nobody sees their posts or their page, until
the ban is lifted (06-moderation.md, "Reports, blocks and bans";
03-data-model.md, invariant 9).

Runs the member API, the desk's API and the events Lambda together.
"""

from ulid import ULID

import tests.admin.test_handler  # noqa: F401  (the env the desk's API reads, set at import)
from admin import handler as desk

from .test_friends import THIRD, feed, kinds, people  # noqa: F401  (the fixture)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)
from .test_posts import CAT, POST, campus, counters  # noqa: F401  (the fixture)
from .test_reports import FOURTH, desk_call, post_item, queue, report, resolve, world  # noqa: F401


def ban(world, who, by=ADMIN):  # noqa: F811
    return desk_call("POST", f"/api/people/{world['me'][who]['userId']}/ban", email=by)


def unban(world, who, by=ADMIN):  # noqa: F811
    return desk_call("POST", f"/api/people/{world['me'][who]['userId']}/unban", email=by)


def people_list():
    status, body = desk_call("GET", "/api/people")
    assert status == 200, body
    return {p["email"]: p for p in body["people"]}


def test_the_desk_lists_everyone_who_has_opened_the_app(world):  # noqa: F811
    listed = people_list()
    assert set(listed) == {ADMIN, HELPER, THIRD, FOURTH}
    one = listed[HELPER]
    assert set(one) == {
        "userId",
        "username",
        "displayName",
        "email",
        "status",
        "createdAt",
        "bannedAt",
        "bannedBy",
    }
    assert (one["status"], one["bannedAt"]) == ("active", None)
    assert desk_call("GET", "/api/people", email=HELPER)[0] == 403


def test_a_banned_person_writes_nothing_and_is_seen_by_nobody(world):  # noqa: F811
    call("PUT", f"/api/v1/posts/{POST}/like", email=THIRD)
    helper = world["me"][HELPER]["userId"]
    assert ban(world, HELPER) == (200, {"userId": helper, "status": "banned"})
    world["stream"].settle()
    listed = people_list()[HELPER]
    assert (listed["status"], listed["bannedBy"]) == ("banned", ADMIN)

    # Their post is out of every list, with what it counted for.
    item = post_item(world)
    assert (item["status"], item["hiddenReason"]) == ("hidden", "banned")
    assert feed(THIRD)["cards"] == []
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (0, 0)
    status, body = call("GET", f"/api/v1/users/{helper}", email=THIRD)
    assert (status, body["code"]) == (404, "gone")

    # The member API answers them nothing but that they are blocked.
    for method, path, body in (
        ("GET", "/api/v1/me", None),
        ("GET", "/api/v1/feed", None),
        ("PUT", f"/api/v1/cats/{CAT}/vote", {"nameKey": "simba"}),
        ("POST", "/api/v1/reports", {"reportId": str(ULID()), "targetType": "post", "targetId": POST, "reason": "spam"}),
    ):
        status, answer = call(method, path, body, email=HELPER)
        assert (status, answer["code"]) == (403, "banned"), path
    # And the desk's API takes no encounter or pick from them.
    status, answer = desk_call(
        "POST", "/api/encounters", {"sessionId": str(ULID()), "lat": 31.262, "lon": 34.803, "accuracyM": 6}, HELPER
    )
    assert (status, answer["error"]) == (403, "this account is blocked")
    # They may still look at the cats there: a read is not a write.
    assert desk_call("GET", "/api/cats", email=HELPER)[0] == 200

    # Lifted: everything is as it was, the like included.
    assert unban(world, HELPER) == (200, {"userId": helper, "status": "active"})
    world["stream"].settle()
    assert post_item(world)["status"] == "visible"
    assert kinds(feed(THIRD)) == ["post"]
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (1, 1)
    assert call("GET", "/api/v1/me", email=HELPER)[0] == 200
    assert people_list()[HELPER]["status"] == "active"


def test_a_post_an_admin_hid_stays_hidden_when_a_ban_is_lifted(world):  # noqa: F811
    desk_call("POST", f"/api/posts/{POST}/hide")
    world["stream"].settle()
    ban(world, HELPER)
    world["stream"].settle()
    unban(world, HELPER)
    world["stream"].settle()
    item = post_item(world)
    assert (item["status"], item["hiddenReason"]) == ("hidden", "admin")


def test_banning_twice_and_unbanning_twice_change_nothing_more(world):  # noqa: F811
    for _ in range(2):
        assert ban(world, HELPER)[0] == 200
        world["stream"].settle()
    assert counters(world["social"])["posts"] == 0
    for _ in range(2):
        assert unban(world, HELPER)[0] == 200
        world["stream"].settle()
    assert counters(world["social"])["posts"] == 1


def test_a_reported_person_is_banned_from_the_report(world):  # noqa: F811
    helper = world["me"][HELPER]["userId"]
    report(THIRD, target=helper, kind="user", reason="harassment")
    world["stream"].settle()
    (entry,) = queue()
    status, body = resolve(entry["reportId"], "ban")
    assert (status, body["status"], body["closed"]) == (200, "actioned", 1)
    world["stream"].settle()
    assert people_list()[HELPER]["status"] == "banned"
    assert feed(THIRD)["cards"] == []
    assert queue() == []
    # A post is not banned; a person is not hidden.
    report(FOURTH, target=world["me"][THIRD]["userId"], kind="user")
    (entry,) = queue()
    assert resolve(entry["reportId"], "hide")[0] == 400


def test_who_cannot_be_banned_and_who_cannot_ban(world, monkeypatch):  # noqa: F811
    # Oneself, an admin, nobody.
    assert ban(world, ADMIN)[0] == 400
    world["data"].put_item(Item={"PK": f"ADMIN#{THIRD}", "SK": "META", "email": THIRD})
    status, body = ban(world, THIRD)
    assert (status, body["error"]) == (409, "an admin cannot be banned; make them a user first")
    assert desk_call("POST", "/api/people/01JD0000000000000000000XXX/ban")[0] == 404
    assert desk_call("POST", "/api/people/01JD0000000000000000000XXX/unban")[0] == 404
    # A user bans nobody.
    assert ban(world, FOURTH, by=HELPER)[0] == 403
    assert people_list()[FOURTH]["status"] == "active"
    # With the app closed on the account there is nobody to ban.
    monkeypatch.setattr(desk, "SOCIAL", False)
    assert ban(world, FOURTH)[0] == 404
    assert desk_call("GET", "/api/people")[1] == {"people": []}


def test_a_post_written_just_before_a_ban_is_never_shown(world):  # noqa: F811
    """The post is still being checked when its author is banned: the
    events Lambda, coming to publish it, finds the ban."""
    from .test_posts import OTHER_SESSION

    photo = "01JD0000000000000000000PH9"
    world["data"].put_item(
        Item={"PK": f"PHOTO#{photo}", "SK": "META", "photoId": photo, "sessionId": OTHER_SESSION, "status": "unlabeled", "mediaType": "photo"}
    )
    world["data"].put_item(Item={"PK": f"ADMIN#{THIRD}", "SK": "META", "email": THIRD, "role": "user"})
    # ADMIN owns the other session; make THIRD its owner so a user posts it.
    world["data"].update_item(
        Key={"PK": f"SESSION#{OTHER_SESSION}", "SK": "META"},
        UpdateExpression="SET startedBy = :who",
        ExpressionAttributeValues={":who": THIRD},
    )
    new_post = str(ULID())
    status, _ = call(
        "POST",
        "/api/v1/posts",
        {"postId": new_post, "sessionId": OTHER_SESSION, "photoIds": [photo], "claim": {"catId": CAT}},
        email=THIRD,
    )
    assert status == 200
    assert ban(world, THIRD)[0] == 200  # before the stream delivers the post
    world["stream"].settle()
    item = world["social"].get_item(Key={"PK": f"POST#{new_post}", "SK": "META"})["Item"]
    assert (item["status"], item["hiddenReason"]) == ("hidden", "banned")
    assert [c["postId"] for c in feed(FOURTH)["cards"]] == [POST]
