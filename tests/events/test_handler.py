"""src/events/handler.py: sorting changes by kind, and failing one record
without failing the batch around it."""

import json
import logging

import boto3
import pytest
from moto import mock_aws

from events import handler


def change(pk, sk, sequence="1", name="INSERT"):
    return {
        "eventName": name,
        "dynamodb": {
            "Keys": {"PK": {"S": pk}, "SK": {"S": sk}},
            "SequenceNumber": sequence,
        },
    }


def summary(caplog):
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("{")]
    return json.loads(lines[-1])


def test_a_batch_is_counted_by_kind(caplog):
    caplog.set_level(logging.INFO)
    event = {
        "Records": [
            change("POST#P1", "META", "1"),
            change("POST#P2", "META", "2", "MODIFY"),
            change("CAT#C1", "VOTE#U1", "3"),
            change("USER#U1", "FRIEND#U2", "4"),
        ]
    }
    assert handler.handler(event, None) == {"batchItemFailures": []}
    assert summary(caplog) == {
        "records": 4,
        "kinds": {
            "friend:INSERT": 1,
            "post:INSERT": 1,
            "post:MODIFY": 1,
            "vote:INSERT": 1,
        },
        "failed": 0,
    }


def test_one_failing_record_is_reported_alone(monkeypatch):
    def broken(record):
        if record["dynamodb"]["SequenceNumber"] == "2":
            raise RuntimeError("boom")

    monkeypatch.setitem(handler.HANDLERS, "post", broken)
    event = {"Records": [change("POST#A", "META", "1"), change("POST#B", "META", "2")]}
    assert handler.handler(event, None) == {
        "batchItemFailures": [{"itemIdentifier": "2"}]
    }


def test_a_change_no_kind_matches_is_skipped_not_retried(caplog):
    result = handler.handler({"Records": [change("ODD#1", "META")]}, None)
    assert result == {"batchItemFailures": []}
    assert "no kind for a change to ODD / META" in caplog.text


def test_the_log_names_kinds_not_people(caplog):
    caplog.set_level(logging.INFO)
    handler.handler(
        {"Records": [change("USER#01JSECRET", "PROFILE"), change("X#y", "Z#z")]}, None
    )
    assert "01JSECRET" not in caplog.text
    assert "no kind for a change to X / Z" in caplog.text
    assert "#y" not in caplog.text and "#z" not in caplog.text


def test_an_empty_event_is_fine():
    assert handler.handler({}, None) == {"batchItemFailures": []}


@pytest.fixture
def social():
    """A table shaped like bgucats-social, with its stream, in moto."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="bgucats-social-test",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            StreamSpecification={
                "StreamEnabled": True,
                "StreamViewType": "NEW_AND_OLD_IMAGES",
            },
        )
        yield table


def test_records_as_the_stream_gives_them(social, caplog, monkeypatch):
    # The record shape is DynamoDB's, not one written by hand above.
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(handler, "social_table", social)
    social.put_item(Item={"PK": "POST#P1", "SK": "META", "status": "draft"})
    social.update_item(
        Key={"PK": "POST#P1", "SK": "META"},
        UpdateExpression="SET #s = :v",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":v": "removed"},
    )
    streams = boto3.client("dynamodbstreams", region_name="us-east-1")
    shard = streams.describe_stream(StreamArn=social.latest_stream_arn)[
        "StreamDescription"
    ]["Shards"][0]["ShardId"]
    iterator = streams.get_shard_iterator(
        StreamArn=social.latest_stream_arn,
        ShardId=shard,
        ShardIteratorType="TRIM_HORIZON",
    )["ShardIterator"]
    records = streams.get_records(ShardIterator=iterator)["Records"]
    assert handler.handler({"Records": records}, None) == {"batchItemFailures": []}
    assert summary(caplog)["kinds"] == {"post:INSERT": 1, "post:MODIFY": 1}
