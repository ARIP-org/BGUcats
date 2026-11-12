"""The member API's role reads the dataset and never writes it
(infra/main/app_api.tf; docs/app-plan/README.md, rule 7).

Read from the Terraform itself, so a statement added later that would let
the member API write bgucats-data fails here, in the pull request, rather
than being noticed in a review of a long plan.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TF = (REPO / "infra" / "main" / "app_api.tf").read_text()
READS = {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"}


def statements():
    start = TF.index('resource "aws_iam_role_policy" "app_lambda_access"')
    end = TF.find('\nresource "', start + 1)
    block = TF[start : end if end != -1 else None]
    parts = re.split(r"\n\s*\{\s*\n", block)[1:]
    found = []
    for part in parts:
        sid = re.search(r'Sid\s*=\s*"([^"]+)"', part)
        if not sid:
            continue
        actions = set(re.findall(r'"(dynamodb:[A-Za-z*]+|[a-z0-9-]+:\*|\*)"', part))
        found.append((sid.group(1), actions, part))
    return found


def test_the_policy_is_read():
    sids = {sid for sid, _, _ in statements()}
    assert {"ReadTheDataset", "SocialItems"} <= sids


def test_every_statement_on_the_dataset_only_reads():
    on_dataset = [
        (sid, acts)
        for sid, acts, text in statements()
        if "aws_dynamodb_table.data" in text
    ]
    assert on_dataset, (
        "no statement names the dataset: the check would pass for nothing"
    )
    for sid, actions in on_dataset:
        assert actions <= READS, (
            f"{sid} lets the member API do {sorted(actions - READS)} on bgucats-data"
        )


def test_no_statement_reaches_a_table_by_wildcard():
    for sid, actions, text in statements():
        assert not any(a in ("*", "dynamodb:*") for a in actions), sid
        assert 'Resource = "*"' not in text or not any(
            a.startswith("dynamodb:") for a in actions
        ), sid


def test_the_writes_are_on_the_social_table():
    for sid, actions, text in statements():
        if actions - READS:
            assert (
                "aws_dynamodb_table.social" in text
                and "aws_dynamodb_table.data" not in text
            ), sid
