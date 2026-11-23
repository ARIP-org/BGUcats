"""The member API: everything a user does in the app that is not an upload
(docs/app-plan/04-api.md). Behind `ANY /api/v1/{proxy+}` and the same JWT
authorizer as the desk's API.

Kept apart from src/admin on purpose: its role can read the dataset
(bgucats-data) and never write it, and writes only bgucats-social
(infra/main/app_api.tf). Uploads stay on the desk's capture routes, which
keep the write order of spec §10.

Since milestone F4: who you are (`GET /me`, which makes your account on
the first call) and accepting the terms. Since B2: the cats. Since B3a:
posts, likes and the feed. Since B3b: what a person met, on `/me` and on
each cat. Since B6: new-cat proposals, and posts held until an admin
decides one. Each later milestone adds its routes to ROUTES.

With the `social` flag off (production until the app opens), every route
answers 404, and nothing here runs.
"""

import base64
import hashlib
import json
import logging
import math
import os
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key

from common import (
    achievements,
    admission,
    api,
    encounters,
    ids,
    limits,
    media,
    polls,
    proposals,
    regions,
    reports,
    tables,
    text,
)
from common.api import ApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_TABLE_NAME = os.environ["DATA_TABLE_NAME"]
SOCIAL_TABLE_NAME = os.environ["SOCIAL_TABLE_NAME"]
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
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
s3 = boto3.client("s3")

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
        # A name just changed is shown to its owner at once; everyone else
        # sees `displayName` until the new one has been checked (B1).
        "displayName": user.get("pendingName") or user["displayName"],
        "namePending": bool(user.get("pendingName")),
        # The same for a photo: the owner sees the new one while it waits.
        "avatar": _avatar_url(user.get("pendingAvatarKey") or user.get("avatarKey")),
        "avatarPending": bool(user.get("pendingAvatarKey")),
        "inviteCode": user["inviteCode"],
        "language": user.get("language", "en"),
        "theme": user.get("theme"),
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
    return {**_me_payload(user, role), "counters": _counters_of(user)}


def _counters_of(user):
    """What the events Lambda counted from the person's encounters (B3b):
    in all, and this month. A second or two behind a pick or a label."""
    month = _israel_today().isoformat()[:7]
    keys = [
        {"PK": user["PK"], "SK": "STATS#ALL"},
        {"PK": user["PK"], "SK": f"STATS#{month}"},
    ]
    found = {item["SK"]: item for item in _batch_get(social_table, keys)}

    def counts(sk):
        item = found.get(sk, {})
        return {
            "catsMet": _number(item.get("catsMet")),
            "encounters": _number(item.get("encounters")),
        }

    return {"all": counts("STATS#ALL"), "month": counts(f"STATS#{month}")}


NAME_MAX = 30
NAME_CHANGES_PER_DAY = 10
LANGUAGES = ("en", "he", "ru", "ar")
THEMES = ("bgu-light", "bgu-dark", "cats-light", "cats-dark")


def _update_me(user, role, body, **_):
    """`PATCH /me`: the display name, and the settings that follow a person
    from phone to phone. Only the fields sent change.

    A display name is what other people read, so it is written beside the
    published one (`pendingName`) and takes its place once it has been
    checked: the events Lambda does that (publish_name; moderation, C1,
    goes there). Its owner sees it at once. The settings are the person's
    own business and are simply stored.
    """
    sets, removes, values = [], [], {}
    if "displayName" in body:
        require_terms(user)
        name = text.clean(body["displayName"], "displayName", NAME_MAX)
        if name == user["displayName"]:
            # Back to the name everyone already sees: nothing to check.
            removes += ["pendingName", "pendingNameAt"]
        elif name != user.get("pendingName"):
            limits.take(
                social_table, f"{user['userId']}#names", NAME_CHANGES_PER_DAY, 86400
            )
            sets += ["pendingName = :name", "pendingNameAt = :now"]
            values |= {":name": name, ":now": api.now_iso()}
    for field, allowed in (("language", LANGUAGES), ("theme", THEMES)):
        if field in body:
            if body[field] not in allowed:
                raise ApiError(400, f"{field} is one of: {', '.join(allowed)}")
            sets.append(f"#{field} = :{field}")
            values[f":{field}"] = body[field]
    if "notifications" in body:
        if not isinstance(body["notifications"], bool):
            raise ApiError(400, "notifications is true or false")
        sets.append("notifications = :notifications")
        values[":notifications"] = body["notifications"]
    if not sets and not removes:
        if "displayName" in body:
            return _get_me(user, role)  # the name it already is
        raise ApiError(
            400, "nothing to change: displayName, language, theme, notifications"
        )

    expression = (f"SET {', '.join(sets)} " if sets else "") + (
        f"REMOVE {', '.join(removes)}" if removes else ""
    )
    names = {f"#{f}": f for f in ("language", "theme") if f"#{f} = :{f}" in sets}
    changed = social_table.update_item(
        Key={"PK": user["PK"], "SK": "PROFILE"},
        UpdateExpression=expression.strip(),
        ConditionExpression="attribute_exists(PK)",
        ReturnValues="ALL_NEW",
        **({"ExpressionAttributeNames": names} if names else {}),
        **({"ExpressionAttributeValues": values} if values else {}),
    )["Attributes"]
    return _get_me(changed, role)


# Attempts, not successes: a taken name counts, so the route cannot be used
# to ask which names exist more than a few times a day.
USERNAME_CHANGES_PER_DAY = 10


def _clean_username(value):
    """The username as it will be stored, or ApiError(400) saying the rule.
    Lower case, so "Maya" and "maya" are one name; 3 to 20 of a-z, 0-9, dot
    and underscore; a letter or digit at each end; none of the names that
    would read as the app speaking."""
    if not isinstance(value, str):
        raise ApiError(400, "username must be text", code="bad_username")
    name = value.strip().lower()
    if (
        not USERNAME_PATTERN.match(name)
        or name[0] in "._"
        or name[-1] in "._"
        or re.search(r"[._]{2}", name)
    ):
        raise ApiError(
            400,
            "a username is 3 to 20 letters a-z, digits, dots or underscores, "
            "with a letter or digit at each end",
            code="bad_username",
        )
    if name in RESERVED_USERNAMES:
        raise ApiError(409, "that username is not available", code="name_taken")
    return name


def _choose_username(user, role, body, **_):
    """`PUT /me/username`: one transaction, so two people asking for the
    same name at once cannot both get it, and the old name is free the
    moment the new one is held (03-data-model.md, "Writes that must be
    all-or-nothing"). Not held for a check as a display name is: its
    alphabet leaves little to check, and a lookup key cannot be pending.
    C1 adds the check; until then the reserved list is the rule."""
    require_terms(user)
    new = _clean_username(body.get("username"))
    old = user["username"]
    if new == old:
        return _get_me(user, role)
    limits.take(
        social_table, f"{user['userId']}#usernames", USERNAME_CHANGES_PER_DAY, 86400
    )
    client = social_table.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": SOCIAL_TABLE_NAME,
                        "Item": {
                            "PK": f"USERNAME#{new}",
                            "SK": "META",
                            "userId": user["userId"],
                        },
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Delete": {
                        "TableName": SOCIAL_TABLE_NAME,
                        "Key": {"PK": f"USERNAME#{old}", "SK": "META"},
                        "ConditionExpression": "userId = :me",
                        "ExpressionAttributeValues": {":me": user["userId"]},
                    }
                },
                {
                    "Update": {
                        "TableName": SOCIAL_TABLE_NAME,
                        "Key": {"PK": user["PK"], "SK": "PROFILE"},
                        "UpdateExpression": "SET username = :new",
                        "ConditionExpression": "username = :old",
                        "ExpressionAttributeValues": {":new": new, ":old": old},
                    }
                },
            ]
        )
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            raise ApiError(409, "that username is taken", code="name_taken")
        # The person's own name changed under this call (two phones).
        raise ApiError(503, "your username just changed; try again", code="try_again")
    return _get_me({**user, "username": new}, role)


# --------------------------------------------------------------------------
# The profile photo (B1b)
# --------------------------------------------------------------------------

AVATAR_CHANGES_PER_DAY = 5
AVATAR_UPLOAD_TTL_SECONDS = 300


def _avatar_url(key):
    """A signed address for a profile photo, or None. An avatar's object is
    never rewritten (a new photo is a new key), so it may be cached like a
    cat's photo."""
    return media.presign(s3, MEDIA_BUCKET, key) if key else None


def _start_avatar(user, **_):
    """`POST /me/avatar`: where to send the picture. The phone has already
    scaled and re-encoded it (02-architecture.md, "Storage"); the upload is
    pinned to this person's own key, to JPEG and to 200 KB."""
    require_terms(user)
    limits.take(
        social_table, f"{user['userId']}#avatars", AVATAR_CHANGES_PER_DAY, 86400
    )
    avatar_id = ids.new_ulid()
    upload = s3.generate_presigned_post(
        Bucket=MEDIA_BUCKET,
        Key=media.avatar_key(user["userId"], avatar_id),
        Fields={"Content-Type": media.AVATAR_TYPE},
        Conditions=[
            {"Content-Type": media.AVATAR_TYPE},
            ["content-length-range", 1, media.AVATAR_MAX_BYTES],
        ],
        ExpiresIn=AVATAR_UPLOAD_TTL_SECONDS,
    )
    return {"avatarId": avatar_id, "upload": upload}


