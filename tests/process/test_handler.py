import io
import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import piexif
import pytest
from moto import mock_aws
from PIL import Image

from process import handler

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["MEDIA_BUCKET"]

SESSION = "01SESSION0000000000000000"


@pytest.fixture
def aws(monkeypatch):
    """Moto-backed S3 + DynamoDB swapped in for the module globals.

    handler.py binds `table` and `s3` at import time, before moto is
    active, so they must be replaced rather than merely mocked.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        monkeypatch.setattr(handler, "table", table)
        monkeypatch.setattr(handler, "s3", s3)
        yield {"table": table, "s3": s3}


def _jpeg(size=(800, 600), colour=(120, 90, 60), exif_bytes=None):
    image = Image.new("RGB", size, colour)
    buffer = io.BytesIO()
    if exif_bytes:
        image.save(buffer, format="JPEG", exif=exif_bytes)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(aws, photo_id, body, session=SESSION):
    key = f"raw/{session}/{photo_id}.jpg"
    aws["s3"].put_object(Bucket=BUCKET, Key=key, Body=body)
    aws["table"].put_item(
        Item={
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "sessionId": session,
            "status": "unlabeled",
            "GSI1PK": f"SESSION#{session}",
            "GSI1SK": "2026-01-01T00:00:00.000000Z",
        }
    )
    return key


def _photo(aws, photo_id):
    return aws["table"].get_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"})["Item"]


def _objects(aws, prefix):
    listing = aws["s3"].list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in listing.get("Contents", [])]


# --- key parsing -------------------------------------------------------


def test_parses_the_join_key_format():
    assert handler._parse_raw_key("raw/SESSION1/PHOTO1.jpg") == (
        "SESSION1",
        "PHOTO1",
        "jpg",
    )


@pytest.mark.parametrize(
    "key", ["derived/PHOTO1/thumb-256.webp", "raw/PHOTO1.jpg", "raw/S/P/extra.jpg"]
)
def test_rejects_keys_that_are_not_raw_originals(key):
    with pytest.raises(ValueError):
        handler._parse_raw_key(key)


# --- the happy path ----------------------------------------------------


def test_writes_both_derivatives(aws):
    handler._process_object(_upload(aws, "PHOTO1", _jpeg()))
    assert sorted(_objects(aws, "derived/PHOTO1/")) == [
        "derived/PHOTO1/medium-1024.webp",
        "derived/PHOTO1/thumb-256.webp",
    ]


def test_derivatives_are_webp_and_bounded_by_longest_edge(aws):
    handler._process_object(_upload(aws, "PHOTO1", _jpeg(size=(2000, 1000))))
    for name, edge in (("thumb-256.webp", 256), ("medium-1024.webp", 1024)):
        body = (
            aws["s3"]
            .get_object(Bucket=BUCKET, Key=f"derived/PHOTO1/{name}")["Body"]
            .read()
        )
        image = Image.open(io.BytesIO(body))
        assert image.format == "WEBP"
        assert max(image.size) == edge
        assert image.size[0] / image.size[1] == pytest.approx(2.0, rel=0.01)


def test_records_hashes_and_dimensions(aws):
    handler._process_object(_upload(aws, "PHOTO1", _jpeg(size=(800, 600))))
    item = _photo(aws, "PHOTO1")
    assert len(item["sha256"]) == 64
    assert len(item["phash"]) == 16
    assert (int(item["width"]), int(item["height"])) == (800, 600)
    assert item["processedAt"]
    assert item["mediaType"] == "photo"


def test_a_photo_with_no_exif_is_not_a_failure(aws):
    handler._process_object(_upload(aws, "PHOTO1", _jpeg()))
    item = _photo(aws, "PHOTO1")
    assert "capturedAt" not in item
    assert item["status"] == "unlabeled"


# --- EXIF --------------------------------------------------------------


def _exif_with(timestamp=None, gps=None, orientation=None, offset=None):
    exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if timestamp:
        exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = timestamp.encode()
    if offset:
        exif["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = offset.encode()
    if orientation:
        exif["0th"][piexif.ImageIFD.Orientation] = orientation
    if gps:
        lat, lon = gps
        exif["GPS"] = {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: lat,
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: lon,
        }
    return piexif.dump(exif)


def test_extracts_capture_timestamp(aws):
    body = _jpeg(exif_bytes=_exif_with(timestamp="2026:03:14 15:09:26"))
    handler._process_object(_upload(aws, "PHOTO1", body))
    assert _photo(aws, "PHOTO1")["capturedAt"].startswith("2026-03-14T15:09:26")


def test_timestamp_without_an_offset_is_not_claimed_to_be_utc(aws):
    # EXIF wall-clock has no zone. Appending Z would assert a fact the
    # camera never recorded, off by up to 14h.
    body = _jpeg(exif_bytes=_exif_with(timestamp="2026:03:14 15:09:26"))
    handler._process_object(_upload(aws, "PHOTO1", body))
    assert not _photo(aws, "PHOTO1")["capturedAt"].endswith("Z")


def test_timestamp_with_an_offset_is_converted_to_utc(aws):
    body = _jpeg(
        exif_bytes=_exif_with(timestamp="2026:03:14 15:09:26", offset="+03:00")
    )
    handler._process_object(_upload(aws, "PHOTO1", body))
    captured = _photo(aws, "PHOTO1")["capturedAt"]
    assert captured.startswith("2026-03-14T12:09:26")
    assert captured.endswith("Z")


def test_negative_offsets_convert_the_other_way(aws):
    body = _jpeg(
        exif_bytes=_exif_with(timestamp="2026:03:14 15:09:26", offset="-05:00")
    )
    handler._process_object(_upload(aws, "PHOTO1", body))
    assert _photo(aws, "PHOTO1")["capturedAt"].startswith("2026-03-14T20:09:26")


def test_gps_is_rounded_to_roughly_100m(aws):
    # 31 deg 15' 45.6789" N, 34 deg 48' 3.21" E — deliberately over-precise.
    body = _jpeg(
        exif_bytes=_exif_with(
            gps=(
                ((31, 1), (15, 1), (456789, 10000)),
                ((34, 1), (48, 1), (321, 100)),
            )
        )
    )
    handler._process_object(_upload(aws, "PHOTO1", body))
    item = _photo(aws, "PHOTO1")
    lat, lon = float(item["coarseLat"]), float(item["coarseLon"])
    # Rounded to 3dp, so at most 3 decimals survive and the value stays
    # within ~110m of the truth.
    assert lat == round(lat, 3) and lon == round(lon, 3)
    assert lat == pytest.approx(31.2627, abs=0.001)
    assert lon == pytest.approx(34.8009, abs=0.001)


def test_derivatives_carry_no_exif(aws):
    body = _jpeg(
        exif_bytes=_exif_with(
            timestamp="2026:03:14 15:09:26",
            gps=(((31, 1), (15, 1), (0, 1)), ((34, 1), (48, 1), (0, 1))),
        )
    )
    handler._process_object(_upload(aws, "PHOTO1", body))
    for name in ("thumb-256.webp", "medium-1024.webp"):
        raw = (
            aws["s3"]
            .get_object(Bucket=BUCKET, Key=f"derived/PHOTO1/{name}")["Body"]
            .read()
        )
        assert not Image.open(io.BytesIO(raw)).getexif()


def test_orientation_is_baked_into_the_pixels(aws):
    # Orientation 6 means "rotate 90 CW to display": a 800x600 original
    # must come out 600x800 once the tag is applied and then discarded.
    body = _jpeg(size=(800, 600), exif_bytes=_exif_with(orientation=6))
    handler._process_object(_upload(aws, "PHOTO1", body))
    item = _photo(aws, "PHOTO1")
    assert (int(item["width"]), int(item["height"])) == (600, 800)


# --- duplicates --------------------------------------------------------


def test_identical_bytes_flag_the_second_photo_as_duplicate(aws):
    body = _jpeg()
    handler._process_object(_upload(aws, "PHOTO1", body))
    handler._process_object(_upload(aws, "PHOTO2", body))

    assert _photo(aws, "PHOTO1")["status"] == "unlabeled"
    second = _photo(aws, "PHOTO2")
    assert second["status"] == "duplicate"
    assert second["duplicateOf"] == "PHOTO1"
    assert second["GSI2PK"] == "STATUS#duplicate"


def test_reprocessing_the_same_photo_is_not_a_duplicate_of_itself(aws):
    key = _upload(aws, "PHOTO1", _jpeg())
    handler._process_object(key)
    handler._process_object(key)  # S3 can deliver the same event twice.

    item = _photo(aws, "PHOTO1")
    assert item["status"] == "unlabeled"
    assert "duplicateOf" not in item


def test_a_near_duplicate_is_flagged_but_stays_in_the_queue(aws):
    # Same scene, re-encoded — a burst frame, which spec 5 says to flag
    # and keep, never drop.
    original = Image.new("RGB", (400, 300), (100, 120, 140))
    for box, colour in (((10, 10, 200, 150), (30, 60, 90)),):
        original.paste(
            Image.new("RGB", (box[2] - box[0], box[3] - box[1]), colour), box
        )

    def encode(quality):
        buffer = io.BytesIO()
        original.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()

    handler._process_object(_upload(aws, "PHOTO1", encode(95)))
    handler._process_object(_upload(aws, "PHOTO2", encode(40)))

    second = _photo(aws, "PHOTO2")
    assert second["nearDuplicateOf"] == "PHOTO1"
    assert second["status"] == "unlabeled", "near-duplicates must stay labelable"


def test_different_photos_are_not_flagged(aws):
    handler._process_object(_upload(aws, "PHOTO1", _jpeg(colour=(10, 20, 30))))
    handler._process_object(
        _upload(aws, "PHOTO2", _jpeg(size=(640, 480), colour=(200, 40, 90)))
    )
    item = _photo(aws, "PHOTO2")
    assert "duplicateOf" not in item
    assert item["status"] == "unlabeled"


def test_near_duplicate_search_is_scoped_to_the_session(aws):
    body_a = _jpeg(colour=(100, 120, 140))
    handler._process_object(_upload(aws, "PHOTO1", body_a, session="SESSION-A"))
    # Same image, different session, different bytes so it isn't an exact
    # duplicate: the session-scoped search must not reach across.
    handler._process_object(
        _upload(aws, "PHOTO2", _jpeg(colour=(100, 120, 141)), session="SESSION-B")
    )
    assert "nearDuplicateOf" not in _photo(aws, "PHOTO2")


# --- video ---------------------------------------------------------------


def _upload_video(aws, photo_id, body, session=SESSION, ext="mp4"):
    key = f"raw/{session}/{photo_id}.{ext}"
    aws["s3"].put_object(Bucket=BUCKET, Key=key, Body=body)
    aws["table"].put_item(
        Item={
            "PK": f"PHOTO#{photo_id}",
            "SK": "META",
            "photoId": photo_id,
            "sessionId": session,
            "status": "unlabeled",
            "GSI1PK": f"SESSION#{session}",
            "GSI1SK": "2026-01-01T00:00:00.000000Z",
        }
    )
    return key


def test_video_is_hashed_but_gets_no_image_processing(aws):
    handler._process_object(_upload_video(aws, "VIDEO1", b"fake-mp4-bytes"))
    item = _photo(aws, "VIDEO1")

    assert len(item["sha256"]) == 64
    assert item["mediaType"] == "video"
    assert item["status"] == "unlabeled"
    assert "phash" not in item
    assert "width" not in item
    assert _objects(aws, "derived/VIDEO1/") == []


def test_identical_video_bytes_flag_the_second_as_duplicate(aws):
    body = b"same-video-bytes"
    handler._process_object(_upload_video(aws, "VIDEO1", body))
    handler._process_object(_upload_video(aws, "VIDEO2", body))

    assert _photo(aws, "VIDEO1")["status"] == "unlabeled"
    second = _photo(aws, "VIDEO2")
    assert second["status"] == "duplicate"
    assert second["duplicateOf"] == "VIDEO1"


def test_reprocessing_the_same_video_is_not_a_duplicate_of_itself(aws):
    key = _upload_video(aws, "VIDEO1", b"same-video-bytes")
    handler._process_object(key)
    handler._process_object(key)

    item = _photo(aws, "VIDEO1")
    assert item["status"] == "unlabeled"
    assert "duplicateOf" not in item


# --- event plumbing ----------------------------------------------------


def test_handler_processes_an_s3_event(aws):
    _upload(aws, "PHOTO1", _jpeg())
    handler.handler(
        {
            "Records": [
                {"s3": {"object": {"key": f"raw/{SESSION}/PHOTO1.jpg"}}},
            ]
        },
        None,
    )
    assert _photo(aws, "PHOTO1")["sha256"]


def test_handler_url_decodes_keys(aws):
    _upload(aws, "PHOTO1", _jpeg(), session="a+b")
    handler.handler(
        {"Records": [{"s3": {"object": {"key": "raw/a%2Bb/PHOTO1.jpg"}}}]}, None
    )
    assert _photo(aws, "PHOTO1")["sha256"]


def test_one_bad_object_does_not_stop_the_batch(aws):
    _upload(aws, "PHOTO1", _jpeg())
    handler.handler(
        {
            "Records": [
                {"s3": {"object": {"key": "raw/SESSION/MISSING.jpg"}}},
                {"s3": {"object": {"key": f"raw/{SESSION}/PHOTO1.jpg"}}},
            ]
        },
        None,
    )
    assert _photo(aws, "PHOTO1")["sha256"]
