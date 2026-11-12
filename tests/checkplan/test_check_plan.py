"""The plan check (scripts/check_plan.py): a new kind of resource or a lifted
cost limit fails; everything infra/main has today passes."""

import io
import json
import re
from pathlib import Path

import pytest

import check_plan as c

REPO = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO / "infra/main/allowed-resource-types.txt"
ALLOWED = c.load_allowlist(ALLOWLIST)


def change(kind, after, name="x", mode="managed"):
    return {
        "address": f"{kind}.{name}",
        "type": kind,
        "mode": mode,
        "change": {"after": after},
    }


def plan(*changes):
    return {"resource_changes": list(changes)}


TABLE = change("aws_dynamodb_table", {"billing_mode": "PAY_PER_REQUEST"})
FUNCTION = change("aws_lambda_function", {"memory_size": 1024, "timeout": 60})


def test_the_allowlist_is_exactly_what_infra_main_declares():
    declared = set()
    for tf in (REPO / "infra/main").glob("*.tf"):
        declared |= set(
            re.findall(r'^resource "([a-z0-9_]+)"', tf.read_text(), re.MULTILINE)
        )
    assert declared == ALLOWED


def test_todays_shapes_pass():
    assert c.violations(plan(TABLE, FUNCTION), ALLOWED) == []


def test_empty_plan_passes():
    assert c.violations({}, ALLOWED) == []
    assert c.violations({"resource_changes": None}, ALLOWED) == []


@pytest.mark.parametrize(
    "kind", ["aws_db_instance", "aws_nat_gateway", "aws_instance", "aws_vpc"]
)
def test_a_new_kind_of_resource_fails(kind):
    found = c.violations(plan(TABLE, change(kind, {})), ALLOWED)
    assert found == [f"{kind}.x: `{kind}` is not an allowed resource type"]


def test_a_destroy_is_not_a_cost():
    # An unlisted kind on its way out (after is null) must not block its own removal.
    assert c.violations(plan(change("aws_db_instance", None)), ALLOWED) == []


def test_data_sources_are_not_resources():
    assert c.violations(plan(change("aws_ami", {}, mode="data")), ALLOWED) == []


@pytest.mark.parametrize("after", [{"billing_mode": "PROVISIONED"}, {}])
def test_a_provisioned_table_fails(after):
    # Omitted means PROVISIONED to AWS, so absent fails too.
    found = c.violations(plan(change("aws_dynamodb_table", after)), ALLOWED)
    assert found == ["aws_dynamodb_table.x: billing_mode must be PAY_PER_REQUEST"]


@pytest.mark.parametrize(
    ("after", "setting"),
    [
        ({"memory_size": 10240, "timeout": 60}, "memory_size"),
        ({"memory_size": 1024, "timeout": 900}, "timeout"),
        (
            {"timeout": 60},
            "memory_size",
        ),  # unknown until apply: not provably within the limit
    ],
)
def test_an_oversized_lambda_fails(after, setting):
    found = c.violations(plan(change("aws_lambda_function", after)), ALLOWED)
    assert len(found) == 1 and setting in found[0]


def test_the_limits_themselves_pass():
    at_limit = {
        "memory_size": c.MAX_LAMBDA_MEMORY_MB,
        "timeout": c.MAX_LAMBDA_TIMEOUT_S,
    }
    assert c.violations(plan(change("aws_lambda_function", at_limit)), ALLOWED) == []


def test_the_second_table_is_held_to_the_same_billing():
    # docs/app-plan: bgucats-social is a second aws_dynamodb_table, so the
    # rule above covers it by kind, not by name.
    social = change(
        "aws_dynamodb_table", {"billing_mode": "PROVISIONED"}, name="social"
    )
    found = c.violations(plan(TABLE, social), ALLOWED)
    assert found == ["aws_dynamodb_table.social: billing_mode must be PAY_PER_REQUEST"]


# Allowed since infra/main declares one (milestone F3 of docs/app-plan/:
# the events Lambda's feed from the social table's stream).


@pytest.mark.parametrize("config", [[], None])
def test_a_plain_event_source_mapping_passes(config):
    mapping = change(
        "aws_lambda_event_source_mapping",
        {"batch_size": 25, "provisioned_poller_config": config},
    )
    assert c.violations(plan(mapping), ALLOWED) == []


def test_an_event_source_mapping_with_provisioned_pollers_fails():
    mapping = change(
        "aws_lambda_event_source_mapping",
        {"provisioned_poller_config": [{"minimum_pollers": 1, "maximum_pollers": 2}]},
    )
    assert c.violations(plan(mapping), ALLOWED) == [
        "aws_lambda_event_source_mapping.x: provisioned_poller_config must not be set"
    ]


def run(monkeypatch, capsys, the_plan):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(the_plan)))
    code = c.main(["check_plan.py", str(ALLOWLIST)])
    return code, capsys.readouterr().out


def test_main_passes_and_fails(monkeypatch, capsys):
    assert run(monkeypatch, capsys, plan(TABLE, FUNCTION))[0] == 0
    code, out = run(
        monkeypatch, capsys, plan(change("aws_db_instance", {"password": "hunter2"}))
    )
    assert code == 1
    assert "::error::aws_db_instance.x" in out
    assert "hunter2" not in out  # values never reach the log


def test_main_needs_the_allowlist_path():
    assert c.main(["check_plan.py"]) == 2