def _complete_avatar(user, role, avatar_id, **_):
    """`POST /me/avatar/{id}/complete`: the picture arrived. Checked by its
    own bytes, never by what the phone said it was, and refused if it still
    carries the camera's metadata. Then it waits beside the published one
    (`pendingAvatarKey`) for the events Lambda, as a changed name does."""
    key = media.avatar_key(user["userId"], avatar_id)
    if key in (user.get("pendingAvatarKey"), user.get("avatarKey")):
        return _get_me(user, role)  # a retry of a call that already worked
    try:
        head = s3.head_object(Bucket=MEDIA_BUCKET, Key=key)
        start = s3.get_object(
            Bucket=MEDIA_BUCKET, Key=key, Range=f"bytes=0-{media.AVATAR_HEAD_BYTES - 1}"
        )["Body"].read()
    except s3.exceptions.ClientError:
        raise ApiError(409, "the photo has not reached storage yet", code="try_again")
    problem = (
        "it is too large"
        if head["ContentLength"] > media.AVATAR_MAX_BYTES
        else media.jpeg_problem(start)
    )
    if problem:
        _delete_avatar_objects(user, keep=_avatar_keys(user))
        raise ApiError(
            400, f"this photo cannot be a profile photo: {problem}", code="bad_photo"
        )
    changed = social_table.update_item(
        Key={"PK": user["PK"], "SK": "PROFILE"},
        UpdateExpression="SET pendingAvatarKey = :key, pendingAvatarAt = :now",
        ConditionExpression="attribute_exists(PK)",
        ExpressionAttributeValues={":key": key, ":now": api.now_iso()},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    # What this photo replaces, and any upload that was never confirmed.
    # The published one stays until this one is.
    _delete_avatar_objects(changed, keep=_avatar_keys(changed))
    return _get_me(changed, role)


def _remove_avatar(user, role, **_):
    """`DELETE /me/avatar`: back to the cat's face, at once and for everyone."""
    changed = social_table.update_item(
        Key={"PK": user["PK"], "SK": "PROFILE"},
        UpdateExpression="REMOVE avatarKey, pendingAvatarKey, pendingAvatarAt",
        ConditionExpression="attribute_exists(PK)",
        ReturnValues="ALL_NEW",
    )["Attributes"]
    _delete_avatar_objects(changed, keep=set())
    return _get_me(changed, role)


def _avatar_keys(user):
    return {user.get("avatarKey"), user.get("pendingAvatarKey")} - {None}


def _delete_avatar_objects(user, keep):
    """Every version of every object under this person's avatar prefix that
    is not in `keep`. The bucket keeps versions, so a plain delete would
    leave the picture there: a removed photo has to be gone."""
    prefix = f"avatars/{user['userId']}/"
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=MEDIA_BUCKET, Prefix=prefix):
        targets = [
            {"Key": v["Key"], "VersionId": v["VersionId"]}
            for v in (page.get("Versions", []) + page.get("DeleteMarkers", []))
            if v["Key"] not in keep
        ]
        if targets:
            s3.delete_objects(Bucket=MEDIA_BUCKET, Delete={"Objects": targets})


def _delete_me(user, body, **_):
    """`DELETE /me`, body `{"confirm": "delete"}`: the account goes
    (03-data-model.md, "Deleting an account"; D14). This marks it
    `deleting`, after which every call by this person, this one again
    included, answers `gone`; the events Lambda does the rest from that
    change, a step at a time (`delete_account` in src/events/handler.py).

    Two parts are done here, because only this Lambda may do them: the
    profile photo's objects (the events Lambda has no access to the
    bucket), and the list of cats whose polls and feedings the job must
    look through (it cannot read the dataset, where the cats are listed).

    Signing the person out and deleting their Cognito user is B10b: until
    then the same sign-in still works, answers `gone` while the job runs,
    and makes a new, empty account once it has finished."""
    if body.get("confirm") != "delete":
        raise ApiError(400, 'confirm is "delete"', code="confirm")
    try:
        social_table.update_item(
            Key={"PK": user["PK"], "SK": "PROFILE"},
            UpdateExpression=(
                "SET #s = :deleting, deletingAt = :now, deletingCats = :cats, "
                "deletionStep = :zero"
            ),
            # Banned a moment ago, or a second call: the ban stands, and a
            # deletion already started is not started again.
            ConditionExpression="#s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":active": "active",
                ":deleting": "deleting",
                ":now": api.now_iso(),
                ":cats": sorted({c["catId"] for c in _cats()}),
                ":zero": 0,
            },
        )
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        fresh = tables.get_one(social_table, user["PK"], "PROFILE") or {}
        _require_usable(fresh)
        raise ApiError(403, "this account is being deleted", code="gone") from None
    _delete_avatar_objects(user, keep=set())
    logger.info("deleting user=%s", user["userId"])
    return {"deleting": True}


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


# A phone that takes notifications (B9). At most this many per person: a
# sixth pushes out the one heard from longest ago.
MAX_DEVICES = 5
APNS_TOKEN = re.compile(r"^[0-9a-f]{64,200}$")
APNS_ENVIRONMENTS = ("production", "development")


def _devices(user):
    return tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(user["PK"]) & Key("SK").begins_with("DEVICE#"),
        ConsistentRead=True,
    )


def _put_device(user, device_id, body, **_):
    """`PUT /me/devices/{deviceId}`: this phone's address for Apple's
    notifications, and which of Apple's two worlds it belongs to (a build
    from Xcode is `development`, TestFlight and the App Store `production`).
    Sent by the phone at every launch with notifications on: the same call
    again only renews it. The events Lambda reads it and nothing else does;
    no route gives a token back."""
    token = body.get("apnsToken")
    if not isinstance(token, str) or not APNS_TOKEN.match(token):
        raise ApiError(400, "apnsToken is the device token, in lowercase hex")
    environment = body.get("environment")
    if environment not in APNS_ENVIRONMENTS:
        raise ApiError(400, "environment is production or development")
    now = api.now_iso()
    social_table.put_item(
        Item={
            "PK": user["PK"],
            "SK": f"DEVICE#{device_id}",
            "userId": user["userId"],
            "deviceId": device_id,
            "apnsToken": token,
            "environment": environment,
            "updatedAt": now,
        }
    )
    devices = sorted(_devices(user), key=lambda d: d.get("updatedAt") or "", reverse=True)
    for old in devices[MAX_DEVICES:]:
        social_table.delete_item(Key={"PK": old["PK"], "SK": old["SK"]})
    return {"deviceId": device_id, "environment": environment, "updatedAt": now}


def _delete_device(user, device_id, **_):
    """`DELETE /me/devices/{deviceId}`: at sign-out, and when the person
    turns notifications off on this phone. Removing one that is not there
    removes nothing and says the same."""
    social_table.delete_item(Key={"PK": user["PK"], "SK": f"DEVICE#{device_id}"})
    return {"deviceId": device_id, "removed": True}


def require_terms(user):
    """For every route that writes (B1 onward): the terms come first."""
    if user.get("termsVersion") != TERMS_VERSION:
        raise ApiError(403, "accept the terms first", code="terms_required")


# --------------------------------------------------------------------------
# Cats (B2)
# --------------------------------------------------------------------------

ISRAEL = ZoneInfo("Asia/Jerusalem")
BATCH_GET_LIMIT = 100
CAT_PAGE_PHOTOS = 12
# A cat of the day is one seen this recently, when there is any.
CAT_OF_THE_DAY_DAYS = 30


def _cats():
    return tables.query_all(
        data_table,
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq("ENTITY#CAT"),
        ScanIndexForward=True,
    )


def _counters(cat_ids):
    """Each cat's public counters (CAT#{id} / PUBLIC in bgucats-social),
    kept by the events Lambda. A cat with none yet has none."""
    found = {}
    name = social_table.name
    client = social_table.meta.client  # plain values, like the table itself
    keys = [{"PK": f"CAT#{c}", "SK": "PUBLIC"} for c in cat_ids]
    for start in range(0, len(keys), BATCH_GET_LIMIT):
        request = {name: {"Keys": keys[start : start + BATCH_GET_LIMIT]}}
        while request:
            answer = client.batch_get_item(RequestItems=request)
            for item in answer["Responses"].get(name, []):
                found[item["PK"].removeprefix("CAT#")] = item
            request = answer.get("UnprocessedKeys") or None
    return found


shown_name = polls.shown_name


