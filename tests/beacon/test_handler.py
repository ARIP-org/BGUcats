import base64
import json
import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("SITE_ORIGIN", "https://site.example")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from beacon import handler

TABLE_NAME = os.environ["TABLE_NAME"]
ORIGIN = os.environ["SITE_ORIGIN"]


@pytest.fixture
def table(monkeypatch):
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
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
        mocked = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        monkeypatch.setattr(handler, "table", mocked)
        yield mocked


def _beacon(body, origin=ORIGIN):
    return {
        "headers": {"Origin": origin} if origin else {},
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def _items(table):
    return table.scan()["Items"]


def _today():
    return handler.datetime.now(handler.LOCAL_TZ).date().isoformat()


def test_a_visit_counts_once_and_a_first_visit_also_counts_a_visitor(table):
    assert handler.handler(
        _beacon({"event": "visit", "referral": "poster", "firstToday": True}), None
    ) == {"statusCode": 204}
    handler.handler(_beacon({"event": "visit", "referral": "poster"}), None)

    (item,) = _items(table)
    assert item["PK"] == f"TRAFFIC#{_today()}#poster"
    assert item["visits"] == 2
    assert item["visitors"] == 1
    assert item["GSI2PK"] == "ENTITY#TRAFFIC"
    assert item["GSI2SK"] == f"{_today()}#poster"


def test_bot_clicks_count_separately_on_the_same_day_item(table):
    handler.handler(_beacon({"event": "visit", "referral": "poster"}), None)
    handler.handler(_beacon({"event": "bot_click", "referral": "poster"}), None)
    (item,) = _items(table)
    assert item["visits"] == 1
    assert item["botClicks"] == 1
    assert "visitors" not in item


def test_first_today_only_applies_to_visits(table):
    handler.handler(
        _beacon({"event": "bot_click", "referral": "x", "firstToday": True}), None
    )
    assert "visitors" not in _items(table)[0]


def test_first_today_must_be_a_real_boolean(table):
    handler.handler(
        _beacon({"event": "visit", "referral": "x", "firstToday": "yes"}), None
    )
    assert "visitors" not in _items(table)[0]


@pytest.mark.parametrize("referral", [None, "", "Has Space", "../etc", "x" * 40, 7])
def test_missing_or_malformed_referrals_count_as_direct(table, referral):
    handler.handler(_beacon({"event": "visit", "referral": referral}), None)
    assert _items(table)[0]["referral"] == "direct"


def test_referral_is_lowercased(table):
    handler.handler(_beacon({"event": "visit", "referral": "Poster"}), None)
    assert _items(table)[0]["referral"] == "poster"


@pytest.mark.parametrize(
    "event",
    [
        _beacon({"event": "visit"}, origin="https://evil.example"),
        _beacon({"event": "visit"}, origin=None),
        _beacon({"event": "photo"}),
        _beacon("not json"),
        _beacon("[1, 2]"),
        _beacon({"event": "visit", "pad": "x" * 600}),
        {"headers": {"origin": ORIGIN}, "body": "%%%", "isBase64Encoded": True},
    ],
)
def test_anything_else_is_dropped_quietly(table, event):
    assert handler.handler(event, None) == {"statusCode": 204}
    assert _items(table) == []


def test_base64_bodies_are_decoded(table):
    body = base64.b64encode(json.dumps({"event": "visit"}).encode()).decode()
    handler.handler(
        {"headers": {"origin": ORIGIN}, "body": body, "isBase64Encoded": True}, None
    )
    assert _items(table)[0]["visits"] == 1


def test_a_storage_error_still_returns_204(monkeypatch):
    class Broken:
        def update_item(self, **_):
            raise RuntimeError("dynamodb is down")

    monkeypatch.setattr(handler, "table", Broken())
    assert handler.handler(_beacon({"event": "visit"}), None) == {"statusCode": 204}
