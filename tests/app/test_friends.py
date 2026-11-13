"""Friends (B5a): an invite link makes two people friends at once (D4), a
friendship is always two items, and what a friend sees that others do not.
"""

import random

import pytest

from app import handler
from common import tables

from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)
from .test_posts import CAT, POST, campus, make_post, published  # noqa: F401

THIRD = "third@example.com"
PEOPLE = (ADMIN, HELPER, THIRD)
PERSON_KEYS = {
    "userId",
    "username",
    "displayName",
    "avatar",
    "since",
    "friend",
    "friendSince",
    "me",
    "found",
}


@pytest.fixture
def people(campus):  # noqa: F811
    campus["data"].put_item(
        Item={"PK": f"ADMIN#{THIRD}", "SK": "META", "email": THIRD, "role": "user"}
    )
    call("POST", "/api/v1/me/terms", {"version": "2026-11"}, email=THIRD)
    campus["me"] = {who: call("GET", "/api/v1/me", email=who)[1] for who in PEOPLE}
    return campus


def accept(people, of, by):
    """`by` opens `of`'s invite link."""
    code = people["me"][of]["inviteCode"]
    return call("POST", f"/api/v1/invites/{code}/accept", email=by)


def friend_items(table):
    return {
        (i["PK"].removeprefix("USER#"), i["SK"].removeprefix("FRIEND#"))
        for i in table.scan()["Items"]
        if i["SK"].startswith("FRIEND#")
    }


def mirrored(table):
    """Invariant 5: a FRIEND item never exists without its mirror."""
    pairs = friend_items(table)
    assert {(b, a) for a, b in pairs} == pairs
    return pairs


def friends_of(who, period=None):
    status, body = call(
        "GET", "/api/v1/friends", email=who, query={"period": period} if period else None
    )
    assert status == 200, body
    return body


def test_an_invite_link_makes_two_friends_at_once(people):
    assert call("GET", "/api/v1/me/invite", email=ADMIN)[1] == {
        "code": people["me"][ADMIN]["inviteCode"]
    }
    status, body = accept(people, of=ADMIN, by=HELPER)
    assert status == 200
    theirs = body["person"]
    assert set(theirs) == PERSON_KEYS
    assert (theirs["userId"], theirs["friend"], theirs["me"]) == (
        people["me"][ADMIN]["userId"],
        "yes",
        False,
    )
    assert theirs["friendSince"]
    a, b = (people["me"][who]["userId"] for who in (ADMIN, HELPER))
    assert mirrored(people["social"]) == {(a, b), (b, a)}
    item = tables.get_one(people["social"], f"USER#{a}", f"FRIEND#{b}")
    assert (item["via"], item["since"]) == ("invite", theirs["friendSince"])

    # Both now have the other in their list, and nobody else does.
    for who, other in ((ADMIN, HELPER), (HELPER, ADMIN)):
        listed = friends_of(who)["people"]
        assert {p["username"] for p in listed} == {
            people["me"][ADMIN]["username"],
            people["me"][HELPER]["username"],
        }
        assert next(p for p in listed if p["me"])["userId"] == people["me"][who]["userId"]
        assert next(p for p in listed if not p["me"])["friend"] == "yes"
        assert people["me"][other]["email"] not in str(listed)
    assert [p["me"] for p in friends_of(THIRD)["people"]] == [True]


def test_the_same_link_twice_is_one_friendship_and_the_same_answer(people):
    first = accept(people, of=ADMIN, by=HELPER)
    again = accept(people, of=ADMIN, by=HELPER)
    back = accept(people, of=HELPER, by=ADMIN)  # the other one's link, too
    assert first == again
    assert back[0] == 200 and back[1]["person"]["friendSince"] == first[1]["person"]["friendSince"]
    assert len(mirrored(people["social"])) == 2


