"""The Cognito pre-sign-up trigger: whether an account is made at all."""

import boto3
import pytest
from moto import mock_aws

import tests.admin.test_handler  # noqa: F401  (sets the env the handler reads)
from admin import presignup


def signup(email):
    return {"request": {"userAttributes": {"email": email}}, "response": {}}


@pytest.fixture
def allowlist(monkeypatch):
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="presignup-test",
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
        table.put_item(Item={"PK": "ADMIN#listed@gmail.com", "SK": "META"})
        monkeypatch.setattr(presignup, "table", table)
        monkeypatch.setattr(presignup, "SIGNUP_POLICY", "allowlist")
        monkeypatch.setattr(
            presignup, "SIGNUP_DOMAINS", ("post.bgu.ac.il", "bgu.ac.il")
        )
        yield


def test_someone_on_the_allowlist_gets_an_account(allowlist):
    event = presignup.handler(signup("Listed@Gmail.com"), None)
    assert event["response"] == {"autoConfirmUser": True, "autoVerifyEmail": True}


def test_anyone_else_is_refused_under_the_allowlist(allowlist):
    with pytest.raises(presignup.SignUpBlocked) as err:
        presignup.handler(signup("student@post.bgu.ac.il"), None)
    assert "cannot sign in to BGU Cats yet" in str(err.value)


def test_the_domain_policy_admits_bgu_accounts(allowlist, monkeypatch):
    monkeypatch.setattr(presignup, "SIGNUP_POLICY", "domain")
    presignup.handler(signup("student@post.bgu.ac.il"), None)
    presignup.handler(signup("staff@bgu.ac.il"), None)
    with pytest.raises(presignup.SignUpBlocked):
        presignup.handler(signup("someone@gmail.com"), None)


def test_an_account_with_no_email_is_refused(allowlist):
    with pytest.raises(presignup.SignUpBlocked):
        presignup.handler(signup(""), None)
