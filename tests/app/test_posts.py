"""Posts, likes and the feed (B3a), with the events Lambda's publication."""

from decimal import Decimal

import pytest
from boto3.dynamodb.types import TypeSerializer

from app import handler
from events import handler as events
from tests.app.test_me import call

from .test_me import ADMIN, HELPER, aws  # noqa: F401  (the fixture)

SESSION = "01JD0000000000000000000SA1"
OTHER_SESSION = "01JD0000000000000000000SA2"
PHOTOS = ["01JD0000000000000000000PH1", "01JD0000000000000000000PH2"]
POST = "01JD0000000000000000000PS1"
CAT = "01JD0000000000000000000CA1"
SERIALIZE = TypeSerializer()


def published(table, post_id):
    """What the stream would hand the events Lambda for a new post."""
    item = table.get_item(Key={"PK": f"POST#{post_id}", "SK": "META"})["Item"]
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "Keys": {"PK": {"S": item["PK"]}, "SK": {"S": "META"}},
            "NewImage": {k: SERIALIZE.serialize(v) for k, v in item.items()},
            "SequenceNumber": "1",
        },
    }
    assert events.handler({"Records": [record]}, None) == {"batchItemFailures": []}


@pytest.fixture
def campus(aws, monkeypatch):  # noqa: F811
    data = aws["data"]
    data.put_item(
        Item={
            "PK": f"CAT#{CAT}",
            "SK": "META",
            "catId": CAT,
            "name": "Simba",
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": "2026-10-01T00:00:00Z",
        }
    )
    for session, owner in ((SESSION, HELPER), (OTHER_SESSION, ADMIN)):
        data.put_item(
            Item={
                "PK": f"SESSION#{session}",
                "SK": "META",
                "sessionId": session,
                "channel": "app",
                "startedBy": owner,
                "startedAt": "2026-11-12T08:00:00Z",
                "coarseLat": Decimal("31.262"),
                "coarseLon": Decimal("34.803"),  # at the library
            }
        )
    for photo in PHOTOS:
        data.put_item(
            Item={
                "PK": f"PHOTO#{photo}",
                "SK": "META",
                "photoId": photo,
                "sessionId": SESSION,
                "status": "unlabeled",
                "mediaType": "photo",
            }
        )
    monkeypatch.setattr(events, "social_table", aws["social"])
    for who in (HELPER, ADMIN):
        call("POST", "/api/v1/me/terms", {"version": "2026-11"}, email=who)
    return aws


def make_post(**over):
    body = {
        "postId": POST,
        "sessionId": SESSION,
        "photoIds": PHOTOS,
        "claim": {"catId": CAT},
        "text": "Sunbathing  on the library steps.",
        "shareRegion": True,
        **over,
    }
    return call("POST", "/api/v1/posts", body, email=HELPER)


def counters(social):
    return social.get_item(Key={"PK": f"CAT#{CAT}", "SK": "PUBLIC"}).get("Item", {})


def test_a_post_waits_then_appears_in_the_feed(campus):
    status, body = make_post()
    assert status == 200
    assert body["post"]["state"] == "pending"
    assert body["post"]["text"] == "Sunbathing on the library steps."
    # Not published yet: nobody else sees it, its author does.
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"] == []
    assert (
        call("GET", "/api/v1/me/posts", email=HELPER)[1]["cards"][0]["state"]
        == "pending"
    )
    assert call("GET", f"/api/v1/posts/{POST}", email=ADMIN)[0] == 404

    published(campus["social"], POST)
    cards = call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"]
    assert [c["postId"] for c in cards] == [POST]
    card = cards[0]
    assert card["author"]["username"] == "helper"
    assert card["cat"] == {"catId": CAT, "name": "Simba"}
    assert [p["photoId"] for p in card["photos"]] == PHOTOS
    assert "derived/" in card["photos"][0]["medium"]
    assert "state" not in card and card["mine"] is False


def test_publishing_twice_counts_once(campus):
    make_post()
    published(campus["social"], POST)
    published(campus["social"], POST)
    assert counters(campus["social"])["posts"] == 1
    cats = {c["catId"]: c for c in call("GET", "/api/v1/cats")[1]["cats"]}
    assert cats[CAT]["posts"] == 1
    assert [
        c["postId"] for c in call("GET", f"/api/v1/cats/{CAT}/posts")[1]["cards"]
    ] == [POST]


def test_the_area_is_shown_to_its_author_only(campus):
    make_post()
    published(campus["social"], POST)
    mine = call("GET", f"/api/v1/posts/{POST}", email=HELPER)[1]["post"]
    theirs = call("GET", f"/api/v1/posts/{POST}", email=ADMIN)[1]["post"]
    assert mine["region"] == "library"
    assert theirs["region"] is None


def test_without_sharing_the_area_is_not_kept(campus):
    make_post(shareRegion=False)
    item = campus["social"].get_item(Key={"PK": f"POST#{POST}", "SK": "META"})["Item"]
    assert item["regionId"] is None


def test_liking_twice_counts_once_and_unliking_takes_it_back(campus):
    make_post()
    published(campus["social"], POST)
    for _ in range(2):
        status, state = call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)
        assert (status, state["liked"], state["likes"]) == (200, True, 1)
    assert counters(campus["social"])["likes"] == 1
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"][0]["liked"] is True
    for _ in range(2):
        state = call("DELETE", f"/api/v1/posts/{POST}/like", email=ADMIN)[1]
        assert (state["liked"], state["likes"]) == (False, 0)
    assert counters(campus["social"])["likes"] == 0


