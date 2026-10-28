"""Admin labelling Lambda: serves the labelling page and its JSON API.

    GET    /admin                         the page (no data in it, no auth)
    GET    /admin/api/queue               unlabelled sessions, oldest first
    GET    /admin/api/sessions/{id}       one session's photos
    POST   /admin/api/sessions/{id}/assign   {"catId"}
    POST   /admin/api/sessions/{id}/reject   {"reason"}
    POST   /admin/api/photos/reject       {"photoIds", "reason"}
    POST   /admin/api/photos/restore      {"photoIds"}
    GET    /admin/api/cats                the catalogue, with coverage
    POST   /admin/api/cats                {"catId"?, "fields"}
    GET    /admin/api/cats/{id}           one cat, photos grouped by session
    PATCH  /admin/api/cats/{id}           {"fields"}
    POST   /admin/api/cats/{id}/merge     {"intoCatId"}

Every /admin/api route requires `Authorization: Bearer <token>`, compared in
constant time against a SecureString in SSM. Without it this is an open write
endpoint onto the dataset, the same reason the webhook checks its secret token
(spec §8.5). The token is long and random, so guessing it is not a practical
attack; it is never logged.

The media bucket stays private. Photos reach the browser as presigned GET URLs
for the WebP derivatives only — never the raw originals — valid for an hour.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config

from admin import store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
ADMIN_TOKEN_PARAM = os.environ["ADMIN_TOKEN_PARAM"]

URL_EXPIRY_SECONDS = 3600
PAGE = (Path(__file__).parent / "page.html").read_text()

# The admin token sits in the browser's localStorage, so the page is the one
# place a script injection would be worth something. Its CSP allows exactly
# one script — the page's own, pinned by hash — and nothing else.
_SCRIPT = re.search(r"<script>(.*?)</script>", PAGE, re.DOTALL).group(1)
SCRIPT_HASH = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
# SigV4 explicitly: presigned URLs signed with the legacy scheme are refused
# by newer regions and by buckets that enforce it.
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
ssm = boto3.client("ssm")

_token_cache = None
_image_origin = None


def _admin_token():
    global _token_cache
    if _token_cache is None:
        _token_cache = ssm.get_parameter(Name=ADMIN_TOKEN_PARAM, WithDecryption=True)[
            "Parameter"
        ]["Value"]
    return _token_cache


# --- plumbing ----------------------------------------------------------------


def _image_origins():
    """Where presigned image URLs point, taken from a real presigned URL.

    Derived rather than written out, so it is exact for whatever endpoint the
    S3 client resolves to — virtual-hosted in AWS, the moto server locally.
    Presigning is local computation; no request is made.
    """
    global _image_origin
    if _image_origin is None:
        parts = urlsplit(_url("csp-probe", "thumb-256.webp"))
        _image_origin = f"{parts.scheme}://{parts.netloc}"
    return _image_origin


def content_security_policy():
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src 'sha256-{SCRIPT_HASH}'",
            # Inline style attributes are set by the page's own script; styles
            # cannot run code, so 'unsafe-inline' here is not the risk it is
            # for scripts.
            "style-src 'unsafe-inline' https://fonts.googleapis.com",
            "font-src https://fonts.gstatic.com",
            f"img-src {_image_origins()}",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )


def _plain(value):
    """DynamoDB returns Decimal for every number; JSON wants int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_plain(v) for v in value]
    return value


def _json(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(_plain(body)),
    }


