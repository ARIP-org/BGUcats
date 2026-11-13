"""Addresses for photos in the media bucket (spec §6.2).

Any location is built from a photo's id without a lookup (spec §6.1):
`derived/{photoId}/thumb-256.webp` and `.../medium-1024.webp`.
"""

# Long enough to look through a screen without a photo going blank, short
# enough that a copied address is useless by the time it leaves a chat.
PRESIGNED_URL_TTL_SECONDS = 3600
# Every object here is write-once (raw/ is never mutated, derived/ is
# rebuilt only under the same bytes), so the browser may keep it. The app
# reuses one address per photo until it expires (web/app.js,
# stablePhotoUrl); without this header it would still ask S3 each time.
PHOTO_CACHE_CONTROL = "private, max-age=86400, immutable"


def presign(s3, bucket, key):
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseCacheControl": PHOTO_CACHE_CONTROL,
        },
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def photo_urls(s3, bucket, photo_id):
    """The two derivatives a screen shows: {"thumb": ..., "medium": ...}."""
    return {
        "thumb": presign(s3, bucket, f"derived/{photo_id}/thumb-256.webp"),
        "medium": presign(s3, bucket, f"derived/{photo_id}/medium-1024.webp"),
    }


# ------------------------------------------------------------ profile photos

# `avatars/{userId}/{avatarId}.jpg` (docs/app-plan/02-architecture.md,
# "Storage"). The phone scales and re-encodes the picture before it uploads,
# which also drops whatever the camera wrote into it.
AVATAR_TYPE = "image/jpeg"
AVATAR_MAX_BYTES = 200_000
# How much of the file is read to check it: the segments that can carry
# metadata come before the picture itself.
AVATAR_HEAD_BYTES = 65536

# JPEG segments that describe the person or the place, not the picture:
# APP1 is EXIF (the camera, the time, the GPS position) and XMP; APP13 is
# IPTC. A re-encoded picture has neither.
_METADATA_MARKERS = {0xE1: "EXIF or XMP", 0xED: "IPTC"}


def avatar_key(user_id, avatar_id):
    return f"avatars/{user_id}/{avatar_id}.jpg"


def jpeg_problem(head):
    """What is wrong with a file that should be a re-encoded JPEG, from its
    first bytes, or None. It walks the segments before the picture data and
    refuses one that carries metadata: a profile photo must not say where,
    when or with what it was taken (spec §7, the same rule as derivatives).
    """
    if head[:3] != b"\xff\xd8\xff":
        return "not a JPEG picture"
    at = 2
    while at + 4 <= len(head):
        if head[at] != 0xFF:
            return "not a JPEG picture"
        marker = head[at + 1]
        if marker == 0xFF:  # padding between segments
            at += 1
            continue
        if marker == 0xDA:  # the picture's own data starts: nothing after counts
            return None
        if marker in _METADATA_MARKERS:
            return f"it still carries {_METADATA_MARKERS[marker]} data"
        at += 2 + int.from_bytes(head[at + 2 : at + 4], "big")
    return None
