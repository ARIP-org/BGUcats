"""Admin labeling API — queue, session grid, merge, reject (spec §7, §10),
and in-app capture for the collaborators who photograph cats from the PWA.

Sits behind an API Gateway JWT authorizer bound to the Cognito user pool, so
every request arriving here already carries a cryptographically verified
identity. What the authorizer cannot know is whether that identity is *still*
an admin, so `_caller_email` is re-checked against the DynamoDB allowlist on
every single call. That is the difference between revoking someone's access
now and revoking it whenever their token happens to expire.

Two roles, both on the same allowlist item (`ADMIN#{email}`):
  admin         — everything, as before.
  collaborator  — photographs cats in the app, browses the catalogue, and
                  works the queue by assigning sessions to cats that already
                  exist. Nothing destructive or structural: no deleting, no
                  merging, no creating or renaming cats, no managing people.
An item with no role is an admin, so every account that existed before roles
(the Terraform bootstrap item, `make admin-add`) keeps its access unchanged.

Routing is done here rather than as one API Gateway route per endpoint: a
single ANY /api/{proxy+} route keeps the Terraform to one resource and puts
the whole surface of the API in one readable table (ROUTES, below).
"""

import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from ulid import ULID

from admin import insights

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]

# Long enough to label a session without the grid going blank mid-review,
# short enough that a copied URL is useless by the time it leaves a chat.
PRESIGNED_URL_TTL_SECONDS = 3600

# One page of the queue. Sessions are expanded in full after this many
# photos are sampled from the queue index, so the real number of photos
# returned is somewhat larger — a session is never shown half-labeled.
QUEUE_PHOTO_SAMPLE = 200

# Photos in these states are not training data and are never assigned to a
# cat: `pending` never finished ingest, `duplicate` is byte-identical to a
# photo already in the table.
UNASSIGNABLE_STATUSES = frozenset({"pending", "duplicate"})

DERIVATIVE_NAMES = ("thumb-256.webp", "medium-1024.webp")

# A tracked link's slug — the landing page's ?src= and the bot's /start
# payload. Same pattern as ingest.core.REFERRAL_PATTERN.
LINK_SLUG = r"[a-z0-9][a-z0-9-]{0,31}"

# Numbers a partner reports about their own side of an ad — how many saw
# it, played, clicked through — typed in from their dashboard. Running
# totals; the stats page lines them up with ours over the same span.
PARTNER_FIELDS = insights.PARTNER_FIELDS
PARTNER_MAX = 10**9

BATCH_GET_LIMIT = 100

ROLE_ADMIN = "admin"
ROLE_COLLABORATOR = "collaborator"
ROLES = (ROLE_ADMIN, ROLE_COLLABORATOR)

# Who may call a route (see ROUTES).
ANYONE = "anyone"  # any allowlisted person, collaborators included
ADMINS = "admins"

# In-app capture. The phone uploads straight to S3 with a presigned POST —
# API Gateway caps a body at 10 MB and a synchronous Lambda at 6 MB, and a
# video would not fit through either. The POST policy pins the exact key,
# the content type and a size ceiling, so the URL can write one object of
# one kind and nothing else.
APP_CHANNEL = "app"
UPLOAD_URL_TTL_SECONDS = 3600
# Same ceiling as the chat bots for photos (ingest.core.MAX_FILE_SIZE_BYTES).
# The app records video at 720p, about 3 MB for ten seconds; the ceiling is
# for a phone that ignores the requested resolution.
MAX_UPLOAD_BYTES = {"photo": 20 * 1024 * 1024, "video": 60 * 1024 * 1024}
UPLOAD_TYPES = {
    "image/jpeg": ("jpg", "photo"),
    "video/mp4": ("mp4", "video"),
    "video/webm": ("webm", "video"),
    # iOS, when the system camera is used instead of the in-app one. Still an
    # ISO base media file, so the "ftyp" check below covers it.
    "video/quicktime": ("mov", "video"),
}
# Magic bytes, read back from the uploaded object itself — the declared
# content type is the phone's claim, the bytes are the fact (spec §8.5).
# MP4 carries "ftyp" at offset 4, not 0.
JPEG_SIGNATURE = b"\xff\xd8\xff"
WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"
# The IDs are minted on the phone so that a retried upload from its offline
# outbox lands on the same records instead of creating new ones — the same
# "idempotent on the ULID" rule the bots follow (spec §10). A ULID is 26
# Crockford base32 characters.
ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"
# ~110 m, as everywhere else (ingest.core.COORDINATE_DECIMALS): territory,
# not the spot the contributor was standing on.
COORDINATE_DECIMALS = 3
MAX_ACCURACY_METRES = 100_000
RECENT_ENCOUNTERS = 30

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")

    try:
        email = _caller_email(event)
        role = _require_member(email)
        handler_fn, params, access = _match_route(method, path)
        if access == ADMINS and role != ROLE_ADMIN:
            logger.warning("collaborator=%s refused %s %s", email, method, path)
            raise ApiError(403, "only admins can do this")
        body = _parse_body(event)
        result = handler_fn(
            email=email, role=role, body=body, query=_query(event), **params
        )
        return _response(200, result)
    except ApiError as exc:
        return _response(exc.status, {"error": exc.message})
    except Exception:
        logger.exception("unhandled error on %s %s", method, path)
        return _response(500, {"error": "internal error"})


