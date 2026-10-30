#!/usr/bin/env bash
# Writes the WhatsApp bot's three secrets to SSM, then prints what to paste
# into the Meta dashboard. Run after a deploy has created the
# parameters (as "unset") and the webhook route — see "WhatsApp" in
# infra/README.md for where each value comes from.
#
# Values are read with `read -s`, so they never land in shell history.
set -euo pipefail

# The right account and a named profile, or nothing runs.
"$(dirname "$0")/aws-guard.sh"

put() {
  aws ssm put-parameter --name "$1" --type SecureString --overwrite \
    --value "$2" >/dev/null
}

read -r -s -p "Permanent access token (System User token): " ACCESS_TOKEN
echo
read -r -s -p "App secret (App settings > Basic): " APP_SECRET
echo

# Keep an existing verify token so re-running this doesn't break a webhook
# that is already registered.
VERIFY_TOKEN=$(aws ssm get-parameter --name /bgucats/whatsapp/verify-token \
  --with-decryption --query Parameter.Value --output text)
if [ "$VERIFY_TOKEN" = "unset" ]; then
  VERIFY_TOKEN=$(openssl rand -hex 32)
fi

put /bgucats/whatsapp/access-token "$ACCESS_TOKEN"
put /bgucats/whatsapp/app-secret "$APP_SECRET"
put /bgucats/whatsapp/verify-token "$VERIFY_TOKEN"

# The Lambda never caches "unset" and re-reads secrets every 10 minutes,
# so there is nothing to redeploy.

echo
echo "Saved. In the Meta dashboard: WhatsApp > Configuration > Webhook > Edit"
echo "  Callback URL:  $(terraform -chdir=infra/main output -raw whatsapp_webhook_url)"
echo "  Verify token:  ${VERIFY_TOKEN}"
echo "Then subscribe the webhook to the \"messages\" field."
