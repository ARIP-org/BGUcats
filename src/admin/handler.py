"""Admin labeling API — queue, session grid, merge, reject (spec §7, §10),
and in-app capture for the users who photograph cats from the PWA.

Sits behind an API Gateway JWT authorizer bound to the Cognito user pool, so
every request arriving here already carries a cryptographically verified
identity. What the authorizer cannot know is whether that identity is *still*
an admin, so `_caller_email` is re-checked against the DynamoDB allowlist on
every single call. That is the difference between revoking someone's access
now and revoking it whenever their token happens to expire.

Two roles (common.admission; the owner's decision R1, 2026-11-12):
  admin  — everything, as before. On the allowlist (`ADMIN#{email}`) with
           no role, or `role = admin`.
  user   — photographs cats in the app and browses the catalogue. Labeling
           stays with admins: no queue, no assigning, and nothing
           destructive or structural — no deleting, merging, creating or
           renaming cats, no managing people. On the allowlist with
           `role = user` (or `collaborator`, the name before that day), or
           admitted by the account's sign-up policy.
An item with no role is an admin, so every account that existed before roles
(the Terraform bootstrap item, `make admin-add`) keeps its access unchanged.

Routing is done here rather than as one API Gateway route per endpoint: a
single ANY /api/{proxy+} route keeps the Terraform to one resource and puts
the whole surface of the API in one readable table (ROUTES, below).
"""

import base64
import hashlib
import logging
import math
import os
import re
from datetime import UTC, datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from ulid import ULID

from admin import insights
from common import admission, api, encounters, media, proposals, regions, tables, text
from common.api import ApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]

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

# Two roles (common.admission, the owner's decision R1 of 2026-11-12): a
# user, and an admin. `role = collaborator`, written before that day, is a
# user.
ROLE_ADMIN = admission.ROLE_ADMIN
ROLE_USER = admission.ROLE_USER
ROLES = admission.ROLES

# Who may sign in at all (docs/app-plan/, D1). Absent: the allowlist only.
SIGNUP_POLICY = os.environ.get("SIGNUP_POLICY", "allowlist")
SIGNUP_DOMAINS = admission.domains_from(os.environ.get("SIGNUP_DOMAINS"))
# The member app (docs/app-plan/). With it on, a pick and every label of an
# app encounter also keep the person's encounter item in the app's table
# (B3b). With it off, nothing here touches that table.
SOCIAL = os.environ.get("SOCIAL", "off") == "on"
SOCIAL_TABLE_NAME = os.environ.get("SOCIAL_TABLE_NAME", "bgucats-social")

# Who may call a route (see ROUTES).
ANYONE = "anyone"  # any admitted user, admins included
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
# "idempotent on the ULID" rule the bots follow (spec §10).
ULID_PATTERN = api.ULID_PATTERN
# ~110 m, as everywhere else (ingest.core.COORDINATE_DECIMALS): territory,
# not the spot the contributor was standing on.
COORDINATE_DECIMALS = 3
MAX_ACCURACY_METRES = 100_000
RECENT_ENCOUNTERS = 30
ENCOUNTER_PAGES = 5

# A recorded guess keeps a score for every enrolled cat, not just the top
# few, so a later threshold sweep can be run over it. Well above the ~50
# campus cats; the cap only bounds the item size.
MAX_PREDICTION_CATS = 200
# Sessions merged into sessions merged into ... — followed this far when
# finding which cat a predicted session became.
MAX_MERGE_HOPS = 5
# Shared vectors (one per photo per model version), written by admins'
# browsers and read by every phone that guesses. A page stays well under
# the 6 MB Lambda response limit: ~4 KB of base64 per 768-float vector.
VECTOR_WRITE_BATCH = 25
VECTOR_PAGE = 400
VECTOR_DIMENSIONS = range(64, 4097)
# What a contributor can answer when the app shows its three guesses.
# "new": a cat that is not on the list, proposed in the member app (B6).
PICK_CHOICES = ("cat", "none", "unsure", "new")
PICK_SHOWN = 5

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
social_table = dynamodb.Table(SOCIAL_TABLE_NAME)
s3 = boto3.client("s3")


# The request, the response and the reads every API Lambda shares
# (src/common, since 2026-11-12). The names below are the ones this file has
# always used; the tests replace `table`, `s3` and `_query_all` here.
_now_iso = api.now_iso
_response = api.response
_json_default = api.json_default
_caller_email = api.caller_email
_parse_body = api.parse_body
_query = api.query_params
_ulid_param = api.ulid_param
_iso_param = api.iso_param
_required_string = api.required_string
_int_param = api.int_param


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")

    try:
        email = _caller_email(event)
        role = _require_member(email)
        handler_fn, params, access = _match_route(method, path)
        if access == ADMINS and role != ROLE_ADMIN:
            logger.warning("user=%s refused %s %s", email, method, path)
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


def _item(pk):
    """One record by its key, read strongly consistent (common.tables)."""
    return tables.get_one(table, pk)


