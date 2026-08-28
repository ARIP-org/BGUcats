"""S3 raw/ upload -> hashes, derivatives, EXIF. Spec Figure 2 / §5.

Everything expensive happens here, off the Telegram request path. Fired by
an S3 ObjectCreated event, so it is retried by S3 on failure and may be
delivered more than once — every step is written to be idempotent.
"""

import hashlib
import io
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from PIL import Image, ImageOps

from process.phash import hamming_distance, phash

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]

# Longest edge, per spec §5. A wall of 50 phone originals is >100MB and
# will never load; these are what the labeling tool and later the app use.
DERIVATIVES = (("thumb-256.webp", 256), ("medium-1024.webp", 1024))

# Two photos within this many bits are near-duplicates. Flagged, never
# dropped — a burst of similar frames is legitimate data (spec §5).
NEAR_DUPLICATE_MAX_DISTANCE = 5

# ~110m at 3 decimal places. Spec §5 wants location useful for territory
# mapping but never precise enough to reveal where a contributor stood.
COORDINATE_DECIMALS = 3

# Anything else under raw/ is video. Hashed and deduped like a photo, but
# gets none of the Pillow pipeline — no frames extracted, no thumbnails, no
# EXIF. Turning a clip into browsable stills is a later problem.
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


def handler(event, context):
    for record in event.get("Records", []):
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        try:
            _process_object(key)
        except Exception:
            # Log and continue: one poison object must not block the rest
            # of the batch, and the photo record simply keeps its
            # pre-processing state rather than being marked misleadingly.
            logger.exception("failed to process %s", key)
    return {"ok": True}


def _process_object(key):
    session_id, photo_id, ext = _parse_raw_key(key)
    if ext.lower() in IMAGE_EXTENSIONS:
        _process_image(key, session_id, photo_id)
    else:
        _process_video(key, session_id, photo_id)


def _process_video(key, session_id, photo_id):
    logger.info("processing video=%s session=%s", photo_id, session_id)

    raw = s3.get_object(Bucket=MEDIA_BUCKET, Key=key)["Body"].read()
    sha256 = hashlib.sha256(raw).hexdigest()
    duplicate_of = _claim_sha256(sha256, photo_id)
    _record_video_results(photo_id=photo_id, sha256=sha256, duplicate_of=duplicate_of)


def _process_image(key, session_id, photo_id):
    logger.info("processing photo=%s session=%s", photo_id, session_id)

    raw = s3.get_object(Bucket=MEDIA_BUCKET, Key=key)["Body"].read()
    sha256 = hashlib.sha256(raw).hexdigest()

    image = Image.open(io.BytesIO(raw))
    captured_at, coarse_lat, coarse_lon = _extract_exif(image)

    # Bake orientation into the pixels before stripping EXIF, or every
    # portrait phone photo renders sideways once the metadata is gone.
    upright = ImageOps.exif_transpose(image)
    width, height = upright.size
    image_phash = phash(upright)

    for name, longest_edge in DERIVATIVES:
        _write_derivative(photo_id, upright, name, longest_edge)

    duplicate_of = _claim_sha256(sha256, photo_id)
    near_duplicate_of = _find_near_duplicate(session_id, photo_id, image_phash)

    _record_results(
        photo_id=photo_id,
        sha256=sha256,
        image_phash=image_phash,
        width=width,
        height=height,
        captured_at=captured_at,
        coarse_lat=coarse_lat,
        coarse_lon=coarse_lon,
        duplicate_of=duplicate_of,
        near_duplicate_of=near_duplicate_of,
    )


def _parse_raw_key(key):
    """raw/{sessionId}/{photoId}.{ext} — the ID-as-join-key format, spec §6.2."""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "raw":
        raise ValueError(f"not a raw object key: {key}")
    filename = parts[2]
    photo_id, _, ext = filename.rpartition(".")
    if not photo_id:
        raise ValueError(f"no photo id in key: {key}")
    return parts[1], photo_id, ext


def _write_derivative(photo_id, upright, name, longest_edge):
    derivative = upright.copy()
    derivative.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    if derivative.mode not in ("RGB", "RGBA"):
        derivative = derivative.convert("RGB")

    buffer = io.BytesIO()
    # A fresh save of pixel data carries no EXIF: derivatives are
    # metadata-free by construction, not by scrubbing (spec §5).
    derivative.save(buffer, format="WEBP", quality=85)

    s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=f"derived/{photo_id}/{name}",
        Body=buffer.getvalue(),
        ContentType="image/webp",
    )


def _claim_sha256(sha256, photo_id):
    """Return the photoId that owns these exact bytes, if it isn't us.

    People resubmit the same photo and social reposts collide (spec §5).
    A conditional write makes the first photo to arrive the owner; anyone
    later with identical bytes is an exact duplicate. Reprocessing the
    same photo re-reads its own claim and is not a duplicate of itself.
    """
    try:
        table.put_item(
            Item={"PK": f"SHA#{sha256}", "SK": "META", "photoId": photo_id},
            ConditionExpression="attribute_not_exists(PK)",
        )
        return None
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        owner = table.get_item(Key={"PK": f"SHA#{sha256}", "SK": "META"}).get("Item")
        owner_id = owner.get("photoId") if owner else None
        return owner_id if owner_id != photo_id else None


def _find_near_duplicate(session_id, photo_id, image_phash):
    """Closest near-duplicate among the other photos of this session.

    Bursts happen within an encounter, so comparing inside the session
    catches the real cases while keeping this bounded to ~20-30 items —
    no table scan, no vector index. Cross-session similarity is the
    labeling tool's job, not ingest's.
    """
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"SESSION#{session_id}"),
    )

    best_id, best_distance = None, None
    for item in response.get("Items", []):
        other_phash = item.get("phash")
        if item.get("photoId") == photo_id or not other_phash:
            continue
        distance = hamming_distance(image_phash, other_phash)
        if distance <= NEAR_DUPLICATE_MAX_DISTANCE and (
            best_distance is None or distance < best_distance
        ):
            best_id, best_distance = item["photoId"], distance
    return best_id