def test_what_an_invite_refuses(people, monkeypatch):
    assert accept(people, of=ADMIN, by=ADMIN) == (
        409,
        {"error": "this is your own invite", "code": "own_invite"},
    )
    status, body = call("POST", "/api/v1/invites/nobodyhasthis/accept", email=HELPER)
    assert (status, body["code"]) == (404, "gone")
    # Someone who has not accepted the terms.
    fourth = "fourth@example.com"
    people["data"].put_item(
        Item={"PK": f"ADMIN#{fourth}", "SK": "META", "email": fourth, "role": "user"}
    )
    code = people["me"][ADMIN]["inviteCode"]
    status, body = call("POST", f"/api/v1/invites/{code}/accept", email=fourth)
    assert (status, body["code"]) == (403, "terms_required")
    # The code of someone whose account is going away.
    people["social"].update_item(
        Key={"PK": f"USER#{people['me'][THIRD]['userId']}", "SK": "PROFILE"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "deleting"},
    )
    assert accept(people, of=THIRD, by=HELPER)[1]["code"] == "gone"
    assert mirrored(people["social"]) == set()

    monkeypatch.setattr(handler, "INVITES_PER_DAY", 2)
    assert accept(people, of=ADMIN, by=HELPER)[0] == 429  # two were used above
    assert mirrored(people["social"]) == set()


@pytest.mark.parametrize("blocker", [ADMIN, HELPER])
def test_a_block_between_them_does_nothing_and_says_nothing(people, blocker):
    """Blocks arrive with B8; the invite already refuses to cross one, in
    the same transaction that would have made the friendship."""
    blocked = HELPER if blocker == ADMIN else ADMIN
    a, b = people["me"][blocker]["userId"], people["me"][blocked]["userId"]
    people["social"].put_item(
        Item={"PK": f"USER#{a}", "SK": f"BLOCK#{b}", "at": "2026-11-13T10:00:00Z"}
    )
    status, body = accept(people, of=ADMIN, by=HELPER)
    # Exactly what an unknown code answers.
    assert (status, body) == (404, {"error": "this invite does not work", "code": "gone"})
    assert mirrored(people["social"]) == set()


def test_removing_a_friend_removes_both_sides(people):
    accept(people, of=ADMIN, by=HELPER)
    accept(people, of=ADMIN, by=THIRD)
    helper = people["me"][HELPER]["userId"]
    status, body = call("DELETE", f"/api/v1/friends/{helper}", email=ADMIN)
    assert (status, body) == (200, {"userId": helper, "friend": "no"})
    a, c = people["me"][ADMIN]["userId"], people["me"][THIRD]["userId"]
    assert mirrored(people["social"]) == {(a, c), (c, a)}
    # Again, or someone who never was a friend: the same answer.
    assert call("DELETE", f"/api/v1/friends/{helper}", email=ADMIN)[0] == 200
    assert call("DELETE", f"/api/v1/friends/{helper}", email=THIRD)[0] == 200
    assert call("DELETE", f"/api/v1/friends/{a}", email=ADMIN)[0] == 200
    assert mirrored(people["social"]) == {(a, c), (c, a)}
    assert call("GET", f"/api/v1/users/{helper}", email=ADMIN)[1]["person"]["friend"] == "no"


def test_every_friendship_has_its_mirror_after_any_sequence(people, monkeypatch):
    """The plan's property: accept and remove in any order, by anyone, and
    every friend item still has its mirror and matches what should be."""
    monkeypatch.setattr(handler, "INVITES_PER_DAY", 10_000)
    ids = {who: people["me"][who]["userId"] for who in PEOPLE}
    rng = random.Random(5)
    expected = set()
    for _ in range(120):
        a, b = rng.sample(PEOPLE, 2)
        if rng.random() < 0.6:
            assert accept(people, of=a, by=b)[0] == 200
            expected |= {(ids[a], ids[b]), (ids[b], ids[a])}
        else:
            assert call("DELETE", f"/api/v1/friends/{ids[a]}", email=b)[0] == 200
            expected -= {(ids[a], ids[b]), (ids[b], ids[a])}
        assert mirrored(people["social"]) == expected


def counted(people, who, sk, cats_met):
    people["social"].put_item(
        Item={
            "PK": f"USER#{people['me'][who]['userId']}",
            "SK": sk,
            "catsMet": cats_met,
            "encounters": cats_met,
        }
    )


def met(people, who, cat, last_day):
    people["social"].put_item(
        Item={
            "PK": f"USER#{people['me'][who]['userId']}",
            "SK": f"MET#{cat}",
            "catId": cat,
            "lastDay": last_day,
            "firstDay": last_day,
            "days": 1,
            "encounters": 1,
        }
    )


