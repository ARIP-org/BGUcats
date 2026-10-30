import json

import pytest

from ingest import core, handler


def test_new_submitter_opens_session(dynamo_table):
    session_id = core.resolve_or_open_session("hash-a", None, channel="telegram")
    assert session_id


def test_second_call_within_idle_window_reuses_session(dynamo_table):
    first = core.resolve_or_open_session("hash-a", None, channel="telegram")
    second = core.resolve_or_open_session("hash-a", None, channel="telegram")
    assert first == second


def test_call_after_idle_window_opens_new_session(dynamo_table):
    first = core.resolve_or_open_session("hash-a", None, channel="telegram")
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = core.resolve_or_open_session("hash-a", None, channel="telegram")
    assert second != first


def test_media_group_reuses_session_even_past_idle_window(dynamo_table):
    first = core.resolve_or_open_session("hash-a", "mg-1", channel="telegram")
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-a", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": 0},
    )
    second = core.resolve_or_open_session("hash-a", "mg-1", channel="telegram")
    assert second == first


def test_different_submitters_get_different_sessions(dynamo_table):
    first = core.resolve_or_open_session("hash-a", None, channel="telegram")
    second = core.resolve_or_open_session("hash-b", None, channel="telegram")
    assert first != second


def test_retry_of_same_telegram_message_reuses_photo_and_session(dynamo_table):
    photo_id_1, session_id_1 = core.resolve_photo_and_session(
        "TGMSG#111_222", "hash-b", None, channel="telegram"
    )
    photo_id_2, session_id_2 = core.resolve_photo_and_session(
        "TGMSG#111_222", "hash-b", None, channel="telegram"
    )
    assert photo_id_1 == photo_id_2
    assert session_id_1 == session_id_2


def test_different_message_gets_a_different_photo(dynamo_table):
    photo_id_1, _ = core.resolve_photo_and_session(
        "TGMSG#111_222", "hash-b", None, channel="telegram"
    )
    photo_id_2, _ = core.resolve_photo_and_session(
        "TGMSG#111_223", "hash-b", None, channel="telegram"
    )
    assert photo_id_1 != photo_id_2


def test_rate_limit_allows_up_to_threshold_then_blocks(dynamo_table):
    for _ in range(core.RATE_LIMIT_PER_MINUTE):
        assert core.check_rate_limit("hash-c") is True
    assert core.check_rate_limit("hash-c") is False


def test_rate_limit_is_scoped_per_submitter(dynamo_table):
    for _ in range(core.RATE_LIMIT_PER_MINUTE):
        core.check_rate_limit("hash-d")
    assert core.check_rate_limit("hash-d") is False
    assert core.check_rate_limit("hash-e") is True


def _age_pointer(dynamo_table, submitter_hash, seconds_ago):
    dynamo_table.update_item(
        Key={"PK": f"SUBMITTER#{submitter_hash}", "SK": "ACTIVE_SESSION"},
        UpdateExpression="SET lastPhotoAtEpoch = :t",
        ExpressionAttributeValues={":t": core.now_epoch() - seconds_ago},
    )


def test_explicit_session_survives_the_idle_window(dynamo_table):
    handler._start_new_session("hash-x")
    first = core.resolve_or_open_session("hash-x", None, channel="telegram")
    _age_pointer(dynamo_table, "hash-x", core.SESSION_IDLE_WINDOW_SECONDS + 60)
    second = core.resolve_or_open_session("hash-x", None, channel="telegram")
    assert second == first


def test_explicit_session_closes_at_the_safety_cap(dynamo_table):
    handler._start_new_session("hash-x")
    first = core.resolve_or_open_session("hash-x", None, channel="telegram")
    _age_pointer(dynamo_table, "hash-x", core.EXPLICIT_SESSION_MAX_SECONDS + 60)
    second = core.resolve_or_open_session("hash-x", None, channel="telegram")
    assert second != first