def _caller_email(event):
    """Email claim from the token the JWT authorizer already verified."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise ApiError(401, "no email claim on token")
    return email


def _require_member(email):
    """The caller's role, or 403 if they are not on the allowlist at all."""
    item = table.get_item(Key={"PK": f"ADMIN#{email}", "SK": "META"}).get("Item")
    if not item:
        logger.warning("rejected non-admin caller=%s", email)
        raise ApiError(403, "not an admin")
    return _role_of(item)


def _role_of(item):
    return item.get("role") if item.get("role") in ROLES else ROLE_ADMIN


def _parse_body(event):
    raw = event.get("body")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ApiError(400, "body must be a JSON object")
    return parsed


def _query(event):
    return event.get("queryStringParameters") or {}


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, default=_json_default),
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"not JSON serializable: {type(value)}")


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def _get_me(email, role, **_):
    return {"email": email, "role": role}


def _get_stats(**_):
    counts = {}
    for status in ("unlabeled", "labeled", "pending", "duplicate"):
        counts[status] = table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"STATUS#{status}"),
            Select="COUNT",
        )["Count"]
    cats = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("ENTITY#CAT"),
        Select="COUNT",
    )["Count"]
    return {"photos": counts, "cats": cats}


def _get_queue(query, **_):
    """Unlabeled photos, oldest first, expanded into whole sessions.

    The queue index is over photos, but the unit of labeling is a session —
    one encounter with one cat, and therefore a guaranteed identity cluster
    (spec §6.1). Showing a session half-populated would invite labeling half
    of it, so each session sampled from the index is re-read in full.
    """
    limit = _int_param(query, "limit", default=QUEUE_PHOTO_SAMPLE, maximum=500)
    sampled = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("STATUS#unlabeled"),
        ScanIndexForward=True,
        Limit=limit,
    )["Items"]

    session_ids = []
    for photo in sampled:
        session_id = photo.get("sessionId")
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)

    return {"sessions": [_session_payload(sid) for sid in session_ids]}


def _get_session(session_id, **_):
    return _session_payload(session_id)


def _session_payload(session_id):
    session = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"}).get(
        "Item"
    )
    photos = _session_photos(session_id)
    return {
        "session": _clean(session) if session else {"sessionId": session_id},
        "photos": [_photo_payload(p) for p in photos],
    }


def _session_photos(session_id):
    return _query_all(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"SESSION#{session_id}"),
        ScanIndexForward=True,
    )


def _query_all(**kwargs):
    """Every page of a query, not just the first 1 MB."""
    items = []
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _photo_payload(photo):
    photo_id = photo["photoId"]
    payload = _clean(photo)
    if photo.get("mediaType") == "video":
        # No derivatives exist for video (spec phase 1 skips frame
        # extraction) — the labeling tool plays the raw upload directly.
        raw_key = photo.get("s3RawKey")
        payload["videoUrl"] = _presign(raw_key) if raw_key else None
    else:
        payload["thumbUrl"] = _presign(f"derived/{photo_id}/thumb-256.webp")
        payload["mediumUrl"] = _presign(f"derived/{photo_id}/medium-1024.webp")
    return payload


def _presign(key):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": MEDIA_BUCKET, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def _clean(item):
    """Drop the key/index plumbing — the UI has no use for it."""
    return {
        k: v
        for k, v in item.items()
        if k
        not in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK")
    }


def _get_cats(**_):
    cats = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("ENTITY#CAT"),
        ScanIndexForward=True,
    )["Items"]
    return {
        "cats": [{**_clean(cat), "coverUrl": _cover_url(cat["catId"])} for cat in cats]
    }


def _cover_url(cat_id):
    """Thumbnail of a cat's earliest *photo*, for the cat list.

    Looked up rather than stored on the Cat record: a cached coverPhotoId
    goes stale the moment that photo is rejected, and a cat card with a
    broken image is worse than one query per cat. GSI3 is sorted by
    createdAt, so the first photo found is the oldest and the cover stays
    stable as more are added.

    Videos have no thumbnail derivative to show (spec phase 1 skips frame
    extraction), so a cat whose earliest media is a video falls through to
    its next-oldest photo instead of a broken image.
    """
    page = table.query(
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CAT#{cat_id}"),
        ScanIndexForward=True,
    )["Items"]
    for item in page:
        if item.get("mediaType") != "video":
            return _presign(f"derived/{item['photoId']}/thumb-256.webp")
    return None


def _get_cat(cat_id, **_):
    cat = table.get_item(Key={"PK": f"CAT#{cat_id}", "SK": "META"}).get("Item")
    if not cat:
        raise ApiError(404, "no such cat")
    photos = _cat_photos(cat_id)
    return {"cat": _clean(cat), "photos": [_photo_payload(p) for p in photos]}


def _cat_photos(cat_id):
    return _query_all(
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CAT#{cat_id}"),
        ScanIndexForward=True,
    )


# --------------------------------------------------------------------------
# Stats page
# --------------------------------------------------------------------------


