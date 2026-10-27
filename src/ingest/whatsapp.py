"""WhatsApp Cloud API webhook -> S3 + DynamoDB. Same job as handler.py.

The WhatsApp adapter: verifies Meta's signature, parses the webhook,
downloads media through the Graph API, and replies in WhatsApp's terms.
Everything that touches storage goes through core.py, so a WhatsApp
session is the same identity cluster, in the same table and the same
labeling queue, as a Telegram one.

Where WhatsApp differs from Telegram, and what that means here:

- No persistent keyboard. Buttons live on individual messages (three at
  most), so replies that change state carry New cat / Done buttons.
- No album ID. Several photos sent at once are separate, concurrent
  messages; core's conditional session open keeps them in one session,
  and each photo is acknowledged with a reaction instead of a reply, so
  five photos don't produce five "Got it!"s.
- The location prompt is WhatsApp's own "Send location" sheet, which can
  also search for a place or send a spot other than where you are.
- The user ID is a phone number. It is only ever used to reply within
  this invocation; what gets stored is a salted hash of "wa:<number>".
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3

from ingest import core

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ACCESS_TOKEN_PARAM = os.environ["WHATSAPP_ACCESS_TOKEN_PARAM"]
APP_SECRET_PARAM = os.environ["WHATSAPP_APP_SECRET_PARAM"]
VERIFY_TOKEN_PARAM = os.environ["WHATSAPP_VERIFY_TOKEN_PARAM"]
SALT_PARAM = os.environ["SUBMITTER_HASH_SALT_PARAM"]
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v26.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

CHANNEL = "whatsapp"

# Terraform creates the parameters with this value and leaves the real
# ones to infra/scripts/set-whatsapp-secrets.sh. Until then every request
# is refused, rather than accepted with a guessable secret.
UNSET = "unset"

NEW_SESSION_ACTION = "new_session"
CLOSE_SESSION_ACTION = "close_session"
LOCATION_HELP_ACTION = "location_help"
START_ACTION = "start"

# Reply-button titles: 20 characters at most.
BUTTONS = [
    (NEW_SESSION_ACTION, "\U0001f43e New cat"),
    (CLOSE_SESSION_ACTION, "✅ Done"),
]

TEXT_ACTIONS = {
    "new": NEW_SESSION_ACTION,
    "new cat": NEW_SESSION_ACTION,
    "/newcat": NEW_SESSION_ACTION,
    "חתול חדש": NEW_SESSION_ACTION,
    "новый": NEW_SESSION_ACTION,
    "done": CLOSE_SESSION_ACTION,
    "/done": CLOSE_SESSION_ACTION,
    "סיום": CLOSE_SESSION_ACTION,
    "готово": CLOSE_SESSION_ACTION,
    "location": LOCATION_HELP_ACTION,
    "/location": LOCATION_HELP_ACTION,
    "מיקום": LOCATION_HELP_ACTION,
}

START_TEXT = (
    "Send me photos of a campus cat and I'll file them. \U0001f431\n\n"
    "Just sending photos works — they're grouped into one encounter "
    "automatically.\n\n"
    "Photographing one cat for a while? Tap *New cat* first and *Done* when "
    "you've finished, and I'll keep every shot in a single session no matter "
    "how long it takes.\n\n"
    "After the first photo I'll ask where you saw the cat. It's rounded to "
    "about 100 m."
)

ASK_LOCATION_TEXT = (
    "Got it! \U0001f431 Where did you see this cat?\n\n"
    "Tap *Send location*. If you've already left, search for the spot or "
    "move the map to it instead of sending where you are now."
)

DONE_ASK_LOCATION_TEXT = "Where did you see this cat? Tap *Send location*."

LOCATION_SAVED_TEXT = (
    "\U0001f4cd Saved, thanks! That's how we learn where each cat hangs out."
)

NO_SESSION_FOR_LOCATION_TEXT = (
    "I don't have a recent session to pin that to. Send the photos first, "
    "then the location."
)

PHOTO_REACTION = "\U0001f431"

ssm = boto3.client("ssm")

# Re-read now and then rather than once per container: a rotated access
# token (or the first real values replacing "unset") takes effect within
# minutes, with no redeploy.
SECRETS_TTL_SECONDS = 10 * 60

_secrets_cache = None
_secrets_read_at = 0


def _get_secrets():
    global _secrets_cache, _secrets_read_at
    if _secrets_cache is None or time.time() - _secrets_read_at > SECRETS_TTL_SECONDS:
        response = ssm.get_parameters(
            Names=[
                ACCESS_TOKEN_PARAM,
                APP_SECRET_PARAM,
                VERIFY_TOKEN_PARAM,
                SALT_PARAM,
            ],
            WithDecryption=True,
        )
        values = {p["Name"]: p["Value"] for p in response["Parameters"]}
        _secrets_cache = {
            "access_token": values[ACCESS_TOKEN_PARAM],
            "app_secret": values[APP_SECRET_PARAM],
            "verify_token": values[VERIFY_TOKEN_PARAM],
            "salt": values[SALT_PARAM],
        }
        _secrets_read_at = time.time()
    return _secrets_cache


def handler(event, context):
    secrets = _get_secrets()
    if UNSET in (
        secrets["access_token"],
        secrets["app_secret"],
        secrets["verify_token"],
    ):
        _forget_secrets()
        return {"statusCode": 503, "body": "whatsapp is not configured"}

    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
    if method == "GET":
        return _verify_subscription(event.get("queryStringParameters") or {}, secrets)

    raw = event.get("body") or ""
    raw = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode("utf-8")

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not _signature_ok(
        raw, headers.get("x-hub-signature-256"), secrets["app_secret"]
    ):
        return {"statusCode": 401, "body": "unauthorized"}

    try:
        for phone_number_id, message in _messages(json.loads(raw)):
            _process_message(message, phone_number_id, secrets)
    except Exception:
        # Same policy as the Telegram handler: log and ack, never let a bug
        # become a retry loop. Records stay `pending` per spec §10.
        logger.exception("unhandled error processing whatsapp webhook")
    return {"statusCode": 200, "body": "ok"}


def _forget_secrets():
    """Never hold on to the placeholder: the next request re-reads SSM."""
    global _secrets_cache
    _secrets_cache = None


def _verify_subscription(params, secrets):
    """Meta's one-time handshake when the webhook URL is registered."""
    if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
        params.get("hub.verify_token", ""), secrets["verify_token"]
    ):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": params.get("hub.challenge", ""),
        }
    return {"statusCode": 403, "body": "forbidden"}


