"""Telegram webhook -> S3 + DynamoDB. Fetch, store, record, respond.

The Telegram adapter: validates the request came from Telegram, parses the
update, downloads files the Telegram way, and replies with Telegram
keyboards. Sessions, photo records and locations are core.py's job, shared
with the WhatsApp adapter (whatsapp.py).

No image processing happens here (see docs/cat-app-design-spec.pdf §5, §10)
— that's the S3-triggered process Lambda's job.
"""

import base64
import json
import logging
import os
import urllib.request

import boto3

from ingest import core

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BOT_TOKEN_PARAM = os.environ["TELEGRAM_BOT_TOKEN_PARAM"]
WEBHOOK_SECRET_PARAM = os.environ["TELEGRAM_WEBHOOK_SECRET_PARAM"]
SALT_PARAM = os.environ["SUBMITTER_HASH_SALT_PARAM"]
# The landing site's map page, opened as a Telegram Mini App. Optional: with
# it unset the bot still takes Telegram's own location messages.
MAP_PICKER_URL = os.environ.get("MAP_PICKER_URL")

CHANNEL = "telegram"

NEW_SESSION_ACTION = "new_session"
CLOSE_SESSION_ACTION = "close_session"
LOCATION_HELP_ACTION = "location_help"

BUTTON_NEW_CAT = "\U0001f43e New cat"
BUTTON_DONE = "✅ Done"
BUTTON_PICK_ON_MAP = "\U0001f5fa Pick on map"
BUTTON_HERE_NOW = "\U0001f4cd I'm there now"

# A reply keyboard (docked under the message box, persistent across
# messages) rather than an inline one attached to a single message —
# pressing these sends their label as an ordinary text message, so the
# controls stay available while you shoot instead of scrolling away.
SESSION_KEYBOARD = {
    "keyboard": [[{"text": BUTTON_NEW_CAT}, {"text": BUTTON_DONE}]],
    "resize_keyboard": True,
    "is_persistent": True,
}


def _location_keyboard():
    """The session keyboard plus a row for saying where the cat was.

    Telegram's own location button only ever sends where the phone is *now*,
    and photos are often sent long after they were taken — so the primary
    option is the map picker, which opens centred on campus. Shown only
    while a session is waiting for a location; any reply carrying
    SESSION_KEYBOARD folds it away again.
    """
    row = []
    if MAP_PICKER_URL:
        row.append({"text": BUTTON_PICK_ON_MAP, "web_app": {"url": MAP_PICKER_URL}})
    row.append({"text": BUTTON_HERE_NOW, "request_location": True})
    return {**SESSION_KEYBOARD, "keyboard": [row, *SESSION_KEYBOARD["keyboard"]]}


LOCATION_KEYBOARD = _location_keyboard()

TEXT_ACTIONS = {
    BUTTON_NEW_CAT: NEW_SESSION_ACTION,
    BUTTON_DONE: CLOSE_SESSION_ACTION,
    "/newcat": NEW_SESSION_ACTION,
    "/done": CLOSE_SESSION_ACTION,
    "/location": LOCATION_HELP_ACTION,
    # Clients that can't open a Mini App or share location (Telegram
    # Desktop, for one) send the button's label as plain text instead.
    BUTTON_PICK_ON_MAP: LOCATION_HELP_ACTION,
    BUTTON_HERE_NOW: LOCATION_HELP_ACTION,
}

START_TEXT = (
    "Send me photos of a campus cat and I'll file them.\n\n"
    "Just sending photos works — they're grouped into one encounter "
    "automatically.\n\n"
    "Photographing one cat for a while? Tap *New cat* first and *Done* when "
    "you've finished, and I'll keep every shot in a single session no matter "
    "how long it takes.\n\n"
    "After the first photo I'll ask where you saw the cat. A pin on the map "
    "is enough, and it's rounded to about 100 m."
)