def _get_insights(**_):
    """Everything on the stats page, recomputed from the table per request.

    GSI2 queries only, no scan: photos by status, and the profile, traffic,
    link and cat entity lists. Sessions are fetched by ID for their pinned
    location. See admin/insights.py for what is computed and why.
    """
    unlabeled = _status_items("unlabeled")
    labeled = _status_items("labeled")
    media = unlabeled + labeled
    session_ids = {p["sessionId"] for p in media if p.get("sessionId")}
    return insights.build(
        media=media,
        duplicates=len(_status_items("duplicate")),
        sessions=_batch_get_sessions(session_ids),
        profiles=_entities("SUBMITTER"),
        traffic=_entities("TRAFFIC"),
        links=_entities("LINK"),
        cats=_entities("CAT"),
        now=datetime.now(timezone.utc),
    )


def _status_items(status):
    return _query_all(
        IndexName="GSI2", KeyConditionExpression=Key("GSI2PK").eq(f"STATUS#{status}")
    )


def _entities(kind):
    return _query_all(
        IndexName="GSI2", KeyConditionExpression=Key("GSI2PK").eq(f"ENTITY#{kind}")
    )


def _batch_get_sessions(session_ids):
    sessions = {}
    ids = sorted(session_ids)
    for start in range(0, len(ids), BATCH_GET_LIMIT):
        keys = [
            {"PK": f"SESSION#{sid}", "SK": "META"}
            for sid in ids[start : start + BATCH_GET_LIMIT]
        ]
        request = {table.name: {"Keys": keys}}
        while request:
            response = table.meta.client.batch_get_item(RequestItems=request)
            for item in response["Responses"].get(table.name, []):
                sessions[item["sessionId"]] = item
            request = response.get("UnprocessedKeys") or None
    return sessions


# --------------------------------------------------------------------------
# Tracked links
# --------------------------------------------------------------------------


def _create_link(body, email, **_):
    """Register a source so the stats page can name it and hold the
    partner's own numbers. Counting works without this — any well-formed
    ?src= is counted — registering just gives it a label."""
    slug = _required_string(body, "slug", maximum=32).lower()
    if not re.fullmatch(LINK_SLUG, slug):
        raise ApiError(
            400, "slug: lowercase letters, digits and dashes, starting with a letter"
        )
    label = _required_string(body, "label", maximum=60)
    now = _now_iso()
    try:
        table.put_item(
            Item={
                "PK": f"LINK#{slug}",
                "SK": "META",
                "slug": slug,
                "label": label,
                "createdAt": now,
                "createdBy": email,
                "GSI2PK": "ENTITY#LINK",
                "GSI2SK": slug,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ApiError(409, f"a link called {slug} already exists")
    return {"slug": slug, "label": label}


def _update_link(slug, body, **_):
    updates = {}
    if "label" in body:
        updates["label"] = _required_string(body, "label", maximum=60)
    for field in PARTNER_FIELDS:
        if field in body:
            updates[field] = _partner_number(body, field)
    if not updates:
        raise ApiError(400, "nothing to update")
    if any(field in updates for field in PARTNER_FIELDS):
        updates["partnerReportedAt"] = _now_iso()

    expression = ", ".join(f"#{k} = :{k}" for k in updates)
    try:
        table.update_item(
            Key={"PK": f"LINK#{slug}", "SK": "META"},
            UpdateExpression=f"SET {expression}",
            ExpressionAttributeNames={f"#{k}": k for k in updates},
            ExpressionAttributeValues={f":{k}": v for k, v in updates.items()},
            ConditionExpression="attribute_exists(PK)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ApiError(404, "no such link")
    return {"slug": slug, **updates}


def _delete_link(slug, **_):
    """Forgets the label and partner numbers. The traffic already counted
    under the slug stays, and shows under the bare slug again."""
    table.delete_item(Key={"PK": f"LINK#{slug}", "SK": "META"})
    return {"deleted": slug}


def _partner_number(body, field):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, f"{field} must be a whole number")
    if not 0 <= value <= PARTNER_MAX:
        raise ApiError(400, f"{field} is out of range")
    return value


# --------------------------------------------------------------------------
# Cats
# --------------------------------------------------------------------------


def _create_cat(body, email, **_):
    name = _required_string(body, "name", maximum=80)
    cat_id = str(ULID())
    now = _now_iso()
    table.put_item(
        Item={
            "PK": f"CAT#{cat_id}",
            "SK": "META",
            "catId": cat_id,
            "name": name,
            "notes": (body.get("notes") or "").strip()[:2000],
            "photoCount": 0,
            "createdAt": now,
            "createdBy": email,
            # GSI2 doubles as the "list every entity of this type" index —
            # cheaper than a fourth GSI for a table with ~50 cats in it.
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": now,
        },
        ConditionExpression="attribute_not_exists(PK)",
    )
    return {"catId": cat_id, "name": name}


def _update_cat(cat_id, body, **_):
    updates = {}
    if "name" in body:
        updates["name"] = _required_string(body, "name", maximum=80)
    if "notes" in body:
        updates["notes"] = (body.get("notes") or "").strip()[:2000]
    if not updates:
        raise ApiError(400, "nothing to update")

    expression = ", ".join(f"#{k} = :{k}" for k in updates)
    table.update_item(
        Key={"PK": f"CAT#{cat_id}", "SK": "META"},
        UpdateExpression=f"SET {expression}",
        ExpressionAttributeNames={f"#{k}": k for k in updates},
        ExpressionAttributeValues={f":{k}": v for k, v in updates.items()},
        ConditionExpression="attribute_exists(PK)",
    )
    return {"catId": cat_id, **updates}


def _delete_cat(cat_id, **_):
    """Refuse while photos still point at it — an orphaned catId is invisible
    corruption that only surfaces at export time, months later."""
    remaining = table.query(
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CAT#{cat_id}"),
        Select="COUNT",
    )["Count"]
    if remaining:
        raise ApiError(409, f"{remaining} photos still assigned to this cat")
    table.delete_item(Key={"PK": f"CAT#{cat_id}", "SK": "META"})
    return {"deleted": cat_id}


# --------------------------------------------------------------------------
# Labeling
# --------------------------------------------------------------------------


def _assign_session(session_id, body, email, **_):
    cat_id = _required_string(body, "catId", maximum=64)
    _assert_cat_exists(cat_id)

    photos = _session_photos(session_id)
    assigned = 0
    for photo in photos:
        if photo.get("status") in UNASSIGNABLE_STATUSES:
            continue
        _assign_photo_item(photo, cat_id, email)
        assigned += 1

    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET catId = :cat, labeledAt = :now, labeledBy = :by",
        ExpressionAttributeValues={":cat": cat_id, ":now": _now_iso(), ":by": email},
    )
    _refresh_cat_photo_count(cat_id)
    return {"sessionId": session_id, "catId": cat_id, "assigned": assigned}


def _assign_photo(photo_id, body, email, **_):
    cat_id = _required_string(body, "catId", maximum=64)
    _assert_cat_exists(cat_id)
    photo = _require_photo(photo_id)
    if photo.get("status") in UNASSIGNABLE_STATUSES:
        raise ApiError(409, f"photo is {photo.get('status')}")
    _assign_photo_item(photo, cat_id, email)
    _refresh_cat_photo_count(cat_id)
    return {"photoId": photo_id, "catId": cat_id}


def _assign_photo_item(photo, cat_id, email):
    table.update_item(
        Key={"PK": f"PHOTO#{photo['photoId']}", "SK": "META"},
        UpdateExpression=(
            "SET catId = :cat, #status = :labeled, labeledAt = :now, "
            "labeledBy = :by, GSI2PK = :queue, GSI3PK = :cat_key, GSI3SK = :created"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":cat": cat_id,
            ":labeled": "labeled",
            ":now": _now_iso(),
            ":by": email,
            ":queue": "STATUS#labeled",
            ":cat_key": f"CAT#{cat_id}",
            ":created": photo.get("createdAt", ""),
        },
    )


def _unassign_session(session_id, email, role, **_):
    """Collaborators may undo only a label they gave themselves — a slip of
    the thumb is theirs to fix, someone else's decision is an admin's."""
    if role != ROLE_ADMIN:
        session = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"}).get(
            "Item"
        )
        if not session or session.get("labeledBy") != email:
            raise ApiError(403, "only the person who labeled this can undo it")
    photos = _session_photos(session_id)
    previous = {p.get("catId") for p in photos if p.get("catId")}
    for photo in photos:
        if photo.get("status") != "labeled":
            continue
        table.update_item(
            Key={"PK": f"PHOTO#{photo['photoId']}", "SK": "META"},
            UpdateExpression=(
                "SET #status = :unlabeled, GSI2PK = :queue "
                "REMOVE catId, labeledAt, labeledBy, GSI3PK, GSI3SK"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":unlabeled": "unlabeled",
                ":queue": "STATUS#unlabeled",
            },
        )
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="REMOVE catId, labeledAt, labeledBy",
    )
    for cat_id in previous:
        _refresh_cat_photo_count(cat_id)
    return {"sessionId": session_id, "unassigned": len(photos)}


