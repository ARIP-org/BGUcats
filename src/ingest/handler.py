"""Telegram webhook -> S3 + DynamoDB. Fetch, store, record, respond.

No image processing happens here (see docs/cat-app-design-spec.pdf §5, §10)
— that's the S3-triggered process Lambda's job. This handler only:
validates the request came from Telegram, resolves which session a photo
belongs to, downloads the original bytes, writes them to S3, and records a
Photo/Session pair in DynamoDB.
"""

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from ulid import ULID

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
BOT_TOKEN_PARAM = os.environ["TELEGRAM_BOT_TOKEN_PARAM"]
WEBHOOK_SECRET_PARAM = os.environ["TELEGRAM_WEBHOOK_SECRET_PARAM"]
SALT_PARAM = os.environ["SUBMITTER_HASH_SALT_PARAM"]

SESSION_IDLE_WINDOW_SECONDS = 10 * 60
RATE_LIMIT_PER_MINUTE = 30
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# Magic-byte signatures for the image formats Telegram actually sends.
# Content type is validated from bytes, never from a filename (spec §8.5).
IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")
ssm = boto3.client("ssm")

_secrets_cache = None


def _get_secrets():
    global _secrets_cache
    if _secrets_cache is None:
        response = ssm.get_parameters(
            Names=[BOT_TOKEN_PARAM, WEBHOOK_SECRET_PARAM, SALT_PARAM],
            WithDecryption=True,
        )
        values = {p["Name"]: p["Value"] for p in response["Parameters"]}
        _secrets_cache = {
            "bot_token": values[BOT_TOKEN_PARAM],
            "webhook_secret": values[WEBHOOK_SECRET_PARAM],
            "salt": values[SALT_PARAM],
        }
    return _secrets_cache


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_epoch():
    return int(time.time())


def handler(event, context):
    secrets = _get_secrets()

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-telegram-bot-api-secret-token") != secrets["webhook_secret"]:
        return {"statusCode": 401, "body": "unauthorized"}

    try:
        return _process_update(event, secrets)
    except Exception:
        # Never let a bug turn into an infinite Telegram retry loop — log
        # and ack. A stuck DynamoDB record stays "pending" (never falsely
        # marked ready) per the write-order guarantee in spec §10.
        logger.exception("unhandled error processing update")
        return {"statusCode": 200, "body": "ok"}


