"""Fails when a Terraform plan holds something that could cost real money.

    terraform -chdir=infra/main show -json tfplan \
      | python scripts/check_plan.py infra/main/allowed-resource-types.txt

Two checks on the plan's JSON, read from stdin:

1. Every managed resource is of a kind on the allowlist. A new kind is a
   decision for the owner (infra/main/allowed-resource-types.txt says what
   it takes), so a pull request that adds one goes red instead of being
   read past in a long plan.
2. The few settings that turn a cheap resource into an expensive one stay
   where they are: the table bills per request, and no Lambda is sized far
   beyond what this app needs. AWS has no switch for these (DynamoDB has
   no condition key for a table's billing mode), so this is where they are
   held.

This is the early, readable warning. What actually stops a deploy is in
AWS: the deploy role can create only what infra/bootstrap lets it, and the
organization's allowlist denies every other service (infra/org).

Only addresses and setting names are printed, never values: a plan's JSON
holds sensitive values in clear text.
"""

import json
import sys
from pathlib import Path

# Today's largest: process at 1024 MB and 60 s. Room to grow, not to run away.
MAX_LAMBDA_MEMORY_MB = 2048
MAX_LAMBDA_TIMEOUT_S = 120


def load_allowlist(path):
    lines = Path(path).read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def _over(value, limit):
    # A value Terraform cannot know until apply is absent from the plan;
    # only a number at or under the limit passes.
    return not isinstance(value, int | float) or value > limit


def violations(plan, allowed):
    """One message per problem, in the plan's order."""
    found = []
    for change in plan.get("resource_changes") or []:
        if change.get("mode") != "managed":
            continue
        address, kind = change["address"], change["type"]
        after = (change.get("change") or {}).get("after")
        if after is None:  # being destroyed: nothing left to cost anything
            continue
        if kind not in allowed:
            found.append(f"{address}: `{kind}` is not an allowed resource type")
            continue
        if (
            kind == "aws_dynamodb_table"
            and after.get("billing_mode") != "PAY_PER_REQUEST"
        ):
            found.append(f"{address}: billing_mode must be PAY_PER_REQUEST")
        if kind == "aws_lambda_function":
            if _over(after.get("memory_size"), MAX_LAMBDA_MEMORY_MB):
                found.append(
                    f"{address}: memory_size must be at most {MAX_LAMBDA_MEMORY_MB}"
                )
            if _over(after.get("timeout"), MAX_LAMBDA_TIMEOUT_S):
                found.append(
                    f"{address}: timeout must be at most {MAX_LAMBDA_TIMEOUT_S}"
                )
    return found


def main(argv):
    if len(argv) != 2:
        print(
            f"usage: {argv[0]} <allowed-resource-types.txt>  (plan JSON on stdin)",
            file=sys.stderr,
        )
        return 2
    found = violations(json.load(sys.stdin), load_allowlist(argv[1]))
    if not found:
        print(
            "Plan check: every resource is of an allowed kind, within the cost limits."
        )
        return 0
    for message in found:
        print(f"::error::{message}")
    print(
        f"\nPlan check failed ({len(found)}). This plan adds a new kind of resource or lifts a "
        f"cost limit.\nThat is the owner's decision, not a fix to make in this pull request: "
        f"see {argv[1]}."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
