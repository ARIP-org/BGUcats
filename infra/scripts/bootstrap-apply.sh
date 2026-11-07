#!/usr/bin/env bash
# Plans and applies infra/bootstrap: the deploy and CI roles, the Lambda
# boundary, the state backend. The one Terraform root a person applies
# (infra/README.md). Run it from a checkout of the branch that changes
# bootstrap, before merging that branch:
#
#   aws sso login --profile bgucats-prod-admin --use-device-code
#   infra/scripts/bootstrap-apply.sh
#   aws sso logout
#
# For staging: AWS_PROFILE=bgucats-staging-admin infra/scripts/bootstrap-apply.sh
#
# - An SSO profile and its environment's account, or nothing runs
#   (aws-guard.sh). The profile defaults to bgucats-prod-admin; a
#   bgucats-staging-* profile means staging, and sets var.environment.
# - The state is local, one file per account
#   (infra/bootstrap/state/<account>.tfstate). Its copy in the account's
#   state bucket is how another machine finds it. Whichever of the two is
#   newer (by serial) is used; two different lineages stop the run.
# - --first is for an account with no bootstrap yet: no state anywhere, the
#   budget address given, and a plan that only creates. Without --first, no
#   state stops the run; with it, any state does.
# - The budget alerts' address (TF_VAR_budget_alert_email) is taken from
#   the state unless it is set; a value that is not one address stops it.
# - Any destroy or replace stops the run before anything is applied.
# - Otherwise it lists every change and applies only after you type "yes",
#   exactly the plan it showed, then puts the new state in the bucket
#   (versioned, so every earlier state stays there).
set -euo pipefail
cd "$(dirname "$0")/../.."

first=""
case "${1:-}" in
  --first) first=yes ;;
  "") ;;
  *)
    echo "usage: $0 [--first]" >&2
    exit 1
    ;;
esac

export AWS_PROFILE="${AWS_PROFILE:-bgucats-prod-admin}"
case "$AWS_PROFILE" in
  bgucats-staging-*) environment=staging ;;
  *) environment=production ;;
esac
export BGUCATS_ENV="$environment" TF_VAR_environment="$environment"
infra/scripts/aws-guard.sh
account=$(aws sts get-caller-identity --query Account --output text)

ROOT=infra/bootstrap
mkdir -p "$ROOT/state"
LOCAL="$ROOT/state/$account.tfstate"
# Before 2026-11-07 there was one account and one file,
# infra/bootstrap/terraform.tfstate. If it is this account's, it moves.
OLD="$ROOT/terraform.tfstate"
if [ ! -f "$LOCAL" ] && [ -f "$OLD" ] &&
  jq -e --arg b "bgucats-tfstate-$account" '[.. | .bucket? // empty] | index($b)' "$OLD" >/dev/null; then
  mv "$OLD" "$LOCAL"
  echo "Moved $OLD to $LOCAL."
fi
BUCKET="bgucats-tfstate-$account"
KEY=bootstrap/terraform.tfstate
REMOTE="s3://$BUCKET/$KEY"
PLAN="$ROOT/bootstrap.tfplan"
work=$(mktemp -d)
trap 'rm -rf "$work" "$PLAN"' EXIT

echo "== State"
# Only "not there" counts as no copy; any other error stops the run, so
# a failed read can never make an older local state look current.
if head=$(aws s3api head-object --bucket "$BUCKET" --key "$KEY" 2>&1); then
  aws s3 cp --quiet "$REMOTE" "$work/remote.tfstate"
  remote_serial=$(jq .serial "$work/remote.tfstate")
elif grep -qE "Not Found|404" <<<"$head"; then
  remote_serial=""
else
  echo "$head" >&2
  exit 1
fi
if [ -n "$first" ]; then
  if [ -f "$LOCAL" ] || [ -n "$remote_serial" ]; then
    echo "--first, but this account already has a bootstrap state ($LOCAL or $REMOTE). Stopping." >&2
    exit 1
  fi
  if [ -z "${TF_VAR_budget_alert_email:-}" ]; then
    echo "--first needs the budget alerts' address: export TF_VAR_budget_alert_email=..." >&2
    exit 1
  fi
  echo "No state yet: a first bootstrap of account $account ($environment)."
