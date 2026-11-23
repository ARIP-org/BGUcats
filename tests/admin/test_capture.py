"""In-app capture: encounters, presigned uploads, and the spec §10 write order.

The phone's upload to S3 is stood in for by a plain put_object — what these
tests check is everything the API does on either side of it.
"""

import base64
import json

import pytest

import tests.admin.test_handler  # noqa: F401  (sets the env the handler reads)
from admin import handler
from tests.admin.test_handler import ADMIN, BUCKET, _call, aws  # noqa: F401

HELPER = "helper@example.com"
OTHER = "other-helper@example.com"
ENCOUNTER = "01JBENC0000000000000000000"
PHOTO = "01JBPHT0000000000000000001"
PHOTO_2 = "01JBPHT0000000000000000002"
VIDEO = "01JBVDE0000000000000000001"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 60
GPS = {"lat": 31.262_345, "lon": 34.801_987, "accuracyM": 8.4}


@pytest.fixture
def app(aws):  # noqa: F811
    for email in (HELPER, OTHER):
        aws["table"].put_item(
            Item={
                "PK": f"ADMIN#{email}",
                "SK": "META",
                "email": email,
                "role": "collaborator",
            }
        )
    return aws


def _encounter(body=None, email=HELPER, session_id=ENCOUNTER):
    return _call(
        "POST", "/api/encounters", {"sessionId": session_id, **(body or {})}, email
    )


def _start_upload(photo_id=PHOTO, content_type="image/jpeg", email=HELPER, **extra):
    return _call(
        "POST",
        f"/api/encounters/{ENCOUNTER}/media",
        {"photoId": photo_id, "contentType": content_type, **extra},
        email,
    )


def _phone_uploads(app, key, data):
    app["s3"].put_object(Bucket=BUCKET, Key=key, Body=data)


def _item(app, pk):
    return app["table"].get_item(Key={"PK": pk, "SK": "META"}).get("Item")


def _policy(upload):
    return json.loads(base64.b64decode(upload["fields"]["policy"]))


# ---- encounters ---------------------------------------------------------


def test_an_encounter_is_an_app_session(app):
    status, data = _encounter(GPS)
    assert status == 200 and data["sessionId"] == ENCOUNTER

    session = _item(app, f"SESSION#{ENCOUNTER}")
    assert session["channel"] == "app"
    assert session["explicit"] is True
    assert session["startedBy"] == HELPER
    # Rounded to ~100 m like every other location in the table.
    assert float(session["coarseLat"]) == 31.262
    assert float(session["coarseLon"]) == 34.802
    assert session["locationSource"] == "app-gps"
    assert int(session["locationAccuracyM"]) == 8


def test_creating_the_same_encounter_twice_is_a_no_op(app):
    _encounter()
    status, _ = _encounter()
    assert status == 200
    assert _item(app, f"SESSION#{ENCOUNTER}")["startedBy"] == HELPER


def test_nobody_can_claim_someone_elses_encounter_id(app):
    _encounter()
    assert _encounter(email=OTHER)[0] == 403


def test_encounter_ids_must_be_ulids(app):
    assert (
        _call("POST", "/api/encounters", {"sessionId": "../../etc"}, HELPER)[0] == 400
    )
    assert _call("POST", "/api/encounters", {}, HELPER)[0] == 400


def test_bad_coordinates_are_dropped_not_stored(app):
    _encounter({"lat": 123.0, "lon": "34.8"})
    assert "coarseLat" not in _item(app, f"SESSION#{ENCOUNTER}")


def test_the_contributor_shows_up_on_the_stats_page(app):
    _encounter()
    profile = _item_with_sk(
        app, f"SUBMITTER#{handler._app_submitter_hash(HELPER)}", "PROFILE"
    )
    assert profile["channel"] == "app"
    assert profile["GSI2PK"] == "ENTITY#SUBMITTER"


def _item_with_sk(app, pk, sk):
    return app["table"].get_item(Key={"PK": pk, "SK": sk}).get("Item")


def _with_a_photo(app, session_id):
    app["table"].update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET photoCount = :n",
        ExpressionAttributeValues={":n": 1},
    )