def _body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise store.StoreError("request body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise store.StoreError("request body must be a JSON object")
    return data


def _authorised(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    supplied = headers.get("authorization", "")
    if not supplied.startswith("Bearer "):
        return False
    return hmac.compare_digest(supplied[7:].encode(), _admin_token().encode())


def _encode_cursor(key):
    if not key:
        return None
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def _decode_cursor(value):
    if not value:
        return None
    try:
        key = json.loads(base64.urlsafe_b64decode(value.encode()))
    except ValueError as exc:
        raise store.StoreError("bad cursor") from exc
    if not isinstance(key, dict) or set(key) != {"PK", "SK", "GSI2PK", "GSI2SK"}:
        raise store.StoreError("bad cursor")
    if not all(isinstance(v, str) for v in key.values()):
        raise store.StoreError("bad cursor")
    return key


def _url(photo_id, name):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": MEDIA_BUCKET, "Key": f"derived/{photo_id}/{name}"},
        ExpiresIn=URL_EXPIRY_SECONDS,
    )


def _photo_view(photo):
    # Derivatives exist only once the process Lambda has run; until then the
    # page shows a placeholder rather than a broken image.
    processed = bool(photo.get("processedAt"))
    pid = photo["photoId"]
    return {
        "photoId": pid,
        "sessionId": photo.get("sessionId"),
        "status": photo.get("status"),
        "createdAt": photo.get("createdAt"),
        "capturedAt": photo.get("capturedAt"),
        "catId": photo.get("catId"),
        "nearDuplicateOf": photo.get("nearDuplicateOf"),
        "duplicateOf": photo.get("duplicateOf"),
        "rejectReason": photo.get("rejectReason"),
        "processed": processed,
        "thumb": _url(pid, "thumb-256.webp") if processed else None,
        "medium": _url(pid, "medium-1024.webp") if processed else None,
    }


def _cat_view(cat):
    primary = cat.get("primaryPhotoId")
    photos = int(cat.get("photoCount", 0))
    sessions = int(cat.get("sessionCount", 0))
    view = {k: v for k, v in cat.items() if not k.startswith(("PK", "SK", "GSI"))}
    view["thumb"] = _url(primary, "thumb-256.webp") if primary else None
    view["coverage"] = store.coverage(photos, sessions)
    return view


def _session_view(meta):
    view = {k: v for k, v in meta.items() if not k.startswith(("PK", "SK", "GSI"))}
    # The page shows a short, stable label for who sent it — never the hash.
    submitter = meta.get("submitterHash") or ""
    view.pop("submitterHash", None)
    view["submitter"] = submitter[:6] or None
    return view


# --- routes ------------------------------------------------------------------


def get_queue(event, _parts):
    params = event.get("queryStringParameters") or {}
    result = store.queue(table, limit=20, cursor=_decode_cursor(params.get("cursor")))
    sessions = []
    for entry in result["sessions"]:
        photos = entry["unlabeled"]
        sessions.append(
            {
                "session": _session_view(entry["session"]),
                "unlabeledCount": len(photos),
                "nearDuplicates": sum(1 for p in photos if p.get("nearDuplicateOf")),
                "preview": [_photo_view(p) for p in photos[:6]],
            }
        )
    return 200, {
        "sessions": sessions,
        "cursor": _encode_cursor(result["cursor"]),
        "queueSize": store.queue_size(table),
    }


def get_session(_event, parts):
    session_id = parts[1]
    meta = store.get_session(table, session_id)
    photos = store.session_photos(table, session_id)
    body = {
        "session": _session_view(meta),
        "photos": [_photo_view(p) for p in photos],
        "cat": None,
    }
    if meta.get("catId"):
        try:
            body["cat"] = _cat_view(store.get_cat(table, meta["catId"]))
        except store.NotFound:
            pass
    return 200, body


def assign(event, parts):
    return 200, store.assign_session(table, parts[1], _body(event).get("catId"))


def reject_session(event, parts):
    return 200, store.reject_session(table, parts[1], _body(event).get("reason"))


def _photo_ids(body):
    ids = body.get("photoIds")
    if not isinstance(ids, list) or not ids or len(ids) > 200:
        raise store.StoreError("photoIds must be a list of 1 to 200 ids")
    return ids


def reject_photos(event, _parts):
    body = _body(event)
    return 200, store.reject_photos(table, _photo_ids(body), body.get("reason"))


def restore_photos(event, _parts):
    return 200, store.restore_photos(table, _photo_ids(_body(event)))


def list_cats(_event, _parts):
    cats = [_cat_view(c) for c in store.list_cats(table)]
    return 200, {
        "cats": cats,
        "targets": store.COVERAGE_TARGETS,
        "coatColors": store.COAT_COLORS,
        "coatPatterns": store.COAT_PATTERNS,
        "statuses": store.CAT_STATUSES,
        "usable": sum(1 for c in cats if c["coverage"]["usable"]),
    }


def create_cat(event, _parts):
    body = _body(event)
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise store.StoreError("fields must be an object")
    return 201, _cat_view(store.create_cat(table, fields, body.get("catId")))


def get_cat(_event, parts):
    cat = store.get_cat(table, parts[1])
    photos = store.cat_photos(table, parts[1])
    sessions = {}
    for photo in photos:
        sessions.setdefault(photo["sessionId"], []).append(_photo_view(photo))
    return 200, {
        "cat": _cat_view(cat),
        "sessions": [{"sessionId": sid, "photos": ps} for sid, ps in sessions.items()],
    }


def update_cat(event, parts):
    fields = _body(event).get("fields")
    if not isinstance(fields, dict):
        raise store.StoreError("fields must be an object")
    return 200, _cat_view(store.update_cat(table, parts[1], fields))


def merge_cat(event, parts):
    return 200, store.merge_cats(table, parts[1], _body(event).get("intoCatId"))


# (method, path pattern) -> handler. "*" matches one path segment.
ROUTES = [
    ("GET", ("queue",), get_queue),
    ("GET", ("sessions", "*"), get_session),
    ("POST", ("sessions", "*", "assign"), assign),
    ("POST", ("sessions", "*", "reject"), reject_session),
    ("POST", ("photos", "reject"), reject_photos),
    ("POST", ("photos", "restore"), restore_photos),
    ("GET", ("cats",), list_cats),
    ("POST", ("cats",), create_cat),
    ("GET", ("cats", "*"), get_cat),
    ("PATCH", ("cats", "*"), update_cat),
    ("POST", ("cats", "*", "merge"), merge_cat),
]


def _match(method, parts):
    path_matched = False
    for route_method, pattern, fn in ROUTES:
        if len(pattern) == len(parts) and all(
            p == "*" or p == part for p, part in zip(pattern, parts, strict=True)
        ):
            path_matched = True
            if route_method == method:
                return fn, None
    return None, (405 if path_matched else 404)


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    path = event.get("rawPath") or http.get("path") or "/"

    if path.rstrip("/") == "/admin" and method == "GET":
        return {
            "statusCode": 200,
            "headers": {
                "content-type": "text/html; charset=utf-8",
                # The page is tiny and changes with each deploy.
                "cache-control": "no-cache",
                # Presigned URLs carry a signature; never send them onward.
                "referrer-policy": "no-referrer",
                "content-security-policy": content_security_policy(),
                "x-content-type-options": "nosniff",
            },
            "body": PAGE,
        }

    if not path.startswith("/admin/api/"):
        return _json(404, {"error": "not found"})
    if not _authorised(event):
        return _json(401, {"error": "missing or wrong admin token"})

    parts = tuple(p for p in path[len("/admin/api/") :].split("/") if p)
    fn, error = _match(method, parts)
    if fn is None:
        return _json(
            error, {"error": "not found" if error == 404 else "method not allowed"}
        )

    try:
        status, body = fn(event, parts)
    except store.StoreError as exc:
        logger.info("%s %s -> %s: %s", method, path, exc.status, exc)
        return _json(exc.status, {"error": str(exc)})
    except Exception:
        logger.exception("%s %s failed", method, path)
        return _json(500, {"error": "internal error"})
    logger.info("%s %s -> %s", method, path, status)
    return _json(status, body)
