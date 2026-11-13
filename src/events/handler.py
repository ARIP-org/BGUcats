"""What happens after a write to bgucats-social (docs/app-plan/02-architecture.md,
"What happens after a write: the events Lambda").

Fed by an event source mapping on the table's stream, through the filter in
filters.json, in batches. It sorts each change by kind, logs one line per
batch, and hands it to that kind's handler in HANDLERS. Since B3a, a new
post is published (publish_post). Since B3b, a change to an encounter
recounts what its person met and keeps its post's cat on the label
(count_encounter). Since B6, an admin's decision on a new cat releases or
hides the post that waited for it (decide_proposal). Moderation (C1), points and badges (B7) and push (B9)
arrive the same way.

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


# What earns points and badges (docs/app-plan/01-product.md, "The rules"),
# and the campus places "Explorer" asks for.
RULES = _rules_file("achievements.json")
CAMPUS_REGIONS = frozenset(r["id"] for r in _rules_file("regions.json")["regions"])
# The badges an encounter can give or, corrected by a label, take back.
ENCOUNTER_BADGES = ("first-meow", "night-owl", "explorer", "cat-whisperer")

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
    enc = _get(f"USER#{proposal['proposerId']}", f"ENC#{proposal['sessionId']}") or {}
    if enc.get("postId"):
        release(f"POST#{enc['postId']}")


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
    """The badge, with the moment it was first earned; once."""
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
    itself, so a name never waits for a photo."""
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


HANDLERS = {kind: _not_built_yet for _, _, kind in KINDS}
HANDLERS["post"] = publish_post
HANDLERS["name"] = count_name
HANDLERS["profile"] = publish_profile
HANDLERS["encounter"] = count_encounter
HANDLERS["proposal"] = decide_proposal
HANDLERS["report"] = take_report


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
