#!/usr/bin/env bash
# Sets or rotates one of the app's secrets. They live in AWS only, never in
# Terraform or its state (infra/main/ssm.tf, infra/main/cognito.tf), so this
# is how they get there: by the owner, from an SSO admin session.
#
#   aws sso login --profile bgucats-prod-admin --use-device-code
#   AWS_PROFILE=bgucats-prod-admin infra/scripts/set-secret.sh <name>
#   aws sso logout
#
# <name> is one of:
#   telegram-bot-token       paste the token from @BotFather; checked with
#                            getMe, then the webhook is re-registered with it
#   telegram-webhook-secret  a new random value is generated; Telegram is
#                            told the new one at once
#   submitter-hash-salt      only creates it, in a new account. Changing it
#                            would give every Telegram contributor a new
#                            identity, so an existing salt is never replaced
#   google-oauth             paste the Google OAuth client ID and secret;
#                            creates or updates Cognito's Google provider
#
# Values are typed at a hidden prompt and handed to aws/curl on stdin, never
# as arguments, so they stay out of shell history and the process list.
# The ingest Lambda re-reads the bot's secrets every 5 minutes, so for up to
# 5 minutes after a Telegram change it may still use the old value: Telegram
# retries webhook calls that fail, but do it when the bot is quiet.
set -euo pipefail

"$(dirname "$0")/aws-guard.sh"

TOKEN_PARAM=/bgucats/telegram/bot-token
SECRET_PARAM=/bgucats/telegram/webhook-secret
SALT_PARAM=/bgucats/submitter-hash-salt
USER_POOL_NAME=bgucats-admins
ALLOWED_UPDATES='["message","callback_query"]' # as set-telegram-webhook.sh

ask() { # value=$(ask <prompt>): hidden input; the prompt goes to stderr
  local value
  read -rsp "$1: " value
  echo >&2
  [ -n "$value" ] || {
    echo "nothing entered" >&2
    exit 1
  }
  printf '%s' "$value"
}

# ssm_get <name>: the value, or nothing if the parameter does not exist
# (a new account); any other error stops the script.
ssm_get() {
  local out
  if out=$(aws ssm get-parameter --name "$1" --with-decryption \
    --query Parameter.Value --output text 2>&1); then
    printf '%s' "$out"
  elif ! grep -q ParameterNotFound <<<"$out"; then
    echo "$out" >&2
    exit 1
  fi
}

# aws_json <aws args...>: the request JSON comes on stdin. The AWS CLI cannot
# read --cli-input-json from file:///dev/stdin ("Invalid JSON received"), and
# an argument would show the value in the process list, so it goes through a
# file only this user can read, deleted at once.
aws_json() {
  local dir rc=0
  dir=$(mktemp -d)
  chmod 700 "$dir"
  (umask 077 && cat >"$dir/in.json")
  aws "$@" --cli-input-json "file://$dir/in.json" || rc=$?
  rm -rf "$dir"
  return "$rc"
}

# ssm_put <name> <value> [--overwrite]
ssm_put() {
  NAME="$1" VALUE="$2" OVERWRITE="${3:+true}" jq -n \
    '{Name: env.NAME, Value: env.VALUE, Type: "SecureString", Overwrite: (env.OVERWRITE == "true")}' |
    aws_json ssm put-parameter --query Version --output text |
    sed "s|^|$1: version |"
}

