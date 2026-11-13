"""Reports (B8b): a person reports a post, a person or a name; it joins the
desk's queue and the admins are emailed; a post that three different people
reported hides itself until an admin looks; and the admin's answer
(06-moderation.md, "Reports, blocks and bans").

Runs the member API, the desk's API and the events Lambda together.
"""

import boto3
import pytest
from boto3.dynamodb.types import TypeSerializer
from ulid import ULID

import tests.admin.test_handler  # the env the desk's API reads, set at import
from admin import handler as desk
from app import handler
from common import reports
from events import handler as events
from tests.events.stream import Stream

from .test_friends import THIRD, feed, kinds, people  # noqa: F401  (the fixture)
from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)
from .test_posts import CAT, POST, campus, counters, make_post, published  # noqa: F401

FOURTH = "fourth@example.com"
TOPIC = "arn:aws:sns:us-east-1:000000000000:bgucats-alerts"


class Mailbox:
    def __init__(self):
        self.sent = []

    def publish(self, **message):
        self.sent.append(message)


def desk_call(method, path, body=None, email=ADMIN, query=None):
    return tests.admin.test_handler._call(method, path, body, email, query=query)


@pytest.fixture
def world(people, monkeypatch):  # noqa: F811
    """HELPER has posted Simba; ADMIN, THIRD and FOURTH can report it."""
    people["data"].put_item(
        Item={"PK": f"ADMIN#{FOURTH}", "SK": "META", "email": FOURTH, "role": "user"}
    )
    people["me"][FOURTH] = call("GET", "/api/v1/me", email=FOURTH)[1]
    monkeypatch.setattr(desk, "table", people["data"])
    monkeypatch.setattr(desk, "social_table", people["social"])
    monkeypatch.setattr(desk, "s3", boto3.client("s3", region_name="us-east-1"))
    monkeypatch.setattr(desk, "MEDIA_BUCKET", "bgucats-media-test")
    monkeypatch.setattr(desk, "SOCIAL", True)
    people["mail"] = Mailbox()
    monkeypatch.setattr(events, "ALERTS_TOPIC_ARN", TOPIC)
    monkeypatch.setattr(events, "ENVIRONMENT", "staging")
    monkeypatch.setattr(events, "_sns", people["mail"])
    make_post()
    published(people["social"], POST)
    people["stream"] = Stream(people["social"])
    return people


def report(by, target=POST, kind="post", reason="spam", note=None, report_id=None):
    body = {
        "reportId": report_id or str(ULID()),
        "targetType": kind,
        "targetId": target,
        "reason": reason,
    }
    if note is not None:
        body["note"] = note
    return call("POST", "/api/v1/reports", body, email=by)


def queue(status=None):
    status_code, body = desk_call(
        "GET", "/api/reports", query={"status": status} if status else None
    )
    assert status_code == 200, body
    return body["reports"]


def resolve(report_id, action):
    return desk_call("POST", f"/api/reports/{report_id}/resolve", {"action": action})


def post_item(world):
    return world["social"].get_item(Key={"PK": f"POST#{POST}", "SK": "META"})["Item"]


def test_a_report_joins_the_desks_queue_and_the_admins_are_emailed(world):
    assert report(THIRD, note="  This is an ad\nfor a shop.  ") == (200, {"reported": True})
    world["stream"].settle()

    (entry,) = queue()
    assert entry["people"] == 1
    target = entry["target"]
    assert (target["type"], target["postId"], target["status"]) == ("post", POST, "visible")
    assert (target["author"], target["cat"]) == (world["me"][HELPER]["username"], "Simba")
    assert len(target["photos"]) == 2 and "derived/" in target["photos"][0]["thumbUrl"]
    (one,) = entry["reports"]
    assert (one["reason"], one["note"], one["reporter"]) == (
        "spam",
        "This is an ad\nfor a shop.",
        world["me"][THIRD]["username"],
    )
    # Usernames, never anyone's email.
    assert THIRD not in str(entry) and HELPER not in str(entry)

    # One email, through the alerts topic, with nothing a person typed.
    (mail,) = world["mail"].sent
    assert mail["TopicArn"] == TOPIC
    assert mail["Subject"] == "BGU Cats (staging): post reported (spam)"
    assert "Different people who reported it: 1." in mail["Message"]
    assert "Reason: spam." in mail["Message"]
    assert "shop" not in mail["Message"]
    # The post is as it was.
    assert kinds(feed(ADMIN)) == ["post"]