def test_the_list_is_whoever_found_the_most_first(people):
    accept(people, of=ADMIN, by=HELPER)
    accept(people, of=ADMIN, by=THIRD)
    month = f"STATS#{handler._israel_today().isoformat()[:7]}"
    for who, in_all, this_month in ((ADMIN, 9, 1), (HELPER, 4, 3), (THIRD, 12, 0)):
        counted(people, who, "STATS#ALL", in_all)
        if this_month:
            counted(people, who, month, this_month)
    for cat, day in (("c1", "2026-11-01"), ("c2", "2026-11-09"), ("c3", "2026-11-04"), ("c4", "2026-10-30")):
        met(people, HELPER, cat, day)

    def order(body):
        return [(p["username"], p["found"]) for p in body["people"]]

    names = {who: people["me"][who]["username"] for who in PEOPLE}
    body = friends_of(ADMIN)  # this month, unless asked
    assert body["period"] == "month" and body["requests"] == 0
    assert order(body) == [(names[HELPER], 3), (names[ADMIN], 1), (names[THIRD], 0)]
    assert order(friends_of(ADMIN, "all")) == [
        (names[THIRD], 12),
        (names[ADMIN], 9),
        (names[HELPER], 4),
    ]
    # Each with the cats they met last, newest first.
    helper = next(p for p in body["people"] if p["username"] == names[HELPER])
    assert helper["cats"] == ["c2", "c3", "c1"]
    assert set(helper) == PERSON_KEYS | {"cats"}
    # HELPER and THIRD are not each other's friends: each sees ADMIN only.
    assert {p["username"] for p in friends_of(HELPER)["people"]} == {
        names[HELPER],
        names[ADMIN],
    }
    assert call("GET", "/api/v1/friends", email=ADMIN, query={"period": "week"})[0] == 400


def test_a_friend_is_marked_in_the_feed_and_sees_roughly_where(people):
    make_post()  # HELPER's, at the library
    published(people["social"], POST)

    def card(who):
        return call("GET", "/api/v1/feed", email=who)[1]["cards"][0]

    assert (card(ADMIN)["author"]["friend"], card(ADMIN)["region"]) == ("no", None)
    accept(people, of=HELPER, by=ADMIN)
    assert (card(ADMIN)["author"]["friend"], card(ADMIN)["region"]) == ("yes", "library")
    # Someone else still does not, and the author always did.
    assert (card(THIRD)["author"]["friend"], card(THIRD)["region"]) == ("no", None)
    assert card(HELPER)["region"] == "library"


def test_a_persons_page_and_their_posts(people):
    make_post()
    helper = people["me"][HELPER]["userId"]
    counted(people, HELPER, "STATS#ALL", 7)
    met(people, HELPER, CAT, "2026-11-12")
    status, body = call("GET", f"/api/v1/users/{helper}", email=ADMIN)
    assert status == 200
    theirs = body["person"]
    assert set(theirs) == PERSON_KEYS | {"cats"}
    assert (theirs["username"], theirs["found"], theirs["friend"], theirs["cats"]) == (
        people["me"][HELPER]["username"],
        7,
        "no",
        [CAT],
    )
    assert HELPER not in str(body)  # never their email

    # A post still being checked is its author's alone.
    assert call("GET", f"/api/v1/users/{helper}/posts", email=ADMIN)[1]["cards"] == []
    published(people["social"], POST)
    cards = call("GET", f"/api/v1/users/{helper}/posts", email=ADMIN)[1]["cards"]
    assert [c["postId"] for c in cards] == [POST]
    assert "state" not in cards[0]

    # Yourself, and nobody.
    mine = call("GET", f"/api/v1/users/{helper}", email=HELPER)[1]["person"]
    assert (mine["me"], mine["friend"]) == (True, "no")
    for path in ("/api/v1/users/01JD0000000000000000000XXX", "/api/v1/users/01JD0000000000000000000XXX/posts"):
        status, body = call("GET", path, email=ADMIN)
        assert (status, body["code"]) == (404, "gone")


# ------------------------------------------------- friends' votes in the feed


def suggest(name, email, cat=CAT):
    status, body = call("POST", f"/api/v1/cats/{cat}/names", {"name": name}, email=email)
    assert status == 200, body
    return body


def vote(key, email, cat=CAT):
    status, body = call("PUT", f"/api/v1/cats/{cat}/vote", {"nameKey": key}, email=email)
    assert status == 200, body
    return body


def feed(who, cursor=None):
    status, body = call(
        "GET", "/api/v1/feed", email=who, query={"cursor": cursor} if cursor else None
    )
    assert status == 200, body
    return body


def kinds(body):
    return [c.get("type", "post") for c in body["cards"]]