def test_new_cat_while_open_starts_a_fresh_session(dynamo_table):
    first = core.resolve_or_open_session("hash-y", None, channel="telegram")
    handler._start_new_session("hash-y")
    second = core.resolve_or_open_session("hash-y", None, channel="telegram")
    assert second != first


def test_done_closes_session_and_next_photo_opens_a_new_one(dynamo_table):
    first = core.resolve_or_open_session("hash-z", None, channel="telegram")
    handler._finish_session("hash-z")
    assert (
        dynamo_table.get_item(
            Key={"PK": "SUBMITTER#hash-z", "SK": "ACTIVE_SESSION"}
        ).get("Item")
        is None
    )
    second = core.resolve_or_open_session("hash-z", None, channel="telegram")
    assert second != first


def test_done_reports_the_photo_count(dynamo_table):
    session_id = core.resolve_or_open_session("hash-w", None, channel="telegram")
    core._bump_session(session_id)
    core._bump_session(session_id)
    assert "2 photos" in handler._finish_session("hash-w")[0]


def test_done_with_no_open_session_is_not_an_error(dynamo_table):
    assert "No session open" in handler._finish_session("hash-nobody")[0]


def test_album_replies_exactly_once(dynamo_table):
    assert core.should_reply("mg-album") is True
    assert core.should_reply("mg-album") is False
    assert core.should_reply("mg-album") is False


def test_standalone_photos_always_reply(dynamo_table):
    assert core.should_reply(None) is True
    assert core.should_reply(None) is True


def test_different_albums_each_get_a_reply(dynamo_table):
    assert core.should_reply("mg-1") is True
    assert core.should_reply("mg-2") is True


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
    assert core.sniff_image_type(b"\xff\xd8\xff\xe0rest-of-file") == (
        "image/jpeg",
        "jpg",
    )


def test_sniff_image_type_png():
    assert core.sniff_image_type(b"\x89PNG\r\n\x1a\nrest-of-file") == (
        "image/png",
        "png",
    )


def test_sniff_image_type_rejects_non_image_bytes():
    assert core.sniff_image_type(b"not an image") is None


def test_sniff_video_type_mp4():
    # ISO base media file: a 4-byte size word, then "ftyp" at offset 4 —
    # not offset 0, unlike the image signatures above.
    data = b"\x00\x00\x00\x18ftypmp42" + b"rest-of-file"
    assert core.sniff_video_type(data) == ("video/mp4", "mp4")


def test_sniff_video_type_webm():
    data = b"\x1a\x45\xdf\xa3" + b"rest-of-file"
    assert core.sniff_video_type(data) == ("video/webm", "webm")


def test_sniff_video_type_rejects_non_video_bytes():
    assert core.sniff_video_type(b"not a video") is None


def test_sniff_media_type_detects_a_photo():
    assert core.sniff_media_type(b"\xff\xd8\xff\xe0rest") == (
        "image/jpeg",
        "jpg",
        "photo",
    )


def test_sniff_media_type_detects_a_video():
    data = b"\x00\x00\x00\x18ftypmp42rest-of-file"
    assert core.sniff_media_type(data) == ("video/mp4", "mp4", "video")


def test_sniff_media_type_rejects_unrecognized_bytes():
    assert core.sniff_media_type(b"not media") is None


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


# --------------------------------------------------------------------------
# Session location
# --------------------------------------------------------------------------


def _location_message(lat, lon):
    return {
        "chat": {"id": 42},
        "from": {"id": 42},
        "location": {"latitude": lat, "longitude": lon},
    }


def _map_message(data):
    return {
        "chat": {"id": 42},
        "from": {"id": 42},
        "web_app_data": {"data": data, "button_text": handler.BUTTON_PICK_ON_MAP},
    }


def _session_meta(dynamo_table, session_id):
    return dynamo_table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"})[
        "Item"
    ]


def test_extract_location_reads_a_telegram_location():
    assert handler._extract_location(_location_message(31.26312, 34.80224)) == (
        31.263,
        34.802,
        "telegram",
    )


def test_extract_location_reads_the_map_picker_payload():
    message = _map_message('{"lat": 31.26312, "lon": 34.80224}')
    assert handler._extract_location(message) == (31.263, 34.802, "map")


