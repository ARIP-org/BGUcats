"""An encounter, as the app counts it (B3b): the pick is a claim, the label
an admin's; "met" and a post's cat follow the label when there is one (D8).

Runs the desk's API, the member API and the events Lambda together, with
tests/events/stream.py standing in for the table's stream.
"""

import boto3
import pytest

import tests.admin.test_handler  # the env the desk's API reads, set at import
from admin import handler as desk
from common import encounters
from events import handler as events
from tests.app.test_me import call
from tests.events.stream import Stream

from .test_me import ADMIN, HELPER, aws  # noqa: F401  (the fixture)

BUCKET = "bgucats-media-test"
SIMBA = "01JD0000000000000000000CA1"
BAMBA = "01JD0000000000000000000CA2"
SESSION = "01JD0000000000000000000SE1"
SECOND = "01JD0000000000000000000SE2"
PHOTO = "01JD0000000000000000000PH1"
SECOND_PHOTO = "01JD0000000000000000000PH2"
POST = "01JD0000000000000000000PS1"
MODEL = "mega-t224-int8-0123456789ab"
LIBRARY = {"lat": 31.262_2, "lon": 34.803_1, "accuracyM": 6}


def desk_call(method, path, body=None, email=ADMIN):
    return tests.admin.test_handler._call(method, path, body, email)


@pytest.fixture
def campus(aws, monkeypatch):  # noqa: F811
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_bucket_versioning(
        Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
    )
    monkeypatch.setattr(desk, "table", aws["data"])
    monkeypatch.setattr(desk, "social_table", aws["social"])
    monkeypatch.setattr(desk, "s3", s3)
    monkeypatch.setattr(desk, "MEDIA_BUCKET", BUCKET)
    monkeypatch.setattr(desk, "SOCIAL", True)
    monkeypatch.setattr(events, "social_table", aws["social"])
    for cat, name in ((SIMBA, "Simba"), (BAMBA, "Bamba")):
        aws["data"].put_item(
            Item={
                "PK": f"CAT#{cat}",
                "SK": "META",
                "catId": cat,
                "name": name,
                "photoCount": 0,
                "GSI2PK": "ENTITY#CAT",
                "GSI2SK": "2026-10-01T00:00:00Z",
            }
        )
    for who in (HELPER, ADMIN):
        call("POST", "/api/v1/me/terms", {"version": "2026-11"}, email=who)
    aws["stream"] = Stream(aws["social"])
    aws["s3"] = s3
    aws["user"] = call("GET", "/api/v1/me", email=HELPER)[1]["userId"]
    return aws


def encounter(campus, session=SESSION, photo=PHOTO, email=HELPER):
    """An encounter with one finished photo, as Capture leaves it."""
    status, _ = desk_call(
        "POST", "/api/encounters", {"sessionId": session, **LIBRARY}, email
    )
    assert status == 200
    key = f"raw/{session}/{photo}.jpg"
    campus["s3"].put_object(Bucket=BUCKET, Key=key, Body=b"jpeg")
    campus["data"].put_item(
        Item={
            "PK": f"PHOTO#{photo}",
            "SK": "META",
            "photoId": photo,
            "sessionId": session,
            "status": "unlabeled",
            "mediaType": "photo",
            "channel": "app",
            "submittedBy": email,
            "s3RawKey": key,
            "createdAt": "2026-11-12T08:00:01Z",
            "GSI1PK": f"SESSION#{session}",
            "GSI1SK": "2026-11-12T08:00:01Z",
            "GSI2PK": "STATUS#unlabeled",
            "GSI2SK": "2026-11-12T08:00:01Z",
        }
    )


def pick(cat=SIMBA, session=SESSION, email=HELPER):
    body = {
        "modelVersion": MODEL,
        "choice": "cat" if cat else "none",
        "shown": [SIMBA, BAMBA],
        "ranked": [{"catId": SIMBA, "score": 0.5}, {"catId": BAMBA, "score": 0.4}],
        "photoCount": 1,
        **({"catId": cat} if cat else {}),
    }
    status, _ = desk_call("POST", f"/api/encounters/{session}/pick", body, email)
    assert status == 200


