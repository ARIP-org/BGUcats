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