def test_my_encounters_lists_only_mine_newest_first(app):
    for session_id, email in (
        ("01JBENC0000000000000000001", HELPER),
        ("01JBENC0000000000000000002", HELPER),
        ("01JBENC0000000000000000003", OTHER),
    ):
        _encounter(session_id=session_id, email=email)
        _with_a_photo(app, session_id)

    ids = [
        e["sessionId"]
        for e in _call("GET", "/api/encounters", email=HELPER)[1]["encounters"]
    ]
    assert ids == ["01JBENC0000000000000000002", "01JBENC0000000000000000001"]


def test_my_encounters_leave_out_empty_ones(app):
    _encounter(session_id="01JBENC0000000000000000001")
    _with_a_photo(app, "01JBENC0000000000000000001")
    # Opened and closed with nothing in it, more of them than one page holds.
    for n in range(handler.RECENT_ENCOUNTERS + 3):
        _encounter(session_id=f"01JBENC00000000000000001{n:02d}")

    ids = [
        e["sessionId"]
        for e in _call("GET", "/api/encounters", email=HELPER)[1]["encounters"]
    ]
    assert ids == ["01JBENC0000000000000000001"]


# ---- uploads ------------------------------------------------------------


def test_upload_writes_a_pending_record_first(app):
    _encounter()
    status, data = _start_upload(capturedAt="2026-10-28T09:15:00.000Z", **GPS)
    assert status == 200 and data["done"] is False

    photo = _item(app, f"PHOTO#{PHOTO}")
    assert photo["status"] == "pending"
    assert photo["s3RawKey"] is None  # not until the object is confirmed
    assert photo["uploadKey"] == f"raw/{ENCOUNTER}/{PHOTO}.jpg"
    assert photo["capturedAt"] == "2026-10-28T09:15:00.000Z"
    assert float(photo["coarseLat"]) == 31.262
    # Not in the session grid or the queue while pending — only on the
    # status index as pending, so Stats can count an upload that stalls.
    assert "GSI1PK" not in photo
    assert photo["GSI2PK"] == "STATUS#pending"
    assert photo["GSI2SK"] == photo["createdAt"]


def test_the_upload_url_can_write_exactly_one_object_of_one_kind(app):
    _encounter()
    upload = _start_upload()[1]["upload"]
    assert upload["fields"]["key"] == f"raw/{ENCOUNTER}/{PHOTO}.jpg"
    conditions = _policy(upload)["conditions"]
    assert {"Content-Type": "image/jpeg"} in conditions
    assert ["content-length-range", 1, 20 * 1024 * 1024] in conditions
    assert {"key": f"raw/{ENCOUNTER}/{PHOTO}.jpg"} in conditions


def test_only_jpeg_and_phone_video_are_accepted(app):
    _encounter()
    assert _start_upload(content_type="image/heic")[0] == 400
    assert _start_upload(content_type="text/html")[0] == 400
    assert _start_upload(VIDEO, "video/mp4")[0] == 200
    assert _start_upload("01JBVDE0000000000000000002", "video/webm")[0] == 200
    status, data = _start_upload("01JBVDE0000000000000000003", "video/quicktime")
    assert status == 200 and data["upload"]["fields"]["key"].endswith(".mov")


def test_nobody_else_can_upload_into_my_encounter(app):
    _encounter()
    assert _start_upload(email=OTHER)[0] == 403
    assert _start_upload(email=ADMIN)[0] == 403


def test_uploads_need_an_app_encounter(app):
    # A Telegram session cannot be written into from the app.
    app["table"].put_item(
        Item={
            "PK": f"SESSION#{ENCOUNTER}",
            "SK": "META",
            "sessionId": ENCOUNTER,
            "channel": "telegram",
        }
    )
    assert _start_upload()[0] == 404


def test_complete_refuses_until_the_object_is_in_storage(app):
    _encounter()
    _start_upload()
    status, _ = _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert status == 409
    assert _item(app, f"PHOTO#{PHOTO}")["status"] == "pending"


