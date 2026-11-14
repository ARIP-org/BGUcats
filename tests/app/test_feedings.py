"""Feedings (B7c, D10): "I fed this cat", the cat's "last fed", the points
for two a day, Snack Giver, and the desk's remove.

Runs the desk's API, the member API and the events Lambda together.
"""

import pytest
from boto3.dynamodb.types import TypeSerializer

from app import handler
from common import regions
from events import handler as events

from .test_encounters import (  # noqa: F401  (the fixture)
    BAMBA,
    SIMBA,
    campus,
    desk_call,
)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)

HOUR = 3600
# Noon in Israel on 12 November 2026, as the phone's clock counts.
NOON = 1794477600


@pytest.fixture
def world(campus, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        handler, "FLAGS", {"social": True, "gpa": True, "feeding": True}
    )
    clock = {"now": NOON}
    monkeypatch.setattr(handler, "_clock", lambda: clock["now"])
    campus["clock"] = clock
    return campus


def fid(n):
    return f"01JF{n:022d}"


def feed(n, cat=SIMBA, email=HELPER, **body):
    return call(
        "POST", f"/api/v1/cats/{cat}/feedings", {"feedingId": fid(n), **body}, email=email
    )


def fed_ok(world, n, cat=SIMBA, email=HELPER, **body):
    status, answer = feed(n, cat, email, **body)
    assert status == 200, answer
    world["stream"].settle()
    return answer


def last_fed(cat=SIMBA):
    return call("GET", f"/api/v1/cats/{cat}", email=HELPER)[1]["cat"]["lastFedAt"]


def mine(email=HELPER):
    return call("GET", "/api/v1/achievements", email=email)[1]


def earned(email=HELPER):
    return [b["id"] for b in mine(email)["badges"] if b["earned"]]


def recount(world, email=HELPER):
    """Points from nothing but the person's feedings, as a recount would."""
    user = call("GET", "/api/v1/me", email=email)[1]["userId"]
    return events.fed(events._query_all(f"USER#{user}", "FED#"))[0]


def test_a_feeding_is_the_cats_last_fed_and_earns_ten_points(world):
    assert last_fed() is None
    assert earned() == [] and mine()["counters"]["catsFed"] == 0
    answer = fed_ok(world, 1, spotId="library-steps")
    assert answer["lastFedAt"].startswith("2026-11-12T10:00:00")
    assert last_fed() == answer["lastFedAt"]
    body = mine()
    assert (body["points"], body["counters"]["catsFed"]) == (10, 1)
    assert earned() == ["snack-giver"]
    assert body["rules"] == [{"id": "feed", "points": 10}, {"id": "post", "points": 5}]
    # In the gallery's list too.
    cats = call("GET", "/api/v1/cats", email=HELPER)[1]["cats"]
    assert {c["catId"]: c["lastFedAt"] for c in cats} == {
        SIMBA: answer["lastFedAt"],
        BAMBA: None,
    }


def test_the_same_cat_again_inside_four_hours_is_refused(world):
    fed_ok(world, 1)
    world["clock"]["now"] += 4 * HOUR - 60
    status, body = feed(2)
    assert (status, body["code"]) == (429, "too_soon")
    assert body["retryAfter"] == 60
    # Another cat is another matter, and so is another person.
    assert feed(3, BAMBA)[0] == 200
    assert feed(4, SIMBA, ADMIN)[0] == 200
    world["clock"]["now"] += 60
    assert feed(2)[0] == 200


def test_asking_twice_is_one_feeding(world):
    first = fed_ok(world, 1)
    world["clock"]["now"] += 30
    status, again = feed(1)
    assert (status, again) == (200, first)
    world["stream"].settle()
    assert mine()["points"] == 10
    items = world["social"].query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :fed)",
        ExpressionAttributeValues={":pk": f"CAT#{SIMBA}", ":fed": "FED#"},
    )["Items"]
    assert len(items) == 1


def test_a_third_feeding_in_a_day_earns_nothing(world):
    world["data"].put_item(
        Item={
            "PK": "CAT#01JD00000000000000000000C3",
            "SK": "META",
            "catId": "01JD00000000000000000000C3",
            "name": "Shemesh",
            "photoCount": 0,
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": "2026-10-02T00:00:00Z",
        }
    )
    fed_ok(world, 1, SIMBA)
    fed_ok(world, 2, BAMBA)
    assert mine()["points"] == 20
    fed_ok(world, 3, "01JD00000000000000000000C3")
    body = mine()
    assert (body["points"], body["counters"]["catsFed"]) == (20, 3)
    # The next day counts again.
    world["clock"]["now"] += 24 * HOUR
    fed_ok(world, 4, SIMBA)
    assert mine()["points"] == 30 == recount(world)