def _photos_of(cat_id, newest_first, limit):
    """Labeled photos of a cat, not videos (no derivatives exist for them)."""
    photos, query = (
        [],
        {
            "IndexName": "GSI3",
            "KeyConditionExpression": Key("GSI3PK").eq(f"CAT#{cat_id}"),
            "ScanIndexForward": not newest_first,
            "Limit": max(limit * 2, 10),
        },
    )
    while len(photos) < limit:
        page = data_table.query(**query)
        photos += [p for p in page["Items"] if p.get("mediaType") != "video"]
        if "LastEvaluatedKey" not in page:
            break
        query["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return photos[:limit]


def _number(value):
    return int(value) if value is not None else 0


# The grade looks at this month and the two before (D9).
GPA_MONTHS = 3


def _popularity(public, today):
    """A cat's popularity now: its counted encounters, and the points they
    earned, over the current month and the two before (`pop{yyyy-mm}`, kept
    by the events Lambda)."""
    month, total = today.isoformat()[:7], 0
    for _ in range(GPA_MONTHS):
        total += _number(public.get(f"pop{month}"))
        month = _previous_month(month)
    return total


def grades(counters, today):
    """{catId: GPA}: a popularity grade the app works out; nobody grades a
    cat (D9). `1 + 3 × √(popularity ÷ the most popular cat's)`, to one
    decimal, so the most popular cat has 4.0 and the square root keeps the
    rest of the campus off the floor. A cat nobody met in that time has
    none, not a low one. With the `gpa` flag off, nobody has one."""
    if not FLAGS.get("gpa"):
        return {}
    popular = {c: _popularity(public, today) for c, public in counters.items()}
    top = max(popular.values(), default=0)
    return {
        c: round(1 + 3 * math.sqrt(points / top), 1)
        for c, points in popular.items()
        if points > 0
    }


def public_cat(cat, public, cover, gpa=None):
    """What a user may see of a cat. The desk's own fields (notes, who
    created it) never leave here: tests/app/test_cats.py lists every key."""
    name, source = shown_name(cat, public)
    return {
        "gpa": gpa,
        "catId": cat["catId"],
        "name": name,
        "nameSource": source,
        "regionId": cat.get("usualRegionId"),
        "coat": cat.get("coat"),
        "cover": media.photo_urls(s3, MEDIA_BUCKET, cover["photoId"])
        if cover
        else None,
        "photoCount": _number(cat.get("photoCount")),
        "posts": _number(public.get("posts")),
        "likes": _number(public.get("likes")),
        "lastSeenAt": public.get("lastSeenAt"),
        "lastFedAt": public.get("lastFedAt"),
        "firstSeenAt": cat.get("createdAt"),
    }


def cat_of_the_day(cats, today):
    """The same cat for everyone on one Israel day, and nothing stored: among
    cats with a photo, seen in the last 30 days if any were, the one at
    hash(date) mod count."""
    shown = [c for c in cats if c["cover"]]
    since = (today - timedelta(days=CAT_OF_THE_DAY_DAYS)).isoformat()
    recent = [c for c in shown if (c["lastSeenAt"] or "") >= since]
    pool = sorted(recent or shown, key=lambda c: c["catId"])
    if not pool:
        return None
    digest = hashlib.sha256(today.isoformat().encode()).digest()
    return pool[int.from_bytes(digest[:8], "big") % len(pool)]["catId"]


def _israel_today():
    return datetime.now(UTC).astimezone(ISRAEL).date()


def _get_cats(**_):
    cats = _cats()
    counters = _counters([c["catId"] for c in cats])
    today = _israel_today()
    gpa = grades(counters, today)
    listed = []
    for cat in cats:
        cat_id = cat["catId"]
        cover = next(iter(_photos_of(cat_id, newest_first=False, limit=1)), None)
        listed.append(
            public_cat(cat, counters.get(cat_id, {}), cover, gpa.get(cat_id))
        )
    return {"cats": listed, "catOfTheDay": cat_of_the_day(listed, today)}


def _get_cat(user, cat_id, **_):
    cat = tables.get_one(data_table, f"CAT#{cat_id}")
    if cat is None:
        raise ApiError(404, "no such cat", code="gone")
    public = tables.get_one(social_table, f"CAT#{cat_id}", "PUBLIC") or {}
    photos = _photos_of(cat_id, newest_first=True, limit=CAT_PAGE_PHOTOS)
    oldest = next(iter(_photos_of(cat_id, newest_first=False, limit=1)), None)
    # A grade is relative to the most popular cat, so it needs them all.
    gpa = grades(_counters([c["catId"] for c in _cats()]), _israel_today())
    return {
        "cat": {
            **public_cat(cat, public, oldest, gpa.get(cat_id)),
            "bio": cat.get("bio") or "",
            "met": _met(user, cat_id),
            "photos": [
                {
                    "photoId": p["photoId"],
                    **media.photo_urls(s3, MEDIA_BUCKET, p["photoId"]),
                }
                for p in photos
            ],
        }
    }


def _met(user, cat_id):
    """The caller and this cat: how often and since when (B3b), or None."""
    item = tables.get_one(social_table, user["PK"], f"MET#{cat_id}")
    if item is None:
        return None
    return {
        "encounters": _number(item.get("encounters")),
        "days": _number(item.get("days")),
        "firstDay": item.get("firstDay"),
        "lastDay": item.get("lastDay"),
    }


# --------------------------------------------------------------------------
# The name poll (B4)
# --------------------------------------------------------------------------

SUGGESTIONS_PER_DAY = 10
SUGGESTIONS_PER_CAT_PER_DAY = 3
VOTES_PER_HOUR = 60
# A vote reads, then writes on the condition that what it read still holds;
# someone else's vote in between means reading again.
VOTE_ATTEMPTS = 4


def _require_cat(cat_id):
    cat = tables.get_one(data_table, f"CAT#{cat_id}")
    if cat is None:
        raise ApiError(404, "no such cat", code="gone")
    return cat


def _admins_name(cat):
    """(key, name) of the name the admins gave the cat, or (None, None). It
    stands in the poll from the start, so people can vote to keep it."""
    try:
        name = polls.clean_name(cat.get("name"))
    except ApiError:
        return None, None  # none, or one the poll cannot hold
    return name.casefold(), name


def _options(cat_id):
    return tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(f"CAT#{cat_id}")
        & Key("SK").begins_with("NAME#"),
        ConsistentRead=True,
    )


def _names_view(cat, user):
    """The poll as this person may see it: the live options with their
    votes, most first; their own vote; and their own suggestion while it is
    being checked or if it was refused. Nobody else's pending name."""
    cat_id, me = cat["catId"], user["userId"]
    options = _options(cat_id)
    public = tables.get_one(social_table, f"CAT#{cat_id}", "PUBLIC") or {}
    vote = tables.get_one(social_table, f"CAT#{cat_id}", f"VOTE#{me}")
    mine = vote["nameKey"] if vote else None
    # A vote for a name an admin has since removed is no vote (it is deleted
    # a moment later, by the events Lambda).
    if mine and any(
        o["nameKey"] == mine and o["status"] in ("removed", "rejected") for o in options
    ):
        mine = None

    live = [o for o in options if o["status"] == "live"]
    key, name = _admins_name(cat)
    if key and key not in {o["nameKey"] for o in options}:
        live.append({"nameKey": key, "name": name, "votes": 0, "createdAt": ""})
    live.sort(key=lambda o: (-_number(o.get("votes")), o.get("createdAt") or "", o["nameKey"]))
    own = [
        o
        for o in options
        if o.get("suggestedBy") == me and o["status"] in ("pending", "rejected")
    ]
    own.sort(key=lambda o: o.get("createdAt") or "")

    # The leader as these options make it, not as the events Lambda last
    # wrote it: the page that just voted must not show the vote and the old
    # name together. The same rule as `lead` in src/events/handler.py.
    leader = polls.leader(live)
    locked = public.get("lockedName")

    def shown(option, **extra):
        return {
            "nameKey": option["nameKey"],
            "name": option["name"],
            "votes": _number(option.get("votes")),
            "leading": option is leader,
            "mine": option["nameKey"] == mine,
            **extra,
        }

    shown_now, source = shown_name(
        cat, {"lockedName": locked, "leaderName": leader["name"] if leader else None}
    )
    return {
        "catId": cat_id,
        "name": shown_now,
        "nameSource": source,
        "options": [shown(o) for o in live]
        + [shown(o, pending=True) for o in own if o["status"] == "pending"],
        "total": sum(_number(o.get("votes")) for o in live),
        "locked": locked,
        "myVote": mine,
        "mySuggestion": {"name": own[-1]["name"], "status": own[-1]["status"]}
        if own
        else None,
    }


def _get_names(user, cat_id, **_):
    return _names_view(_require_cat(cat_id), user)


def _votes_change(cat_id, option, by):
    """One option's count moved by `by`, for a transaction, on the condition
    that the option is still in the state it was read in: the total counts
    live options only, so a name going live between the read and the write
    must fail the write, not be miscounted."""
    return {
        "Update": {
            "TableName": social_table.name,
            "Key": polls.option_key(cat_id, option["nameKey"]),
            "UpdateExpression": "ADD votes :by",
            "ConditionExpression": "#status = :status",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":by": by, ":status": option["status"]},
        }
    }


