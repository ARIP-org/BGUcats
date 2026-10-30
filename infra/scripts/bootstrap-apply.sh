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
# - Production's account and an SSO profile, or nothing runs
#   (aws-guard.sh). The profile defaults to bgucats-prod-admin.
# - The state is local (infra/bootstrap/terraform.tfstate). Its copy in
#   the state bucket is how another machine finds it. Whichever of the two
#   is newer (by serial) is used; two different lineages stop the run.
# - Any destroy or replace stops the run before anything is applied.
# - Otherwise it lists every change and applies only after you type "yes",
#   exactly the plan it showed, then puts the new state in the bucket
#   (versioned, so every earlier state stays there).
set -euo pipefail
cd "$(dirname "$0")/../.."

export AWS_PROFILE="${AWS_PROFILE:-bgucats-prod-admin}"
infra/scripts/aws-guard.sh
account=$(aws sts get-caller-identity --query Account --output text)

ROOT=infra/bootstrap
LOCAL="$ROOT/terraform.tfstate"
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
if [ -f "$LOCAL" ]; then
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
  echo "A first bootstrap of an empty account is docs/MANUAL_STEPS.md 6b, not this script." >&2
  exit 1
fi

echo
echo "== Plan"
terraform -chdir="$ROOT" init -input=false >/dev/null
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
if grep -q delete "$work/changes.txt"; then
  echo
  echo "The plan destroys or replaces something. Nothing applied." >&2
  echo "Read it with: terraform -chdir=$ROOT plan" >&2
  exit 1
fi

echo
read -r -p "Apply the $(wc -l <"$work/changes.txt") change(s) above to account $account? Type yes: " answer
if [ "$answer" != yes ]; then
  echo "Nothing applied."
  exit 1
fi
terraform -chdir="$ROOT" apply -input=false "$(basename "$PLAN")"

echo
echo "== Saving the state to the bucket"
aws s3 cp --quiet "$LOCAL" "$REMOTE"
echo "Saved: $REMOTE (serial $(jq .serial "$LOCAL"))"
