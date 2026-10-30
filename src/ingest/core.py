"""The platform-neutral half of ingestion: sessions, photo records, location.

The chat adapter, handler.py (Telegram), parses its webhook format and
talks back in its own API, but everything that touches storage goes through
here, so the guarantees in spec §10 (write order, idempotency on a
per-message key, sessions as identity clusters) are written once, apart from
any one platform. A WhatsApp adapter shared it until it was removed on
2026-10-30; its sessions and photos stay in the table (channel "whatsapp").

No image processing (spec §5, §10): fetch, store, record. The S3 event
drives the process Lambda.
"""

import hashlib
import logging
import math
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from ulid import ULID

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]

SESSION_IDLE_WINDOW_SECONDS = 10 * 60
# An explicitly-opened session ignores the idle window — you can shoot one
# cat for half an hour — but not forever: a session left open and forgotten
# would otherwise swallow the next cat photographed days later, silently
# corrupting an identity cluster.
EXPLICIT_SESSION_MAX_SECONDS = 2 * 60 * 60
RATE_LIMIT_PER_MINUTE = 30
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# A location pins the submitter's most recent session. Past this age a stray
# pin is more likely about some other cat than the last one photographed.
LOCATION_WINDOW_SECONDS = 24 * 60 * 60
# Same rounding as EXIF GPS in the process Lambda: ~100 m, a cat's territory
# rather than the spot the contributor was standing on.
COORDINATE_DECIMALS = 3

# Where someone came from, as a tracked link carries it: the landing page's
# ?src= and the bot's /start payload are the same slug, so a visitor and the
# contributor they turn into are counted under one name on the stats page.
# Fits inside Telegram's start-parameter alphabet (A-Z a-z 0-9 _ -).
REFERRAL_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# Recorded when someone starts the bot without a tracked link — found it by
# name, or came from before tracking existed. A profile with no referral at
# all reads the same way on the stats page.
NO_REFERRAL = "none"

# Magic-byte signatures for the image formats the chat apps actually send.
# Content type is validated from bytes, never from a filename (spec §8.5).
IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}

# Videos arrive as MP4 (an ISO base media file — a size word, then "ftyp"
# at offset 4, not offset 0 like the image signatures above). WebM is
# included for the rare client that sends it as a document-style upload.
MP4_FTYP_OFFSET = 4
WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def now_epoch():
    return int(time.time())


def epoch_to_iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def submitter_hash(salt, user_key):
    """Salted SHA-256 of a platform user ID; the raw ID is never stored.

    Telegram passes its numeric user ID as-is. The removed WhatsApp bot
    passed "wa:<number>", so its submitters' hashes never collide with
    Telegram's. App users are hashed apart, as "app:<email>" (admin
    handler).
    """
    return hashlib.sha256((salt + user_key).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Media: the spec §10 write order
# --------------------------------------------------------------------------


def ingest_media(
    *,
    idempotency_key,
    submitter_hash,
    media_group_id,
    channel,
    captured_at,
    fetch,
    width=None,
    height=None,
    duration_seconds=None,
):
    """Record one photo or video. Returns its session ID, or None if the
    download failed.

    `fetch()` returns (bytes, ext, content_type, media_kind) and raises
    ValueError or OSError on failure — the adapter supplies it, since each
    platform hands out files its own way. OSError covers
    URLError and also a read that times out mid-response, which urllib
    raises as a bare TimeoutError: five photos were lost that way on
    2026-08-24, when Telegram's getFile stalled past the 8-second timeout.

    Write order (spec §10): DynamoDB record as `pending`, then S3, then flip
    to `unlabeled`. A failed download leaves the record `pending`, never
    falsely marked ready, and the caller tells the submitter to send it
    again — Telegram does not redeliver an acknowledged update.
    """
    photo_id, session_id = resolve_photo_and_session(
        idempotency_key, submitter_hash, media_group_id, channel=channel
    )
    created_at = now_iso()

    _write_pending_photo(
        photo_id=photo_id,
        session_id=session_id,
        submitter_hash=submitter_hash,
        channel=channel,
        captured_at=captured_at,
        created_at=created_at,
    )

    try:
        media_bytes, ext, content_type, media_kind = fetch()
    except (ValueError, OSError) as exc:
        logger.warning("download failed for photo=%s: %s", photo_id, exc)
        return None

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
        width=width,
        height=height,
        media_type=media_kind,
        duration_seconds=duration_seconds,
    )
    _bump_session(session_id)
    _bump_submitter_pointer(submitter_hash, session_id, media_group_id)
    return session_id