def _merge_sessions(body, email, **_):
    """Fold one session's photos into another.

    Only the DynamoDB records move. The S3 key of a raw object embeds the
    session it arrived under, and raw/ is write-once and never mutated
    (spec §6.2) — so `s3RawKey` keeps pointing at the original location and
    stays the authoritative path. Rewriting those keys would mean copying
    every object and briefly having two truths about where a photo lives.
    """
    source_id = _required_string(body, "sourceSessionId", maximum=64)
    target_id = _required_string(body, "targetSessionId", maximum=64)
    if source_id == target_id:
        raise ApiError(400, "cannot merge a session into itself")

    target = table.get_item(Key={"PK": f"SESSION#{target_id}", "SK": "META"}).get(
        "Item"
    )
    if not target:
        raise ApiError(404, "no such target session")

    photos = _session_photos(source_id)
    if not photos:
        raise ApiError(404, "source session has no photos")

    for photo in photos:
        table.update_item(
            Key={"PK": f"PHOTO#{photo['photoId']}", "SK": "META"},
            UpdateExpression=(
                "SET sessionId = :target, GSI1PK = :target_key, "
                "mergedFromSessionId = :source"
            ),
            ExpressionAttributeValues={
                ":target": target_id,
                ":target_key": f"SESSION#{target_id}",
                ":source": source_id,
            },
        )

    table.update_item(
        Key={"PK": f"SESSION#{source_id}", "SK": "META"},
        UpdateExpression=(
            "SET mergedInto = :target, mergedAt = :now, mergedBy = :by, "
            "photoCount = :zero"
        ),
        ExpressionAttributeValues={
            ":target": target_id,
            ":now": _now_iso(),
            ":by": email,
            ":zero": 0,
        },
    )
    _refresh_session_photo_count(target_id)

    target_cat = target.get("catId")
    if target_cat:
        # The target was already labeled, so the photos that just arrived
        # inherit its cat rather than dropping back into the queue.
        for photo in photos:
            if photo.get("status") not in UNASSIGNABLE_STATUSES:
                _assign_photo_item(photo, target_cat, email)
        _refresh_cat_photo_count(target_cat)

    return {"merged": len(photos), "into": target_id}


