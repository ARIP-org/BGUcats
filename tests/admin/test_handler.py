import json
import os
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from admin import handler

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["MEDIA_BUCKET"]

ADMIN = "admin@example.com"
SESSION = "01SESSION0000000000000000"
OTHER_SESSION = "01SESSION0000000000000001"

INDEXES = ("GSI1", "GSI2", "GSI3")


@pytest.fixture
def aws(monkeypatch):
    """Moto-backed S3 + DynamoDB swapped in for the module globals.

    handler.py binds `table` and `s3` at import time, before moto is
    active, so they must be replaced rather than merely mocked.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": name, "AttributeType": "S"}
                for name in (
                    "PK",
                    "SK",
                    "GSI1PK",
                    "GSI1SK",
                    "GSI2PK",
                    "GSI2SK",
                    "GSI3PK",
                    "GSI3SK",
                )
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": index,
                    "KeySchema": [
                        {"AttributeName": f"{index}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{index}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for index in INDEXES
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        s3.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )

        monkeypatch.setattr(handler, "table", table)
        monkeypatch.setattr(handler, "s3", s3)

        table.put_item(Item={"PK": f"ADMIN#{ADMIN}", "SK": "META", "email": ADMIN})
        yield {"table": table, "s3": s3}


def _event(method, path, body=None, email=ADMIN):
    return {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"email": email}}},
        },
        "body": json.dumps(body) if body is not None else None,
    }


def _call(method, path, body=None, email=ADMIN):
    response = handler.handler(_event(method, path, body, email), None)
    return response["statusCode"], json.loads(response["body"])


def _photo(aws, photo_id, session_id=SESSION, status="unlabeled", sha=None):
    key = f"raw/{session_id}/{photo_id}.jpg"
    aws["s3"].put_object(Bucket=BUCKET, Key=key, Body=b"raw-bytes")
    for name in handler.DERIVATIVE_NAMES:
        aws["s3"].put_object(
            Bucket=BUCKET, Key=f"derived/{photo_id}/{name}", Body=b"derived"
        )
    item = {
        "PK": f"PHOTO#{photo_id}",
        "SK": "META",
        "photoId": photo_id,
        "sessionId": session_id,
        "status": status,
        "createdAt": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
        "s3RawKey": key,
        "GSI1PK": f"SESSION#{session_id}",
        "GSI1SK": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
        "GSI2PK": f"STATUS#{status}",
        "GSI2SK": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
    }
    if sha:
        item["sha256"] = sha
        aws["table"].put_item(Item={"PK": f"SHA#{sha}", "SK": "META"})
    aws["table"].put_item(Item=item)
    return item


def _video(aws, photo_id, session_id=SESSION, status="unlabeled"):
    key = f"raw/{session_id}/{photo_id}.mp4"
    aws["s3"].put_object(Bucket=BUCKET, Key=key, Body=b"raw-video-bytes")
    item = {
        "PK": f"PHOTO#{photo_id}",
        "SK": "META",
        "photoId": photo_id,
        "sessionId": session_id,
        "status": status,
        "mediaType": "video",
        "createdAt": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
        "s3RawKey": key,
        "GSI1PK": f"SESSION#{session_id}",
        "GSI1SK": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
        "GSI2PK": f"STATUS#{status}",
        "GSI2SK": f"2026-08-24T11:00:00.{photo_id[-3:]}Z",
    }
    aws["table"].put_item(Item=item)
    return item


def _session(aws, session_id=SESSION, **extra):
    aws["table"].put_item(
        Item={
            "PK": f"SESSION#{session_id}",
            "SK": "META",
            "sessionId": session_id,
            "startedAt": "2026-08-24T11:00:00.000Z",
            **extra,
        }
    )


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


def test_non_allowlisted_email_is_rejected(aws):
    status, body = _call("GET", "/api/me", email="stranger@gmail.com")
    assert status == 403
    assert body["error"] == "not an admin"


def test_token_without_email_claim_is_rejected(aws):
    status, _ = _call("GET", "/api/me", email="")
    assert status == 401


def test_removing_an_admin_takes_effect_immediately(aws):
    aws["table"].put_item(
        Item={
            "PK": "ADMIN#second@example.com",
            "SK": "META",
            "email": "second@example.com",
        }
    )
    assert _call("GET", "/api/me", email="second@example.com")[0] == 200

    _call("DELETE", "/api/admins/second@example.com")

    assert _call("GET", "/api/me", email="second@example.com")[0] == 403


def test_admin_cannot_remove_themselves(aws):
    status, _ = _call("DELETE", f"/api/admins/{ADMIN}")
    assert status == 409


def test_unknown_route_is_404_and_wrong_method_is_405(aws):
    assert _call("GET", "/api/nope")[0] == 404
    assert _call("DELETE", "/api/queue")[0] == 405


# --------------------------------------------------------------------------
# Labeling
# --------------------------------------------------------------------------


def test_assign_session_labels_every_photo_and_indexes_them_by_cat(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _photo(aws, "01PHOTO00000000000000000B")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})

    status, body = _call(
        "POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]}
    )

    assert status == 200
    assert body["assigned"] == 2

    _, detail = _call("GET", f"/api/cats/{cat['catId']}")
    assert len(detail["photos"]) == 2
    assert detail["cat"]["photoCount"] == 2
    assert all(p["status"] == "labeled" for p in detail["photos"])


def test_duplicates_are_never_assigned_to_a_cat(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _photo(aws, "01PHOTO00000000000000000B", status="duplicate")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})

    _, body = _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    assert body["assigned"] == 1


def test_assigned_photos_leave_the_queue(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})

    assert _call("GET", "/api/queue")[1]["sessions"]

    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    assert _call("GET", "/api/queue")[1]["sessions"] == []


def test_unassign_returns_photos_to_the_queue(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    _call("POST", f"/api/sessions/{SESSION}/unassign")

    assert len(_call("GET", "/api/queue")[1]["sessions"]) == 1
    assert _call("GET", f"/api/cats/{cat['catId']}")[1]["cat"]["photoCount"] == 0


def test_assigning_to_an_unknown_cat_is_refused(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    status, _ = _call(
        "POST", f"/api/sessions/{SESSION}/assign", {"catId": "01NOSUCHCAT"}
    )
    assert status == 404


def test_cat_cannot_be_deleted_while_photos_point_at_it(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    status, _ = _call("DELETE", f"/api/cats/{cat['catId']}")

    assert status == 409


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------


def test_merge_moves_photos_but_never_rewrites_the_raw_s3_key(aws):
    _session(aws, SESSION)
    _session(aws, OTHER_SESSION)
    photo = _photo(aws, "01PHOTO00000000000000000A", session_id=SESSION)

    _, body = _call(
        "POST",
        "/api/sessions/merge",
        {"sourceSessionId": SESSION, "targetSessionId": OTHER_SESSION},
    )

    assert body["merged"] == 1
    moved = aws["table"].get_item(
        Key={"PK": "PHOTO#01PHOTO00000000000000000A", "SK": "META"}
    )["Item"]
    assert moved["sessionId"] == OTHER_SESSION
    assert moved["GSI1PK"] == f"SESSION#{OTHER_SESSION}"
    # raw/ is write-once (spec §6.2) — the object did not move, so neither
    # does the pointer to it.
    assert moved["s3RawKey"] == photo["s3RawKey"]
    assert f"/{SESSION}/" in moved["s3RawKey"]


def test_merging_into_a_labeled_session_inherits_its_cat(aws):
    _session(aws, SESSION)
    _session(aws, OTHER_SESSION)
    _photo(aws, "01PHOTO00000000000000000A", session_id=SESSION)
    _photo(aws, "01PHOTO00000000000000000B", session_id=OTHER_SESSION)
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})
    _call("POST", f"/api/sessions/{OTHER_SESSION}/assign", {"catId": cat["catId"]})

    _call(
        "POST",
        "/api/sessions/merge",
        {"sourceSessionId": SESSION, "targetSessionId": OTHER_SESSION},
    )

    assert _call("GET", f"/api/cats/{cat['catId']}")[1]["cat"]["photoCount"] == 2
    assert _call("GET", "/api/queue")[1]["sessions"] == []


def test_a_session_cannot_be_merged_into_itself(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    status, _ = _call(
        "POST",
        "/api/sessions/merge",
        {"sourceSessionId": SESSION, "targetSessionId": SESSION},
    )
    assert status == 400


def test_merge_is_not_read_as_a_session_id(aws):
    """The literal path /api/sessions/merge must beat /api/sessions/{id}."""
    _session(aws)
    status, body = _call("POST", "/api/sessions/merge", {})
    assert status == 400
    assert "required" in body["error"]


# --------------------------------------------------------------------------
# Reject — hard delete
# --------------------------------------------------------------------------


def test_reject_deletes_every_s3_version_and_the_records(aws):
    _session(aws)
    photo_id = "01PHOTO00000000000000000A"
    _photo(aws, photo_id, sha="deadbeef")
    # A second version of the raw object: a plain delete would leave this
    # one alive under a delete marker.
    aws["s3"].put_object(
        Bucket=BUCKET, Key=f"raw/{SESSION}/{photo_id}.jpg", Body=b"raw-bytes-v2"
    )

    status, _ = _call("POST", f"/api/photos/{photo_id}/reject")

    assert status == 200
    versions = aws["s3"].list_object_versions(Bucket=BUCKET)
    assert versions.get("Versions", []) == []
    assert versions.get("DeleteMarkers", []) == []
    assert "Item" not in aws["table"].get_item(
        Key={"PK": f"PHOTO#{photo_id}", "SK": "META"}
    )
    assert "Item" not in aws["table"].get_item(Key={"PK": "SHA#deadbeef", "SK": "META"})


def test_reject_leaves_the_telegram_idempotency_record_alone(aws):
    """Deleting it would let a webhook retry walk the photo back in."""
    _session(aws)
    photo_id = "01PHOTO00000000000000000A"
    _photo(aws, photo_id)
    aws["table"].put_item(
        Item={"PK": "TGMSG#123#456", "SK": "META", "photoId": photo_id}
    )

    _call("POST", f"/api/photos/{photo_id}/reject")

    assert "Item" in aws["table"].get_item(Key={"PK": "TGMSG#123#456", "SK": "META"})


def test_reject_session_deletes_all_of_its_photos(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _photo(aws, "01PHOTO00000000000000000B")

    _, body = _call("POST", f"/api/sessions/{SESSION}/reject")

    assert body["deleted"] == 2
    assert _call("GET", "/api/queue")[1]["sessions"] == []


def test_rejecting_an_unknown_photo_is_404(aws):
    assert _call("POST", "/api/photos/01NOPE/reject")[0] == 404


# --------------------------------------------------------------------------
# Queue shape
# --------------------------------------------------------------------------


def test_queue_returns_whole_sessions_not_just_queued_photos(aws):
    """A half-shown session invites half-labeling it."""
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A", status="unlabeled")
    _photo(aws, "01PHOTO00000000000000000B", status="duplicate")

    _, body = _call("GET", "/api/queue")

    assert len(body["sessions"]) == 1
    assert len(body["sessions"][0]["photos"]) == 2


def test_queue_photos_carry_presigned_derivative_urls(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")

    photo = _call("GET", "/api/queue")[1]["sessions"][0]["photos"][0]

    assert "thumb-256.webp" in photo["thumbUrl"]
    assert "medium-1024.webp" in photo["mediumUrl"]
    # Signed and time-boxed. The signature version differs between moto and
    # the real runtime, so assert on what both emit rather than on SigV4's
    # parameter names.
    assert "Signature" in photo["thumbUrl"]
    assert "Expires" in photo["thumbUrl"]


def test_cat_list_carries_a_cover_thumbnail(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")
    _photo(aws, "01PHOTO00000000000000000B")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    listed = _call("GET", "/api/cats")[1]["cats"][0]

    # Oldest photo of the cat, so the cover does not shuffle as more arrive.
    assert "derived/01PHOTO00000000000000000A/thumb-256.webp" in listed["coverUrl"]


def test_a_cat_with_no_photos_yet_has_no_cover(aws):
    _call("POST", "/api/cats", {"name": "Unphotographed"})

    assert _call("GET", "/api/cats")[1]["cats"][0]["coverUrl"] is None


def test_video_queue_item_carries_a_presigned_raw_url_not_derivatives(aws):
    _session(aws)
    _video(aws, "01VIDEO0000000000000000A")

    photo = _call("GET", "/api/queue")[1]["sessions"][0]["photos"][0]

    assert "videoUrl" in photo
    assert "raw/" in photo["videoUrl"]
    assert "thumbUrl" not in photo
    assert "mediumUrl" not in photo


def test_cat_cover_skips_a_video_and_falls_back_to_the_next_photo(aws):
    _session(aws)
    # Earliest media in the session is a video — no thumbnail to show.
    _video(aws, "01VIDEO0000000000000000A")
    _photo(aws, "01PHOTO0000000000000000B")
    _, cat = _call("POST", "/api/cats", {"name": "Ginger"})
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    listed = _call("GET", "/api/cats")[1]["cats"][0]

    assert "derived/01PHOTO0000000000000000B/thumb-256.webp" in listed["coverUrl"]


def test_a_cat_with_only_a_video_has_no_cover(aws):
    _session(aws)
    _video(aws, "01VIDEO0000000000000000A")
    _, cat = _call("POST", "/api/cats", {"name": "Video-only"})
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": cat["catId"]})

    assert _call("GET", "/api/cats")[1]["cats"][0]["coverUrl"] is None


def test_key_plumbing_is_not_leaked_to_the_client(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")

    photo = _call("GET", "/api/queue")[1]["sessions"][0]["photos"][0]

    assert not any(k.startswith("GSI") for k in photo)
    assert "PK" not in photo


# --------------------------------------------------------------------------
# Stats page and tracked links
# --------------------------------------------------------------------------


def test_insights_reads_photos_sessions_profiles_and_traffic(aws):
    _session(aws, SESSION, coarseLat=Decimal("31.262"), coarseLon=Decimal("34.801"))
    _session(aws, OTHER_SESSION)
    for photo_id, session_id in (
        ("01PHOTO0000000000000000001", SESSION),
        ("01PHOTO0000000000000000002", SESSION),
        ("01PHOTO0000000000000000003", OTHER_SESSION),
    ):
        item = _photo(aws, photo_id, session_id)
        aws["table"].update_item(
            Key={"PK": item["PK"], "SK": "META"},
            UpdateExpression="SET submitterHash = :h",
            ExpressionAttributeValues={":h": "a" * 64},
        )
    _photo(aws, "01PHOTO0000000000000000004", status="duplicate")
    aws["table"].put_item(
        Item={
            "PK": f"SUBMITTER#{'a' * 64}",
            "SK": "PROFILE",
            "submitterHash": "a" * 64,
            "referral": "poster",
            "channel": "telegram",
            "firstSeenAt": "2026-08-24T10:00:00.000Z",
            "GSI2PK": "ENTITY#SUBMITTER",
            "GSI2SK": "2026-08-24T10:00:00.000Z",
        }
    )
    aws["table"].put_item(
        Item={
            "PK": "TRAFFIC#2026-08-24#poster",
            "SK": "META",
            "day": "2026-08-24",
            "referral": "poster",
            "visits": 9,
            "visitors": 7,
            "botClicks": 3,
            "GSI2PK": "ENTITY#TRAFFIC",
            "GSI2SK": "2026-08-24#poster",
        }
    )

    status, body = _call("GET", "/api/insights")
    assert status == 200
    summary = body["summary"]
    assert summary["media"] == 3
    assert summary["duplicates"] == 1
    assert summary["sessions"] == 2
    assert summary["sessionsWithLocation"] == 1
    assert summary["contributors"] == 1

    (poster,) = [r for r in body["referrals"] if r["referral"] == "poster"]
    assert poster["visitors"] == 7
    assert poster["botClicks"] == 3
    assert poster["people"] == 1
    assert poster["media"] == 3


def test_links_can_be_created_labelled_and_given_partner_numbers(aws):
    status, _ = _call("POST", "/api/links", {"slug": "Friend-App", "label": "Friend"})
    assert status == 200

    status, body = _call(
        "PATCH",
        "/api/links/friend-app",
        {"partnerViews": 1200, "partnerPlays": 300, "partnerClicks": 45},
    )
    assert status == 200
    assert body["partnerReportedAt"]

    _, insights = _call("GET", "/api/insights")
    (row,) = [r for r in insights["referrals"] if r["referral"] == "friend-app"]
    assert row["link"]["label"] == "Friend"
    assert row["link"]["partnerViews"] == 1200
    assert row["link"]["partnerClicks"] == 45


def test_duplicate_link_slug_is_a_conflict(aws):
    _call("POST", "/api/links", {"slug": "poster", "label": "Poster"})
    status, _ = _call("POST", "/api/links", {"slug": "poster", "label": "Again"})
    assert status == 409


@pytest.mark.parametrize("slug", ["has space", "-dash", "x" * 33, "под"])
def test_bad_link_slugs_are_refused(aws, slug):
    status, _ = _call("POST", "/api/links", {"slug": slug, "label": "x"})
    assert status == 400


@pytest.mark.parametrize("value", [-1, 1.5, "12", True, 10**10])
def test_partner_numbers_must_be_whole_and_in_range(aws, value):
    _call("POST", "/api/links", {"slug": "friend", "label": "Friend"})
    status, _ = _call("PATCH", "/api/links/friend", {"partnerViews": value})
    assert status == 400


def test_updating_a_missing_link_is_404(aws):
    status, _ = _call("PATCH", "/api/links/ghost", {"label": "Boo"})
    assert status == 404


def test_deleting_a_link_keeps_its_traffic(aws):
    _call("POST", "/api/links", {"slug": "poster", "label": "Poster"})
    aws["table"].put_item(
        Item={
            "PK": "TRAFFIC#2026-08-24#poster",
            "SK": "META",
            "day": "2026-08-24",
            "referral": "poster",
            "visits": 2,
            "GSI2PK": "ENTITY#TRAFFIC",
            "GSI2SK": "2026-08-24#poster",
        }
    )
    assert _call("DELETE", "/api/links/poster")[0] == 200
    _, insights = _call("GET", "/api/insights")
    (row,) = [r for r in insights["referrals"] if r["referral"] == "poster"]
    assert row["link"] is None
    assert row["visits"] == 2
