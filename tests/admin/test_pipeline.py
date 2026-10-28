"""End to end through the real pipeline code.

The store tests seed records in the shape ingest + process are *believed* to
leave them. This test removes the belief: photos go through the real ingest
write functions and the real process Lambda, and the labelling layer has to
work on whatever they actually produce — including a real exact-duplicate
verdict from the process Lambda.
"""

import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN_PARAM", "/bgucats/telegram/bot-token")
os.environ.setdefault(
    "TELEGRAM_WEBHOOK_SECRET_PARAM", "/bgucats/telegram/webhook-secret"
)
os.environ.setdefault("SUBMITTER_HASH_SALT_PARAM", "/bgucats/submitter-hash-salt")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from admin import local, store
from ingest import handler as ingest
from process import handler as process
from tests.admin.conftest import create_table

BUCKET = os.environ["MEDIA_BUCKET"]
WHEN = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def pipeline(monkeypatch):
    with mock_aws():
        table = create_table()
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(ingest, "table", table)
        monkeypatch.setattr(process, "table", table)
        monkeypatch.setattr(process, "s3", s3)
        yield table, s3


def encounter(table, s3, images, submitter="b" * 64):
    return local.seed_encounter(ingest, process, s3, BUCKET, images, submitter, WHEN)


def test_a_real_encounter_reaches_the_queue_processed(pipeline):
    table, s3 = pipeline
    sid, _ = encounter(table, s3, [local.synthetic_jpeg(i) for i in range(4)])

    q = store.queue(table)
    assert [e["session"]["sessionId"] for e in q["sessions"]] == [sid]
    assert len(q["sessions"][0]["unlabeled"]) == 4

    for photo in store.session_photos(table, sid):
        assert photo["status"] == "unlabeled"
        assert photo["processedAt"] and photo["phash"] and photo["sha256"]
        keys = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"derived/{photo['photoId']}/")
        names = {o["Key"].rsplit("/", 1)[1] for o in keys["Contents"]}
        assert names == {"thumb-256.webp", "medium-1024.webp"}


def test_assignment_writes_the_export_index(pipeline):
    table, s3 = pipeline
    sid, photo_ids = encounter(table, s3, [local.synthetic_jpeg(i) for i in range(3)])
    cat = store.create_cat(table, {"coatColor": "black", "coatPattern": "solid"})
    store.assign_session(table, sid, cat["catId"])

    exported = store.cat_photos(table, cat["catId"])
    assert sorted(p["photoId"] for p in exported) == sorted(photo_ids)
    assert store.queue(table)["sessions"] == []


def test_a_real_duplicate_verdict_keeps_the_copy_out_of_the_cat(pipeline):
    table, s3 = pipeline
    same = local.synthetic_jpeg(7)
    sid, _ = encounter(table, s3, [same, local.synthetic_jpeg(8), same])

    statuses = {p["photoId"]: p["status"] for p in store.session_photos(table, sid)}
    assert sorted(statuses.values()) == ["duplicate", "unlabeled", "unlabeled"]

    cat = store.create_cat(table, {"coatColor": "white", "coatPattern": "solid"})
    result = store.assign_session(table, sid, cat["catId"])
    assert result["labeled"] == 2
    assert result["skipped"] == {"duplicate": 1}
    assert store.get_cat(table, cat["catId"])["photoCount"] == 2


def test_the_session_counter_matches_what_was_ingested(pipeline):
    table, s3 = pipeline
    sid, _ = encounter(table, s3, [local.synthetic_jpeg(i) for i in range(5)])
    assert store.get_session(table, sid)["photoCount"] == 5
