import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN_PARAM", "/bgucats/telegram/bot-token")
os.environ.setdefault(
    "TELEGRAM_WEBHOOK_SECRET_PARAM", "/bgucats/telegram/webhook-secret"
)
os.environ.setdefault("SUBMITTER_HASH_SALT_PARAM", "/bgucats/submitter-hash-salt")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from ingest import handler

TABLE_NAME = os.environ["TABLE_NAME"]


@pytest.fixture
def dynamo_table(monkeypatch):
    """A moto-backed table swapped in for handler.table.

    handler.py's own `table` global was bound at import time, before this
    fixture's mock is active, so it points at real AWS — monkeypatching it
    to a freshly-created mocked Table is what actually redirects the
    handler's DynamoDB calls.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        monkeypatch.setattr(handler, "table", table)
        yield table


def test_new_submitter_opens_session(dynamo_table):
    session_id = handler._resolve_or_open_session("hash-a", None)
    assert session_id


def test_second_call_within_idle_window_reuses_session(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    second = handler._resolve_or_open_session("hash-a", None)
    assert first == second


def test_call_after_idle_window_opens_new_session(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = handler._resolve_or_open_session("hash-a", None)
    assert second != first


def test_media_group_reuses_session_even_past_idle_window(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", "mg-1")
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = handler._resolve_or_open_session("hash-a", "mg-1")
    assert second == first


def test_different_submitters_get_different_sessions(dynamo_table):
    first = handler._resolve_or_open_session("hash-a", None)
    second = handler._resolve_or_open_session("hash-b", None)
    assert first != second


def test_retry_of_same_telegram_message_reuses_photo_and_session(dynamo_table):
    photo_id_1, session_id_1 = handler._resolve_photo_and_session(
        111, 222, "hash-b", None
    )
    photo_id_2, session_id_2 = handler._resolve_photo_and_session(
        111, 222, "hash-b", None
    )
    assert photo_id_1 == photo_id_2
    assert session_id_1 == session_id_2


def test_different_message_gets_a_different_photo(dynamo_table):
    photo_id_1, _ = handler._resolve_photo_and_session(111, 222, "hash-b", None)
    photo_id_2, _ = handler._resolve_photo_and_session(111, 223, "hash-b", None)
    assert photo_id_1 != photo_id_2


def test_rate_limit_allows_up_to_threshold_then_blocks(dynamo_table):
    for _ in range(handler.RATE_LIMIT_PER_MINUTE):
        assert handler._check_rate_limit("hash-c") is True
    assert handler._check_rate_limit("hash-c") is False


def test_rate_limit_is_scoped_per_submitter(dynamo_table):
    for _ in range(handler.RATE_LIMIT_PER_MINUTE):
        handler._check_rate_limit("hash-d")
    assert handler._check_rate_limit("hash-d") is False
    assert handler._check_rate_limit("hash-e") is True


def _age_pointer(dynamo_table, submitter_hash, seconds_ago):
    dynamo_table.update_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": handler._now_epoch() - seconds_ago},
    )


def test_explicit_session_survives_the_idle_window(dynamo_table):
    handler._start_new_session("hash-x")
    first = handler._resolve_or_open_session("hash-x", None)
    _age_pointer(dynamo_table, "hash-x", handler.SESSION_IDLE_WINDOW_SECONDS + 60)
    second = handler._resolve_or_open_session("hash-x", None)
    assert second == first


def test_explicit_session_closes_at_the_safety_cap(dynamo_table):
    handler._start_new_session("hash-x")
    first = handler._resolve_or_open_session("hash-x", None)
    _age_pointer(dynamo_table, "hash-x", handler.EXPLICIT_SESSION_MAX_SECONDS + 60)
    second = handler._resolve_or_open_session("hash-x", None)
    assert second != first


def test_new_cat_while_open_starts_a_fresh_session(dynamo_table):
    first = handler._resolve_or_open_session("hash-y", None)
    handler._start_new_session("hash-y")
    second = handler._resolve_or_open_session("hash-y", None)
    assert second != first


def test_done_closes_session_and_next_photo_opens_a_new_one(dynamo_table):
    first = handler._resolve_or_open_session("hash-z", None)
    handler._finish_session("hash-z")
    assert (
        dynamo_table.get_item(
            Key={"PK": "SUBMITTER#hash-z", "SK": "ACTIVE_SESSION"}
        ).get("Item")
        is None
    )
    second = handler._resolve_or_open_session("hash-z", None)
    assert second != first


def test_done_reports_the_photo_count(dynamo_table):
    session_id = handler._resolve_or_open_session("hash-w", None)
    handler._bump_session(session_id)
    handler._bump_session(session_id)
    assert "2 photos" in handler._finish_session("hash-w")


def test_done_with_no_open_session_is_not_an_error(dynamo_table):
    assert "No session open" in handler._finish_session("hash-nobody")


def test_album_replies_exactly_once(dynamo_table):
    assert handler._should_reply("mg-album") is True
    assert handler._should_reply("mg-album") is False
    assert handler._should_reply("mg-album") is False


def test_standalone_photos_always_reply(dynamo_table):
    assert handler._should_reply(None) is True
    assert handler._should_reply(None) is True


def test_different_albums_each_get_a_reply(dynamo_table):
    assert handler._should_reply("mg-1") is True
    assert handler._should_reply("mg-2") is True


@pytest.fixture
def telegram_calls(monkeypatch):
    """Captures outbound Telegram calls instead of making them."""
    calls = []
    monkeypatch.setattr(
        handler,
        "_telegram_post",
        lambda token, method, body: calls.append((method, body)),
    )
    return calls


SECRETS = {"bot_token": "t", "webhook_secret": "s", "salt": "salt"}


def test_new_cat_button_opens_a_session(dynamo_table, telegram_calls):
    handler._handle_callback(
        {
            "id": "cb-1",
            "data": handler.NEW_SESSION_ACTION,
            "from": {"id": 42},
            "message": {"chat": {"id": 42}},
        },
        SECRETS,
    )
    methods = [m for m, _ in telegram_calls]
    assert "answerCallbackQuery" in methods
    assert "sendMessage" in methods

    submitter = handler._submitter_hash(SECRETS, 42)
    pointer = dynamo_table.get_item(
        Key={"PK": f"SUBMITTER#{submitter}", "SK": "ACTIVE_SESSION"}
    )["Item"]
    assert pointer["explicit"] is True


def test_unknown_callback_still_answers_the_spinner(dynamo_table, telegram_calls):
    handler._handle_callback(
        {
            "id": "cb-2",
            "data": "something-we-do-not-know",
            "from": {"id": 42},
            "message": {"chat": {"id": 42}},
        },
        SECRETS,
    )
    assert [m for m, _ in telegram_calls] == ["answerCallbackQuery"]


def _send_text(text):
    return {"text": text, "chat": {"id": 42}, "from": {"id": 42}}


def _pointer_for(dynamo_table, tg_user_id=42):
    submitter = handler._submitter_hash(SECRETS, tg_user_id)
    return dynamo_table.get_item(
        Key={"PK": f"SUBMITTER#{submitter}", "SK": "ACTIVE_SESSION"}
    ).get("Item")


def test_start_sends_the_reply_keyboard(dynamo_table, telegram_calls):
    handler._handle_text(_send_text("/start"), "/start", SECRETS)
    method, body = telegram_calls[0]
    assert method == "sendMessage"
    assert body["reply_markup"] == handler.SESSION_KEYBOARD


def test_keyboard_is_a_reply_keyboard_not_an_inline_one():
    # A reply keyboard docks under the message box and persists; an inline
    # one is attached to a single message and scrolls away with it.
    assert "keyboard" in handler.SESSION_KEYBOARD
    assert "inline_keyboard" not in handler.SESSION_KEYBOARD
    assert handler.SESSION_KEYBOARD["is_persistent"] is True


def test_new_cat_button_text_opens_a_session(dynamo_table, telegram_calls):
    handler._handle_text(
        _send_text(handler.BUTTON_NEW_CAT), handler.BUTTON_NEW_CAT, SECRETS
    )
    assert _pointer_for(dynamo_table)["explicit"] is True


def test_done_button_text_closes_the_session(dynamo_table, telegram_calls):
    handler._handle_text(
        _send_text(handler.BUTTON_NEW_CAT), handler.BUTTON_NEW_CAT, SECRETS
    )
    handler._handle_text(_send_text(handler.BUTTON_DONE), handler.BUTTON_DONE, SECRETS)
    assert _pointer_for(dynamo_table) is None


def test_newcat_command_matches_the_button(dynamo_table, telegram_calls):
    handler._handle_text(
        _send_text("/newcat@BguCatsBot"), "/newcat@BguCatsBot", SECRETS
    )
    assert _pointer_for(dynamo_table)["explicit"] is True


def test_ordinary_chatter_is_ignored(dynamo_table, telegram_calls):
    handler._handle_text(_send_text("hello there"), "hello there", SECRETS)
    handler._handle_text(_send_text("/nonsense"), "/nonsense", SECRETS)
    assert telegram_calls == []


def test_sniff_image_type_jpeg():
    assert handler._sniff_image_type(b"\xff\xd8\xff\xe0rest-of-file") == (
        "image/jpeg",
        "jpg",
    )


def test_sniff_image_type_png():
    assert handler._sniff_image_type(b"\x89PNG\r\n\x1a\nrest-of-file") == (
        "image/png",
        "png",
    )


def test_sniff_image_type_rejects_non_image_bytes():
    assert handler._sniff_image_type(b"not an image") is None


def test_sniff_video_type_mp4():
    # ISO base media file: a 4-byte size word, then "ftyp" at offset 4 —
    # not offset 0, unlike the image signatures above.
    data = b"\x00\x00\x00\x18ftypmp42" + b"rest-of-file"
    assert handler._sniff_video_type(data) == ("video/mp4", "mp4")


def test_sniff_video_type_webm():
    data = b"\x1a\x45\xdf\xa3" + b"rest-of-file"
    assert handler._sniff_video_type(data) == ("video/webm", "webm")


def test_sniff_video_type_rejects_non_video_bytes():
    assert handler._sniff_video_type(b"not a video") is None


def test_sniff_media_type_detects_a_photo():
    assert handler._sniff_media_type(b"\xff\xd8\xff\xe0rest") == (
        "image/jpeg",
        "jpg",
        "photo",
    )


def test_sniff_media_type_detects_a_video():
    data = b"\x00\x00\x00\x18ftypmp42rest-of-file"
    assert handler._sniff_media_type(data) == ("video/mp4", "mp4", "video")


def test_sniff_media_type_rejects_unrecognized_bytes():
    assert handler._sniff_media_type(b"not media") is None


def test_extract_media_picks_the_largest_photo():
    message = {
        "photo": [
            {"file_id": "small", "width": 90, "height": 90, "file_size": 1000},
            {"file_id": "big", "width": 800, "height": 600, "file_size": 90000},
        ]
    }
    assert handler._extract_media(message)["file_id"] == "big"


def test_extract_media_returns_the_video_object():
    video = {"file_id": "v1", "width": 640, "height": 480, "duration": 12}
    assert handler._extract_media({"video": video}) == video


def test_extract_media_maps_video_note_length_onto_width_and_height():
    note = {"file_id": "vn1", "length": 240, "duration": 8}
    media = handler._extract_media({"video_note": note})
    assert media["width"] == 240
    assert media["height"] == 240
    assert media["duration"] == 8


def test_extract_media_returns_none_when_theres_nothing_to_fetch():
    assert handler._extract_media({}) is None