elif [ -f "$LOCAL" ]; then
  local_serial=$(jq .serial "$LOCAL")
  if [ -n "$remote_serial" ]; then
    if [ "$(jq -r .lineage "$LOCAL")" != "$(jq -r .lineage "$work/remote.tfstate")" ]; then
      echo "The local state and the bucket's copy are different lineages. Stopping." >&2
      exit 1
    fi
    if [ "$remote_serial" -gt "$local_serial" ]; then
      cp "$LOCAL" "$LOCAL.older-local-copy"
      cp "$work/remote.tfstate" "$LOCAL"
      echo "Using the bucket's copy (serial $remote_serial; the local serial $local_serial is kept as $LOCAL.older-local-copy)."
    else
      echo "Using the local state (serial $local_serial; the bucket has $remote_serial)."
    fi
  else
    echo "Using the local state (serial $local_serial; the bucket has no copy yet)."
  fi
elif [ -n "$remote_serial" ]; then
  cp "$work/remote.tfstate" "$LOCAL"
  echo "Using the bucket's copy (serial $remote_serial)."
else
  echo "No bootstrap state, local or in $REMOTE." >&2
  echo "For an account that has never been bootstrapped: $0 --first" >&2
  exit 1
fi

# The budget alerts' address is not kept in the repo. Unless it is given,
# keep the one in the state. Anything that is not one address stops the
# run: on 2026-11-07 a pasted command split across two lines put the whole
# state file in this variable, and the plan wanted to "update" the budget.
if [ -z "${TF_VAR_budget_alert_email:-}" ]; then
  TF_VAR_budget_alert_email=$(jq -r '[.. | .subscriber_email_addresses? // empty | .[]] | first // empty' "$LOCAL")
  export TF_VAR_budget_alert_email
  echo "Budget alerts: the state's address."
fi
if ! [[ "$TF_VAR_budget_alert_email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  echo "TF_VAR_budget_alert_email is not one email address. Unset it to keep the state's." >&2
  exit 1
fi

echo
echo "== Plan"
terraform -chdir="$ROOT" init -input=false -reconfigure \
  -backend-config="path=state/$account.tfstate" >/dev/null
terraform -chdir="$ROOT" plan -input=false -out="$(basename "$PLAN")" >"$work/plan.txt" ||
  { cat "$work/plan.txt"; exit 1; }
terraform -chdir="$ROOT" show -json "$(basename "$PLAN")" >"$work/plan.json"

jq -r '(.resource_changes // [])[] | select(.mode == "managed" and .change.actions != ["no-op"])
  | "  \(.change.actions | join("+"))\t\(.address)"' "$work/plan.json" >"$work/changes.txt"
if [ ! -s "$work/changes.txt" ]; then
  echo "No changes: bootstrap already matches this branch."
  exit 0
fi
terraform -chdir="$ROOT" show -no-color "$(basename "$PLAN")"
echo
echo "Changes:"
cat "$work/changes.txt"
if [ -n "$first" ] && grep -qv $'^  create\t' "$work/changes.txt"; then
  echo
  echo "--first, but the plan does more than create. Nothing applied." >&2
  exit 1
fi
if grep -q delete "$work/changes.txt"; then
  echo
  echo "The plan destroys or replaces something. Nothing applied." >&2
  echo "Read it with: terraform -chdir=$ROOT plan" >&2
  exit 1
fi

echo
read -r -p "Apply the $(wc -l <"$work/changes.txt") change(s) above to account $account ($environment)? Type yes: " answer
if [ "$answer" != yes ]; then
  echo "Nothing applied."
  exit 1
fi
terraform -chdir="$ROOT" apply -input=false "$(basename "$PLAN")"

echo
echo "== Saving the state to the bucket"
aws s3 cp --quiet "$LOCAL" "$REMOTE"
echo "Saved: $REMOTE (serial $(jq .serial "$LOCAL"))"
