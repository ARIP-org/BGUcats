"""Changing who you are (B1): `PATCH /me`. A new display name is its
owner's at once and everyone's once it has been checked, which the events
Lambda does; the settings are simply stored."""

import base64
import io
import json

import pytest
from PIL import Image

from app import handler
from events import handler as events
from tests.events.stream import Stream

from .test_me import ADMIN, HELPER, aws, call  # noqa: F401  (the fixture)

TERMS = {"version": "2026-11"}


@pytest.fixture
def people(aws, monkeypatch):  # noqa: F811
    """Two members who accepted the terms, and the stream to the events
    Lambda, which publishes a changed name."""
    monkeypatch.setattr(events, "social_table", aws["social"])
    for who, name in ((ADMIN, "Sasha"), (HELPER, "Maya")):
        call("GET", "/api/v1/me", email=who, name=name)
        call("POST", "/api/v1/me/terms", TERMS, email=who)
    stream = Stream(aws["social"])
    return {"social": aws["social"], "stream": stream}


def profile(table, email):
    user_id = table.get_item(Key={"PK": f"IDENTITY#{email}", "SK": "META"})["Item"]["userId"]
    return table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})["Item"]


def test_a_new_name_is_its_owners_at_once_and_everyones_once_checked(people):
    status, me = call("PATCH", "/api/v1/me", {"displayName": "  Sasha   the Brave "})
    assert status == 200
    # Cleaned as every text is, and shown to its owner straight away.
    assert (me["displayName"], me["namePending"]) == ("Sasha the Brave", True)
    # Everyone else still reads the old one: it is what the item publishes.
    kept = profile(people["social"], ADMIN)
    assert (kept["displayName"], kept["pendingName"]) == ("Sasha", "Sasha the Brave")

    assert people["stream"].settle() > 0
    now = profile(people["social"], ADMIN)
    assert now["displayName"] == "Sasha the Brave"
    assert "pendingName" not in now and "pendingNameAt" not in now
    _, me = call("GET", "/api/v1/me")
    assert (me["displayName"], me["namePending"]) == ("Sasha the Brave", False)


def test_a_name_changed_again_before_it_was_checked_is_not_published(people):
    """The stream hands the Lambda the first change after the second was
    written: the condition is the name it read, so the first is dropped and
    the second goes out with its own record."""
    call("PATCH", "/api/v1/me", {"displayName": "First"})
    first = people["stream"]._records(people["stream"].seen, people["stream"]._snapshot())
    call("PATCH", "/api/v1/me", {"displayName": "Second"})
    assert events.handler({"Records": first}, None) == {"batchItemFailures": []}
    assert profile(people["social"], ADMIN)["displayName"] == "Sasha"
    people["stream"].settle()
    assert profile(people["social"], ADMIN)["displayName"] == "Second"


def test_going_back_to_the_published_name_needs_no_check(people):
    call("PATCH", "/api/v1/me", {"displayName": "Other"})
    status, me = call("PATCH", "/api/v1/me", {"displayName": "Sasha"})
    assert (status, me["displayName"], me["namePending"]) == (200, "Sasha", False)
    assert "pendingName" not in profile(people["social"], ADMIN)


def test_the_same_name_twice_is_one_change(people, monkeypatch):
    monkeypatch.setattr(handler, "NAME_CHANGES_PER_DAY", 1)
    for _ in range(3):  # a retry from the phone lands on the same name
        status, _ = call("PATCH", "/api/v1/me", {"displayName": "Once"})
        assert status == 200
    status, body = call("PATCH", "/api/v1/me", {"displayName": "Twice"})
    assert (status, body["code"]) == (429, "rate_limited")
    assert body["retryAfter"] > 0


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 31, 7, None],
)
def test_a_name_that_cannot_be_one_is_refused(people, name):
    status, _ = call("PATCH", "/api/v1/me", {"displayName": name})
    assert status == 400
    assert "pendingName" not in profile(people["social"], ADMIN)


