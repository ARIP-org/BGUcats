"""What happens after a write to bgucats-social (docs/app-plan/02-architecture.md,
"What happens after a write: the events Lambda").

Fed by an event source mapping on the table's stream, through the filter in
filters.json, in batches. It sorts each change by kind, logs one line per
batch, and hands it to that kind's handler in HANDLERS. Since B3a, a new
post is published (publish_post). Since B3b, a change to an encounter
recounts what its person met and keeps its post's cat on the label
(count_encounter). Since B6, an admin's decision on a new cat releases or
hides the post that waited for it (decide_proposal). Since B10a, a profile
marked `deleting` is deleted, a step a change (delete_account); since
B10b its first step signs the person out and deletes their Cognito user.
Since B9, four of these changes tell someone's phone (notify, and push.py
for the sending). Moderation (C1) arrives the same way.

The rules every handler keeps:

- Idempotent. A stream delivers at least once, so a handler checks the
  state it is about to make before making it, and writes with conditions.
- Never in a person's way: the request that wrote the item has answered.
- A failing record is reported by its sequence number, so the batch around
  it is not retried with it (ReportBatchItemFailures). The mapping retries
  it, splits the batch to find it, and after three tries sends it to the
  alerts topic.
- Never writes anything filters.json admits unless the handler that writes
  it checks the state first: that is how it would trigger itself.
"""

import json
import logging
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOCIAL_TABLE_NAME = os.environ.get("SOCIAL_TABLE_NAME", "bgucats-social")


def _rules_file(name):
    """A rules file the phone and the APIs share: beside this module in the
    Lambda's package (the Makefile's build-events), in web/ in the
    repository."""
    here = Path(__file__).resolve().parent
    for path in (here / name, here.parents[1] / "web" / name):
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(f"{name} is not beside the handler nor in web/")


_words = {}


def words(language):
    """The app's strings in one language (web/i18n), read once."""
    language = language if language in LANGUAGES else "en"
    if language not in _words:
        _words[language] = _rules_file(f"i18n/{language}.json")
    return _words[language]


# What earns points and badges (docs/app-plan/01-product.md, "The rules"),
# and the campus places "Explorer" asks for.
RULES = _rules_file("achievements.json")
CAMPUS_REGIONS = frozenset(r["id"] for r in _rules_file("regions.json")["regions"])
# The badges an encounter can give or, corrected by a label, take back.
ENCOUNTER_BADGES = ("first-meow", "night-owl", "explorer", "cat-whisperer")

# Push (B9, D18). Off unless the account's `push` flag is on. A person is
# told of four things, at most PUSH_DAILY_CAP times a day in all, in their
# own language, and never in words anyone wrote but a name: the plan's "no
# more than a few a day" is five here.
PUSH = os.environ.get("PUSH", "off") == "on"
PUSH_DAILY_CAP = 5
# A post is told to at most this many friends: one change must finish
# within the Lambda's minute. Far above anyone in the beta.
PUSH_FRIENDS_MAX = 200
# How long the day's count is kept (the table's TTL removes it).
PUSH_COUNT_KEPT_S = 3 * 86400
# What each notification says (web/i18n/{language}.json) and what a tap on
# it opens.
PUSH_WORDS = {
    "friendPosted": "push.friendPosted",
    "friendJoined": "push.friendJoined",
    "nameLeads": "push.nameLeads",
    "proposalApproved": "push.proposalApproved",
}
LANGUAGES = ("en", "he", "ru", "ar")

# Reports (B8). This many different people reporting a post hide it until
# an admin looks: common/reports.py's HIDE_AT, held equal by a test (this
# Lambda ships without src/common).
REPORT_HIDE_AT = 3
# Where a report is emailed: the account's alerts topic (alarms.tf), whose
# subscriber is the admin. Absent in tests and on a machine with no topic.
ALERTS_TOPIC_ARN = os.environ.get("ALERTS_TOPIC_ARN")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "")
_sns = None
social_table = boto3.resource("dynamodb").Table(SOCIAL_TABLE_NAME)
_DESERIALIZE = TypeDeserializer()

# (partition key prefix, sort key equal or prefix) -> kind. The first match
# wins. Keys are the social table's (docs/data-model.md, "bgucats-social").
KINDS = (
    ("POST#", "META", "post"),
    ("CAT#", "NAME#", "name"),
    ("CAT#", "VOTE#", "vote"),
    ("CAT#", "FED#", "feeding"),
    ("USER#", "PROFILE", "profile"),
    ("USER#", "FRIEND#", "friend"),
    ("USER#", "FREQ#IN#", "friend_request"),
    ("USER#", "ENC#", "encounter"),
    ("PROPOSAL#", "META", "proposal"),
    ("REPORT#", "META", "report"),
)

# Items this Lambda writes, or will: none of them may pass the filter, or
# writing one would start the Lambda again (tests/events/test_filters.py).
SELF_WRITTEN = (
    ("CAT#", "PUBLIC"),
    ("USER#", "STATS#ALL"),
    ("USER#", "STATS#2026-11"),
    ("USER#", "MET#01J0000000000000000000000"),
    ("USER#", "METM#2026-11#01J0000000000000000000000"),
    ("USER#", "BADGE#first-meow"),
    ("USER#", "FED#2026-11-12T00:00:00.000000Z#01J0000000000000000000000"),
    ("USER#", "FEDCAT#01J0000000000000000000000"),
    ("USER#", "PUSHED#2026-11-12"),
    ("USER#", "DEVICE#phone"),
    ("MOD#POSTTEXT#01J0000000000000000000000", "RUN#2026-11-12T00:00:00Z"),
    ("SPEND#2026-11-12", "DECISIONS"),
    ("RATE#u#posts#1800000000", "META"),
    ("POST#01J0000000000000000000000", "LIKE#u"),
)


def kind_of(pk, sk):
    for pk_prefix, sk_match, kind in KINDS:
        if not pk.startswith(pk_prefix):
            continue
        exact = sk_match in ("META", "PROFILE")
        if (sk == sk_match) if exact else sk.startswith(sk_match):
            return kind
    return None


def _not_built_yet(record):
    """Every kind, until the milestone that brings it gives it a handler."""


def _image(record, which="NewImage"):
    raw = record.get("dynamodb", {}).get(which)
    return {k: _DESERIALIZE.deserialize(v) for k, v in raw.items()} if raw else None


def _now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def publish_post(record):
    """A new post becomes visible: it joins the feed's month and its cat's
    list, and counts on its cat. One transaction, conditional on the post
    still being pending, so a second delivery of the same change, or the
    change this writes coming back through the stream, does nothing.

    This is where moderation goes (C1, docs/app-plan/06-moderation.md).
    Until then a post is published at once: right for the internal beta,
    where everyone is known to the owner; production has the app off.

    An admin's decision about a post (hide, restore, remove) arrives the
    same way: the desk's API marks the post (`modAction`), and it is
    carried out here (B8).
    """
    changed = _image(record)
    if not changed:
        return
    if changed.get("modAction"):
        set_post(changed["PK"], changed["modAction"], changed.get("modReason") or "admin")
        return
    if changed.get("status") == "pending":
        release(changed["PK"])


# What each decision turns a post into, and from what.
POST_MOVES = {
    "hide": ("hidden", ("visible",)),
    "restore": ("visible", ("hidden",)),
    "remove": ("removed", ("visible", "hidden", "pending")),
}