def test_six_logs_a_day_and_no_more(world):
    # One cat every four hours would never reach six in a day: six cats.
    cats = [f"01JD0000000000000000000{n:03d}" for n in range(7)]
    for n, cat in enumerate(cats):
        world["data"].put_item(
            Item={
                "PK": f"CAT#{cat}",
                "SK": "META",
                "catId": cat,
                "name": f"Cat {n}",
                "photoCount": 0,
                "GSI2PK": "ENTITY#CAT",
                "GSI2SK": f"2026-10-03T00:00:0{n}Z",
            }
        )
    for n, cat in enumerate(cats[:6]):
        assert feed(n, cat)[0] == 200
    status, body = feed(6, cats[6])
    assert (status, body["code"]) == (429, "rate_limited")
    assert handler.FEEDINGS_PER_DAY == 6


def test_removing_the_newest_puts_last_fed_back_to_the_one_before(world):
    first = fed_ok(world, 1)
    world["clock"]["now"] += 5 * HOUR
    second = fed_ok(world, 2, email=ADMIN)
    assert last_fed() == second["lastFedAt"]

    status, desk = desk_call("GET", f"/api/cats/{SIMBA}/feedings", None, ADMIN)
    assert status == 200
    assert [(f["feedingId"], f["removed"]) for f in desk["feedings"]] == [
        (fid(2), False),
        (fid(1), False),
    ]
    assert desk["lastFedAt"] == second["lastFedAt"]
    assert desk["feedings"][1]["by"] == call("GET", "/api/v1/me", email=HELPER)[1]["username"]

    status, desk = desk_call(
        "POST", f"/api/cats/{SIMBA}/feedings/{fid(2)}/remove", None, ADMIN
    )
    assert status == 200 and desk["feedings"][0]["removed"] is True
    world["stream"].settle()
    assert last_fed() == first["lastFedAt"]
    # What it earned is taken back, and the badge with it.
    assert (mine(ADMIN)["points"], earned(ADMIN)) == (0, [])
    assert (mine()["points"], earned()) == (10, ["snack-giver"])

    # Twice is once; and with the last one gone there is no "last fed".
    assert desk_call(
        "POST", f"/api/cats/{SIMBA}/feedings/{fid(2)}/remove", None, ADMIN
    )[0] == 200
    desk_call("POST", f"/api/cats/{SIMBA}/feedings/{fid(1)}/remove", None, ADMIN)
    world["stream"].settle()
    assert last_fed() is None
    assert (mine()["points"], mine()["counters"]["catsFed"], earned()) == (0, 0, [])
    assert desk_call(
        "POST", f"/api/cats/{SIMBA}/feedings/{fid(9)}/remove", None, ADMIN
    )[0] == 404


def test_only_an_admin_removes_a_feeding(world):
    fed_ok(world, 1)
    assert desk_call("GET", f"/api/cats/{SIMBA}/feedings", None, HELPER)[0] == 403
    assert desk_call(
        "POST", f"/api/cats/{SIMBA}/feedings/{fid(1)}/remove", None, HELPER
    )[0] == 403


def test_the_same_records_twice_change_nothing(world):
    fed_ok(world, 1)
    world["clock"]["now"] += 60
    fed_ok(world, 2, BAMBA)
    before = (mine(), last_fed(), last_fed(BAMBA))
    serialize = TypeSerializer().serialize
    for item in world["social"].query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :fed)",
        ExpressionAttributeValues={":pk": f"CAT#{SIMBA}", ":fed": "FED#"},
    )["Items"]:
        record = {
            "eventName": "INSERT",
            "dynamodb": {
                "Keys": {"PK": {"S": item["PK"]}, "SK": {"S": item["SK"]}},
                "NewImage": {k: serialize(v) for k, v in item.items()},
            },
        }
        events.count_feeding(record)
        events.count_feeding(record)
    assert (mine(), last_fed(), last_fed(BAMBA)) == before
    assert mine()["points"] == 20 == recount(world)


def test_what_is_refused(world):
    assert feed(1, spotId="the-moon")[0] == 400
    assert call("POST", f"/api/v1/cats/{SIMBA}/feedings", {}, email=HELPER)[0] == 400
    assert feed(1, "01JD00000000000000000000ZZ")[0] == 404
    assert regions.feeding_spot_ids() >= {"library-steps"}
    assert all(s["regionId"] in regions.ids() for s in regions.feeding_spots())


def test_with_the_flag_off_there_is_no_feeding_anywhere(world, monkeypatch):
    fed_ok(world, 1)
    monkeypatch.setattr(handler, "FLAGS", {"social": True})
    assert feed(2, BAMBA)[0] == 404
    body = mine()
    assert body["points"] == 0
    assert "catsFed" not in body["counters"]
    assert "snack-giver" not in [b["id"] for b in body["badges"]]
    assert body["rules"] == [{"id": "post", "points": 5}]