@pytest.mark.parametrize(
    "data",
    [
        "not json",
        "[31.2, 34.8]",
        '{"lat": "31.2", "lon": 34.8}',
        '{"lat": true, "lon": 34.8}',
        '{"lat": NaN, "lon": 34.8}',
        '{"lat": 91, "lon": 34.8}',
        '{"lat": 31.2, "lon": -181}',
        '{"lat": 31.2}',
    ],
)
def test_extract_location_rejects_malformed_map_payloads(data):
    assert handler._extract_location(_map_message(data)) is None


def test_extract_location_ignores_ordinary_messages():
    assert handler._extract_location(_send_text("hi")) is None


def test_location_pins_the_open_session_rounded(dynamo_table, telegram_calls):
    submitter = handler._submitter_hash(SECRETS, 42)
    session_id = core.resolve_or_open_session(submitter, None, channel="telegram")

    handler._handle_location(
        _location_message(31.26312, 34.80224),
        *handler._extract_location(_location_message(31.26312, 34.80224)),
        SECRETS,
    )

    session = _session_meta(dynamo_table, session_id)
    assert str(session["coarseLat"]) == "31.263"
    assert str(session["coarseLon"]) == "34.802"
    assert session["locationSource"] == "telegram"
    _, body = telegram_calls[-1]
    assert body["text"] == handler.LOCATION_SAVED_TEXT
    # Saving folds the location row away again.
    assert body["reply_markup"] == handler.SESSION_KEYBOARD


def test_location_after_done_still_pins_that_session(dynamo_table):
    session_id = core.resolve_or_open_session("hash-loc", None, channel="telegram")
    core._bump_session(session_id)
    handler._finish_session("hash-loc")

    assert core.set_session_location("hash-loc", 31.263, 34.802, "map") is True
    assert _session_meta(dynamo_table, session_id)["locationSource"] == "map"


def test_location_pins_the_newest_session_not_an_older_one(dynamo_table):
    first = core.resolve_or_open_session("hash-loc", None, channel="telegram")
    handler._start_new_session("hash-loc")
    second = core.resolve_or_open_session("hash-loc", None, channel="telegram")

    core.set_session_location("hash-loc", 31.263, 34.802, "map")
    assert "coarseLat" in _session_meta(dynamo_table, second)
    assert "coarseLat" not in _session_meta(dynamo_table, first)


def test_last_pin_wins(dynamo_table):
    session_id = core.resolve_or_open_session("hash-loc", None, channel="telegram")
    core.set_session_location("hash-loc", 31.1, 34.1, "telegram")
    core.set_session_location("hash-loc", 31.263, 34.802, "map")
    session = _session_meta(dynamo_table, session_id)
    assert str(session["coarseLat"]) == "31.263"
    assert session["locationSource"] == "map"


def test_location_with_no_session_is_refused(dynamo_table, telegram_calls):
    assert core.set_session_location("hash-nobody", 31.263, 34.802, "map") is False


def test_stale_location_is_refused(dynamo_table):
    session_id = core.resolve_or_open_session("hash-loc", None, channel="telegram")
    dynamo_table.update_item(
        Key={"PK": "SUBMITTER#hash-loc", "SK": "LAST_SESSION"},
        UpdateExpression="SET atEpoch = :t",
        ExpressionAttributeValues={
            ":t": core.now_epoch() - core.LOCATION_WINDOW_SECONDS - 60
        },
    )
    assert core.set_session_location("hash-loc", 31.263, 34.802, "map") is False
    assert "coarseLat" not in _session_meta(dynamo_table, session_id)


def test_location_prompt_is_claimed_once_per_session(dynamo_table):
    session_id = core.resolve_or_open_session("hash-ask", None, channel="telegram")
    assert core.claim_location_prompt(session_id) is True
    assert core.claim_location_prompt(session_id) is False


