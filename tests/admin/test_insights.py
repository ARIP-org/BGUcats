"""The stats page's arithmetic, on plain lists — no DynamoDB involved."""

from datetime import UTC, datetime, timedelta

from admin import insights

# 10:00 UTC = 13:00 in Israel (IDT, UTC+3) on 2026-10-20.
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


def _media(n, *, submitter="a", session="s1", cat=None, day="2026-10-20", **extra):
    return [
        {
            "photoId": f"{submitter}{session}{i}",
            "submitterHash": submitter * 64,
            "sessionId": session,
            "catId": cat,
            "status": "labeled" if cat else "unlabeled",
            "createdAt": f"{day}T09:00:00.000Z",
            **extra,
        }
        for i in range(n)
    ]


def _build(media=(), *, profiles=(), traffic=(), links=(), cats=(), sessions=None):
    return insights.build(
        media=list(media),
        duplicates=0,
        sessions=sessions or {},
        profiles=list(profiles),
        traffic=list(traffic),
        links=list(links),
        cats=list(cats),
        now=NOW,
    )


def test_local_day_uses_israel_time_not_utc():
    # 22:30 UTC on the 19th is already 01:30 on the 20th in Beer Sheva.
    assert insights.local_day("2026-10-19T22:30:00.000Z").isoformat() == "2026-10-20"


def test_local_day_tolerates_junk():
    assert insights.local_day(None) is None
    assert insights.local_day("yesterday") is None


def test_a_cat_is_ready_only_with_two_separate_sessions():
    cats = [{"catId": "c1", "name": "Burst"}, {"catId": "c2", "name": "Regular"}]
    media = _media(40, session="s1", cat="c1") + (
        _media(2, session="s2", cat="c2") + _media(1, session="s3", cat="c2")
    )
    result = _build(media, cats=cats)

    by_name = {c["name"]: c for c in result["cats"]}
    assert by_name["Burst"]["media"] == 40
    assert by_name["Burst"]["ready"] is False
    assert by_name["Regular"]["ready"] is True
    assert result["summary"]["catsReady"] == 1


def test_cats_with_no_photos_are_still_listed():
    result = _build(cats=[{"catId": "c1", "name": "Ghost"}])
    assert result["cats"] == [
        {
            "catId": "c1",
            "name": "Ghost",
            "media": 0,
            "sessions": 0,
            "contributors": 0,
            "lastSeen": None,
            "ready": False,
        }
    ]


def test_this_week_and_last_week_are_split_on_israel_days():
    media = _media(3, day="2026-10-20") + _media(2, day="2026-10-10")
    summary = _build(media)["summary"]
    assert summary["mediaThisWeek"] == 3
    assert summary["mediaLastWeek"] == 2


def test_contributors_without_a_profile_count_as_no_link():
    result = _build(_media(2, submitter="a"))
    (row,) = result["referrals"]
    assert row["referral"] == "none"
    assert row["contributors"] == 1
    assert row["media"] == 2


def test_a_profile_without_photos_is_a_person_but_not_a_contributor():
    profiles = [
        {
            "submitterHash": "b" * 64,
            "referral": "poster",
            "firstSeenAt": "2026-10-19T08:00:00Z",
        }
    ]
    result = _build(_media(1, submitter="a"), profiles=profiles)
    assert result["summary"]["people"] == 2
    assert result["summary"]["contributors"] == 1
    (poster,) = [r for r in result["referrals"] if r["referral"] == "poster"]
    assert poster["people"] == 1
    assert poster["contributors"] == 0


def test_first_seen_is_the_earliest_photo_when_the_profile_is_younger():
    # Sent photos in August, got a profile on the next session in October.
    media = _media(1, submitter="a", day="2026-08-24")
    profiles = [{"submitterHash": "a" * 64, "firstSeenAt": "2026-10-20T08:00:00.000Z"}]
    result = _build(media, profiles=profiles)
    assert result["contributors"]["top"][0]["firstSeen"].startswith("2026-08-24")
    assert result["summary"]["newContributorsThisWeek"] == 0