def test_a_name_is_public_writing_so_the_terms_come_first(aws):  # noqa: F811
    call("GET", "/api/v1/me")
    status, body = call("PATCH", "/api/v1/me", {"displayName": "Early"})
    assert (status, body["code"]) == (403, "terms_required")
    # A setting is the person's own business and needs no terms.
    status, me = call("PATCH", "/api/v1/me", {"theme": "cats-dark"})
    assert (status, me["theme"]) == (200, "cats-dark")


def test_settings_are_stored_and_only_the_ones_sent_change(people):
    status, me = call(
        "PATCH",
        "/api/v1/me",
        {"language": "he", "theme": "bgu-light", "notifications": False},
    )
    assert status == 200
    assert (me["language"], me["theme"], me["notifications"]) == ("he", "bgu-light", False)
    _, me = call("PATCH", "/api/v1/me", {"theme": "cats-light"})
    assert (me["language"], me["theme"], me["notifications"]) == ("he", "cats-light", False)
    assert me["displayName"] == "Sasha"
    # A setting is not a change anyone else sees: nothing to publish.
    people["stream"].settle()
    assert "pendingName" not in profile(people["social"], ADMIN)


@pytest.mark.parametrize(
    "body",
    [
        {"language": "tlh"},
        {"theme": "neon"},
        {"notifications": "yes"},
        {},
        {"email": "someone@else.example"},
    ],
)
def test_a_setting_that_is_not_one_is_refused(people, body):
    before = profile(people["social"], ADMIN)
    status, _ = call("PATCH", "/api/v1/me", body)
    assert status == 400
    assert profile(people["social"], ADMIN) == before


def test_nobody_else_is_changed_and_nobody_elses_pending_name_is_shown(people):
    call("PATCH", "/api/v1/me", {"displayName": "Renamed"}, email=HELPER)
    assert profile(people["social"], ADMIN)["displayName"] == "Sasha"
    _, me = call("GET", "/api/v1/me")
    assert (me["displayName"], me["namePending"]) == ("Sasha", False)


# ------------------------------------------------------- the profile photo

BUCKET = "bgucats-media-test"


def picture(kind="JPEG", **options):
    """A small picture's bytes: what a phone's canvas would hand over, or,
    with `exif`, what a camera writes."""
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(out, kind, **options)
    return out.getvalue()


def camera_picture():
    exif = Image.Exif()
    exif[0x010F] = "A phone maker"
    return picture(exif=exif)


@pytest.fixture
def bucket(people):
    """The media bucket, keeping versions as the real one does."""
    s3 = handler.s3
    s3.create_bucket(Bucket=BUCKET)
    s3.put_bucket_versioning(
        Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
    )
    return {**people, "s3": s3}


def stored(s3):
    """Every version of every object in the bucket, by key."""
    listing = s3.list_object_versions(Bucket=BUCKET)
    return sorted(v["Key"] for v in listing.get("Versions", []) + listing.get("DeleteMarkers", []))


def upload(s3, email=ADMIN, body=None):
    """Asks where to send a photo and puts one there, as the phone's POST
    would. Returns (avatarId, key)."""
    status, started = call("POST", "/api/v1/me/avatar", email=email)
    assert status == 200, started
    key = started["upload"]["fields"]["key"]
    s3.put_object(Bucket=BUCKET, Key=key, Body=body or picture(), ContentType="image/jpeg")
    return started["avatarId"], key


def test_the_upload_is_pinned_to_the_persons_own_key_type_and_size(bucket):
    status, started = call("POST", "/api/v1/me/avatar")
    assert status == 200
    user_id = profile(bucket["social"], ADMIN)["userId"]
    fields = started["upload"]["fields"]
    assert fields["key"] == f"avatars/{user_id}/{started['avatarId']}.jpg"
    assert fields["Content-Type"] == "image/jpeg"
    policy = json.loads(base64.b64decode(fields["policy"]))
    assert ["content-length-range", 1, 200_000] in policy["conditions"]
    assert {"key": fields["key"]} in policy["conditions"]
    assert {"Content-Type": "image/jpeg"} in policy["conditions"]


