import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws
from ulid import ULID

TABLE_NAME = "bgucats-data-test"


def _index(n):
    return {
        "IndexName": f"GSI{n}",
        "KeySchema": [
            {"AttributeName": f"GSI{n}PK", "KeyType": "HASH"},
            {"AttributeName": f"GSI{n}SK", "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "ALL"},
    }


def create_table():
    """The real table shape — mirrors infra/main/dynamodb.tf."""
    client = boto3.client("dynamodb", region_name="us-east-1")
    attributes = ["PK", "SK"] + [f"GSI{n}{k}" for n in (1, 2, 3) for k in ("PK", "SK")]
    client.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in attributes
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[_index(n) for n in (1, 2, 3)],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)


@pytest.fixture
def table():
    with mock_aws():
        yield create_table()


class Seeder:
    """Writes sessions and photos in exactly the shape ingest + process leave
    them in (see src/ingest/handler.py _mark_photo_unlabeled and
    src/process/handler.py _record_results). The integration test checks this
    against the real handlers."""

    def __init__(self, table):
        self.table = table
        self.clock = 0

    def tick(self):
        self.clock += 1
        return f"2026-03-01T12:{self.clock // 60:02d}:{self.clock % 60:02d}.000000Z"

    def session(self, photos=3, status="unlabeled"):
        session_id = str(ULID())
        started = self.tick()
        self.table.put_item(
            Item={
                "PK": f"SESSION#{session_id}",
                "SK": "META",
                "sessionId": session_id,
                "submitterHash": "a" * 64,
                "source": "bot",
                "startedAt": started,
                "lastPhotoAt": started,
                "photoCount": photos,
                "catId": None,
                "notes": None,
                "explicit": False,
            }
        )
        ids = [self.photo(session_id, status=status) for _ in range(photos)]
        return session_id, ids

    def photo(self, session_id, status="unlabeled"):
        photo_id = str(ULID())
        created = self.tick()
        item = {
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "sessionId": session_id,
            "source": "bot",
            "status": status,
            "catId": None,
            "createdAt": created,
            "processedAt": created,
        }
        if status != "pending":
            item.update(
                GSI1PK=f"SESSION#{session_id}",
                GSI1SK=created,
                GSI2PK=f"STATUS#{status}",
                GSI2SK=created,
            )
        self.table.put_item(Item=item)
        return photo_id

    def get(self, pk):
        return self.table.get_item(Key={"PK": pk, "SK": "META"}).get("Item")


@pytest.fixture
def seed(table):
    return Seeder(table)
