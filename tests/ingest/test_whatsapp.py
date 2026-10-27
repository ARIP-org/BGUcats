import hashlib
import hmac
import json

import pytest

from ingest import core, whatsapp

SECRETS = {
    "access_token": "token",
    "app_secret": "app-secret",
    "verify_token": "verify-me",
    "salt": "salt",
}
PHONE_NUMBER_ID = "1111"
WA_ID = "972500000000"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def sent(monkeypatch):
    """Captures outbound Graph API calls instead of making them."""
    calls = []
    monkeypatch.setattr(
        whatsapp, "_graph_post", lambda token, path, body: calls.append(body)
    )
    return calls


@pytest.fixture
def media_store(monkeypatch):
    """Stands in for both ends of a media fetch: Graph download and S3 put."""
    puts = []

    class FakeS3:
        def put_object(self, **kwargs):
            puts.append(kwargs)

    monkeypatch.setattr(core, "s3", FakeS3())
    monkeypatch.setattr(
        whatsapp, "_download_media", lambda token, media_id: core.sniffed_or_raise(JPEG)
    )
    return puts


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(whatsapp, "_get_secrets", lambda: SECRETS)


def _image(message_id="wamid.1", media_id="media-1"):
    return {
        "from": WA_ID,
        "id": message_id,
        "timestamp": "1761580800",
        "type": "image",
        "image": {"id": media_id, "mime_type": "image/jpeg"},
    }


def _text(body):
    return {"from": WA_ID, "id": "wamid.t", "type": "text", "text": {"body": body}}


def _button(action):
    return {
        "from": WA_ID,
        "id": "wamid.b",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": action}},
    }


def _location(lat, lon):
    return {
        "from": WA_ID,
        "id": "wamid.l",
        "type": "location",
        "location": {"latitude": lat, "longitude": lon},
    }


def _process(message):
    whatsapp._process_message(message, PHONE_NUMBER_ID, SECRETS)


def _submitter():
    return core.submitter_hash(SECRETS["salt"], f"wa:{WA_ID}")


def _webhook(*messages):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": list(messages),
                        },
                    }
                ]
            }
        ],
    }


def _signed_event(payload, secret=SECRETS["app_secret"]):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"X-Hub-Signature-256": signature},
        "body": raw.decode(),
    }


# --------------------------------------------------------------------------
# Request authenticity
# --------------------------------------------------------------------------


def test_signature_accepts_the_exact_body():
    raw = b'{"a": 1}'
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    assert whatsapp._signature_ok(raw, sig, "app-secret") is True


def test_signature_rejects_a_tampered_body():
    sig = "sha256=" + hmac.new(b"app-secret", b'{"a": 1}', hashlib.sha256).hexdigest()
    assert whatsapp._signature_ok(b'{"a": 2}', sig, "app-secret") is False


def test_signature_rejects_a_missing_header():
    assert whatsapp._signature_ok(b"{}", None, "app-secret") is False


def test_unsigned_post_is_refused(configured, dynamo_table, sent):
    event = _signed_event(_webhook(_text("hi")))
    event["headers"] = {}
    assert whatsapp.handler(event, None)["statusCode"] == 401
    assert sent == []


def test_signed_post_is_processed(configured, dynamo_table, sent):
    response = whatsapp.handler(_signed_event(_webhook(_text("hi"))), None)
    assert response["statusCode"] == 200
    assert sent and sent[0]["to"] == WA_ID


def test_post_signed_with_the_wrong_secret_is_refused(configured, dynamo_table, sent):
    event = _signed_event(_webhook(_text("hi")), secret="someone-else")
    assert whatsapp.handler(event, None)["statusCode"] == 401


def test_subscription_handshake_echoes_the_challenge(configured):
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "12345",
        },
    }
    response = whatsapp.handler(event, None)
    assert response["statusCode"] == 200
    assert response["body"] == "12345"


def test_subscription_handshake_with_the_wrong_token_is_refused(configured):
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": "guess",
            "hub.challenge": "12345",
        },
    }
    assert whatsapp.handler(event, None)["statusCode"] == 403


def test_everything_is_refused_until_the_secrets_are_set(monkeypatch):
    monkeypatch.setattr(
        whatsapp, "_get_secrets", lambda: {**SECRETS, "app_secret": "unset"}
    )
    response = whatsapp.handler(_signed_event(_webhook(_text("hi"))), None)
    assert response["statusCode"] == 503


def test_delivery_receipts_are_not_messages():
    payload = _webhook()
    payload["entry"][0]["changes"][0]["value"]["statuses"] = [{"status": "read"}]
    assert list(whatsapp._messages(payload)) == []


# --------------------------------------------------------------------------
# Photos
# --------------------------------------------------------------------------


def test_photo_is_stored_and_reacted_to(dynamo_table, sent, media_store):
    _process(_image())

    assert len(media_store) == 1
    key = media_store[0]["Key"]
    assert key.startswith("raw/") and key.endswith(".jpg")

    photo_id = key.rsplit("/", 1)[1].split(".")[0]
    photo = dynamo_table.get_item(Key={"PK": f"PHOTO#{photo_id}", "SK": "META"})["Item"]
    assert photo["status"] == "unlabeled"
    assert photo["channel"] == "whatsapp"

    assert sent[0]["type"] == "reaction"
    assert sent[0]["reaction"]["message_id"] == "wamid.1"