GOT_IT_TEXT = "Got it! \U0001f431"

FETCH_FAILED_TEXT = (
    "Sorry, Telegram didn't hand me that one in time. Could you send it again?"
)

ASK_LOCATION_TEXT = (
    "Where did you see this cat? Tap *Pick on map* and drop a pin, or "
    "*I'm there now* if you still are.\n\n"
    "Also works: \U0001f4ce → *Location*, then drag the pin to the spot."
)

LOCATION_HELP_TEXT = (
    "To mark where you saw the cat, tap *Pick on map*. On a phone you can "
    "also tap \U0001f4ce → *Location* and drag the pin to the spot."
)

LOCATION_SAVED_TEXT = (
    "\U0001f4cd Saved, thanks! That's how we learn where each cat hangs out."
)

NO_SESSION_FOR_LOCATION_TEXT = (
    "I don't have a recent session to pin that to. Send the photos first, "
    "then the location."
)

ssm = boto3.client("ssm")

_secrets_cache = None


def _get_secrets():
    global _secrets_cache
    if _secrets_cache is None:
        response = ssm.get_parameters(
            Names=[BOT_TOKEN_PARAM, WEBHOOK_SECRET_PARAM, SALT_PARAM],
            WithDecryption=True,
        )
        values = {p["Name"]: p["Value"] for p in response["Parameters"]}
        _secrets_cache = {
            "bot_token": values[BOT_TOKEN_PARAM],
            "webhook_secret": values[WEBHOOK_SECRET_PARAM],
            "salt": values[SALT_PARAM],
        }
    return _secrets_cache


def handler(event, context):
    secrets = _get_secrets()

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-telegram-bot-api-secret-token") != secrets["webhook_secret"]:
        return {"statusCode": 401, "body": "unauthorized"}

    try:
        return _process_update(event, secrets)
    except Exception:
        # Never let a bug turn into an infinite Telegram retry loop — log
        # and ack. A stuck DynamoDB record stays "pending" (never falsely
        # marked ready) per the write-order guarantee in spec §10.
        logger.exception("unhandled error processing update")
        return {"statusCode": 200, "body": "ok"}


def _process_update(event, secrets):
    body_raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        return {"statusCode": 200, "body": "ok"}

    if body.get("callback_query"):
        return _handle_callback(body["callback_query"], secrets)

    message = body.get("message") or body.get("channel_post")
    if not message:
        return {"statusCode": 200, "body": "ok"}

    location = _extract_location(message)
    if location is not None:
        return _handle_location(message, *location, secrets)

    # Reply-keyboard presses arrive as ordinary text messages carrying the
    # button's label, so buttons and slash commands share one path.
    text = (message.get("text") or "").strip()
    if text:
        return _handle_text(message, text, secrets)

    media = _extract_media(message)
    if media is None:
        return {"statusCode": 200, "body": "ok"}

    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    media_group_id = message.get("media_group_id")
    date = message.get("date")

    submitter_hash = _submitter_hash(secrets, tg_user_id)

    if not core.check_rate_limit(submitter_hash):
        logger.info("rate limited submitter=%s", submitter_hash)
        return {"statusCode": 200, "body": "ok"}

    session_id = core.ingest_media(
        idempotency_key=_idempotency_key(chat_id, message_id),
        submitter_hash=submitter_hash,
        media_group_id=media_group_id,
        channel=CHANNEL,
        captured_at=core.epoch_to_iso(date) if date else None,
        fetch=lambda: _download_telegram_file(secrets["bot_token"], media["file_id"]),
        width=media.get("width"),
        height=media.get("height"),
        duration_seconds=media.get("duration"),
    )
    if session_id is None:
        # The record stays `pending` (spec §10) and Telegram will not
        # redeliver an update we acknowledge, so the person is the retry.
        _reply(secrets["bot_token"], chat_id, FETCH_FAILED_TEXT)
        return {"statusCode": 200, "body": "ok"}

    # One reply per album, not per photo: each photo in a media group is a
    # separate concurrent invocation, and five "Got it!"s for one album is
    # noise. No count here — none of these invocations knows how many
    # siblings it has. "Done" is where a count belongs.
    if core.should_reply(media_group_id):
        if core.claim_location_prompt(session_id):
            _reply(
                secrets["bot_token"],
                chat_id,
                f"{GOT_IT_TEXT}\n\n{ASK_LOCATION_TEXT}",
                keyboard=LOCATION_KEYBOARD,
            )
        else:
            _reply(secrets["bot_token"], chat_id, GOT_IT_TEXT)

    return {"statusCode": 200, "body": "ok"}


