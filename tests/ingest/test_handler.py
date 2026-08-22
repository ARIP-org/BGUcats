import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN_PARAM", "/bgucats/telegram/bot-token")
os.environ.setdefault(
    "TELEGRAM_WEBHOOK_SECRET_PARAM", "/bgucats/telegram/webhook-secret"
)
os.environ.setdefault("SUBMITTER_HASH_SALT_PARAM", "/bgucats/submitter-hash-salt")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from ingest import handler

TABLE_NAME = os.environ["TABLE_NAME"]


@pytest.fixture
def dynamo_table(monkeypatch):
    """A moto-backed table swapped in for handler.table.

    handler.py's own `table` global was bound at import time, before this
    fixture's mock is active, so it points at real AWS — monkeypatching it
    to a freshly-created mocked Table is what actually redirects the
    handler's DynamoDB calls.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        monkeypatch.setattr(handler, "table", table)
        yield table


def test_new_submitter_opens_session(dynamo_table):
    session_id = handler._resolve_or_open_session("hash-a", None)
    assert session_id


def test_second_call_within_idle_window_reuses_session(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    second = handler._resolve_or_open_session("hash-a", None)
    assert first == second


def test_call_after_idle_window_opens_new_session(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = handler._resolve_or_open_session("hash-a", None)
    assert second != first


def test_media_group_reuses_session_even_past_idle_window(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", "mg-1")
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = handler._resolve_or_open_session("hash-a", "mg-1")
    assert second == first


def test_different_submitters_get_different_sessions(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    second = handler._resolve_or_open_session("hash-b", None)
    assert first != second


def test_retry_of_same_telegram_message_reuses_photo_and_session(dynamo_table):
    photo_id_1, session_id_1 = handler._resolve_photo_and_session(
        111, 222, "hash-b", None
    )
    photo_id_2, session_id_2 = handler._resolve_photo_and_session(
        111, 222, "hash-b", None
    )
    assert photo_id_1 == photo_id_2
    assert session_id_1 == session_id_2


def test_different_message_gets_a_different_photo(dynamo_table):
    photo_id_1, _ = handler._resolve_photo_and_session(111, 222, "hash-b", None)
    photo_id_2, _ = handler._resolve_photo_and_session(111, 223, "hash-b", None)
    assert photo_id_1 != photo_id_2


def test_rate_limit_allows_up_to_threshold_then_blocks(dynamo_table):
    for _ in range(handler.RATE_LIMIT_PER_MINUTE):
        assert handler._check_rate_limit("hash-c") is True
    assert handler._check_rate_limit("hash-c") is False


def test_rate_limit_is_scoped_per_submitter(dynamo_table):
    for _ in range(handler.RATE_LIMIT_PER_MINUTE):
        handler._check_rate_limit("hash-d")
    assert handler._check_rate_limit("hash-d") is False
    assert handler._check_rate_limit("hash-e") is True


def test_sniff_image_type_jpeg():
    assert handler._sniff_image_type(b"\xff\xd8\xff\xe0rest-of-file") == (
        "image/jpeg",
        "jpg",
    )


def test_sniff_image_type_png():
    assert handler._sniff_image_type(b"\x89PNG\r\n\x1a\nrest-of-file") == (
        "image/png",
        "png",
    )


def test_sniff_image_type_rejects_non_image_bytes():
    assert handler._sniff_image_type(b"not an image") is None