def _extract_exif(image):
    """Capture time and coarse GPS, read before any stripping happens.

    Malformed EXIF must never cost us the photo — the pixels and
    derivatives are the valuable part — so this degrades to "no metadata"
    rather than failing. It logs loudly because absent EXIF returns an
    empty mapping rather than raising; reaching the handler means the
    bytes were genuinely corrupt, which is worth seeing.
    """
    try:
        exif = image.getexif()
        if not exif:
            return None, None, None
        return (_exif_timestamp(exif), *_exif_coarse_location(exif))
    except Exception:
        logger.exception("unreadable EXIF; continuing without it")
        return None, None, None


def _exif_timestamp(exif):
    """Prefer DateTimeOriginal (when the shutter fired) over DateTime.

    DateTimeOriginal lives in the Exif sub-IFD, which getexif() does not
    merge into the top level — it has to be fetched explicitly. DateTime
    (IFD0) is the fallback and can be a later edit timestamp.

    EXIF timestamps are camera-local wall clock with no zone, so this
    returns UTC (trailing Z) only when the camera also recorded an offset.
    Otherwise it returns a naive ISO string — stamping an unknown-zone
    local time as UTC would bake in an error of up to 14 hours, and
    "when are these cats active" is exactly the sort of question this
    field will later be asked.
    """
    sub_ifd = exif.get_ifd(0x8769)

    raw = sub_ifd.get(36867) or exif.get(36867) or exif.get(306)
    if not raw:
        return None
    try:
        # EXIF carries no zone by design; DTZ007 does not apply.
        taken = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007
    except ValueError:
        return None

    offset = sub_ifd.get(0x9011) or sub_ifd.get(0x9010)  # OffsetTimeOriginal
    if offset:
        try:
            aware = taken.replace(tzinfo=_parse_utc_offset(str(offset)))
            return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        except ValueError:
            pass

    return taken.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _parse_utc_offset(offset):
    """'+03:00' -> a fixed-offset tzinfo."""
    hours, _, minutes = offset.strip().partition(":")
    delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
    if hours.startswith("-"):
        delta = -timedelta(hours=abs(int(hours)), minutes=int(minutes or 0))
    return timezone(delta)


def _exif_coarse_location(exif):
    gps = exif.get_ifd(0x8825)
    if not gps:
        return None, None

    lat = _to_degrees(gps.get(2), gps.get(1))
    lon = _to_degrees(gps.get(4), gps.get(3))
    if lat is None or lon is None:
        return None, None
    return round(lat, COORDINATE_DECIMALS), round(lon, COORDINATE_DECIMALS)


def _to_degrees(dms, ref):
    """EXIF stores coordinates as (degrees, minutes, seconds) plus a hemisphere."""
    if not dms or len(dms) != 3:
        return None
    try:
        degrees = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if ref in ("S", "W", b"S", b"W"):
        degrees = -degrees
    return degrees


def _record_results(
    photo_id,
    sha256,
    image_phash,
    width,
    height,
    captured_at,
    coarse_lat,
    coarse_lon,
    duplicate_of,
    near_duplicate_of,
):
    expressions = [
        "sha256 = :sha",
        "phash = :phash",
        "width = :w",
        "height = :h",
        "mediaType = :mt",
        "processedAt = :now",
    ]
    values = {
        ":sha": sha256,
        ":phash": image_phash,
        ":w": width,
        ":h": height,
        ":mt": "photo",
        ":now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }

    if captured_at:
        expressions.append("capturedAt = :captured")
        values[":captured"] = captured_at
    if coarse_lat is not None and coarse_lon is not None:
        expressions += ["coarseLat = :lat", "coarseLon = :lon"]
        values[":lat"] = Decimal(str(coarse_lat))
        values[":lon"] = Decimal(str(coarse_lon))
    if near_duplicate_of:
        expressions.append("nearDuplicateOf = :near")
        values[":near"] = near_duplicate_of

    names = {}
    if duplicate_of:
        # Byte-identical resubmission: mark it and keep it out of the
        # labeling queue. Near-duplicates deliberately do NOT do this.
        expressions += ["#status = :status", "duplicateOf = :dup", "GSI2PK = :g2pk"]
        values[":status"] = "duplicate"
        values[":dup"] = duplicate_of
        values[":g2pk"] = "STATUS#duplicate"
        names["#status"] = "status"

    kwargs = {
        "Key": {"PK": f"PHOTO#{photo_id}", "SK": "META"},
        "UpdateExpression": "SET " + ", ".join(expressions),
        "ExpressionAttributeValues": values,
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names

    table.update_item(**kwargs)


def _record_video_results(photo_id, sha256, duplicate_of):
    expressions = ["sha256 = :sha", "mediaType = :mt", "processedAt = :now"]
    values = {
        ":sha": sha256,
        ":mt": "video",
        ":now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }

    names = {}
    if duplicate_of:
        expressions += ["#status = :status", "duplicateOf = :dup", "GSI2PK = :g2pk"]
        values[":status"] = "duplicate"
        values[":dup"] = duplicate_of
        values[":g2pk"] = "STATUS#duplicate"
        names["#status"] = "status"

    kwargs = {
        "Key": {"PK": f"PHOTO#{photo_id}", "SK": "META"},
        "UpdateExpression": "SET " + ", ".join(expressions),
        "ExpressionAttributeValues": values,
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names

    table.update_item(**kwargs)
