"""Achievements (B7): points, the level they make, and badges, worked out
by the events Lambda from a person's encounters and shown by the member
API. The rules are one file, web/achievements.json (D11).

Runs the desk's API, the member API and the events Lambda together.
"""

import json
from pathlib import Path

import pytest

from app import handler
from common import achievements, encounters
from events import handler as events

from .test_encounters import (  # noqa: F401  (the fixture)
    BAMBA,
    POST,
    SECOND,
    SECOND_PHOTO,
    SESSION,
    SIMBA,
    campus,
    desk_call,
    encounter,
    label,
    pick,
    post,
)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)

REPO = Path(__file__).resolve().parents[2]
SECOND_POST = "01JD0000000000000000000PS2"
BADGES = ["first-meow", "night-owl", "explorer", "name-giver", "deans-list", "cat-whisperer"]


@pytest.fixture(autouse=True)
def daytime(request, monkeypatch):
    """These tests make encounters now, whenever now is. Run after ten at
    night in Israel they would all earn "Night Owl"; here it is always noon,
    except in the test of the hour itself."""
    if "hour" not in request.node.name:
        monkeypatch.setattr(encounters, "hour_of", lambda iso: 12)


def mine(email=HELPER):
    status, body = call("GET", "/api/v1/achievements", email=email)
    assert status == 200, body
    return body


def earned(email=HELPER):
    return [b["id"] for b in mine(email)["badges"] if b["earned"]]


def recount(world):
    """Points from nothing but the encounters, as a recount would."""
    user = f"USER#{world['user']}"
    encs = events._encounters_of(user)
    met = events.summarise(encs)[0]
    return events.achievements(encs, met)[0]


def settle(world):
    world["stream"].settle()
    assert mine()["points"] == recount(world)


def test_someone_new_has_nothing_and_every_badge_still_to_earn(campus):  # noqa: F811
    body = mine()
    assert body == {
        "points": 0,
        "level": {"level": 1, "from": 0, "next": 50},
        "counters": {"catsMet": 0, "encounters": 0, "posts": 0},
        "badges": [{"id": b, "earned": False, "at": None} for b in BADGES],
        "rules": [{"id": "post", "points": 5}],
    }


def test_meeting_earns_first_meow_and_posting_earns_points(campus):  # noqa: F811
    encounter(campus)
    pick(SIMBA)
    settle(campus)
    body = mine()
    # Met and saved: the badge, and no points yet.
    assert (body["points"], earned()) == (0, ["first-meow"])
    assert body["counters"] == {"catsMet": 1, "encounters": 1, "posts": 0}
    first = next(b for b in body["badges"] if b["id"] == "first-meow")["at"]
    assert first

    assert post(campus)[0] == 200
    settle(campus)
    assert (mine()["points"], mine()["counters"]["posts"]) == (5, 1)

    # Another cat the same day is another five.
    encounter(campus, SECOND, SECOND_PHOTO)
    pick(BAMBA, SECOND)
    assert post(campus, SECOND, SECOND_PHOTO, SECOND_POST, BAMBA)[0] == 200
    settle(campus)
    body = mine()
    assert (body["points"], body["counters"]["posts"]) == (10, 2)
    # The badge keeps the moment it was first earned.
    assert next(b for b in body["badges"] if b["id"] == "first-meow")["at"] == first


def test_a_label_takes_back_exactly_what_the_claim_gave(campus):  # noqa: F811
    encounter(campus)
    pick(SIMBA)
    post(campus)
    encounter(campus, SECOND, SECOND_PHOTO)
    pick(BAMBA, SECOND)
    post(campus, SECOND, SECOND_PHOTO, SECOND_POST, BAMBA)
    settle(campus)
    assert mine()["points"] == 10

    # The admin says the second was Simba too: one cat on one day is five,
    # however many posts.
    label(SIMBA, SECOND)
    settle(campus)
    assert (mine()["points"], mine()["counters"]["catsMet"]) == (5, 1)
    assert desk_call("POST", f"/api/sessions/{SECOND}/unassign")[0] == 200
    settle(campus)
    assert mine()["points"] == 10

    # Both encounters rejected: nothing is left, the first badge included.
    for session in (SESSION, SECOND):
        assert desk_call("POST", f"/api/sessions/{session}/reject")[0] == 200
    settle(campus)
    assert (mine()["points"], earned()) == (0, [])


def test_the_same_change_seen_twice_changes_nothing(campus):  # noqa: F811
    encounter(campus)
    pick(SIMBA)
    post(campus)
    settle(campus)

    def held():
        return sorted(
            (i["SK"], i.get("points"), i.get("at"))
            for i in campus["social"].scan()["Items"]
            if i["SK"].startswith(("BADGE#", "STATS#ALL"))
        )

    before = held()
    user = f"USER#{campus['user']}"
    record = {"dynamodb": {"Keys": {"PK": {"S": user}, "SK": {"S": f"ENC#{SESSION}"}}}}
    for _ in range(2):
        events.count_encounter(record)
    assert held() == before
    assert campus["stream"].settle() == 0


def test_an_encounter_keeps_the_hour_it_began_at(campus):  # noqa: F811
    encounter(campus)
    pick(SIMBA)
    enc = campus["social"].get_item(
        Key={"PK": f"USER#{campus['user']}", "SK": f"ENC#{SESSION}"}
    )["Item"]
    assert 0 <= int(enc["hour"]) <= 23
    # Israel's clock, not the server's: 21:30 UTC in November is 23:30 there.
    assert encounters.hour_of("2026-11-12T21:30:00+00:00") == 23
    assert encounters.hour_of("2026-07-01T21:30:00+00:00") == 0  # summer time


