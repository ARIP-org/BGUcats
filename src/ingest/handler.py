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
# An explicitly-opened session ignores the idle window — you can shoot one
# cat for half an hour — but not forever: a session left open and forgotten
# would otherwise swallow the next cat photographed days later, silently
# corrupting an identity cluster.
EXPLICIT_SESSION_MAX_SECONDS = 2 * 60 * 60
RATE_LIMIT_PER_MINUTE = 30
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

NEW_SESSION_ACTION = "new_session"
CLOSE_SESSION_ACTION = "close_session"

BUTTON_NEW_CAT = "\U0001f43e New cat"
BUTTON_DONE = "✅ Done"

# A reply keyboard (docked under the message box, persistent across
# messages) rather than an inline one attached to a single message —
# pressing these sends their label as an ordinary text message, so the
# controls stay available while you shoot instead of scrolling away.
SESSION_KEYBOARD = {
    "keyboard": [[{"text": BUTTON_NEW_CAT}, {"text": BUTTON_DONE}]],
    "resize_keyboard": True,
    "is_persistent": True,
}

TEXT_ACTIONS = {
    BUTTON_NEW_CAT: NEW_SESSION_ACTION,
    BUTTON_DONE: CLOSE_SESSION_ACTION,
    "/newcat": NEW_SESSION_ACTION,
    "/done": CLOSE_SESSION_ACTION,
}

START_TEXT = (
    "Send me photos of a campus cat and I'll file them.\n\n"
    "Just sending photos works — they're grouped into one encounter "
    "automatically.\n\n"
    "Photographing one cat for a while? Tap *New cat* first and *Done* when "
    "you've finished, and I'll keep every shot in a single session no matter "
    "how long it takes."
)

# Magic-byte signatures for the image formats Telegram actually sends.
# Content type is validated from bytes, never from a filename (spec §8.5).
IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}

# Telegram transcodes ordinary videos and video notes to MP4 (an ISO base
# media file — a size word, then "ftyp" at offset 4, not offset 0 like the
# image signatures above). WebM is included for the rare client that sends
# it as a document-style upload.
MP4_FTYP_OFFSET = 4
WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"

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

    if body.get("callback_query"):
        return _handle_callback(body["callback_query"], secrets)

    message = body.get("message") or body.get("channel_post")
    if not message:
        return {"statusCode": 200, "body": "ok"}

    # Reply-keyboard presses arrive as ordinary text messages carrying the
    # button's label, so buttons and slash commands share one path.
    text = (message.get("text") or "").strip()
    if text:
        return _handle_text(message, text, secrets)

    media = _extract_media(message)
    if media is None:
        return {"statusCode": 200, "body": "ok"}

    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    media_group_id = message.get("media_group_id")
    date = message.get("date")

    submitter_hash = _submitter_hash(secrets, tg_user_id)

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

    try:
        media_bytes, ext, content_type, media_kind = _download_telegram_file(
            secrets["bot_token"], media["file_id"]
        )
    except (ValueError, urllib.error.URLError) as exc:
        logger.warning("download failed for photo=%s: %s", photo_id, exc)
        return {"statusCode": 200, "body": "ok"}

    s3_key = f"raw/{session_id}/{photo_id}.{ext}"
    s3.put_object(
        Bucket=MEDIA_BUCKET, Key=s3_key, Body=media_bytes, ContentType=content_type
    )

    _mark_photo_unlabeled(
        photo_id=photo_id,
        session_id=session_id,
        created_at=created_at,
        s3_key=s3_key,
        content_type=content_type,
        width=media.get("width"),
        height=media.get("height"),
        media_type=media_kind,
        duration_seconds=media.get("duration"),
    )
    _bump_session(session_id)
    _bump_submitter_pointer(submitter_hash, session_id, media_group_id)

    # One reply per album, not per photo: each photo in a media group is a
    # separate concurrent invocation, and five "Got it!"s for one album is
    # noise. No count here — none of these invocations knows how many
    # siblings it has. "Done" is where a count belongs.
    if _should_reply(media_group_id):
        _reply(secrets["bot_token"], chat_id, "Got it! \U0001f431")

    return {"statusCode": 200, "body": "ok"}