def test_a_new_photo_is_its_owners_at_once_and_everyones_once_checked(bucket):
    avatar_id, key = upload(bucket["s3"])
    status, me = call("POST", f"/api/v1/me/avatar/{avatar_id}/complete")
    assert status == 200
    assert key in me["avatar"] and me["avatarPending"] is True
    kept = profile(bucket["social"], ADMIN)
    assert kept["pendingAvatarKey"] == key and "avatarKey" not in kept

    assert bucket["stream"].settle() > 0
    now = profile(bucket["social"], ADMIN)
    assert now["avatarKey"] == key and "pendingAvatarKey" not in now
    _, me = call("GET", "/api/v1/me")
    assert key in me["avatar"] and me["avatarPending"] is False
    # Confirming twice (a lost answer, sent again) changes nothing.
    assert call("POST", f"/api/v1/me/avatar/{avatar_id}/complete")[0] == 200
    assert profile(bucket["social"], ADMIN) == now


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (camera_picture(), "EXIF"),
        (picture("PNG"), "not a JPEG"),
        (b"not a picture at all", "not a JPEG"),
    ],
)
def test_a_photo_with_the_cameras_data_or_that_is_no_jpeg_is_refused_and_removed(
    bucket, body, why
):
    avatar_id, _ = upload(bucket["s3"], body=body)
    status, answer = call("POST", f"/api/v1/me/avatar/{avatar_id}/complete")
    assert (status, answer["code"]) == (400, "bad_photo")
    assert why in answer["error"]
    # Not kept anywhere: no version of it is left in the bucket.
    assert stored(bucket["s3"]) == []
    assert "pendingAvatarKey" not in profile(bucket["social"], ADMIN)


def test_confirming_before_the_photo_arrived_says_try_again(bucket):
    _, started = call("POST", "/api/v1/me/avatar")
    status, answer = call("POST", f"/api/v1/me/avatar/{started['avatarId']}/complete")
    assert (status, answer["code"]) == (409, "try_again")


def test_nobody_can_confirm_someone_elses_photo_as_their_own(bucket):
    avatar_id, key = upload(bucket["s3"], email=HELPER)
    status, answer = call("POST", f"/api/v1/me/avatar/{avatar_id}/complete")
    assert (status, answer["code"]) == (409, "try_again")
    assert "pendingAvatarKey" not in profile(bucket["social"], ADMIN)
    assert stored(bucket["s3"]) == [key]  # and theirs is untouched


def test_a_replaced_photo_is_removed_but_the_published_one_stays_until_then(bucket):
    s3 = bucket["s3"]
    first_id, first = upload(s3)
    call("POST", f"/api/v1/me/avatar/{first_id}/complete")
    bucket["stream"].settle()  # first is published

    second_id, second = upload(s3)
    upload(s3)  # sent, never confirmed
    call("POST", f"/api/v1/me/avatar/{second_id}/complete")
    # Everyone still sees the first; the second waits; the stray is gone.
    assert stored(s3) == sorted([first, second])
    bucket["stream"].settle()
    assert profile(bucket["social"], ADMIN)["avatarKey"] == second

    third_id, third = upload(s3)
    call("POST", f"/api/v1/me/avatar/{third_id}/complete")
    assert stored(s3) == sorted([second, third])  # the first, at last


def test_removing_the_photo_removes_every_version_of_it(bucket):
    s3 = bucket["s3"]
    avatar_id, key = upload(s3)
    call("POST", f"/api/v1/me/avatar/{avatar_id}/complete")
    bucket["stream"].settle()
    s3.put_object(Bucket=BUCKET, Key=key, Body=picture())  # a second version
    _, other = upload(s3, email=HELPER)

    status, me = call("DELETE", "/api/v1/me/avatar")
    assert (status, me["avatar"], me["avatarPending"]) == (200, None, False)
    assert "avatarKey" not in profile(bucket["social"], ADMIN)
    assert stored(s3) == [other]  # nobody else's photo was touched
    # A photo removed while it waited is not published afterwards.
    bucket["stream"].settle()
    assert "avatarKey" not in profile(bucket["social"], ADMIN)


