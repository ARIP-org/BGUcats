"""Push (B9, D18): a phone registers, and four things are told to it.

Runs the member API and the events Lambda together, with a list where
Apple would be (`events._deliver`): what would have been sent, to which
device. The sending itself is tests/events/test_push.py.
"""

import pytest

from app import handler
from events import handler as events
from tests.events.stream import Stream

from .test_friends import (  # noqa: F401  (the fixtures)
    PEOPLE,
    THIRD,
    accept,
    people,
    suggest,
    vote,
)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401
from .test_posts import CAT, POST, campus, make_post  # noqa: F401

TOKEN = "ab" * 32
PHONE = "phone-0001"


@pytest.fixture
def world(people, monkeypatch):  # noqa: F811
    """Push on, every person with one phone, and Apple a list."""
    monkeypatch.setattr(events, "PUSH", True)
    sent = []

    def deliver(device, payload, collapse):
        sent.append({"to": device["userId"], "device": device["deviceId"], "key": collapse, **payload})
        return people.get("apple", {}).get(device["apnsToken"], "sent")

    monkeypatch.setattr(events, "_deliver", deliver)
    for n, who in enumerate(PEOPLE):
        register(who, token=f"{n:02x}" * 32)
    people["stream"] = Stream(people["social"])
    people["sent"] = sent
    people["id"] = {who: people["me"][who]["userId"] for who in PEOPLE}
    return people


def register(who, device=PHONE, token=TOKEN, environment="production"):
    return call(
        "PUT",
        f"/api/v1/me/devices/{device}",
        {"apnsToken": token, "environment": environment},
        email=who,
    )


def devices(world, who):
    user = world["me"][who]["userId"]
    return sorted(
        (i["deviceId"], i["apnsToken"], i["environment"])
        for i in world["social"].scan()["Items"]
        if i["PK"] == f"USER#{user}" and i["SK"].startswith("DEVICE#")
    )


def told(world):
    """(who, what it said), in the order sent."""
    names = {world["id"][who]: who for who in PEOPLE}
    return [(names[p["to"]], p["aps"]["alert"]["body"]) for p in world["sent"]]


# ---------------------------------------------------------------- a phone


def test_a_phone_registers_renews_and_leaves(world):
    status, body = register(HELPER, token="cd" * 32, environment="development")
    assert status == 200
    assert (body["deviceId"], body["environment"]) == (PHONE, "development")
    # The same phone again is the same device, with its newest token.
    assert devices(world, HELPER) == [(PHONE, "cd" * 32, "development")]
    assert register(HELPER, device="ipad-00001")[0] == 200
    assert len(devices(world, HELPER)) == 2

    status, body = call("DELETE", f"/api/v1/me/devices/{PHONE}", email=HELPER)
    assert (status, body) == (200, {"deviceId": PHONE, "removed": True})
    assert devices(world, HELPER) == [("ipad-00001", TOKEN, "production")]
    # Removing what is not there says the same; somebody else's is untouched.
    assert call("DELETE", f"/api/v1/me/devices/{PHONE}", email=HELPER)[0] == 200
    assert len(devices(world, ADMIN)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"apnsToken": "not hex", "environment": "production"},
        {"apnsToken": "AB" * 32, "environment": "production"},
        {"apnsToken": "ab" * 8, "environment": "production"},
        {"apnsToken": TOKEN, "environment": "sandbox"},
        {"environment": "production"},
    ],
)
def test_a_registration_that_is_not_one_is_refused(world, body):
    status, answer = call("PUT", f"/api/v1/me/devices/{PHONE}", body, email=HELPER)
    assert status == 400, answer


def test_a_sixth_phone_pushes_out_the_one_heard_from_longest_ago(world, monkeypatch):
    # Later than the phone the fixture registered, one second apart.
    clock = iter(f"2031-01-01T10:00:0{n}.000000Z" for n in range(9))
    monkeypatch.setattr(handler.api, "now_iso", lambda: next(clock))
    for n in range(handler.MAX_DEVICES + 1):
        assert register(HELPER, device=f"phone-new{n}")[0] == 200
    kept = [d[0] for d in devices(world, HELPER)]
    assert kept == [f"phone-new{n}" for n in range(1, handler.MAX_DEVICES + 1)]


def test_no_route_gives_a_token_back(world):
    for path in ("/api/v1/me", "/api/v1/friends", f"/api/v1/users/{world['id'][ADMIN]}"):
        assert "apnsToken" not in str(call("GET", path, email=HELPER)[1])
        assert "00" * 32 not in str(call("GET", path, email=HELPER)[1])


# ------------------------------------------------------- what is told, to whom


def test_a_friends_post_is_told_to_friends_and_says_nothing_they_wrote(world):
    accept(world, of=HELPER, by=ADMIN)
    world["stream"].settle()
    world["sent"].clear()

    assert make_post(text="A secret the lock screen must not show")[0] == 200
    world["stream"].settle()
    name = world["me"][HELPER]["displayName"] or world["me"][HELPER]["username"]
    # The friend, once; not the author, and not someone who is no friend.
    assert told(world) == [(ADMIN, f"{name} posted a cat")]
    (push,) = world["sent"]
    assert push["opens"] == {"kind": "post", "id": POST}
    assert push["aps"]["alert"]["title"] == "BGU Cats"
    assert "secret" not in str(push)


def test_the_one_whose_invite_it_was_is_told_and_the_one_who_joined_is_not(world):
    assert accept(world, of=ADMIN, by=HELPER)[0] == 200
    world["stream"].settle()
    name = world["me"][HELPER]["displayName"] or world["me"][HELPER]["username"]
    assert told(world) == [(ADMIN, f"{name} joined with your invite")]
    assert world["sent"][0]["opens"] == {"kind": "person", "id": world["id"][HELPER]}
    # Opening the link again makes nobody friends again and tells nobody.
    accept(world, of=ADMIN, by=HELPER)
    world["stream"].settle()
    assert len(world["sent"]) == 1


