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


def test_a_guess_is_recorded_for_a_session_written_with_a_null_cat(aws):
    # The bots and the app create sessions with catId = None, not without it.
    _session(aws, catId=None)
    status, body = _guess()
    assert (status, body["new"]) == (200, True)


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


# --------------------------------------------------------------------------
# Shared vectors — computed once by an admin's browser, read by every phone
# --------------------------------------------------------------------------

import base64
import struct


def _get(path, email="admin@example.com"):
    """GET with a query string, as API Gateway delivers it."""
    import json
    from urllib.parse import parse_qsl, urlsplit

    from tests.admin.test_handler import _event

    parts = urlsplit(path)
    event = _event("GET", parts.path, email=email)
    event["queryStringParameters"] = dict(parse_qsl(parts.query)) or None
    response = tests.admin.test_handler.handler.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


COLLABORATOR = "helper@example.com"


def _vec(dim=768, hot=0):
    values = [0.0] * dim
    values[hot] = 1.0
    return base64.b64encode(struct.pack(f"<{dim}f", *values)).decode()


def _collaborator(aws):
    aws["table"].put_item(
        Item={
            "PK": f"ADMIN#{COLLABORATOR}",
            "SK": "META",
            "email": COLLABORATOR,
            "role": "collaborator",
        }
    )


def _labeled_photo(aws, photo_id, session_id=SESSION, cat_id=CAT):
    item = _photo(aws, photo_id, session_id=session_id)
    aws["table"].update_item(
        Key={"PK": f"PHOTO#{photo_id}", "SK": "META"},
        UpdateExpression="SET #s = :l, GSI2PK = :q, catId = :c",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":l": "labeled",
            ":q": "STATUS#labeled",
            ":c": cat_id,
        },
    )
    return item


def test_vectors_written_by_an_admin_are_served_to_a_collaborator(aws):
    _collaborator(aws)
    _labeled_photo(aws, "01PHOTO00000000000000000001")
    _labeled_photo(aws, "01PHOTO00000000000000000002")
    _photo(aws, "01PHOTO00000000000000000003", session_id=OTHER_SESSION)  # unlabeled

    status, body = _call(
        "POST",
        "/api/recognition/vectors",
        {
            "modelVersion": MODEL,
            "vectors": [
                {"photoId": "01PHOTO00000000000000000001", "vector": _vec(hot=1)},
                {"photoId": "01PHOTO00000000000000000002", "vector": _vec(hot=2)},
                {"photoId": "01PHOTO00000000000000000003", "vector": _vec(hot=3)},
                {"photoId": "01PHOTO0000000000000000GONE", "vector": _vec()},
            ],
        },
    )
    assert (status, body["written"]) == (200, 3)

    status, body = _get(f"/api/recognition/vectors?version={MODEL}", email=COLLABORATOR)
    assert status == 200
    templates = {t["photoId"]: t for t in body["templates"]}
    # The unlabeled photo's vector is stored but is not a template yet.
    assert sorted(templates) == [
        "01PHOTO00000000000000000001",
        "01PHOTO00000000000000000002",
    ]
    assert templates["01PHOTO00000000000000000001"]["catId"] == CAT
    assert templates["01PHOTO00000000000000000001"]["vector"] == _vec(hot=1)
    assert body["next"] is None


def test_vectors_are_paged(aws, monkeypatch):
    monkeypatch.setattr(tests.admin.test_handler.handler, "VECTOR_PAGE", 2)
    ids = [f"01PHOTO0000000000000000000{i}" for i in range(5)]
    for pid in ids:
        _labeled_photo(aws, pid)
    _call(
        "POST",
        "/api/recognition/vectors",
        {
            "modelVersion": MODEL,
            "vectors": [{"photoId": p, "vector": _vec()} for p in ids],
        },
    )
    seen, after = [], None
    for _ in range(5):
        query = f"?version={MODEL}" + (f"&after={after}" if after else "")
        _, body = _get(f"/api/recognition/vectors{query}")
        seen += [t["photoId"] for t in body["templates"]]
        after = body["next"]
        if not after:
            break
    assert sorted(seen) == ids


def test_a_deleted_photo_takes_its_vector_with_it(aws):
    _labeled_photo(aws, "01PHOTO00000000000000000001")
    _call(
        "POST",
        "/api/recognition/vectors",
        {
            "modelVersion": MODEL,
            "vectors": [{"photoId": "01PHOTO00000000000000000001", "vector": _vec()}],
        },
    )
    _call("POST", "/api/photos/01PHOTO00000000000000000001/reject")
    item = (
        aws["table"]
        .get_item(
            Key={"PK": "PHOTO#01PHOTO00000000000000000001", "SK": f"VECTOR#{MODEL}"}
        )
        .get("Item")
    )
    assert item is None