def test_five_photos_a_day_and_the_terms_first(bucket, monkeypatch):
    monkeypatch.setattr(handler, "AVATAR_CHANGES_PER_DAY", 1)
    assert call("POST", "/api/v1/me/avatar")[0] == 200
    status, answer = call("POST", "/api/v1/me/avatar")
    assert (status, answer["code"]) == (429, "rate_limited")
    monkeypatch.setattr(handler, "TERMS_VERSION", "2027-01")  # new terms
    status, answer = call("POST", "/api/v1/me/avatar", email=HELPER)
    assert (status, answer["code"]) == (403, "terms_required")


# ------------------------------------------------------------ the username


def lookup(table, username):
    return table.get_item(Key={"PK": f"USERNAME#{username}", "SK": "META"}).get("Item")


def test_a_new_username_takes_the_place_of_the_old_one(people):
    social = people["social"]
    before = profile(social, ADMIN)
    status, me = call("PUT", "/api/v1/me/username", {"username": "  Sasha.Cats "})
    assert (status, me["username"]) == (200, "sasha.cats")  # lower case, trimmed
    assert profile(social, ADMIN)["username"] == "sasha.cats"
    assert lookup(social, "sasha.cats")["userId"] == before["userId"]
    assert lookup(social, before["username"]) is None  # free for someone else
    # The same name again is no change, and costs nothing.
    assert call("PUT", "/api/v1/me/username", {"username": "sasha.cats"})[0] == 200


def test_a_name_someone_holds_is_refused_and_nothing_changes(people):
    social = people["social"]
    theirs = profile(social, HELPER)["username"]
    mine = profile(social, ADMIN)["username"]
    status, answer = call("PUT", "/api/v1/me/username", {"username": theirs.upper()})
    assert (status, answer["code"]) == (409, "name_taken")
    assert profile(social, ADMIN)["username"] == mine
    assert lookup(social, mine) and lookup(social, theirs)["userId"] != lookup(social, mine)["userId"]


def test_the_name_given_up_can_be_taken_by_someone_else(people):
    old = profile(people["social"], ADMIN)["username"]
    call("PUT", "/api/v1/me/username", {"username": "moved.on"})
    status, me = call("PUT", "/api/v1/me/username", {"username": old}, email=HELPER)
    assert (status, me["username"]) == (200, old)


@pytest.mark.parametrize(
    "name",
    ["ab", "x" * 21, "has space", "émile", "semi;colon", ".dot", "dot.", "a..b", "a._b", 7, None],
)
def test_a_username_outside_the_rule_is_refused(people, name):
    before = profile(people["social"], ADMIN)
    status, answer = call("PUT", "/api/v1/me/username", {"username": name})
    assert (status, answer["code"]) == (400, "bad_username")
    assert profile(people["social"], ADMIN) == before


@pytest.mark.parametrize("name", ["admin", "BGUcats", "moderator"])
def test_a_name_that_would_read_as_the_app_is_never_given(people, name):
    status, answer = call("PUT", "/api/v1/me/username", {"username": name})
    assert (status, answer["code"]) == (409, "name_taken")
    assert lookup(people["social"], name.lower()) is None


def test_a_few_username_tries_a_day_and_the_terms_first(people, monkeypatch):
    monkeypatch.setattr(handler, "USERNAME_CHANGES_PER_DAY", 1)
    assert call("PUT", "/api/v1/me/username", {"username": "first.one"})[0] == 200
    status, answer = call("PUT", "/api/v1/me/username", {"username": "second.one"})
    assert (status, answer["code"]) == (429, "rate_limited")
    assert profile(people["social"], ADMIN)["username"] == "first.one"
    monkeypatch.setattr(handler, "TERMS_VERSION", "2027-01")
    status, answer = call("PUT", "/api/v1/me/username", {"username": "early"}, email=HELPER)
    assert (status, answer["code"]) == (403, "terms_required")