def _require_member(email):
    """The caller's role, or 403 if the sign-up policy does not admit them.

    Checked on every call, not only at sign-up: removing someone from the
    allowlist, or tightening the policy, shuts them out at once.
    """
    role = admission.role_for(
        email, _item(f"ADMIN#{email}"), SIGNUP_POLICY, SIGNUP_DOMAINS
    )
    if role is None:
        logger.warning("rejected caller=%s policy=%s", email, SIGNUP_POLICY)
        raise ApiError(403, "this account is not let in to BGU Cats")
    return role


def _role_of(item):
    return admission.role_of(item)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def _get_me(email, role, **_):
    # `social`: whether this account's member app is open, so the desk can
    # offer the way there (web/app.js, #new-app).
    return {"email": email, "role": role, "social": SOCIAL}


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
    session = _item(f"SESSION#{session_id}")
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
    """Every page of a query, not just the first 1 MB (common.tables)."""
    return tables.query_all(table, **kwargs)


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
    """A signed address for one object (common.media)."""
    return media.presign(s3, MEDIA_BUCKET, key)


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
    cat = _item(f"CAT#{cat_id}")
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
        pending=_status_items("pending"),
        sessions=_batch_get_sessions(session_ids),
        profiles=_entities("SUBMITTER"),
        traffic=_entities("TRAFFIC"),
        links=_entities("LINK"),
        cats=_entities("CAT"),
        now=datetime.now(UTC),
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


def _create_cat(body, email, cat_id=None, **_):
    """A new cat. `cat_id` is given only by an approved proposal, whose id
    becomes the cat's, so approving twice makes one cat (B6)."""
    name = _required_string(body, "name", maximum=80)
    cat_id = cat_id or str(ULID())
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
    # Public, unlike notes: shown to every user on the cat's page (B2 of
    # docs/app-plan/). Written by an admin, so not sent to moderation.
    if "bio" in body:
        updates["bio"] = text.clean(
            body.get("bio"), "bio", 280, required=False, multiline=True
        )
    if "coat" in body:
        coat = body.get("coat") or None
        if coat is not None and coat not in proposals.COATS:
            raise ApiError(400, f"coat is one of {', '.join(proposals.COATS)}")
        updates["coat"] = coat
    if "usualRegionId" in body:
        region = body.get("usualRegionId") or None
        if region is not None and region not in regions.ids():
            raise ApiError(400, "usualRegionId is not one of the campus places")
        updates["usualRegionId"] = region
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
    assigned_ids = []
    for photo in photos:
        if photo.get("status") in UNASSIGNABLE_STATUSES:
            continue
        _assign_photo_item(photo, cat_id, email)
        assigned += 1
        assigned_ids.append(photo["photoId"])

    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET catId = :cat, labeledAt = :now, labeledBy = :by",
        ExpressionAttributeValues={":cat": cat_id, ":now": _now_iso(), ":by": email},
    )
    _refresh_cat_photo_count(cat_id, present=assigned_ids)
    _sync_encounters(session_id, photos)
    return {"sessionId": session_id, "catId": cat_id, "assigned": assigned}


def _assign_photo(photo_id, body, email, **_):
    cat_id = _required_string(body, "catId", maximum=64)
    _assert_cat_exists(cat_id)
    photo = _require_photo(photo_id)
    if photo.get("status") in UNASSIGNABLE_STATUSES:
        raise ApiError(409, f"photo is {photo.get('status')}")
    _assign_photo_item(photo, cat_id, email)
    _refresh_cat_photo_count(cat_id, present=[photo_id])
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
    unassigned_ids = [p["photoId"] for p in photos if p.get("status") == "labeled"]
    for cat_id in previous:
        _refresh_cat_photo_count(cat_id, absent=unassigned_ids)
    _sync_encounters(session_id, photos)
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

    target = _item(f"SESSION#{target_id}")
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
    moved_ids = [p["photoId"] for p in photos]
    _refresh_session_photo_count(target_id, present=moved_ids)

    target_cat = target.get("catId")
    if target_cat:
        # The target was already labeled, so the photos that just arrived
        # inherit its cat rather than dropping back into the queue.
        for photo in photos:
            if photo.get("status") not in UNASSIGNABLE_STATUSES:
                _assign_photo_item(photo, target_cat, email)
        _refresh_cat_photo_count(
            target_cat,
            present=[
                p["photoId"]
                for p in photos
                if p.get("status") not in UNASSIGNABLE_STATUSES
            ],
        )

    # A merge counts as a label: the source encounter is now the target's
    # cat, or unlabeled with it.
    _sync_encounters(source_id, photos)
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
    # Its recognition vectors go with it: a deleted photo must not keep
    # being matched against.
    for vector in _query_all(
        KeyConditionExpression=Key("PK").eq(f"PHOTO#{photo_id}")
        & Key("SK").begins_with("VECTOR#")
    ):
        table.delete_item(Key={"PK": vector["PK"], "SK": vector["SK"]})
    sha256 = photo.get("sha256")
    if sha256:
        # Frees the content hash so an intentional re-submission of the same
        # image is treated as new rather than as a duplicate of a record
        # that no longer exists.
        table.delete_item(Key={"PK": f"SHA#{sha256}", "SK": "META"})

    if session_id:
        _refresh_session_photo_count(session_id, absent=[photo_id])
    if cat_id:
        _refresh_cat_photo_count(cat_id, absent=[photo_id])

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
    _sync_encounters(session_id, photos)
    return {"deleted": len(photos), "sessionId": session_id}