def _move_vote(cat, user, new_key, create=None):
    """The caller's vote moves to `new_key` (None takes it back), in one
    transaction (03-data-model.md, "Writes that must be all-or-nothing"):
    one off the old option, one on the new, the vote item itself, and the
    cat's total if a live option gained or lost. The vote item must still
    say what was read, so two taps at once cannot count twice.

    `create` is a new option to write with the vote: a suggestion."""
    cat_id, me = cat["catId"], user["userId"]
    client = social_table.meta.client
    for _ in range(VOTE_ATTEMPTS):
        vote = tables.get_one(social_table, f"CAT#{cat_id}", f"VOTE#{me}")
        old_key = vote["nameKey"] if vote else None
        if old_key == new_key:
            return
        items, total = [], 0
        if old_key:
            old = tables.get_one(social_table, f"CAT#{cat_id}", f"NAME#{old_key}")
            # A name an admin removed or the check refused is out of the
            # poll and its count is no longer this vote's to change: the
            # events Lambda takes its votes away as a whole (`remove_name`).
            if old and old["status"] in ("live", "pending"):
                items.append(_votes_change(cat_id, old, -1))
                total -= old["status"] == "live"
        if new_key:
            new = tables.get_one(social_table, f"CAT#{cat_id}", f"NAME#{new_key}")
            if new is None and create is None:
                raise ApiError(404, "no such name in this poll", code="gone")
            if new is None:
                items.append(
                    {
                        "Put": {
                            "TableName": social_table.name,
                            "Item": create,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    }
                )
                total += create["status"] == "live"
            else:
                if new["status"] in ("rejected", "removed"):
                    raise ApiError(409, "this name was not accepted", code="not_accepted")
                if new["status"] == "pending" and new.get("suggestedBy") != me:
                    raise ApiError(
                        409, "that name is being checked; try again", code="try_again"
                    )
                items.append(_votes_change(cat_id, new, 1))
                total += new["status"] == "live"
            was = (
                {
                    "ConditionExpression": "nameKey = :old",
                    "ExpressionAttributeValues": {":old": old_key},
                }
                if old_key
                else {"ConditionExpression": "attribute_not_exists(PK)"}
            )
            at = api.now_iso()
            items.append(
                {
                    "Put": {
                        "TableName": social_table.name,
                        "Item": {
                            **polls.vote_key(cat_id, me),
                            "catId": cat_id,
                            "userId": me,
                            "nameKey": new_key,
                            "at": at,
                            # In the feed's index, where a friend's vote
                            # becomes a card (`_vote_card`). One item per
                            # person per cat, so a changed vote moves and a
                            # vote taken back is gone from the feed too.
                            "GSI2PK": f"FEED#{_month(at)}",
                            "GSI2SK": f"{at}#V#{cat_id}#{me}",
                        },
                        **was,
                    }
                }
            )
        else:
            items.append(
                {
                    "Delete": {
                        "TableName": social_table.name,
                        "Key": polls.vote_key(cat_id, me),
                        "ConditionExpression": "nameKey = :old",
                        "ExpressionAttributeValues": {":old": old_key},
                    }
                }
            )
        if total:
            items.append(_cat_counts(cat_id, voteTotal=total))
        try:
            client.transact_write_items(TransactItems=items)
            return
        except client.exceptions.TransactionCanceledException:
            continue  # the poll moved under this vote: read it again
    raise ApiError(503, "the poll is busy; try again", code="try_again")


def _suggest_name(user, cat_id, body, **_):
    """`POST /cats/{id}/names`: a name for the poll. One that is already an
    option, whatever its capitals, is a vote for it. A new one is written
    as pending with its author's vote and is theirs alone until it has been
    checked (the events Lambda, where moderation goes, C1)."""
    require_terms(user)
    cat = _require_cat(cat_id)
    name = polls.clean_name(body.get("name"))
    key, me = name.casefold(), user["userId"]
    if tables.get_one(social_table, f"CAT#{cat_id}", f"NAME#{key}"):
        limits.take(social_table, f"{me}#votes", VOTES_PER_HOUR, 3600)
        _move_vote(cat, user, key)
        return _names_view(cat, user)

    limits.take(social_table, f"{me}#suggestions", SUGGESTIONS_PER_DAY, 86400)
    limits.take(
        social_table, f"{me}#suggestions#{cat_id}", SUGGESTIONS_PER_CAT_PER_DAY, 86400
    )
    # The admins' own name needs no check: everyone reads it already.
    admins_key, admins_name = _admins_name(cat)
    theirs = key == admins_key
    option = {
        **polls.option_key(cat_id, key),
        "catId": cat_id,
        "nameKey": key,
        "name": admins_name if theirs else name,
        "votes": 1,
        "status": "live" if theirs else "pending",
        "createdAt": api.now_iso(),
    }
    if not theirs:
        option["suggestedBy"] = me
    _move_vote(cat, user, key, create=option)
    return _names_view(cat, user)


def _vote(user, cat_id, body, **_):
    """`PUT /cats/{id}/vote`: the caller's one vote on this cat, moved."""
    require_terms(user)
    cat = _require_cat(cat_id)
    key = body.get("nameKey")
    if not isinstance(key, str) or not key:
        raise ApiError(400, "nameKey is the option to vote for")
    limits.take(social_table, f"{user['userId']}#votes", VOTES_PER_HOUR, 3600)
    create = None
    admins_key, admins_name = _admins_name(cat)
    if key == admins_key:
        # The first vote for the admins' own name writes it into the poll.
        create = {
            **polls.option_key(cat_id, key),
            "catId": cat_id,
            "nameKey": key,
            "name": admins_name,
            "votes": 1,
            "status": "live",
            "createdAt": api.now_iso(),
        }
    _move_vote(cat, user, key, create=create)
    return _names_view(cat, user)


def _unvote(user, cat_id, **_):
    """`DELETE /cats/{id}/vote`: taken back. Not voting is not writing, so
    it needs neither the terms nor a place in the hour's votes."""
    cat = _require_cat(cat_id)
    _move_vote(cat, user, None)
    return _names_view(cat, user)


# --------------------------------------------------------------------------
# Achievements (B7)
# --------------------------------------------------------------------------


def _get_achievements(user, **_):
    """`GET /achievements`: points and the level they make, the counters,
    and every badge with whether it is earned. All of it is the events
    Lambda's bookkeeping, a second or two behind, except "Dean's List",
    which is asked of the cats as they stand: you have met every cat whose
    grade is at or over the mark, while there is such a cat."""
    rules = achievements.rules()
    stats = tables.get_one(social_table, user["PK"], "STATS#ALL") or {}
    mine = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(user["PK"]),
        ConsistentRead=True,
    )
    held = {
        i["SK"].removeprefix("BADGE#"): i["at"]
        for i in mine
        if i["SK"].startswith("BADGE#")
    }
    met = {i["catId"] for i in mine if i["SK"].startswith("MET#")}
    mark = rules["badges"]["deans-list"]["gpa"]
    gpa = grades(_counters([c["catId"] for c in _cats()]), _israel_today())
    top = {cat for cat, grade in gpa.items() if grade >= mark}
    feeding = bool(FLAGS.get("feeding"))
    # What encounters earned and what feedings earned are kept apart, each
    # by its own recount (the events Lambda), and added here.
    points = _number(stats.get("points")) + (
        _number(stats.get("fedPoints")) if feeding else 0
    )
    return {
        "points": points,
        "level": achievements.level_of(points),
        "counters": {
            "catsMet": _number(stats.get("catsMet")),
            "encounters": _number(stats.get("encounters")),
            "posts": _number(stats.get("posts")),
            **({"catsFed": _number(stats.get("catsFed"))} if feeding else {}),
        },
        "badges": [
            {
                "id": badge,
                "earned": bool(top) and top <= met
                if badge == "deans-list"
                else badge in held,
                "at": held.get(badge),
            }
            for badge in rules["badges"]
            if feeding or badge != "snack-giver"
        ],
        "rules": [
            *([{"id": "feed", "points": rules["points"]["feed"]}] if feeding else []),
            {"id": "post", "points": rules["points"]["post"]},
        ],
    }


# --------------------------------------------------------------------------
# Feedings (B7c, D10)
# --------------------------------------------------------------------------

FEEDINGS_PER_DAY = 6
FEED_AGAIN_AFTER_S = 4 * 3600


def _clock():
    return time.time()


def _feed(user, cat_id, body, **_):
    """`POST /cats/{id}/feedings`: the caller fed this cat, now.

    One log per cat per person every four hours, held by a pointer item
    whose condition is the rule, so two phones at once cannot both pass;
    six logs a day. The same `feedingId` again answers as the first time.
    Writes the feeding under the cat (which the events Lambda follows: the
    cat's "last fed", the person's points) and a copy under the person,
    which is how their feedings are counted again from nothing."""
    if not FLAGS.get("feeding"):
        raise ApiError(404, "not found")
    feeding_id = api.ulid_param(body, "feedingId")
    spot_id = body.get("spotId")
    if spot_id is not None and spot_id not in regions.feeding_spot_ids():
        raise ApiError(400, "spotId is not a feeding spot")
    _require_cat(cat_id)
    me = user["userId"]
    pointer = tables.get_one(social_table, user["PK"], f"FEDCAT#{cat_id}")
    if pointer and pointer.get("feedingId") == feeding_id:
        return {"lastFedAt": pointer["at"], "feedingId": feeding_id}  # asked twice

    now = _clock()
    again = int(_number((pointer or {}).get("atS"))) + FEED_AGAIN_AFTER_S
    too_soon = ApiError(
        429,
        "You logged a feeding for this cat a short while ago.",
        code="too_soon",
        details={"retryAfter": max(1, math.ceil(again - now))},
    )
    if pointer and now < again:
        raise too_soon
    limits.take(social_table, f"{me}#feedings", FEEDINGS_PER_DAY, 86400, now=now)

    at = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    feeding = {
        "feedingId": feeding_id,
        "catId": cat_id,
        "userId": me,
        "at": at,
        "day": encounters.day_of(at),
        **({"spotId": spot_id} if spot_id else {}),
    }
    client = social_table.meta.client
    name = social_table.name
    new = {"ConditionExpression": "attribute_not_exists(PK)"}
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": name,
                        "Item": {"PK": f"CAT#{cat_id}", "SK": f"FED#{at}#{me}", **feeding},
                        **new,
                    }
                },
                {
                    "Put": {
                        "TableName": name,
                        "Item": {"PK": user["PK"], "SK": f"FED#{at}#{cat_id}", **feeding},
                        **new,
                    }
                },
                {
                    "Put": {
                        "TableName": name,
                        "Item": {
                            "PK": user["PK"],
                            "SK": f"FEDCAT#{cat_id}",
                            "catId": cat_id,
                            "feedingId": feeding_id,
                            "at": at,
                            "atS": int(now),
                        },
                        "ConditionExpression": "attribute_not_exists(PK) OR atS <= :before",
                        "ExpressionAttributeValues": {
                            ":before": int(now) - FEED_AGAIN_AFTER_S
                        },
                    }
                },
            ]
        )
    except client.exceptions.TransactionCanceledException:
        raise too_soon from None  # another phone of theirs got there first
    return {"lastFedAt": at, "feedingId": feeding_id}


# --------------------------------------------------------------------------
# Friends (B5)
# --------------------------------------------------------------------------
#
# People become friends through an invite link, at once: sharing your link
# is consent (D4). A friendship is two items, one under each person, always
# written and deleted together (03-data-model.md, invariant 5).

INVITES_PER_DAY = 30
PERIODS = ("month", "all")
LATEST_CATS = 3


def _friendships(user_id):
    """{friendId: the FRIEND item}, for one person."""
    items = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
        & Key("SK").begins_with("FRIEND#"),
        ConsistentRead=True,
    )
    return {item["SK"].removeprefix("FRIEND#"): item for item in items}


def _friend_key(a, b):
    return {"PK": f"USER#{a}", "SK": f"FRIEND#{b}"}


def person(profile, friendship, me):
    """A person as others see them (04-api.md). Never their email, and only
    what has been published: a name or a photo still being checked is its
    owner's alone. tests/app/test_friends.py lists every key."""
    return {
        "userId": profile["userId"],
        "username": profile["username"],
        "displayName": profile["displayName"],
        "avatar": _avatar_url(profile.get("avatarKey")),
        "since": profile["createdAt"],
        "friend": "yes" if friendship else "no",
        "friendSince": friendship["since"] if friendship else None,
        "me": profile["userId"] == me,
    }


def _found(user_id, period="all"):
    sk = "STATS#ALL" if period == "all" else f"STATS#{_israel_today().isoformat()[:7]}"
    stats = tables.get_one(social_table, f"USER#{user_id}", sk) or {}
    return _number(stats.get("catsMet"))


def _require_person(user_id, me=None):
    """The person's profile, or 404: nobody, an account that is banned or
    going away, or (given `me`) someone a block keeps apart from the caller,
    who is told nothing more than that."""
    profile = tables.get_one(social_table, f"USER#{user_id}", "PROFILE")
    if profile is None or profile.get("status") != "active":
        raise ApiError(404, "no such person", code="gone")
    if me and me != user_id and user_id in _hidden(me):
        raise ApiError(404, "no such person", code="gone")
    return profile