def test_returning_means_photos_on_two_different_days():
    media = _media(1, submitter="a", day="2026-10-01") + _media(
        1, submitter="a", session="s2", day="2026-10-05"
    )
    media += _media(5, submitter="b")
    assert _build(media)["summary"]["returningContributors"] == 1


def test_contribution_buckets_and_concentration():
    media = (
        _media(30, submitter="a") + _media(3, submitter="b") + _media(1, submitter="c")
    )
    breakdown = _build(media)["contributors"]
    assert [b["count"] for b in breakdown["buckets"]] == [1, 1, 0, 1]
    assert breakdown["top"][0]["id"] == "a" * 8
    assert breakdown["topShare"] == 30 / 34


def test_traffic_is_summed_per_referral_and_per_day():
    traffic = [
        {
            "day": "2026-10-20",
            "referral": "poster",
            "visits": 5,
            "visitors": 4,
            "botClicks": 1,
        },
        {"day": "2026-10-19", "referral": "poster", "visits": 2, "visitors": 2},
        {"day": "2026-10-20", "referral": "direct", "visits": 1, "visitors": 1},
    ]
    result = _build(traffic=traffic)
    (poster,) = [r for r in result["referrals"] if r["referral"] == "poster"]
    assert (poster["visits"], poster["visitors"], poster["botClicks"]) == (7, 6, 1)
    assert result["summary"]["visitorsThisWeek"] == 7
    today = result["daily"][-1]
    assert today["date"] == "2026-10-20"
    assert today["visitors"] == 5


def test_daily_series_is_thirty_days_ending_today():
    daily = _build()["daily"]
    assert len(daily) == insights.DAYS
    assert daily[0]["date"] == "2026-09-21"
    assert daily[-1]["date"] == "2026-10-20"


def test_a_registered_link_shows_up_before_any_traffic():
    links = [{"slug": "friend", "label": "Friend's app", "partnerViews": 1000}]
    (row,) = _build(links=links)["referrals"]
    assert row["referral"] == "friend"
    assert row["link"]["label"] == "Friend's app"
    assert row["link"]["partnerViews"] == 1000
    assert row["link"]["partnerPlays"] is None


def test_location_counts_a_pinned_session_or_exif_gps():
    media = _media(1, session="pinned") + _media(1, session="exif", coarseLat=31.26)
    media += _media(1, session="nowhere")
    sessions = {"pinned": {"coarseLat": 31.262}, "exif": {}, "nowhere": {}}
    summary = _build(media, sessions=sessions)["summary"]
    assert summary["sessions"] == 3
    assert summary["sessionsWithLocation"] == 2


def test_old_photos_without_a_channel_are_telegram():
    (row,) = _build(_media(2))["channels"]
    assert row == {"channel": "telegram", "contributors": 1, "media": 2}


def test_only_uploads_pending_for_over_an_hour_count_as_stalled():
    pending = [
        {
            "photoId": "OLD",
            "sessionId": "S1",
            "createdAt": "2026-08-24T20:03:02.956161Z",
        },
        {
            "photoId": "APP",
            "sessionId": "S2",
            "channel": "app",
            "createdAt": (NOW - timedelta(hours=2)).isoformat(),
        },
        {
            "photoId": "FRESH",
            "sessionId": "S3",
            "createdAt": (NOW - timedelta(minutes=5)).isoformat(),
        },
        {"photoId": "JUNK", "createdAt": None},
    ]
    stalled = insights.build(
        media=[],
        duplicates=0,
        sessions={},
        profiles=[],
        traffic=[],
        links=[],
        cats=[],
        now=NOW,
        pending=pending,
    )["stalled"]

    assert stalled["count"] == 2
    assert [(i["photoId"], i["channel"]) for i in stalled["items"]] == [
        ("OLD", "telegram"),  # oldest first; no channel means Telegram
        ("APP", "app"),
    ]


def test_nothing_stalled_by_default():
    assert _build()["stalled"] == {"count": 0, "items": []}