# --------------------------------------------------------------------------
# Recognition — measuring the model on real sessions
# --------------------------------------------------------------------------
#
# The model runs in the admin's browser (web/recognition.js); nothing here
# touches it. The API does two boring things: hands the browser the labeled
# photos to build templates from, and keeps a record of what the model
# guessed for a session *before* a person labeled it. Joining that record
# with the label the person later gave is the measurement.


def _get_recognition_gallery(**_):
    """Every labeled photo, with a URL to its 1024px derivative.

    The browser embeds each one once per model version and keeps the
    vectors on the device. Videos have no derivative and are left out.
    """
    photos = _status_items("labeled")
    return {
        "photos": [
            {
                "photoId": p["photoId"],
                "sessionId": p.get("sessionId"),
                "catId": p["catId"],
                "mediumUrl": _presign(f"derived/{p['photoId']}/medium-1024.webp"),
            }
            for p in photos
            if p.get("catId") and p.get("mediaType") != "video"
        ]
    }


def _record_prediction(session_id, body, email, **_):
    """What the model guessed for an unlabeled session.

    Refused once the session has a cat: a guess made after the answer is
    known measures nothing. The first guess per model version wins — a
    retry, or a second admin opening the same session, cannot overwrite it.
    """
    model_version = _required_string(body, "modelVersion", maximum=40)
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model_version):
        raise ApiError(400, "modelVersion is not a version string")
    ranked = body.get("ranked")
    if not isinstance(ranked, list) or len(ranked) > MAX_PREDICTION_CATS:
        raise ApiError(400, f"ranked must be a list of at most {MAX_PREDICTION_CATS}")
    cleaned = []
    for entry in ranked:
        cat_id = entry.get("catId") if isinstance(entry, dict) else None
        score = entry.get("score") if isinstance(entry, dict) else None
        if not isinstance(cat_id, str) or not re.fullmatch(ID, cat_id):
            raise ApiError(400, "every ranked entry needs a catId")
        if not isinstance(score, (int, float)) or not -1.0 <= score <= 1.0:
            raise ApiError(400, "every score is a cosine similarity in [-1, 1]")
        cleaned.append({"catId": cat_id, "score": Decimal(str(round(score, 4)))})
    photo_count = body.get("photoCount")
    if not isinstance(photo_count, int) or photo_count < 1:
        raise ApiError(400, "photoCount must be a positive integer")

    session = _item(f"SESSION#{session_id}")
    if not session:
        raise ApiError(404, "no such session")
    if session.get("catId"):
        raise ApiError(409, "session is already labeled")

    now = _now_iso()
    item = {
        "PK": f"SESSION#{session_id}",
        "SK": f"PREDICTION#{model_version}",
        "sessionId": session_id,
        "modelVersion": model_version,
        "ranked": cleaned,
        "photoCount": photo_count,
        "predictedAt": now,
        "predictedBy": email,
        "GSI2PK": "ENTITY#PREDICTION",
        "GSI2SK": now,
    }
    # One transaction, so a label landing between the check above and this
    # write cannot leave a guess that was made after the answer was known.
    client = table.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": table.name,
                        "Key": {"PK": f"SESSION#{session_id}", "SK": "META"},
                        # Sessions are written with catId = null (the bots,
                        # the app, and an unassign), and a null attribute
                        # exists: attribute_not_exists alone refused every
                        # real session as "already labeled" until 2026-10-29.
                        "ConditionExpression": "attribute_not_exists(catId)"
                        " OR attribute_type(catId, :null)",
                        "ExpressionAttributeValues": {":null": "NULL"},
                    }
                },
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": item,
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
            ]
        )
    except client.exceptions.TransactionCanceledException as err:
        reasons = [r.get("Code") for r in err.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            raise ApiError(409, "session is already labeled")
        return {"sessionId": session_id, "modelVersion": model_version, "new": False}
    return {"sessionId": session_id, "modelVersion": model_version, "new": True}


def _get_predictions(**_):
    """Every recorded guess — the admins' blind ones and the contributors'
    picks — joined with the cat its session ended up as.

    A session merged into another takes the cat of the one it joined —
    merging is a person saying "same cat". `truthCatId` is null while the
    session is still unlabeled and for a deleted one: neither is a
    measurement.
    """
    predictions = _entities("PREDICTION")
    picks = _entities("PICK")
    sessions = _batch_get_sessions({p["sessionId"] for p in predictions + picks})
    for _ in range(MAX_MERGE_HOPS):
        targets = {
            s["mergedInto"]
            for s in sessions.values()
            if s.get("mergedInto") and s["mergedInto"] not in sessions
        }
        if not targets:
            break
        sessions.update(_batch_get_sessions(targets))

    def resolve(session_id):
        session = sessions.get(session_id) or {}
        for _ in range(MAX_MERGE_HOPS):
            if not session.get("mergedInto"):
                break
            session = sessions.get(session["mergedInto"]) or {}
        return session

    def joined(items):
        out = []
        for p in items:
            session = resolve(p["sessionId"])
            gone = not session or session.get("rejectedAt")
            out.append(
                {
                    **_clean(p),
                    "truthCatId": None if gone else session.get("catId"),
                    "labeledAt": None if gone else session.get("labeledAt"),
                }
            )
        return out

    return {"predictions": joined(predictions), "picks": joined(picks)}


def _model_version_param(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]{0,39}", value
    ):
        raise ApiError(400, "modelVersion is not a version string")
    return value