def _get_invite(user, **_):
    """`GET /me/invite`: the code. The link is the phone's to build, from
    the address it was opened at."""
    return {"code": user["inviteCode"]}


def _accept_invite(user, code, **_):
    """`POST /invites/{code}/accept`: the caller and the code's owner are
    friends, both ways, in one transaction. The same answer whether they
    just became friends or were already; `gone` for a code nobody has, and
    for a block between the two, which says nothing more than that."""
    require_terms(user)
    me = user["userId"]
    limits.take(social_table, f"{me}#invites", INVITES_PER_DAY, 86400)
    invite = tables.get_one(social_table, f"INVITE#{code}")
    other = invite and tables.get_one(
        social_table, f"USER#{invite['userId']}", "PROFILE"
    )
    if not other or other.get("status") != "active":
        raise ApiError(404, "this invite does not work", code="gone")
    them = other["userId"]
    if them == me:
        raise ApiError(409, "this is your own invite", code="own_invite")
    now, pairs = api.now_iso(), ((me, them), (them, me))
    client = social_table.meta.client
    items = [
        {
            "Put": {
                "TableName": social_table.name,
                "Item": {
                    **_friend_key(a, b),
                    "userId": a,
                    "friendId": b,
                    "since": now,
                    "via": "invite",
                    # Who accepted: the other one's link it was (the
                    # events Lambda tells them, B9).
                    "by": me,
                },
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
        for a, b in pairs
    ] + [
        {
            "ConditionCheck": {
                "TableName": social_table.name,
                "Key": {"PK": f"USER#{a}", "SK": f"BLOCK#{b}"},
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
        for a, b in pairs
    ]
    try:
        client.transact_write_items(TransactItems=items)
        logger.info("friends user=%s and user=%s via invite", me, them)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if "ConditionalCheckFailed" in reasons[2:]:
            raise ApiError(404, "this invite does not work", code="gone") from None
        if "ConditionalCheckFailed" not in reasons[:2]:
            raise
        # Friends already: the same answer.
    friendship = tables.get_one(social_table, f"USER#{me}", f"FRIEND#{them}")
    return {"person": {**person(other, friendship, me), "found": _found(them)}}


def _remove_friend(user, user_id, **_):
    """`DELETE /friends/{userId}`: both sides, together. Removing someone
    who is not a friend removes nothing and says the same."""
    me = user["userId"]
    if user_id != me:
        social_table.meta.client.transact_write_items(
            TransactItems=[
                {"Delete": {"TableName": social_table.name, "Key": _friend_key(a, b)}}
                for a, b in ((me, user_id), (user_id, me))
            ]
        )
    return {"userId": user_id, "friend": "no"}


def _latest_cats(user_id):
    """The ids of the cats a person met last, newest first. Names and
    photos are the cat list's, which the phone already holds."""
    met = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
        & Key("SK").begins_with("MET#"),
    )
    met.sort(key=lambda m: (m.get("lastDay") or "", m["catId"]), reverse=True)
    return [m["catId"] for m in met[:LATEST_CATS]]


def _get_friends(user, query, **_):
    """`GET /friends?period=month|all`: the caller and their friends, whoever
    found the most cats in the period first. The podium is the first
    three."""
    period = query.get("period") or "month"
    if period not in PERIODS:
        raise ApiError(400, f"period is one of {', '.join(PERIODS)}")
    me = user["userId"]
    friendships = _friendships(me)
    stats_sk = (
        "STATS#ALL" if period == "all" else f"STATS#{_israel_today().isoformat()[:7]}"
    )
    ids = [me, *friendships]
    found = _batch_get(
        social_table,
        [{"PK": f"USER#{i}", "SK": sk} for i in ids for sk in ("PROFILE", stats_sk)],
    )
    profiles = {i["userId"]: i for i in found if i["SK"] == "PROFILE"}
    stats = {i["PK"].removeprefix("USER#"): i for i in found if i["SK"] == stats_sk}
    people = []
    for user_id in ids:
        profile = profiles.get(user_id)
        if profile is None or profile.get("status") != "active":
            continue
        row = person(profile, friendships.get(user_id), me)
        if user_id == me:
            # Their own row as they see themselves elsewhere (`GET /me`).
            row["displayName"] = profile.get("pendingName") or profile["displayName"]
            row["avatar"] = _avatar_url(
                profile.get("pendingAvatarKey") or profile.get("avatarKey")
            )
        row["found"] = _number(stats.get(user_id, {}).get("catsMet"))
        row["cats"] = _latest_cats(user_id)
        people.append(row)
    people.sort(
        key=lambda p: (-p["found"], (p["displayName"] or "").casefold(), p["userId"])
    )
    # No requests in this build: an invite link is instant (D4).
    return {"period": period, "people": people, "requests": 0}


def _get_user(user, user_id, **_):
    """`GET /users/{userId}`: a person as others see them."""
    me = user["userId"]
    profile = _require_person(user_id, me)
    friendship = (
        None
        if user_id == me
        else tables.get_one(social_table, f"USER#{me}", f"FRIEND#{user_id}")
    )
    # Friends in common: how many, never who (B5). None on one's own page.
    mutual = (
        None
        if user_id == me
        else len(set(_friendships(me)) & set(_friendships(user_id)) - _hidden(me))
    )
    return {
        "person": {
            **person(profile, friendship, me),
            "found": _found(user_id),
            "cats": _latest_cats(user_id),
            "mutual": mutual,
        }
    }


def _user_posts(user, user_id, **_):
    """`GET /users/{userId}/posts`: what everyone may see of theirs (D3:
    the whole campus reads every visible post)."""
    _require_person(user_id, user["userId"])
    items = social_table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"AUTHOR#{user_id}"),
        ScanIndexForward=False,
        Limit=FEED_QUERY,
    )["Items"]
    visible = [i for i in items if i.get("status") == "visible"][:FEED_PAGE]
    return {"cards": _cards(visible, user)}


# --------------------------------------------------------------------------
# Blocks (B8)
# --------------------------------------------------------------------------
#
# Blocking a person hides each from the other everywhere and ends the
# friendship (06-moderation.md, "Reports, blocks and bans"; Apple's rule
# 1.2). A block is two items, `BLOCK#` under the one who blocked and
# `BLOCKEDBY#` under the other, so "whom must I not see, and who must not
# see me" is one read of one's own partition.

BLOCKS_PER_DAY = 50


def _hidden(user_id):
    """The people this person and the app keep apart: everyone they blocked
    and everyone who blocked them. Neither sees the other's posts or page."""
    items = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
        & Key("SK").begins_with("BLOCK"),  # BLOCK# and BLOCKEDBY#
        ConsistentRead=True,
    )
    return {item["SK"].split("#", 1)[1] for item in items}


def _block_pair(me, them):
    return (
        {"PK": f"USER#{me}", "SK": f"BLOCK#{them}"},
        {"PK": f"USER#{them}", "SK": f"BLOCKEDBY#{me}"},
    )


def _block(user, user_id, **_):
    """`PUT /blocks/{userId}`: the block and its mirror, and the end of the
    friendship both ways, in one transaction. Blocking twice is blocking
    once."""
    me = user["userId"]
    if user_id == me:
        raise ApiError(400, "that is you")
    if tables.get_one(social_table, f"USER#{user_id}", "PROFILE") is None:
        raise ApiError(404, "no such person", code="gone")
    limits.take(social_table, f"{me}#blocks", BLOCKS_PER_DAY, 86400)
    now = api.now_iso()
    mine, theirs = _block_pair(me, user_id)
    social_table.meta.client.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": social_table.name,
                    "Item": {**mine, "userId": me, "blockedId": user_id, "at": now},
                }
            },
            {
                "Put": {
                    "TableName": social_table.name,
                    "Item": {**theirs, "userId": user_id, "blockerId": me, "at": now},
                }
            },
            *(
                {"Delete": {"TableName": social_table.name, "Key": _friend_key(a, b)}}
                for a, b in ((me, user_id), (user_id, me))
            ),
        ]
    )
    logger.info("user=%s blocked user=%s", me, user_id)
    return {"userId": user_id, "blocked": True}


def _unblock(user, user_id, **_):
    """`DELETE /blocks/{userId}`: both items. They are not friends again:
    that takes a new invite."""
    mine, theirs = _block_pair(user["userId"], user_id)
    social_table.meta.client.transact_write_items(
        TransactItems=[
            {"Delete": {"TableName": social_table.name, "Key": key}}
            for key in (mine, theirs)
        ]
    )
    return {"userId": user_id, "blocked": False}


def _get_blocks(user, **_):
    """`GET /blocks`: the people the caller blocked, newest first, so there
    is somewhere to unblock from. Not those who blocked the caller: nobody
    is told that."""
    items = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(user["PK"]) & Key("SK").begins_with("BLOCK#"),
        ConsistentRead=True,
    )
    items.sort(key=lambda i: i["at"], reverse=True)
    profiles = {
        p["userId"]: p
        for p in _batch_get(
            social_table,
            [{"PK": f"USER#{i['blockedId']}", "SK": "PROFILE"} for i in items],
        )
    }
    return {
        "people": [
            {**_person_brief(profiles[i["blockedId"]]), "at": i["at"]}
            for i in items
            if i["blockedId"] in profiles
        ]
    }


# --------------------------------------------------------------------------
# Reports (B8)
# --------------------------------------------------------------------------

REPORTS_PER_DAY = 20


def _report_target(user, target_type, target_id):
    """The thing reported, checked to be there; and whose it is, for the
    desk. None if there is no such thing."""
    if target_type == "post":
        post = tables.get_one(social_table, f"POST#{target_id}")
        if post is None or post.get("status") == "removed":
            return None
        return post["authorId"]
    if target_type in ("user", "avatar"):
        profile = tables.get_one(social_table, f"USER#{target_id}", "PROFILE")
        return profile["userId"] if profile else None
    cat_id, _, name_key = target_id.partition("/")
    option = tables.get_one(social_table, f"CAT#{cat_id}", f"NAME#{name_key}")
    return (option.get("suggestedBy") or "") if option else None