def test_no_prompt_for_a_session_that_already_has_a_location(dynamo_table):
    session_id = core.resolve_or_open_session("hash-ask", None, channel="telegram")
    core.set_session_location("hash-ask", 31.263, 34.802, "map")
    assert core.claim_location_prompt(session_id) is False


def test_done_asks_for_a_location_when_missing(dynamo_table):
    session_id = core.resolve_or_open_session("hash-done", None, channel="telegram")
    core._bump_session(session_id)
    text, keyboard = handler._finish_session("hash-done")
    assert handler.ASK_LOCATION_TEXT in text
    assert keyboard == handler.LOCATION_KEYBOARD


def test_done_does_not_ask_again_once_pinned(dynamo_table):
    session_id = core.resolve_or_open_session("hash-done", None, channel="telegram")
    core._bump_session(session_id)
    core.set_session_location("hash-done", 31.263, 34.802, "map")
    text, keyboard = handler._finish_session("hash-done")
    assert handler.ASK_LOCATION_TEXT not in text
    assert keyboard == handler.SESSION_KEYBOARD


def test_location_keyboard_keeps_the_session_buttons():
    rows = handler.LOCATION_KEYBOARD["keyboard"]
    assert rows[-1] == handler.SESSION_KEYBOARD["keyboard"][0]
    here_now = [b for b in rows[0] if b["text"] == handler.BUTTON_HERE_NOW]
    assert here_now == [{"text": handler.BUTTON_HERE_NOW, "request_location": True}]


def test_map_button_opens_the_picker_when_configured(monkeypatch):
    monkeypatch.setattr(handler, "MAP_PICKER_URL", "https://example.test/map.html")
    first_row = handler._location_keyboard()["keyboard"][0]
    assert first_row[0] == {
        "text": handler.BUTTON_PICK_ON_MAP,
        "web_app": {"url": "https://example.test/map.html"},
    }


def test_location_button_label_as_text_gets_help(dynamo_table, telegram_calls):
    # What clients that can't share location send instead.
    handler._handle_text(
        _send_text(handler.BUTTON_HERE_NOW), handler.BUTTON_HERE_NOW, SECRETS
    )
    _, body = telegram_calls[0]
    assert body["text"] == handler.LOCATION_HELP_TEXT
    assert body["reply_markup"] == handler.LOCATION_KEYBOARD


# --------------------------------------------------------------------------
# Concurrent opens (bursts with no album ID: photos sent one at a time)
# --------------------------------------------------------------------------


def _session_exists(dynamo_table, session_id):
    return "Item" in dynamo_table.get_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"}
    )


def test_concurrent_first_photos_join_one_session(dynamo_table):
    # Invocation A already opened a session; B read "no pointer" just before
    # and now tries to open its own.
    first = core.resolve_or_open_session("hash-burst", None, channel="telegram")
    second = core._open_session(
        "hash-burst", None, explicit=False, channel="telegram", replacing=None
    )
    assert second == first
    sessions = dynamo_table.scan(
        FilterExpression="begins_with(PK, :p)",
        ExpressionAttributeValues={":p": "SESSION#"},
    )["Items"]
    assert [s["sessionId"] for s in sessions] == [first]


def test_replacing_a_stale_pointer_loses_to_whoever_replaced_it_first(dynamo_table):
    winner = core.resolve_or_open_session("hash-burst", None, channel="telegram")
    loser = core._open_session(
        "hash-burst", None, explicit=False, channel="telegram", replacing="already-gone"
    )
    assert loser == winner


def test_explicit_open_always_takes_over(dynamo_table):
    first = core.resolve_or_open_session("hash-burst", None, channel="telegram")
    second = core.open_explicit_session("hash-burst", channel="telegram")
    assert second != first
    assert _session_exists(dynamo_table, second)


def test_sessions_record_their_channel(dynamo_table):
    session_id = core.resolve_or_open_session("hash-ch", None, channel="telegram")
    item = dynamo_table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "META"})
    assert item["Item"]["channel"] == "telegram"


# --------------------------------------------------------------------------
# Contributor profiles: first-touch referral for the stats page
# --------------------------------------------------------------------------