def test_first_photo_asks_for_the_location_and_the_rest_do_not(
    dynamo_table, sent, media_store
):
    _process(_image("wamid.1", "m1"))
    _process(_image("wamid.2", "m2"))
    _process(_image("wamid.3", "m3"))

    kinds = [m.get("interactive", {}).get("type") or m["type"] for m in sent]
    assert kinds.count("location_request_message") == 1
    assert kinds.count("reaction") == 3


def test_a_burst_lands_in_one_session(dynamo_table, sent, media_store):
    for i in range(4):
        _process(_image(f"wamid.{i}", f"m{i}"))
    sessions = {put["Key"].split("/")[1] for put in media_store}
    assert len(sessions) == 1


def test_retried_delivery_reuses_the_same_photo(dynamo_table, sent, media_store):
    _process(_image("wamid.same"))
    _process(_image("wamid.same"))
    assert media_store[0]["Key"] == media_store[1]["Key"]


def test_failed_download_leaves_the_record_pending(
    dynamo_table, sent, media_store, monkeypatch
):
    def fail(token, media_id):
        raise ValueError("nope")

    monkeypatch.setattr(whatsapp, "_download_media", fail)
    _process(_image())
    assert media_store == []
    assert sent == []
    photos = dynamo_table.scan(
        FilterExpression="begins_with(PK, :p)",
        ExpressionAttributeValues={":p": "PHOTO#"},
    )["Items"]
    assert [p["status"] for p in photos] == ["pending"]


# --------------------------------------------------------------------------
# Location, buttons, text
# --------------------------------------------------------------------------


def test_location_pins_the_session(dynamo_table, sent, media_store):
    _process(_image())
    _process(_location(31.26312, 34.80224))

    pointer = dynamo_table.get_item(
        Key={"PK": f"SUBMITTER#{_submitter()}", "SK": "LAST_SESSION"}
    )["Item"]
    session = dynamo_table.get_item(
        Key={"PK": f"SESSION#{pointer['sessionId']}", "SK": "META"}
    )["Item"]
    assert str(session["coarseLat"]) == "31.263"
    assert session["locationSource"] == "whatsapp"
    assert sent[-1]["interactive"]["body"]["text"] == whatsapp.LOCATION_SAVED_TEXT


def test_location_without_a_session_is_refused(dynamo_table, sent):
    _process(_location(31.26, 34.80))
    assert sent[-1]["text"]["body"] == whatsapp.NO_SESSION_FOR_LOCATION_TEXT


def test_out_of_range_location_is_ignored(dynamo_table, sent, media_store):
    _process(_image())
    sent.clear()
    _process(_location(123.0, 34.8))
    assert sent == []


def test_new_cat_button_opens_an_explicit_whatsapp_session(dynamo_table, sent):
    _process(_button(whatsapp.NEW_SESSION_ACTION))
    pointer = dynamo_table.get_item(
        Key={"PK": f"SUBMITTER#{_submitter()}", "SK": "ACTIVE_SESSION"}
    )["Item"]
    assert pointer["explicit"] is True
    session = dynamo_table.get_item(
        Key={"PK": f"SESSION#{pointer['sessionId']}", "SK": "META"}
    )["Item"]
    assert session["channel"] == "whatsapp"


def test_done_counts_photos_and_asks_for_a_missing_location(
    dynamo_table, sent, media_store
):
    _process(_image("wamid.1", "m1"))
    _process(_image("wamid.2", "m2"))
    sent.clear()
    _process(_text("Done"))

    assert "2 photos" in sent[0]["interactive"]["body"]["text"]
    assert sent[1]["interactive"]["type"] == "location_request_message"


def test_done_with_nothing_open(dynamo_table, sent):
    _process(_text("done"))
    assert "No session open" in sent[0]["interactive"]["body"]["text"]


def test_hebrew_and_russian_commands_work(dynamo_table, sent):
    _process(_text("חתול חדש"))
    _process(_text("Готово"))
    assert "New session started" in sent[0]["interactive"]["body"]["text"]
    assert "Session closed" in sent[1]["interactive"]["body"]["text"]


def test_any_other_text_gets_the_introduction(dynamo_table, sent):
    _process(_text("hi"))
    message = sent[0]
    assert message["interactive"]["body"]["text"] == whatsapp.START_TEXT
    titles = [b["reply"]["title"] for b in message["interactive"]["action"]["buttons"]]
    assert all(len(title) <= 20 for title in titles)


def test_phone_numbers_and_telegram_ids_never_share_a_hash():
    # A Telegram user ID that happens to equal someone's phone digits must
    # not land in that person's sessions.
    assert core.submitter_hash("salt", f"wa:{WA_ID}") != core.submitter_hash(
        "salt", WA_ID
    )


def test_rate_limit_applies_to_whatsapp_too(dynamo_table, sent, monkeypatch):
    monkeypatch.setattr(core, "check_rate_limit", lambda submitter_hash: False)
    _process(_text("hi"))
    assert sent == []
