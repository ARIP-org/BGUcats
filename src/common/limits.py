"""How often a person may do something (docs/app-plan/02-architecture.md,
"Abuse and limits").

A counter item per person, action and window, the same pattern as the
bot's per-minute limit (spec §8.5): one conditional update per request,
and the table's TTL removes old windows by itself. Fixed windows, not a
sliding log: one write per request, and easy to read in the table. The
cost is that someone can use the limit at the end of one window and again
at the start of the next.
"""

import math
import time

from botocore.exceptions import ClientError

from common.api import ApiError

# A window's item outlives the window by this much before TTL removes it,
# so it can still be read when someone asks why they were refused.
KEEP_AFTER_WINDOW_S = 24 * 3600


def rate_key(key, window_s, now):
    """The counter's partition key for `key` in the window holding `now`."""
    start = int(now // window_s) * window_s
    return f"RATE#{key}#{start}", start + window_s


def take(table, key, limit, window_s, now=None):
    """Counts one use of `key` (e.g. "{userId}#posts") in the current window.

    Under the limit: counted, and returns how many are left. At the limit:
    ApiError(429), and nothing is counted. The error's details carry
    retryAfter in seconds, which the outbox reads as "later", not "never".
    """
    now = time.time() if now is None else now
    pk, window_end = rate_key(key, window_s, now)
    try:
        answer = table.update_item(
            Key={"PK": pk, "SK": "META"},
            UpdateExpression="ADD #count :one SET expiresAt = if_not_exists(expiresAt, :expires)",
            ConditionExpression="attribute_not_exists(#count) OR #count < :limit",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={
                ":one": 1,
                ":limit": limit,
                ":expires": int(window_end + KEEP_AFTER_WINDOW_S),
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise ApiError(
            429,
            "Too many of these for now. Try again later.",
            code="rate_limited",
            details={"retryAfter": max(1, math.ceil(window_end - now))},
        ) from None
    return limit - int(answer["Attributes"]["count"])