def _report(user, body, **_):
    """`POST /reports`: one person says a post, a person, a photo or a name
    should not be here, with a reason from the list. It joins the desk's
    queue; the events Lambda emails the admins and, for a post, hides it
    once enough different people have said so.

    The answer is always the same: a reporter learns nothing about earlier
    reports, nor whether the thing still exists. One report per person per
    thing counts; a second is accepted and changes nothing."""
    me = user["userId"]
    report_id = api.ulid_param(body, "reportId")
    target_type, target_id, reason = (
        body.get("targetType"),
        body.get("targetId"),
        body.get("reason"),
    )
    if target_type not in reports.TARGETS:
        raise ApiError(400, f"targetType is one of {', '.join(reports.TARGETS)}")
    if not isinstance(target_id, str) or not 0 < len(target_id) <= 120:
        raise ApiError(400, "targetId is what is reported")
    if reason not in reports.REASONS:
        raise ApiError(400, f"reason is one of {', '.join(reports.REASONS)}")
    note = text.clean(
        body.get("note"), "note", reports.NOTE_MAX, required=False, multiline=True
    )
    limits.take(social_table, f"{me}#reports", REPORTS_PER_DAY, 86400)
    answer = {"reported": True}
    owner = _report_target(user, target_type, target_id)
    if owner is None or owner == me:
        return answer  # nothing there, or their own: nothing to queue
    now = api.now_iso()
    client = social_table.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": social_table.name,
                        "Item": {
                            **reports.report_key(report_id),
                            "reportId": report_id,
                            "reporterId": me,
                            "targetType": target_type,
                            "targetId": target_id,
                            "targetOwnerId": owner or None,
                            "reason": reason,
                            "note": note,
                            "status": "open",
                            "createdAt": now,
                            "GSI2PK": "REPORTS#open",
                            "GSI2SK": now,
                        },
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Put": {
                        "TableName": social_table.name,
                        "Item": {
                            "PK": reports.reported_pk(target_type, target_id),
                            "SK": f"BY#{me}",
                            "reporterId": me,
                            "reportId": report_id,
                            "at": now,
                        },
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
            ]
        )
        logger.info("report=%s on %s by user=%s", report_id, target_type, me)
    except client.exceptions.TransactionCanceledException:
        pass  # sent twice, or this person reported this before: the same answer
    return answer


# --------------------------------------------------------------------------
# Posts, likes and the feed (B3a)
# --------------------------------------------------------------------------

POST_TEXT_MAX = 280
POST_PHOTOS_MAX = 4
PHOTO_STATES_POSTABLE = ("unlabeled", "labeled")
POSTS_PER_DAY = 20
LIKES_PER_HOUR = 300
FEED_PAGE = 20
FEED_QUERY = 50
FEED_QUERIES = 6
# The month the app began: the feed never looks further back than this.
FEED_START = "2026-11"


def _month(iso):
    return iso[:7]


def _previous_month(month):
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def _encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def _decode_cursor(text_value):
    try:
        return json.loads(base64.urlsafe_b64decode(text_value.encode()))
    except ValueError:
        raise ApiError(400, "not a cursor from this API", code="bad_cursor")


def _batch_get(table, keys):
    """Items by key, any number of them, in no particular order."""
    found, name, client = [], table.name, table.meta.client
    for start in range(0, len(keys), BATCH_GET_LIMIT):
        request = {name: {"Keys": keys[start : start + BATCH_GET_LIMIT]}}
        while request:
            answer = client.batch_get_item(RequestItems=request)
            found += answer["Responses"].get(name, [])
            request = answer.get("UnprocessedKeys") or None
    return found


def _post_photos_ok(session_id, photo_ids, email):
    """The encounter is the caller's, and every photo is in it and has
    finished uploading. 425, "not yet", while one is still on its way: the
    phone's outbox tries again (docs/app-plan/04-api.md, "Conventions")."""
    session = tables.get_one(data_table, f"SESSION#{session_id}")
    if session is None or session.get("channel") != "app":
        raise ApiError(404, "no such encounter", code="gone")
    if session.get("startedBy") != email:
        raise ApiError(403, "this encounter is someone else's", code="not_yours")
    for photo_id in photo_ids:
        photo = tables.get_one(data_table, f"PHOTO#{photo_id}")
        if photo is None or photo.get("status") == "pending":
            raise ApiError(425, "a photo is still uploading", code="not_ready")
        if photo.get("sessionId") != session_id:
            raise ApiError(400, "a photo is not from this encounter")
        if (
            photo.get("status") not in PHOTO_STATES_POSTABLE
            or photo.get("mediaType") == "video"
        ):
            raise ApiError(400, "this photo cannot be posted")
    return session


def _create_post(user, body, **_):
    require_terms(user)
    post_id = api.ulid_param(body, "postId")
    session_id = api.ulid_param(body, "sessionId")
    photo_ids = body.get("photoIds")
    if (
        not isinstance(photo_ids, list)
        or not 1 <= len(photo_ids) <= POST_PHOTOS_MAX
        or len(set(photo_ids)) != len(photo_ids)
    ):
        raise ApiError(400, f"photoIds: one to {POST_PHOTOS_MAX} different photos")
    for photo_id in photo_ids:
        api.ulid_param({"id": photo_id}, "id")
    claim = body.get("claim") or {}
    if (
        not isinstance(claim, dict)
        or len(claim) > 1
        or set(claim) - {"catId", "proposalId"}
    ):
        raise ApiError(400, "claim is {catId}, {proposalId} or nothing")
    cat_id = claim.get("catId")
    if cat_id is not None and tables.get_one(data_table, f"CAT#{cat_id}") is None:
        raise ApiError(400, "no such cat")
    proposal = _claimed_proposal(claim.get("proposalId"), user, session_id)
    words = text.clean(
        body.get("text"), "text", POST_TEXT_MAX, required=False, multiline=True
    )

    existing = tables.get_one(social_table, f"POST#{post_id}")
    if existing is not None:
        if existing.get("authorId") != user["userId"]:
            raise ApiError(409, "that post id is taken")
        return {"post": _cards([existing], user)[0]}  # the same request, sent again

    session = _post_photos_ok(session_id, photo_ids, user["email"])
    place = encounters.place_fields(session)
    region = place["regionId"] if body.get("shareRegion") else None
    enc = tables.get_one(social_table, user["PK"], f"ENC#{session_id}") or {}
    if enc.get("postId") and enc["postId"] != post_id:
        earlier = tables.get_one(social_table, f"POST#{enc['postId']}") or {}
        if earlier.get("status") not in (None, "removed"):
            raise ApiError(
                409, "this encounter is posted already", code="already_posted"
            )
    limits.take(social_table, f"{user['userId']}#posts", POSTS_PER_DAY, 86400)

    now = api.now_iso()
    post = {
        "PK": f"POST#{post_id}",
        "SK": "META",
        "postId": post_id,
        "authorId": user["userId"],
        "sessionId": session_id,
        "photoIds": photo_ids,
        "claimedCatId": cat_id,
        "catId": cat_id,
        # A post for a new cat waits for an admin's decision (D7): the
        # events Lambda publishes it under the decided cat, or never.
        "proposalId": proposal["proposalId"] if proposal else None,
        "text": words,
        "regionId": region,
        "status": "pending",
        "likeCount": 0,
        "createdAt": now,
        # Always: the author sees their own post in every state.
        "GSI1PK": f"AUTHOR#{user['userId']}",
        "GSI1SK": now,
    }
    try:
        social_table.put_item(Item=post, ConditionExpression="attribute_not_exists(PK)")
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        return {
            "post": _cards([tables.get_one(social_table, f"POST#{post_id}")], user)[0]
        }
    # The encounter learns its post, and the events Lambda puts the post on
    # the label's cat when there is one (B3b). Posting without picking
    # still counts as meeting the cat claimed here.
    encounters.update(
        social_table,
        user["userId"],
        session_id,
        {
            **place,
            "userId": user["userId"],
            "claimedCatId": cat_id,
            "postId": post_id,
            "updatedAt": now,
        },
        keep=("claimedCatId",),
    )
    return {"post": _cards([post], user)[0]}


def _claimed_proposal(proposal_id, user, session_id):
    """The caller's own proposal for this encounter, if the post names one."""
    if proposal_id is None:
        return None
    api.ulid_param({"proposalId": proposal_id}, "proposalId")
    proposal = tables.get_one(social_table, f"PROPOSAL#{proposal_id}")
    if (
        proposal is None
        or proposal.get("proposerId") != user["userId"]
        or proposal["sessionId"] != session_id
    ):
        raise ApiError(400, "no such proposal for this encounter")
    if proposal["status"] == "rejected":
        raise ApiError(400, "this new cat was not accepted", code="not_accepted")
    return proposal


# --------------------------------------------------------------------------
# New-cat proposals (B6)
# --------------------------------------------------------------------------

PROPOSALS_PER_DAY = 10


def proposal_view(item):
    """What the proposer sees of their proposal. Nobody else sees it until an
    admin decides, and then they see the cat, not the proposal (D7)."""
    return {
        "proposalId": item["proposalId"],
        "sessionId": item["sessionId"],
        "nameIdea": item.get("nameIdea") or "",
        "coat": item.get("coat"),
        "regionId": item.get("regionId"),
        "traits": list(item.get("traits") or []),
        "status": item["status"],
        "catId": item.get("catId"),
        "createdAt": item["createdAt"],
    }


def _own_session(session_id, email):
    session = tables.get_one(data_table, f"SESSION#{session_id}")
    if session is None or session.get("channel") != "app":
        raise ApiError(404, "no such encounter", code="gone")
    if session.get("startedBy") != email:
        raise ApiError(403, "this encounter is someone else's", code="not_yours")
    return session