# tg <token> <method> [key=value ...]: a Bot API call with the token in a
# curl config on stdin, not on the command line.
tg() {
  local token="$1" method="$2"
  shift 2
  {
    printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$token" "$method"
    for kv in "$@"; do
      kv=${kv//\\/\\\\} # a config string is double-quoted: escape \ and "
      printf 'data-urlencode = "%s"\n' "${kv//\"/\\\"}"
    done
  } | curl -sS --config -
}

# The webhook URL does not change with a secret; take it from Telegram.
# In a new account, with the token or the secret not set yet, or no webhook
# registered, say so: infra/scripts/set-telegram-webhook.sh does the first one.
reregister_webhook() {
  local token="$1" secret="$2" url
  if [ -z "$token" ] || [ -z "$secret" ]; then
    echo "Webhook not registered: set the other Telegram secret too, then run set-telegram-webhook.sh."
    return
  fi
  url=$(tg "$token" getWebhookInfo | jq -r '.result.url // ""')
  if [ -z "$url" ]; then
    echo "Telegram has no webhook for this bot yet: run infra/scripts/set-telegram-webhook.sh"
    return
  fi
  echo "Re-registering webhook: $url"
  tg "$token" setWebhook "url=$url" "secret_token=$secret" "allowed_updates=$ALLOWED_UPDATES" | jq -c .
}

case "${1:-}" in
telegram-bot-token)
  token=$(ask "New bot token from @BotFather")
  # Check it before it replaces a working one.
  me=$(tg "$token" getMe)
  [ "$(jq -r .ok <<<"$me")" = true ] || {
    echo "Telegram does not accept this token: $(jq -r .description <<<"$me")" >&2
    exit 1
  }
  echo "Token is for @$(jq -r .result.username <<<"$me")"
  # The webhook was registered with the old token; ask with the new one,
  # which is the same bot.
  secret=$(ssm_get "$SECRET_PARAM")
  ssm_put "$TOKEN_PARAM" "$token" overwrite
  reregister_webhook "$token" "$secret"
  ;;

telegram-webhook-secret)
  # Telegram allows A-Z a-z 0-9 _ - and up to 256 characters.
  secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  token=$(ssm_get "$TOKEN_PARAM")
  ssm_put "$SECRET_PARAM" "$secret" overwrite
  reregister_webhook "$token" "$secret"
  ;;

submitter-hash-salt)
  if aws ssm get-parameter --name "$SALT_PARAM" --query Parameter.Name --output text >/dev/null 2>&1; then
    echo "$SALT_PARAM already exists. Replacing it would split every Telegram" >&2
    echo "contributor into a new identity, so this script never does." >&2
    exit 1
  fi
  ssm_put "$SALT_PARAM" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  ;;

google-oauth)
  pool=$(aws cognito-idp list-user-pools --max-results 60 \
    --query "UserPools[?Name=='$USER_POOL_NAME'].Id" --output text)
  [ -n "$pool" ] && [ "$(wc -w <<<"$pool")" = 1 ] || {
    echo "expected one user pool named $USER_POOL_NAME, found: '${pool}'" >&2
    exit 1
  }
  read -rp "Google OAuth client ID: " client_id
  client_secret=$(ask "Google OAuth client secret")
  # Cognito fills in Google's endpoints itself; these three are ours.
  details=$(CID="$client_id" CSECRET="$client_secret" jq -n \
    '{client_id: env.CID, client_secret: env.CSECRET, authorize_scopes: "openid email profile"}')
  if aws cognito-idp describe-identity-provider --user-pool-id "$pool" \
    --provider-name Google --query IdentityProvider.ProviderName --output text >/dev/null 2>&1; then
    POOL="$pool" DETAILS="$details" jq -n \
      '{UserPoolId: env.POOL, ProviderName: "Google", ProviderDetails: (env.DETAILS | fromjson)}' |
      aws_json cognito-idp update-identity-provider \
        --query IdentityProvider.LastModifiedDate --output text | sed 's/^/Google provider updated: /'
  else
    POOL="$pool" DETAILS="$details" jq -n \
      '{UserPoolId: env.POOL, ProviderName: "Google", ProviderType: "Google",
        ProviderDetails: (env.DETAILS | fromjson),
        AttributeMapping: {email: "email", username: "sub", name: "name", picture: "picture"}}' |
      aws_json cognito-idp create-identity-provider \
        --query IdentityProvider.CreationDate --output text | sed 's/^/Google provider created: /'
  fi
  ;;

*)
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
