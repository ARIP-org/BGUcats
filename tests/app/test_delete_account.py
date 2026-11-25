"""Deleting an account (B10a): `DELETE /me` and the events Lambda's job
(docs/app-plan/03-data-model.md, "Deleting an account"; D14).

The milestone's own test: a seeded person who has done everything is
deleted; the social table then holds their user id nowhere, every counter
they touched is what a recount gives, and the job run again, a step at a
time, ends in the same tables.

Runs the member API, the desk's API and the events Lambda together, with
tests/events/stream.py standing in for the table's stream.
"""

import io
import json
import re
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from PIL import Image

import recount
from app import handler
from events import handler as events

from .test_encounters import (  # noqa: F401  (the fixture)
    BAMBA,
    BUCKET,
    PHOTO,
    POST,
    SECOND,
    SECOND_PHOTO,
    SESSION,
    SIMBA,
    campus,
    desk_call,
    encounter,
    get,
    pick,
    post,
)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)

THIRD = "third@example.com"
FOURTH = "fourth@example.com"
THIRD_SESSION = "01JD0000000000000000000SE3"
THIRD_PHOTO = "01JD0000000000000000000PH3"
ADMINS_POST = "01JD0000000000000000000PS2"
PROPOSAL = "01JD0000000000000000000PR1"
REPORT_BY = "01JD0000000000000000000RP1"
REPORT_OF = "01JD0000000000000000000RP2"
PHONE = "phone-0001"


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(out, "JPEG")
    return out.getvalue()


def scan(table):
    items, start = [], None
    while True:
        page = table.scan(**({"ExclusiveStartKey": start} if start else {}))
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def holding(table, needle):
    """(PK, SK, attribute) of every place `needle` appears in the table."""
    found = set()
    for item in scan(table):
        for name, value in item.items():
            if needle in str(value):
                found.add((item["PK"], item["SK"], name))
    return found


