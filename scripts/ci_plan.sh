#!/usr/bin/env bash
# A read-only plan of infra/main for one environment, the plan check, and a
# short summary of it. CI runs this twice on every pull request
# (.github/workflows/ci.yml): staging is what merging would deploy,
# production is what the next promote would.
#
#   scripts/ci_plan.sh staging
#   scripts/ci_plan.sh production
#
# By hand, with an SSO session and the Lambda packages built (make build):
#
#   AWS_PROFILE=bgucats-staging-ro scripts/ci_plan.sh staging
#
# It changes nothing and takes no lock: the plan runs at the same time as
# Deploy on every merge, and holding the lock could fail either of them.
# It leaves infra/main/<environment>.tfplan (never upload it: a plan holds
# sensitive values in clear text) and plan-summary-<environment>.md, which
# has counts, actions and addresses only. Git ignores both.
set -euo pipefail
cd "$(dirname "$0")/.."

env="${1:-}"
case "$env" in
  production) backend=prod ;;
  staging) backend=staging ;;
  *)
    echo "usage: $0 staging|production" >&2
    exit 1
    ;;
esac

# The credentials must belong to this environment's account, or the plan
# would compare one account's state with another account's resources.
BGUCATS_ENV="$env" infra/scripts/aws-guard.sh

export TF_VAR_environment="$env"
# Not a secret, and the item it names ignores changes: any address does for
# a plan. The bot's secrets and Google's are outside Terraform (ssm.tf).
export TF_VAR_bootstrap_admin_email="${TF_VAR_bootstrap_admin_email:-ci-plan-placeholder@example.com}"

plan="$env.tfplan"
summary="plan-summary-$env.md"

terraform -chdir=infra/main init -input=false -reconfigure -backend-config="backend/$backend.hcl" >/dev/null
terraform -chdir=infra/main plan -input=false -lock=false -out="$plan"

# A new kind of resource, a provisioned table or an oversized Lambda fails
# here: each is a cost decision for the owner (scripts/check_plan.py).
terraform -chdir=infra/main show -json "$plan" |
  python scripts/check_plan.py infra/main/allowed-resource-types.txt

# Destroys sort first: they are what to look for (docs/deploy.md, "Reading
# the plan"). The JSON goes straight into jq and only addresses come out.
{
  terraform -chdir=infra/main show -no-color "$plan" | grep -E '^(Plan:|No changes)' ||
    echo "No summary line in the plan."
  echo
  terraform -chdir=infra/main show -json "$plan" | jq -r '[(.resource_changes // [])[]
    | select(.mode == "managed" and .change.actions != ["no-op"])
    | {a: (.change.actions | join("+")), r: .address}]
    | sort_by((.a | contains("delete") | not), .r)[]
    | "- `\(.a)` `\(.r)`"'
} >"$summary"