def read_capped(url, headers=None, timeout=15):
    """Download at most MAX_FILE_SIZE_BYTES, and refuse anything larger."""
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        data = resp.read(MAX_FILE_SIZE_BYTES + 1)
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise ValueError("downloaded file exceeds size cap")
    return data


def sniffed_or_raise(data):
    """(bytes, ext, content_type, media_kind) — the shape `fetch()` returns."""
    sniffed = sniff_media_type(data)
    if sniffed is None:
        raise ValueError("downloaded bytes are not a recognized image or video format")
    content_type, ext, media_kind = sniffed
    return data, ext, content_type, media_kind


def sniff_image_type(data):
    for signature, info in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return info
    return None


def sniff_video_type(data):
    if len(data) >= 12 and data[MP4_FTYP_OFFSET : MP4_FTYP_OFFSET + 4] == b"ftyp":
        return "video/mp4", "mp4"
    if data.startswith(WEBM_SIGNATURE):
        return "video/webm", "webm"
    return None


def sniff_media_type(data):
    image = sniff_image_type(data)
    if image:
        return (*image, "photo")
    video = sniff_video_type(data)
    if video:
        return (*video, "video")
    return None


def _write_pending_photo(
    photo_id, session_id, submitter_hash, channel, captured_at, created_at
):
    # DynamoDB record first, status=pending — spec §10 write order. Only
    # after the S3 write succeeds does _mark_photo_unlabeled flip it. The
    # record is on the status index from the start (STATUS#pending), so one
    # whose object never landed shows up on the admin Stats page instead of
    # being invisible to every query.
    table.put_item(
        Item={
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "sessionId": session_id,
            "source": "bot",
            "channel": channel,
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
            "GSI2PK": "STATUS#pending",
            "GSI2SK": created_at,
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


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def resolve_photo_and_session(idempotency_key, submitter_hash, media_group_id, channel):
    """Idempotent on the platform's message key: a retried webhook delivery
    reuses the same photoId/sessionId instead of creating a duplicate."""
    existing = table.get_item(Key={"PK": idempotency_key, "SK": "META"}).get("Item")
    if existing:
        return existing["photoId"], existing["sessionId"]

    session_id = resolve_or_open_session(
        submitter_hash, media_group_id, channel=channel
    )
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


def resolve_or_open_session(submitter_hash, media_group_id, channel):
    pointer = _active_pointer(submitter_hash)
    if pointer and _pointer_still_open(pointer, media_group_id):
        return pointer["sessionId"]

    return _open_session(
        submitter_hash,
        media_group_id,
        explicit=False,
        channel=channel,
        replacing=pointer["sessionId"] if pointer else None,
    )


def open_explicit_session(submitter_hash, channel):
    """ "New cat": close whatever is open and start a session that ignores
    the idle window until Done or the safety cap."""
    close_session(submitter_hash)
    return _open_session(submitter_hash, None, explicit=True, channel=channel)


def close_active_session(submitter_hash):
    """ "Done". Returns (photo_count, has_location), or None if nothing was
    open."""
    pointer = _active_pointer(submitter_hash)
    if not pointer:
        return None

    session = table.get_item(
        Key={"PK": f"SESSION#{pointer['sessionId']}", "SK": "META"}
    ).get("Item")
    count = int(session.get("photoCount", 0)) if session else 0
    has_location = bool(session) and session.get("coarseLat") is not None

    close_session(submitter_hash)
    return count, has_location


def close_session(submitter_hash):
    table.delete_item(Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"})


def _active_pointer(submitter_hash):
    return table.get_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"}
    ).get("Item")


def _pointer_still_open(pointer, media_group_id):
    # An album always belongs to one encounter, whatever the clock says.
    if media_group_id and media_group_id == pointer.get("mediaGroupId"):
        return True

    idle = now_epoch() - int(pointer.get("lastPhotoAtEpoch", 0))
    if pointer.get("explicit"):
        return idle < EXPLICIT_SESSION_MAX_SECONDS
    return idle < SESSION_IDLE_WINDOW_SECONDS


def _open_session(submitter_hash, media_group_id, explicit, channel, replacing=None):
    """Create a Session and point the submitter at it.

    An explicit open ("New cat") always wins. An implicit one only replaces
    the pointer it actually read (`replacing`, or none at all): a burst of
    photos sent one at a time arrives as concurrent invocations with no
    album ID to hold them together, and without that condition each would open its
    own session, splitting one encounter into several. The loser joins the
    winner's session and deletes its own still-empty one.
    """
    for _ in range(3):
        session_id = str(ULID())
        now = now_epoch()
        now_iso_ = now_iso()

        table.put_item(
            Item={
                "PK": f"SESSION#{session_id}",
                "SK": "META",
                "sessionId": session_id,
                "submitterHash": submitter_hash,
                "source": "bot",
                "channel": channel,
                "startedAt": now_iso_,
                "lastPhotoAt": now_iso_,
                "photoCount": 0,
                "catId": None,
                "notes": None,
                "explicit": explicit,
            }
        )

        pointer = {
            "PK": f"SUBMITTER#{submitter_hash}",
            "SK": "ACTIVE_SESSION",
            "sessionId": session_id,
            "mediaGroupId": media_group_id,
            "lastPhotoAtEpoch": now,
            "explicit": explicit,
        }
        if explicit:
            table.put_item(Item=pointer)
        else:
            condition = {"ConditionExpression": "attribute_not_exists(PK)"}
            if replacing is not None:
                condition = {
                    "ConditionExpression": "sessionId = :replacing",
                    "ExpressionAttributeValues": {":replacing": replacing},
                }
            try:
                table.put_item(Item=pointer, **condition)
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                table.delete_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"})
                winner = _active_pointer(submitter_hash)
                if winner:
                    return winner["sessionId"]
                # The winner was closed in between (Done); try again from
                # an empty slate.
                replacing = None
                continue

        _touch_last_session(submitter_hash, session_id)
        record_contributor(submitter_hash, channel)
        return session_id

    raise RuntimeError("could not open a session after repeated contention")


def _touch_last_session(submitter_hash, session_id):
    """Remember the session a location should pin.

    Separate from ACTIVE_SESSION because Done deletes that pointer, and
    straight after Done is exactly when people send the location.
    """
    table.put_item(
        Item={
            "PK": f"SUBMITTER#{submitter_hash}",
            "SK": "LAST_SESSION",
            "sessionId": session_id,
            "atEpoch": now_epoch(),
        }
    )


def _bump_session(session_id):
    table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET lastPhotoAt = :now ADD photoCount :one",
        ExpressionAttributeValues={":now": now_iso(), ":one": 1},
    )


def _bump_submitter_pointer(submitter_hash, session_id, media_group_id):
    table.update_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET sessionId = :sid, lastPhotoAtEpoch = :now, mediaGroupId = :mg",
        ExpressionAttributeValues={
            ":sid": session_id,
            ":now": now_epoch(),
            ":mg": media_group_id,
        },
    )
    _touch_last_session(submitter_hash, session_id)