def _idempotency_key(chat_id, message_id):
    return f"TGMSG#{chat_id}_{message_id}"


def _extract_media(message):
    """Pick the file to fetch: the largest photo size, a video, or a video
    note (Telegram's circular selfie clips, which report a single `length`
    instead of width/height).

    What kind of file it actually is gets settled by magic bytes in
    `_download_telegram_file`, not by which of these fields it arrived
    in — spec §8.5 applies to video the same as to photos.
    """
    if message.get("photo"):
        return max(
            message["photo"],
            key=lambda p: p.get("file_size", 0) or p["width"] * p["height"],
        )
    if message.get("video"):
        return message["video"]
    if message.get("video_note"):
        note = message["video_note"]
        return {**note, "width": note.get("length"), "height": note.get("length")}
    return None


def _extract_location(message):
    """Where the cat was, as (lat, lon, source), or None.

    Two ways in: a Telegram location message — the "I'm there now" button,
    or 📎 → Location with the pin dragged anywhere (a venue carries one
    too) — or the map picker's sendData payload.
    """
    if message.get("location"):
        loc = message["location"]
        lat, lon, source = loc.get("latitude"), loc.get("longitude"), "telegram"
    elif message.get("web_app_data"):
        # User-controlled JSON, however it arrived.
        try:
            data = json.loads(message["web_app_data"].get("data") or "")
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        lat, lon, source = data.get("lat"), data.get("lon"), "map"
    else:
        return None

    coarse = core.coarse_location(lat, lon)
    return (*coarse, source) if coarse else None


