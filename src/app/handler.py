"""The member API: everything a user does in the app that is not an upload
(docs/app-plan/04-api.md). Behind `ANY /api/v1/{proxy+}` and the same JWT
authorizer as the desk's API.

Kept apart from src/admin on purpose: its role can read the dataset
(bgucats-data) and never write it, and writes only bgucats-social
(infra/main/app_api.tf). Uploads stay on the desk's capture routes, which
keep the write order of spec §10.

Since milestone F4: who you are (`GET /me`, which makes your account on
the first call) and accepting the terms. Each later milestone adds its
routes to ROUTES.

With the `social` flag off (production until the app opens), every route
answers 404, and nothing here runs.
"""

import json
import logging
import os
import re
import secrets

import boto3

from common import admission, api, ids, tables, text
from common.api import ApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_TABLE_NAME = os.environ["DATA_TABLE_NAME"]
SOCIAL_TABLE_NAME = os.environ["SOCIAL_TABLE_NAME"]
SOCIAL = os.environ.get("SOCIAL", "off") == "on"
SIGNUP_POLICY = os.environ.get("SIGNUP_POLICY", "allowlist")
SIGNUP_DOMAINS = admission.domains_from(os.environ.get("SIGNUP_DOMAINS"))
# The terms a person must accept before they write anything. A new version
# asks everyone again (docs/app-plan/OWNER_STEPS.md, O10).
TERMS_VERSION = os.environ.get("TERMS_VERSION", "draft")
# What the client may offer, per account (infra/main/variables.tf).
FLAGS = json.loads(os.environ.get("FLAGS") or "{}")

dynamodb = boto3.resource("dynamodb")
data_table = dynamodb.Table(DATA_TABLE_NAME)
social_table = dynamodb.Table(SOCIAL_TABLE_NAME)

USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{3,20}$")
# Names nobody may hold: they would read as the app speaking.
RESERVED_USERNAMES = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "app",
        "bgu",
        "bgucats",
        "cats",
        "help",
        "me",
        "moderator",
        "null",
        "official",
        "root",
        "staff",
        "support",
        "system",
        "undefined",
    }
)
INVITE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
INVITE_LENGTH = 10
CREATE_ATTEMPTS = 5


class _Taken(Exception):
    """A username or invite code another account already holds."""


# --------------------------------------------------------------------------
# The caller and their account
# --------------------------------------------------------------------------


def _claims(event):
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )


def _admit(email):
    """The caller's role, or 403 not_admitted (common.admission)."""
    role = admission.role_for(
        email,
        tables.get_one(data_table, f"ADMIN#{email}"),
        SIGNUP_POLICY,
        SIGNUP_DOMAINS,
    )
    if role is None:
        raise ApiError(
            403, "this account is not let in to BGU Cats", code="not_admitted"
        )
    return role


def username_base(email):
    """A first guess at a username from the address: "Maya.Levi+x@..." ->
    "maya.levi". Chosen properly at first run (G16); this is only a start."""
    local = email.split("@", 1)[0].split("+", 1)[0].lower()
    base = re.sub(r"[^a-z0-9._]", "", local)
    base = re.sub(r"[._]{2,}", ".", base).strip("._")[:16]
    if len(base) < 3:
        base = (base + "cat")[:16] if base else "cat"
    return base


def _candidates(email):
    base = username_base(email)
    if base not in RESERVED_USERNAMES:
        yield base
    while True:
        yield f"{base[:15]}{secrets.randbelow(10_000):04d}"


