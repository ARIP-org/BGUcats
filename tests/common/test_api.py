"""common.api: the pieces every API Lambda answers with."""

import json
from decimal import Decimal

import pytest

from common import api, ids


def gateway(claims=None, body=None):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": claims or {}}}},
        "body": body,
    }


def test_the_caller_is_the_tokens_email_lowercased():
    assert (
        api.caller_email(gateway({"email": "  Someone@Example.COM "}))
        == "someone@example.com"
    )
    with pytest.raises(api.ApiError) as err:
        api.caller_email(gateway({}))
    assert err.value.status == 401


def test_numbers_from_dynamodb_come_out_as_json_numbers():
    body = json.loads(api.response(200, {"a": Decimal(3), "b": Decimal("1.5")})["body"])
    assert body == {"a": 3, "b": 1.5}


@pytest.mark.parametrize(("raw", "status"), [("{", 400), ("[1]", 400)])
def test_a_body_must_be_a_json_object(raw, status):
    with pytest.raises(api.ApiError) as err:
        api.parse_body(gateway(body=raw))
    assert err.value.status == status
    assert api.parse_body(gateway(body=None)) == {}


def test_a_new_id_is_a_ulid_the_routes_accept():
    new = ids.new_ulid()
    assert api.ulid_param({"id": new}, "id") == new
    with pytest.raises(api.ApiError):
        api.ulid_param({"id": new.lower()}, "id")


def test_routes_match_first_and_tell_404_from_405():
    def a():
        pass

    def b():
        pass

    routes = (
        ("POST", r"^/x/special$", a, "admins"),
        ("GET", r"^/x/(?P<x_id>[A-Z]+)$", b, "anyone"),
    )
    assert api.match_route(routes, "POST", "/x/special/") == (a, {}, "admins")
    assert api.match_route(routes, "GET", "/x/ABC") == (b, {"x_id": "ABC"}, "anyone")
    with pytest.raises(api.ApiError) as err:
        api.match_route(routes, "DELETE", "/x/ABC")
    assert err.value.status == 405
    with pytest.raises(api.ApiError) as err:
        api.match_route(routes, "GET", "/y")
    assert err.value.status == 404


def test_an_error_carries_a_code_and_details_only_when_given():
    plain = api.ApiError(400, "no")
    assert (plain.code, plain.details) == (None, {})
    rich = api.ApiError(429, "later", code="rate_limited", details={"retryAfter": 5})
    assert (rich.code, rich.details) == ("rate_limited", {"retryAfter": 5})