def _process_update(event, secrets):
    body_raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        return {"statusCode": 200, "body": "ok"}

    message = body.get("message") or body.get("channel_post")
    if not message or not message.get("photo"):
        return {"statusCode": 200, "body": "ok"}

    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    media_group_id = message.get("media_group_id")
    date = message.get("date")

    submitter_hash = hashlib.sha256(
        (secrets["salt"] + str(tg_user_id)).encode("utf-8")
    ).hexdigest()

    if not _check_rate_limit(submitter_hash):
        logger.info("rate limited submitter=%s", submitter_hash)
        return {"statusCode": 200, "body": "ok"}

    photo_id, session_id = _resolve_photo_and_session(
        chat_id, message_id, submitter_hash, media_group_id
    )

    captured_at = (
        datetime.fromtimestamp(date, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if date
        else None
    )
    created_at = _now_iso()

    _write_pending_photo(
        photo_id=photo_id,
        session_id=session_id,
        submitter_hash=submitter_hash,
        captured_at=captured_at,
        created_at=created_at,
    )

    largest = max(
        message["photo"],
        key=lambda p: p.get("file_size", 0) or p["width"] * p["height"],
    )

    try:
        image_bytes, ext, content_type = _download_telegram_file(
            secrets["bot_token"], largest["file_id"]
        )
    except (ValueError, urllib.error.URLError) as exc:
        logger.warning("download failed for photo=%s: %s", photo_id, exc)
        return {"statusCode": 200, "body": "ok"}

    s3_key = f"raw/{session_id}/{photo_id}.{ext}"
    s3.put_object(
        Bucket=MEDIA_BUCKET, Key=s3_key, Body=image_bytes, ContentType=content_type
    )

    _mark_photo_unlabeled(
        photo_id=photo_id,
        session_id=session_id,
        created_at=created_at,
        s3_key=s3_key,
        content_type=content_type,
        width=largest["width"],
        height=largest["height"],
    )
    _bump_session(session_id)
    _bump_submitter_pointer(submitter_hash, session_id, media_group_id)

    _reply(secrets["bot_token"], chat_id, "Got it! \U0001f431")

    return {"statusCode": 200, "body": "ok"}


def _check_rate_limit(submitter_hash):
    minute_bucket = _now_epoch() // 60
    pk = f"RATE#{submitter_hash}#{minute_bucket}"
    try:
        table.update_item(
            Key={"PK": pk, "SK": "META"},
            UpdateExpression="SET expiresAt = if_not_exists(expiresAt, :exp) ADD #cnt :one",
            ConditionExpression="attribute_not_exists(#cnt) OR #cnt < :limit",
            ExpressionAttributeNames={"#cnt": "count"},
            ExpressionAttributeValues={
                ":one": 1,
                ":exp": _now_epoch() + 180,
                ":limit": RATE_LIMIT_PER_MINUTE,
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _resolve_photo_and_session(chat_id, message_id, submitter_hash, media_group_id):
    """Idempotent on (chat_id, message_id): a retried Telegram delivery
    reuses the same photoId/sessionId instead of creating a duplicate."""
    idempotency_key = f"TGMSG#{chat_id}_{message_id}"
    existing = table.get_item(Key={"PK": idempotency_key, "SK": "META"}).get("Item")
    if existing:
        return existing["photoId"], existing["sessionId"]

    session_id = _resolve_or_open_session(submitter_hash, media_group_id)
    photo_id = str(ULID())

    try:
        table.put_item(
            Item={
                "PK": idempotency_key,
                "SK": "META",
                "photoId": photo_id,
                "sessionId": session_id,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # Lost a race with a concurrent retry of the same update.
        existing = table.get_item(Key={"PK": idempotency_key, "SK": "META"}).get("Item")
        return existing["photoId"], existing["sessionId"]

    return photo_id, session_id


def _resolve_or_open_session(submitter_hash, media_group_id):
    pointer_key = {"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"}
    pointer = table.get_item(Key=pointer_key).get("Item")

    now = _now_epoch()
    if pointer:
        same_media_group = bool(media_group_id) and media_group_id == pointer.get(
            "mediaGroupId"
        )
        within_idle_window = (
            now - int(pointer.get("lastPhotoAtEpoch", 0))
        ) < SESSION_IDLE_WINDOW_SECONDS
        if same_media_group or within_idle_window:
            return pointer["sessionId"]

    session_id = str(ULID())
    now_iso = _now_iso()
    table.put_item(
        Item={
            "PK": f"SESSION#{session_id}",
            "SK": "META",
            "sessionId": session_id,
            "submitterHash": submitter_hash,
            "source": "bot",
            "startedAt": now_iso,
            "lastPhotoAt": now_iso,
            "photoCount": 0,
            "catId": None,
            "notes": None,
        }
    )
    table.put_item(
        Item={
            **pointer_key,
            "sessionId": session_id,
            "mediaGroupId": media_group_id,
            "lastPhotoAtEpoch": now,
        }
    )
    return session_id


def _write_pending_photo(photo_id, session_id, submitter_hash, captured_at, created_at):
    # DynamoDB record first, status=pending — spec §10 write order. Only
    # after the S3 write below succeeds does _mark_photo_unlabeled flip it.
    table.put_item(
        Item={
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "sessionId": session_id,
            "source": "bot",
            "submitterHash": submitter_hash,
            "s3RawKey": None,
            "sha256": None,
            "phash": None,
            "width": None,
            "height": None,
            "mime": None,
            "capturedAt": captured_at,
            "coarseLat": None,
            "coarseLon": None,
            "status": "pending",
            "catId": None,
            "createdAt": created_at,
        }
    )


def _mark_photo_unlabeled(
    photo_id, session_id, created_at, s3_key, content_type, width, height
):
    table.update_item(
        Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
        UpdateExpression=(
            "SET s3RawKey = :key, mime = :mime, width = :w, height = :h, "
            "#status = :status, GSI1PK = :g1pk, GSI1SK = :createdAt, "
            "GSI2PK = :g2pk, GSI2SK = :createdAt"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":key": s3_key,
            ":mime": content_type,
            ":w": width,
            ":h": height,
            ":status": "unlabeled",
            ":g1pk": f"SESSION#{session_id}",
            ":g2pk": "STATUS#unlabeled",
            ":createdAt": created_at,
        },
    )


def _bump_session(session_id):
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET lastPhotoAt = :now ADD photoCount :one",
        ExpressionAttributeValues={":now": _now_iso(), ":one": 1},
    )


def _bump_submitter_pointer(submitter_hash, session_id, media_group_id):
    table.update_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET sessionId = :sid, lastPhotoAtEpoch = :now, mediaGroupId = :mg",
        ExpressionAttributeValues={
            ":sid": session_id,
            ":now": _now_epoch(),
            ":mg": media_group_id,
        },
    )


def _download_telegram_file(bot_token, file_id):
    get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    with urllib.request.urlopen(get_file_url, timeout=8) as resp:
        file_info = json.loads(resp.read())

    if not file_info.get("ok"):
        raise ValueError(f"getFile failed: {file_info}")

    result = file_info["result"]
    file_size = result.get("file_size", 0)
    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"file too large: {file_size} bytes")

    file_path = result["file_path"]
    download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    with urllib.request.urlopen(download_url, timeout=15) as resp:
        image_bytes = resp.read(MAX_FILE_SIZE_BYTES + 1)

    if len(image_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError("downloaded file exceeds size cap")

    sniffed = _sniff_image_type(image_bytes)
    if sniffed is None:
        raise ValueError("downloaded bytes are not a recognized image format")

    content_type, ext = sniffed
    return image_bytes, ext, content_type


def _sniff_image_type(data):
    for signature, info in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return info
    return None


def _reply(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=8)
    except urllib.error.URLError as exc:
        logger.warning("failed to send reply: %s", exc)