def test_a_name_that_takes_the_lead_is_told_to_whoever_suggested_it(world):
    def key_of(name, answer):
        return next(o["nameKey"] for o in answer["options"] if o["name"] == name)

    # The first name leads from its author's own vote: nobody is told that.
    suggest("Mango", ADMIN)
    world["stream"].settle()
    # A second name ties with it on its author's vote; the earlier one leads.
    hummus = key_of("Hummus", suggest("Hummus", HELPER))
    world["stream"].settle()
    assert told(world) == []
    # Somebody else votes for it: it takes the lead, and its author is told.
    vote(hummus, THIRD)
    world["stream"].settle()
    assert told(world) == [(HELPER, "A name you suggested is in the lead")]
    assert world["sent"][0]["opens"] == {"kind": "cat", "id": CAT}
    assert "Hummus" not in str(world["sent"][0])
    # Another vote for it changes nothing about who leads: not told again.
    vote(hummus, ADMIN)
    world["stream"].settle()
    assert len(world["sent"]) == 1


# ----------------------------------------------------------- when it is not


def test_nothing_is_sent_with_push_off(world, monkeypatch):
    monkeypatch.setattr(events, "PUSH", False)
    accept(world, of=ADMIN, by=HELPER)
    make_post()
    world["stream"].settle()
    assert world["sent"] == []


def test_someone_who_turned_notifications_off_is_not_told(world):
    assert call("PATCH", "/api/v1/me", {"notifications": False}, email=ADMIN)[0] == 200
    accept(world, of=ADMIN, by=HELPER)
    world["stream"].settle()
    assert world["sent"] == []


def test_a_change_delivered_twice_is_told_once(world):
    user = world["id"][ADMIN]
    assert events.notify(user, "nameLeads", "lead:C1:mango") is True
    assert events.notify(user, "nameLeads", "lead:C1:mango") is False
    assert len(world["sent"]) == 1


def test_no_more_than_the_days_cap(world):
    user = world["id"][ADMIN]
    for n in range(events.PUSH_DAILY_CAP + 3):
        events.notify(user, "friendPosted", f"post:P{n}", name="Maya")
    assert len(world["sent"]) == events.PUSH_DAILY_CAP
    # The day's count is its own item, which the table forgets by itself.
    (count,) = [i for i in world["social"].scan()["Items"] if i["SK"].startswith("PUSHED#")]
    assert count["count"] == events.PUSH_DAILY_CAP
    assert count["expiresAt"] > 1_790_000_000
    # Somebody else's day is their own.
    assert events.notify(world["id"][HELPER], "friendPosted", "post:P0", name="Maya") is True


def test_a_device_apple_will_never_reach_is_forgotten(world):
    register(ADMIN, device="old-phone-1", token="ee" * 32)
    world["apple"] = {"ee" * 32: "gone"}
    assert events.notify(world["id"][ADMIN], "nameLeads", "lead:C1:mango") is True
    assert [d[0] for d in devices(world, ADMIN)] == [PHONE]
    assert len(world["sent"]) == 2  # both were tried


def test_a_notification_is_in_its_readers_language(world):
    world["social"].update_item(
        Key={"PK": f"USER#{world['id'][ADMIN]}", "SK": "PROFILE"},
        UpdateExpression="SET #l = :he",
        ExpressionAttributeNames={"#l": "language"},
        ExpressionAttributeValues={":he": "he"},
    )
    events.notify(world["id"][ADMIN], "friendPosted", "post:P1", name="Maya")
    body = world["sent"][0]["aps"]["alert"]["body"]
    assert body.startswith("Maya ") and "posted" not in body


def test_a_failure_while_telling_never_fails_the_change(world, monkeypatch):
    def broken(*_):
        raise RuntimeError("Apple is on fire")

    monkeypatch.setattr(events, "_deliver", broken)
    accept(world, of=ADMIN, by=HELPER)
    # settle() asserts the Lambda reported no failed record.
    world["stream"].settle()
    assert call("GET", "/api/v1/friends", email=ADMIN)[1]["people"]


# ------------------------------------------------------------ a whole day


def test_a_seeded_day_sends_exactly_these_and_nothing_anyone_wrote(world):
    """The milestone's own test: everything that can cause a notification,
    in one day, and the list of what went out."""
    accept(world, of=ADMIN, by=HELPER)  # ADMIN is told
    accept(world, of=HELPER, by=THIRD)  # HELPER is told
    world["stream"].settle()
    make_post(text="Words of mine that stay in the app")  # ADMIN and THIRD are told
    world["stream"].settle()
    suggest("Shawarma", HELPER)  # leads from the start: nobody is told
    world["stream"].settle()
    option = suggest("Falafel", ADMIN)
    world["stream"].settle()
    key = next(o["nameKey"] for o in option["options"] if o["name"] == "Falafel")
    vote(key, THIRD)  # takes the lead: ADMIN is told
    world["stream"].settle()

    name = {who: world["me"][who]["displayName"] or world["me"][who]["username"] for who in PEOPLE}
    assert sorted(told(world)) == sorted(
        [
            (ADMIN, f"{name[HELPER]} joined with your invite"),
            (HELPER, f"{name[THIRD]} joined with your invite"),
            (ADMIN, f"{name[HELPER]} posted a cat"),
            (THIRD, f"{name[HELPER]} posted a cat"),
            (ADMIN, "A name you suggested is in the lead"),
        ]
    )
    everything = str(world["sent"])
    for written in ("Words of mine", "Shawarma", "Falafel", "example.com"):
        assert written not in everything
