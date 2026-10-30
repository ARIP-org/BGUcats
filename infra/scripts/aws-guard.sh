#!/usr/bin/env bash
# Stops a hand-run command from acting on the wrong AWS account.
#
# Run before anything that calls AWS from a person's shell (the Makefile's
# AWS targets and infra/scripts/*.sh do). It refuses when:
#   - AWS_ACCESS_KEY_ID is set. Environment keys win over AWS_PROFILE, so a
#     leftover key silently points every command at its own account.
#   - no AWS_PROFILE is set. Every human command names its profile
#     (bgucats-prod-ro, bgucats-prod-admin, ...): docs/codespaces.md.
#   - the credentials belong to an account other than production's, which
#     is read from infra/main/backend/prod.hcl so there is one place to
#     change it.
# In GitHub Actions the OIDC role's keys are the environment, so only the
# account check runs there.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
expected=$(sed -n 's/^bucket *= *"bgucats-tfstate-\([0-9]\{12\}\)".*/\1/p' "$here/../main/backend/prod.hcl")
if [ -z "$expected" ]; then
  echo "aws-guard: no account ID in infra/main/backend/prod.hcl" >&2
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
  echo "aws-guard: these credentials are for account $actual; production is $expected." >&2
  exit 1
fi
echo "aws-guard: account $actual${AWS_PROFILE:+, profile $AWS_PROFILE}" >&2