def _put_vectors(body, email, **_):
    """Vectors an admin's browser computed for labeled photos.

    Every phone that guesses matches against these instead of downloading
    and embedding every labeled photo itself — and they come from the same
    browser pipeline the phones use, so gallery and query agree. Admins
    only: a vector is trusted data. Rewriting one is harmless (same model,
    same photo, same vector), so a retry is a no-op in effect.
    """
    version = _model_version_param(body.get("modelVersion"))
    entries = body.get("vectors")
    if not isinstance(entries, list) or not 0 < len(entries) <= VECTOR_WRITE_BATCH:
        raise ApiError(400, f"vectors must hold 1 to {VECTOR_WRITE_BATCH} entries")
    decoded = {}
    for entry in entries:
        photo_id = entry.get("photoId") if isinstance(entry, dict) else None
        if not isinstance(photo_id, str) or not re.fullmatch(ID, photo_id):
            raise ApiError(400, "every vector needs a photoId")
        decoded[photo_id] = _decode_vector(entry.get("vector"))

    photos = _batch_get_photos(decoded)
    now = _now_iso()
    written = 0
    with table.batch_writer() as batch:
        for photo_id, raw in decoded.items():
            photo = photos.get(photo_id)
            if not photo or photo.get("status") in UNASSIGNABLE_STATUSES:
                continue  # deleted, or never a template: skip, don't fail
            batch.put_item(
                Item={
                    "PK": f"PHOTO#{photo_id}",
                    "SK": f"VECTOR#{version}",
                    "photoId": photo_id,
                    "modelVersion": version,
                    "vector": raw,
                    "computedAt": now,
                    "computedBy": email,
                    "GSI2PK": f"VECTOR#{version}",
                    "GSI2SK": photo_id,
                }
            )
            written += 1
    return {"written": written}


