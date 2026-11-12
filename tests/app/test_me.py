"""The member API's first routes: who you are, and the terms (F4)."""

import json

import boto3
import pytest
from moto import mock_aws

from app import handler

ADMIN = "admin@example.com"
HELPER = "helper@example.com"
STUDENT = "maya.levi@post.bgu.ac.il"


def _table(dynamodb, name):
    """A table shaped like both of the project's: PK/SK and GSI1-3."""
    names = ["PK", "SK"] + [f"GSI{n}{k}" for n in (1, 2, 3) for k in ("PK", "SK")]
    return dynamodb.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in names
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": f"GSI{n}",
                "KeySchema": [
                    {"AttributeName": f"GSI{n}PK", "KeyType": "HASH"},
                    {"AttributeName": f"GSI{n}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for n in (1, 2, 3)
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws(monkeypatch):
    """Both tables in moto. handler.py binds its tables at import time,
    before moto is active, so they are replaced here."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        data = _table(dynamodb, handler.DATA_TABLE_NAME)
        social = _table(dynamodb, handler.SOCIAL_TABLE_NAME)
        data.put_item(Item={"PK": f"ADMIN#{ADMIN}", "SK": "META", "email": ADMIN})
        data.put_item(
            Item={
                "PK": f"ADMIN#{HELPER}",
                "SK": "META",
                "email": HELPER,
                "role": "collaborator",
            }
        )
        monkeypatch.setattr(handler, "data_table", data)
        monkeypatch.setattr(handler, "s3", boto3.client("s3", region_name="us-east-1"))
        monkeypatch.setattr(handler, "MEDIA_BUCKET", "bgucats-media-test")
        monkeypatch.setattr(handler, "social_table", social)
        monkeypatch.setattr(handler, "SOCIAL", True)
        monkeypatch.setattr(handler, "SIGNUP_POLICY", "allowlist")
        monkeypatch.setattr(handler, "SIGNUP_DOMAINS", ("post.bgu.ac.il", "bgu.ac.il"))
        monkeypatch.setattr(handler, "TERMS_VERSION", "2026-11")
        monkeypatch.setattr(handler, "FLAGS", {"social": True})
        yield {"data": data, "social": social}


def call(method, path, body=None, email=ADMIN, name=None):
    claims = {"email": email}
    if name:
        claims["name"] = name
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": claims}},
        },
        "body": json.dumps(body) if body is not None else None,
    }
    answer = handler.handler(event, None)
    return answer["statusCode"], json.loads(answer["body"])


def items(table):
    return table.scan()["Items"]


# ------------------------------------------------------------- the account


def test_the_first_call_makes_the_account(aws):
    status, me = call("GET", "/api/v1/me", email=HELPER, name="Helper Person")
    assert status == 200
    assert me["email"] == HELPER
    assert me["role"] == "user"  # stored "collaborator" (R1)
    assert me["displayName"] == "Helper Person"
    assert me["username"] == "helper"
    assert len(me["inviteCode"]) == 10
    assert me["flags"] == {"social": True}
    keys = {(i["PK"].split("#")[0], i["SK"]) for i in items(aws["social"])}
    assert keys == {
        ("IDENTITY", "META"),
        ("USER", "PROFILE"),
        ("USERNAME", "META"),
        ("INVITE", "META"),
    }


def test_the_next_call_finds_the_same_account(aws):
    first = call("GET", "/api/v1/me")[1]
    again = call("GET", "/api/v1/me")[1]
    assert again["userId"] == first["userId"]
    assert len(items(aws["social"])) == 4


def test_an_admin_is_an_admin(aws):
    assert call("GET", "/api/v1/me")[1]["role"] == "admin"


def test_a_taken_username_gets_digits(aws):
    aws["social"].put_item(
        Item={"PK": "USERNAME#helper", "SK": "META", "userId": "someone"}
    )
    me = call("GET", "/api/v1/me", email=HELPER)[1]
    assert me["username"].startswith("helper") and me["username"] != "helper"
    assert me["username"][len("helper") :].isdigit()


def test_two_first_calls_at_once_make_one_account(aws, monkeypatch):
    # The second call finds no identity, then loses the race to write it.
    winner = call("GET", "/api/v1/me")[1]
    real_get_one = handler.tables.get_one
    seen = {"misses": 0}

    def stale_once(table, pk, sk="META"):
        if pk.startswith("IDENTITY#") and seen["misses"] == 0:
            seen["misses"] += 1
            return None
        return real_get_one(table, pk, sk)

    monkeypatch.setattr(handler.tables, "get_one", stale_once)
    loser = call("GET", "/api/v1/me")[1]
    assert loser["userId"] == winner["userId"]
    assert len([i for i in items(aws["social"]) if i["SK"] == "PROFILE"]) == 1


@pytest.mark.parametrize(
    ("email", "username"),
    [
        ("Maya.Levi+cats@post.bgu.ac.il", "maya.levi"),
        ("a@x.com", "acat"),
        ("--__--@x.com", "cat"),
        ("verylongaddressname123456@x.com", "verylongaddressn"),
        ("ad..min@x.com", "ad.min"),
    ],
)
def test_the_first_username_comes_from_the_address(email, username):
    assert handler.username_base(email) == username


def test_a_reserved_name_is_never_given(aws, monkeypatch):
    me = call("GET", "/api/v1/me", email="admin@example.com")[1]
    assert me["username"] != "admin"


# ------------------------------------------------------- who is let in


def test_a_stranger_is_refused_and_no_account_is_made(aws):
    status, body = call("GET", "/api/v1/me", email="stranger@gmail.com")
    assert (status, body["code"]) == (403, "not_admitted")
    assert items(aws["social"]) == []


def test_the_domain_policy_lets_bgu_students_in(aws, monkeypatch):
    monkeypatch.setattr(handler, "SIGNUP_POLICY", "domain")
    status, me = call("GET", "/api/v1/me", email=STUDENT)
    assert (status, me["role"], me["username"]) == (200, "user", "maya.levi")


def test_leaving_the_allowlist_shuts_the_account_out(aws):
    assert call("GET", "/api/v1/me", email=HELPER)[0] == 200
    aws["data"].delete_item(Key={"PK": f"ADMIN#{HELPER}", "SK": "META"})
    assert call("GET", "/api/v1/me", email=HELPER)[0] == 403


def test_a_banned_account_is_refused(aws):
    me = call("GET", "/api/v1/me", email=HELPER)[1]
    aws["social"].update_item(
        Key={"PK": f"USER#{me['userId']}", "SK": "PROFILE"},
        UpdateExpression="SET #s = :b",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":b": "banned"},
    )
    status, body = call("GET", "/api/v1/me", email=HELPER)
    assert (status, body["code"]) == (403, "banned")


def test_no_email_claim_is_a_401(aws):
    event = {"requestContext": {"http": {"method": "GET", "path": "/api/v1/me"}}}
    assert handler.handler(event, None)["statusCode"] == 401


# ------------------------------------------------------------ the flag


def test_with_social_off_every_route_is_404_and_nothing_is_written(aws, monkeypatch):
    monkeypatch.setattr(handler, "SOCIAL", False)
    for method, path in (("GET", "/api/v1/me"), ("POST", "/api/v1/me/terms")):
        status, body = call(method, path, {"version": "2026-11"})
        assert (status, body["code"]) == (404, "not_found")
    assert items(aws["social"]) == []


def test_an_unknown_route_makes_no_account(aws):
    assert call("GET", "/api/v1/nothing")[0] == 404
    assert items(aws["social"]) == []


# ------------------------------------------------------------ the terms


def test_terms_are_required_until_accepted(aws):
    me = call("GET", "/api/v1/me")[1]
    assert me["terms"] == {"current": "2026-11", "accepted": None, "required": True}
    status, me = call("POST", "/api/v1/me/terms", {"version": "2026-11"})
    assert status == 200
    assert me["terms"]["required"] is False
    assert call("GET", "/api/v1/me")[1]["terms"]["accepted"] == "2026-11"


def test_accepting_old_terms_is_refused(aws):
    status, body = call("POST", "/api/v1/me/terms", {"version": "2025-01"})
    assert (status, body["code"]) == (409, "stale_terms")


def test_new_terms_ask_again(aws, monkeypatch):
    call("POST", "/api/v1/me/terms", {"version": "2026-11"})
    monkeypatch.setattr(handler, "TERMS_VERSION", "2027-01")
    assert call("GET", "/api/v1/me")[1]["terms"]["required"] is True


def test_require_terms_refuses_a_write_before_them(aws):
    user = {"termsVersion": None}
    with pytest.raises(handler.ApiError) as err:
        handler.require_terms(user)
    assert err.value.code == "terms_required"
