"""Labelling operations on the data table. Spec §4.1, §6.3, §10.

The unit of labelling is the session, not the photo: one encounter with one
cat is a guaranteed identity cluster, so an admin says "sessions 14 and 39 are
both Ryzhik" a few clicks at a time instead of labelling photos one by one.

Every operation here keeps three properties the rest of the project relies on:

* **Exact key formats.** Cat items are CAT#{catId}/META; labelled photos carry
  GSI3 = CAT#{catId} / createdAt, the "all photos of a cat" index the export
  will read. No new key shapes, no fourth GSI.

* **Idempotent on the ULID.** Re-running an assignment, a rejection, or a merge
  converges on the same state. Creating a cat takes a client-supplied ULID, so
  a retried request cannot create a second cat.

* **Children before parent.** Assigning a session updates every photo first and
  sets the session's catId last, the same order the ingest path follows. A
  failure halfway leaves the session unassigned and re-runnable, never marked
  done with photos still unlabelled.

Cat listing uses GSI2 overloaded with the partition CATALOG. GSI2 is "list
items by a category"; photo statuses live under STATUS#…, cats under CATALOG,
and the two partitions never meet. The alternative is a table scan that grows
with every photo ingested.

Per-cat photo and session counts are stored on the cat item, but they are
derived data: `_recount` rebuilds them from GSI3 after every write that could
change them, rather than incrementing, so they cannot drift.
"""

import re
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from ulid import ULID

COAT_COLORS = ("orange", "black", "white", "grey", "tabby", "calico", "mixed")
COAT_PATTERNS = ("solid", "tabby", "bicolor", "tortie", "pointed")
CAT_STATUSES = ("active", "departed", "unknown")

CATALOG_PARTITION = "CATALOG"

# Spec §4.2. A cat is usable for recognition at the floor, comfortable above
# the second number. Distinct sessions matter more than photo count: the
# phase-1b results measured three captures beating one capture of the same
# size by ~29 points of top-1.
COVERAGE_TARGETS = {
    "photos": {"floor": 20, "comfortable": 50},
    "sessions": {"floor": 3, "comfortable": 5},
}

# Photos an assignment may (re)label. Duplicates stay out of the dataset — the
# same bytes are already counted under the photo that owns them — and a
# rejected photo stays rejected until someone restores it on purpose.
ASSIGNABLE = ("unlabeled", "labeled")

ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class StoreError(Exception):
    status = 400


class NotFound(StoreError):
    status = 404


class Conflict(StoreError):
    status = 409


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def require_ulid(value, what):
    """IDs become key fragments, so anything that is not a ULID is refused —
    a value like "X#Y" must never be able to address a different item."""
    if not isinstance(value, str) or not ULID_PATTERN.match(value):
        raise StoreError(f"{what} must be a ULID")
    return value


# --- reads -------------------------------------------------------------------


