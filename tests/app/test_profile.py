"""Changing who you are (B1): `PATCH /me`. A new display name is its
owner's at once and everyone's once it has been checked, which the events
Lambda does; the settings are simply stored."""

import pytest

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