def test_a_post_that_is_not_visible_cannot_be_liked(campus):
    make_post()
    assert call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)[0] == 404


def test_deleting_a_post_takes_it_out_of_every_list_and_count(campus):
    make_post()
    published(campus["social"], POST)
    call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)
    assert call("DELETE", f"/api/v1/posts/{POST}", email=ADMIN)[0] == 403
    assert call("DELETE", f"/api/v1/posts/{POST}", email=HELPER)[0] == 200
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"] == []
    assert call("GET", f"/api/v1/cats/{CAT}/posts")[1]["cards"] == []
    assert call("GET", "/api/v1/me/posts", email=HELPER)[1]["cards"] == []
    assert (
        counters(campus["social"])["posts"],
        counters(campus["social"])["likes"],
    ) == (0, 0)
    assert (
        call("DELETE", f"/api/v1/posts/{POST}", email=HELPER)[0] == 200
    )  # again: the same


def test_sending_the_same_post_again_is_the_same_post(campus):
    first = make_post()[1]["post"]
    again = make_post(text="different words")[1]["post"]
    assert again["postId"] == first["postId"] and again["text"] == first["text"]
    assert len(call("GET", "/api/v1/me/posts", email=HELPER)[1]["cards"]) == 1


def test_a_photo_still_uploading_is_not_yet_not_never(campus):
    campus["data"].update_item(
        Key={"PK": f"PHOTO#{PHOTOS[1]}", "SK": "META"},
        UpdateExpression="SET #s = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":p": "pending"},
    )
    status, body = make_post()
    # 425: web/outbox.js retries it; 400/403/404/409 it would drop.
    assert (status, body["code"]) == (425, "not_ready")
    assert call("GET", "/api/v1/me/posts", email=HELPER)[1]["cards"] == []


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"sessionId": OTHER_SESSION}, 403),  # someone else's encounter
        ({"photoIds": []}, 400),
        ({"photoIds": PHOTOS * 3}, 400),
        ({"claim": {"catId": "01JD0000000000000000000NC1"}}, 400),
        ({"claim": {"proposalId": "x"}}, 400),
        ({"text": "x" * 281}, 400),
        ({"postId": "not-a-ulid"}, 400),
    ],
)
def test_a_post_that_cannot_be_made_is_refused(campus, change, status):
    assert make_post(**change)[0] == status


def test_writing_needs_the_terms_first(campus, monkeypatch):
    monkeypatch.setattr(handler, "TERMS_VERSION", "2027-01")
    status, body = make_post()
    assert (status, body["code"]) == (403, "terms_required")


def test_the_feed_pages_newest_first(campus, monkeypatch):
    monkeypatch.setattr(handler, "FEED_PAGE", 2)
    social = campus["social"]
    for n in range(5):
        social.put_item(
            Item={
                "PK": f"POST#P{n}",
                "SK": "META",
                "postId": f"P{n}",
                "authorId": "someone",
                "photoIds": [],
                "status": "visible",
                "createdAt": f"2026-11-0{n + 1}T00:00:00Z",
                "GSI2PK": "FEED#2026-11",
                "GSI2SK": f"2026-11-0{n + 1}T00:00:00Z#P#P{n}",
            }
        )
    seen, cursor = [], None
    for _ in range(4):
        query = f"?cursor={cursor}" if cursor else ""
        event_query = {"cursor": cursor} if cursor else None
        status, page = _call_with_query("/api/v1/feed", event_query)
        assert status == 200, query
        seen += [c["postId"] for c in page["cards"]]
        cursor = page.get("cursor")
        if not cursor:
            break
    assert seen == ["P4", "P3", "P2", "P1", "P0"]


def _call_with_query(path, query):
    import json

    event = {
        "requestContext": {
            "http": {"method": "GET", "path": path},
            "authorizer": {"jwt": {"claims": {"email": ADMIN}}},
        },
        "queryStringParameters": query,
    }
    answer = handler.handler(event, None)
    return answer["statusCode"], json.loads(answer["body"])


def _photos_in_session(data, count):
    """`count` finished photos in the helper's encounter, oldest first."""
    photos = [f"01JD00000000000000000{n:05d}" for n in range(count)]
    for photo in photos:
        data.put_item(
            Item={
                "PK": f"PHOTO#{photo}",
                "SK": "META",
                "photoId": photo,
                "sessionId": SESSION,
                "status": "unlabeled",
                "mediaType": "photo",
            }
        )
    return photos


def test_a_post_carries_every_photo_of_its_encounter_in_order(campus):
    # More than the four of before #105, and not in the order they were taken.
    photos = _photos_in_session(campus["data"], 12)
    photos = photos[5:] + photos[:5]
    status, body = make_post(photoIds=photos)
    assert status == 200, body
    published(campus["social"], POST)
    card = call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"][0]
    assert [p["photoId"] for p in card["photos"]] == photos
    assert all("derived/" in p["medium"] for p in card["photos"])


def test_a_post_over_the_ceiling_is_refused_as_before(campus):
    too_many = _photos_in_session(campus["data"], handler.POST_PHOTOS_MAX + 1)
    status, body = make_post(photoIds=too_many)
    # The shape a post with no photo has always had.
    empty_status, empty = make_post(photoIds=[])
    assert status == empty_status == 400
    assert body == empty
    assert str(handler.POST_PHOTOS_MAX) in body["error"]
    at_ceiling = make_post(photoIds=too_many[:-1])
    assert at_ceiling[0] == 200, at_ceiling[1]
