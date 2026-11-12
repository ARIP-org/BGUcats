"""common.limits.take, against a moto table shaped like the project's."""

import boto3
import pytest
from moto import mock_aws

from common import limits
from common.api import ApiError

HOUR = 3600
NOW = 1_800_000_123.5


@pytest.fixture
def table():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        yield dynamodb.create_table(
            TableName="t",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )


def test_counts_down_to_the_limit_then_refuses(table):
    left = [limits.take(table, "U1#votes", 3, HOUR, now=NOW) for _ in range(3)]
    assert left == [2, 1, 0]
    with pytest.raises(ApiError) as err:
        limits.take(table, "U1#votes", 3, HOUR, now=NOW)
    assert err.value.status == 429
    assert err.value.code == "rate_limited"


def test_a_refusal_counts_nothing_and_says_when_to_come_back(table):
    for _ in range(2):
        limits.take(table, "U1#posts", 2, HOUR, now=NOW)
    for _ in range(3):
        with pytest.raises(ApiError) as err:
            limits.take(table, "U1#posts", 2, HOUR, now=NOW)
    pk, window_end = limits.rate_key("U1#posts", HOUR, NOW)
    item = table.get_item(Key={"PK": pk, "SK": "META"})["Item"]
    assert item["count"] == 2
    assert err.value.details["retryAfter"] == int(window_end - NOW) + 1


def test_the_next_window_starts_again(table):
    limits.take(table, "U1#likes", 1, HOUR, now=NOW)
    with pytest.raises(ApiError):
        limits.take(table, "U1#likes", 1, HOUR, now=NOW)
    assert limits.take(table, "U1#likes", 1, HOUR, now=NOW + HOUR) == 0


def test_people_and_actions_are_counted_apart(table):
    limits.take(table, "U1#likes", 1, HOUR, now=NOW)
    assert limits.take(table, "U2#likes", 1, HOUR, now=NOW) == 0
    assert limits.take(table, "U1#votes", 1, HOUR, now=NOW) == 0


def test_the_counter_expires_by_itself(table):
    limits.take(table, "U1#votes", 5, HOUR, now=NOW)
    pk, window_end = limits.rate_key("U1#votes", HOUR, NOW)
    assert pk == f"RATE#U1#votes#{int(NOW // HOUR) * HOUR}"
    item = table.get_item(Key={"PK": pk, "SK": "META"})["Item"]
    assert item["expiresAt"] == window_end + limits.KEEP_AFTER_WINDOW_S


def test_other_errors_are_not_mistaken_for_the_limit(table):
    table.delete()
    with pytest.raises(Exception) as err:
        limits.take(table, "U1#votes", 5, HOUR, now=NOW)
    assert not isinstance(err.value, ApiError)
