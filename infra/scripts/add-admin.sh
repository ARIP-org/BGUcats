#!/usr/bin/env bash
# Adds an email to the admin allowlist, which is the only thing that lets a
# Google account create a user in the Cognito pool at all.
#
# The Admins tab in the labeling tool does exactly the same write; this script
# is for the case where nobody can reach that tab yet, or where you would
# rather not click. It is not Terraform-managed on purpose — the allowlist is
# operational data that changes when people join, not infrastructure.
set -euo pipefail

EMAIL=$(echo "${1:?usage: add-admin.sh someone@example.com}" | tr '[:upper:]' '[:lower:]')

case "$EMAIL" in
*@*.*) ;;
*)
  echo "not an email address: $EMAIL" >&2
  exit 1
  ;;
esac

aws dynamodb put-item \
  --table-name bgucats-data \
  --item "$(
    cat <<JSON
{
  "PK":      {"S": "ADMIN#${EMAIL}"},
  "SK":      {"S": "META"},
  "email":   {"S": "${EMAIL}"},
  "addedAt": {"S": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"},
  "addedBy": {"S": "cli"},
  "GSI2PK":  {"S": "ENTITY#ADMIN"},
  "GSI2SK":  {"S": "${EMAIL}"}
}
JSON
  )"

echo "${EMAIL} can now sign in."