# --------------------------------------------------------------------------
# Contributor profiles (stats page)
# --------------------------------------------------------------------------


def clean_referral(raw):
    """A well-formed referral slug, or None. The /start payload is whatever
    the link said, so it is user-controlled input like everything else."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    return value if REFERRAL_PATTERN.fullmatch(value) else None


def record_contributor(submitter_hash, channel, referral=None):
    """Note when a submitter first showed up, on which channel, and which
    tracked link brought them.

    First touch wins: every field is if_not_exists, so a later visit through
    some other link never rewrites where someone originally came from. That
    also makes it idempotent — called on every /start and every new session,
    it writes the profile once and leaves it alone after.

    Listed through GSI2 like cats and admins, so the stats page reads every
    profile with one query instead of a scan.
    """
    expression = (
        "SET submitterHash = :hash, firstSeenAt = if_not_exists(firstSeenAt, :now), "
        "#channel = if_not_exists(#channel, :channel), "
        "GSI2PK = :entity, GSI2SK = if_not_exists(GSI2SK, :now)"
    )
    names = {"#channel": "channel"}
    values = {
        ":hash": submitter_hash,
        ":now": now_iso(),
        ":channel": channel,
        ":entity": "ENTITY#SUBMITTER",
    }
    if referral:
        expression += ", #referral = if_not_exists(#referral, :referral)"
        names["#referral"] = "referral"
        values[":referral"] = referral

    table.update_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "PROFILE"},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


# --------------------------------------------------------------------------
# Replies, rate limiting, location
# --------------------------------------------------------------------------


def should_reply(media_group_id):
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
                "expiresAt": now_epoch() + 3600,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def check_rate_limit(submitter_hash):
    minute_bucket = now_epoch() // 60
    pk = f"RATE#{submitter_hash}#{minute_bucket}"
    try:
        table.update_item(
            Key={"PK": pk, "SK": "META"},
            UpdateExpression="SET expiresAt = if_not_exists(expiresAt, :exp) ADD #cnt :one",
            ConditionExpression="attribute_not_exists(#cnt) OR #cnt < :limit",
            ExpressionAttributeNames={"#cnt": "count"},
            ExpressionAttributeValues={
                ":one": 1,
                ":exp": now_epoch() + 180,
                ":limit": RATE_LIMIT_PER_MINUTE,
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def coarse_location(lat, lon):
    """Validated and rounded (lat, lon), or None.

    Whatever the channel, coordinates are user-controlled input: trust only
    two finite, in-range numbers, and round before anything is stored.
    """
    if not (_is_coordinate(lat, 90) and _is_coordinate(lon, 180)):
        return None
    return round(lat, COORDINATE_DECIMALS), round(lon, COORDINATE_DECIMALS)


def _is_coordinate(value, limit):
    # bool is an int subclass, and json.loads accepts NaN/Infinity.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and -limit <= value <= limit
    )


def set_session_location(submitter_hash, lat, lon, source):
    """Pin the submitter's most recent session. Last pin wins, so a
    mis-tap is fixed by sending another one."""
    pointer = table.get_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "LAST_SESSION"}
    ).get("Item")
    if not pointer:
        return False
    if now_epoch() - int(pointer.get("atEpoch", 0)) > LOCATION_WINDOW_SECONDS:
        return False

    try:
        table.update_item(
            Key={"PK": f"SESSION#{pointer['sessionId']}", "SK": "META"},
            UpdateExpression=(
                "SET coarseLat = :lat, coarseLon = :lon, "
                "locationSource = :src, locatedAt = :now"
            ),
            # Never conjure a half-formed Session out of a stale pointer.
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeValues={
                ":lat": Decimal(str(lat)),
                ":lon": Decimal(str(lon)),
                ":src": source,
                ":now": now_iso(),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def claim_location_prompt(session_id):
    """True exactly once per session, and only while it has no location.

    The first photo's reply asks; the rest of the burst stays quiet. A
    conditional write rather than a read-then-write, for the same reason
    as `should_reply`: burst photos arrive as concurrent invocations.
    """
    try:
        table.update_item(
            Key={"PK": f"SESSION#{session_id}", "SK": "META"},
            UpdateExpression="SET locationAskedAt = :now",
            ConditionExpression=(
                "attribute_exists(PK) AND attribute_not_exists(locationAskedAt) "
                "AND attribute_not_exists(coarseLat)"
            ),
            ExpressionAttributeValues={":now": now_iso()},
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