@pytest.fixture
def everything(campus, monkeypatch):  # noqa: F811
    """HELPER has done everything the app lets a person do."""
    monkeypatch.setattr(
        handler, "FLAGS", {"social": True, "gpa": True, "feeding": True}
    )
    for who in (THIRD, FOURTH):
        campus["data"].put_item(
            Item={"PK": f"ADMIN#{who}", "SK": "META", "email": who, "role": "user"}
        )
        call("POST", "/api/v1/me/terms", {"version": "2026-11"}, email=who)
    me = {
        who: call("GET", "/api/v1/me", email=who)[1]
        for who in (ADMIN, HELPER, THIRD, FOURTH)
    }
    ids = {who: m["userId"] for who, m in me.items()}

    def ok(answer):
        status, body = answer
        assert status == 200, body
        return body

    # An encounter, picked and posted, and one the admin posted.
    encounter(campus)
    pick(SIMBA)
    ok(post(campus))
    encounter(campus, SECOND, SECOND_PHOTO, email=ADMIN)
    pick(BAMBA, SECOND, email=ADMIN)
    ok(
        call(
            "POST",
            "/api/v1/posts",
            {
                "postId": ADMINS_POST,
                "sessionId": SECOND,
                "photoIds": [SECOND_PHOTO],
                "claim": {"catId": BAMBA},
            },
            email=ADMIN,
        )
    )
    # A new cat proposed from a third encounter.
    encounter(campus, THIRD_SESSION, THIRD_PHOTO)
    ok(
        call(
            "POST",
            "/api/v1/proposals",
            {
                "proposalId": PROPOSAL,
                "sessionId": THIRD_SESSION,
                "nameIdea": "Hummus",
                "coat": "ginger",
                "regionId": "library",
                "traits": ["kitten"],
            },
            email=HELPER,
        )
    )
    campus["stream"].settle()
    # Likes both ways.
    ok(call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN))
    ok(call("PUT", f"/api/v1/posts/{ADMINS_POST}/like", email=HELPER))
    # A name suggested, which someone else voted for too, and a vote.
    ok(call("POST", f"/api/v1/cats/{SIMBA}/names", {"name": "Mango"}, email=HELPER))
    campus["stream"].settle()
    ok(call("PUT", f"/api/v1/cats/{SIMBA}/vote", {"nameKey": "mango"}, email=ADMIN))
    ok(call("PUT", f"/api/v1/cats/{BAMBA}/vote", {"nameKey": "bamba"}, email=HELPER))
    ok(call("PUT", f"/api/v1/cats/{BAMBA}/vote", {"nameKey": "bamba"}, email=THIRD))
    # A feeding.
    ok(
        call(
            "POST",
            f"/api/v1/cats/{SIMBA}/feedings",
            {"feedingId": "01JF" + "0" * 22},
            email=HELPER,
        )
    )
    # A friend, a request (no route writes one yet, D4), a block each way.
    ok(call("POST", f"/api/v1/invites/{me[ADMIN]['inviteCode']}/accept", email=HELPER))
    campus["social"].put_item(
        Item={
            "PK": f"USER#{ids[HELPER]}",
            "SK": f"FREQ#IN#{ids[FOURTH]}",
            "at": "2026-11-20T00:00:00Z",
        }
    )
    campus["social"].put_item(
        Item={
            "PK": f"USER#{ids[FOURTH]}",
            "SK": f"FREQ#OUT#{ids[HELPER]}",
            "at": "2026-11-20T00:00:00Z",
        }
    )
    ok(call("PUT", f"/api/v1/blocks/{ids[THIRD]}", email=HELPER))
    ok(call("PUT", f"/api/v1/blocks/{ids[HELPER]}", email=FOURTH))
    # A report by them, and one about them.
    ok(
        call(
            "POST",
            "/api/v1/reports",
            {
                "reportId": REPORT_BY,
                "targetType": "post",
                "targetId": ADMINS_POST,
                "reason": "spam",
            },
            email=HELPER,
        )
    )
    ok(
        call(
            "POST",
            "/api/v1/reports",
            {
                "reportId": REPORT_OF,
                "targetType": "user",
                "targetId": ids[HELPER],
                "reason": "spam",
            },
            email=THIRD,
        )
    )
    # A phone, and a profile photo.
    ok(
        call(
            "PUT",
            f"/api/v1/me/devices/{PHONE}",
            {"apnsToken": "ab" * 32, "environment": "production"},
            email=HELPER,
        )
    )
    started = ok(call("POST", "/api/v1/me/avatar", email=HELPER))
    campus["s3"].put_object(
        Bucket=BUCKET,
        Key=started["upload"]["fields"]["key"],
        Body=jpeg(),
        ContentType="image/jpeg",
    )
    ok(call("POST", f"/api/v1/me/avatar/{started['avatarId']}/complete", email=HELPER))
    campus["stream"].settle()

    mine = {
        i["SK"].split("#")[0]
        for i in campus["social"].query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"USER#{ids[HELPER]}"},
        )["Items"]
    }
    # Everything this test claims was done, so a later change to the
    # routes cannot quietly make it test less.
    assert {
        "PROFILE",
        "ENC",
        "MET",
        "METM",
        "STATS",
        "BADGE",
        "FED",
        "FEDCAT",
        "FRIEND",
        "FREQ",
        "BLOCK",
        "BLOCKEDBY",
        "DEVICE",
    } <= mine
    assert get(campus["social"], f"USER#{ids[HELPER]}", "PROFILE")["avatarKey"]
    assert (
        get(campus["social"], f"CAT#{SIMBA}", "NAME#mango")["suggestedBy"]
        == ids[HELPER]
    )
    assert get(campus["social"], f"POST#{POST}", "META")["status"] == "visible"
    assert not recount.differences(scan(campus["social"]))
    campus["ids"] = ids
    return campus


def delete(email=HELPER, body=None):
    return call(
        "DELETE",
        "/api/v1/me",
        {"confirm": "delete"} if body is None else body,
        email=email,
    )


def avatars(world, user_id):
    listing = world["s3"].list_object_versions(
        Bucket=BUCKET, Prefix=f"avatars/{user_id}/"
    )
    return listing.get("Versions", []) + listing.get("DeleteMarkers", [])


def test_deleting_asks_to_be_sure(everything):
    status, body = delete(body={})
    assert (status, body["code"]) == (400, "confirm")
    status, body = delete(body={"confirm": "yes"})
    assert status == 400
    assert call("GET", "/api/v1/me", email=HELPER)[0] == 200


