"""Blocks (B8): blocking a person hides each from the other everywhere and
ends the friendship (06-moderation.md, "Reports, blocks and bans").
"""

import random

from app import handler

from .test_friends import (  # noqa: F401  (the fixtures)
    PEOPLE,
    THIRD,
    accept,
    feed,
    friend_items,
    kinds,
    mirrored,
    people,
    suggest,
    vote,
    voting,
)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)
from .test_posts import CAT, POST, campus, make_post, published  # noqa: F401


def block(people, who, by):  # noqa: F811
    return call("PUT", f"/api/v1/blocks/{people['me'][who]['userId']}", email=by)


def unblock(people, who, by):  # noqa: F811
    return call("DELETE", f"/api/v1/blocks/{people['me'][who]['userId']}", email=by)


def block_items(table):
    return {
        (i["PK"].removeprefix("USER#"), i["SK"])
        for i in table.scan()["Items"]
        if i["SK"].startswith("BLOCK")
    }


def paired(table):
    """Invariant 5: a block never exists without its mirror."""
    items = block_items(table)
    blocks = {(a, sk.removeprefix("BLOCK#")) for a, sk in items if sk.startswith("BLOCK#")}
    mirrors = {(sk.removeprefix("BLOCKEDBY#"), b) for b, sk in items if sk.startswith("BLOCKEDBY#")}
    assert blocks == mirrors
    return blocks


def blocked_by(who):
    status, body = call("GET", "/api/v1/blocks", email=who)
    assert status == 200, body
    return [p["username"] for p in body["people"]]


def test_a_block_is_two_items_and_ends_the_friendship(people):  # noqa: F811
    accept(people, of=ADMIN, by=HELPER)
    admin, helper = (people["me"][who]["userId"] for who in (ADMIN, HELPER))
    status, body = block(people, HELPER, by=ADMIN)
    assert (status, body) == (200, {"userId": helper, "blocked": True})
    assert paired(people["social"]) == {(admin, helper)}
    assert friend_items(people["social"]) == set()

    # Only the one who blocked has a list of it; the other is told nothing.
    assert blocked_by(ADMIN) == [people["me"][HELPER]["username"]]
    assert blocked_by(HELPER) == []
    listed = call("GET", "/api/v1/blocks", email=ADMIN)[1]["people"][0]
    assert set(listed) == {"userId", "username", "displayName", "avatar", "at"}
    assert HELPER not in str(listed)  # never their email

    # Again: the same, and still one pair.
    assert block(people, HELPER, by=ADMIN)[0] == 200
    assert paired(people["social"]) == {(admin, helper)}


def test_two_people_kept_apart_see_nothing_of_each_other(people):  # noqa: F811
    make_post()  # HELPER's
    published(people["social"], POST)
    helper, admin = (people["me"][who]["userId"] for who in (HELPER, ADMIN))
    assert kinds(feed(ADMIN)) == ["post"]

    block(people, HELPER, by=ADMIN)
    # The one who blocked: no post in the feed, on the cat's page, by its
    # id, nor a page for the person.
    assert feed(ADMIN)["cards"] == []
    assert call("GET", f"/api/v1/cats/{CAT}/posts", email=ADMIN)[1]["cards"] == []
    for path in (f"/api/v1/posts/{POST}", f"/api/v1/users/{helper}", f"/api/v1/users/{helper}/posts"):
        status, body = call("GET", path, email=ADMIN)
        assert (status, body["code"]) == (404, "gone"), path
    # And the one who was blocked sees nothing of the blocker either,
    # with the same answer a missing person gets.
    status, body = call("GET", f"/api/v1/users/{admin}", email=HELPER)
    assert (status, body) == (404, {"error": "no such person", "code": "gone"})
    # Everyone else sees both as before.
    assert kinds(feed(THIRD)) == ["post"]
    assert call("GET", f"/api/v1/users/{helper}", email=THIRD)[0] == 200
    # One's own post is one's own.
    assert kinds(feed(HELPER)) == ["post"]

    assert unblock(people, HELPER, by=ADMIN) == (200, {"userId": helper, "blocked": False})
    assert paired(people["social"]) == set()
    assert kinds(feed(ADMIN)) == ["post"]
    assert call("GET", f"/api/v1/users/{helper}", email=ADMIN)[1]["person"]["friend"] == "no"


def test_a_blocked_friends_vote_is_no_longer_a_card(voting):  # noqa: F811
    suggest("Mango", HELPER)
    voting["stream"].settle()
    assert kinds(feed(ADMIN)) == ["vote"]
    block(voting, HELPER, by=ADMIN)
    assert feed(ADMIN)["cards"] == []
    # THIRD, still ADMIN's friend, votes: the card names THIRD alone.
    vote("mango", THIRD)
    (card,) = feed(ADMIN)["cards"]
    assert [p["username"] for p in card["voters"]] == [voting["me"][THIRD]["username"]]
    assert card["friendsVoted"] == 1


def test_an_invite_does_not_cross_a_block_until_it_is_lifted(people):  # noqa: F811
    block(people, HELPER, by=ADMIN)
    for of, by in ((ADMIN, HELPER), (HELPER, ADMIN)):
        status, body = accept(people, of=of, by=by)
        assert (status, body["code"]) == (404, "gone")
    assert friend_items(people["social"]) == set()
    unblock(people, HELPER, by=ADMIN)
    assert accept(people, of=ADMIN, by=HELPER)[0] == 200


def test_what_blocking_refuses(people, monkeypatch):  # noqa: F811
    me = people["me"][ADMIN]["userId"]
    assert call("PUT", f"/api/v1/blocks/{me}", email=ADMIN)[0] == 400
    status, body = call("PUT", "/api/v1/blocks/01JD0000000000000000000XXX", email=ADMIN)
    assert (status, body["code"]) == (404, "gone")
    assert paired(people["social"]) == set()
    # Unblocking someone who was never blocked changes nothing and says so.
    assert unblock(people, HELPER, by=ADMIN)[0] == 200
    monkeypatch.setattr(handler, "BLOCKS_PER_DAY", 1)
    assert block(people, HELPER, by=ADMIN)[0] == 200
    assert block(people, THIRD, by=ADMIN)[0] == 429


def test_blocks_and_friendships_keep_their_mirrors_through_anything(people, monkeypatch):  # noqa: F811
    """The plan's property, with blocks in it: accept, remove, block and
    unblock in any order, by anyone. Every item has its mirror, and nobody
    is ever a friend of someone a block keeps them apart from."""
    monkeypatch.setattr(handler, "INVITES_PER_DAY", 10_000)
    monkeypatch.setattr(handler, "BLOCKS_PER_DAY", 10_000)
    ids = {who: people["me"][who]["userId"] for who in PEOPLE}
    rng = random.Random(8)
    for _ in range(160):
        a, b = rng.sample(PEOPLE, 2)
        move = rng.choice(("accept", "accept", "remove", "block", "unblock"))
        if move == "accept":
            assert accept(people, of=a, by=b)[0] in (200, 404)
        elif move == "remove":
            assert call("DELETE", f"/api/v1/friends/{ids[a]}", email=b)[0] == 200
        elif move == "block":
            assert block(people, a, by=b)[0] == 200
        else:
            assert unblock(people, a, by=b)[0] == 200
        friends = mirrored(people["social"])
        apart = paired(people["social"])
        apart |= {(y, x) for x, y in apart}
        assert not friends & apart