def _extract_media(message):
    """Pick the file to fetch: the largest photo size, a video, or a video
    note (Telegram's circular selfie clips, which report a single `length`
    instead of width/height).

    What kind of file it actually is gets settled by magic bytes in
    `_download_telegram_file`, not by which of these fields it arrived
    in — spec §8.5 applies to video the same as to photos.
    """
    if message.get("photo"):
        return max(
            message["photo"],
            key=lambda p: p.get("file_size", 0) or p["width"] * p["height"],
        )
    if message.get("video"):
        return message["video"]
    if message.get("video_note"):
        note = message["video_note"]
        return {**note, "width": note.get("length"), "height": note.get("length")}
    return None


def _submitter_hash(secrets, tg_user_id):
    return hashlib.sha256(
        (secrets["salt"] + str(tg_user_id)).encode("utf-8")
    ).hexdigest()


def _handle_callback(callback_query, secrets):
    """Serves the inline buttons from before the switch to a reply keyboard.

    Those messages are still in people's chat history with live buttons;
    dropping this would leave them spinning until they time out.
    """
    data = callback_query.get("data")
    chat_id = callback_query["message"]["chat"]["id"]
    tg_user_id = callback_query.get("from", {}).get("id", chat_id)
    submitter_hash = _submitter_hash(secrets, tg_user_id)

    if data == NEW_SESSION_ACTION:
        text = _start_new_session(submitter_hash)
    elif data == CLOSE_SESSION_ACTION:
        text = _finish_session(submitter_hash)
    else:
        text = None

    # Required, or the client shows a spinner on the button until it times
    # out — regardless of whether we recognized the action.
    _answer_callback(secrets["bot_token"], callback_query["id"])

    if text:
        _reply(secrets["bot_token"], chat_id, text, keyboard=SESSION_KEYBOARD)

    return {"statusCode": 200, "body": "ok"}


def _handle_text(message, text, secrets):
    chat_id = message["chat"]["id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    submitter_hash = _submitter_hash(secrets, tg_user_id)

    # "/done@BguCatsBot extra words" -> "/done"; button labels match as-is.
    key = text.split()[0].split("@")[0].lower() if text.startswith("/") else text
    action = TEXT_ACTIONS.get(key)

    if action == NEW_SESSION_ACTION:
        reply = _start_new_session(submitter_hash)
    elif action == CLOSE_SESSION_ACTION:
        reply = _finish_session(submitter_hash)
    elif key == "/start":
        reply = START_TEXT
    else:
        return {"statusCode": 200, "body": "ok"}

    _reply(secrets["bot_token"], chat_id, reply, keyboard=SESSION_KEYBOARD)
    return {"statusCode": 200, "body": "ok"}


def _start_new_session(submitter_hash):
    _close_session(submitter_hash)
    _open_session(submitter_hash, media_group_id=None, explicit=True)
    return "New session started \U0001f43e Send photos of this one cat, then tap Done."


def _finish_session(submitter_hash):
    pointer = table.get_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"}
    ).get("Item")

    if not pointer:
        return "No session open. Send photos, or tap New cat to start one."

    session = table.get_item(
        Key={"PK": f"SESSION#{pointer['sessionId']}", "SK": "META"}
    ).get("Item")
    count = int(session.get("photoCount", 0)) if session else 0

    _close_session(submitter_hash)

    if count == 0:
        return "Session closed — no photos in it."
    return f"Session closed with {count} photo{'s' if count != 1 else ''}. Thanks!"