def test_after_deletion_nothing_in_the_app_names_the_person(everything):
    world, me = everything, everything["ids"][HELPER]
    assert avatars(world, me)
    status, body = delete()
    assert (status, body) == (200, {"deleting": True})
    # From now on every call by them, a second deletion too, is `gone`.
    for method, path in (
        ("GET", "/api/v1/me"),
        ("DELETE", "/api/v1/me"),
        ("GET", "/api/v1/feed"),
    ):
        status, body = call(method, path, {"confirm": "delete"}, email=HELPER)
        assert (status, body["code"]) == (403, "gone"), path
    # The photo is gone at once: only the member API may touch the bucket.
    assert avatars(world, me) == []

    world["stream"].settle()

    assert holding(world["social"], me) == set()
    assert holding(world["social"], HELPER) == set()
    assert recount.differences(scan(world["social"])) == []

    social = world["social"]
    # Their post is removed, with no author; the admin's like went with it.
    theirs = get(social, f"POST#{POST}", "META")
    assert (theirs["status"], theirs["hiddenReason"], int(theirs["likeCount"])) == (
        "removed",
        "deleted",
        0,
    )
    assert "GSI2PK" not in theirs and "GSI1PK" not in theirs
    assert get(social, f"POST#{POST}", f"LIKE#{world['ids'][ADMIN]}") is None
    # Their like on the admin's post is taken back, with the cat's count.
    admins = get(social, f"POST#{ADMINS_POST}", "META")
    assert int(admins["likeCount"]) == 0
    simba, bamba = (
        get(social, f"CAT#{SIMBA}", "PUBLIC"),
        get(social, f"CAT#{BAMBA}", "PUBLIC"),
    )
    assert (int(simba["posts"]), int(simba["likes"])) == (0, 0)
    assert (int(bamba["posts"]), int(bamba["likes"])) == (1, 0)
    # Their name stays, with no suggester and the admin's one vote; their
    # vote for Bamba's name is taken back.
    mango = get(social, f"CAT#{SIMBA}", "NAME#mango")
    assert (mango["status"], int(mango["votes"]), "suggestedBy" in mango) == (
        "live",
        1,
        False,
    )
    assert int(simba["voteTotal"]) == 1 and simba["leaderName"] == "Mango"
    assert int(get(social, f"CAT#{BAMBA}", "NAME#bamba")["votes"]) == 1
    assert int(bamba["voteTotal"]) == 1
    # Their feeding is gone, and so Simba was never fed.
    assert "lastFedAt" not in simba
    # The others keep their own side of nothing: no friend, request or block.
    for other in (ADMIN, THIRD, FOURTH):
        left = social.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"USER#{world['ids'][other]}"},
        )["Items"]
        assert not [
            i
            for i in left
            if i["SK"].split("#")[0] in ("FRIEND", "FREQ", "BLOCK", "BLOCKEDBY")
        ]
    # Reports stay, with them cut out.
    by, of = (
        get(social, f"REPORT#{REPORT_BY}", "META"),
        get(social, f"REPORT#{REPORT_OF}", "META"),
    )
    assert "reporterId" not in by and by["targetId"] == ADMINS_POST
    assert of["targetId"] == events.DELETED and "targetOwnerId" not in of
    assert of["reporterId"] == world["ids"][THIRD]
    # The proposal stays for the desk, with no proposer.
    proposal = get(social, f"PROPOSAL#{PROPOSAL}", "META")
    assert proposal["status"] == "open" and "proposerId" not in proposal
    status, desk = desk_call("GET", "/api/proposals")
    assert status == 200 and desk["proposals"][0]["proposer"] == {
        "username": None,
        "email": None,
    }


def test_what_the_dataset_still_holds_is_what_the_pull_request_says(everything):
    """D14 keeps the photos and their sessions. Clearing the address they
    carry needs a write to bgucats-data, which neither the member API nor
    the events Lambda may make (docs/app-plan/README.md, rule 7): not done
    in B10a. This pins exactly where it remains, so the change that clears
    it has to change this test."""
    world = everything
    delete()
    world["stream"].settle()
    left = holding(world["data"], HELPER)
    assert left == {
        # Who may sign in: the allowlist, an admin's to change.
        (f"ADMIN#{HELPER}", "META", "PK"),
        (f"ADMIN#{HELPER}", "META", "email"),
        # Who sent each photo.
        (f"PHOTO#{PHOTO}", "META", "submittedBy"),
        (f"PHOTO#{THIRD_PHOTO}", "META", "submittedBy"),
        # Who started each encounter, also in the index key that lists them.
        *(
            (f"SESSION#{s}", "META", f)
            for s in (SESSION, THIRD_SESSION)
            for f in ("startedBy", "GSI2SK")
        ),
        # Who answered "Who did you meet?".
        (f"SESSION#{SESSION}", "PICK", "pickedBy"),
    }


def test_after_deletion_the_same_sign_in_starts_a_new_empty_account(everything):
    """Should a token outlive the Cognito user (an ID token is good for up
    to an hour after B10b's step deletes it, and here no pool is stood in):
    while the job runs it is answered `gone`, and once it has finished the
    next call makes a new account with nothing of the old one."""
    old = everything["ids"][HELPER]
    delete()
    everything["stream"].settle()
    status, me = call("GET", "/api/v1/me", email=HELPER)
    assert status == 200
    assert me["userId"] != old
    assert me["counters"]["all"] == {"catsMet": 0, "encounters": 0}
    assert me["terms"]["required"] is True