def test_complete_flips_to_unlabeled_and_joins_the_queue(app):
    _encounter()
    _start_upload(**GPS)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)

    status, data = _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert status == 200 and data["status"] == "unlabeled"

    photo = _item(app, f"PHOTO#{PHOTO}")
    assert photo["s3RawKey"] == f"raw/{ENCOUNTER}/{PHOTO}.jpg"
    assert photo["GSI1PK"] == f"SESSION#{ENCOUNTER}"
    assert photo["GSI2PK"] == "STATUS#unlabeled"
    assert _item(app, f"SESSION#{ENCOUNTER}")["photoCount"] == 1

    queue = _call("GET", "/api/queue")[1]["sessions"]
    assert [s["session"]["sessionId"] for s in queue] == [ENCOUNTER]


def test_counts_include_the_photo_just_written_when_the_index_lags(app, monkeypatch):
    """GSIs are eventually consistent: a recount right after a write may not
    see it. The count stored must still include what this call wrote."""
    real = handler._query_all

    def lagging(**kwargs):
        if kwargs.get("IndexName") in ("GSI1", "GSI3"):
            return []  # the index has not caught up with anything yet
        return real(**kwargs)

    _encounter()
    _start_upload(**GPS)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    monkeypatch.setattr(handler, "_query_all", lagging)

    assert _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)[0] == 200
    assert _item(app, f"SESSION#{ENCOUNTER}")["photoCount"] == 1

    cat = _call("POST", "/api/cats", {"name": "Mitzi"})[1]["catId"]
    assert _call("POST", f"/api/photos/{PHOTO}/assign", {"catId": cat})[0] == 200
    assert _item(app, f"CAT#{cat}")["photoCount"] == 1


def test_the_first_located_photo_pins_an_unlocated_encounter(app):
    _encounter()  # no GPS fix yet when it opened
    _start_upload(**GPS)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)

    session = _item(app, f"SESSION#{ENCOUNTER}")
    assert float(session["coarseLat"]) == 31.262
    assert int(session["locationAccuracyM"]) == 8


def test_an_encounter_location_is_not_overwritten_by_later_photos(app):
    _encounter({"lat": 31.0, "lon": 34.0})
    _start_upload(**GPS)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert float(_item(app, f"SESSION#{ENCOUNTER}")["coarseLat"]) == 31.0


def test_bytes_that_are_not_what_was_declared_are_deleted(app):
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", b"<html>not a photo</html>")

    status, _ = _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert status == 400
    assert _item(app, f"PHOTO#{PHOTO}") is None
    versions = app["s3"].list_object_versions(Bucket=BUCKET, Prefix=f"raw/{ENCOUNTER}/")
    assert not versions.get("Versions")


def test_videos_are_recognised_by_their_bytes(app):
    _encounter()
    _start_upload(VIDEO, "video/mp4", durationSeconds=9.73)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{VIDEO}.mp4", MP4)
    status, data = _call("POST", f"/api/photos/{VIDEO}/complete", email=HELPER)
    assert status == 200 and data["status"] == "unlabeled"
    video = _item(app, f"PHOTO#{VIDEO}")
    assert video["mediaType"] == "video"
    assert float(video["durationSeconds"]) == 9.7


def test_a_duplicate_verdict_from_processing_is_kept(app):
    # The process Lambda can beat the phone's complete call to the record.
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    app["table"].update_item(
        Key={"PK": f"PHOTO#{PHOTO}", "SK": "META"},
        UpdateExpression="SET #s = :d, GSI2PK = :g",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":d": "duplicate", ":g": "STATUS#duplicate"},
    )

    status, data = _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert status == 200 and data["status"] == "duplicate"
    photo = _item(app, f"PHOTO#{PHOTO}")
    assert photo["GSI2PK"] == "STATUS#duplicate"
    # Still visible in its own session, like a bot duplicate.
    assert photo["GSI1PK"] == f"SESSION#{ENCOUNTER}"


def test_retrying_a_finished_upload_tells_the_outbox_to_stop(app):
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)

    status, data = _start_upload()
    assert status == 200 and data["done"] is True and "upload" not in data
    status, data = _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    assert status == 200 and data["status"] == "unlabeled"