# --------------------------------------------------------------------------
# Reject — hard delete
# --------------------------------------------------------------------------


def _reject_photo(photo_id, **_):
    """Remove a photo everywhere: S3 (all versions), then DynamoDB.

    The media bucket is versioned, so a plain delete would leave a delete
    marker over an object that still exists and still costs money. Every
    version is removed explicitly.

    The TGMSG idempotency record is deliberately left behind. It is what
    stops a Telegram webhook retry from re-ingesting the same photo, and
    without it a rejected image could walk straight back into the queue.
    """
    photo = _require_photo(photo_id)
    session_id = photo.get("sessionId")
    cat_id = photo.get("catId")

    keys = [
        photo.get("s3RawKey"),
        *(f"derived/{photo_id}/{n}" for n in DERIVATIVE_NAMES),
    ]
    for key in keys:
        if key:
            _delete_all_versions(key)

    table.delete_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"})
    sha256 = photo.get("sha256")
    if sha256:
        # Frees the content hash so an intentional re-submission of the same
        # image is treated as new rather than as a duplicate of a record
        # that no longer exists.
        table.delete_item(Key={"PK": f"SHA#{sha256}", "SK": "META"})

    if session_id:
        _refresh_session_photo_count(session_id)
    if cat_id:
        _refresh_cat_photo_count(cat_id)

    return {"deleted": photo_id}


def _delete_all_versions(key):
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=MEDIA_BUCKET, Prefix=key):
        targets = [
            {"Key": v["Key"], "VersionId": v["VersionId"]}
            for v in (page.get("Versions", []) + page.get("DeleteMarkers", []))
            # Prefix is a prefix, not an exact match: `derived/X/thumb-256.webp`
            # would otherwise also sweep up a hypothetical `...webp.bak`.
            if v["Key"] == key
        ]
        if targets:
            s3.delete_objects(Bucket=MEDIA_BUCKET, Delete={"Objects": targets})


def _reject_session(session_id, **_):
    photos = _session_photos(session_id)
    for photo in photos:
        _reject_photo(photo_id=photo["photoId"])
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET rejectedAt = :now, photoCount = :zero",
        ExpressionAttributeValues={":now": _now_iso(), ":zero": 0},
    )
    return {"deleted": len(photos), "sessionId": session_id}


# --------------------------------------------------------------------------
# Admins
# --------------------------------------------------------------------------


def _get_admins(**_):
    admins = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("ENTITY#ADMIN"),
        ScanIndexForward=True,
    )["Items"]
    return {"admins": [_clean(a) for a in admins]}


def _get_admins_with_roles(**_):
    return {"admins": [{**a, "role": _role_of(a)} for a in _get_admins()["admins"]]}


def _add_admin(body, email, **_):
    """Least privilege by default: a person added without a role is a
    collaborator. Making someone an admin is always an explicit choice."""
    new_email = _required_string(body, "email", maximum=254).lower()
    if "@" not in new_email:
        raise ApiError(400, "not an email address")
    role = _role_param(body, default=ROLE_COLLABORATOR)
    if new_email == email:
        raise ApiError(409, "you are already on the list")
    now = _now_iso()
    table.put_item(
        Item={
            "PK": f"ADMIN#{new_email}",
            "SK": "META",
            "email": new_email,
            "role": role,
            "addedAt": now,
            "addedBy": email,
            "GSI2PK": "ENTITY#ADMIN",
            "GSI2SK": new_email,
        }
    )
    logger.info("person added=%s role=%s by=%s", new_email, role, email)
    return {"email": new_email, "role": role}