# ---------------------------------------------------- stopping and starting


def _normal(items):
    """The tables without the moments things were written, which differ
    between two runs by the clock alone."""
    out = {}
    for item in items:
        out[(item["PK"], item["SK"])] = {
            k: v for k, v in item.items() if not re.search(r"(At|countedAt)$", k)
        }
    return out


def _restore(table, items):
    for item in scan(table):
        table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
    for item in items:
        table.put_item(Item=item)


def test_every_step_run_twice_and_the_whole_job_again_end_the_same(
    everything, monkeypatch
):
    """Running a step again is what happens when the job is stopped after
    it (a timeout, a failure, a change delivered twice): the mapping
    starts it over before `deletionStep` moves on. Each step is run twice
    here, then every change of the first run is delivered again, and the
    tables are compared with a plain run's."""
    world = everything
    stream = world["stream"]
    before = stream.seen
    delete()
    start = scan(world["social"])

    stream.settle()
    plain = _normal(scan(world["social"]))

    _restore(world["social"], start)
    stream.seen = before
    twice = []
    for index, step in enumerate(events.DELETION_STEPS):

        def run(profile, step=step):
            step(profile)
            twice.append(step.__name__)
            step(events._get(profile["PK"], "PROFILE") or profile)

        monkeypatch.setattr(
            events,
            "DELETION_STEPS",
            events.DELETION_STEPS[:index] + (run,) + events.DELETION_STEPS[index + 1 :],
        )
    records = []
    handle = events.handler

    def keep(event, context):
        records.extend(event["Records"])
        return handle(event, context)

    monkeypatch.setattr(events, "handler", keep)
    stream.settle()
    assert len(twice) == len(events.DELETION_STEPS)
    assert _normal(scan(world["social"])) == plain

    # The whole job again: every change it caused, delivered once more.
    assert handle({"Records": records}, None) == {"batchItemFailures": []}
    stream.settle()
    assert _normal(scan(world["social"])) == plain
    assert recount.differences(scan(world["social"])) == []


def test_the_rate_counters_are_the_member_apis_own():
    """The job deletes the counters `limits.take` keeps for each action;
    held to the actions src/app/handler.py counts."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "app" / "handler.py"
    ).read_text()
    found = set()
    for match in re.finditer(
        r'limits\.take\(\s*social_table,\s*f"\{[^}]+\}#(\w+)(#\{cat_id\})?",\s*\w+,\s*(\d+)',
        source,
    ):
        action, per_cat, window = match.group(1), match.group(2), int(match.group(3))
        found.add((action, window, bool(per_cat)))
    expected = {
        (a, w, False) for w, actions in events.RATE_ACTIONS.items() for a in actions
    }
    expected |= {
        (a, w, True)
        for w, actions in events.RATE_ACTIONS_PER_CAT.items()
        for a in actions
    }
    assert found == expected


# ------------------------------------------------- the Cognito user (B10b)

HELPERS_SIGN_IN = "Google_100000000000000000002"
ADMINS_SIGN_IN = "Google_100000000000000000001"


class Recording:
    """The Cognito client, every Admin call written down with the social
    table as it was at that moment. `fail` makes the next calls raise."""

    def __init__(self, social):
        self.client = boto3.client("cognito-idp", region_name="us-east-1")
        self.exceptions = self.client.exceptions
        self.social = social
        self.calls = []
        self.fail = None

    def _call(self, name, **kwargs):
        self.calls.append((name, kwargs["Username"], _normal(scan(self.social))))
        if self.fail:
            raise ClientError({"Error": {"Code": self.fail, "Message": "no"}}, name)
        return getattr(self.client, name)(**kwargs)

    def admin_user_global_sign_out(self, **kwargs):
        return self._call("admin_user_global_sign_out", **kwargs)

    def admin_delete_user(self, **kwargs):
        return self._call("admin_delete_user", **kwargs)


@pytest.fixture
def pool(everything, monkeypatch):
    """A user pool in moto with HELPER's and the admin's Google users."""
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool_id = cognito.create_user_pool(PoolName="bgucats-admins")["UserPool"]["Id"]
    for username, email in ((HELPERS_SIGN_IN, HELPER), (ADMINS_SIGN_IN, ADMIN)):
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
    recording = Recording(everything["social"])
    monkeypatch.setattr(events, "COGNITO_USER_POOL_ID", pool_id)
    monkeypatch.setattr(events, "_cognito", recording)
    everything["pool"] = pool_id
    everything["cognito"] = recording
    return everything


def delete_signed_in(email=HELPER, username=HELPERS_SIGN_IN):
    """`DELETE /me` with the ID token's claims as API Gateway passes them."""
    event = {
        "requestContext": {
            "http": {"method": "DELETE", "path": "/api/v1/me"},
            "authorizer": {
                "jwt": {"claims": {"email": email, "cognito:username": username}}
            },
        },
        "body": json.dumps({"confirm": "delete"}),
    }
    answer = handler.handler(event, None)
    return answer["statusCode"], json.loads(answer["body"])


