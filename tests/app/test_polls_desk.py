"""The desk's half of the name poll (B4b): an admin removes a name, and its
votes go with it; an admin locks the name the app shows, and the lock wins
over the poll (D6).

Runs the desk's API, the member API and the events Lambda together, with
tests/events/stream.py standing in for the table's stream.
"""

import pytest

import tests.admin.test_handler  # the env the desk's API reads, set at import
from admin import handler as desk
from app import handler
from common import tables

from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)
from .test_polls import (  # noqa: F401  (the fixture)
    NAMED,
    NAMELESS,
    THIRD,
    consistent,
    counts,
    names,
    poll,
    shown_name,
    suggest,
    vote,
)


def desk_call(method, path, body=None, email=ADMIN):
    return tests.admin.test_handler._call(method, path, body, email)


@pytest.fixture
def desk_poll(poll, aws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(desk, "table", aws["data"])
    monkeypatch.setattr(desk, "social_table", aws["social"])
    monkeypatch.setattr(desk, "SOCIAL", True)
    return poll


def desk_names(cat=NAMELESS):
    status, body = desk_call("GET", f"/api/cats/{cat}/names")
    assert status == 200, body
    return body


def remove(key, cat=NAMELESS, email=ADMIN):
    return desk_call("POST", f"/api/cats/{cat}/names/remove", {"nameKey": key}, email)


def lock(name, cat=NAMELESS, email=ADMIN):
    return desk_call("POST", f"/api/cats/{cat}/name-lock", {"name": name}, email)


def three_votes(stream):
    """Mango with two votes and the lead, Pita with one."""
    suggest("Mango")
    suggest("Pita", email=HELPER)
    stream.settle()
    vote("mango", email=THIRD)
    stream.settle()


def test_the_desk_sees_every_option_and_who_suggested_it(desk_poll):
    three_votes(desk_poll["stream"])
    suggest("Waiting", email=THIRD)  # not yet checked: the desk sees it anyway
    body = desk_names()
    assert (body["shown"], body["source"], body["locked"]) == ("Mango", "poll", None)
    assert [
        (o["name"], o["votes"], o["status"], o["leading"], o["suggestedBy"])
        for o in body["options"]
    ] == [
        ("Mango", 1, "live", True, username(ADMIN)),
        ("Pita", 1, "live", False, username(HELPER)),
        ("Waiting", 1, "pending", False, username(THIRD)),
    ]
    # No email of a member in it, only the public username.
    assert "@" not in str(body["options"])


def test_a_removed_name_takes_its_votes_with_it(desk_poll):
    three_votes(desk_poll["stream"])
    assert shown_name() == ("Mango", "poll")

    status, body = remove("mango")
    assert status == 200
    # At once, before the events Lambda has run: out of the poll for
    # everyone, and the desk already names the next leader.
    assert (body["shown"], body["source"]) == ("Pita", "poll")
    assert counts(names(email=THIRD)) == {"Pita": 1}
    assert names(email=THIRD)["myVote"] is None

    desk_poll["stream"].settle()
    table = desk_poll["social"]
    option = tables.get_one(table, f"CAT#{NAMELESS}", "NAME#mango")
    assert (option["status"], int(option["votes"]), option["removedBy"]) == (
        "removed",
        0,
        ADMIN,
    )
    # Its two votes are gone, the total is Pita's one, and the cat is Pita.
    assert consistent(table)["voteTotal"] == 1
    assert shown_name() == ("Pita", "poll")
    assert names()["total"] == 1

    # Those who voted for it may vote again; the name itself stays out.
    status, body = vote("pita", email=THIRD)
    assert status == 200 and counts(body) == {"Pita": 2}
    status, body = suggest("MANGO", email=THIRD)
    assert (status, body["code"]) == (409, "not_accepted")
    assert vote("mango", email=THIRD)[0] == 409
    desk_poll["stream"].settle()
    assert consistent(table)["voteTotal"] == 2


def test_removing_twice_is_removing_once(desk_poll):
    three_votes(desk_poll["stream"])
    assert remove("mango")[0] == 200
    assert remove("mango")[0] == 200
    desk_poll["stream"].settle()
    assert remove("mango")[0] == 200
    desk_poll["stream"].settle()
    assert consistent(desk_poll["social"])["voteTotal"] == 1
    body = desk_names()
    assert [(o["name"], o["status"], o["votes"]) for o in body["options"]] == [
        ("Pita", "live", 1),
        ("Mango", "removed", 0),
    ]


def test_a_vote_leaving_a_removed_name_is_counted_once(desk_poll):
    """The race the removal is built for: the name is removed, and before
    the events Lambda has taken its votes away one of its voters votes for
    another name. The total must lose both of the removed name's votes and
    gain that one."""
    three_votes(desk_poll["stream"])
    remove("mango")
    status, body = vote("pita", email=THIRD)  # was Mango's; the sweep has not run
    assert status == 200 and counts(body) == {"Pita": 2}
    desk_poll["stream"].settle()
    table = desk_poll["social"]
    assert consistent(table)["voteTotal"] == 2
    # The vote that moved was not deleted with the removed name's.
    assert tables.get_one(table, f"CAT#{NAMELESS}", f"VOTE#{user_id(THIRD)}")[
        "nameKey"
    ] == "pita"
    assert shown_name() == ("Pita", "poll")


def user_id(email):
    return call("GET", "/api/v1/me", email=email)[1]["userId"]


def username(email):
    return call("GET", "/api/v1/me", email=email)[1]["username"]


def test_a_name_removed_before_it_was_checked_never_joins(desk_poll):
    suggest("Mango")  # pending: the events Lambda has not seen it
    assert remove("mango")[0] == 200
    desk_poll["stream"].settle()
    table = desk_poll["social"]
    assert tables.get_one(table, f"CAT#{NAMELESS}", "NAME#mango")["status"] == "removed"
    assert consistent(table).get("voteTotal", 0) == 0
    body = names()
    assert (body["options"], body["total"], body["myVote"]) == ([], 0, None)
    assert shown_name() == (None, "none")


def test_a_locked_name_wins_over_the_poll(desk_poll):
    three_votes(desk_poll["stream"])
    status, body = lock("  Sir  Whiskers ")
    assert status == 200
    assert (body["shown"], body["source"], body["locked"], body["lockedBy"]) == (
        "Sir Whiskers",
        "locked",
        "Sir Whiskers",
        ADMIN,
    )
    # Everywhere a member reads the cat: its page, the poll, the list.
    assert shown_name(email=HELPER) == ("Sir Whiskers", "admin")
    poll_now = names(email=HELPER)
    assert (poll_now["name"], poll_now["locked"]) == ("Sir Whiskers", "Sir Whiskers")
    cats = call("GET", "/api/v1/cats", email=HELPER)[1]["cats"]
    assert next(c for c in cats if c["catId"] == NAMELESS)["name"] == "Sir Whiskers"

    # The poll goes on underneath, and changes nothing that is shown.
    assert vote("pita", email=THIRD)[0] == 200
    assert vote("pita")[0] == 200
    desk_poll["stream"].settle()
    assert shown_name() == ("Sir Whiskers", "admin")
    assert consistent(desk_poll["social"])["voteTotal"] == 3

    # Unlocked, the name is the poll's again, as it stands now.
    status, body = lock(None)
    assert (status, body["shown"], body["source"], body["locked"]) == (
        200,
        "Pita",
        "poll",
        None,
    )
    assert shown_name(email=HELPER) == ("Pita", "poll")


def test_a_cat_nobody_voted_on_can_be_locked(desk_poll):
    assert lock("Mitzi", cat=NAMED)[0] == 200
    assert shown_name(cat=NAMED) == ("Mitzi", "admin")
    assert lock(None, cat=NAMED)[0] == 200
    assert shown_name(cat=NAMED) == ("Simba", "admin")


def test_what_the_desk_refuses(desk_poll, monkeypatch):
    three_votes(desk_poll["stream"])
    # Only admins.
    for method, path, body in (
        ("GET", f"/api/cats/{NAMELESS}/names", None),
        ("POST", f"/api/cats/{NAMELESS}/names/remove", {"nameKey": "mango"}),
        ("POST", f"/api/cats/{NAMELESS}/name-lock", {"name": "Mine"}),
    ):
        assert desk_call(method, path, body, HELPER)[0] == 403
    assert counts(names()) == {"Mango": 2, "Pita": 1}
    assert names()["locked"] is None

    assert remove("nobody-said-this")[0] == 404
    assert remove("")[0] == 400
    assert remove("mango", cat="01JD0000000000000000000XXX")[0] == 404
    assert lock("x" * 81)[0] == 400
    assert lock("   ")[0] == 400

    # With the app closed on the account there is no poll to manage.
    monkeypatch.setattr(desk, "SOCIAL", False)
    assert desk_call("GET", f"/api/cats/{NAMELESS}/names")[0] == 404
    assert remove("mango")[0] == 404
    assert lock("Mine")[0] == 404
    assert handler  # the member API is untouched by the desk's flag
