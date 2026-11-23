"""The cats, as a user sees them (B2)."""

from datetime import date

import pytest

from app import handler
from tests.app.test_me import call

from .test_me import aws  # noqa: F401  (the fixture)

# Every key a user may receive about a cat. A new field is added here on
# purpose, or it is not sent: the admins' notes, and who made the cat, never
# are.
LIST_KEYS = {
    "gpa",
    "catId",
    "name",
    "nameSource",
    "regionId",
    "coat",
    "cover",
    "photoCount",
    "posts",
    "likes",
    "lastSeenAt",
    "lastFedAt",
    "firstSeenAt",
}
PAGE_KEYS = LIST_KEYS | {"bio", "photos", "met"}


def add_cat(data, cat_id, name, **fields):
    data.put_item(
        Item={
            "PK": f"CAT#{cat_id}",
            "SK": "META",
            "catId": cat_id,
            "name": name,
            "notes": "admin only: has a vet appointment",
            "createdBy": "admin@example.com",
            "createdAt": f"2026-10-0{len(cat_id) % 9 + 1}T00:00:00Z",
            "photoCount": 2,
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": f"2026-10-01T00:00:{cat_id[-2:]}Z",
            **fields,
        }
    )


def add_photo(data, photo_id, cat_id, created, media_type="photo"):
    data.put_item(
        Item={
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "mediaType": media_type,
            "status": "labeled",
            "catId": cat_id,
            "GSI3PK": f"CAT#{cat_id}",
            "GSI3SK": created,
        }
    )


@pytest.fixture
def campus(aws):  # noqa: F811
    data = aws["data"]
    add_cat(
        data,
        "CAT01",
        "Simba",
        bio="Sunbathes on the library steps.",
        usualRegionId="library",
    )
    add_cat(data, "CAT02", "Bamba")
    add_cat(data, "CAT03", "Ghost")  # no photo at all
    add_photo(data, "P1", "CAT01", "2026-10-01")
    add_photo(data, "P2", "CAT01", "2026-11-01")
    add_photo(data, "V1", "CAT02", "2026-10-01", media_type="video")
    add_photo(data, "P3", "CAT02", "2026-10-02")
    aws["social"].put_item(
        Item={
            "PK": "CAT#CAT02",
            "SK": "PUBLIC",
            "posts": 3,
            "likes": 7,
            "leaderName": "Ginger",
        }
    )
    return aws


def by_id(cats):
    return {c["catId"]: c for c in cats}


def test_every_cat_is_listed_with_only_its_public_fields(campus):
    status, body = call("GET", "/api/v1/cats", email="helper@example.com")
    assert status == 200
    cats = by_id(body["cats"])
    assert set(cats) == {"CAT01", "CAT02", "CAT03"}
    for cat in cats.values():
        assert set(cat) == LIST_KEYS
    assert "vet" not in str(body) and "createdBy" not in str(body)


def test_the_cover_is_the_oldest_photo_never_a_video(campus):
    cats = by_id(call("GET", "/api/v1/cats")[1]["cats"])
    assert "derived/P1/thumb-256.webp" in cats["CAT01"]["cover"]["thumb"]
    assert "derived/P3/medium-1024.webp" in cats["CAT02"]["cover"]["medium"]
    assert cats["CAT03"]["cover"] is None


def test_the_poll_leader_is_the_name_and_says_so(campus):
    cats = by_id(call("GET", "/api/v1/cats")[1]["cats"])
    assert (cats["CAT02"]["name"], cats["CAT02"]["nameSource"]) == ("Ginger", "poll")
    assert (cats["CAT01"]["name"], cats["CAT01"]["nameSource"]) == ("Simba", "admin")
    assert (cats["CAT02"]["posts"], cats["CAT02"]["likes"]) == (3, 7)
    assert (cats["CAT01"]["posts"], cats["CAT01"]["likes"]) == (0, 0)


def test_an_admins_lock_wins_over_the_poll(campus):
    campus["social"].update_item(
        Key={"PK": "CAT#CAT02", "SK": "PUBLIC"},
        UpdateExpression="SET lockedName = :n",
        ExpressionAttributeValues={":n": "Bamba"},
    )
    cat = by_id(call("GET", "/api/v1/cats")[1]["cats"])["CAT02"]
    assert (cat["name"], cat["nameSource"]) == ("Bamba", "admin")


def test_a_cats_page_has_its_description_and_newest_photos(campus):
    status, body = call("GET", "/api/v1/cats/CAT01")
    assert status == 200
    cat = body["cat"]
    assert set(cat) == PAGE_KEYS
    assert cat["bio"] == "Sunbathes on the library steps."
    assert cat["regionId"] == "library"
    assert [p["photoId"] for p in cat["photos"]] == ["P2", "P1"]
    assert "vet" not in str(body)


def test_a_cats_page_marks_a_photo_from_the_gallery(campus):
    """#108: a photo picked from the phone's gallery says so, and was
    not made on the spot; every other photo says "camera"."""
    campus["data"].update_item(
        Key={"PK": "PHOTO#P1", "SK": "META"},
        UpdateExpression="SET origin = :g",
        ExpressionAttributeValues={":g": "gallery"},
    )
    photos = call("GET", "/api/v1/cats/CAT01")[1]["cat"]["photos"]
    assert {p["photoId"]: p["origin"] for p in photos} == {
        "P2": "camera",
        "P1": "gallery",
    }


def test_an_unknown_cat_is_404(campus):
    assert call("GET", "/api/v1/cats/NOPE")[0] == 404


def test_the_cat_of_the_day_is_the_same_all_day_and_has_a_photo(campus):
    first = call("GET", "/api/v1/cats")[1]["catOfTheDay"]
    assert first in {"CAT01", "CAT02"}
    assert (
        call("GET", "/api/v1/cats", email="helper@example.com")[1]["catOfTheDay"]
        == first
    )


def test_the_cat_of_the_day_changes_with_the_day_and_prefers_recent_cats():
    cats = [
        {"catId": f"C{i}", "cover": {"thumb": "x"}, "lastSeenAt": None}
        for i in range(20)
    ] + [{"catId": "NONE", "cover": None, "lastSeenAt": "2026-11-11"}]
    picks = {handler.cat_of_the_day(cats, date(2026, 11, d)) for d in range(1, 29)}
    assert len(picks) > 5 and "NONE" not in picks
    cats[3]["lastSeenAt"] = "2026-11-10"
    assert handler.cat_of_the_day(cats, date(2026, 11, 12)) == "C3"
    assert handler.cat_of_the_day([], date(2026, 11, 12)) is None