def test_retrying_a_pending_upload_issues_a_fresh_url(app):
    _encounter()
    _start_upload()
    status, data = _start_upload()
    assert status == 200 and data["done"] is False and data["upload"]


def test_a_retry_cannot_switch_the_file_type(app):
    _encounter()
    _start_upload()
    assert _start_upload(content_type="video/mp4")[0] == 409


def test_nobody_else_can_complete_my_upload(app):
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    assert _call("POST", f"/api/photos/{PHOTO}/complete", email=OTHER)[0] == 403


def test_a_late_photo_of_a_labeled_encounter_inherits_the_cat(app):
    cat = _call("POST", "/api/cats", {"name": "Ryzhik"})[1]["catId"]
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    _call("POST", f"/api/sessions/{ENCOUNTER}/assign", {"catId": cat})

    _start_upload(PHOTO_2)
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO_2}.jpg", JPEG)
    _, data = _call("POST", f"/api/photos/{PHOTO_2}/complete", email=HELPER)

    assert data["status"] == "labeled"
    assert _item(app, f"PHOTO#{PHOTO_2}")["catId"] == cat
    assert _item(app, f"CAT#{cat}")["photoCount"] == 2
    assert _call("GET", "/api/queue")[1]["sessions"] == []


def test_my_encounters_show_which_cat_they_became(app):
    cat = _call("POST", "/api/cats", {"name": "Ryzhik"})[1]["catId"]
    _encounter()
    _start_upload()
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)
    _call("POST", f"/api/sessions/{ENCOUNTER}/assign", {"catId": cat})

    [encounter] = _call("GET", "/api/encounters", email=HELPER)[1]["encounters"]
    assert encounter["catName"] == "Ryzhik"
    assert encounter["photoCount"] == 1


# --- reads right after a write -------------------------------------------


def test_the_upload_path_never_reads_a_stale_copy(app, monkeypatch):
    """The phone sends an encounter, its photo's record and the confirmation
    one after another. A default DynamoDB read may miss a write made
    milliseconds earlier; a 404 on any of these makes the outbox give the
    photo up. On staging that happened to one encounter in twelve."""
    reads = []
    real_get_item = app["table"].get_item

    def spy(**kwargs):
        reads.append(kwargs)
        return real_get_item(**kwargs)

    monkeypatch.setattr(app["table"], "get_item", spy)

    assert _encounter()[0] == 200
    assert _start_upload()[0] == 200
    _phone_uploads(app, f"raw/{ENCOUNTER}/{PHOTO}.jpg", JPEG)
    assert _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)[0] == 200

    assert reads
    stale = [read["Key"]["PK"] for read in reads if not read.get("ConsistentRead")]
    assert not stale, f"read without ConsistentRead: {stale}"


def test_a_place_that_arrives_after_the_first_photo_is_taken_once(app):
    """GPS takes seconds, and nobody waits for it to take a photo: the
    outbox sends the encounter again with the place. An encounter with no
    place takes it; one that has a place keeps it."""

    def place():
        item = app["table"].get_item(Key={"PK": f"SESSION#{ENCOUNTER}", "SK": "META"})["Item"]
        return item.get("coarseLat"), item.get("coarseLon"), item.get("locationSource")

    assert _encounter()[0] == 200
    assert place() == (None, None, None)
    library = {"lat": 31.26219, "lon": 34.80312, "accuracyM": 8}
    status, body = _encounter(library)
    assert status == 200 and body["sessionId"] == ENCOUNTER
    assert [str(v) for v in place()] == ["31.262", "34.803", "app-gps"]
    # Sent again from somewhere else: the first place stands.
    assert _encounter({"lat": 31.3, "lon": 34.9})[0] == 200
    assert [str(v) for v in place()] == ["31.262", "34.803", "app-gps"]
    # And nobody places someone else's encounter.
    assert _encounter({"lat": 31.3, "lon": 34.9}, email=ADMIN)[0] == 403


# ---- a photo from the phone's gallery (#108) ------------------------------


