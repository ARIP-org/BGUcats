#!/usr/bin/env bash
# Stops a hand-run command from acting on the wrong AWS account.
#
# Run before anything that calls AWS from a person's shell (the Makefile's
# AWS targets and infra/scripts/*.sh do). It refuses when:
#   - AWS_ACCESS_KEY_ID is set. Environment keys win over AWS_PROFILE, so a
#     leftover key silently points every command at its own account.
#   - no AWS_PROFILE is set. Every human command names its profile
#     (bgucats-prod-ro, bgucats-prod-admin, ...): docs/codespaces.md.
#   - the profile is for one environment and BGUCATS_ENV names the other.
#   - the credentials belong to an account other than the environment's,
#     which is read from infra/main/backend/<prod|staging>.hcl so there is
#     one place to change it.
# The environment is BGUCATS_ENV ("production" or "staging"). Unset, it
# follows the profile: bgucats-staging-* is staging, anything else is
# production. In GitHub Actions the OIDC role's keys are the environment, so
# only the account check runs there, against BGUCATS_ENV.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

case "${AWS_PROFILE:-}" in
  bgucats-staging-*) profile_env=staging ;;
  bgucats-prod-*) profile_env=production ;;
  *) profile_env="" ;;
esac
env="${BGUCATS_ENV:-${profile_env:-production}}"
case "$env" in
  production) backend=prod ;;
  staging) backend=staging ;;
  *)
    echo "aws-guard: BGUCATS_ENV must be production or staging, not \"$env\"." >&2
    exit 1
    ;;
esac
if [ -n "$profile_env" ] && [ "$profile_env" != "$env" ]; then
  echo "aws-guard: profile $AWS_PROFILE is for $profile_env, but this run is for $env." >&2
  exit 1
fi

expected=$(sed -n 's/^bucket *= *"bgucats-tfstate-\([0-9]\{12\}\)".*/\1/p' "$here/../main/backend/$backend.hcl")
if [ -z "$expected" ]; then
  echo "aws-guard: no account ID in infra/main/backend/$backend.hcl" >&2
  exit 1
fi

if [ -z "${GITHUB_ACTIONS:-}" ]; then
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    echo "aws-guard: AWS_ACCESS_KEY_ID is set in this shell. Long-lived keys win over" >&2
    echo "  any profile. Run: unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" >&2
    exit 1
  fi
  if [ -z "${AWS_PROFILE:-}" ]; then
    echo "aws-guard: name the profile, e.g. PROFILE=bgucats-prod-admin (make) or" >&2
    echo "  AWS_PROFILE=bgucats-prod-admin (scripts). See docs/codespaces.md." >&2
    exit 1
  fi
fi

actual=$(aws sts get-caller-identity --query Account --output text)
if [ "$actual" != "$expected" ]; then
  echo "aws-guard: these credentials are for account $actual; $env is $expected." >&2
  exit 1
fi
echo "aws-guard: $env, account $actual${AWS_PROFILE:+, profile $AWS_PROFILE}" >&2