def _query_all(table, **kwargs):
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = table.query(**kwargs)
        items += page.get("Items", [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def session_photos(table, session_id):
    """Every processed-or-processing photo of a session, oldest first.

    Photos still `pending` (the S3 object may never have landed) have no GSI1
    keys yet and are deliberately invisible here.
    """
    require_ulid(session_id, "sessionId")
    return _query_all(
        table,
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"SESSION#{session_id}"),
    )


def get_session(table, session_id):
    require_ulid(session_id, "sessionId")
    item = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"}).get("Item")
    if not item:
        raise NotFound(f"no session {session_id}")
    return item


def queue(table, limit=20, cursor=None):
    """Sessions with unlabelled photos, oldest first.

    Built from the photo-status index rather than a session index: a session is
    "in the queue" exactly when it has an unlabelled photo, which is a fact
    about photos.

    The cursor is the key of the last photo actually consumed — not DynamoDB's
    own LastEvaluatedKey. This stops as soon as `limit` sessions are found,
    usually mid-page, and resuming from the end of that page would silently skip
    every session on the rest of it. A session that straddles a page boundary
    can appear on two pages; the client drops the repeat.
    """
    sessions, order, start, last, full = {}, [], cursor, None, False
    while not full:
        kwargs = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq("STATUS#unlabeled"),
            "ScanIndexForward": True,
            "Limit": 200,
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = table.query(**kwargs)
        for photo in page.get("Items", []):
            sid = photo["sessionId"]
            if sid not in sessions:
                if len(order) >= limit:
                    full = True
                    break
                sessions[sid] = []
                order.append(sid)
            sessions[sid].append(photo)
            last = photo
        start = page.get("LastEvaluatedKey")
        if not start:
            break

    next_cursor = _gsi2_key(last) if full else start

    entries = []
    for sid in order:
        try:
            meta = get_session(table, sid)
        except NotFound:
            meta = {"sessionId": sid}
        entries.append({"session": meta, "unlabeled": sessions[sid]})
    return {"sessions": entries, "cursor": next_cursor}


def _gsi2_key(item):
    """An ExclusiveStartKey for GSI2: the table key plus the index key."""
    return {k: item[k] for k in ("PK", "SK", "GSI2PK", "GSI2SK")}


def queue_size(table):
    """Unlabelled photo count — the number that must not reach 2,000 (§4.4)."""
    total, start = 0, None
    while True:
        kwargs = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq("STATUS#unlabeled"),
            "Select": "COUNT",
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = table.query(**kwargs)
        total += page["Count"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return total


def get_cat(table, cat_id):
    require_ulid(cat_id, "catId")
    item = table.get_item(Key={"PK": f"CAT#{cat_id}", "SK": "META"}).get("Item")
    if not item:
        raise NotFound(f"no cat {cat_id}")
    return item


def list_cats(table):
    """Every cat in the catalogue, oldest first. Merged cats drop out."""
    return _query_all(
        table,
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq(CATALOG_PARTITION),
    )


def cat_photos(table, cat_id):
    require_ulid(cat_id, "catId")
    return _query_all(
        table,
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CAT#{cat_id}"),
    )


def coverage(photo_count, session_count):
    """Where a cat stands against the §4.2 targets."""

    def level(value, target):
        if value >= target["comfortable"]:
            return "comfortable"
        if value >= target["floor"]:
            return "floor"
        return "below"

    photos = level(photo_count, COVERAGE_TARGETS["photos"])
    sessions = level(session_count, COVERAGE_TARGETS["sessions"])
    return {
        "photos": photos,
        "sessions": sessions,
        "usable": photos != "below" and sessions != "below",
    }


# --- cats --------------------------------------------------------------------


def _validate_cat_fields(fields, partial):
    allowed = {
        "displayName",
        "coatColor",
        "coatPattern",
        "distinguishing",
        "status",
        "adminNotes",
        "primaryPhotoId",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise StoreError(f"unknown cat fields: {sorted(unknown)}")

    clean = {}
    for name, value in fields.items():
        if value is None or value == "":
            clean[name] = None
            continue
        if name == "coatColor" and value not in COAT_COLORS:
            raise StoreError(f"coatColor must be one of {COAT_COLORS}")
        if name == "coatPattern" and value not in COAT_PATTERNS:
            raise StoreError(f"coatPattern must be one of {COAT_PATTERNS}")
        if name == "status" and value not in CAT_STATUSES:
            raise StoreError(f"status must be one of {CAT_STATUSES}")
        if name == "primaryPhotoId":
            require_ulid(value, "primaryPhotoId")
        if isinstance(value, str):
            value = value.strip()[:500]
        clean[name] = value

    for required in ("coatColor", "coatPattern", "status"):
        if partial and required in clean and clean[required] is None:
            raise StoreError(f"{required} cannot be cleared")
    if not partial:
        for required in ("coatColor", "coatPattern"):
            if not clean.get(required):
                # Required at creation because they power the no-ML fallback
                # filter (§3) and constrain candidates before any search runs.
                raise StoreError(f"{required} is required for a new cat")
    return clean


def create_cat(table, fields, cat_id=None):
    """Create a cat. Idempotent when the caller supplies the ULID.

    The page generates the catId before sending, so a retried request lands on
    the same item: the conditional put fails, and the existing cat is returned
    instead of a second one being created.
    """
    clean = _validate_cat_fields(fields, partial=False)
    cat_id = require_ulid(cat_id, "catId") if cat_id else str(ULID())
    now = _now_iso()
    item = {
        "PK": f"CAT#{cat_id}",
        "SK": "META",
        "catId": cat_id,
        "coatColor": clean["coatColor"],
        "coatPattern": clean["coatPattern"],
        "status": clean.get("status") or "active",
        "createdAt": now,
        "photoCount": 0,
        "sessionCount": 0,
        "GSI2PK": CATALOG_PARTITION,
        "GSI2SK": now,
    }
    # Unset optional fields are omitted, never stored as NULL: "absent means
    # unset" is one rule instead of two.
    for name in ("displayName", "distinguishing", "adminNotes", "primaryPhotoId"):
        if clean.get(name) is not None:
            item[name] = clean[name]
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return get_cat(table, cat_id)
    return item


def update_cat(table, cat_id, fields):
    get_cat(table, cat_id)
    clean = _validate_cat_fields(fields, partial=True)
    if not clean:
        return get_cat(table, cat_id)
    to_set = {k: v for k, v in clean.items() if v is not None}
    to_remove = [k for k, v in clean.items() if v is None]
    parts = []
    if to_set:
        parts.append("SET " + ", ".join(f"#{k} = :{k}" for k in to_set))
    if to_remove:
        parts.append("REMOVE " + ", ".join(f"#{k}" for k in to_remove))
    kwargs = {
        "Key": {"PK": f"CAT#{cat_id}", "SK": "META"},
        "UpdateExpression": " ".join(parts),
        "ConditionExpression": (
            "attribute_exists(PK) AND attribute_not_exists(mergedInto)"
        ),
        "ExpressionAttributeNames": {f"#{k}": k for k in clean},
    }
    if to_set:
        kwargs["ExpressionAttributeValues"] = {f":{k}": v for k, v in to_set.items()}
    try:
        table.update_item(**kwargs)
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise Conflict(f"cat {cat_id} was merged and cannot be edited") from exc
    return get_cat(table, cat_id)


def _recount(table, cat_id):
    """Rebuild a cat's derived fields from GSI3, the source of truth.

    Counts are recomputed, not incremented, so they cannot drift. The main
    photo is checked too: it must be a photo still labelled as this cat, and
    after a rejection or a merge it may not be.
    """
    photos = cat_photos(table, cat_id)
    ids = [p["photoId"] for p in photos]
    sessions = {p["sessionId"] for p in photos}
    current = get_cat(table, cat_id).get("primaryPhotoId")

    update = "SET photoCount = :p, sessionCount = :s"
    values = {":p": len(photos), ":s": len(sessions)}
    if current not in ids:
        if ids:
            update += ", primaryPhotoId = :first"
            values[":first"] = ids[0]
        else:
            update += " REMOVE primaryPhotoId"
    table.update_item(
        Key={"PK": f"CAT#{cat_id}", "SK": "META"},
        UpdateExpression=update,
        ConditionExpression="attribute_exists(PK)",
        ExpressionAttributeValues=values,
    )
    return {"photoCount": len(photos), "sessionCount": len(sessions)}


# --- labelling ---------------------------------------------------------------


def assign_session(table, session_id, cat_id):
    """ "Session N is this cat." Labels every assignable photo, then the session.

    Re-running is a no-op; assigning to a different cat moves the photos and
    recounts both cats. Photos are updated with a condition on their status, so
    a photo rejected concurrently is not silently relabelled.
    """
    get_session(table, session_id)
    cat = get_cat(table, cat_id)
    if cat.get("mergedInto"):
        raise Conflict(f"cat {cat_id} was merged into {cat['mergedInto']}")

    labeled, skipped, previous_cats = 0, {}, set()
    for photo in session_photos(table, session_id):
        status = photo.get("status")
        if status not in ASSIGNABLE:
            skipped[status] = skipped.get(status, 0) + 1
            continue
        if photo.get("catId") and photo["catId"] != cat_id:
            previous_cats.add(photo["catId"])
        try:
            table.update_item(
                Key={"PK": photo["PK"], "SK": "META"},
                UpdateExpression=(
                    "SET #status = :labeled, catId = :cat, GSI2PK = :g2, "
                    "GSI3PK = :g3, GSI3SK = :created"
                ),
                ConditionExpression="#status IN (:unlabeled, :labeled)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":labeled": "labeled",
                    ":unlabeled": "unlabeled",
                    ":cat": cat_id,
                    ":g2": "STATUS#labeled",
                    ":g3": f"CAT#{cat_id}",
                    ":created": photo["createdAt"],
                },
            )
            labeled += 1
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            skipped["changed"] = skipped.get("changed", 0) + 1

    # Parent last: only now is the session "merged" (§6.3, Session.catId).
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET catId = :cat, labeledAt = :now",
        ExpressionAttributeValues={":cat": cat_id, ":now": _now_iso()},
    )

    counts = _recount(table, cat_id)
    for old in previous_cats:
        _recount(table, old)
    return {"labeled": labeled, "skipped": skipped, "cat": counts}


def reject_photos(table, photo_ids, reason):
    """Mark photos as not usable — not a cat, wrong cat in frame, unusable.

    Removes them from the queue and from any cat's GSI3 partition. The original
    in raw/ is untouched (write-once), so a rejection is always reversible.
    """
    reason = (reason or "rejected").strip()[:200]
    affected_cats, rejected = set(), 0
    for photo_id in photo_ids:
        require_ulid(photo_id, "photoId")
        item = table.get_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"}).get("Item")
        if not item:
            raise NotFound(f"no photo {photo_id}")
        if item.get("status") == "pending":
            raise Conflict(f"photo {photo_id} has not finished uploading")
        if item.get("catId"):
            affected_cats.add(item["catId"])
        table.update_item(
            Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
            UpdateExpression=(
                "SET #status = :rejected, GSI2PK = :g2, rejectReason = :why, "
                "rejectedFrom = if_not_exists(rejectedFrom, #status) "
                "REMOVE GSI3PK, GSI3SK"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":rejected": "rejected",
                ":g2": "STATUS#rejected",
                ":why": reason,
            },
        )
        rejected += 1
    for cat_id in affected_cats:
        _recount(table, cat_id)
    return {"rejected": rejected}


def reject_session(table, session_id, reason):
    get_session(table, session_id)
    ids = [
        p["photoId"]
        for p in session_photos(table, session_id)
        if p.get("status") in ASSIGNABLE
    ]
    return reject_photos(table, ids, reason) if ids else {"rejected": 0}


def restore_photos(table, photo_ids):
    """Undo a rejection.

    A photo returns to the queue as unlabelled rather than straight to its old
    cat: the admin sees it again and decides, instead of a mistake being
    re-applied silently. The one exception is a photo that was a duplicate
    before it was rejected — it goes back to being a duplicate. Restoring it as
    unlabelled would let the same bytes be labelled a second time and counted
    twice in the dataset.
    """
    restored = 0
    for photo_id in photo_ids:
        require_ulid(photo_id, "photoId")
        item = table.get_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"}).get("Item")
        if not item or item.get("status") != "rejected":
            continue
        back_to = (
            "duplicate" if item.get("rejectedFrom") == "duplicate" else "unlabeled"
        )
        try:
            table.update_item(
                Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
                UpdateExpression=(
                    "SET #status = :to, GSI2PK = :g2 "
                    "REMOVE rejectReason, rejectedFrom, catId"
                ),
                ConditionExpression="#status = :rejected",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":to": back_to,
                    ":rejected": "rejected",
                    ":g2": f"STATUS#{back_to}",
                },
            )
            restored += 1
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            continue
    return {"restored": restored}


