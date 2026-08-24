"""Admin labeling API — queue, session grid, merge, reject (spec §7, §10).

Sits behind an API Gateway JWT authorizer bound to the Cognito user pool, so
every request arriving here already carries a cryptographically verified
identity. What the authorizer cannot know is whether that identity is *still*
an admin, so `_caller_email` is re-checked against the DynamoDB allowlist on
every single call. That is the difference between revoking someone's access
now and revoking it whenever their token happens to expire.

Routing is done here rather than as one API Gateway route per endpoint: a
single ANY /api/{proxy+} route keeps the Terraform to one resource and puts
the whole surface of the API in one readable table (ROUTES, below).
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from ulid import ULID

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
        _require_admin(email)
        handler_fn, params = _match_route(method, path)
        body = _parse_body(event)
        result = handler_fn(email=email, body=body, query=_query(event), **params)
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


def _require_admin(email):
    item = table.get_item(Key={"PK": f"ADMIN#{email}", "SK": "META"}).get("Item")
    if not item:
        logger.warning("rejected non-admin caller=%s", email)
        raise ApiError(403, "not an admin")


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


def _get_me(email, **_):
    return {"email": email}


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
    items = []
    kwargs = {
        "IndexName": "GSI1",
        "KeyConditionExpression": Key("GSI1PK").eq(f"SESSION#{session_id}"),
        "ScanIndexForward": True,
    }
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _photo_payload(photo):
    photo_id = photo["photoId"]
    payload = _clean(photo)
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
    return {"cats": [_clean(c) for c in cats]}


def _get_cat(cat_id, **_):
    cat = table.get_item(Key={"PK": f"CAT#{cat_id}", "SK": "META"}).get("Item")
    if not cat:
        raise ApiError(404, "no such cat")
    photos = _cat_photos(cat_id)
    return {"cat": _clean(cat), "photos": [_photo_payload(p) for p in photos]}


def _cat_photos(cat_id):
    items = []
    kwargs = {
        "IndexName": "GSI3",
        "KeyConditionExpression": Key("GSI3PK").eq(f"CAT#{cat_id}"),
        "ScanIndexForward": True,
    }
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


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


def _unassign_session(session_id, **_):
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


def _add_admin(body, email, **_):
    new_email = _required_string(body, "email", maximum=254).lower()
    if "@" not in new_email:
        raise ApiError(400, "not an email address")
    now = _now_iso()
    table.put_item(
        Item={
            "PK": f"ADMIN#{new_email}",
            "SK": "META",
            "email": new_email,
            "addedAt": now,
            "addedBy": email,
            "GSI2PK": "ENTITY#ADMIN",
            "GSI2SK": new_email,
        }
    )
    logger.info("admin added=%s by=%s", new_email, email)
    return {"email": new_email}


def _remove_admin(admin_email, email, **_):
    target = admin_email.lower()
    if target == email:
        raise ApiError(409, "cannot remove yourself")
    table.delete_item(Key={"PK": f"ADMIN#{target}", "SK": "META"})
    logger.info("admin removed=%s by=%s", target, email)
    return {"removed": target}


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
# passed to the handler as keyword arguments.
ID = r"[A-Za-z0-9]+"
EMAIL = r"[^/]+"

ROUTES = (
    ("GET", r"^/api/me$", _get_me),
    ("GET", r"^/api/stats$", _get_stats),
    ("GET", r"^/api/queue$", _get_queue),
    # Ahead of the /{session_id} patterns: "merge" would otherwise be read
    # as a session id.
    ("POST", r"^/api/sessions/merge$", _merge_sessions),
    ("GET", rf"^/api/sessions/(?P<session_id>{ID})$", _get_session),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/assign$", _assign_session),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/unassign$", _unassign_session),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/reject$", _reject_session),
    ("GET", r"^/api/cats$", _get_cats),
    ("POST", r"^/api/cats$", _create_cat),
    ("GET", rf"^/api/cats/(?P<cat_id>{ID})$", _get_cat),
    ("PATCH", rf"^/api/cats/(?P<cat_id>{ID})$", _update_cat),
    ("DELETE", rf"^/api/cats/(?P<cat_id>{ID})$", _delete_cat),
    ("POST", rf"^/api/photos/(?P<photo_id>{ID})/assign$", _assign_photo),
    ("POST", rf"^/api/photos/(?P<photo_id>{ID})/reject$", _reject_photo),
    ("GET", r"^/api/admins$", _get_admins),
    ("POST", r"^/api/admins$", _add_admin),
    ("DELETE", rf"^/api/admins/(?P<admin_email>{EMAIL})$", _remove_admin),
)


def _match_route(method, path):
    path = path.rstrip("/") or path
    matched_path = False
    for route_method, pattern, handler_fn in ROUTES:
        match = re.match(pattern, path)
        if not match:
            continue
        matched_path = True
        if route_method == method:
            return handler_fn, match.groupdict()
    raise ApiError(405 if matched_path else 404, f"no route for {method} {path}")