def _set_role(admin_email, body, email, **_):
    """Nobody changes their own role: an admin demoting themselves could
    leave the tool with no admin at all."""
    target = admin_email.lower()
    if target == email:
        raise ApiError(409, "you cannot change your own role")
    role = _role_param(body)
    try:
        table.update_item(
            Key={"PK": f"ADMIN#{target}", "SK": "META"},
            UpdateExpression="SET #role = :role, roleSetAt = :now, roleSetBy = :by",
            ExpressionAttributeNames={"#role": "role"},
            ExpressionAttributeValues={":role": role, ":now": _now_iso(), ":by": email},
            ConditionExpression="attribute_exists(PK)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ApiError(404, "no such person")
    logger.info("role of %s set to %s by=%s", target, role, email)
    return {"email": target, "role": role}


def _role_param(body, default=None):
    role = body.get("role") or default
    if role not in ROLES:
        raise ApiError(400, "role must be admin or collaborator")
    return role


def _remove_admin(admin_email, email, **_):
    target = admin_email.lower()
    if target == email:
        raise ApiError(409, "cannot remove yourself")
    table.delete_item(Key={"PK": f"ADMIN#{target}", "SK": "META"})
    logger.info("admin removed=%s by=%s", target, email)
    return {"removed": target}


# --------------------------------------------------------------------------
# In-app capture — the PWA's third channel next to Telegram and WhatsApp
# --------------------------------------------------------------------------
#
# An encounter is a Session with channel "app": one cat, one sitting, opened
# deliberately with "New encounter", so it is an identity cluster by
# construction rather than by a ten-minute idle guess.
#
# Each photo or video follows the spec §10 write order, split across two
# calls because the bytes travel from the phone to S3 directly:
#   1. POST .../media     record written as `pending`, presigned POST returned
#   2. phone -> S3        raw/{sessionId}/{photoId}.{ext}, which fires the
#                         process Lambda exactly as a bot upload does
#   3. POST .../complete  object confirmed in S3 and its bytes sniffed, then
#                         the record flips to `unlabeled`
# A phone that dies between 2 and 3 leaves a `pending` record over a real
# object — the harmless direction — and its outbox calls 3 again on the next
# launch. Never the reverse: nothing is marked ready that S3 does not hold.


def _app_submitter_hash(email):
    """Stable per-person ID for the stats page's contributor table.

    Unsalted, unlike the bots' hashes: those protect anonymous members of
    the public, while every app user is a named person on the allowlist
    whose email already appears in labeledBy and addedBy. The "app:" prefix
    keeps the namespace apart from Telegram and WhatsApp IDs.
    """
    return hashlib.sha256(f"app:{email}".encode()).hexdigest()


def _create_encounter(body, email, **_):
    session_id = _ulid_param(body, "sessionId")
    now = _now_iso()
    item = {
        "PK": f"SESSION#{session_id}",
        "SK": "META",
        "sessionId": session_id,
        "submitterHash": _app_submitter_hash(email),
        "source": APP_CHANNEL,
        "channel": APP_CHANNEL,
        "startedAt": now,
        "lastPhotoAt": now,
        "photoCount": 0,
        "catId": None,
        "notes": None,
        "explicit": True,
        "startedBy": email,
        # GSI2 overload: a collaborator's own encounters, newest last, for
        # the Capture screen. See infra/main/dynamodb.tf.
        "GSI2PK": "ENTITY#ENCOUNTER",
        "GSI2SK": f"{email}#{now}",
    }
    item.update(_location_fields(body))
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # A retry from the outbox after a lost response. Same person: the
        # encounter is already there, which is the outcome they wanted.
        existing = _require_encounter(session_id, email)
        return {"sessionId": session_id, "startedAt": existing.get("startedAt")}
    _record_app_contributor(email)
    return {"sessionId": session_id, "startedAt": now}


def _get_encounters(email, **_):
    items = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("ENTITY#ENCOUNTER")
        & Key("GSI2SK").begins_with(f"{email}#"),
        ScanIndexForward=False,
        Limit=RECENT_ENCOUNTERS,
    )["Items"]
    names = {c["catId"]: c["name"] for c in _entities("CAT")}
    return {
        "encounters": [
            {**_clean(item), "catName": names.get(item.get("catId"))} for item in items
        ]
    }


def _create_upload(session_id, body, email, **_):
    session = _require_encounter(session_id, email)
    photo_id = _ulid_param(body, "photoId")
    content_type = body.get("contentType")
    if content_type not in UPLOAD_TYPES:
        raise ApiError(
            400, "contentType must be a JPEG photo or an MP4, WebM or MOV video"
        )
    ext, kind = UPLOAD_TYPES[content_type]
    key = f"raw/{session_id}/{photo_id}.{ext}"

    item = {
        "PK": f"PHOTO#{photo_id}",
        "SK": "META",
        "photoId": photo_id,
        "sessionId": session_id,
        "source": APP_CHANNEL,
        "channel": APP_CHANNEL,
        "submitterHash": session["submitterHash"],
        "submittedBy": email,
        "s3RawKey": None,
        "sha256": None,
        "phash": None,
        "width": None,
        "height": None,
        "mime": content_type,
        "mediaType": kind,
        "capturedAt": _iso_param(body, "capturedAt"),
        "coarseLat": None,
        "coarseLon": None,
        "status": "pending",
        "catId": None,
        "createdAt": _now_iso(),
        "uploadKey": key,
    }
    item.update(_location_fields(body))
    duration = body.get("durationSeconds")
    if kind == "video" and isinstance(duration, (int, float)) and 0 < duration < 600:
        item["durationSeconds"] = Decimal(str(round(duration, 1)))
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        existing = _require_own_photo(photo_id, email)
        if existing.get("status") != "pending":
            # Already uploaded and confirmed: tell the outbox to drop it.
            return {"photoId": photo_id, "done": True}
        if existing.get("uploadKey") != key:
            raise ApiError(409, "this photo was started with a different file type")

    upload = s3.generate_presigned_post(
        Bucket=MEDIA_BUCKET,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, MAX_UPLOAD_BYTES[kind]],
        ],
        ExpiresIn=UPLOAD_URL_TTL_SECONDS,
    )
    return {"photoId": photo_id, "done": False, "upload": upload}