def label(cat, session=SESSION):
    status, _ = desk_call("POST", f"/api/sessions/{session}/assign", {"catId": cat})
    assert status == 200


def post(campus, session=SESSION, photo=PHOTO, post_id=POST, cat=SIMBA):
    return call(
        "POST",
        "/api/v1/posts",
        {
            "postId": post_id,
            "sessionId": session,
            "photoIds": [photo],
            "claim": {"catId": cat},
            "shareRegion": True,
        },
        email=HELPER,
    )


def get(table, pk, sk):
    return table.get_item(Key={"PK": pk, "SK": sk}).get("Item")


def enc(campus, session=SESSION):
    return get(campus["social"], f"USER#{campus['user']}", f"ENC#{session}")


def met(campus):
    items = campus["social"].query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :met)",
        ExpressionAttributeValues={":pk": f"USER#{campus['user']}", ":met": "MET#"},
    )["Items"]
    return {i["catId"]: i for i in items}


def counts(campus):
    return call("GET", "/api/v1/me", email=HELPER)[1]["counters"]


def cat_counts(campus, cat):
    item = get(campus["social"], f"CAT#{cat}", "PUBLIC") or {}
    return int(item.get("posts", 0)), int(item.get("likes", 0))


# ------------------------------------------------------------- the claim


def test_a_pick_counts_at_once(campus):
    encounter(campus)
    pick()
    item = enc(campus)
    assert item["claimedCatId"] == SIMBA
    assert item["labelCatId"] is None and item["rejected"] is False
    assert item["regionId"] == "library"
    assert item["day"] == encounters.day_of(item["updatedAt"])

    campus["stream"].settle()
    assert set(met(campus)) == {SIMBA}
    assert met(campus)[SIMBA]["encounters"] == 1
    assert counts(campus)["all"] == {"catsMet": 1, "encounters": 1}
    cat = call("GET", f"/api/v1/cats/{SIMBA}", email=HELPER)[1]["cat"]
    assert cat["met"]["encounters"] == 1 and cat["met"]["days"] == 1
    assert call("GET", f"/api/v1/cats/{BAMBA}", email=HELPER)[1]["cat"]["met"] is None


def test_not_sure_is_an_encounter_with_nobody(campus):
    encounter(campus)
    pick(cat=None)
    campus["stream"].settle()
    assert met(campus) == {}
    assert counts(campus)["all"] == {"catsMet": 0, "encounters": 1}


def test_changing_ones_mind_moves_the_count(campus):
    encounter(campus)
    pick(SIMBA)
    campus["stream"].settle()
    pick(BAMBA)
    campus["stream"].settle()
    assert set(met(campus)) == {BAMBA}
    assert counts(campus)["all"]["catsMet"] == 1


def test_someone_who_never_opened_the_app_has_nothing_written(campus):
    outsider = "desk-only@example.com"
    campus["data"].put_item(
        Item={"PK": f"ADMIN#{outsider}", "SK": "META", "email": outsider}
    )
    encounter(campus, email=outsider)  # never called /api/v1/me
    pick(email=outsider)
    label(BAMBA)
    assert not [
        i for i in campus["social"].scan()["Items"] if i["SK"].startswith("ENC#")
    ]


def test_with_the_app_off_the_desk_leaves_its_table_alone(campus, monkeypatch):
    monkeypatch.setattr(desk, "SOCIAL", False)
    encounter(campus)
    pick()
    label(BAMBA)
    assert enc(campus) is None


# ------------------------------------------------------------- the label


def test_a_label_that_agrees_changes_nothing(campus):
    encounter(campus)
    pick(SIMBA)
    campus["stream"].settle()
    label(SIMBA)
    assert enc(campus)["labelCatId"] == SIMBA
    campus["stream"].settle()
    assert set(met(campus)) == {SIMBA}