def _profile_for(dynamo_table, tg_user_id=42):
    submitter = handler._submitter_hash(SECRETS, tg_user_id)
    return dynamo_table.get_item(
        Key={"PK": f"SUBMITTER#{submitter}", "SK": "PROFILE"}
    ).get("Item")


def test_start_with_a_tracked_link_records_the_referral(dynamo_table, telegram_calls):
    handler._handle_text(_send_text("/start friend-app"), "/start friend-app", SECRETS)
    profile = _profile_for(dynamo_table)
    assert profile["referral"] == "friend-app"
    assert profile["channel"] == "telegram"
    assert profile["GSI2PK"] == "ENTITY#SUBMITTER"
    assert telegram_calls[0][1]["text"] == handler.START_TEXT


def test_start_without_a_link_is_recorded_as_none(dynamo_table, telegram_calls):
    handler._handle_text(_send_text("/start"), "/start", SECRETS)
    assert _profile_for(dynamo_table)["referral"] == core.NO_REFERRAL


@pytest.mark.parametrize("payload", ["x" * 40, "-lead", "a_b", "a.b", "שלום"])
def test_malformed_start_payloads_are_not_stored(dynamo_table, telegram_calls, payload):
    text = f"/start {payload}"
    handler._handle_text(_send_text(text), text, SECRETS)
    assert _profile_for(dynamo_table)["referral"] == core.NO_REFERRAL


def test_start_payload_is_lowercased(dynamo_table, telegram_calls):
    # A hand-typed slug in a different case shouldn't split one source in two.
    handler._handle_text(_send_text("/start Poster"), "/start Poster", SECRETS)
    assert _profile_for(dynamo_table)["referral"] == "poster"


def test_first_referral_wins(dynamo_table, telegram_calls):
    handler._handle_text(_send_text("/start poster"), "/start poster", SECRETS)
    handler._handle_text(_send_text("/start friend-app"), "/start friend-app", SECRETS)
    profile = _profile_for(dynamo_table)
    assert profile["referral"] == "poster"


def test_first_session_creates_a_profile_without_a_referral(dynamo_table):
    submitter = handler._submitter_hash(SECRETS, 42)
    core.resolve_or_open_session(submitter, None, channel="telegram")
    profile = _profile_for(dynamo_table)
    assert profile["channel"] == "telegram"
    assert "referral" not in profile


def test_photo_first_then_start_still_records_the_link(dynamo_table, telegram_calls):
    submitter = handler._submitter_hash(SECRETS, 42)
    core.resolve_or_open_session(submitter, None, channel="telegram")
    first_seen = _profile_for(dynamo_table)["firstSeenAt"]

    handler._handle_text(_send_text("/start poster"), "/start poster", SECRETS)
    profile = _profile_for(dynamo_table)
    assert profile["referral"] == "poster"
    assert profile["firstSeenAt"] == first_seen


def _photo_update(message_id=7):
    return {
        "body": json.dumps(
            {
                "message": {
                    "message_id": message_id,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "date": 1787600000,
                    "photo": [{"file_id": "f-1", "width": 800, "height": 600}],
                }
            }
        )
    }


def test_a_fetch_that_times_out_asks_for_the_photo_again(
    dynamo_table, telegram_calls, monkeypatch
):
    # 2026-08-24: Telegram's getFile stalled, urllib raised a bare
    # TimeoutError (not a URLError), and five photos vanished silently.
    def time_out(token, file_id):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(handler, "_download_telegram_file", time_out)
    response = handler._process_update(_photo_update(), SECRETS)

    assert response["statusCode"] == 200
    assert [(m, b["text"]) for m, b in telegram_calls] == [
        ("sendMessage", handler.FETCH_FAILED_TEXT)
    ]
    photos = dynamo_table.scan(
        FilterExpression="begins_with(PK, :p)",
        ExpressionAttributeValues={":p": "PHOTO#"},
    )["Items"]
    assert [(p["status"], p["GSI2PK"]) for p in photos] == [
        ("pending", "STATUS#pending")
    ]