def _complete_upload(photo_id, email, **_):
    photo = _require_own_photo(photo_id, email)
    if photo.get("s3RawKey"):
        # Confirmed already; this is the outbox retrying a lost response.
        return {"photoId": photo_id, "status": photo.get("status")}
    key = photo["uploadKey"]
    kind = photo["mediaType"]

    try:
        head = s3.head_object(Bucket=MEDIA_BUCKET, Key=key)
    except s3.exceptions.ClientError:
        raise ApiError(409, "the file has not reached storage yet")
    start = s3.get_object(Bucket=MEDIA_BUCKET, Key=key, Range="bytes=0-15")["Body"]
    if head["ContentLength"] > MAX_UPLOAD_BYTES[kind] or not _bytes_match(
        start.read(), kind
    ):
        _delete_all_versions(key)
        table.delete_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"})
        raise ApiError(400, "the uploaded file is not a photo or video we accept")

    session_id = photo["sessionId"]
    created_at = photo["createdAt"]
    # Attach to the session unconditionally, then flip the status only if it
    # is still `pending`: the process Lambda may have run first and marked an
    # exact duplicate, and that verdict must not be overwritten.
    table.update_item(
        Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
        UpdateExpression="SET s3RawKey = :key, GSI1PK = :g1pk, GSI1SK = :created",
        ExpressionAttributeValues={
            ":key": key,
            ":g1pk": f"SESSION#{session_id}",
            ":created": created_at,
        },
    )
    status = "unlabeled"
    try:
        table.update_item(
            Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
            UpdateExpression="SET #status = :status, GSI2PK = :g2pk, GSI2SK = :created",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "unlabeled",
                ":pending": "pending",
                ":g2pk": "STATUS#unlabeled",
                ":created": created_at,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        status = _require_photo(photo_id).get("status")

    session = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"})["Item"]
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET lastPhotoAt = :now",
        ExpressionAttributeValues={":now": _now_iso()},
    )
    _refresh_session_photo_count(session_id)
    _locate_session_from_photo(session, photo)

    cat_id = session.get("catId")
    if cat_id and status == "unlabeled":
        # Someone labeled the encounter while it was still being filmed; a
        # late photo of the same sitting is the same cat (cf. merge).
        _assign_photo_item(
            {**photo, "photoId": photo_id}, cat_id, session.get("labeledBy") or email
        )
        _refresh_cat_photo_count(cat_id)
        status = "labeled"
    return {"photoId": photo_id, "status": status}


def _bytes_match(start, kind):
    if kind == "photo":
        return start.startswith(JPEG_SIGNATURE)
    return start[4:8] == b"ftyp" or start.startswith(WEBM_SIGNATURE)


def _locate_session_from_photo(session, photo):
    """The first located photo pins its encounter, if nothing pinned it yet.
    The phone often has no GPS fix yet when the encounter opens."""
    if session.get("coarseLat") is not None or photo.get("coarseLat") is None:
        return
    try:
        table.update_item(
            Key={"PK": f"SESSION#{session['sessionId']}", "SK": "META"},
            UpdateExpression=(
                "SET coarseLat = :lat, coarseLon = :lon, locationSource = :src, "
                "locationAccuracyM = :acc, locatedAt = :now"
            ),
            ConditionExpression="attribute_not_exists(coarseLat) OR coarseLat = :null",
            ExpressionAttributeValues={
                ":lat": photo["coarseLat"],
                ":lon": photo["coarseLon"],
                ":src": photo.get("locationSource", "app-gps"),
                ":acc": photo.get("locationAccuracyM"),
                ":now": _now_iso(),
                ":null": None,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _location_fields(body):
    """Coarse location from the phone's GPS, with the accuracy it reported.

    The fix is taken at the moment of capture — unlike the bots, which
    accept a pin up to a day later from wherever the person is by then —
    and the accuracy is kept so recognition can ignore a fix that was
    hundreds of metres wide.
    """
    lat, lon = body.get("lat"), body.get("lon")
    if not (_is_coordinate(lat, 90) and _is_coordinate(lon, 180)):
        return {}
    fields = {
        "coarseLat": Decimal(str(round(lat, COORDINATE_DECIMALS))),
        "coarseLon": Decimal(str(round(lon, COORDINATE_DECIMALS))),
        "locationSource": "app-gps",
        "locatedAt": _now_iso(),
    }
    accuracy = body.get("accuracyM")
    if _is_coordinate(accuracy, MAX_ACCURACY_METRES) and accuracy >= 0:
        fields["locationAccuracyM"] = Decimal(str(round(accuracy)))
    return fields


def _is_coordinate(value, limit):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and -limit <= value <= limit
    )


def _record_app_contributor(email):
    """Same profile item the bots write (ingest.core.record_contributor),
    so app collaborators show up on the stats page alongside them."""
    table.update_item(
        Key={"PK": f"SUBMITTER#{_app_submitter_hash(email)}", "SK": "PROFILE"},
        UpdateExpression=(
            "SET submitterHash = :hash, firstSeenAt = if_not_exists(firstSeenAt, :now), "
            "#channel = if_not_exists(#channel, :channel), "
            "GSI2PK = :entity, GSI2SK = if_not_exists(GSI2SK, :now)"
        ),
        ExpressionAttributeNames={"#channel": "channel"},
        ExpressionAttributeValues={
            ":hash": _app_submitter_hash(email),
            ":now": _now_iso(),
            ":channel": APP_CHANNEL,
            ":entity": "ENTITY#SUBMITTER",
        },
    )


def _require_encounter(session_id, email):
    session = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"}).get(
        "Item"
    )
    if not session or session.get("channel") != APP_CHANNEL:
        raise ApiError(404, "no such encounter")
    if session.get("startedBy") != email:
        raise ApiError(403, "this encounter belongs to someone else")
    return session


