"""The API side of measuring the model: the gallery the browser embeds, and
the record of what the model guessed before a person labeled the session."""

import pytest

import tests.admin.test_handler
from tests.admin.test_handler import (
    OTHER_SESSION,
    SESSION,
    _call,
    _photo,
    _session,
    _video,
)

# The moto fixture, re-exported by assignment so pytest finds it here.
aws = tests.admin.test_handler.aws

CAT = "01CAT00000000000000000000A"
OTHER_CAT = "01CAT00000000000000000000B"
MODEL = "mega-t224-int8-0123456789ab"


def _cat(aws, cat_id=CAT, name="Mitzi"):
    aws["table"].put_item(
        Item={
            "PK": f"CAT#{cat_id}",
            "SK": "META",
            "catId": cat_id,
            "name": name,
            "GSI2PK": "ENTITY#CAT",
            "GSI2SK": name,
        }
    )


def _guess(session_id=SESSION, **overrides):
    body = {
        "modelVersion": MODEL,
        "ranked": [
            {"catId": CAT, "score": 0.61234567},
            {"catId": OTHER_CAT, "score": 0.4},
        ],
        "photoCount": 3,
        **overrides,
    }
    return _call("POST", f"/api/sessions/{session_id}/prediction", body)


def test_gallery_lists_labeled_photos_with_a_medium_url_and_no_videos(aws):
    _cat(aws)
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000001")
    _photo(aws, "01PHOTO00000000000000000002")
    _video(aws, "01PHOTO00000000000000000003")
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": CAT})
    _photo(aws, "01PHOTO00000000000000000004", session_id=OTHER_SESSION)

    status, body = _call("GET", "/api/recognition/gallery")

    assert status == 200
    ids = sorted(p["photoId"] for p in body["photos"])
    assert ids == ["01PHOTO00000000000000000001", "01PHOTO00000000000000000002"]
    photo = body["photos"][0]
    assert photo["catId"] == CAT and photo["sessionId"] == SESSION
    assert "medium-1024.webp" in photo["mediumUrl"]


def test_a_guess_is_recorded_once_and_a_retry_does_not_overwrite_it(aws):
    _session(aws)

    status, body = _guess()
    assert (status, body["new"]) == (200, True)
    status, body = _guess(ranked=[{"catId": OTHER_CAT, "score": 0.9}])
    assert (status, body["new"]) == (200, False)

    _, listing = _call("GET", "/api/recognition/predictions")
    [prediction] = listing["predictions"]
    assert prediction["ranked"][0] == {"catId": CAT, "score": 0.6123}
    assert prediction["predictedBy"] == "admin@example.com"
    assert prediction["truthCatId"] is None


def test_a_guess_after_the_session_is_labeled_is_refused(aws):
    _session(aws, catId=CAT)
    status, _ = _guess()
    assert status == 409


def test_a_guess_for_an_unknown_session_is_404(aws):
    status, _ = _guess()
    assert status == 404


def test_a_recorded_guess_is_joined_with_the_label_given_later(aws):
    _cat(aws)
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000001")
    _guess()
    _call("POST", f"/api/sessions/{SESSION}/assign", {"catId": CAT})

    _, listing = _call("GET", "/api/recognition/predictions")
    [prediction] = listing["predictions"]
    assert prediction["truthCatId"] == CAT
    assert prediction["labeledAt"]


def test_a_merged_session_takes_the_cat_of_the_session_it_joined(aws):
    _session(aws)
    _session(aws, session_id=OTHER_SESSION, catId=OTHER_CAT)
    _photo(aws, "01PHOTO00000000000000000001")
    _guess()
    _call(
        "POST",
        "/api/sessions/merge",
        {"sourceSessionId": SESSION, "targetSessionId": OTHER_SESSION},
    )

    _, listing = _call("GET", "/api/recognition/predictions")
    assert listing["predictions"][0]["truthCatId"] == OTHER_CAT


def test_a_deleted_session_is_not_a_measurement(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000001")
    _guess()
    _call("POST", f"/api/sessions/{SESSION}/reject")

    _, listing = _call("GET", "/api/recognition/predictions")
    assert listing["predictions"][0]["truthCatId"] is None


def test_prediction_records_stay_out_of_the_session_and_queue_views(aws):
    _session(aws)
    _photo(aws, "01PHOTO00000000000000000001")
    _guess()

    _, queue = _call("GET", "/api/queue")
    [entry] = queue["sessions"]
    assert entry["session"]["sessionId"] == SESSION
    assert [p["photoId"] for p in entry["photos"]] == ["01PHOTO00000000000000000001"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"modelVersion": "Has Spaces"},
        {"modelVersion": ""},
        {"ranked": "not a list"},
        {"ranked": [{"catId": CAT}]},
        {"ranked": [{"catId": CAT, "score": 1.5}]},
        {"ranked": [{"catId": "../x", "score": 0.1}]},
        {"ranked": [{"catId": CAT, "score": 0.1}] * 201},
        {"photoCount": 0},
        {"photoCount": "3"},
    ],
)
def test_malformed_guesses_are_refused(aws, overrides):
    _session(aws)
    status, _ = _guess(**overrides)
    assert status == 400


def test_collaborators_cannot_see_or_record_guesses(aws):
    aws["table"].put_item(
        Item={
            "PK": "ADMIN#helper@example.com",
            "SK": "META",
            "email": "helper@example.com",
            "role": "collaborator",
        }
    )
    _session(aws)
    for method, path, body in (
        ("GET", "/api/recognition/gallery", None),
        ("GET", "/api/recognition/predictions", None),
        ("POST", f"/api/sessions/{SESSION}/prediction", {"modelVersion": MODEL}),
    ):
        status, _ = _call(method, path, body, email="helper@example.com")
        assert status == 403