def test_the_answer_is_always_the_same_and_one_person_counts_once(world):
    first = str(ULID())
    assert report(THIRD, report_id=first) == (200, {"reported": True})
    # Sent again by the phone's outbox, and reported again by the same person.
    assert report(THIRD, report_id=first) == (200, {"reported": True})
    assert report(THIRD, reason="offensive") == (200, {"reported": True})
    # One's own post, and something that is not there.
    assert report(HELPER) == (200, {"reported": True})
    assert report(THIRD, target="01JD0000000000000000000XXX") == (200, {"reported": True})
    assert report(THIRD, target="01JD0000000000000000000XXX", kind="user") == (200, {"reported": True})
    world["stream"].settle()
    (entry,) = queue()
    assert (entry["people"], [r["reason"] for r in entry["reports"]]) == (1, ["spam"])
    assert len(world["mail"].sent) == 1


def test_three_different_people_hide_a_post_until_an_admin_looks(world):
    call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (1, 1)
    for who in (ADMIN, THIRD):
        report(who)
    world["stream"].settle()
    assert post_item(world)["status"] == "visible"  # two are not three

    report(FOURTH, reason="offensive")
    world["stream"].settle()
    item = post_item(world)
    assert (item["status"], item["hiddenReason"]) == ("hidden", "reports")
    assert "GSI2PK" not in item and "GSI3PK" not in item
    # Out of everyone's feed and off its cat, with what it counted for.
    assert feed(THIRD)["cards"] == []
    assert call("GET", f"/api/v1/cats/{CAT}/posts", email=THIRD)[1]["cards"] == []
    assert call("GET", f"/api/v1/posts/{POST}", email=THIRD)[0] == 404
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (0, 0)
    # Its author still has it, marked.
    assert call("GET", "/api/v1/me/posts", email=HELPER)[1]["cards"][0]["state"] == "hidden"
    # Three emails, the last saying it is hidden.
    assert len(world["mail"].sent) == 3
    assert "hidden from everyone" in world["mail"].sent[-1]["Message"]

    # One admin action puts it back, with its like, and closes all three.
    (entry,) = queue()
    assert (entry["people"], entry["target"]["status"]) == (3, "hidden")
    status, body = resolve(entry["reportId"], "dismiss")
    assert (status, body["status"], body["closed"]) == (200, "dismissed", 3)
    world["stream"].settle()
    assert post_item(world)["status"] == "visible"
    assert kinds(feed(THIRD)) == ["post"]
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (1, 1)
    assert queue() == []
    assert len(queue("dismissed")) == 1
    # Closing reports emails nobody.
    assert len(world["mail"].sent) == 3


@pytest.mark.parametrize(("action", "state"), [("hide", "hidden"), ("remove", "removed")])
def test_an_admin_hides_or_removes_a_reported_post(world, action, state):
    report(THIRD)
    world["stream"].settle()
    (entry,) = queue()
    status, body = resolve(entry["reportId"], action)
    assert (status, body["status"], body["closed"]) == (200, "actioned", 1)
    world["stream"].settle()
    item = post_item(world)
    assert (item["status"], item["hiddenReason"]) == (state, "admin")
    assert "modAction" not in item  # carried out, and the request forgotten
    assert feed(ADMIN)["cards"] == []
    assert counters(world["social"])["posts"] == 0
    assert queue() == []
    (closed,) = queue("actioned")
    assert closed["target"]["status"] == state


def test_the_desk_hides_restores_and_removes_a_post_by_itself(world):
    for action, state, shown in (("hide", "hidden", 0), ("restore", "visible", 1), ("remove", "removed", 0)):
        status, body = desk_call("POST", f"/api/posts/{POST}/{action}")
        assert (status, body) == (200, {"postId": POST, "asked": action})
        world["stream"].settle()
        assert post_item(world)["status"] == state
        assert counters(world["social"])["posts"] == shown
    # A removed post is not put back, and asking changes nothing.
    desk_call("POST", f"/api/posts/{POST}/restore")
    world["stream"].settle()
    item = post_item(world)
    assert item["status"] == "removed" and "modAction" not in item
    assert counters(world["social"])["posts"] == 0