def merge_cats(table, source_id, target_id):
    """ "These two cats are the same cat." Moves everything into the target.

    The fix the open-set threshold is designed around: a false "new cat"
    verdict costs exactly this one action (CLAUDE.md, open-set rules). The
    source is kept as a tombstone pointing at the target, and dropped from the
    catalogue, so an old link to it can still be followed.
    """
    if source_id == target_id:
        raise StoreError("a cat cannot be merged into itself")
    source = get_cat(table, source_id)
    target = get_cat(table, target_id)
    if target.get("mergedInto"):
        raise Conflict(
            f"target {target_id} was itself merged into {target['mergedInto']}"
        )
    if source.get("mergedInto") == target_id:
        return {"moved_sessions": 0, "cat": _recount(table, target_id)}
    if source.get("mergedInto"):
        raise Conflict(
            f"cat {source_id} was already merged into {source['mergedInto']}"
        )

    sessions = sorted({p["sessionId"] for p in cat_photos(table, source_id)})
    for session_id in sessions:
        assign_session(table, session_id, target_id)

    table.update_item(
        Key={"PK": f"CAT#{source_id}", "SK": "META"},
        UpdateExpression="SET mergedInto = :target, mergedAt = :now REMOVE GSI2PK, GSI2SK",
        ExpressionAttributeValues={":target": target_id, ":now": _now_iso()},
    )
    _recount(table, source_id)
    return {"moved_sessions": len(sessions), "cat": _recount(table, target_id)}
