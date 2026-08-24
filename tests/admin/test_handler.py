import json
import os

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


def test_key_plumbing_is_not_leaked_to_the_client(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000A")

    photo = _call("GET", "/api/queue")[1]["sessions"][0]["photos"][0]

    assert not any(k.startswith("GSI") for k in photo)
    assert "PK" not in photo
