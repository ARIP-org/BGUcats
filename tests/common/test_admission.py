"""common.admission: two roles, and who the sign-up policy lets in."""

import pytest

from common import admission as a

BGU = ("post.bgu.ac.il", "bgu.ac.il")


@pytest.mark.parametrize(
    ("item", "role"),
    [
        ({}, "admin"),  # no role field: the bootstrap item, make admin-add
        ({"role": "admin"}, "admin"),
        ({"role": "user"}, "user"),
        ({"role": "collaborator"}, "user"),  # the name before 2026-11-12
    ],
)
def test_the_role_an_allowlist_item_gives(item, role):
    assert a.role_of(item) == role


@pytest.mark.parametrize(
    ("value", "role"),
    [
        ("admin", "admin"),
        ("user", "user"),
        ("collaborator", "user"),
        ("boss", None),
        (None, None),
    ],
)
def test_a_requested_role_is_named_as_today(value, role):
    assert a.normalise_role(value) == role


@pytest.mark.parametrize(
    ("policy", "email", "role"),
    [
        ("allowlist", "student@post.bgu.ac.il", None),
        ("domain", "student@post.bgu.ac.il", "user"),
        ("domain", "STAFF@BGU.AC.IL", "user"),
        ("domain", "someone@gmail.com", None),
        ("domain", "x@sub.bgu.ac.il", None),  # only the listed domains, exactly
        ("domain", "bgu.ac.il@gmail.com", None),
        ("open", "someone@gmail.com", "user"),
        ("unknown", "someone@gmail.com", None),  # an unknown policy admits nobody
    ],
)
def test_who_the_policy_admits_when_not_on_the_allowlist(policy, email, role):
    assert a.role_for(email, None, policy, BGU) == role


def test_the_allowlist_admits_under_every_policy_and_decides_the_role():
    for policy in a.POLICIES:
        assert a.role_for("x@gmail.com", {"role": "user"}, policy, ()) == "user"
        assert a.role_for("x@gmail.com", {}, policy, ()) == "admin"


def test_domains_are_read_from_a_comma_list():
    assert a.domains_from(" Post.BGU.ac.il, bgu.ac.il ,") == BGU
    assert a.domains_from(None) == ()