def _create_proposal(user, body, **_):
    """ "A cat that isn't here": a new cat for an admin to approve, merge into
    a known one, or reject. Its id, made on the phone, becomes the cat's id
    if approved. One proposal per encounter."""
    require_terms(user)
    proposal_id = api.ulid_param(body, "proposalId")
    session_id = api.ulid_param(body, "sessionId")
    idea = text.clean(body.get("nameIdea"), "nameIdea", 24, required=False)
    coat = body.get("coat")
    if coat is not None and coat not in proposals.COATS:
        raise ApiError(400, f"coat is one of {', '.join(proposals.COATS)}")
    region = body.get("regionId")
    if (
        region is not None
        and region != proposals.ELSEWHERE
        and region not in regions.ids()
    ):
        raise ApiError(400, "regionId is not one of the campus places")
    traits = body.get("traits") or []
    if not isinstance(traits, list) or not set(traits) <= set(proposals.TRAITS):
        raise ApiError(400, f"traits are from {', '.join(proposals.TRAITS)}")
    traits = [t for t in proposals.TRAITS if t in traits]  # one order, no repeats

    existing = tables.get_one(social_table, f"PROPOSAL#{proposal_id}")
    if existing is not None:
        if existing.get("proposerId") != user["userId"]:
            raise ApiError(409, "that proposal id is taken")
        return {"proposal": proposal_view(existing)}  # the same request, again

    session = _own_session(session_id, user["email"])
    enc = tables.get_one(social_table, user["PK"], f"ENC#{session_id}") or {}
    if enc.get("proposalId") and enc["proposalId"] != proposal_id:
        earlier = tables.get_one(social_table, f"PROPOSAL#{enc['proposalId']}") or {}
        if earlier.get("status") != "rejected":
            raise ApiError(
                409, "this encounter has a proposal already", code="already_proposed"
            )
    limits.take(social_table, f"{user['userId']}#proposals", PROPOSALS_PER_DAY, 86400)

    now = api.now_iso()
    item = {
        "PK": f"PROPOSAL#{proposal_id}",
        "SK": "META",
        "proposalId": proposal_id,
        "proposerId": user["userId"],
        "sessionId": session_id,
        "nameIdea": idea,
        "coat": coat,
        "regionId": region,
        "traits": traits,
        "status": "open",
        "createdAt": now,
        # The desk's queue, by status; and the proposer's own list.
        "GSI2PK": "PROPOSALS#open",
        "GSI2SK": now,
        "GSI1PK": f"PROPOSER#{user['userId']}",
        "GSI1SK": now,
    }
    try:
        social_table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        item = tables.get_one(social_table, f"PROPOSAL#{proposal_id}")
        return {"proposal": proposal_view(item)}
    # The encounter's claim is "a new cat": nobody, until an admin decides.
    encounters.update(
        social_table,
        user["userId"],
        session_id,
        {
            **encounters.place_fields(session),
            "userId": user["userId"],
            "claimedCatId": None,
            "proposalId": proposal_id,
            "updatedAt": now,
        },
    )
    return {"proposal": proposal_view(item)}


def _my_proposals(user, **_):
    items = tables.query_all(
        social_table,
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"PROPOSER#{user['userId']}"),
        ScanIndexForward=False,
    )
    return {"proposals": [proposal_view(i) for i in items]}


def _visible_or_own(post, user):
    if post is None or post.get("status") == "removed":
        raise ApiError(404, "no such post", code="gone")
    if post["status"] != "visible" and post["authorId"] != user["userId"]:
        raise ApiError(404, "no such post", code="gone")
    return post


def _get_post(user, post_id, **_):
    post = _visible_or_own(tables.get_one(social_table, f"POST#{post_id}"), user)
    if post["authorId"] in _hidden(user["userId"]):
        raise ApiError(404, "no such post", code="gone")
    return {"post": _cards([post], user)[0]}


def _delete_post(user, post_id, **_):
    post = tables.get_one(social_table, f"POST#{post_id}")
    if post is None or post.get("status") == "removed":
        return {"removed": post_id}
    if post["authorId"] != user["userId"]:
        raise ApiError(403, "this post is someone else's", code="not_yours")
    client = social_table.meta.client
    items = [
        {
            "Update": {
                "TableName": social_table.name,
                "Key": {"PK": f"POST#{post_id}", "SK": "META"},
                "UpdateExpression": "SET #s = :removed, removedAt = :now "
                "REMOVE GSI2PK, GSI2SK, GSI3PK, GSI3SK",
                "ConditionExpression": "#s = :was",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {
                    ":removed": "removed",
                    ":was": post["status"],
                    ":now": api.now_iso(),
                },
            }
        }
    ]
    if post["status"] == "visible" and post.get("catId"):
        items.append(
            _cat_counts(post["catId"], posts=-1, likes=-int(post.get("likeCount", 0)))
        )
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException:
        raise ApiError(503, "the post changed meanwhile; try again", code="try_again")
    return {"removed": post_id}


