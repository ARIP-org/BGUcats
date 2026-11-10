#!/usr/bin/env bash
# Plans and applies infra/org: the service control policies, the budget
# actions and cost anomaly detection, all in the organization's management
# account. Run from a checkout of the branch that changes infra/org, before
# merging it (the same order as infra/bootstrap):
#
#   aws sso login --profile mgmt-admin --use-device-code
#   infra/scripts/org-apply.sh --plan     # look only
#   infra/scripts/org-apply.sh            # the same plan, then "yes" applies it
#
# - Only an SSO profile on the management account: mgmt-admin (the
#   default), or mgmt-ro with --plan. The account is checked against the
#   organization itself, not against a number written here.
# - The state is in s3://bgucats-org-tfstate-<account>/ (infra/org/main.tf).
#   The first run makes that bucket: versioned, private.
# - --plan changes nothing and takes no lock, so read-only credentials do.
# - Otherwise it lists every change, destroys first, and applies exactly
#   the plan it showed, only after you type "yes".
set -euo pipefail
cd "$(dirname "$0")/../.."

plan_only=""
case "${1:-}" in
  --plan) plan_only=yes ;;
  "") ;;
  *)
    echo "usage: $0 [--plan]" >&2
    exit 1
    ;;
esac

if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
  echo "org-apply: AWS_ACCESS_KEY_ID is set in this shell, and keys win over any profile." >&2
  echo "  Run: unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" >&2
  exit 1
fi
export AWS_PROFILE="${AWS_PROFILE:-mgmt-admin}"
case "$AWS_PROFILE" in
  mgmt-admin) ;;
  mgmt-ro)
    if [ -z "$plan_only" ]; then
      echo "org-apply: $AWS_PROFILE can only plan. Use --plan, or AWS_PROFILE=mgmt-admin." >&2
      exit 1
    fi
    ;;
  *)
    echo "org-apply: infra/org belongs to the management account: AWS_PROFILE must be mgmt-admin or mgmt-ro, not \"$AWS_PROFILE\"." >&2
    exit 1
    ;;
esac

account=$(aws sts get-caller-identity --query Account --output text)
management=$(aws organizations describe-organization --query Organization.MasterAccountId --output text)
if [ "$account" != "$management" ]; then
  echo "org-apply: profile $AWS_PROFILE is account $account, but the organization's management account is $management." >&2
  exit 1
fi
echo "org-apply: management account $account, profile $AWS_PROFILE"

ROOT=infra/org
BUCKET=$(sed -n 's/^ *bucket *= *"\(bgucats-org-tfstate-[0-9]\{12\}\)".*/\1/p' "$ROOT/main.tf")
if [ "$BUCKET" != "bgucats-org-tfstate-$account" ]; then
  echo "org-apply: $ROOT/main.tf names the state bucket \"$BUCKET\", which is not this account's." >&2
  exit 1
fi

# Only "not there" means make it; any other error stops the run.
if ! head=$(aws s3api head-bucket --bucket "$BUCKET" 2>&1); then
  if ! grep -qE "Not Found|404" <<<"$head"; then
    echo "$head" >&2
    exit 1
  fi
  if [ -n "$plan_only" ]; then
    echo "org-apply: no state bucket yet. The first run is without --plan, as mgmt-admin: it makes $BUCKET." >&2
    exit 1
  fi
  echo "== First run: making the state bucket $BUCKET"
  aws s3api create-bucket --bucket "$BUCKET" --region us-east-1 >/dev/null
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
fi

PLAN=org.tfplan
work=$(mktemp -d)
trap 'rm -rf "$work" "$ROOT/$PLAN"' EXIT

echo
echo "== Plan"
lock=()
[ -z "$plan_only" ] || lock=(-lock=false)
terraform -chdir="$ROOT" init -input=false -reconfigure >/dev/null
terraform -chdir="$ROOT" plan -input=false "${lock[@]}" -out="$PLAN" >"$work/plan.txt" ||
  {
    cat "$work/plan.txt"
    exit 1
  }
terraform -chdir="$ROOT" show -json "$PLAN" >"$work/plan.json"

# Imports with nothing to change are listed too: the first apply is mostly those.
jq -r '[(.resource_changes // [])[] | select(.mode == "managed")
  | {a: ((if .change.importing then ["import"] else [] end)
         + (.change.actions | map(select(. != "no-op"))) | join("+")), r: .address}
  | select(.a != "")]
  | sort_by((.a | contains("delete") | not), .r)[] | "  \(.a)\t\(.r)"' "$work/plan.json" >"$work/changes.txt"
if [ ! -s "$work/changes.txt" ]; then
  echo "No changes: the organization already matches this branch."
  exit 0
fi
terraform -chdir="$ROOT" show -no-color "$PLAN"
echo
echo "Changes:"
cat "$work/changes.txt"
if grep -q delete "$work/changes.txt"; then
  echo
  echo "NOTE: the plan destroys or replaces something (listed first). Read those lines."
fi
if [ -n "$plan_only" ]; then
  echo
  echo "--plan: nothing applied."
  exit 0
fi

echo
read -r -p "Apply the $(wc -l <"$work/changes.txt") change(s) above to the organization (account $account)? Type yes: " answer
if [ "$answer" != yes ]; then
  echo "Nothing applied."
  exit 1
fi
terraform -chdir="$ROOT" apply -input=false "$PLAN"