def _decode_vector(value):
    """Base64 of little-endian float32s, unit length (the model L2-normalises)."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (TypeError, ValueError):
        raise ApiError(400, "vector must be base64")
    if len(raw) % 4 or len(raw) // 4 not in VECTOR_DIMENSIONS:
        raise ApiError(400, "vector has the wrong length")
    floats = memoryview(raw).cast("f")
    norm = math.sqrt(sum(x * x for x in floats))
    if not math.isfinite(norm) or abs(norm - 1) > 0.01:
        raise ApiError(400, "vector must be unit length")
    return raw


def _batch_get_photos(photo_ids):
    photos = {}
    keys = [{"PK": f"PHOTO#{pid}", "SK": "META"} for pid in sorted(photo_ids)]
    for start in range(0, len(keys), BATCH_GET_LIMIT):
        request = {table.name: {"Keys": keys[start : start + BATCH_GET_LIMIT]}}
        while request:
            response = table.meta.client.batch_get_item(RequestItems=request)
            for item in response["Responses"].get(table.name, []):
                photos[item["photoId"]] = item
            request = response.get("UnprocessedKeys") or None
    return photos


def _get_vectors(query, **_):
    """The templates a phone matches against: labeled photos that have a
    vector for this model version, a page at a time.

    Any member may read them — a contributor's phone guesses with them.
    They are numbers, not photos, and say no more than the cat list does.
    """
    version = _model_version_param(query.get("version"))
    kwargs = {
        "IndexName": "GSI2",
        "KeyConditionExpression": Key("GSI2PK").eq(f"VECTOR#{version}"),
        "Limit": VECTOR_PAGE,
    }
    after = query.get("after")
    if after:
        if not re.fullmatch(ID, after):
            raise ApiError(400, "after must be a photo id")
        kwargs["ExclusiveStartKey"] = {
            "PK": f"PHOTO#{after}",
            "SK": f"VECTOR#{version}",
            "GSI2PK": f"VECTOR#{version}",
            "GSI2SK": after,
        }
    page = table.query(**kwargs)
    labeled = {p["photoId"]: p for p in _status_items("labeled") if p.get("catId")}
    templates = []
    for item in page["Items"]:
        photo = labeled.get(item["photoId"])
        if not photo or photo.get("mediaType") == "video":
            continue
        templates.append(
            {
                "photoId": item["photoId"],
                "catId": photo["catId"],
                "sessionId": photo.get("sessionId"),
                "vector": base64.b64encode(bytes(item["vector"])).decode(),
            }
        )
    last = page.get("LastEvaluatedKey")
    return {"templates": templates, "next": last["GSI2SK"] if last else None}


def _record_pick(session_id, body, email, **_):
    """What a contributor answered when the app showed its guesses.

    Their own encounter only. The latest answer wins — someone may change
    their mind after a better photo — and it is kept apart from the label:
    the labeling desk never reads it, so the admin's label stays blind and
    can score both the model and the contributor.
    """
    session = _require_encounter(session_id, email)
    version = _model_version_param(body.get("modelVersion"))
    choice = body.get("choice")
    if choice not in PICK_CHOICES:
        raise ApiError(400, "choice must be cat, none, unsure or new")
    cat_id = body.get("catId") if choice == "cat" else None
    if choice == "cat":
        if not isinstance(cat_id, str) or not re.fullmatch(ID, cat_id):
            raise ApiError(400, "a cat pick needs a catId")
        _assert_cat_exists(cat_id)
    shown = body.get("shown")
    if (
        not isinstance(shown, list)
        or not 0 < len(shown) <= PICK_SHOWN
        or not all(isinstance(c, str) and re.fullmatch(ID, c) for c in shown)
    ):
        raise ApiError(400, f"shown must list 1 to {PICK_SHOWN} cat ids")
    ranked = body.get("ranked")
    if not isinstance(ranked, list) or len(ranked) > MAX_PREDICTION_CATS:
        raise ApiError(400, f"ranked must be a list of at most {MAX_PREDICTION_CATS}")
    cleaned = []
    for entry in ranked:
        rid = entry.get("catId") if isinstance(entry, dict) else None
        score = entry.get("score") if isinstance(entry, dict) else None
        if not isinstance(rid, str) or not re.fullmatch(ID, rid):
            raise ApiError(400, "every ranked entry needs a catId")
        if not isinstance(score, (int, float)) or not -1.0 <= score <= 1.0:
            raise ApiError(400, "every score is a cosine similarity in [-1, 1]")
        cleaned.append({"catId": rid, "score": Decimal(str(round(score, 4)))})
    photo_count = body.get("photoCount")
    if not isinstance(photo_count, int) or photo_count < 1:
        raise ApiError(400, "photoCount must be a positive integer")

    now = _now_iso()
    table.put_item(
        Item={
            "PK": f"SESSION#{session_id}",
            "SK": "PICK",
            "sessionId": session_id,
            "modelVersion": version,
            "choice": choice,
            "catId": cat_id,
            "shown": shown,
            "ranked": cleaned,
            "photoCount": photo_count,
            "pickedAt": _iso_param(body, "pickedAt") or now,
            "receivedAt": now,
            "pickedBy": email,
            "GSI2PK": "ENTITY#PICK",
            "GSI2SK": session_id,
        }
    )
    _record_encounter_claim(session, cat_id, email)
    return {"sessionId": session_id, "choice": choice}


# --------------------------------------------------------------------------
# The person's encounter, in the app's table (B3b)
# --------------------------------------------------------------------------
#
# A pick is a person's claim; a label is an admin's. The app counts the
# claim at once and follows the label when there is one (D8). This API is
# the one that sees both, so it keeps `ENC` (common/encounters.py) and the
# events Lambda does the counting from there. Only for a person who has
# opened the app: one who never has has no user to count for.

# Merges chain (A into B, then B into C); following more than this many is
# a loop or a mistake, and the encounter is left as it is.
MERGE_HOPS = 5


def _record_encounter_claim(session, cat_id, email):
    if not SOCIAL:
        return
    user_id = encounters.user_id_for(social_table, email)
    if user_id is None:
        return
    encounters.update(
        social_table,
        user_id,
        session["sessionId"],
        {
            **encounters.place_fields(session),
            "userId": user_id,
            "claimedCatId": cat_id,
            "updatedAt": _now_iso(),
        },
    )
    # The label is read after the claim is written. An admin who labels in
    # between finds the item there, or this read finds their label.
    _sync_encounter(session["sessionId"])


def _label_of(session):
    """(cat, rejected) for a session, following merges to where its photos
    went."""
    for _ in range(MERGE_HOPS):
        if session.get("rejectedAt"):
            return None, True
        target = session.get("mergedInto")
        if not target:
            return session.get("catId"), False
        session = _item(f"SESSION#{target}") or {}
    return None, False


def _sync_encounter(session_id):
    """The encounter's label, from the dataset as it is now. Does nothing
    for a session that is not an app encounter of someone in the app."""
    if not SOCIAL:
        return
    session = _item(f"SESSION#{session_id}")
    if not session or session.get("channel") != APP_CHANNEL:
        return
    user_id = encounters.user_id_for(social_table, session.get("startedBy"))
    if user_id is None:
        return
    cat_id, rejected = _label_of(session)
    encounters.update(
        social_table,
        user_id,
        session_id,
        {"labelCatId": cat_id, "rejected": rejected, "updatedAt": _now_iso()},
        only_if_there=True,
    )


def _sync_encounters(session_id, photos):
    """This session's encounter, and those merged into it: their photos
    carry where they came from, and their label is this one's."""
    _sync_encounter(session_id)
    merged = {p.get("mergedFromSessionId") for p in photos} - {None, session_id}
    for source in sorted(merged):
        _sync_encounter(source)


