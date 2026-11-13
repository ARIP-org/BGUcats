"""What the desk's API may do in the app's table (infra/main/admin_api.tf).

Since B3b it keeps a person's encounter item there (docs/data-model.md,
"ENC"): it reads the sign-in lookup and updates `USER#…` items. Since B6
it reads the new-cat proposals' queue and decides them. Since B4b it reads
a cat's name poll, marks an option removed and locks the shown name. Since
B8b it reads the reports queue, answers a report and marks a post. Since
B8c it lists the app's people. Nothing else.
Read from the Terraform itself, so a wider grant fails here.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TF = (REPO / "infra" / "main" / "admin_api.tf").read_text()


def statements():
    start = TF.index('resource "aws_iam_role_policy" "admin_lambda_access"')
    end = TF.find('\nresource "', start + 1)
    block = TF[start:end]
    return re.split(r"\n      \{\n", block)[1:]


def test_one_statement_reaches_the_app_table():
    on_social = [s for s in statements() if "aws_dynamodb_table.social" in s]
    assert len(on_social) == 1
    (statement,) = on_social
    assert 'Sid    = "EncountersInTheApp"' in statement
    actions = set(re.findall(r"\"(dynamodb:[A-Za-z]+)\",", statement))
    assert actions == {"dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"}
    # The table and the one index the proposals' queue is on; only these
    # partitions. No Put, no Delete: nothing is made or removed there.
    indexes = re.findall(r"/index/([^\"]+)\"", statement)
    assert indexes == ["GSI2"]
    keys = re.search(r'"dynamodb:LeadingKeys" = \[([^\]]*)\]', statement).group(1)
    assert set(re.findall(r'"([^"]+)"', keys)) == {
        "IDENTITY#*",
        "USER#*",
        "PROPOSAL#*",
        "PROPOSALS#*",
        "CAT#*",
        "REPORT#*",
        "REPORTS#*",
        "POST#*",
        "ENTITY#USER",
    }
    assert '"ForAllValues:StringLike"' in statement


def test_the_desk_learns_whether_the_app_is_on():
    lambda_block = TF[TF.index('resource "aws_lambda_function" "admin"') :]
    lambda_block = lambda_block[: lambda_block.index("\n}\n")]
    assert 'SOCIAL            = local.settings.social ? "on" : "off"' in lambda_block
    assert "SOCIAL_TABLE_NAME = aws_dynamodb_table.social.name" in lambda_block
