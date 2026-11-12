"""src/events/filters.json: what reaches the events Lambda.

The patterns are Lambda's event filtering, applied by AWS before the
function runs. This file evaluates the part of that syntax the patterns
use (a list of exact strings or {"prefix": ...}, all fields must match, any
pattern may) so that two things are checked here and not in production:

- every kind the handler knows reaches it;
- nothing the handler writes reaches it, or it would start itself again,
  for ever, at the price of every invocation.
"""

import json
from pathlib import Path

import pytest

from events import handler

FILTERS = json.loads((Path(handler.__file__).parent / "filters.json").read_text())
PATTERNS = FILTERS["patterns"]


def _matches(rule, value):
    for option in rule:
        if isinstance(option, str) and value == option:
            return True
        if (
            isinstance(option, dict)
            and set(option) == {"prefix"}
            and value.startswith(option["prefix"])
        ):
            return True
    return False


def _pattern_matches(pattern, record):
    if isinstance(pattern, list):
        return isinstance(record, str) and _matches(pattern, record)
    if not isinstance(record, dict):
        return False
    return all(
        key in record and _pattern_matches(sub, record[key])
        for key, sub in pattern.items()
    )


def admitted(pk, sk):
    record = {"dynamodb": {"Keys": {"PK": {"S": pk}, "SK": {"S": sk}}}}
    return any(_pattern_matches(p, record) for p in PATTERNS)


def example_sk(sk_match):
    return (
        sk_match
        if sk_match in ("META", "PROFILE")
        else f"{sk_match}01J0000000000000000000000"
    )


def test_at_most_five_patterns():
    # A mapping's default limit; raising it is a quota request.
    assert 1 <= len(PATTERNS) <= 5


def test_the_patterns_only_use_what_this_file_can_evaluate():
    def walk(node):
        if isinstance(node, list):
            for option in node:
                assert isinstance(option, str) or (
                    isinstance(option, dict) and set(option) == {"prefix"}
                ), option
        else:
            assert isinstance(node, dict)
            for sub in node.values():
                walk(sub)

    for pattern in PATTERNS:
        assert set(pattern) == {"dynamodb"}
        walk(pattern)


@pytest.mark.parametrize(("pk_prefix", "sk_match", "kind"), handler.KINDS)
def test_every_kind_the_handler_knows_reaches_it(pk_prefix, sk_match, kind):
    pk, sk = f"{pk_prefix}01J0000000000000000000000", example_sk(sk_match)
    assert admitted(pk, sk), kind
    assert handler.kind_of(pk, sk) == kind


@pytest.mark.parametrize(("pk", "sk"), handler.SELF_WRITTEN)
def test_nothing_the_handler_writes_reaches_it(pk, sk):
    assert not admitted(pk, sk)
    assert handler.kind_of(pk, sk) is None


@pytest.mark.parametrize(
    ("pk", "sk"),
    [
        ("IDENTITY#someone@example.com", "META"),
        ("USERNAME#maya", "META"),
        ("INVITE#abc", "META"),
        ("PHONE#ab12", "META"),
        ("REPORTED#post#01J", "BY#u"),
        ("POST#01J", "METADATA"),  # an exact match, not a prefix
        ("CAT#01J", "GRADE#u"),
    ],
)
def test_bookkeeping_items_do_not_reach_it(pk, sk):
    assert not admitted(pk, sk)


def test_the_matcher_itself_tells_apart():
    # Worth its silence only if it can say yes and no.
    assert admitted("POST#X", "META")
    assert not admitted("POST#X", "META2")
    assert not admitted("XPOST#X", "META")