def enc(cat="a", day="2026-11-03", **more):
    return {"claimedCatId": cat, "day": day, **more}


@pytest.mark.parametrize(
    ("hour", "owl"),
    [(22, True), (23, True), (0, True), (4, True), (5, False), (12, False), (21, False), (None, False)],
)
def test_night_owl_is_between_ten_at_night_and_five(hour, owl):
    badges = events.achievements([enc(hour=hour)], {})[2]
    assert ("night-owl" in badges) is owl


def test_explorer_needs_every_campus_region():
    regions = sorted(events.CAMPUS_REGIONS)
    assert len(regions) >= 2
    almost = [enc(regionId=r) for r in regions[:-1]]
    assert "explorer" not in events.achievements(almost, {})[2]
    everywhere = [*almost, enc(regionId=regions[-1])]
    assert "explorer" in events.achievements(everywhere, {})[2]
    # A rejected encounter was not there.
    cheated = [*almost, enc(regionId=regions[-1], rejected=True)]
    assert "explorer" not in events.achievements(cheated, {})[2]


def test_cat_whisperer_is_one_cat_on_ten_different_days():
    def badges(days):
        encs = [enc(day=f"2026-11-{d:02d}") for d in range(1, days + 1)]
        return events.achievements(encs, events.summarise(encs)[0])[2]

    assert "cat-whisperer" not in badges(9)
    assert "cat-whisperer" in badges(10)
    # Ten cats on ten days is not it.
    many = [enc(cat=f"c{d}", day=f"2026-11-{d:02d}") for d in range(1, 11)]
    assert "cat-whisperer" not in events.achievements(many, events.summarise(many)[0])[2]


def test_points_are_once_per_cat_per_day_and_only_for_a_post_of_a_cat():
    encs = [
        enc(postId="p1"),
        enc(postId="p2"),  # the same cat the same day
        enc(day="2026-11-04", postId="p3"),
        enc(cat="b"),  # met, not posted
        {"day": "2026-11-05", "postId": "p4"},  # a post of no cat
        enc(cat="c", postId="p5", rejected=True),
    ]
    points, posts, badges = events.achievements(encs, {})
    assert (points, posts, badges) == (10, 4, {"first-meow"})


def test_name_giver_is_kept_once_a_name_you_suggested_has_led(campus):  # noqa: F811
    status, _ = call("POST", f"/api/v1/cats/{SIMBA}/names", {"name": "Mango"}, email=HELPER)
    assert status == 200
    campus["stream"].settle()  # checked, live, and leading with its one vote
    assert earned() == ["name-giver"]
    assert earned(ADMIN) == []

    # The admin's suggestion overtakes it: the admin earns one, and the
    # first keeps theirs.
    call("POST", f"/api/v1/cats/{SIMBA}/names", {"name": "Pita"}, email=ADMIN)
    campus["stream"].settle()
    assert call("PUT", f"/api/v1/cats/{SIMBA}/vote", {"nameKey": "pita"}, email=HELPER)[0] == 200
    campus["stream"].settle()
    assert earned() == ["name-giver"]
    assert earned(ADMIN) == ["name-giver"]


def test_deans_list_is_every_cat_at_the_mark_while_there_is_one(campus, monkeypatch):  # noqa: F811
    monkeypatch.setattr(handler, "FLAGS", {"social": True, "gpa": True})
    assert "deans-list" not in earned()  # nobody has a grade yet
    encounter(campus)
    pick(SIMBA)
    campus["stream"].settle()
    # Simba is the only graded cat, at 4.0, and HELPER met him.
    assert "deans-list" in earned()
    assert "deans-list" not in earned(ADMIN)

    # Bamba becomes as popular, and HELPER has not met her: not any more.
    month = handler._israel_today().isoformat()[:7]
    campus["social"].update_item(
        Key={"PK": f"CAT#{BAMBA}", "SK": "PUBLIC"},
        UpdateExpression="SET #pop = :one",
        ExpressionAttributeNames={"#pop": f"pop{month}"},
        ExpressionAttributeValues={":one": 1},
    )
    assert "deans-list" not in earned()


@pytest.mark.parametrize(
    ("points", "level", "start", "following"),
    [(0, 1, 0, 50), (49, 1, 0, 50), (50, 2, 50, 200), (1240, 4, 500, 1500), (1500, 5, 1500, 3000), (9999, 6, 3000, None)],
)
def test_levels_are_the_files_thresholds(points, level, start, following):
    # 1,240 points: "Level 4", "260 to Level 5", as the prototype draws it.
    assert achievements.level_of(points) == {"level": level, "from": start, "next": following}


def test_the_rules_file_is_what_both_lambdas_read_and_ship():
    rules = json.loads((REPO / "web" / "achievements.json").read_text())
    assert achievements.rules() == rules == events.RULES
    assert list(rules["badges"]) == BADGES
    assert rules["levels"] == sorted(set(rules["levels"])) and rules["levels"][0] == 0
    # Every badge the events Lambda keeps from encounters is in the file.
    assert set(events.ENCOUNTER_BADGES) <= set(rules["badges"])
    makefile = (REPO / "Makefile").read_text()
    common = next(line for line in makefile.splitlines() if line.startswith("copy-common ="))
    assert "web/achievements.json" in common
    build_events = makefile[makefile.index("\nbuild-events:") :].split("\n\n")[0]
    assert "web/achievements.json web/regions.json build/events/events/" in build_events