@pytest.mark.parametrize(
    "vector",
    [
        "not base64!!",
        base64.b64encode(b"abc").decode(),  # not float32s
        base64.b64encode(struct.pack("<768f", *([0.5] * 768))).decode(),  # not unit
        base64.b64encode(
            struct.pack("<8f", *([0.0] * 7 + [1.0]))
        ).decode(),  # too short
    ],
)
def test_malformed_vectors_are_refused(aws, vector):
    _labeled_photo(aws, "01PHOTO00000000000000000001")
    status, _ = _call(
        "POST",
        "/api/recognition/vectors",
        {
            "modelVersion": MODEL,
            "vectors": [{"photoId": "01PHOTO00000000000000000001", "vector": vector}],
        },
    )
    assert status == 400


def test_collaborators_read_vectors_but_cannot_write_them(aws):
    _collaborator(aws)
    status, _ = _call(
        "POST",
        "/api/recognition/vectors",
        {
            "modelVersion": MODEL,
            "vectors": [{"photoId": "01PHOTO00000000000000000001", "vector": _vec()}],
        },
        email=COLLABORATOR,
    )
    assert status == 403
    status, _ = _get(f"/api/recognition/vectors?version={MODEL}", email=COLLABORATOR)
    assert status == 200


# --------------------------------------------------------------------------
# Contributor picks — the product loop, scored against the admin's label
# --------------------------------------------------------------------------

ENCOUNTER = "01JENC0000000000000000000A"


def _encounter(aws, email=COLLABORATOR):
    status, _ = _call("POST", "/api/encounters", {"sessionId": ENCOUNTER}, email=email)
    assert status == 200


def _pick(email=COLLABORATOR, **overrides):
    body = {
        "modelVersion": MODEL,
        "choice": "cat",
        "catId": CAT,
        "shown": [CAT, OTHER_CAT],
        "ranked": [{"catId": CAT, "score": 0.5}, {"catId": OTHER_CAT, "score": 0.4}],
        "photoCount": 2,
        "pickedAt": "2026-10-29T10:00:00Z",
        **overrides,
    }
    return _call("POST", f"/api/encounters/{ENCOUNTER}/pick", body, email=email)


def test_a_pick_is_joined_with_the_label_and_never_shown_to_the_labeler(aws):
    _collaborator(aws)
    _cat(aws)
    _cat(aws, OTHER_CAT, "Ryzhik")
    _encounter(aws)
    assert _pick()[0] == 200
    # changed their mind after a better photo: the latest answer wins
    assert _pick(catId=OTHER_CAT)[0] == 200

    _, session = _call("GET", f"/api/sessions/{ENCOUNTER}")
    assert "pick" not in json_dump(session) and "PICK" not in json_dump(session)

    aws["table"].update_item(
        Key={"PK": f"SESSION#{ENCOUNTER}", "SK": "META"},
        # Labeled, so it holds a photo (an empty encounter is not listed).
        UpdateExpression="SET catId = :c, photoCount = :n",
        ExpressionAttributeValues={":c": CAT, ":n": 1},
    )
    _, listing = _call("GET", "/api/recognition/predictions")
    [pick] = listing["picks"]
    assert (pick["catId"], pick["truthCatId"], pick["choice"]) == (
        OTHER_CAT,
        CAT,
        "cat",
    )

    _, mine = _call("GET", "/api/encounters", email=COLLABORATOR)
    assert mine["encounters"][0]["pick"] == {
        "choice": "cat",
        "catId": OTHER_CAT,
        "catName": "Ryzhik",
        # the model's first guess, from the ranking shown to them
        "modelCatId": CAT,
        "modelCatName": "Mitzi",
    }
    assert mine["encounters"][0]["catName"] == "Mitzi"


def test_none_and_unsure_need_no_cat(aws):
    _collaborator(aws)
    _encounter(aws)
    assert _pick(choice="none", catId=None)[0] == 200
    assert _pick(choice="unsure")[0] == 200
    _, listing = _call("GET", "/api/recognition/predictions")
    assert listing["picks"][0]["catId"] is None


def test_only_the_encounters_owner_can_pick(aws):
    _collaborator(aws)
    _cat(aws)
    _encounter(aws)
    status, _ = _pick(email="admin@example.com")
    assert status == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"choice": "maybe"},
        {"catId": None},
        {"catId": "01CAT0000000000000000NOPE"},
        {"shown": []},
        {"shown": ["a"] * 6},
        {"ranked": [{"catId": CAT, "score": 2}]},
        {"photoCount": 0},
        {"modelVersion": "Bad Version"},
    ],
)
def test_malformed_picks_are_refused(aws, overrides):
    _collaborator(aws)
    _cat(aws)
    _encounter(aws)
    status, _ = _pick(**overrides)
    assert status in (400, 404)


def json_dump(value):
    import json

    return json.dumps(value)