def _cat_counts(cat_id, **deltas):
    """One update of a cat's public counters, for a transaction."""
    names = {f"#{k}": k for k in deltas}
    values = {f":{k}": v for k, v in deltas.items()}
    return {
        "Update": {
            "TableName": social_table.name,
            "Key": {"PK": f"CAT#{cat_id}", "SK": "PUBLIC"},
            "UpdateExpression": "ADD " + ", ".join(f"#{k} :{k}" for k in deltas),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
    }


def _like(user, post_id, **_):
    require_terms(user)
    limits.take(social_table, f"{user['userId']}#likes", LIKES_PER_HOUR, 3600)
    post = tables.get_one(social_table, f"POST#{post_id}")
    if post is None or post.get("status") != "visible":
        raise ApiError(404, "no such post", code="gone")
    client = social_table.meta.client
    items = [
        {
            "Put": {
                "TableName": social_table.name,
                "Item": {
                    "PK": f"POST#{post_id}",
                    "SK": f"LIKE#{user['userId']}",
                    "at": api.now_iso(),
                },
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        _post_likes(post_id, 1, post.get("catId")),
    ]
    if post.get("catId"):
        items.append(_cat_counts(post["catId"], likes=1))
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] != "ConditionalCheckFailed":
            fresh = tables.get_one(social_table, f"POST#{post_id}") or {}
            if fresh.get("status") == "visible":
                # Its cat was corrected between the read and the write.
                raise ApiError(503, "the post changed; try again", code="try_again")
            raise ApiError(404, "no such post", code="gone")
        # Already liked: the same answer as the first time.
    return _like_state(post_id, True)


def _unlike(user, post_id, **_):
    post = tables.get_one(social_table, f"POST#{post_id}")
    if post is None:
        raise ApiError(404, "no such post", code="gone")
    client = social_table.meta.client
    items = [
        {
            "Delete": {
                "TableName": social_table.name,
                "Key": {"PK": f"POST#{post_id}", "SK": f"LIKE#{user['userId']}"},
                "ConditionExpression": "attribute_exists(PK)",
            }
        },
        _post_likes(post_id, -1, post.get("catId")),
    ]
    if post.get("catId") and post.get("status") == "visible":
        items.append(_cat_counts(post["catId"], likes=-1))
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        fresh = tables.get_one(social_table, f"POST#{post_id}") or {}
        if reasons and reasons[0] != "ConditionalCheckFailed" and fresh:
            raise ApiError(503, "the post changed; try again", code="try_again")
        # Not liked, or the post is gone: either way, not liked now.
    return _like_state(post_id, False)


def _post_likes(post_id, delta, cat_id):
    """The post's like count, for a transaction. A like needs the post
    visible; taking one back needs only the post. Both need its cat to be
    the one whose count moves with it: the events Lambda moves a post to
    the label's cat, likes and all (B3b)."""
    values = {":d": delta}
    if cat_id is None:
        values[":nocat"] = None
        same_cat = "(attribute_not_exists(catId) OR catId = :nocat)"
    else:
        values[":cat"] = cat_id
        same_cat = "catId = :cat"
    update = {
        "TableName": social_table.name,
        "Key": {"PK": f"POST#{post_id}", "SK": "META"},
        "UpdateExpression": "ADD likeCount :d",
        "ExpressionAttributeValues": values,
        "ConditionExpression": f"attribute_exists(PK) AND {same_cat}",
    }
    if delta > 0:
        update["ConditionExpression"] = f"#s = :visible AND {same_cat}"
        update["ExpressionAttributeNames"] = {"#s": "status"}
        values[":visible"] = "visible"
    return {"Update": update}


def _like_state(post_id, liked):
    post = tables.get_one(social_table, f"POST#{post_id}") or {}
    return {"postId": post_id, "liked": liked, "likes": _number(post.get("likeCount"))}


def _cat_names(cat_ids):
    """{catId: shown name} for the cats a page of posts names."""
    if not cat_ids:
        return {}
    keys = [{"PK": f"CAT#{c}", "SK": "META"} for c in cat_ids]
    cats = {c["catId"]: c for c in _batch_get(data_table, keys)}
    public = _counters(list(cats))
    return {c: shown_name(cat, public.get(c, {}))[0] for c, cat in cats.items()}


def _cards(posts, user, friends=None):
    """Posts as the app shows them: who, which cat, the photos, the words,
    the likes; the author marked if a friend of the caller's; and the area
    to the author and their friends only (D3: friends see roughly where)."""
    posts = [p for p in posts if p]
    if not posts:
        return []
    if friends is None:
        friends = _friendships(user["userId"])
    author_keys = {p["authorId"] for p in posts}
    authors = {
        a["userId"]: a
        for a in _batch_get(
            social_table, [{"PK": f"USER#{a}", "SK": "PROFILE"} for a in author_keys]
        )
    }
    liked = {
        item["PK"].removeprefix("POST#")
        for item in _batch_get(
            social_table,
            [
                {"PK": f"POST#{p['postId']}", "SK": f"LIKE#{user['userId']}"}
                for p in posts
            ],
        )
    }
    names = _cat_names({p["catId"] for p in posts if p.get("catId")})
    cards = []
    for p in posts:
        author = authors.get(p["authorId"], {})
        mine = p["authorId"] == user["userId"]
        card = {
            "postId": p["postId"],
            "author": {
                "userId": p["authorId"],
                "username": author.get("username"),
                "displayName": author.get("displayName"),
                # The published photo only: one still waiting is its
                # owner's alone (`GET /me`).
                "avatar": _avatar_url(author.get("avatarKey")),
                "friend": "yes" if p["authorId"] in friends else "no",
            },
            "cat": {"catId": p["catId"], "name": names.get(p["catId"])}
            if p.get("catId")
            else None,
            "photos": [
                {"photoId": photo_id, **media.photo_urls(s3, MEDIA_BUCKET, photo_id)}
                for photo_id in p["photoIds"]
            ],
            "text": p.get("text") or "",
            "likes": _number(p.get("likeCount")),
            "liked": p["postId"] in liked,
            "createdAt": p["createdAt"],
            "region": p.get("regionId")
            if mine or p["authorId"] in friends
            else None,
            "mine": mine,
        }
        if mine:
            card["state"] = p["status"]
            if p.get("proposalId"):
                # Only its author sees that a post waits for a new cat (D7).
                proposal = tables.get_one(social_table, f"PROPOSAL#{p['proposalId']}")
                if proposal:
                    card["proposal"] = {
                        "proposalId": proposal["proposalId"],
                        "status": proposal["status"],
                        "nameIdea": proposal.get("nameIdea") or "",
                    }
        cards.append(card)
    return cards


def _person_brief(profile):
    """A person beside something they did: who, and their published photo."""
    return {
        "userId": profile["userId"],
        "username": profile["username"],
        "displayName": profile["displayName"],
        "avatar": _avatar_url(profile.get("avatarKey")),
    }


def _vote_card(cat_id, user, friends):
    """Friends' votes on one cat's name, as one card: "Daniel and Noa voted
    to call Professor Pumpkin 'Mango'", over the poll itself with the
    friends who chose each name. Built from the poll as it is now, not from
    the feed's items, so it holds every friend's vote wherever the page
    ends. None when there is nothing to show: the cat is gone, or no friend
    has a vote on a name that is in the poll."""
    cat = tables.get_one(data_table, f"CAT#{cat_id}")
    if cat is None:
        return None
    poll = _names_view(cat, user)
    in_poll = {o["nameKey"] for o in poll["options"] if not o.get("pending")}
    votes = tables.query_all(
        social_table,
        KeyConditionExpression=Key("PK").eq(f"CAT#{cat_id}")
        & Key("SK").begins_with("VOTE#"),
    )
    theirs = [v for v in votes if v["userId"] in friends and v["nameKey"] in in_poll]
    if not theirs:
        return None
    theirs.sort(key=lambda v: v["at"], reverse=True)
    people = {
        p["userId"]: _person_brief(p)
        for p in _batch_get(
            social_table,
            [{"PK": f"USER#{v['userId']}", "SK": "PROFILE"} for v in theirs],
        )
    }
    theirs = [v for v in theirs if v["userId"] in people]
    if not theirs:
        return None
    newest = theirs[0]
    for option in poll["options"]:
        option["friends"] = [
            people[v["userId"]] for v in theirs if v["nameKey"] == option["nameKey"]
        ]
    chosen = next(o for o in poll["options"] if o["nameKey"] == newest["nameKey"])
    cover = next(iter(_photos_of(cat_id, newest_first=False, limit=1)), None)
    return {
        "type": "vote",
        "cardId": f"vote-{cat_id}",
        "createdAt": newest["at"],
        "cat": {
            "catId": cat_id,
            "name": poll["name"],
            "cover": media.photo_urls(s3, MEDIA_BUCKET, cover["photoId"])
            if cover
            else None,
        },
        # What the newest of the friends' votes says, and who else says it.
        "name": chosen["name"],
        "voters": chosen["friends"],
        "friendsVoted": len(theirs),
        "poll": poll,
    }


def _get_feed(user, query, **_):
    """Newest first, month by month, over the whole campus (D3): posts, and
    friends' name votes folded into one card per cat. At most a page of
    cards and a few queries per call; the cursor says where to go on: the
    month, the last key read inside it, and the cats whose vote card an
    earlier page already carried."""
    state = _decode_cursor(query["cursor"]) if query.get("cursor") else {}
    month = state.get("month") or _month(api.now_iso())
    start_key = state.get("key")
    voted = set(state.get("cats") or [])
    friends = _friendships(user["userId"])
    hidden = _hidden(user["userId"])  # a block, either way: not in this feed
    entries, queries = [], 0  # ("post", item) or ("vote", catId), in order
    while queries < FEED_QUERIES and month >= FEED_START:
        request = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(f"FEED#{month}"),
            "ScanIndexForward": False,
            "Limit": FEED_QUERY,
        }
        if start_key:
            request["ExclusiveStartKey"] = start_key
        page = social_table.query(**request)
        queries += 1
        for item in page["Items"]:
            start_key = {k: item[k] for k in ("PK", "SK", "GSI2PK", "GSI2SK")}
            if "#P#" in item["GSI2SK"]:
                if item["authorId"] not in hidden:
                    entries.append(("post", item))
            elif (
                "#V#" in item["GSI2SK"]
                and item["userId"] in friends
                and item["catId"] not in voted
            ):
                voted.add(item["catId"])
                entries.append(("vote", item["catId"]))
            if len(entries) == FEED_PAGE:
                break
        if len(entries) == FEED_PAGE:
            break
        if "LastEvaluatedKey" in page:
            start_key = page["LastEvaluatedKey"]
            continue
        month, start_key = _previous_month(month), None
    posts = iter(_cards([e for kind, e in entries if kind == "post"], user, friends))
    cards = [
        next(posts) if kind == "post" else _vote_card(entry, user, friends)
        for kind, entry in entries
    ]
    answer = {"cards": [card for card in cards if card]}
    if month >= FEED_START and (len(entries) == FEED_PAGE or queries == FEED_QUERIES):
        answer["cursor"] = _encode_cursor(
            {"month": month, "key": start_key, "cats": sorted(voted)}
        )
    return answer


def _my_posts(user, **_):
    items = tables.query_all(
        social_table,
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"AUTHOR#{user['userId']}"),
        ScanIndexForward=False,
    )
    return {"cards": _cards([i for i in items if i.get("status") != "removed"], user)}


def _cat_posts(user, cat_id, **_):
    items = social_table.query(
        IndexName="GSI3",
        KeyConditionExpression=Key("GSI3PK").eq(f"CATPOST#{cat_id}"),
        ScanIndexForward=False,
        Limit=FEED_PAGE,
    )["Items"]
    hidden = _hidden(user["userId"])
    return {"cards": _cards([i for i in items if i["authorId"] not in hidden], user)}


ID = r"[0-9A-Za-z]+"
# A phone's own name for itself: an id the app makes once and keeps.
DEVICE_ID = r"[0-9A-Za-z-]{8,64}"

ROUTES = (
    ("GET", r"^/api/v1/me$", _get_me, "user"),
    ("PATCH", r"^/api/v1/me$", _update_me, "user"),
    ("DELETE", r"^/api/v1/me$", _delete_me, "user"),
    ("PUT", r"^/api/v1/me/username$", _choose_username, "user"),
    ("POST", r"^/api/v1/me/avatar$", _start_avatar, "user"),
    (
        "POST",
        rf"^/api/v1/me/avatar/(?P<avatar_id>{api.ULID_PATTERN})/complete$",
        _complete_avatar,
        "user",
    ),
    ("DELETE", r"^/api/v1/me/avatar$", _remove_avatar, "user"),
    ("POST", r"^/api/v1/me/terms$", _accept_terms, "user"),
    ("PUT", rf"^/api/v1/me/devices/(?P<device_id>{DEVICE_ID})$", _put_device, "user"),
    ("DELETE", rf"^/api/v1/me/devices/(?P<device_id>{DEVICE_ID})$", _delete_device, "user"),
    ("GET", r"^/api/v1/cats$", _get_cats, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})$", _get_cat, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})/posts$", _cat_posts, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})/names$", _get_names, "user"),
    ("POST", rf"^/api/v1/cats/(?P<cat_id>{ID})/names$", _suggest_name, "user"),
    ("PUT", rf"^/api/v1/cats/(?P<cat_id>{ID})/vote$", _vote, "user"),
    ("DELETE", rf"^/api/v1/cats/(?P<cat_id>{ID})/vote$", _unvote, "user"),
    ("POST", rf"^/api/v1/cats/(?P<cat_id>{ID})/feedings$", _feed, "user"),
    ("GET", r"^/api/v1/feed$", _get_feed, "user"),
    ("POST", r"^/api/v1/posts$", _create_post, "user"),
    ("GET", rf"^/api/v1/posts/(?P<post_id>{ID})$", _get_post, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})$", _delete_post, "user"),
    ("PUT", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _like, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _unlike, "user"),
    ("GET", r"^/api/v1/me/posts$", _my_posts, "user"),
    ("GET", r"^/api/v1/me/invite$", _get_invite, "user"),
    ("GET", r"^/api/v1/achievements$", _get_achievements, "user"),
    ("POST", r"^/api/v1/invites/(?P<code>[a-z0-9]{1,32})/accept$", _accept_invite, "user"),
    ("GET", r"^/api/v1/friends$", _get_friends, "user"),
    ("POST", r"^/api/v1/reports$", _report, "user"),
    ("GET", r"^/api/v1/blocks$", _get_blocks, "user"),
    ("PUT", rf"^/api/v1/blocks/(?P<user_id>{ID})$", _block, "user"),
    ("DELETE", rf"^/api/v1/blocks/(?P<user_id>{ID})$", _unblock, "user"),
    ("DELETE", rf"^/api/v1/friends/(?P<user_id>{ID})$", _remove_friend, "user"),
    ("GET", rf"^/api/v1/users/(?P<user_id>{ID})$", _get_user, "user"),
    ("GET", rf"^/api/v1/users/(?P<user_id>{ID})/posts$", _user_posts, "user"),
    ("POST", r"^/api/v1/proposals$", _create_proposal, "user"),
    ("GET", r"^/api/v1/me/proposals$", _my_proposals, "user"),
)


def _answer(status, payload):
    return api.response(status, payload)


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    if method == "OPTIONS":
        return api.preflight(event)
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