def set_post(post_pk, action, reason):
    """Hide a post, put a hidden one back, or remove one: its state, its
    place in the feed and on its cat's list, and its cat's counters, in one
    transaction, on the condition that the post is as it was read. A post
    that is already there, or not in a state the move starts from, is left
    as it is, and the desk's mark is cleared either way.

    A hidden post keeps its cat and its likes, so putting it back gives the
    cat exactly what hiding took."""
    post = _get(post_pk, "META")
    if not post:
        return
    to, start = POST_MOVES[action]
    was = post.get("status")
    names = {"#s": "status"}
    values = {":was": was}
    if was not in start:
        # Nothing to do but forget the request, if there was one.
        if post.get("modAction"):
            try:
                social_table.update_item(
                    Key={"PK": post_pk, "SK": "META"},
                    UpdateExpression="REMOVE modAction, modReason",
                    ConditionExpression="#s = :was",
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
            except social_table.meta.client.exceptions.ConditionalCheckFailedException:
                raise RuntimeError(f"{post_pk} changed under a decision") from None
        return
    likes = int(post.get("likeCount", 0))
    cat_id = post.get("catId")
    values.update({":to": to, ":likes": likes, ":now": _now_iso()})
    if to == "visible":
        created = post["createdAt"]
        update = "SET #s = :to, GSI2PK = :feed, GSI2SK = :feed_sk"
        values.update({":feed": f"FEED#{created[:7]}", ":feed_sk": f"{created}#P#{post['postId']}"})
        if cat_id:
            update += ", GSI3PK = :cat, GSI3SK = :created"
            values.update({":cat": f"CATPOST#{cat_id}", ":created": created})
        update += " REMOVE hiddenReason, hiddenAt, modAction, modReason"
        values.pop(":now")
    else:
        values[":why"] = reason
        stamp = "hiddenAt" if to == "hidden" else "removedAt"
        update = (
            f"SET #s = :to, hiddenReason = :why, {stamp} = :now "
            "REMOVE GSI2PK, GSI2SK, GSI3PK, GSI3SK, modAction, modReason"
        )
    items = [
        {
            "Update": {
                "TableName": social_table.name,
                "Key": {"PK": post_pk, "SK": "META"},
                "UpdateExpression": update,
                "ConditionExpression": "#s = :was AND likeCount = :likes",
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }
    ]
    # Only a visible post counts on its cat.
    if cat_id and was == "visible":
        items.append(_cat_counts(cat_id, -1, -likes))
    elif cat_id and to == "visible":
        items.append(_cat_counts(cat_id, 1, likes))
    # A like in between changes likeCount and cancels this; the mapping
    # retries the record and the post is read again.
    social_table.meta.client.transact_write_items(TransactItems=items)


def take_report(record):
    """A report was made (B8): the admins are emailed, once, and a post
    that enough different people have reported is hidden until one of them
    looks. The report itself waits in the desk's queue either way."""
    report = _image(record)
    if not report or report.get("status") != "open":
        return
    kind, target = report["targetType"], report["targetId"]
    people = social_table.query(
        KeyConditionExpression=Key("PK").eq(f"REPORTED#{kind}#{target}"),
        Select="COUNT",
        ConsistentRead=True,
    )["Count"]
    hides = kind == "post" and people >= REPORT_HIDE_AT
    if hides:
        set_post(f"POST#{target}", "hide", "reports")
    if not report.get("emailedAt"):
        _email_report(report, people, hides)
        try:
            social_table.update_item(
                Key={"PK": report["PK"], "SK": "META"},
                UpdateExpression="SET emailedAt = :now",
                ConditionExpression="attribute_not_exists(emailedAt)",
                ExpressionAttributeValues={":now": _now_iso()},
            )
        except social_table.meta.client.exceptions.ConditionalCheckFailedException:
            pass


def _email_report(report, people, hidden):
    """Through the alerts topic, to whoever reads the account's alerts. It
    carries what was reported and why from the fixed list, and nothing a
    person typed: the note stays in the desk."""
    if not ALERTS_TOPIC_ARN:
        logger.info("no alerts topic: report=%s not emailed", report.get("reportId"))
        return
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    where = f" ({ENVIRONMENT})" if ENVIRONMENT else ""
    what = {"post": "A post", "user": "A person", "avatar": "A profile photo", "name": "A cat's name"}
    lines = [
        f"{what.get(report['targetType'], 'Something')} was reported in BGU Cats{where}.",
        f"Reason: {report['reason']}.",
        f"Different people who reported it: {people}.",
    ]
    if hidden:
        lines.append("It is hidden from everyone until an admin decides.")
    lines += [
        "",
        "Decide in the desk: Queue, Reports. Apple's rules ask for an answer within a day.",
        f"Report {report['reportId']}, {report['targetType']} {report['targetId']}.",
    ]
    _sns.publish(
        TopicArn=ALERTS_TOPIC_ARN,
        Subject=f"BGU Cats{where}: {report['targetType']} reported ({report['reason']})"[:100],
        Message="\n".join(lines),
    )


def release(post_pk):
    """Publish a pending post if nothing holds it back. A post for a new cat
    waits while its proposal is open; once an admin decides, it goes out
    under the decided cat, or is hidden if the proposal was rejected (D7)."""
    # The post as it is now, not as a change left it: its cat may have been
    # corrected by a label since (count_encounter).
    post = _get(post_pk, "META")
    if not post or post.get("status") != "pending":
        return
    author = _get(f"USER#{post['authorId']}", "PROFILE") or {}
    if author.get("status") == "banned":
        _hide(post, "banned")  # written a moment before the ban: never shown
        return
    cat_id = post.get("catId")
    if post.get("proposalId"):
        proposal = _get(f"PROPOSAL#{post['proposalId']}", "META") or {}
        decided = proposal.get("status", "rejected")
        if decided == "open":
            return  # held until an admin decides
        if decided == "rejected":
            _hide(post, "proposal_rejected")
            return
        cat_id = proposal.get("catId")
    created = post["createdAt"]
    names = {"#s": "status"}
    values = {
        ":pending": "pending",
        ":visible": "visible",
        ":now": _now_iso(),
        ":feed": f"FEED#{created[:7]}",
        ":feed_sk": f"{created}#P#{post['postId']}",
    }
    update = (
        "SET #s = :visible, visibleAt = :now, GSI2PK = :feed, GSI2SK = :feed_sk, "
        "catId = :newcat"
    )
    values[":newcat"] = cat_id
    same_cat = _cat_is(post.get("catId"), values)
    items = []
    if cat_id:
        update += ", GSI3PK = :cat, GSI3SK = :created"
        values[":cat"] = f"CATPOST#{cat_id}"
        values[":created"] = created
        items.append(
            {
                "Update": {
                    "TableName": social_table.name,
                    "Key": {"PK": f"CAT#{cat_id}", "SK": "PUBLIC"},
                    "UpdateExpression": "ADD posts :one SET lastSeenAt = :created",
                    "ExpressionAttributeValues": {":one": 1, ":created": created},
                }
            }
        )
    items.insert(
        0,
        {
            "Update": {
                "TableName": social_table.name,
                "Key": {"PK": post["PK"], "SK": "META"},
                "UpdateExpression": update,
                "ConditionExpression": f"#s = :pending AND {same_cat}",
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        },
    )
    client = social_table.meta.client
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            # Already published, removed, or its cat corrected meanwhile:
            # read again, by the mapping's retry.
            fresh = _get(post["PK"], "META") or {}
            if fresh.get("status") == "pending":
                raise
            return
        raise
    tell_friends(post, author)


def _hide(post, reason):
    """A pending post that will never be published stays its author's, with
    the reason; it is in no list."""
    try:
        social_table.update_item(
            Key={"PK": post["PK"], "SK": "META"},
            UpdateExpression="SET #s = :hidden, hiddenReason = :why",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":hidden": "hidden",
                ":why": reason,
                ":pending": "pending",
            },
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass  # published or removed meanwhile


def decide_proposal(record):
    """An admin approved, merged or rejected a new cat: its encounter's post,
    if there is one, is released or hidden (release, above). The label of
    the encounter itself comes from the desk, which counts as for any label."""
    proposal = _image(record)
    if not proposal or proposal.get("status") == "open":
        return
    if not proposal.get("proposerId"):
        return  # its proposer deleted their account; their post went with it
    enc = _get(f"USER#{proposal['proposerId']}", f"ENC#{proposal['sessionId']}") or {}
    if enc.get("postId"):
        release(f"POST#{enc['postId']}")
    before = _image(record, "OldImage") or {}
    if before.get("status") == "open" and proposal.get("status") == "approved":
        notify(
            proposal["proposerId"],
            "proposalApproved",
            f"proposal:{proposal['proposalId']}",
            opens={"kind": "cat", "id": proposal.get("catId")},
        )


def _get(pk, sk):
    return social_table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get(
        "Item"
    )


def _cat_is(cat_id, values):
    """A condition that a post's `catId` is still `cat_id`; none may be
    stored as null or be absent."""
    if cat_id is None:
        values[":nocat"] = None
        return "(attribute_not_exists(catId) OR catId = :nocat)"
    values[":wascat"] = cat_id
    return "catId = :wascat"


def _cat_counts(cat_id, posts, likes):
    return {
        "Update": {
            "TableName": social_table.name,
            "Key": {"PK": f"CAT#{cat_id}", "SK": "PUBLIC"},
            "UpdateExpression": "ADD posts :p, likes :l",
            "ExpressionAttributeValues": {":p": posts, ":l": likes},
        }
    }


# --------------------------------------------------------------------------
# Encounters (B3b): what a person met, and their post's cat
# --------------------------------------------------------------------------


def _shown_cat(enc):
    """The same rule as common/encounters.py, shown_cat: the label, else the
    claim; none if rejected. Kept here because this Lambda ships without
    src/common, and held to it by a test."""
    if not enc or enc.get("rejected"):
        return None
    return enc.get("labelCatId") or enc.get("claimedCatId")


def _month(enc):
    return enc["day"][:7] if enc and enc.get("day") else None


def summarise(encs):
    """What a person's encounters add up to. Recomputed from all of them on
    every change rather than adjusted, so a change seen twice, late, or out
    of order still leaves the right numbers; a person has hundreds at most.

    Returns (met, months, total): met is {catId: {firstDay, lastDay, days,
    encounters}}, months is {yyyy-mm: {encounters, catsMet}}, total is
    {encounters, catsMet}. A rejected encounter counts for nothing; one
    without a cat counts as an encounter but meets nobody.
    """
    met, months = {}, {}
    month_cats = {}
    total = 0
    for enc in encs:
        if enc.get("rejected") or not enc.get("day"):
            continue
        day, month = enc["day"], enc["day"][:7]
        total += 1
        months.setdefault(month, {"encounters": 0, "catsMet": 0})["encounters"] += 1
        cat = _shown_cat(enc)
        if cat is None:
            continue
        month_cats.setdefault(month, set()).add(cat)
        entry = met.setdefault(
            cat, {"firstDay": day, "lastDay": day, "days": set(), "encounters": 0}
        )
        entry["firstDay"] = min(entry["firstDay"], day)
        entry["lastDay"] = max(entry["lastDay"], day)
        entry["days"].add(day)
        entry["encounters"] += 1
    for month, cats in month_cats.items():
        months[month]["catsMet"] = len(cats)
    for entry in met.values():
        entry["days"] = len(entry["days"])
    return met, months, {"encounters": total, "catsMet": len(met)}


# What a met-and-posted day is worth beside a met-and-saved one (D9).
POST_POINTS = 5


def popularity(encs):
    """{(catId, yyyy-mm): points}: what one person's encounters add to their
    cats' popularity (docs/app-plan/01-product.md, "GPA"). One person
    meeting a cat on one day is one, however many encounters or photos, and
    five more if any of them became a post. The same encounters count as
    for "met": the label, else the claim, and nothing if rejected."""
    days = {}
    for enc in encs:
        cat = _shown_cat(enc)
        if cat is None or not enc.get("day"):
            continue
        key = (cat, enc["day"])
        days[key] = days.get(key, False) or bool(enc.get("postId"))
    points = {}
    for (cat, day), posted in days.items():
        key = (cat, day[:7])
        points[key] = points.get(key, 0) + 1 + (POST_POINTS if posted else 0)
    return points


def achievements(encs, met):
    """(points, posts, badges): what a person's encounters have earned
    them. Five points for an encounter that became a post, once per cat per
    day, so ten photos of one cat in an hour are five points. Worked out
    again from all of them on every change, like "met", so a label that
    takes an encounter away takes back exactly what it gave."""
    counted = [e for e in encs if not e.get("rejected") and e.get("day")]
    # "Meet & post a cat": a post of no cat is a post, and earns nothing.
    posted = {
        (_shown_cat(e), e["day"]) for e in counted if e.get("postId") and _shown_cat(e)
    }
    points = RULES["points"]["post"] * len(posted)
    badges = set()
    if counted:
        badges.add("first-meow")
    night = RULES["badges"]["night-owl"]
    if any(
        e.get("hour") is not None
        and (int(e["hour"]) >= night["fromHour"] or int(e["hour"]) < night["untilHour"])
        for e in counted
    ):
        badges.add("night-owl")
    if CAMPUS_REGIONS and CAMPUS_REGIONS <= {e.get("regionId") for e in counted}:
        badges.add("explorer")
    if any(m["days"] >= RULES["badges"]["cat-whisperer"]["days"] for m in met.values()):
        badges.add("cat-whisperer")
    return points, sum(1 for e in counted if e.get("postId")), badges


def _award(user_pk, badge):
    """The badge, with the moment it was first earned; once. Never to an
    account being deleted, which would keep a piece of it."""
    if _being_deleted(user_pk):
        return
    try:
        social_table.put_item(
            Item={"PK": user_pk, "SK": f"BADGE#{badge}", "badgeId": badge, "at": _now_iso()},
            ConditionExpression="attribute_not_exists(PK)",
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass  # theirs already


def keep_badges(user_pk, earned):
    """The person holds exactly the encounter badges they have earned now:
    a new one is given, one a label took the ground from is taken back."""
    held = {
        item["SK"].removeprefix("BADGE#")
        for item in social_table.query(
            KeyConditionExpression=Key("PK").eq(user_pk)
            & Key("SK").begins_with("BADGE#"),
            ConsistentRead=True,
        )["Items"]
    }
    for badge in ENCOUNTER_BADGES:
        if badge in earned and badge not in held:
            _award(user_pk, badge)
        elif badge in held and badge not in earned:
            social_table.delete_item(Key={"PK": user_pk, "SK": f"BADGE#{badge}"})


def count_popularity(user_pk, encs):
    """Each cat's popularity per month (`pop{yyyy-mm}` on its public item)
    is the sum of what every person gives it. What this person gives is
    kept beside their other counters (`METM#{yyyy-mm}#{catId}`), and the
    cat's number moves by the difference, in one transaction with that
    item, on the condition that the item still says what was read. So a
    record seen twice changes nothing, and a label that corrects an
    encounter takes from one cat exactly what it gives the other."""
    want = popularity(encs)
    have, start = {}, None
    while True:
        page = social_table.query(
            KeyConditionExpression=Key("PK").eq(user_pk)
            & Key("SK").begins_with("METM#"),
            ConsistentRead=True,
            **({"ExclusiveStartKey": start} if start else {}),
        )
        for item in page["Items"]:
            have[(item["catId"], item["month"])] = int(item["points"])
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    for cat, month in sorted(set(want) | set(have)):
        new, old = want.get((cat, month), 0), have.get((cat, month))
        if new == (old or 0):
            continue
        key = {"PK": user_pk, "SK": f"METM#{month}#{cat}"}
        was = (
            {"ConditionExpression": "attribute_not_exists(PK)"}
            if old is None
            else {
                "ConditionExpression": "points = :old",
                "ExpressionAttributeValues": {":old": old},
            }
        )
        mine = (
            {
                "Put": {
                    "TableName": social_table.name,
                    "Item": {**key, "catId": cat, "month": month, "points": new},
                    **was,
                }
            }
            if new
            else {"Delete": {"TableName": social_table.name, "Key": key, **was}}
        )
        social_table.meta.client.transact_write_items(
            TransactItems=[
                mine,
                {
                    "Update": {
                        "TableName": social_table.name,
                        "Key": {"PK": f"CAT#{cat}", "SK": "PUBLIC"},
                        "UpdateExpression": "ADD #pop :by",
                        "ExpressionAttributeNames": {"#pop": f"pop{month}"},
                        "ExpressionAttributeValues": {":by": new - (old or 0)},
                    }
                },
            ]
        )


def _query_all(pk, prefix, forward=True):
    items, start = [], None
    while True:
        kwargs = {
            "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with(prefix),
            "ConsistentRead": True,
            "ScanIndexForward": forward,
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = social_table.query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def fed(feedings):
    """(points, cats, count): what a person's feedings add up to. Ten
    points each, for at most two in one Israel day (D10), so the largest
    reward in the app cannot be farmed by tapping. One an admin removed
    counts for nothing."""
    counted = [f for f in feedings if not f.get("removed")]
    days = {}
    for f in counted:
        days[f["day"]] = days.get(f["day"], 0) + 1
    paid = sum(min(n, RULES["feedingsCountedADay"]) for n in days.values())
    return RULES["points"]["feed"] * paid, len({f["catId"] for f in counted}), len(counted)


def count_feeding(record):
    """A feeding was logged, or an admin removed one (the desk only marks
    it `removed`).

    The cat's "last fed" is its newest feeding that still stands, read
    again rather than adjusted, so removing the newest puts it back to the
    one before. The person's copy takes the mark, and their points, "cats
    fed" and Snack Giver are worked out again from all their copies: a
    record seen twice changes nothing."""
    cat_pk = _keys(record)[0]
    feeding = _image(record) or _image(record, "OldImage")
    user_pk = f"USER#{feeding['userId']}"
    mine = {"PK": user_pk, "SK": f"FED#{feeding['at']}#{feeding['catId']}"}
    if _image(record) is None:
        social_table.delete_item(Key=mine)
    elif feeding.get("removed"):
        try:
            social_table.update_item(
                Key=mine,
                UpdateExpression="SET removed = :yes",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={":yes": True},
            )
        except social_table.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # the person's copy is gone: nothing of theirs to correct

    standing = next(
        (f for f in _query_all(cat_pk, "FED#", forward=False) if not f.get("removed")),
        None,
    )
    if standing:
        social_table.update_item(
            Key={"PK": cat_pk, "SK": "PUBLIC"},
            UpdateExpression="SET lastFedAt = :at",
            ExpressionAttributeValues={":at": standing["at"]},
        )
    else:
        social_table.update_item(
            Key={"PK": cat_pk, "SK": "PUBLIC"}, UpdateExpression="REMOVE lastFedAt"
        )

    if _being_deleted(user_pk):
        return  # their feedings went with their account: nothing to count
    points, cats, count = fed(_query_all(user_pk, "FED#"))
    social_table.update_item(
        Key={"PK": user_pk, "SK": "STATS#ALL"},
        UpdateExpression="SET fedPoints = :p, catsFed = :c, feedings = :n, fedCountedAt = :now",
        ExpressionAttributeValues={":p": points, ":c": cats, ":n": count, ":now": _now_iso()},
    )
    if count:
        _award(user_pk, "snack-giver")
    else:
        social_table.delete_item(Key={"PK": user_pk, "SK": "BADGE#snack-giver"})


def _encounters_of(user_pk):
    items, start = [], None
    while True:
        kwargs = {
            "KeyConditionExpression": Key("PK").eq(user_pk)
            & Key("SK").begins_with("ENC#"),
            "ConsistentRead": True,
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = social_table.query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _set_counts(pk, sk, counts):
    """The counters as they are now. `points` and `posts` are on the item
    for all time only (docs/data-model.md, "Counters")."""
    names = {"encounters": ":e", "catsMet": ":c", "points": ":p", "posts": ":o"}
    fields = [f for f in names if f in counts]
    social_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET countedAt = :now, "
        + ", ".join(f"{f} = {names[f]}" for f in fields),
        ExpressionAttributeValues={
            ":now": _now_iso(),
            **{names[f]: counts[f] for f in fields},
        },
    )


def count_encounter(record):
    """An encounter was recorded, labeled, relabeled, rejected or posted.

    Rewrites the person's `MET#` items for the cats it was and is, and
    their `STATS#` for its months and in all; then puts its post on the
    right cat. Writes only items the stream filter does not pass
    (SELF_WRITTEN), and the post only when its cat is wrong.
    """
    pk = _keys(record)[0]
    if _being_deleted(pk):
        return  # the deletion job takes what they counted for away itself
    old, new = _image(record, "OldImage"), _image(record)
    encs = _encounters_of(pk)
    met, months, total = summarise(encs)

    for cat in sorted({_shown_cat(old), _shown_cat(new)} - {None}):
        if cat in met:
            social_table.put_item(
                Item={"PK": pk, "SK": f"MET#{cat}", "catId": cat, **met[cat]}
            )
        else:
            social_table.delete_item(Key={"PK": pk, "SK": f"MET#{cat}"})
    for month in sorted({_month(old), _month(new)} - {None}):
        _set_counts(
            pk, f"STATS#{month}", months.get(month, {"encounters": 0, "catsMet": 0})
        )
    points, posts, badges = achievements(encs, met)
    _set_counts(pk, "STATS#ALL", {**total, "points": points, "posts": posts})
    keep_badges(pk, badges)
    count_popularity(pk, encs)

    if new and new.get("postId"):
        correct_post(new)


def correct_post(enc):
    """The encounter's post shows the label once there is one, and leaves
    every list if the encounter was rejected: its photos are gone."""
    post = _get(f"POST#{enc['postId']}", "META")
    if not post or post.get("status") == "removed":
        return
    visible = post.get("status") == "visible"
    was = post.get("catId")
    likes = int(post.get("likeCount", 0))
    names = {"#s": "status"}
    values = {":status": post["status"], ":likes": likes}
    condition = f"#s = :status AND likeCount = :likes AND {_cat_is(was, values)}"

    if enc.get("rejected"):
        values.update({":removed": "removed", ":why": "rejected", ":now": _now_iso()})
        update = (
            "SET #s = :removed, hiddenReason = :why, removedAt = :now "
            "REMOVE GSI2PK, GSI2SK, GSI3PK, GSI3SK"
        )
        want = was
    else:
        want = enc.get("labelCatId") or post.get("claimedCatId")
        if want == was:
            return
        values[":cat"] = want
        update = "SET catId = :cat"
        if visible and want:
            values[":catpost"] = f"CATPOST#{want}"
            values[":created"] = post["createdAt"]
            update += ", GSI3PK = :catpost, GSI3SK = :created"
        elif visible:
            update += " REMOVE GSI3PK, GSI3SK"

    items = [
        {
            "Update": {
                "TableName": social_table.name,
                "Key": {"PK": post["PK"], "SK": "META"},
                "UpdateExpression": update,
                "ConditionExpression": condition,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }
    ]
    if visible and was:
        items.append(_cat_counts(was, -1, -likes))
    if visible and want and not enc.get("rejected"):
        items.append(_cat_counts(want, 1, likes))
    # A like or an unlike in between changes likeCount and cancels this;
    # the mapping retries the record and it is read again.
    social_table.meta.client.transact_write_items(TransactItems=items)


def publish_name(record):
    """A changed display name becomes the one everyone sees (B1). The member
    API writes it beside the published one (`pendingName`); this moves it
    over, on the condition that it is still the name that was read, so a
    second delivery, a newer change, or this write coming back through the
    stream does nothing.

    This is where moderation goes (C1, docs/app-plan/06-moderation.md), as
    for a post: until then a name is published at once.
    """
    changed = _image(record)
    name = (changed or {}).get("pendingName")
    if not name:
        return
    try:
        social_table.update_item(
            Key={"PK": changed["PK"], "SK": "PROFILE"},
            UpdateExpression="SET displayName = :name REMOVE pendingName, pendingNameAt",
            ConditionExpression="pendingName = :name",
            ExpressionAttributeValues={":name": name},
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        return  # changed again, or gone: the newer change has its own record


def publish_avatar(record):
    """A new profile photo becomes the one everyone sees (B1b), exactly as
    a name does: moved from `pendingAvatarKey` on the condition that it is
    still the photo that was read. Moderation of photos (C4) goes here.

    The photo it replaces stays in the bucket until the person's next
    change or removal, when the member API sweeps their prefix: this
    Lambda has no access to the bucket and needs none.
    """
    changed = _image(record)
    key = (changed or {}).get("pendingAvatarKey")
    if not key:
        return
    try:
        social_table.update_item(
            Key={"PK": changed["PK"], "SK": "PROFILE"},
            UpdateExpression="SET avatarKey = :key REMOVE pendingAvatarKey, pendingAvatarAt",
            ConditionExpression="pendingAvatarKey = :key",
            ExpressionAttributeValues={":key": key},
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        return  # replaced or removed since: nothing of this one to publish


def publish_profile(record):
    """What a person changed about themselves, made public: each part by
    itself, so a name never waits for a photo. An account being deleted
    has only its deletion to do."""
    if delete_account(record):
        return
    publish_name(record)
    publish_avatar(record)
    follow_ban(record)


def _posts_of(user_id):
    items, start = [], None
    while True:
        page = social_table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"AUTHOR#{user_id}"),
            **({"ExclusiveStartKey": start} if start else {}),
        )
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def follow_ban(record):
    """An admin banned a person, or lifted a ban (B8c): their posts leave
    every list, and come back, with what they counted for on their cats.
    Only the posts the ban itself hid come back: one an admin hid for its
    own sake stays hidden."""
    old, new = _image(record, "OldImage") or {}, _image(record) or {}
    was, now = old.get("status"), new.get("status")
    if now == "banned" and was != "banned":
        for post in _posts_of(new["userId"]):
            if post.get("status") == "visible":
                set_post(post["PK"], "hide", "banned")
    elif was == "banned" and now == "active":
        for post in _posts_of(new["userId"]):
            if post.get("status") == "hidden" and post.get("hiddenReason") == "banned":
                set_post(post["PK"], "restore", "banned")


# ------------------------------------------------------------ the name poll

# A pending name read and written again if a vote lands in between.
NAME_ATTEMPTS = 4


def _options(cat_pk):
    items, start = [], None
    while True:
        page = social_table.query(
            KeyConditionExpression=Key("PK").eq(cat_pk) & Key("SK").begins_with("NAME#"),
            ConsistentRead=True,
            **({"ExclusiveStartKey": start} if start else {}),
        )
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def publish_suggestion(cat_pk, sk):
    """A suggested name joins the poll (B4): pending becomes live, and the
    votes it already holds (its author's) join the cat's total, in one
    transaction, on the condition that nothing about the option moved since
    it was read. Moderation of names (C1) goes here, as for a post.

    Returns once the option is no longer pending, by this or anything else.
    """
    client = social_table.meta.client
    for _ in range(NAME_ATTEMPTS):
        option = _get(cat_pk, sk)
        if not option or option.get("status") != "pending":
            return
        votes = int(option.get("votes") or 0)
        items = [
            {
                "Update": {
                    "TableName": social_table.name,
                    "Key": {"PK": cat_pk, "SK": sk},
                    "UpdateExpression": "SET #status = :live",
                    "ConditionExpression": "#status = :pending AND votes = :votes",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        ":live": "live",
                        ":pending": "pending",
                        ":votes": votes,
                    },
                }
            }
        ]
        if votes:
            items.append(
                {
                    "Update": {
                        "TableName": social_table.name,
                        "Key": {"PK": cat_pk, "SK": "PUBLIC"},
                        "UpdateExpression": "ADD voteTotal :votes",
                        "ExpressionAttributeValues": {":votes": votes},
                    }
                }
            )
        try:
            client.transact_write_items(TransactItems=items)
            return
        except client.exceptions.TransactionCanceledException:
            continue
    raise RuntimeError(f"could not publish {cat_pk} / {sk}: it kept changing")


def _votes(cat_pk):
    items, start = [], None
    while True:
        page = social_table.query(
            KeyConditionExpression=Key("PK").eq(cat_pk) & Key("SK").begins_with("VOTE#"),
            ConsistentRead=True,
            **({"ExclusiveStartKey": start} if start else {}),
        )
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def remove_name(cat_pk, sk):
    """An admin removed a name from the poll (B4b); its votes go with it.
    The desk only marks the option `removed`, keeping what it was
    (`removedFrom`). Here its count goes to zero, and leaves the cat's
    total if the name was live, in one transaction; then every vote that
    names it is deleted, so those people may vote again.

    Safe to run twice: a count already at zero is left alone, and a vote
    is deleted only while it still names this option."""
    client = social_table.meta.client
    for _ in range(NAME_ATTEMPTS):
        option = _get(cat_pk, sk)
        if not option or option.get("status") != "removed":
            return
        votes = int(option.get("votes") or 0)
        if not votes:
            break
        items = [
            {
                "Update": {
                    "TableName": social_table.name,
                    "Key": {"PK": cat_pk, "SK": sk},
                    "UpdateExpression": "SET votes = :none",
                    "ConditionExpression": "#status = :removed AND votes = :votes",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        ":none": 0,
                        ":removed": "removed",
                        ":votes": votes,
                    },
                }
            }
        ]
        if option.get("removedFrom") == "live":
            items.append(
                {
                    "Update": {
                        "TableName": social_table.name,
                        "Key": {"PK": cat_pk, "SK": "PUBLIC"},
                        "UpdateExpression": "ADD voteTotal :less",
                        "ExpressionAttributeValues": {":less": -votes},
                    }
                }
            )
        try:
            client.transact_write_items(TransactItems=items)
            break
        except client.exceptions.TransactionCanceledException:
            continue
    else:
        raise RuntimeError(f"could not remove {cat_pk} / {sk}: it kept changing")

    for vote in _votes(cat_pk):
        if vote.get("nameKey") != option["nameKey"]:
            continue
        try:
            social_table.delete_item(
                Key={"PK": cat_pk, "SK": vote["SK"]},
                ConditionExpression="nameKey = :key",
                ExpressionAttributeValues={":key": option["nameKey"]},
            )
        except client.exceptions.ConditionalCheckFailedException:
            pass  # moved to another name meanwhile: theirs to keep


def lead(cat_pk):
    """The poll's leader, worked out again from the options themselves and
    written to the cat's public item: the live option with the most votes,
    the earlier suggestion on a tie, none while nobody has voted. Written
    only when it changed. It can be a moment behind a vote and can always
    be recomputed (03-data-model.md, "Kept by the events Lambda")."""
    voted = [
        o
        for o in _options(cat_pk)
        if o.get("status") == "live" and int(o.get("votes") or 0) > 0
    ]
    voted.sort(key=lambda o: (-int(o["votes"]), o.get("createdAt") or "", o["SK"]))
    leader = voted[0] if voted else None
    if leader and leader.get("suggestedBy"):
        # "Name Giver": a name you suggested has led its poll. Kept once
        # earned, whatever the poll does next.
        _award(f"USER#{leader['suggestedBy']}", "name-giver")
    public = _get(cat_pk, "PUBLIC") or {}
    now = (leader["nameKey"], leader["name"]) if leader else (None, None)
    if (public.get("leaderKey"), public.get("leaderName")) == now:
        return
    if leader:
        social_table.update_item(
            Key={"PK": cat_pk, "SK": "PUBLIC"},
            UpdateExpression="SET leaderKey = :key, leaderName = :name",
            ExpressionAttributeValues={":key": now[0], ":name": now[1]},
        )
        # "A name you suggested is in the lead": told once somebody else
        # has voted for it too. One vote is usually the suggester's own.
        if leader.get("suggestedBy") and int(leader["votes"]) >= 2:
            cat_id = cat_pk.split("#", 1)[1]
            notify(
                leader["suggestedBy"],
                "nameLeads",
                f"lead:{cat_id}:{leader['nameKey']}",
                opens={"kind": "cat", "id": cat_id},
            )
    else:
        social_table.update_item(
            Key={"PK": cat_pk, "SK": "PUBLIC"},
            UpdateExpression="REMOVE leaderKey, leaderName",
        )


def count_name(record):
    """Every change to a name option: a suggestion to publish, a name an
    admin removed, and votes that may have moved the leader."""
    pk, sk = _keys(record)
    changed = _image(record)
    if changed and changed.get("status") == "pending":
        publish_suggestion(pk, sk)
    if changed and changed.get("status") == "removed":
        remove_name(pk, sk)
    lead(pk)


# ---------------------------------------------------------------------------
# Deleting an account (B10a; docs/app-plan/03-data-model.md, "Deleting an
# account")
# ---------------------------------------------------------------------------

# A transaction read and written again if the thing it changes moves.
DELETE_ATTEMPTS = 4
# The member API's rate counters (src/common/limits.py): `RATE#{userId}#
# {action}#{windowStart}`, by window length. Held to the actions the member
# API counts by tests/events/test_delete_account.py. A window's item lives
# a day past its end and the table's TTL can take two more to remove it, so
# the job deletes every window that started in the last RATE_LOOKBACK_S.
RATE_ACTIONS = {
    3600: ("likes", "votes"),
    86400: (
        "avatars",
        "blocks",
        "feedings",
        "invites",
        "names",
        "posts",
        "proposals",
        "reports",
        "suggestions",
        "usernames",
    ),
}
# Counted once per cat as well: `{userId}#suggestions#{catId}`.
RATE_ACTIONS_PER_CAT = {86400: ("suggestions",)}
RATE_LOOKBACK_S = 4 * 86400
# What a report about a deleted person names instead of their id.
DELETED = "deleted"
REPORT_STATUSES = ("open", "actioned", "dismissed")


def _being_deleted(user_pk):
    """True while a person's account is being deleted, and after: nothing
    may be counted, awarded or told to them again."""
    profile = _get(user_pk, "PROFILE")
    return profile is None or profile.get("status") == "deleting"


def _gsi(index, pk_name, pk):
    items, start = [], None
    while True:
        page = social_table.query(
            IndexName=index,
            KeyConditionExpression=Key(pk_name).eq(pk),
            **({"ExclusiveStartKey": start} if start else {}),
        )
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _delete_if(key, field, value):
    """Delete one item if `field` still says `value`; absent is done."""
    try:
        social_table.delete_item(
            Key=key,
            ConditionExpression="#f = :v",
            ExpressionAttributeNames={"#f": field},
            ExpressionAttributeValues={":v": value},
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _transact_retrying(build, what):
    """Run the transaction `build()` returns (None: nothing left to do),
    reading again if something moved under it."""
    client = social_table.meta.client
    for _ in range(DELETE_ATTEMPTS):
        items = build()
        if not items:
            return
        try:
            client.transact_write_items(TransactItems=items)
            return
        except client.exceptions.TransactionCanceledException:
            continue
    raise RuntimeError(f"could not {what}: it kept changing")


def _partition(pk):
    """Every item under one partition key, read consistently."""
    items, start = [], None
    while True:
        page = social_table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ConsistentRead=True,
            **({"ExclusiveStartKey": start} if start else {}),
        )
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _encounters_with(user_pk, field):
    return {e[field] for e in _query_all(user_pk, "ENC#") if e.get(field)}


def _forget_post(post_pk, me):
    """One of the person's posts: removed, out of every list, its cat's
    counters taken back as when an author removes it, and no longer theirs
    (`authorId` and its index keys go). Then the likes others gave it, each
    as an unlike, so a like is always on a post whose author can be listed
    (`_take_likes`)."""

    def remove():
        post = _get(post_pk, "META")
        if not post or post.get("authorId") != me:
            return None
        was, cat_id = post.get("status"), post.get("catId")
        names = {"#s": "status"}
        values = {":was": was, ":me": me, ":removed": "removed", ":now": _now_iso()}
        update = "SET #s = :removed, removedAt = if_not_exists(removedAt, :now)"
        if was != "removed":
            update += ", hiddenReason = :why"
            values[":why"] = "deleted"
        update += (
            " REMOVE authorId, GSI1PK, GSI1SK, GSI2PK, GSI2SK, GSI3PK, GSI3SK, "
            "modAction, modReason, modBy, modAt"
        )
        condition = "#s = :was AND authorId = :me"
        if "likeCount" in post:
            condition += " AND likeCount = :likes"
            values[":likes"] = post["likeCount"]
        items = [
            {
                "Update": {
                    "TableName": social_table.name,
                    "Key": {"PK": post_pk, "SK": "META"},
                    "UpdateExpression": update,
                    "ConditionExpression": condition,
                    "ExpressionAttributeNames": names,
                    "ExpressionAttributeValues": values,
                }
            }
        ]
        if was == "visible" and cat_id:
            items.append(_cat_counts(cat_id, -1, -int(post.get("likeCount", 0))))
        return items

    _transact_retrying(remove, f"remove {post_pk}")
    post = _get(post_pk, "META")
    if not post or post.get("authorId"):
        return  # not there, or not this person's after all
    for like in _query_all(post_pk, "LIKE#"):
        _take_like(post_pk, like["SK"].removeprefix("LIKE#"))


def _take_like(post_pk, user_id):
    """A like taken back, exactly as `DELETE /posts/{id}/like` does: the
    like, the post's count, and its cat's while the post is visible."""

    def unlike():
        if not _get(post_pk, f"LIKE#{user_id}"):
            return None
        post = _get(post_pk, "META")
        names, values = {}, {":less": -1}
        condition = "attribute_exists(PK)"
        if post:
            names["#s"] = "status"
            values[":status"] = post.get("status")
            condition = f"#s = :status AND {_cat_is(post.get('catId'), values)}"
        items = [
            {
                "Delete": {
                    "TableName": social_table.name,
                    "Key": {"PK": post_pk, "SK": f"LIKE#{user_id}"},
                    "ConditionExpression": "attribute_exists(PK)",
                }
            }
        ]
        if post:
            items.append(
                {
                    "Update": {
                        "TableName": social_table.name,
                        "Key": {"PK": post_pk, "SK": "META"},
                        "UpdateExpression": "ADD likeCount :less",
                        "ConditionExpression": condition,
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": values,
                    }
                }
            )
            if post.get("status") == "visible" and post.get("catId"):
                items.append(_cat_counts(post["catId"], 0, -1))
        return items

    _transact_retrying(unlike, f"take back a like on {post_pk}")


def _take_vote(cat_pk, user_id):
    """A vote taken back, as `DELETE /cats/{id}/vote` does (`_move_vote`
    in src/app/handler.py): the vote, one off its option while the option
    is live or pending, and one off the cat's total if it was live."""

    def unvote():
        vote = _get(cat_pk, f"VOTE#{user_id}")
        if not vote:
            return None
        items = [
            {
                "Delete": {
                    "TableName": social_table.name,
                    "Key": {"PK": cat_pk, "SK": f"VOTE#{user_id}"},
                    "ConditionExpression": "nameKey = :old",
                    "ExpressionAttributeValues": {":old": vote["nameKey"]},
                }
            }
        ]
        option = _get(cat_pk, f"NAME#{vote['nameKey']}")
        if option and option.get("status") in ("live", "pending"):
            items.append(
                {
                    "Update": {
                        "TableName": social_table.name,
                        "Key": {"PK": cat_pk, "SK": option["SK"]},
                        "UpdateExpression": "ADD votes :less",
                        "ConditionExpression": "#status = :status",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":less": -1,
                            ":status": option["status"],
                        },
                    }
                }
            )
            if option["status"] == "live":
                items.append(
                    {
                        "Update": {
                            "TableName": social_table.name,
                            "Key": {"PK": cat_pk, "SK": "PUBLIC"},
                            "UpdateExpression": "ADD voteTotal :less",
                            "ExpressionAttributeValues": {":less": -1},
                        }
                    }
                )
        return items

    _transact_retrying(unvote, f"take back a vote on {cat_pk}")


def delete_posts(profile):
    """Step 2: the person's posts, and their new-cat proposals cut loose
    from them. Found through the author's index and through their
    encounters, read consistently, so a post made a moment ago that the
    index has not caught up with is not missed."""
    me, pk = profile["userId"], profile["PK"]
    posts = {p["PK"] for p in _posts_of(me)}
    posts |= {f"POST#{i}" for i in _encounters_with(pk, "postId")}
    for post_pk in sorted(posts):
        _forget_post(post_pk, me)
    proposals = {p["PK"] for p in _gsi("GSI1", "GSI1PK", f"PROPOSER#{me}")}
    proposals |= {f"PROPOSAL#{i}" for i in _encounters_with(pk, "proposalId")}
    for proposal_pk in sorted(proposals):
        try:
            social_table.update_item(
                Key={"PK": proposal_pk, "SK": "META"},
                UpdateExpression="REMOVE proposerId, GSI1PK, GSI1SK",
                ConditionExpression="proposerId = :me",
                ExpressionAttributeValues={":me": me},
            )
        except social_table.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # done already, or someone else's


def delete_marks(profile):
    """Step 3: what the person left on others' things. Likes and votes are
    taken back with their counts; names they suggested stay in the polls
    with no suggester; their feedings go, and each cat's "last fed" is
    worked out again by `count_feeding`.

    No index lists a person's likes, so every listed person's posts are
    looked at: a campus has thousands at most. Posts with no author left
    have no likes (`_forget_post`). The cats come from the member API,
    which listed them when deletion began (`deletingCats`): this Lambda
    cannot read the dataset."""
    me, pk = profile["userId"], profile["PK"]
    for person in _gsi("GSI2", "GSI2PK", "ENTITY#USER"):
        if person.get("userId") == me:
            continue
        for post in _posts_of(person["userId"]):
            if _get(post["PK"], f"LIKE#{me}"):
                _take_like(post["PK"], me)

    cats = set(profile.get("deletingCats") or [])
    copies = _query_all(pk, "FED#")
    cats |= {c["catId"] for c in copies}
    for cat in sorted(cats):
        cat_pk = f"CAT#{cat}"
        _take_vote(cat_pk, me)
        for option in _options(cat_pk):
            if option.get("suggestedBy") == me:
                try:
                    social_table.update_item(
                        Key={"PK": cat_pk, "SK": option["SK"]},
                        UpdateExpression="REMOVE suggestedBy",
                        ConditionExpression="suggestedBy = :me",
                        ExpressionAttributeValues={":me": me},
                    )
                except social_table.meta.client.exceptions.ConditionalCheckFailedException:
                    pass
    feedings = {(f"CAT#{c['catId']}", f"FED#{c['at']}#{me}") for c in copies}
    for cat in sorted(cats):
        feedings |= {
            (f["PK"], f["SK"])
            for f in _query_all(f"CAT#{cat}", "FED#")
            if f.get("userId") == me
        }
    for cat_pk, sk in sorted(feedings):
        social_table.delete_item(Key={"PK": cat_pk, "SK": sk})


# The person's side of a tie -> the other person's side.
MIRRORS = (
    ("FRIEND#", "FRIEND#"),
    ("FREQ#IN#", "FREQ#OUT#"),
    ("FREQ#OUT#", "FREQ#IN#"),
    ("BLOCKEDBY#", "BLOCK#"),  # before BLOCK#, which it also begins with
    ("BLOCK#", "BLOCKEDBY#"),
)


def delete_ties(profile):
    """Step 4: friends, friend requests and blocks, each with its mirror in
    one transaction (invariant 5)."""
    me, pk = profile["userId"], profile["PK"]
    for item in _partition(pk):
        for mine, theirs in MIRRORS:
            if item["SK"].startswith(mine):
                other = item["SK"].removeprefix(mine)
                social_table.meta.client.transact_write_items(
                    TransactItems=[
                        {
                            "Delete": {
                                "TableName": social_table.name,
                                "Key": {"PK": pk, "SK": item["SK"]},
                            }
                        },
                        {
                            "Delete": {
                                "TableName": social_table.name,
                                "Key": {"PK": f"USER#{other}", "SK": f"{theirs}{me}"},
                            }
                        },
                    ]
                )
                break


def clear_reports(profile):
    """Reports stay, for the desk's record, with the person cut out of
    them: the reporter cleared on theirs, the owner cleared on those about
    their things, and a report about the person themselves (or their
    photo) names `deleted`. The one-per-person items (`REPORTED#…/BY#`) that
    name them go."""
    me = profile["userId"]
    for status in REPORT_STATUSES:
        for report in _gsi("GSI2", "GSI2PK", f"REPORTS#{status}"):
            key = {"PK": report["PK"], "SK": "META"}
            if report.get("reporterId") == me:
                social_table.delete_item(
                    Key={
                        "PK": f"REPORTED#{report['targetType']}#{report['targetId']}",
                        "SK": f"BY#{me}",
                    }
                )
                _clear(key, "REMOVE reporterId", "reporterId", me)
            if report.get("targetOwnerId") == me:
                _clear(key, "REMOVE targetOwnerId", "targetOwnerId", me)
            if report.get("targetType") in ("user", "avatar") and report.get("targetId") == me:
                _clear(key, "SET targetId = :deleted", "targetId", me)
    for kind in ("user", "avatar"):
        for item in _partition(f"REPORTED#{kind}#{me}"):
            social_table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})


def _clear(key, update, field, me):
    values = {":me": me}
    if ":deleted" in update:
        values[":deleted"] = DELETED
    try:
        social_table.update_item(
            Key=key,
            UpdateExpression=update,
            ConditionExpression="#f = :me",
            ExpressionAttributeNames={"#f": field},
            ExpressionAttributeValues=values,
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def delete_own_items(profile):
    """Step 5: everything in the person's partition but the profile:
    devices, badges, counters, `MET`, `ENC`, feedings, pushes. What they
    gave each cat's popularity is taken off it first (`count_popularity`
    with no encounters), in the same transactions that delete `METM#`."""
    pk = profile["PK"]
    count_popularity(pk, [])
    for item in _partition(pk):
        if item["SK"] != "PROFILE":
            social_table.delete_item(Key={"PK": pk, "SK": item["SK"]})


def _rate_keys(me, cats, now):
    """Every rate counter this person may still have."""
    keys = []
    for window, actions in RATE_ACTIONS.items():
        per_cat = RATE_ACTIONS_PER_CAT.get(window, ())
        start = int(now // window) * window
        while start > now - RATE_LOOKBACK_S - window:
            for action in actions:
                keys.append(f"RATE#{me}#{action}#{start}")
            for action in per_cat:
                keys += [f"RATE#{me}#{action}#{cat}#{start}" for cat in cats]
            start -= window
    return keys


# Step 1 (B10b): the person's Cognito user. The pool's id comes from
# Terraform (infra/main/events.tf); absent in tests and the local app,
# which have no pool, and then the step logs and moves on.
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
_cognito = None


def _cognito_client():
    global _cognito
    if _cognito is None:
        _cognito = boto3.client("cognito-idp")
    return _cognito


def sign_out_everywhere(profile):
    """Step 1: sign the person out of every device (their refresh tokens
    stop working), then delete their Cognito user, before anything in the
    tables goes. `DELETE /me` kept the user's Cognito name on the profile
    (`cognitoUser`). A user already gone is done, not a failure, so the
    step can run again; any other answer from Cognito (throttled,
    unreachable) fails the change, which leaves the account `deleting` at
    this step for the mapping to try again.

    An ID token already handed out stays valid until it expires (an hour
    at most): API Gateway does not ask Cognito. While the job runs such a
    call is answered `gone`."""
    me, user = profile["userId"], profile.get("cognitoUser")
    if not user:
        logger.warning("deleting user=%s: no Cognito user recorded", me)
        return
    if not COGNITO_USER_POOL_ID:
        logger.warning("deleting user=%s: no user pool here", me)
        return
    cognito = _cognito_client()
    try:
        cognito.admin_user_global_sign_out(
            UserPoolId=COGNITO_USER_POOL_ID, Username=user
        )
        cognito.admin_delete_user(UserPoolId=COGNITO_USER_POOL_ID, Username=user)
    except cognito.exceptions.UserNotFoundException:
        pass  # deleted by an earlier run of this step: signed out with it
    logger.info("deleting user=%s: signed out and Cognito user deleted", me)


def delete_last(profile):
    """Steps 6 and 7 (the avatar's objects went with `DELETE /me`, the one
    Lambda that may touch the bucket): the lookups, the rate counters, a
    last sweep of the partition for anything written while the job ran,
    and, last, the profile. Each lookup only while it is still this
    person's. `PHONE#` is not written by any route yet (D5): the milestone
    that writes it adds it here."""
    me, pk = profile["userId"], profile["PK"]
    if profile.get("username"):
        _delete_if({"PK": f"USERNAME#{profile['username']}", "SK": "META"}, "userId", me)
    if profile.get("inviteCode"):
        _delete_if({"PK": f"INVITE#{profile['inviteCode']}", "SK": "META"}, "userId", me)
    _delete_if({"PK": f"IDENTITY#{profile['email']}", "SK": "META"}, "userId", me)
    for rate_pk in _rate_keys(me, profile.get("deletingCats") or [], time.time()):
        social_table.delete_item(Key={"PK": rate_pk, "SK": "META"})
    delete_own_items(profile)
    try:
        social_table.delete_item(
            Key={"PK": pk, "SK": "PROFILE"},
            ConditionExpression="#s = :deleting",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":deleting": "deleting"},
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass
    logger.info("deleted user=%s", me)


DELETION_STEPS = (
    sign_out_everywhere,
    delete_posts,
    delete_marks,
    delete_ties,
    clear_reports,
    delete_own_items,
    delete_last,
)


def delete_account(record):
    """`DELETE /me` marked the person `deleting` (B10a). One step a change:
    each step ends by moving `deletionStep` on, on the condition that it
    is still the step that ran, and that change comes back through the
    stream to start the next. So every step has the Lambda's whole minute,
    a step that fails is retried by the mapping, and a step run twice (a
    change delivered again, or the job started over) finds its work done.
    The profile is read again, never taken from the change. Returns True
    for a person being deleted: nothing else about the profile is acted on."""
    changed = _image(record)
    if not changed or changed.get("status") != "deleting":
        return False
    profile = _get(changed["PK"], "PROFILE")
    if not profile or profile.get("status") != "deleting":
        return True
    step = int(profile.get("deletionStep") or 0)
    if step >= len(DELETION_STEPS) - 1:
        DELETION_STEPS[-1](profile)  # the profile goes last: nothing to move on
        return True
    DELETION_STEPS[step](profile)
    logger.info("deleting user=%s: step %s done", profile["userId"], step)
    try:
        social_table.update_item(
            Key={"PK": profile["PK"], "SK": "PROFILE"},
            UpdateExpression="SET deletionStep = :next",
            ConditionExpression=(
                "#s = :deleting AND "
                "(deletionStep = :step OR attribute_not_exists(deletionStep))"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":next": step + 1,
                ":step": step,
                ":deleting": "deleting",
            },
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        pass  # another delivery moved it on
    return True


HANDLERS = {kind: _not_built_yet for _, _, kind in KINDS}
HANDLERS["post"] = publish_post
HANDLERS["name"] = count_name
HANDLERS["profile"] = publish_profile
HANDLERS["encounter"] = count_encounter
HANDLERS["feeding"] = count_feeding
HANDLERS["proposal"] = decide_proposal
HANDLERS["report"] = take_report


# ---------------------------------------------------------------------------
# Push (B9): who is told what
# ---------------------------------------------------------------------------


def _shown_name(profile):
    """The name others see: the published one, never one still waiting."""
    return profile.get("displayName") or profile.get("username") or ""


def _deliver(device, payload, collapse):
    """One payload to one device, through Apple (push.py). Its packages are
    loaded here, the first time anything is sent, and by nothing else in
    this Lambda. Tests and the local app put a list in its place."""
    from . import push

    return push.send(device, payload, collapse)


def _take_push(user_id, key):
    """One of today's notifications for this person, unless this very one
    was sent already (a change delivered twice) or today is full. One
    conditional write, so two changes at once cannot both take the last."""
    now = time.time()
    day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    try:
        social_table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": f"PUSHED#{day}"},
            UpdateExpression=(
                "ADD #count :one, #sent :this "
                "SET expiresAt = if_not_exists(expiresAt, :until)"
            ),
            ConditionExpression=(
                "(attribute_not_exists(#count) OR #count < :cap) "
                "AND (attribute_not_exists(#sent) OR NOT contains(#sent, :key))"
            ),
            ExpressionAttributeNames={"#count": "count", "#sent": "sent"},
            ExpressionAttributeValues={
                ":one": 1,
                ":this": {key},
                ":key": key,
                ":cap": PUSH_DAILY_CAP,
                ":until": int(now) + PUSH_COUNT_KEPT_S,
            },
        )
        return True
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def notify(user_id, what, key, name=None, opens=None):
    """Tell one person's phones one thing. `what` is one of PUSH_WORDS,
    `key` names this very notification (so it is sent once), `name` is the
    shown name of whoever it is about, `opens` what a tap goes to.

    Nothing is sent with push off, to someone who turned notifications off
    or is not active, to someone with no phone registered, twice, or past
    the day's cap. It never raises: the change that caused it has been made
    and must not be retried for the sake of a notification."""
    if not PUSH or not user_id:
        return False
    try:
        profile = _get(f"USER#{user_id}", "PROFILE") or {}
        if profile.get("status") != "active" or profile.get("notifications") is False:
            return False
        devices = _query_all(f"USER#{user_id}", "DEVICE#")
        if not devices or not _take_push(user_id, key):
            return False
        strings = words(profile.get("language"))
        payload = {
            "aps": {
                "alert": {
                    "title": strings["app.name"],
                    "body": strings[PUSH_WORDS[what]].replace("{name}", name or ""),
                },
                "sound": "default",
                "thread-id": what,
            },
            "what": what,
        }
        if opens and opens.get("id"):
            payload["opens"] = opens
        results = Counter()
        for device in devices:
            result = _deliver(device, payload, key)
            results[result] += 1
            if result == "gone":
                # Apple will never deliver to it: forgotten, unless the
                # phone registered a new token meanwhile.
                try:
                    social_table.delete_item(
                        Key={"PK": device["PK"], "SK": device["SK"]},
                        ConditionExpression="apnsToken = :token",
                        ExpressionAttributeValues={":token": device["apnsToken"]},
                    )
                except social_table.meta.client.exceptions.ConditionalCheckFailedException:
                    pass
        logger.info("push %s: %s", what, dict(sorted(results.items())))
        return results["sent"] > 0
    except Exception:
        logger.exception("push %s failed", what)
        return False


def tell_friends(post, author):
    """A post went out: its author's friends are told, by the author's
    shown name and nothing the author wrote."""
    if not PUSH:
        return
    friends = _query_all(f"USER#{post['authorId']}", "FRIEND#")[:PUSH_FRIENDS_MAX]
    for friend in friends:
        notify(
            friend["friendId"],
            "friendPosted",
            f"post:{post['postId']}",
            name=_shown_name(author),
            opens={"kind": "post", "id": post["postId"]},
        )


def befriended(record):
    """Someone joined by a person's invite link: the person whose link it
    was is told. A friendship is two items written together; only the
    inviter's copy says so (`by` is the one who accepted)."""
    edge = _image(record)
    if record.get("eventName") != "INSERT" or not edge:
        return
    joined = edge.get("by")
    if not joined or joined == edge.get("userId"):
        return
    them = _get(f"USER#{joined}", "PROFILE") or {}
    notify(
        edge["userId"],
        "friendJoined",
        f"friend:{joined}",
        name=_shown_name(them),
        opens={"kind": "person", "id": joined},
    )


HANDLERS["friend"] = befriended


def _keys(record):
    keys = record.get("dynamodb", {}).get("Keys", {})
    return keys.get("PK", {}).get("S", ""), keys.get("SK", {}).get("S", "")


def handler(event, context):
    records = event.get("Records") or []
    seen = Counter()
    failures = []
    for record in records:
        pk, sk = _keys(record)
        kind = kind_of(pk, sk)
        if kind is None:
            # Passed the filter but no kind matches: the two have drifted.
            # Skipped, not retried: retrying cannot make it match.
            seen["unexpected"] += 1
            logger.warning(
                "no kind for a change to %s / %s", pk.split("#")[0], sk.split("#")[0]
            )
            continue
        seen[f"{kind}:{record.get('eventName', '?')}"] += 1
        try:
            HANDLERS[kind](record)
        except Exception:
            logger.exception("handler for %s failed", kind)
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    logger.info(
        json.dumps(
            {
                "records": len(records),
                "kinds": dict(sorted(seen.items())),
                "failed": len(failures),
            }
        )
    )
    return {"batchItemFailures": failures}
