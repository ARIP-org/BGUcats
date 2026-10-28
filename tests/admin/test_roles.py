"""Admin vs collaborator — what each role can reach through the API."""

import pytest

import tests.admin.test_handler  # noqa: F401  (sets the env the handler reads)
from admin import handler
from tests.admin.test_handler import ADMIN, SESSION, _call, _photo, aws  # noqa: F401

HELPER = "helper@example.com"
OTHER_HELPER = "other-helper@example.com"


@pytest.fixture
def people(aws):  # noqa: F811
    for email in (HELPER, OTHER_HELPER):
        aws["table"].put_item(
            Item={
                "PK": f"ADMIN#{email}",
                "SK": "META",
                "email": email,
                "role": "collaborator",
                "GSI2PK": "ENTITY#ADMIN",
                "GSI2SK": email,
            }
        )
    aws["table"].put_item(
        Item={
            "PK": f"SESSION#{SESSION}",
            "SK": "META",
            "sessionId": SESSION,
            "startedAt": "2026-08-24T11:00:00.000000Z",
        }
    )
    _photo(aws, "01PHOTO00000000000000000A1")
    status, cat = _call("POST", "/api/cats", {"name": "Ryzhik"})
    assert status == 200
    return {**aws, "cat": cat["catId"]}


def test_me_reports_the_role(people):
    assert _call("GET", "/api/me", email=HELPER)[1] == {
        "email": HELPER,
        "role": "collaborator",
    }


def test_an_item_without_a_role_is_an_admin(people):
    # The Terraform bootstrap item and `make admin-add` write no role.
    assert _call("GET", "/api/me")[1]["role"] == "admin"


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/insights", None),
        ("POST", "/api/cats", {"name": "Someone new"}),
        (
            "POST",
            "/api/sessions/merge",
            {"sourceSessionId": "A", "targetSessionId": "B"},
        ),
        ("POST", f"/api/sessions/{SESSION}/reject", None),
        ("POST", "/api/photos/01PHOTO00000000000000000A1/reject", None),
        ("GET", "/api/admins", None),
        ("POST", "/api/admins", {"email": "x@example.com"}),
        ("POST", "/api/links", {"slug": "poster", "label": "Poster"}),
    ],
)
def test_collaborators_cannot_delete_merge_name_or_manage(people, method, path, body):
    status, data = _call(method, path, body, email=HELPER)
    assert status == 403
    assert data["error"] == "only admins can do this"


def test_refused_reject_leaves_the_photo_alone(people):
    _call("POST", f"/api/sessions/{SESSION}/reject", email=HELPER)
    photo = people["table"].get_item(
        Key={"PK": "PHOTO#01PHOTO00000000000000000A1", "SK": "META"}
    )
    assert "Item" in photo


def test_collaborators_cannot_rename_or_delete_a_cat(people):
    cat = people["cat"]
    assert _call("PATCH", f"/api/cats/{cat}", {"name": "X"}, email=HELPER)[0] == 403
    assert _call("DELETE", f"/api/cats/{cat}", email=HELPER)[0] == 403


def test_collaborators_browse_the_cats(people):
    assert _call("GET", "/api/cats", email=HELPER)[0] == 200
    assert _call("GET", f"/api/cats/{people['cat']}", email=HELPER)[0] == 200


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/queue", None),
        ("GET", "/api/stats", None),
        ("GET", f"/api/sessions/{SESSION}", None),
        ("POST", f"/api/sessions/{SESSION}/assign", {"catId": "X"}),
        ("POST", f"/api/sessions/{SESSION}/unassign", None),
    ],
)
def test_labeling_stays_with_admins(people, method, path, body):
    assert _call(method, path, body, email=HELPER)[0] == 403


def test_a_refused_assign_labels_nothing(people):
    _call(
        "POST",
        f"/api/sessions/{SESSION}/assign",
        {"catId": people["cat"]},
        email=HELPER,
    )
    session = people["table"].get_item(Key={"PK": f"SESSION#{SESSION}", "SK": "META"})
    assert "catId" not in session["Item"] or session["Item"]["catId"] is None


def test_people_are_added_as_collaborators_unless_said_otherwise(people):
    status, data = _call("POST", "/api/admins", {"email": "New@Example.com"})
    assert status == 200
    assert data == {"email": "new@example.com", "role": "collaborator"}

    status, data = _call(
        "POST", "/api/admins", {"email": "boss@example.com", "role": "admin"}
    )
    assert data["role"] == "admin"

    roles = {a["email"]: a["role"] for a in _call("GET", "/api/admins")[1]["admins"]}
    assert roles["new@example.com"] == "collaborator"
    assert roles["boss@example.com"] == "admin"


def test_unknown_role_is_refused(people):
    status, _ = _call(
        "POST", "/api/admins", {"email": "a@example.com", "role": "owner"}
    )
    assert status == 400


def test_role_can_be_changed_but_not_your_own(people):
    status, data = _call("PATCH", f"/api/admins/{HELPER}", {"role": "admin"})
    assert status == 200 and data["role"] == "admin"
    assert _call("GET", "/api/me", email=HELPER)[1]["role"] == "admin"

    status, _ = _call("PATCH", f"/api/admins/{ADMIN}", {"role": "collaborator"})
    assert status == 409


def test_changing_the_role_of_nobody_is_a_404(people):
    status, _ = _call("PATCH", "/api/admins/ghost@example.com", {"role": "admin"})
    assert status == 404


def test_a_demoted_admin_loses_admin_routes_on_the_next_call(people):
    _call("POST", "/api/admins", {"email": "temp@example.com", "role": "admin"})
    assert _call("GET", "/api/insights", email="temp@example.com")[0] == 200
    _call("PATCH", "/api/admins/temp@example.com", {"role": "collaborator"})
    assert _call("GET", "/api/insights", email="temp@example.com")[0] == 403


def test_strangers_are_still_refused(people):
    assert _call("GET", "/api/me", email="stranger@example.com")[0] == 403


def test_every_route_declares_who_may_call_it():
    assert all(
        access in (handler.ANYONE, handler.ADMINS) for *_, access in handler.ROUTES
    )
