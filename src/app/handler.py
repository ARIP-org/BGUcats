"""The member API: everything a user does in the app that is not an upload
(docs/app-plan/04-api.md). Behind `ANY /api/v1/{proxy+}` and the same JWT
authorizer as the desk's API.

Kept apart from src/admin on purpose: its role can read the dataset
(bgucats-data) and never write it, and writes only bgucats-social
(infra/main/app_api.tf). Uploads stay on the desk's capture routes, which
keep the write order of spec §10.

Since milestone F4: who you are (`GET /me`, which makes your account on
the first call) and accepting the terms. Since B2: the cats. Since B3a:
posts, likes and the feed. Each later milestone adds its routes to ROUTES.

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

from common import admission, api, ids, limits, media, regions, tables, text
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


def _get_cat(cat_id, **_):
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
            "photos": [
                {
                    "photoId": p["photoId"],
                    **media.photo_urls(s3, MEDIA_BUCKET, p["photoId"]),
                }
                for p in photos
            ],
        }
    }


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
    if not isinstance(claim, dict) or set(claim) - {"catId"}:
        raise ApiError(400, "claim is {catId} or nothing (new cats come with B6)")
    cat_id = claim.get("catId")
    if cat_id is not None and tables.get_one(data_table, f"CAT#{cat_id}") is None:
        raise ApiError(400, "no such cat")
    words = text.clean(
        body.get("text"), "text", POST_TEXT_MAX, required=False, multiline=True
    )

    existing = tables.get_one(social_table, f"POST#{post_id}")
    if existing is not None:
        if existing.get("authorId") != user["userId"]:
            raise ApiError(409, "that post id is taken")
        return {"post": _cards([existing], user)[0]}  # the same request, sent again

    session = _post_photos_ok(session_id, photo_ids, user["email"])
    region = None
    if body.get("shareRegion") and session.get("coarseLat") is not None:
        region = regions.region_at(
            float(session["coarseLat"]), float(session["coarseLon"])
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
    return {"post": _cards([post], user)[0]}


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
        _post_likes(post_id, 1),
    ]
    if post.get("catId"):
        items.append(_cat_counts(post["catId"], likes=1))
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] != "ConditionalCheckFailed":
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
        _post_likes(post_id, -1),
    ]
    if post.get("catId") and post.get("status") == "visible":
        items.append(_cat_counts(post["catId"], likes=-1))
    try:
        client.transact_write_items(TransactItems=items)
    except client.exceptions.TransactionCanceledException:
        pass  # not liked, or the post is gone: either way, not liked now
    return _like_state(post_id, False)


def _post_likes(post_id, delta):
    """The post's like count, for a transaction. A like needs the post
    visible; taking one back needs only the post."""
    update = {
        "TableName": social_table.name,
        "Key": {"PK": f"POST#{post_id}", "SK": "META"},
        "UpdateExpression": "ADD likeCount :d",
        "ExpressionAttributeValues": {":d": delta},
        "ConditionExpression": "attribute_exists(PK)",
    }
    if delta > 0:
        update["ConditionExpression"] = "#s = :visible"
        update["ExpressionAttributeNames"] = {"#s": "status"}
        update["ExpressionAttributeValues"][":visible"] = "visible"
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
    ("POST", r"^/api/v1/me/terms$", _accept_terms, "user"),
    ("GET", r"^/api/v1/cats$", _get_cats, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})$", _get_cat, "user"),
    ("GET", rf"^/api/v1/cats/(?P<cat_id>{ID})/posts$", _cat_posts, "user"),
    ("GET", r"^/api/v1/feed$", _get_feed, "user"),
    ("POST", r"^/api/v1/posts$", _create_post, "user"),
    ("GET", rf"^/api/v1/posts/(?P<post_id>{ID})$", _get_post, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})$", _delete_post, "user"),
    ("PUT", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _like, "user"),
    ("DELETE", rf"^/api/v1/posts/(?P<post_id>{ID})/like$", _unlike, "user"),
    ("GET", r"^/api/v1/me/posts$", _my_posts, "user"),
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