def _invite_code():
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def _new_account(email, display_name, now):
    """Writes the account in one transaction: the sign-in lookup, the user,
    their username and their invite code. Every key is conditional, so two
    first calls at once make one account (03-data-model.md, "Writes that
    must be all-or-nothing")."""
    user_id = ids.new_ulid()
    names = _candidates(email)
    for _ in range(CREATE_ATTEMPTS):
        username, code = next(names), _invite_code()
        user = {
            "PK": f"USER#{user_id}",
            "SK": "PROFILE",
            "userId": user_id,
            "email": email,
            "username": username,
            "displayName": display_name or username,
            "inviteCode": code,
            "status": "active",
            "language": "en",
            "notifications": True,
            "createdAt": now,
            "GSI2PK": "ENTITY#USER",
            "GSI2SK": now,
        }
        items = [
            {"PK": f"IDENTITY#{email}", "SK": "META", "userId": user_id},
            user,
            {"PK": f"USERNAME#{username}", "SK": "META", "userId": user_id},
            {"PK": f"INVITE#{code}", "SK": "META", "userId": user_id},
        ]
        try:
            social_table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": SOCIAL_TABLE_NAME,
                            # The resource's client takes plain values, as
                            # everywhere in this project's transactions.
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    }
                    for item in items
                ]
            )
            logger.info("new account user=%s", user_id)
            return user
        except social_table.meta.client.exceptions.TransactionCanceledException as exc:
            reasons = [
                r.get("Code") for r in exc.response.get("CancellationReasons", [])
            ]
            if reasons and reasons[0] == "ConditionalCheckFailed":
                # Another call made this person's account a moment ago.
                return None
            if "ConditionalCheckFailed" not in reasons:
                raise
            # The username or the invite code was taken: try others.
    raise ApiError(503, "could not make the account; try again", code="try_again")


def _account(email, claims):
    """The caller's user item, made on their first call."""
    identity = tables.get_one(social_table, f"IDENTITY#{email}")
    if identity is None:
        name = text.clean(claims.get("name"), "name", 30, required=False)
        made = _new_account(email, name, api.now_iso())
        if made is not None:
            return made
        identity = tables.get_one(social_table, f"IDENTITY#{email}")
    user = tables.get_one(social_table, f"USER#{identity['userId']}", "PROFILE")
    if user is None:
        raise ApiError(503, "the account is being made; try again", code="try_again")
    return user


def _require_usable(user):
    if user.get("status") == "banned":
        raise ApiError(403, "this account is blocked", code="banned")
    if user.get("status") == "deleting":
        raise ApiError(403, "this account is being deleted", code="gone")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _me_payload(user, role):
    return {
        "userId": user["userId"],
        "email": user["email"],
        "username": user["username"],
        "displayName": user["displayName"],
        "inviteCode": user["inviteCode"],
        "language": user.get("language", "en"),
        "notifications": user.get("notifications", True),
        "role": role,
        "since": user["createdAt"],
        "terms": {
            "current": TERMS_VERSION,
            "accepted": user.get("termsVersion"),
            "required": user.get("termsVersion") != TERMS_VERSION,
        },
        "flags": FLAGS,
    }


def _get_me(user, role, **_):
    return _me_payload(user, role)


def _accept_terms(user, role, body, **_):
    version = body.get("version")
    if version != TERMS_VERSION:
        raise ApiError(409, "these are not the current terms", code="stale_terms")
    now = api.now_iso()
    social_table.update_item(
        Key={"PK": user["PK"], "SK": "PROFILE"},
        UpdateExpression="SET termsVersion = :v, termsAcceptedAt = :now",
        ExpressionAttributeValues={":v": version, ":now": now},
    )
    return _me_payload({**user, "termsVersion": version, "termsAcceptedAt": now}, role)


def require_terms(user):
    """For every route that writes (B1 onward): the terms come first."""
    if user.get("termsVersion") != TERMS_VERSION:
        raise ApiError(403, "accept the terms first", code="terms_required")


ROUTES = (
    ("GET", r"^/api/v1/me$", _get_me, "user"),
    ("POST", r"^/api/v1/me/terms$", _accept_terms, "user"),
)


def _answer(status, payload):
    return api.response(status, payload)


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    try:
        if not SOCIAL:
            raise ApiError(404, "not found", code="not_found")
        email = api.caller_email(event)
        role = _admit(email)
        handler_fn, params, _ = api.match_route(ROUTES, method, path)
        user = _account(email, _claims(event))
        _require_usable(user)
        body = api.parse_body(event)
        result = handler_fn(
            user=user, role=role, body=body, query=api.query_params(event), **params
        )
        return _answer(200, result)
    except ApiError as exc:
        payload = {"error": exc.message, **exc.details}
        if exc.code:
            payload["code"] = exc.code
        return _answer(exc.status, payload)
    except Exception:
        logger.exception("unhandled error on %s %s", method, path)
        return _answer(500, {"error": "internal error", "code": "internal"})
