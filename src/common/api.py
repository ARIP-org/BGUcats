"""The request and the response, the same way in every API Lambda.

Moved out of src/admin/handler.py unchanged (2026-11-12), so the member API
(src/app/, docs/app-plan/04-api.md) answers in the same shape.
"""

import json
import re
from datetime import UTC, datetime
from decimal import Decimal

# A ULID is 26 Crockford base32 characters. IDs are minted on the phone so a
# retried request from its offline outbox lands on the same record (spec
# §10, "idempotent on the ULID").
ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"


class ApiError(Exception):
    """An answer to the caller, not a fault: status and words for a person.

    A status code is a contract with the phone's outbox, which drops a
    request on a permanent error (web/outbox.js, isPermanent; docs/notes.md,
    "A status code is a contract with the retry logic").
    """

    def __init__(self, status, message, *, code=None, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        # For the member API's answers (docs/app-plan/04-api.md,
        # "Conventions"): a word a program can test, and extra fields such
        # as retryAfter. The labeling desk's API sends neither.
        self.code = code
        self.details = details or {}


def now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def response(status, payload):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, default=json_default),
    }


def json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"not JSON serializable: {type(value)}")


def preflight(event):
    """The answer to a web view's CORS preflight, or None for any other call.

    The iPhone app's pages are another origin to the API, so the web view
    first sends an OPTIONS that carries no token. Its route has no
    authorizer (infra/main/admin_api.tf, app_api.tf), and API Gateway does
    not answer it by itself, as was assumed until 2026-11-13: it invokes
    the route's Lambda and only adds the CORS headers (api.tf) to whatever
    comes back. Every handler therefore answers it first, before asking who
    is calling: 204 and nothing else. A preflight reads and changes nothing.
    """
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    return {"statusCode": 204} if method == "OPTIONS" else None


def caller_email(event):
    """Email claim from the token the JWT authorizer already verified."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise ApiError(401, "no email claim on token")
    return email


def parse_body(event):
    raw = event.get("body")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ApiError(400, "body must be a JSON object")
    return parsed


def query_params(event):
    return event.get("queryStringParameters") or {}


def ulid_param(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not re.fullmatch(ULID_PATTERN, value):
        raise ApiError(400, f"{field} must be a ULID")
    return value


def iso_param(body, field):
    """A client timestamp, kept only if it parses — it is the phone's clock."""
    value = body.get(field)
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def required_string(body, field, maximum):
    value = (body.get(field) or "").strip()
    if not value:
        raise ApiError(400, f"{field} is required")
    if len(value) > maximum:
        raise ApiError(400, f"{field} is longer than {maximum} characters")
    return value


def int_param(query, name, default, maximum):
    raw = query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, f"{name} must be an integer")
    return max(1, min(value, maximum))


def match_route(routes, method, path):
    """The first route whose pattern matches the path and whose method is
    the request's: (handler, path parameters, who may call it).

    routes is an ordered table of (method, pattern, handler, access). A path
    that matches with another method is 405; no match at all is 404.
    """
    path = path.rstrip("/") or path
    matched_path = False
    for route_method, pattern, handler_fn, access in routes:
        match = re.match(pattern, path)
        if not match:
            continue
        matched_path = True
        if route_method == method:
            return handler_fn, match.groupdict(), access
    raise ApiError(405 if matched_path else 404, f"no route for {method} {path}")