def _require_own_photo(photo_id, email):
    photo = _require_photo(photo_id)
    if photo.get("channel") != APP_CHANNEL or photo.get("submittedBy") != email:
        raise ApiError(403, "this photo belongs to someone else")
    return photo


def _ulid_param(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not re.fullmatch(ULID_PATTERN, value):
        raise ApiError(400, f"{field} must be a ULID")
    return value


def _iso_param(body, field):
    """A client timestamp, kept only if it parses — it is the phone's clock."""
    value = body.get(field)
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _assert_cat_exists(cat_id):
    if not table.get_item(Key={"PK": f"CAT#{cat_id}", "SK": "META"}).get("Item"):
        raise ApiError(404, "no such cat")


def _require_photo(photo_id):
    photo = table.get_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"}).get("Item")
    if not photo:
        raise ApiError(404, "no such photo")
    return photo


def _refresh_cat_photo_count(cat_id):
    """Recounted rather than incremented: an idempotent write that cannot
    drift, which matters when the same merge is retried."""
    count = table.query(
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CAT#{cat_id}"),
        Select="COUNT",
    )["Count"]
    table.update_item(
        Key={"PK": f"CAT#{cat_id}", "SK": "META"},
        UpdateExpression="SET photoCount = :count",
        ExpressionAttributeValues={":count": count},
    )


def _refresh_session_photo_count(session_id):
    count = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"SESSION#{session_id}"),
        Select="COUNT",
    )["Count"]
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET photoCount = :count",
        ExpressionAttributeValues={":count": count},
    )


def _required_string(body, field, maximum):
    value = (body.get(field) or "").strip()
    if not value:
        raise ApiError(400, f"{field} is required")
    if len(value) > maximum:
        raise ApiError(400, f"{field} is longer than {maximum} characters")
    return value


def _int_param(query, name, default, maximum):
    raw = query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, f"{name} must be an integer")
    return max(1, min(value, maximum))


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

# Ordered; first match wins. Path segments are captured as named groups and
# passed to the handler as keyword arguments. The last column is who may
# call it: ANYONE on the allowlist, or ADMINS only. Everything that deletes,
# merges, names a cat or manages people is ADMINS.
ID = r"[A-Za-z0-9]+"
EMAIL = r"[^/]+"

ROUTES = (
    ("GET", r"^/api/me$", _get_me, ANYONE),
    # The queue badge reads this; counts only, nothing a collaborator
    # cannot already see in the queue itself.
    ("GET", r"^/api/stats$", _get_stats, ANYONE),
    ("GET", r"^/api/insights$", _get_insights, ADMINS),
    ("POST", r"^/api/links$", _create_link, ADMINS),
    ("PATCH", rf"^/api/links/(?P<slug>{LINK_SLUG})$", _update_link, ADMINS),
    ("DELETE", rf"^/api/links/(?P<slug>{LINK_SLUG})$", _delete_link, ADMINS),
    ("GET", r"^/api/queue$", _get_queue, ANYONE),
    # Ahead of the /{session_id} patterns: "merge" would otherwise be read
    # as a session id.
    ("POST", r"^/api/sessions/merge$", _merge_sessions, ADMINS),
    ("GET", rf"^/api/sessions/(?P<session_id>{ID})$", _get_session, ANYONE),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/assign$", _assign_session, ANYONE),
    (
        "POST",
        rf"^/api/sessions/(?P<session_id>{ID})/unassign$",
        _unassign_session,
        ANYONE,
    ),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/reject$", _reject_session, ADMINS),
    ("GET", r"^/api/cats$", _get_cats, ANYONE),
    ("POST", r"^/api/cats$", _create_cat, ADMINS),
    ("GET", rf"^/api/cats/(?P<cat_id>{ID})$", _get_cat, ANYONE),
    ("PATCH", rf"^/api/cats/(?P<cat_id>{ID})$", _update_cat, ADMINS),
    ("DELETE", rf"^/api/cats/(?P<cat_id>{ID})$", _delete_cat, ADMINS),
    ("POST", rf"^/api/photos/(?P<photo_id>{ID})/assign$", _assign_photo, ADMINS),
    ("POST", rf"^/api/photos/(?P<photo_id>{ID})/reject$", _reject_photo, ADMINS),
    ("POST", rf"^/api/photos/(?P<photo_id>{ID})/complete$", _complete_upload, ANYONE),
    ("GET", r"^/api/encounters$", _get_encounters, ANYONE),
    ("POST", r"^/api/encounters$", _create_encounter, ANYONE),
    (
        "POST",
        rf"^/api/encounters/(?P<session_id>{ID})/media$",
        _create_upload,
        ANYONE,
    ),
    ("GET", r"^/api/admins$", _get_admins_with_roles, ADMINS),
    ("POST", r"^/api/admins$", _add_admin, ADMINS),
    ("PATCH", rf"^/api/admins/(?P<admin_email>{EMAIL})$", _set_role, ADMINS),
    ("DELETE", rf"^/api/admins/(?P<admin_email>{EMAIL})$", _remove_admin, ADMINS),
)


def _match_route(method, path):
    path = path.rstrip("/") or path
    matched_path = False
    for route_method, pattern, handler_fn, access in ROUTES:
        match = re.match(pattern, path)
        if not match:
            continue
        matched_path = True
        if route_method == method:
            return handler_fn, match.groupdict(), access
    raise ApiError(405 if matched_path else 404, f"no route for {method} {path}")
