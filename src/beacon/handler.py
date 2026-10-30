"""Landing-page counters: visits, first visits of the day, bot-button clicks.

The landing page is the front door — the poster's QR code, a partner's ad and
a link in a group chat all land there — so this is where "where do people
come from" is answered. It is also the only unauthenticated endpoint that
writes anything, so it is built to stay boring under abuse:

- One UpdateItem per request, on a daily counter keyed by a validated slug.
  Nothing is ever created per visitor.
- No cookies, no IP address, no user agent. The page sends an event name, a
  source slug and whether this browser was already counted today; daily
  totals are all that is stored.
- The IAM role can touch TRAFFIC# items and nothing else, and API Gateway
  throttles the route, so a script hammering it can inflate a counter but
  not reach a photo, a session or the bill.

Every request gets a 204 whatever happened: the page ignores the response
(sendBeacon), and an error message would only teach a scraper what we
validate.
"""

import base64
import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
# Only the landing page's own origin is counted. Anyone can forge the
# header, but a browser can't: another page can't inflate our numbers by
# firing beacons at us from its visitors.
SITE_ORIGIN = os.environ["SITE_ORIGIN"]

# Days as the campus lives them. A visit at 01:00 in Beer Sheva belongs to
# that day, not to the previous UTC one.
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")

# Event name from the page -> counter attribute on the day's item.
COUNTERS = {
    "visit": "visits",
    "bot_click": "botClicks",
}

# Same slug as ingest.core.REFERRAL_PATTERN: the landing page passes it on
# to the bot unchanged, and the two have to agree for the funnel to join.
REFERRAL_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
DIRECT = "direct"

MAX_BODY_BYTES = 512

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

NO_CONTENT = {"statusCode": 204}


def handler(event, context):
    try:
        _count(event)
    except Exception:
        logger.exception("beacon failed")
    return NO_CONTENT


def _count(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("origin") != SITE_ORIGIN:
        return

    body = _parse(event)
    if body is None:
        return

    counter = COUNTERS.get(body.get("event"))
    if counter is None:
        return
    referral = _clean_referral(body.get("referral")) or DIRECT
    # `is True`, not truthiness: the field is user-controlled JSON.
    first_today = counter == "visits" and body.get("firstToday") is True

    day = datetime.now(LOCAL_TZ).date().isoformat()
    add = f"#{counter} :one" + (", visitors :one" if first_today else "")
    table.update_item(
        Key={"PK": f"TRAFFIC#{day}#{referral}", "SK": "META"},
        UpdateExpression=(
            "SET #day = :day, referral = :referral, GSI2PK = :entity, GSI2SK = :sort "
            f"ADD {add}"
        ),
        ExpressionAttributeNames={"#day": "day", f"#{counter}": counter},
        ExpressionAttributeValues={
            ":day": day,
            ":referral": referral,
            # Listed through GSI2 like every other entity type: the stats
            # page reads a month of counters with one range query.
            ":entity": "ENTITY#TRAFFIC",
            ":sort": f"{day}#{referral}",
            ":one": 1,
        },
    )


def _parse(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    if len(raw) > MAX_BODY_BYTES:
        return None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def _clean_referral(raw):
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    return value if REFERRAL_PATTERN.fullmatch(value) else None
