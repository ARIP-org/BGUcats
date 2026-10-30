import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN_PARAM", "/bgucats/telegram/bot-token")
os.environ.setdefault(
    "TELEGRAM_WEBHOOK_SECRET_PARAM", "/bgucats/telegram/webhook-secret"
)
os.environ.setdefault("SUBMITTER_HASH_SALT_PARAM", "/bgucats/submitter-hash-salt")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN_PARAM", "/bgucats/whatsapp/access-token")
os.environ.setdefault("WHATSAPP_APP_SECRET_PARAM", "/bgucats/whatsapp/app-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN_PARAM", "/bgucats/whatsapp/verify-token")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from ingest import core

TABLE_NAME = os.environ["TABLE_NAME"]


@pytest.fixture
def dynamo_table(monkeypatch):
    """A moto-backed table swapped in for core.table.

    core.py's own `table` global was bound at import time, before this
    fixture's mock is active, so it points at real AWS — monkeypatching it
    to a freshly-created mocked Table is what actually redirects every
    adapter's DynamoDB calls, since they all go through core.
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
        monkeypatch.setattr(core, "table", table)
        yield table