def test_a_decision_seen_twice_is_carried_out_once(world):
    call("PUT", f"/api/v1/posts/{POST}/like", email=ADMIN)
    report(THIRD)
    world["stream"].settle()
    for _ in range(3):
        events.set_post(f"POST#{POST}", "hide", "admin")
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (0, 0)
    for _ in range(3):
        events.set_post(f"POST#{POST}", "restore", "admin")
    assert (counters(world["social"])["posts"], counters(world["social"])["likes"]) == (1, 1)
    # The same report delivered again emails nobody again.
    item = world["social"].scan(
        FilterExpression="begins_with(PK, :p)", ExpressionAttributeValues={":p": "REPORT#"}
    )["Items"][0]
    image = {k: TypeSerializer().serialize(v) for k, v in item.items()}
    events.take_report({"dynamodb": {"NewImage": image}})
    assert len(world["mail"].sent) == 1


def test_a_reported_name_is_removed_from_its_poll(world):
    call("POST", f"/api/v1/cats/{CAT}/names", {"name": "Stinky"}, email=HELPER)
    world["stream"].settle()
    assert report(THIRD, target=f"{CAT}/stinky", kind="name", reason="offensive")[0] == 200
    world["stream"].settle()
    (entry,) = queue()
    assert (entry["target"]["type"], entry["target"]["name"], entry["target"]["cat"]) == (
        "name",
        "Stinky",
        "Simba",
    )
    assert resolve(entry["reportId"], "hide")[0] == 400  # a name is removed, not hidden
    assert resolve(entry["reportId"], "remove")[0] == 200
    world["stream"].settle()
    poll = call("GET", f"/api/v1/cats/{CAT}/names", email=THIRD)[1]
    assert [o["name"] for o in poll["options"]] == ["Simba"]


def test_a_reported_person_waits_in_the_queue(world):
    helper = world["me"][HELPER]["userId"]
    assert report(THIRD, target=helper, kind="user", reason="harassment")[0] == 200
    world["stream"].settle()
    (entry,) = queue()
    assert entry["target"] == {
        "type": "user",
        "userId": helper,
        "username": world["me"][HELPER]["username"],
        "displayName": world["me"][HELPER]["displayName"],
        "status": "active",
    }
    # A person is not removed or hidden: closed, or banned (tests/app/test_bans.py).
    assert resolve(entry["reportId"], "remove")[0] == 400
    assert resolve(entry["reportId"], "dismiss")[0] == 200
    assert queue() == []


def test_what_is_refused(world, monkeypatch):
    for bad in (
        {"targetType": "cat"},
        {"reason": "boring"},
        {"targetId": ""},
        {"reportId": "nope"},
        {"note": "x" * 281},
    ):
        body = {"reportId": str(ULID()), "targetType": "post", "targetId": POST, "reason": "spam", **bad}
        assert call("POST", "/api/v1/reports", body, email=THIRD)[0] == 400, bad
    assert queue() == []
    # The desk's side is the admins'.
    report(THIRD)
    (entry,) = queue()
    assert desk_call("GET", "/api/reports", email=HELPER)[0] == 403
    assert desk_call("POST", f"/api/reports/{entry['reportId']}/resolve", {"action": "dismiss"}, HELPER)[0] == 403
    assert desk_call("POST", f"/api/posts/{POST}/hide", email=HELPER)[0] == 403
    # A post is hidden or removed, not banned; and only the listed answers.
    assert resolve(entry["reportId"], "ban")[0] == 400
    assert resolve(entry["reportId"], "nuke")[0] == 400
    assert "modAction" not in post_item(world)
    assert resolve("01JD0000000000000000000XXX", "dismiss")[0] == 404
    assert desk_call("POST", "/api/posts/01JD0000000000000000000XXX/hide")[0] == 404
    # Twenty a day.
    monkeypatch.setattr(handler, "REPORTS_PER_DAY", 1)
    assert report(FOURTH)[0] == 200
    assert report(FOURTH, reason="other")[0] == 429


def test_the_two_lambdas_agree_on_when_a_post_hides():
    assert events.REPORT_HIDE_AT == reports.HIDE_AT == 3