def test_a_label_that_disagrees_takes_the_claim_back(campus):
    encounter(campus)
    pick(SIMBA)
    campus["stream"].settle()
    label(BAMBA)
    campus["stream"].settle()
    assert set(met(campus)) == {BAMBA}
    assert counts(campus)["all"] == {"catsMet": 1, "encounters": 1}


def test_a_label_made_before_the_pick_is_found_by_it(campus):
    encounter(campus)
    label(BAMBA)
    pick(SIMBA)
    assert enc(campus)["labelCatId"] == BAMBA
    campus["stream"].settle()
    assert set(met(campus)) == {BAMBA}


def test_taking_a_label_off_goes_back_to_the_claim(campus):
    encounter(campus)
    pick(SIMBA)
    label(BAMBA)
    status, _ = desk_call("POST", f"/api/sessions/{SESSION}/unassign")
    assert status == 200
    assert enc(campus)["labelCatId"] is None
    campus["stream"].settle()
    assert set(met(campus)) == {SIMBA}


def test_a_rejected_encounter_counts_for_nothing(campus):
    encounter(campus)
    pick(SIMBA)
    campus["stream"].settle()
    status, _ = desk_call("POST", f"/api/sessions/{SESSION}/reject")
    assert status == 200
    assert enc(campus)["rejected"] is True
    campus["stream"].settle()
    assert met(campus) == {}
    assert counts(campus)["all"] == {"catsMet": 0, "encounters": 0}


def test_a_merge_gives_the_encounter_the_targets_cat(campus):
    encounter(campus)
    pick(SIMBA)
    encounter(campus, SECOND, SECOND_PHOTO, email=ADMIN)
    label(BAMBA, SECOND)
    status, _ = desk_call(
        "POST",
        "/api/sessions/merge",
        {"sourceSessionId": SESSION, "targetSessionId": SECOND},
    )
    assert status == 200
    assert enc(campus)["labelCatId"] == BAMBA
    # Relabeling the target reaches the encounter merged into it.
    label(SIMBA, SECOND)
    assert enc(campus)["labelCatId"] == SIMBA


def test_two_encounters_on_one_day_are_one_day(campus):
    encounter(campus)
    pick(SIMBA)
    encounter(campus, SECOND, SECOND_PHOTO)
    pick(SIMBA, SECOND)
    campus["stream"].settle()
    simba = met(campus)[SIMBA]
    assert (simba["encounters"], simba["days"]) == (2, 1)
    assert counts(campus)["all"] == {"catsMet": 1, "encounters": 2}


# ------------------------------------------------------------- the post


def test_a_post_follows_the_label_with_its_likes(campus):
    encounter(campus)
    pick(SIMBA)
    assert post(campus)[0] == 200
    campus["stream"].settle()
    assert call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)[0] == 200
    assert cat_counts(campus, SIMBA) == (1, 1)

    label(BAMBA)
    campus["stream"].settle()
    assert cat_counts(campus, SIMBA) == (0, 0)
    assert cat_counts(campus, BAMBA) == (1, 1)
    card = call("GET", f"/api/v1/posts/{POST}", email=ADMIN)[1]["post"]
    assert card["cat"]["catId"] == BAMBA
    assert [
        c["postId"] for c in call("GET", f"/api/v1/cats/{BAMBA}/posts")[1]["cards"]
    ] == [POST]
    assert call("GET", f"/api/v1/cats/{SIMBA}/posts")[1]["cards"] == []

    # A like taken back now comes off the cat the post is on.
    assert call("DELETE", f"/api/v1/posts/{POST}/like", email=ADMIN)[0] == 200
    assert cat_counts(campus, BAMBA) == (1, 0)


def test_a_post_labeled_before_it_is_published_is_published_on_the_label(campus):
    encounter(campus)
    label(BAMBA)
    pick(SIMBA)
    post(campus)
    campus["stream"].settle()
    assert cat_counts(campus, SIMBA) == (0, 0)
    assert cat_counts(campus, BAMBA) == (1, 0)


