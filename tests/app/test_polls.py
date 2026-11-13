"""A cat's name poll (B4): suggesting, voting, taking a vote back, and the
leader the events Lambda keeps. Three members and two cats: Simba, whom the
admins named, and one with no name yet."""

import pytest

from app import handler
from common import tables
from events import handler as events
from tests.events.stream import Stream

from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)

THIRD = "third@example.com"
NAMED = "01JD0000000000000000000CA1"
NAMELESS = "01JD0000000000000000000CA2"
TERMS = {"version": "2026-11"}
PEOPLE = (ADMIN, HELPER, THIRD)


@pytest.fixture
def poll(aws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(events, "social_table", aws["social"])
    aws["data"].put_item(
        Item={"PK": f"ADMIN#{THIRD}", "SK": "META", "email": THIRD, "role": "user"}
    )
    for cat_id, name in ((NAMED, "Simba"), (NAMELESS, None)):
        item = {
            "PK": f"CAT#{cat_id}",
            "SK": "META",
            "catId": cat_id,
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": "2026-10-01T00:00:00Z",
        }
        if name:
            item["name"] = name
        aws["data"].put_item(Item=item)
    for who in PEOPLE:
        call("GET", "/api/v1/me", email=who)
        call("POST", "/api/v1/me/terms", TERMS, email=who)
    return {"social": aws["social"], "stream": Stream(aws["social"])}


def names(cat=NAMELESS, email=ADMIN):
    status, body = call("GET", f"/api/v1/cats/{cat}/names", email=email)
    assert status == 200, body
    return body


def suggest(name, cat=NAMELESS, email=ADMIN):
    return call("POST", f"/api/v1/cats/{cat}/names", {"name": name}, email=email)


def vote(key, cat=NAMELESS, email=ADMIN):
    return call("PUT", f"/api/v1/cats/{cat}/vote", {"nameKey": key}, email=email)


def counts(body):
    return {o["name"]: o["votes"] for o in body["options"]}


def consistent(table, cat=NAMELESS):
    """The invariant: the cat's total is the votes on its live options, and
    every option's count is the vote items that name it."""
    items = table.query(
        KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": f"CAT#{cat}"}
    )["Items"]
    options = {i["nameKey"]: i for i in items if i["SK"].startswith("NAME#")}
    cast = [i["nameKey"] for i in items if i["SK"].startswith("VOTE#")]
    public = next((i for i in items if i["SK"] == "PUBLIC"), {})
    for key, option in options.items():
        assert int(option["votes"]) == cast.count(key), key
    live = sum(int(o["votes"]) for o in options.values() if o["status"] == "live")
    assert int(public.get("voteTotal", 0)) == live
    return public


def shown_name(cat=NAMELESS, email=ADMIN):
    _, body = call("GET", f"/api/v1/cats/{cat}", email=email)
    return body["cat"]["name"], body["cat"]["nameSource"]


def test_a_suggestion_is_its_authors_alone_until_it_has_been_checked(poll):
    status, mine = suggest("  Mango ")
    assert status == 200
    # Cleaned, voted for by its author, and marked as waiting.
    assert mine["options"] == [
        {"nameKey": "mango", "name": "Mango", "votes": 1, "leading": False, "mine": True, "pending": True}
    ]
    assert mine["mySuggestion"] == {"name": "Mango", "status": "pending"}
    # Nobody else sees it, and it is not in the total or the cat's name.
    assert (mine["name"], mine["nameSource"]) == (None, "none")
    theirs = names(email=HELPER)
    assert (theirs["options"], theirs["total"], theirs["mySuggestion"]) == ([], 0, None)
    assert shown_name() == (None, "none")
    consistent(poll["social"])

    assert poll["stream"].settle() > 0
    theirs = names(email=HELPER)
    assert theirs["options"] == [
        {"nameKey": "mango", "name": "Mango", "votes": 1, "leading": True, "mine": False}
    ]
    assert theirs["total"] == 1
    assert names()["mySuggestion"] is None  # it is simply an option now
    # The poll leads: the cat has its name (D6).
    assert shown_name(email=HELPER) == ("Mango", "poll")
    consistent(poll["social"])


def test_the_same_name_in_other_capitals_is_a_vote_for_it(poll):
    suggest("Mango")
    poll["stream"].settle()
    status, body = suggest("mango ", email=HELPER)
    assert status == 200
    assert counts(body) == {"Mango": 2}  # one option, the first spelling
    status, body = suggest("MANGO", email=THIRD)
    assert counts(body) == {"Mango": 3}
    assert consistent(poll["social"])["voteTotal"] == 3


def test_a_vote_moves_and_the_leader_follows(poll):
    suggest("Mango")
    suggest("Pita", email=HELPER)
    poll["stream"].settle()
    vote("mango", email=THIRD)
    poll["stream"].settle()
    assert counts(names()) == {"Mango": 2, "Pita": 1}
    assert shown_name() == ("Mango", "poll")

    # Two people change their minds: one vote each, never two.
    for who in (ADMIN, THIRD):
        status, body = vote("pita", email=who)
        assert status == 200
    assert counts(body) == {"Pita": 3, "Mango": 0}
    assert body["myVote"] == "pita" and body["total"] == 3
    # The answer already names the new leader, before the events Lambda
    # has written it for everyone's lists.
    assert (body["name"], body["nameSource"]) == ("Pita", "poll")
    assert shown_name() == ("Mango", "poll")
    # Voting for the same name again changes nothing.
    assert counts(vote("pita", email=THIRD)[1]) == {"Pita": 3, "Mango": 0}
    poll["stream"].settle()
    assert shown_name() == ("Pita", "poll")
    assert [o["leading"] for o in names()["options"]] == [True, False]
    consistent(poll["social"])


def test_a_tie_goes_to_the_name_suggested_first(poll):
    suggest("Mango")
    poll["stream"].settle()
    suggest("Pita", email=HELPER)
    poll["stream"].settle()
    assert shown_name() == ("Mango", "poll")


def test_a_vote_taken_back_is_gone_and_a_poll_with_none_names_nothing(poll):
    suggest("Mango")
    poll["stream"].settle()
    status, body = call("DELETE", f"/api/v1/cats/{NAMELESS}/vote")
    assert status == 200
    assert (counts(body), body["total"], body["myVote"]) == ({"Mango": 0}, 0, None)
    # Taking back what is not there is the same answer.
    assert call("DELETE", f"/api/v1/cats/{NAMELESS}/vote")[0] == 200
    poll["stream"].settle()
    assert shown_name() == (None, "none")
    assert "leaderKey" not in consistent(poll["social"])


def test_the_admins_name_stands_in_the_poll_and_can_be_voted_to_stay(poll):
    """Simba was named by the admins. The name is an option from the start,
    with no votes, so one suggestion does not simply erase it."""
    assert names(NAMED)["options"] == [
        {"nameKey": "simba", "name": "Simba", "votes": 0, "leading": False, "mine": False}
    ]
    assert shown_name(NAMED) == ("Simba", "admin")
    suggest("Mango", cat=NAMED, email=HELPER)
    poll["stream"].settle()
    assert shown_name(NAMED) == ("Mango", "poll")

    for who in (ADMIN, THIRD):
        status, body = vote("simba", cat=NAMED, email=who)
        assert status == 200
    assert counts(body) == {"Simba": 2, "Mango": 1}
    poll["stream"].settle()
    assert shown_name(NAMED) == ("Simba", "poll")
    consistent(poll["social"], NAMED)
    # Typed as a suggestion, it is the same option, live at once.
    call("DELETE", f"/api/v1/cats/{NAMED}/vote", email=THIRD)
    assert counts(suggest("SIMBA", cat=NAMED, email=THIRD)[1]) == {"Simba": 2, "Mango": 1}


def test_a_name_going_live_under_a_vote_is_counted_once(poll, monkeypatch):
    """The author moves their vote off their pending name at the moment the
    events Lambda publishes it. The vote's write is refused, because the
    option is no longer as it was read, and tried again against the truth."""
    suggest("Pita", email=HELPER)
    poll["stream"].settle()
    suggest("Mango")  # pending, with its author's vote

    client = poll["social"].meta.client
    real = client.transact_write_items
    state = {"published": False}

    def publish_first(**kwargs):
        if not state["published"]:
            state["published"] = True
            poll["stream"].settle()  # Mango goes live with its one vote
        return real(**kwargs)

    monkeypatch.setattr(client, "transact_write_items", publish_first)
    status, body = vote("pita")
    assert status == 200
    assert counts(body) == {"Pita": 2, "Mango": 0}
    assert consistent(poll["social"])["voteTotal"] == 2


def test_two_taps_at_once_are_one_vote(poll, monkeypatch):
    suggest("Mango", email=HELPER)
    suggest("Pita", email=THIRD)
    poll["stream"].settle()
    client = poll["social"].meta.client
    real = client.transact_write_items
    state = {"raced": False}

    def other_tap_first(**kwargs):
        if not state["raced"]:
            state["raced"] = True
            assert vote("mango")[0] == 200  # the same person's other tap lands
        return real(**kwargs)

    monkeypatch.setattr(client, "transact_write_items", other_tap_first)
    status, body = vote("mango")
    assert status == 200
    assert counts(body) == {"Mango": 2, "Pita": 1}
    consistent(poll["social"])


def test_every_order_of_votes_keeps_the_counts_true(poll):
    for name, who in (("Mango", ADMIN), ("Pita", HELPER), ("Shawarma", THIRD)):
        suggest(name, email=who)
    poll["stream"].settle()
    moves = [
        (ADMIN, "pita"), (HELPER, "mango"), (THIRD, None), (ADMIN, "shawarma"),
        (THIRD, "pita"), (HELPER, None), (ADMIN, None), (HELPER, "pita"), (THIRD, "mango"),
    ]
    for who, key in moves:
        if key:
            assert vote(key, email=who)[0] == 200
        else:
            assert call("DELETE", f"/api/v1/cats/{NAMELESS}/vote", email=who)[0] == 200
        consistent(poll["social"])
    poll["stream"].settle()
    assert counts(names()) == {"Pita": 1, "Mango": 1, "Shawarma": 0}
    assert shown_name() == ("Mango", "poll")  # the tie goes to the earlier name


def test_a_name_or_a_cat_that_is_not_there(poll):
    assert vote("nobody")[0] == 404
    assert (vote("")[0], vote(None)[0]) == (400, 400)
    missing = "01JD0000000000000000000ZZZ"
    assert call("GET", f"/api/v1/cats/{missing}/names")[0] == 404
    assert suggest("Mango", cat=missing)[0] == 404
    for bad in ("", "   ", "x" * 25, 7):
        assert suggest(bad)[0] == 400
    assert tables.query_all(
        poll["social"],
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"CAT#{NAMELESS}"},
    ) == []


def test_someone_elses_pending_name_cannot_be_voted_for(poll):
    suggest("Mango")
    status, body = vote("mango", email=HELPER)
    assert (status, body["code"]) == (409, "try_again")
    status, body = suggest("mango", email=HELPER)
    assert (status, body["code"]) == (409, "try_again")
    consistent(poll["social"])


def test_three_suggestions_a_cat_a_day_and_the_terms_first(poll, monkeypatch):
    for name in ("One", "Two", "Three"):
        assert suggest(name)[0] == 200
    status, body = suggest("Four")
    assert (status, body["code"]) == (429, "rate_limited")
    assert suggest("Four", cat=NAMED)[0] == 200  # another cat, another count
    monkeypatch.setattr(handler, "TERMS_VERSION", "2027-01")
    for answer in (suggest("Five", email=HELPER), vote("one", email=HELPER)):
        assert (answer[0], answer[1]["code"]) == (403, "terms_required")