# --------------------------------------------------------------------------
# New-cat proposals (B6): the desk's minimum, until the admin desk is
# designed (docs/app-plan/04-api.md, "New desk routes")
# --------------------------------------------------------------------------
#
# A person in the member app says "a cat that isn't here". Nothing about it
# is public until an admin decides (D7): approve (a new cat, named by the
# admin, from the person's idea), merge (it is a cat we know), or reject.
# Approve and merge label the encounter the way the queue does, which is
# also what corrects the person's counters (ENC). The events Lambda then
# releases or hides the post that waited.


def _get_proposals(query, **_):
    if not SOCIAL:
        return {"proposals": []}
    status = query.get("status") or "open"
    if status not in proposals.STATUSES:
        raise ApiError(400, f"status is one of {', '.join(proposals.STATUSES)}")
    items = tables.query_all(
        social_table,
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq(f"PROPOSALS#{status}"),
        ScanIndexForward=True,  # oldest first, like the queue
    )
    out = []
    for item in items:
        person = (
            social_table.get_item(
                Key={"PK": f"USER#{item['proposerId']}", "SK": "PROFILE"}
            ).get("Item")
            or {}
        )
        photos = [
            _photo_payload(photo)
            for photo in _session_photos(item["sessionId"])
            if photo.get("status") not in UNASSIGNABLE_STATUSES
        ]
        out.append(
            {
                "proposalId": item["proposalId"],
                "sessionId": item["sessionId"],
                "nameIdea": item.get("nameIdea") or "",
                "coat": item.get("coat"),
                "regionId": item.get("regionId"),
                "traits": list(item.get("traits") or []),
                "status": item["status"],
                "catId": item.get("catId"),
                "createdAt": item["createdAt"],
                "proposer": {
                    "username": person.get("username"),
                    "email": person.get("email"),
                },
                "photos": photos,
            }
        )
    return {"proposals": out}


def _require_proposal(proposal_id):
    if not SOCIAL:
        raise ApiError(404, "no such proposal")
    item = social_table.get_item(
        Key={"PK": f"PROPOSAL#{proposal_id}", "SK": "META"}, ConsistentRead=True
    ).get("Item")
    if item is None:
        raise ApiError(404, "no such proposal")
    return item


def _decide(proposal, status, cat_id, email):
    """Record the decision, once: a second, different decision is refused."""
    if proposal["status"] != "open":
        if proposal["status"] == status and proposal.get("catId") == cat_id:
            return  # the same decision again: the outbox of the desk, a retry
        raise ApiError(409, f"this proposal was {proposal['status']} already")
    now = _now_iso()
    try:
        social_table.update_item(
            Key={"PK": proposal["PK"], "SK": "META"},
            UpdateExpression=(
                "SET #s = :status, catId = :cat, decidedBy = :by, decidedAt = :now, "
                "GSI2PK = :queue"
            ),
            ConditionExpression="#s = :open",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":cat": cat_id,
                ":by": email,
                ":now": now,
                ":queue": f"PROPOSALS#{status}",
                ":open": "open",
            },
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ApiError(409, "this proposal was decided meanwhile") from None


def _approve_proposal(proposal_id, body, email, **_):
    proposal = _require_proposal(proposal_id)
    if proposal["status"] == "approved":
        return {"proposalId": proposal_id, "catId": proposal["catId"]}
    if proposal["status"] != "open":
        raise ApiError(409, f"this proposal was {proposal['status']} already")
    name = (body.get("name") or proposal.get("nameIdea") or "").strip()
    if not name:
        raise ApiError(400, "a new cat needs a name; this proposal has no idea for one")
    # The proposal's id is the cat's: a retry finds the cat it made.
    cat_id = proposal_id
    if not _item(f"CAT#{cat_id}"):
        try:
            _create_cat({"name": name}, email, cat_id=cat_id)
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass
    public = {}
    if proposal.get("coat"):
        public["coat"] = proposal["coat"]
    if proposal.get("regionId") in regions.ids():
        public["usualRegionId"] = proposal["regionId"]
    if public:
        _update_cat(cat_id, public)
    _assign_session(proposal["sessionId"], {"catId": cat_id}, email)
    _decide(proposal, "approved", cat_id, email)
    return {"proposalId": proposal_id, "catId": cat_id, "name": name}