def test_a_post_without_a_pick_still_counts_the_encounter(campus):
    encounter(campus)
    post(campus)
    assert enc(campus)["claimedCatId"] == SIMBA
    assert enc(campus)["postId"] == POST
    campus["stream"].settle()
    assert set(met(campus)) == {SIMBA}


def test_a_rejected_encounter_takes_its_post_down(campus):
    encounter(campus)
    pick(SIMBA)
    post(campus)
    campus["stream"].settle()
    desk_call("POST", f"/api/sessions/{SESSION}/reject")
    campus["stream"].settle()
    assert call("GET", f"/api/v1/posts/{POST}", email=ADMIN)[0] == 404
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"] == []
    assert cat_counts(campus, SIMBA) == (0, 0)


def test_one_post_per_encounter(campus):
    encounter(campus)
    pick(SIMBA)
    post(campus)
    other = "01JD0000000000000000000PS2"
    status, body = post(campus, post_id=other)
    assert (status, body["code"]) == (409, "already_posted")
    # Sending the first one again is still the same post.
    assert post(campus)[0] == 200
    # Once it is deleted, the encounter may be posted again.
    call("DELETE", f"/api/v1/posts/{POST}", email=HELPER)
    assert post(campus, post_id=other)[0] == 200


# ------------------------------------------------------------- the rule


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"claimedCatId": SIMBA},
        {"claimedCatId": SIMBA, "labelCatId": BAMBA},
        {"claimedCatId": None, "labelCatId": BAMBA},
        {"claimedCatId": SIMBA, "labelCatId": BAMBA, "rejected": True},
        {"claimedCatId": SIMBA, "labelCatId": None, "rejected": False},
    ],
)
def test_the_events_lambda_keeps_the_same_rule_as_the_api(item):
    # The events Lambda ships without src/common, so it has its own copy.
    assert events._shown_cat(item) == encounters.shown_cat(item)


def test_the_day_is_israels():
    # 23:30 UTC on the 11th is already the 12th in Israel.
    assert encounters.day_of("2026-11-11T23:30:00Z") == "2026-11-12"
    assert encounters.day_of("2026-11-12T08:00:00.123Z") == "2026-11-12"


def test_summarise_counts_months_apart():
    met_, months, total = events.summarise(
        [
            {"day": "2026-11-30", "claimedCatId": SIMBA},
            {"day": "2026-12-01", "claimedCatId": SIMBA},
            {"day": "2026-12-01", "claimedCatId": BAMBA, "rejected": True},
            {"day": "2026-12-02"},
            {"claimedCatId": BAMBA},  # never placed: not counted
        ]
    )
    assert met_[SIMBA]["days"] == 2 and met_[SIMBA]["firstDay"] == "2026-11-30"
    assert months == {
        "2026-11": {"encounters": 1, "catsMet": 1},
        "2026-12": {"encounters": 2, "catsMet": 1},
    }
    assert total == {"encounters": 3, "catsMet": 1}


def test_a_post_with_no_cat_is_published_liked_and_given_the_label(campus):
    encounter(campus)
    status, _ = call(
        "POST",
        "/api/v1/posts",
        {
            "postId": POST,
            "sessionId": SESSION,
            "photoIds": [PHOTO],
            "claim": None,
            "shareRegion": False,
        },
        email=HELPER,
    )
    assert status == 200
    campus["stream"].settle()
    card = call("GET", f"/api/v1/posts/{POST}", email=ADMIN)[1]["post"]
    assert card["cat"] is None
    assert call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)[1]["likes"] == 1
    assert met(campus) == {}

    label(SIMBA)
    campus["stream"].settle()
    assert cat_counts(campus, SIMBA) == (1, 1)
    assert set(met(campus)) == {SIMBA}
    assert call("DELETE", f"/api/v1/posts/{POST}/like", email=ADMIN)[1]["likes"] == 0
    assert cat_counts(campus, SIMBA) == (1, 0)
