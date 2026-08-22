#!/usr/bin/env bash
# Registers (or re-registers) the Telegram webhook against the deployed API
# Gateway URL. Not Terraform-managed — Telegram's own API is the source of
# truth for webhook registration. Run once after `terraform apply`, and
# again any time the API Gateway URL changes.
#
# Reads secrets from SSM (not terraform.tfvars) so this works from any
# machine with the right AWS credentials, not just the one that ran apply.
set -euo pipefail

BOT_TOKEN=$(aws ssm get-parameter --name /bgucats/telegram/bot-token \
  --with-decryption --query 'Parameter.Value' --output text)
WEBHOOK_SECRET=$(aws ssm get-parameter --name /bgucats/telegram/webhook-secret \
  --with-decryption --query 'Parameter.Value' --output text)
WEBHOOK_URL=$(terraform -chdir=infra/main output -raw webhook_url)

echo "Registering webhook: ${WEBHOOK_URL}"
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${WEBHOOK_URL}" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d 'allowed_updates=["message","callback_query"]'
echo

echo "Verifying:"
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
echo
