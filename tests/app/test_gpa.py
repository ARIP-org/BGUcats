"""A cat's grade (B7b, D9): nobody grades a cat; the app works a grade out
from how many people met it lately. The events Lambda keeps each cat's
popularity per month from people's encounters, with the same corrections
as "met"; the member API turns it into a grade when the cats are read.

Runs the desk's API, the member API and the events Lambda together.
"""

import pytest

from app import handler
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

NOBODYS = "01JD0000000000000000000CA3"
THIRD_SESSION = "01JD0000000000000000000SE3"
THIRD_PHOTO = "01JD0000000000000000000PH3"


@pytest.fixture
def graded(campus, monkeypatch):  # noqa: F811
    monkeypatch.setattr(handler, "FLAGS", {"social": True, "gpa": True})
    campus["data"].put_item(
        Item={
            "PK": f"CAT#{NOBODYS}",
            "SK": "META",
            "catId": NOBODYS,
            "name": "Pilpel",
            "photoCount": 0,
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": "2026-10-02T00:00:00Z",
        }
    )
    return campus


def grades_now(email=HELPER):
    cats = call("GET", "/api/v1/cats", email=email)[1]["cats"]
    return {c["catId"]: c["gpa"] for c in cats}


def stored(world):
    """{(catId, month): points} as the cats' public items hold it."""
    out = {}
    for item in world["social"].scan()["Items"]:
        if item["SK"] != "PUBLIC":
            continue
        for key, value in item.items():
            if key.startswith("pop") and int(value):
                out[(item["PK"].removeprefix("CAT#"), key.removeprefix("pop"))] = int(value)
    return out


def recount(world):
    """The same numbers from nothing but the encounters: every person's,
    added up. What a recount script would write."""
    by_person = {}
    for item in world["social"].scan()["Items"]:
        if item["SK"].startswith("ENC#"):
            by_person.setdefault(item["PK"], []).append(item)
    out = {}
    for encs in by_person.values():
        for key, points in events.popularity(encs).items():
            out[key] = out.get(key, 0) + points
    return out


def settle(world):
    world["stream"].settle()
    assert stored(world) == recount(world)


def test_the_most_popular_cat_reads_four_and_one_nobody_met_reads_nothing(graded):
    # Simba: met and posted, six points. Bamba: met, one.
    encounter(graded)
    pick(SIMBA)
    assert post(graded)[0] == 200
    encounter(graded, SECOND, SECOND_PHOTO)
    pick(BAMBA, SECOND)
    settle(graded)

    assert grades_now() == {SIMBA: 4.0, BAMBA: 2.2, NOBODYS: None}  # 1 + 3·√(1/6)
    # The same on each cat's own page, and for whoever asks.
    for cat, grade in ((SIMBA, 4.0), (BAMBA, 2.2), (NOBODYS, None)):
        assert call("GET", f"/api/v1/cats/{cat}", email=ADMIN)[1]["cat"]["gpa"] == grade


def test_only_the_last_three_months_count(graded):
    encounter(graded)
    pick(SIMBA)
    month = handler._israel_today().isoformat()[:7]
    before = handler._previous_month
    old = before(before(before(month)))  # one month too far back
    graded["social"].update_item(
        Key={"PK": f"CAT#{NOBODYS}", "SK": "PUBLIC"},
        UpdateExpression="SET #old = :much, #near = :some",
        ExpressionAttributeNames={
            "#old": f"pop{old}",
            "#near": f"pop{before(before(month))}",
        },
        ExpressionAttributeValues={":much": 500, ":some": 4},
    )
    graded["stream"].settle()
    # Pilpel's four points two months ago beat Simba's one; the 500 from
    # three months ago count for nothing.
    assert grades_now() == {SIMBA: 2.5, BAMBA: None, NOBODYS: 4.0}


def test_a_label_takes_from_one_cat_exactly_what_it_gives_the_other(graded):
    encounter(graded)
    pick(SIMBA)
    post(graded)
    encounter(graded, SECOND, SECOND_PHOTO)
    pick(BAMBA, SECOND)
    settle(graded)
    month = handler._israel_today().isoformat()[:7]
    assert stored(graded) == {(SIMBA, month): 6, (BAMBA, month): 1}

    # The admin says the posted encounter was Bamba. Both encounters are
    # now one person meeting Bamba on one day, one of them posted: six.
    label(BAMBA)
    settle(graded)
    assert stored(graded) == {(BAMBA, month): 6}
    assert grades_now() == {SIMBA: None, BAMBA: 4.0, NOBODYS: None}

    # The label comes off: back to what the person said.
    assert desk_call("POST", f"/api/sessions/{SESSION}/unassign")[0] == 200
    settle(graded)
    assert stored(graded) == {(SIMBA, month): 6, (BAMBA, month): 1}


def test_two_people_add_up_and_a_rejected_encounter_gives_nothing(graded):
    encounter(graded)
    pick(SIMBA)
    encounter(graded, THIRD_SESSION, THIRD_PHOTO, email=ADMIN)
    pick(SIMBA, THIRD_SESSION, email=ADMIN)
    settle(graded)
    month = handler._israel_today().isoformat()[:7]
    assert stored(graded) == {(SIMBA, month): 2}

    assert desk_call("POST", f"/api/sessions/{THIRD_SESSION}/reject")[0] == 200
    settle(graded)
    assert stored(graded) == {(SIMBA, month): 1}


def test_the_same_change_seen_twice_changes_nothing(graded):
    encounter(graded)
    pick(SIMBA)
    post(graded)
    settle(graded)
    before = stored(graded)
    user = f"USER#{graded['user']}"
    for _ in range(2):
        events.count_popularity(user, events._encounters_of(user))
    assert stored(graded) == before
    # And nothing the Lambda wrote brought it back to itself.
    assert graded["stream"].settle() == 0


def test_what_one_persons_encounters_are_worth():
    def enc(cat, day, **more):
        return {"claimedCatId": cat, "day": day, **more}

    assert events.popularity(
        [
            enc("a", "2026-11-03"),
            enc("a", "2026-11-03"),  # the same day: still one
            enc("a", "2026-11-04", postId="p1"),  # met and posted: six
            enc("a", "2026-11-04", postId="p2"),  # once per cat per day
            enc("b", "2026-10-31", labelCatId="c"),  # the label's cat, not the claim's
            enc("a", "2026-11-05", rejected=True),
            {"day": "2026-11-06"},  # an encounter with nobody
        ]
    ) == {("a", "2026-11"): 7, ("c", "2026-10"): 1}


def test_with_the_flag_off_nobody_has_a_grade(graded, monkeypatch):
    encounter(graded)
    pick(SIMBA)
    settle(graded)
    assert grades_now()[SIMBA] == 4.0
    monkeypatch.setattr(handler, "FLAGS", {"social": True})
    assert grades_now() == {SIMBA: None, BAMBA: None, NOBODYS: None}
    assert call("GET", f"/api/v1/cats/{SIMBA}", email=HELPER)[1]["cat"]["gpa"] is None