def _signature_ok(raw, header, app_secret):
    """X-Hub-Signature-256 is an HMAC of the exact body bytes with the app
    secret. Without this check the endpoint is an open upload to anyone who
    finds the URL (spec §8.5) — the same job Telegram's secret token does."""
    if not header:
        return False
    expected = (
        "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, header)


def _messages(payload):
    """Yield (phone_number_id, message) for every inbound message.

    Delivery receipts (`statuses`) arrive on the same webhook and are
    skipped. The phone number ID is the bot's own, needed to reply.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            for message in value.get("messages") or []:
                yield phone_number_id, message


def _process_message(message, phone_number_id, secrets):
    wa_id = message.get("from")
    kind = message.get("type")
    if not wa_id or not phone_number_id:
        return

    submitter_hash = core.submitter_hash(secrets["salt"], f"wa:{wa_id}")
    if not core.check_rate_limit(submitter_hash):
        logger.info("rate limited submitter=%s", submitter_hash)
        return

    reply = Replier(secrets["access_token"], phone_number_id, wa_id)

    if kind in ("image", "video"):
        _handle_media(message, submitter_hash, reply, secrets)
    elif kind == "location":
        _handle_location(message.get("location") or {}, submitter_hash, reply)
    elif kind == "interactive":
        button = (message.get("interactive") or {}).get("button_reply") or {}
        _handle_action(button.get("id"), submitter_hash, reply)
    elif kind == "text":
        text = ((message.get("text") or {}).get("body") or "").strip().lower()
        # Anything unrecognised gets the introduction: unlike Telegram there
        # is no /start, and a first message is usually just "hi".
        _handle_action(TEXT_ACTIONS.get(text, START_ACTION), submitter_hash, reply)


def _handle_media(message, submitter_hash, reply, secrets):
    kind = message["type"]
    media = message.get(kind) or {}
    media_id = media.get("id")
    if not media_id:
        return

    timestamp = message.get("timestamp")
    session_id = core.ingest_media(
        idempotency_key=f"WAMSG#{message['id']}",
        submitter_hash=submitter_hash,
        media_group_id=None,
        channel=CHANNEL,
        captured_at=core.epoch_to_iso(int(timestamp)) if timestamp else None,
        fetch=lambda: _download_media(secrets["access_token"], media_id),
    )
    if session_id is None:
        return

    reply.react(message["id"], PHOTO_REACTION)
    if core.claim_location_prompt(session_id):
        reply.location_request(ASK_LOCATION_TEXT)


def _handle_location(location, submitter_hash, reply):
    coarse = core.coarse_location(location.get("latitude"), location.get("longitude"))
    if coarse is None:
        return
    if core.set_session_location(submitter_hash, *coarse, CHANNEL):
        reply.buttons(LOCATION_SAVED_TEXT)
    else:
        reply.text(NO_SESSION_FOR_LOCATION_TEXT)


def _handle_action(action, submitter_hash, reply):
    if action == NEW_SESSION_ACTION:
        core.open_explicit_session(submitter_hash, channel=CHANNEL)
        reply.buttons(
            "New session started \U0001f43e Send photos of this one cat, then tap Done."
        )
    elif action == CLOSE_SESSION_ACTION:
        _finish_session(submitter_hash, reply)
    elif action == LOCATION_HELP_ACTION:
        reply.location_request(DONE_ASK_LOCATION_TEXT)
    elif action == START_ACTION:
        # WhatsApp's nearest thing to /start. No tracked-link payload rides
        # along, so the profile only says when and on which channel.
        core.record_contributor(submitter_hash, CHANNEL)
        reply.buttons(START_TEXT)


def _finish_session(submitter_hash, reply):
    closed = core.close_active_session(submitter_hash)
    if closed is None:
        reply.buttons("No session open. Send photos, or tap New cat to start one.")
        return

    count, has_location = closed
    if count == 0:
        reply.buttons("Session closed — no photos in it.")
        return
    reply.buttons(
        f"Session closed with {count} photo{'s' if count != 1 else ''}. Thanks!"
    )
    if not has_location:
        reply.location_request(DONE_ASK_LOCATION_TEXT)


def _download_media(access_token, media_id):
    """Two hops: the media ID resolves to a short-lived URL, and that URL
    needs the same bearer token. Size is capped and the type sniffed from
    bytes, exactly as for Telegram (spec §8.5)."""
    auth = {"Authorization": f"Bearer {access_token}"}
    request = urllib.request.Request(
        f"{GRAPH_URL}/{urllib.parse.quote(media_id, safe='')}", headers=auth
    )
    with urllib.request.urlopen(request, timeout=8) as resp:
        info = json.loads(resp.read())

    if not info.get("url"):
        raise ValueError("media lookup returned no url")
    file_size = info.get("file_size") or 0
    if file_size > core.MAX_FILE_SIZE_BYTES:
        raise ValueError(f"file too large: {file_size} bytes")

    return core.sniffed_or_raise(core.read_capped(info["url"], headers=auth))


class Replier:
    """Outbound messages to one user, through the bot's phone number."""

    def __init__(self, access_token, phone_number_id, wa_id):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.wa_id = wa_id

    def text(self, body):
        self._send({"type": "text", "text": {"body": body}})

    def buttons(self, body):
        self._send(
            {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": action, "title": title}}
                            for action, title in BUTTONS
                        ]
                    },
                },
            }
        )

    def location_request(self, body):
        self._send(
            {
                "type": "interactive",
                "interactive": {
                    "type": "location_request_message",
                    "body": {"text": body},
                    "action": {"name": "send_location"},
                },
            }
        )

    def react(self, message_id, emoji):
        self._send(
            {"type": "reaction", "reaction": {"message_id": message_id, "emoji": emoji}}
        )

    def _send(self, message):
        _graph_post(
            self.access_token,
            f"{self.phone_number_id}/messages",
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.wa_id,
                **message,
            },
        )


def _graph_post(access_token, path, body):
    request = urllib.request.Request(
        f"{GRAPH_URL}/{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=8)
    except urllib.error.URLError as exc:
        # The phone number stays out of the log; the type of message is
        # enough to debug with.
        logger.warning("whatsapp send %s failed: %s", body.get("type"), exc)
