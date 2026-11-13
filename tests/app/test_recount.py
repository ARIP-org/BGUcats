"""scripts/recount.py: every counter the events Lambda keeps, counted again
from the items it is a sum of (B7's "done when": the recount's result
equals the stored counters on a campus where everything has happened)."""

import recount
from app import handler

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


def differences(world):
    world["stream"].settle()
    return recount.differences(recount.read(world["social"]))


def test_after_everything_has_happened_nothing_differs(campus, monkeypatch):  # noqa: F811
    monkeypatch.setattr(handler, "FLAGS", {"social": True, "gpa": True, "feeding": True})
    assert differences(campus) == []
    # Met and posted, met again and saved, fed, and then relabeled.
    encounter(campus)
    pick(SIMBA)
    post(campus)
    assert differences(campus) == []
    encounter(campus, SECOND, SECOND_PHOTO)
    pick(BAMBA, SECOND)
    assert differences(campus) == []
    for n, (cat, who) in enumerate(((SIMBA, HELPER), (BAMBA, HELPER), (SIMBA, ADMIN))):
        status, body = call(
            "POST", f"/api/v1/cats/{cat}/feedings", {"feedingId": f"01JF{n:022d}"}, email=who
        )
        assert status == 200, body
    assert differences(campus) == []
    label(BAMBA)
    assert differences(campus) == []
    desk_call("POST", f"/api/cats/{SIMBA}/feedings/01JF{0:022d}/remove", None, ADMIN)
    assert differences(campus) == []


def test_a_counter_that_drifted_is_named(campus, monkeypatch):  # noqa: F811
    monkeypatch.setattr(handler, "FLAGS", {"social": True, "gpa": True, "feeding": True})
    encounter(campus)
    pick(SIMBA)
    post(campus)
    call("POST", f"/api/v1/cats/{SIMBA}/feedings", {"feedingId": f"01JF{1:022d}"}, email=HELPER)
    assert differences(campus) == []
    user = f"USER#{campus['user']}"
    campus["social"].update_item(
        Key={"PK": user, "SK": "STATS#ALL"},
        UpdateExpression="SET points = :p, fedPoints = :f",
        ExpressionAttributeValues={":p": 500, ":f": 0},
    )
    campus["social"].update_item(
        Key={"PK": f"CAT#{SIMBA}", "SK": "PUBLIC"},
        UpdateExpression="SET #pop = :n REMOVE lastFedAt",
        ExpressionAttributeNames={"#pop": "pop2031-01"},
        ExpressionAttributeValues={":n": 9},
    )
    found = recount.differences(recount.read(campus["social"]))
    assert f"{user} STATS#ALL points: stored 500, counted 5" in found
    assert f"{user} STATS#ALL fedPoints: stored 0, counted 10" in found
    assert f"CAT#{SIMBA} pop2031-01: stored 9, counted 0" in found
    assert any(line.startswith(f"CAT#{SIMBA} lastFedAt: stored None") for line in found)
    assert len(found) == 4