def _jpeg_taken_at(lat_dms, lon_dms, when=b"2025:06:01 10:20:30"):
    """A real JPEG whose EXIF holds a capture time and a position."""
    import io

    import piexif
    from PIL import Image

    exif = piexif.dump(
        {
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: when},
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: lat_dms,
                piexif.GPSIFD.GPSLongitudeRef: b"E",
                piexif.GPSIFD.GPSLongitude: lon_dms,
            },
            "1st": {},
            "thumbnail": None,
        }
    )
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), (120, 90, 60)).save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


# Tel Aviv, nowhere near campus: where an old gallery photo was taken.
ELSEWHERE = (((32, 1), (5, 1), (0, 1)), ((34, 1), (46, 1), (0, 1)))


def _process(app, monkeypatch, key):
    """The real process Lambda, on the object the phone uploaded."""
    from process import handler as process_handler

    monkeypatch.setattr(process_handler, "table", app["table"])
    monkeypatch.setattr(process_handler, "s3", app["s3"])
    monkeypatch.setattr(process_handler, "MEDIA_BUCKET", BUCKET)
    process_handler.handler({"Records": [{"s3": {"object": {"key": key}}}]}, None)


def _send_photo(app, monkeypatch, **extra):
    _encounter()  # no place yet: only a photo could give it one
    status, _ = _start_upload(**GPS, **extra)
    assert status == 200
    key = f"raw/{ENCOUNTER}/{PHOTO}.jpg"
    _phone_uploads(app, key, _jpeg_taken_at(*ELSEWHERE))
    # Either order happens in AWS; here processing runs before the
    # confirmation, so a place it wrote would be there for the encounter.
    _process(app, monkeypatch, key)
    assert _call("POST", f"/api/photos/{PHOTO}/complete", email=HELPER)[0] == 200
    return _item(app, f"PHOTO#{PHOTO}"), _item(app, f"SESSION#{ENCOUNTER}")


def test_a_gallery_photo_keeps_no_place_and_gives_its_encounter_none(
    app, monkeypatch
):
    photo, session = _send_photo(app, monkeypatch, origin="gallery")
    assert photo["origin"] == "gallery"
    assert photo.get("coarseLat") is None and photo.get("coarseLon") is None
    assert "locationSource" not in photo and "locationAccuracyM" not in photo
    assert session.get("coarseLat") is None and session.get("coarseLon") is None
    # The capture time is kept: the owner spoke of the place only.
    assert photo["capturedAt"].startswith("2025-06-01T10:20:30")
    assert photo["status"] == "unlabeled" and photo.get("width") == 320


def test_a_camera_photo_still_gets_its_place(app, monkeypatch):
    photo, session = _send_photo(app, monkeypatch)
    assert "origin" not in photo
    assert photo.get("coarseLat") is not None
    assert float(session["coarseLat"]) == float(photo["coarseLat"])


def test_saying_camera_is_the_same_as_saying_nothing(app):
    _encounter()
    assert _start_upload(**GPS, origin="camera")[0] == 200
    assert _start_upload(**GPS, origin=None)[0] == 200  # null is the default
    photo = _item(app, f"PHOTO#{PHOTO}")
    assert "origin" not in photo and float(photo["coarseLat"]) == 31.262


def test_an_unknown_origin_is_refused(app):
    _encounter()
    assert _start_upload(origin="screenshot")[0] == 400
    assert _start_upload(origin=True)[0] == 400
    assert _item(app, f"PHOTO#{PHOTO}") is None


def test_a_gallery_photo_sent_twice_lands_on_the_same_item(app):
    _encounter()
    assert _start_upload(**GPS, origin="gallery")[0] == 200
    status, data = _start_upload(**GPS, origin="gallery")
    assert status == 200 and data["done"] is False
    photo = _item(app, f"PHOTO#{PHOTO}")
    assert photo["origin"] == "gallery" and photo.get("coarseLat") is None


def test_a_retry_cannot_change_where_the_photo_came_from(app):
    _encounter()
    _start_upload(**GPS, origin="gallery")
    assert _start_upload(**GPS)[0] == 409
    assert _item(app, f"PHOTO#{PHOTO}")["origin"] == "gallery"
