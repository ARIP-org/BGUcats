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
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key

from common import (
    admission,
    api,
    encounters,
    ids,
    limits,
    media,
    polls,
    proposals,
    regions,
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


def shown_name(cat, public):
    """(name, where it came from): an admin's lock, else the poll's leader,
    else the admin's name (docs/app-plan/03-data-model.md, D6)."""
    if public.get("lockedName"):
        return public["lockedName"], "admin"
    if public.get("leaderName"):
        return public["leaderName"], "poll"
    if cat.get("name"):
        return cat["name"], "admin"
    return None, "none"


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


def public_cat(cat, public, cover):
    """What a user may see of a cat. The desk's own fields (notes, who
    created it) never leave here: tests/app/test_cats.py lists every key."""
    name, source = shown_name(cat, public)
    return {
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
    listed = []
    for cat in cats:
        cover = next(iter(_photos_of(cat["catId"], newest_first=False, limit=1)), None)
        listed.append(public_cat(cat, counters.get(cat["catId"], {}), cover))
    return {"cats": listed, "catOfTheDay": cat_of_the_day(listed, _israel_today())}


def _get_cat(user, cat_id, **_):
    cat = tables.get_one(data_table, f"CAT#{cat_id}")
    if cat is None:
        raise ApiError(404, "no such cat", code="gone")
    public = tables.get_one(social_table, f"CAT#{cat_id}", "PUBLIC") or {}
    photos = _photos_of(cat_id, newest_first=True, limit=CAT_PAGE_PHOTOS)
    oldest = next(iter(_photos_of(cat_id, newest_first=False, limit=1)), None)
    return {
        "cat": {
            **public_cat(cat, public, oldest),
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
    leader = next((o for o in live if _number(o.get("votes")) > 0), None)
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
            if old:
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
            items.append(
                {
                    "Put": {
                        "TableName": social_table.name,
                        "Item": {
                            **polls.vote_key(cat_id, me),
                            "catId": cat_id,
                            "userId": me,
                            "nameKey": new_key,
                            "at": api.now_iso(),
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
        or proposal["proposerId"] != user["userId"]
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
        if existing["proposerId"] != user["userId"]:
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


def _cards(posts, user):
    """Posts as the app shows them: who, which cat, the photos, the words,
    the likes, and the area only to its author until there are friends (B5,
    D3: friends see roughly where)."""
    posts = [p for p in posts if p]
    if not posts:
        return []
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
            "region": p.get("regionId") if mine else None,
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


def _get_feed(user, query, **_):
    """Newest first, month by month, over the whole campus (D3). At most a
    page of cards and a few queries per call; the cursor says where to go
    on: the month, and the last card's key inside it."""
    state = _decode_cursor(query["cursor"]) if query.get("cursor") else {}
    month = state.get("month") or _month(api.now_iso())
    start_key = state.get("key")
    posts, queries = [], 0
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
            if "#P#" in item["GSI2SK"]:  # votes join the feed in B4
                posts.append(item)
                if len(posts) == FEED_PAGE:
                    break
        if len(posts) == FEED_PAGE:
            break
        if "LastEvaluatedKey" in page:
            start_key = page["LastEvaluatedKey"]
            continue
        month, start_key = _previous_month(month), None
    answer = {"cards": _cards(posts, user)}
    if month >= FEED_START and (len(posts) == FEED_PAGE or queries == FEED_QUERIES):
        answer["cursor"] = _encode_cursor({"month": month, "key": start_key})
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
    return {"cards": _cards(items, user)}


ID = r"[0-9A-Za-z]+"

ROUTES = (
    ("GET", r"^/api/v1/me$", _get_me, "user"),
    ("PATCH", r"^/api/v1/me$", _update_me, "user"),
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
    ("GET", r"^/api/v1/cats$", _get_cats, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})$", _get_cat, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})/posts$", _cat_posts, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})/names$", _get_names, "user"),
    ("POST", rf"^/api/v1/cats/(?P<cat_id>{ID})/names$", _suggest_name, "user"),
    ("PUT", rf"^/api/v1/cats/(?P<cat_id>{ID})/vote$", _vote, "user"),
    ("DELETE", rf"^/api/v1/cats/(?P<cat_id>{ID})/vote$", _unvote, "user"),
    ("GET", r"^/api/v1/feed$", _get_feed, "user"),
    ("POST", r"^/api/v1/posts$", _create_post, "user"),
    ("GET", rf"^/api/v1/posts/(?P<post_id>{ID})$", _get_post, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})$", _delete_post, "user"),
    ("PUT", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _like, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _unlike, "user"),
    ("GET", r"^/api/v1/me/posts$", _my_posts, "user"),
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