def _merge_proposal(proposal_id, body, email, **_):
    proposal = _require_proposal(proposal_id)
    cat_id = _required_string(body, "catId", maximum=64)
    _assert_cat_exists(cat_id)
    if proposal["status"] == "open":
        _assign_session(proposal["sessionId"], {"catId": cat_id}, email)
    _decide(proposal, "merged", cat_id, email)
    return {"proposalId": proposal_id, "catId": cat_id}


def _reject_proposal(proposal_id, email, **_):
    """Not a new cat. The encounter stays in the queue, to be labeled or
    rejected there like any other; only the proposal is closed."""
    proposal = _require_proposal(proposal_id)
    _decide(proposal, "rejected", None, email)
    return {"proposalId": proposal_id, "status": "rejected"}


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
    user. Making someone an admin is always an explicit choice."""
    new_email = _required_string(body, "email", maximum=254).lower()
    if "@" not in new_email:
        raise ApiError(400, "not an email address")
    role = _role_param(body, default=ROLE_USER)
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
    """admin or user; "collaborator", the old name for a user, is accepted."""
    role = admission.normalise_role(body.get("role") or default)
    if role is None:
        raise ApiError(400, "role must be admin or user")
    return role


def _remove_admin(admin_email, email, **_):
    target = admin_email.lower()
    if target == email:
        raise ApiError(409, "cannot remove yourself")
    table.delete_item(Key={"PK": f"ADMIN#{target}", "SK": "META"})
    logger.info("admin removed=%s by=%s", target, email)
    return {"removed": target}


# --------------------------------------------------------------------------
# In-app capture — the PWA's own channel next to the Telegram bot
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
    keeps the namespace apart from the bots' IDs.
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
    # Only encounters that hold something. One opened and closed with nothing
    # in it (or whose files are still on the phone — Capture shows those
    # itself) is not an encounter anyone needs to see. Filtered after the
    # read, so a run of empty ones costs another page, never a short list.
    items = []
    kwargs = {
        "IndexName": "GSI2",
        "KeyConditionExpression": Key("GSI2PK").eq("ENTITY#ENCOUNTER")
        & Key("GSI2SK").begins_with(f"{email}#"),
        "ScanIndexForward": False,
        "Limit": RECENT_ENCOUNTERS,
    }
    for _ in range(ENCOUNTER_PAGES):
        page = table.query(**kwargs)
        items += [i for i in page["Items"] if i.get("photoCount")]
        if len(items) >= RECENT_ENCOUNTERS or "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items = items[:RECENT_ENCOUNTERS]
    names = {c["catId"]: c["name"] for c in _entities("CAT")}
    picks = _batch_get_picks([item["sessionId"] for item in items])
    out = []
    for item in items:
        entry = {**_clean(item), "catName": names.get(item.get("catId"))}
        pick = picks.get(item["sessionId"])
        if pick:
            # Their own answer and the model's first guess, so the screen
            # can say how each held up against the label.
            model_cat = (pick.get("ranked") or [{}])[0].get("catId")
            entry["pick"] = {
                "choice": pick["choice"],
                "catId": pick.get("catId"),
                "catName": names.get(pick.get("catId")),
                "modelCatId": model_cat,
                "modelCatName": names.get(model_cat),
            }
        out.append(entry)
    return {"encounters": out}


def _batch_get_picks(session_ids):
    picks = {}
    keys = [{"PK": f"SESSION#{sid}", "SK": "PICK"} for sid in session_ids]
    for start in range(0, len(keys), BATCH_GET_LIMIT):
        request = {table.name: {"Keys": keys[start : start + BATCH_GET_LIMIT]}}
        while request:
            response = table.meta.client.batch_get_item(RequestItems=request)
            for item in response["Responses"].get(table.name, []):
                picks[item["sessionId"]] = item
            request = response.get("UnprocessedKeys") or None
    return picks


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
    created_at = _now_iso()

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
        "createdAt": created_at,
        "uploadKey": key,
        # On the status index while pending, like the bots' records, so an
        # upload that never completes is counted on the Stats page.
        "GSI2PK": "STATUS#pending",
        "GSI2SK": created_at,
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

    session = _item(f"SESSION#{session_id}")
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET lastPhotoAt = :now",
        ExpressionAttributeValues={":now": _now_iso()},
    )
    _refresh_session_photo_count(session_id, present=[photo_id])
    _locate_session_from_photo(session, photo)

    cat_id = session.get("catId")
    if cat_id and status == "unlabeled":
        # Someone labeled the encounter while it was still being filmed; a
        # late photo of the same sitting is the same cat (cf. merge).
        _assign_photo_item(
            {**photo, "photoId": photo_id}, cat_id, session.get("labeledBy") or email
        )
        _refresh_cat_photo_count(cat_id, present=[photo_id])
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
    session = _item(f"SESSION#{session_id}")
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


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _assert_cat_exists(cat_id):
    if not _item(f"CAT#{cat_id}"):
        raise ApiError(404, "no such cat")


def _require_photo(photo_id):
    photo = _item(f"PHOTO#{photo_id}")
    if not photo:
        raise ApiError(404, "no such photo")
    return photo


def _refresh_cat_photo_count(cat_id, present=(), absent=()):
    """Recounted rather than incremented: an idempotent write that cannot
    drift, which matters when the same merge is retried.

    The index is eventually consistent, so it may not yet show what this very
    request wrote (or still show what it removed). The caller names those
    photos: `present` are counted even if the index misses them, `absent` are
    left out even if it still lists them."""
    _store_count(
        {"PK": f"CAT#{cat_id}", "SK": "META"},
        _indexed_ids("GSI3", "GSI3PK", f"CAT#{cat_id}", present, absent),
    )


def _refresh_session_photo_count(session_id, present=(), absent=()):
    _store_count(
        {"PK": f"SESSION#{session_id}", "SK": "META"},
        _indexed_ids("GSI1", "GSI1PK", f"SESSION#{session_id}", present, absent),
    )


def _indexed_ids(index, key_name, key_value, present, absent):
    ids = {
        item["PK"]
        for item in _query_all(
            IndexName=index,
            KeyConditionExpression=Key(key_name).eq(key_value),
            ProjectionExpression="PK",
        )
    }
    ids |= {f"PHOTO#{photo_id}" for photo_id in present}
    ids -= {f"PHOTO#{photo_id}" for photo_id in absent}
    return ids


def _store_count(key, ids):
    table.update_item(
        Key=key,
        UpdateExpression="SET photoCount = :count",
        ExpressionAttributeValues={":count": len(ids)},
    )


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
    ("GET", r"^/api/stats$", _get_stats, ADMINS),
    ("GET", r"^/api/insights$", _get_insights, ADMINS),
    ("POST", r"^/api/links$", _create_link, ADMINS),
    ("PATCH", rf"^/api/links/(?P<slug>{LINK_SLUG})$", _update_link, ADMINS),
    ("DELETE", rf"^/api/links/(?P<slug>{LINK_SLUG})$", _delete_link, ADMINS),
    ("GET", r"^/api/queue$", _get_queue, ADMINS),
    # Ahead of the /{session_id} patterns: "merge" would otherwise be read
    # as a session id.
    ("POST", r"^/api/sessions/merge$", _merge_sessions, ADMINS),
    ("GET", r"^/api/proposals$", _get_proposals, ADMINS),
    (
        "POST",
        rf"^/api/proposals/(?P<proposal_id>{ID})/approve$",
        _approve_proposal,
        ADMINS,
    ),
    ("POST", rf"^/api/proposals/(?P<proposal_id>{ID})/merge$", _merge_proposal, ADMINS),
    (
        "POST",
        rf"^/api/proposals/(?P<proposal_id>{ID})/reject$",
        _reject_proposal,
        ADMINS,
    ),
    ("GET", rf"^/api/sessions/(?P<session_id>{ID})$", _get_session, ADMINS),
    ("POST", rf"^/api/sessions/(?P<session_id>{ID})/assign$", _assign_session, ADMINS),
    (
        "POST",
        rf"^/api/sessions/(?P<session_id>{ID})/unassign$",
        _unassign_session,
        ADMINS,
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
    (
        "POST",
        rf"^/api/encounters/(?P<session_id>{ID})/pick$",
        _record_pick,
        ANYONE,
    ),
    ("POST", r"^/api/encounters$", _create_encounter, ANYONE),
    (
        "POST",
        rf"^/api/encounters/(?P<session_id>{ID})/media$",
        _create_upload,
        ANYONE,
    ),
    ("GET", r"^/api/recognition/gallery$", _get_recognition_gallery, ADMINS),
    ("GET", r"^/api/recognition/predictions$", _get_predictions, ADMINS),
    ("GET", r"^/api/recognition/vectors$", _get_vectors, ANYONE),
    ("POST", r"^/api/recognition/vectors$", _put_vectors, ADMINS),
    (
        "POST",
        rf"^/api/sessions/(?P<session_id>{ID})/prediction$",
        _record_prediction,
        ADMINS,
    ),
    ("GET", r"^/api/admins$", _get_admins_with_roles, ADMINS),
    ("POST", r"^/api/admins$", _add_admin, ADMINS),
    ("PATCH", rf"^/api/admins/(?P<admin_email>{EMAIL})$", _set_role, ADMINS),
    ("DELETE", rf"^/api/admins/(?P<admin_email>{EMAIL})$", _remove_admin, ADMINS),
)


def _match_route(method, path):
    return api.match_route(ROUTES, method, path)