def _handle_location(message, lat, lon, source, secrets):
    chat_id = message["chat"]["id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    submitter_hash = _submitter_hash(secrets, tg_user_id)

    if not core.check_rate_limit(submitter_hash):
        logger.info("rate limited submitter=%s", submitter_hash)
        return {"statusCode": 200, "body": "ok"}

    if core.set_session_location(submitter_hash, lat, lon, source):
        _reply(
            secrets["bot_token"],
            chat_id,
            LOCATION_SAVED_TEXT,
            keyboard=SESSION_KEYBOARD,
        )
    else:
        _reply(secrets["bot_token"], chat_id, NO_SESSION_FOR_LOCATION_TEXT)
    return {"statusCode": 200, "body": "ok"}


def _submitter_hash(secrets, tg_user_id):
    return core.submitter_hash(secrets["salt"], str(tg_user_id))


def _handle_callback(callback_query, secrets):
    """Serves the inline buttons from before the switch to a reply keyboard.

    Those messages are still in people's chat history with live buttons;
    dropping this would leave them spinning until they time out.
    """
    data = callback_query.get("data")
    chat_id = callback_query["message"]["chat"]["id"]
    tg_user_id = callback_query.get("from", {}).get("id", chat_id)
    submitter_hash = _submitter_hash(secrets, tg_user_id)

    keyboard = SESSION_KEYBOARD
    if data == NEW_SESSION_ACTION:
        text = _start_new_session(submitter_hash)
    elif data == CLOSE_SESSION_ACTION:
        text, keyboard = _finish_session(submitter_hash)
    else:
        text = None

    # Required, or the client shows a spinner on the button until it times
    # out — regardless of whether we recognized the action.
    _answer_callback(secrets["bot_token"], callback_query["id"])

    if text:
        _reply(secrets["bot_token"], chat_id, text, keyboard=keyboard)

    return {"statusCode": 200, "body": "ok"}


def _handle_text(message, text, secrets):
    chat_id = message["chat"]["id"]
    tg_user_id = message.get("from", {}).get("id", chat_id)
    submitter_hash = _submitter_hash(secrets, tg_user_id)

    # "/done@BguCatsBot extra words" -> "/done"; button labels match as-is.
    key = text.split()[0].split("@")[0].lower() if text.startswith("/") else text
    action = TEXT_ACTIONS.get(key)

    keyboard = SESSION_KEYBOARD
    if action == NEW_SESSION_ACTION:
        reply = _start_new_session(submitter_hash)
    elif action == CLOSE_SESSION_ACTION:
        reply, keyboard = _finish_session(submitter_hash)
    elif action == LOCATION_HELP_ACTION:
        reply, keyboard = LOCATION_HELP_TEXT, LOCATION_KEYBOARD
    elif key == "/start":
        # t.me/bgucatsbot?start=<slug> arrives as "/start <slug>": the landing
        # page puts its own ?src= there, so the stats page can follow a
        # visitor from the ad to the bot.
        words = text.split()
        referral = core.clean_referral(words[1]) if len(words) > 1 else None
        core.record_contributor(
            submitter_hash, CHANNEL, referral=referral or core.NO_REFERRAL
        )
        reply = START_TEXT
    else:
        return {"statusCode": 200, "body": "ok"}

    _reply(secrets["bot_token"], chat_id, reply, keyboard=keyboard)
    return {"statusCode": 200, "body": "ok"}


def _start_new_session(submitter_hash):
    core.open_explicit_session(submitter_hash, channel=CHANNEL)
    return "New session started \U0001f43e Send photos of this one cat, then tap Done."


def _finish_session(submitter_hash):
    """Close the open session. Returns (reply text, keyboard) — the location
    row stays up if the session still has no pin, since right after Done is
    the most natural moment to add one."""
    closed = core.close_active_session(submitter_hash)
    if closed is None:
        return (
            "No session open. Send photos, or tap New cat to start one.",
            SESSION_KEYBOARD,
        )

    count, has_location = closed
    if count == 0:
        return "Session closed — no photos in it.", SESSION_KEYBOARD
    text = f"Session closed with {count} photo{'s' if count != 1 else ''}. Thanks!"
    if has_location:
        return text, SESSION_KEYBOARD
    return f"{text}\n\n{ASK_LOCATION_TEXT}", LOCATION_KEYBOARD


def _download_telegram_file(bot_token, file_id):
    get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    with urllib.request.urlopen(get_file_url, timeout=8) as resp:
        file_info = json.loads(resp.read())

    if not file_info.get("ok"):
        raise ValueError(f"getFile failed: {file_info}")

    result = file_info["result"]
    file_size = result.get("file_size", 0)
    if file_size and file_size > core.MAX_FILE_SIZE_BYTES:
        raise ValueError(f"file too large: {file_size} bytes")

    download_url = f"https://api.telegram.org/file/bot{bot_token}/{result['file_path']}"
    return core.sniffed_or_raise(core.read_capped(download_url))


def _reply(bot_token, chat_id, text, keyboard=None):
    body = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if keyboard:
        body["reply_markup"] = keyboard
    _telegram_post(bot_token, "sendMessage", body)


def _answer_callback(bot_token, callback_query_id):
    _telegram_post(
        bot_token, "answerCallbackQuery", {"callback_query_id": callback_query_id}
    )


def _telegram_post(bot_token, method, body):
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=8)
    except OSError as exc:  # URLError, or a read that timed out
        logger.warning("telegram %s failed: %s", method, exc)
