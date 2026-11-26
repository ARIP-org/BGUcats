"""What the events Lambda's role may do to the dataset (infra/main/events.tf).

Since #135 (the owner's option 2) the deletion job clears a deleted
person's address from `bgucats-data`: the one thing the events Lambda
writes there. Read from the Terraform and from the job's code, so a field
the job starts clearing that the policy does not allow fails here, not in
an account stuck at that step on staging, and a statement that would let
the role write anything more fails too.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TF = (REPO / "infra" / "main" / "events.tf").read_text()
CODE = (REPO / "src" / "events" / "handler.py").read_text()
ON_DATASET = {
    "DeleteAccountFindInDataset": {"dynamodb:Query"},
    "DeleteAccountReadSessions": {"dynamodb:GetItem"},
    "DeleteAccountClearAddress": {"dynamodb:UpdateItem"},
    "DeleteAccountAllowlistItem": {"dynamodb:DeleteItem"},
}


def statements():
    start = TF.index('resource "aws_iam_role_policy" "events_lambda_access"')
    end = TF.find('\nresource "', start + 1)
    block = TF[start : end if end != -1 else None]
    parts = re.split(r"\n\s*\{\s*\n", block)[1:]
    found = {}
    for part in parts:
        sid = re.search(r'Sid\s*=\s*"([^"]+)"', part)
        if sid:
            actions = set(re.findall(r'"(dynamodb:[A-Za-z*]+)"', part)) - {
                "dynamodb:Attributes",
                "dynamodb:LeadingKeys",
                "dynamodb:ReturnValues",
            }
            found[sid.group(1)] = (actions, part)
    return found


def function(name):
    start = CODE.index(f"\ndef {name}(")
    end = CODE.index("\ndef ", start + 1)
    return CODE[start:end]


def test_the_dataset_is_reached_by_these_four_statements_alone():
    found = statements()
    on_dataset = {
        sid: actions
        for sid, (actions, text) in found.items()
        if "aws_dynamodb_table.data" in text
    }
    assert on_dataset == ON_DATASET


def test_each_reaches_only_what_the_job_needs():
    found = statements()
    # Two indexes, and not the table itself.
    query = found["DeleteAccountFindInDataset"][1]
    assert re.findall(r"aws_dynamodb_table\.data\.arn\}(/index/\w+)", query) == [
        "/index/GSI1",
        "/index/GSI2",
    ]
    assert query.count("aws_dynamodb_table.data.arn") == 2
    sessions = found["DeleteAccountReadSessions"][1]
    assert '"dynamodb:LeadingKeys" = ["SESSION#*"]' in sessions
    allowlist = found["DeleteAccountAllowlistItem"][1]
    assert '"dynamodb:LeadingKeys" = ["ADMIN#*"]' in allowlist
    clear = found["DeleteAccountClearAddress"][1]
    assert '"ForAllValues:StringEquals"' in clear
    assert '"dynamodb:ReturnValues" = ["NONE"]' in clear


def test_the_fields_the_policy_allows_are_the_fields_the_job_clears():
    clear = statements()["DeleteAccountClearAddress"][1]
    listed = re.search(r'"dynamodb:Attributes" = \[(.*?)\]', clear, re.DOTALL)
    allowed = set(re.findall(r'"(\w+)"', listed.group(1)))
    job = function("clear_dataset")
    cleared = set(re.findall(r'_forget_in_dataset\([^)]*"(\w+)", email\)', job))
    session = re.search(r'UpdateExpression="REMOVE (\w+) SET (\w+) = :gone"', job)
    cleared |= set(session.groups())
    assert cleared == {"submittedBy", "pickedBy", "startedBy", "GSI2SK"}
    assert allowed == cleared | {"PK", "SK"}


def test_the_job_clears_on_the_address_and_deletes_only_a_members_item():
    helper = function("_forget_in_dataset")
    assert 'ConditionExpression="#f = :email"' in helper
    job = function("clear_dataset")
    assert 'ConditionExpression="startedBy = :email"' in job
    assert 'ConditionExpression="#r IN (:user, :collaborator)"' in job
    assert 'MEMBER_ROLES = ("user", "collaborator")' in CODE


def test_the_lambda_is_told_which_table_the_dataset_is():
    assert "DATA_TABLE_NAME = aws_dynamodb_table.data.name" in TF