def _close_session(submitter_hash):
    table.delete_item(Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"})


def _should_reply(media_group_id):
    """True for a standalone photo, or for exactly one photo per album.

    Each album photo is its own concurrent invocation; the conditional
    write picks a single winner to answer for the whole group.
    """
    if not media_group_id:
        return True
    try:
        table.put_item(
            Item={
                "PK": f"MGREPLY#{media_group_id}",
                "SK": "META",
                "expiresAt": _now_epoch() + 3600,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


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
    pointer = table.get_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"}
    ).get("Item")

    if pointer and _pointer_still_open(pointer, media_group_id):
        return pointer["sessionId"]

    return _open_session(submitter_hash, media_group_id, explicit=False)


def _pointer_still_open(pointer, media_group_id):
    # An album always belongs to one encounter, whatever the clock says.
    if media_group_id and media_group_id == pointer.get("mediaGroupId"):
        return True

    idle = _now_epoch() - int(pointer.get("lastPhotoAtEpoch", 0))
    if pointer.get("explicit"):
        return idle < EXPLICIT_SESSION_MAX_SECONDS
    return idle < SESSION_IDLE_WINDOW_SECONDS


def _open_session(submitter_hash, media_group_id, explicit):
    session_id = str(ULID())
    now = _now_epoch()
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
            "explicit": explicit,
        }
    )
    table.put_item(
        Item={
            "PK": f"SUBMITTER#{submitter_hash}",
            "SK": "ACTIVE_SESSION",
            "sessionId": session_id,
            "mediaGroupId": media_group_id,
            "lastPhotoAtEpoch": now,
            "explicit": explicit,
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
            "mediaType": None,
            "capturedAt": captured_at,
            "coarseLat": None,
            "coarseLon": None,
            "status": "pending",
            "catId": None,
            "createdAt": created_at,
        }
    )


def _mark_photo_unlabeled(
    photo_id,
    session_id,
    created_at,
    s3_key,
    content_type,
    width,
    height,
    media_type,
    duration_seconds=None,
):
    expression = (
        "SET s3RawKey = :key, mime = :mime, width = :w, height = :h, "
        "mediaType = :mt, #status = :status, GSI1PK = :g1pk, GSI1SK = :createdAt, "
        "GSI2PK = :g2pk, GSI2SK = :createdAt"
    )
    values = {
        ":key": s3_key,
        ":mime": content_type,
        ":w": width,
        ":h": height,
        ":mt": media_type,
        ":status": "unlabeled",
        ":g1pk": f"SESSION#{session_id}",
        ":g2pk": "STATUS#unlabeled",
        ":createdAt": created_at,
    }
    if duration_seconds is not None:
        expression += ", durationSeconds = :dur"
        values[":dur"] = duration_seconds

    table.update_item(
        Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
        UpdateExpression=expression,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=values,
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

    sniffed = _sniff_media_type(image_bytes)
    if sniffed is None:
        raise ValueError("downloaded bytes are not a recognized image or video format")

    content_type, ext, media_kind = sniffed
    return image_bytes, ext, content_type, media_kind


def _sniff_image_type(data):
    for signature, info in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return info
    return None


def _sniff_video_type(data):
    if len(data) >= 12 and data[MP4_FTYP_OFFSET : MP4_FTYP_OFFSET + 4] == b"ftyp":
        return "video/mp4", "mp4"
    if data.startswith(WEBM_SIGNATURE):
        return "video/webm", "webm"
    return None


def _sniff_media_type(data):
    image = _sniff_image_type(data)
    if image:
        return (*image, "photo")
    video = _sniff_video_type(data)
    if video:
        return (*video, "video")
    return None


def _reply(bot_token, chat_id, text, keyboard=None):
    body = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if keyboard:
        body["reply_markup"] = keyboard
    _telegram_post(bot_token, "sendMessage", body)


def _answer_callback(bot_token, callback_query_id):
    _telegram_post(
        bot_token, "answerCallbackQuery", {"callback_query_id": callback_query_id}
    )


def _telegram_post(bot_token, method, body):
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=8)
    except urllib.error.URLError as exc:
        logger.warning("telegram %s failed: %s", method, exc)