def users(world):
    listing = boto3.client("cognito-idp", region_name="us-east-1").list_users(
        UserPoolId=world["pool"]
    )
    return {u["Username"] for u in listing["Users"]}


def test_the_person_is_signed_out_and_their_cognito_user_deleted_first(pool):
    world, me = pool, pool["ids"][HELPER]
    assert delete_signed_in() == (200, {"deleting": True})
    profile = get(world["social"], f"USER#{me}", "PROFILE")
    assert profile["cognitoUser"] == HELPERS_SIGN_IN
    marked = _normal(scan(world["social"]))

    world["stream"].settle()

    # Both calls, for this person, in that order, with the tables as
    # `DELETE /me` left them: no item deleted yet.
    assert [(name, user) for name, user, _ in world["cognito"].calls] == [
        ("admin_user_global_sign_out", HELPERS_SIGN_IN),
        ("admin_delete_user", HELPERS_SIGN_IN),
    ]
    assert all(tables == marked for _, _, tables in world["cognito"].calls)
    # Their user is gone from the pool; the admin's is not.
    assert users(world) == {ADMINS_SIGN_IN}
    # And the rest of the job ran as before.
    assert holding(world["social"], me) == set()
    assert holding(world["social"], HELPERS_SIGN_IN) == set()
    assert recount.differences(scan(world["social"])) == []


def test_the_job_again_and_a_user_already_gone_end_the_same(pool):
    world = pool
    stream = world["stream"]
    before = stream.seen
    delete_signed_in()
    start = scan(world["social"])
    stream.settle()  # asserts that no change failed, here and below
    plain = _normal(scan(world["social"]))
    assert users(world) == {ADMINS_SIGN_IN}

    # The whole job again, from `DELETE /me`'s change: the user is already
    # gone from Cognito, which is success.
    for _ in range(2):
        _restore(world["social"], start)
        stream.seen = before
        stream.settle()
        assert _normal(scan(world["social"])) == plain
    assert users(world) == {ADMINS_SIGN_IN}
    # Each run asked Cognito: the later ones were told the user was gone.
    assert [name for name, _, _ in world["cognito"].calls] == [
        "admin_user_global_sign_out",
        "admin_delete_user",
        "admin_user_global_sign_out",
        "admin_user_global_sign_out",
    ]


@pytest.mark.parametrize("error", ["TooManyRequestsException", "InternalErrorException"])
def test_a_failure_of_cognito_stops_the_job_before_the_tables(pool, error):
    """Throttled, or unreachable: the change is reported failed, so the
    mapping delivers it again, and nothing in the tables has moved."""
    world, me = pool, pool["ids"][HELPER]
    stream = world["stream"]
    delete_signed_in()
    marked = _normal(scan(world["social"]))
    now = stream._snapshot()
    records = stream._records(stream.seen, now)
    stream.seen = now

    world["cognito"].fail = error
    answer = events.handler({"Records": records}, None)
    assert len(answer["batchItemFailures"]) == 1
    assert _normal(scan(world["social"])) == marked
    profile = get(world["social"], f"USER#{me}", "PROFILE")
    assert (profile["status"], int(profile["deletionStep"])) == ("deleting", 0)
    assert HELPERS_SIGN_IN in users(world)

    # The mapping's retry, with Cognito answering again: the job finishes.
    world["cognito"].fail = None
    assert events.handler({"Records": records}, None) == {"batchItemFailures": []}
    stream.settle()
    assert users(world) == {ADMINS_SIGN_IN}
    assert holding(world["social"], me) == set()


def test_with_no_cognito_user_recorded_the_job_still_runs(pool):
    """No `cognito:username` kept (every ID token the app sends has one,
    but an account marked before B10b has none): the step says so in the
    log and the tables are deleted as before."""
    world, me = pool, pool["ids"][HELPER]
    assert delete()[0] == 200
    world["stream"].settle()
    assert world["cognito"].calls == []
    assert holding(world["social"], me) == set()
    assert HELPERS_SIGN_IN in users(world)
