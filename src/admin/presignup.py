"""Cognito pre-sign-up trigger: only allowlisted emails get an account.

The user pool has no self-service sign-up and no passwords — the only way in
is Google, and Google will happily authenticate all eight billion people on
earth. This trigger is the gate: unless an `ADMIN#{email}` record already
exists in the table, no user is ever created.

Deliberately *not* a domain check. "Anyone with a @post.bgu.ac.il address"
would hand admin over the whole dataset to every student at the university;
the allowlist is a handful of named people, added on purpose.

Raising is the documented way to reject — Cognito surfaces the message on the
hosted login page and creates nothing.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]

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

    if not table.get_item(Key={"PK": f"ADMIN#{email}", "SK": "META"}).get("Item"):
        logger.warning("blocked sign-up for non-allowlisted email=%s", email)
        raise SignUpBlocked(
            "This Google account is not an admin or collaborator of BGU cats."
        )

    logger.info("allowing sign-up for email=%s", email)

    # Google has already verified the address, and there is no second factor
    # to fall back on — leaving it unconfirmed would just block the login.
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    return event