@pytest.fixture
def voting(people):
    from tests.events.stream import Stream

    people["stream"] = Stream(people["social"])
    accept(people, of=ADMIN, by=HELPER)
    accept(people, of=ADMIN, by=THIRD)  # HELPER and THIRD are not friends
    return people


def test_a_friends_vote_is_a_card_and_a_strangers_is_not(voting):
    suggest("Mango", HELPER)
    # Until it has been checked the name is its author's alone: no card.
    assert feed(ADMIN)["cards"] == []
    voting["stream"].settle()

    (card,) = feed(ADMIN)["cards"]
    names = {who: voting["me"][who]["username"] for who in PEOPLE}
    assert (card["type"], card["cardId"], card["name"]) == ("vote", f"vote-{CAT}", "Mango")
    # The poll leads, so the cat is already called by the new name.
    assert card["cat"] == {"catId": CAT, "name": "Mango", "cover": None}
    assert [p["username"] for p in card["voters"]] == [names[HELPER]]
    assert set(card["voters"][0]) == {"userId", "username", "displayName", "avatar"}
    assert card["friendsVoted"] == 1
    poll = card["poll"]
    assert (poll["total"], poll["myVote"]) == (1, None)
    by_name = {o["name"]: o for o in poll["options"]}
    assert [p["username"] for p in by_name["Mango"]["friends"]] == [names[HELPER]]
    assert by_name["Simba"]["friends"] == []  # the admins' name, still votable
    assert HELPER not in str(card)  # never an email

    # Your own vote is not news to you, and a stranger's is not shown.
    assert feed(HELPER)["cards"] == []
    assert feed(THIRD)["cards"] == []


def test_two_friends_on_one_cat_are_one_card_at_the_newest_vote(voting):
    suggest("Mango", HELPER)
    voting["stream"].settle()
    make_post()  # HELPER's post, between the two votes
    published(voting["social"], POST)
    vote("mango", THIRD)
    voting["stream"].settle()

    body = feed(ADMIN)
    assert kinds(body) == ["vote", "post"]  # one card, where the newest vote is
    card = body["cards"][0]
    names = {who: voting["me"][who]["username"] for who in PEOPLE}
    assert [p["username"] for p in card["voters"]] == [names[THIRD], names[HELPER]]
    assert (card["friendsVoted"], card["poll"]["total"]) == (2, 2)

    # They disagree: the card says what the newest vote says, and each
    # name carries the friends who chose it.
    vote("simba", HELPER)
    card = feed(ADMIN)["cards"][0]
    assert (card["name"], [p["username"] for p in card["voters"]]) == (
        "Simba",
        [names[HELPER]],
    )
    by_name = {o["name"]: o for o in card["poll"]["options"]}
    assert [p["username"] for p in by_name["Mango"]["friends"]] == [names[THIRD]]
    assert card["friendsVoted"] == 2

    # The caller votes from the card: still a card, now with their choice.
    vote("mango", ADMIN)
    card = feed(ADMIN)["cards"][0]
    assert card["poll"]["myVote"] == "mango" and card["poll"]["total"] == 3


def test_a_vote_taken_back_or_a_friend_removed_takes_the_card_away(voting):
    suggest("Mango", HELPER)
    voting["stream"].settle()
    vote("mango", THIRD)
    assert kinds(feed(ADMIN)) == ["vote"]

    call("DELETE", f"/api/v1/cats/{CAT}/vote", email=THIRD)
    card = feed(ADMIN)["cards"][0]
    assert card["friendsVoted"] == 1

    helper = voting["me"][HELPER]["userId"]
    call("DELETE", f"/api/v1/friends/{helper}", email=ADMIN)
    assert feed(ADMIN)["cards"] == []


def test_a_cats_card_is_not_repeated_on_the_next_page(voting, monkeypatch):
    suggest("Mango", HELPER)
    voting["stream"].settle()
    make_post()
    published(voting["social"], POST)
    vote("mango", THIRD)  # newer than the post; HELPER's vote is older
    monkeypatch.setattr(handler, "FEED_PAGE", 2)

    first = feed(ADMIN)
    assert kinds(first) == ["vote", "post"]
    assert first["cards"][0]["friendsVoted"] == 2  # both, though one is further on
    rest = feed(ADMIN, first["cursor"])
    assert rest["cards"] == []  # HELPER's older vote is already in that card
    assert "cursor" not in rest
