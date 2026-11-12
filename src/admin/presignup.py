"""Cognito pre-sign-up trigger: only people the sign-up policy admits get an
account.

The user pool has no self-service sign-up and no passwords — the only way in
is Google, and Google will happily authenticate all eight billion people on
earth. This trigger is the gate (common.admission): an `ADMIN#{email}`
record lets anyone in, and the account's policy may also let in every
address at the listed domains (`domain`, BGU's Google accounts) or everyone
(`open`). Staging stays `allowlist`; production too until the app opens
(docs/app-plan/, D1 and L3).

The policy is checked again on every API call, so tightening it shuts out
existing accounts at once, not only new ones.

Raising is the documented way to reject — Cognito surfaces the message on the
hosted login page and creates nothing.
"""

import logging
import os

import boto3

from common import admission

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
SIGNUP_POLICY = os.environ.get("SIGNUP_POLICY", "allowlist")
SIGNUP_DOMAINS = admission.domains_from(os.environ.get("SIGNUP_DOMAINS"))

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


class SignUpBlocked(Exception):
    """Message reaches the user verbatim on the hosted login page."""


def handler(event, context):
    attributes = event.get("request", {}).get("userAttributes", {})
    email = (attributes.get("email") or "").strip().lower()

    if not email:
        logger.warning("sign-up attempt with no email attribute")
        raise SignUpBlocked("This account has no email address.")

    item = table.get_item(Key={"PK": f"ADMIN#{email}", "SK": "META"}).get("Item")
    if not admission.admitted(email, item, SIGNUP_POLICY, SIGNUP_DOMAINS):
        logger.warning("blocked sign-up for email=%s policy=%s", email, SIGNUP_POLICY)
        raise SignUpBlocked("This Google account cannot sign in to BGU Cats yet.")

    logger.info("allowing sign-up for email=%s", email)

    # Google has already verified the address, and there is no second factor
    # to fall back on — leaving it unconfirmed would just block the login.
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    return event
