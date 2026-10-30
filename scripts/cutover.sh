#!/usr/bin/env bash
# The evening of the move to sasha-bgucats-prod: docs/MANUAL_STEPS.md 7b
# (steps 2, 4–6) and 8.1, in one run, by the owner:
#
#   aws sso login --profile bgucats-prod-admin --use-device-code
#   bash scripts/cutover.sh
#   aws sso logout
#
# 1. Pauses Telegram (deleteWebhook without drop_pending_updates: Telegram
#    holds new messages for up to 24 hours instead of delivering them).
# 2. Copies the media that arrived since the pre-copy, while the new table
#    is still empty.
# 3. Dry-runs the table copy. Any conflict except the bootstrap ADMIN# row
#    stops the run before anything is written.
# 4. Copies the table.
# 5. Verifies media, model, table and SSM values. A lagging GSI is
#    retried for up to five minutes; any other difference stops the run.
# 6. Points Telegram at the new account and checks that it took.
#
# Until step 6 has succeeded, any failure, or Ctrl-C, points Telegram back
# at the old account, which nothing here changes (it is only read, through
# mgmt-ro). The messages queued in the meantime then go there, and the
# move can be tried again another evening. If it stopped at step 4 or
# later, the new table is partly filled: look at why before re-running,
# because step 2 then refuses (an object landing in raw/ would re-process
# a photo whose record is already there).
set -euo pipefail
cd "$(dirname "$0")/.."
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

ALLOWED='["message","callback_query"]' # as infra/scripts/set-telegram-webhook.sh

migrate() { python scripts/migrate_account.py "$@"; }
secret() {
  aws ssm get-parameter --profile "$1" --with-decryption --name "$2" \
    --query Parameter.Value --output text
}
# Telegram answers a failed call with HTTP 400, so --fail-with-body makes
# curl, and with it this script, stop on it.
tg() { curl -sS --fail-with-body "https://api.telegram.org/bot${TOKEN}/$1" "${@:2}"; }

TOKEN=$(secret mgmt-ro /bgucats/telegram/bot-token)
OLD_SECRET=$(secret mgmt-ro /bgucats/telegram/webhook-secret)
OLD_URL=$(tg getWebhookInfo | jq -r .result.url)
if [ -z "$OLD_URL" ]; then
  echo "Telegram has no webhook set, so there is nothing to move. Stopping." >&2
  exit 1
fi
echo "$OLD_URL" >"$HOME/bgucats-old-webhook-url.txt"
echo "Old webhook: $OLD_URL (also in ~/bgucats-old-webhook-url.txt: the way back)"

paused=0
moved=0
way_back() {
  status=$?
  if [ "$paused" = 1 ] && [ "$moved" = 0 ]; then
    echo
    echo "!! Stopped before the cutover. Pointing Telegram back at the old account."
    if tg setWebhook -d "url=$OLD_URL" -d "secret_token=$OLD_SECRET" \
      -d "allowed_updates=$ALLOWED" >/dev/null; then
      echo "   Done: production is the old account, as before. Queued messages go there."
      echo "   Nothing in the old account was changed. If this stopped at step 4 or later,"
      echo "   the new table is partly filled: find out why before running this again."
    else
      echo "   FAILED. Run by hand: infra/scripts/set-telegram-webhook.sh with the old" >&2
      echo "   account's state, or setWebhook with the URL in ~/bgucats-old-webhook-url.txt." >&2
    fi
  fi
  unset TOKEN OLD_SECRET
  exit "$status"
}
trap way_back EXIT

echo
echo "== 1/6 Pausing Telegram"
tg deleteWebhook >/dev/null
paused=1

echo
echo "== 2/6 Last media copy"
migrate media --apply

echo
echo "== 3/6 Table, dry run"
migrate table --overwrite-prefix 'ADMIN#'

echo
echo "== 4/6 Table, copy"
migrate table --apply --overwrite-prefix 'ADMIN#'

echo
echo "== 5/6 Verify"
for attempt in 1 2 3 4 5; do
  if migrate verify; then
    break
  fi
  if [ "$attempt" = 5 ]; then
    echo "Still different after five tries: not cutting over." >&2
    exit 1
  fi
  echo "   (a GSI may still be catching up: again in 60 s)"
  sleep 60
done

echo
echo "== 6/6 Telegram to the new account"
make tf-init PROFILE=bgucats-prod-ro >/dev/null
NEW_URL=$(AWS_PROFILE=bgucats-prod-ro terraform -chdir=infra/main output -raw webhook_url)
NEW_SECRET=$(secret bgucats-prod-admin /bgucats/telegram/webhook-secret)
tg setWebhook -d "url=$NEW_URL" -d "secret_token=$NEW_SECRET" \
  -d "allowed_updates=$ALLOWED" >/dev/null
unset NEW_SECRET
if [ "$(tg getWebhookInfo | jq -r .result.url)" != "$NEW_URL" ]; then
  echo "Telegram does not report the new URL." >&2
  exit 1
fi
moved=1

sleep 10
tg getWebhookInfo | jq '.result | {url, pending_update_count, last_error_message}'
echo
echo "Cut over. Telegram delivers to $NEW_URL; queued messages arrive now."
echo "Next: docs/MANUAL_STEPS.md 8.2 (install the new app) and 8.3 (smoke test)."
