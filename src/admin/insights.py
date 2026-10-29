"""The stats page: where contributors come from, and how far the dataset has got.

Computed on request from the table rather than kept as running counters. At
campus scale — a few thousand photos, fifty cats — that is a handful of GSI2
queries, and a recount can't drift the way an incremented counter does when
a merge or a reject is retried. Running counters are the upgrade path if the
table ever outgrows this. The landing page's traffic is the one exception:
a visit leaves no other record to recount, so the beacon Lambda keeps daily
counters for it.

Pure functions over lists of items, so every number on the page is
unit-testable without DynamoDB.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Days as the campus lives them — the same zone the beacon buckets visits in.
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")
DAYS = 30
WEEK = 7
TOP_CONTRIBUTORS = 10

# A cat needs photos from at least this many separate encounters before it
# can sit on both sides of a session-split evaluation: one session in train,
# another in test (CLAUDE.md, "Evaluation"). Photo count alone overstates
# readiness — forty frames of one burst are one encounter.
EVAL_MIN_SESSIONS = 2

# ingest.core.NO_REFERRAL. A contributor with no profile at all — everyone
# from before profiles existed — reads the same way.
NO_REFERRAL = "none"
# Photos from before WhatsApp existed carry no channel; all of them came
# through Telegram.
DEFAULT_CHANNEL = "telegram"

# (lowest, highest or None, label) — how many photos each contributor sent.
CONTRIBUTION_BUCKETS = (
    (1, 1, "1 photo"),
    (2, 5, "2–5"),
    (6, 20, "6–20"),
    (21, None, "21+"),
)

PARTNER_FIELDS = ("partnerViews", "partnerPlays", "partnerClicks")

# A record still `pending` this long after it was written has lost its file:
# a bot fetch takes seconds, and the app's outbox retries within minutes of
# the phone coming back online. Write order (spec §10) means the record says
# so honestly; this is where someone finally gets to read it.
STALLED_AFTER = timedelta(hours=1)
STALLED_SHOWN = 10


def local_day(iso):
    """The Israel calendar day of an ISO-8601 UTC timestamp, or None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(LOCAL_TZ).date()
    except (TypeError, ValueError):
        return None


def build(
    *, media, duplicates, sessions, profiles, traffic, links, cats, now, pending=()
):
    """Everything the stats page shows, as one JSON-ready dict.

    media      photo/video items that count as data (unlabeled + labeled)
    duplicates number of byte-identical re-sends, reported but not counted
    pending    items still `pending` — written, but their file never confirmed
    sessions   {sessionId: Session item} for every session in `media`
    profiles   SUBMITTER#…/PROFILE items (ingest.core.record_contributor)
    traffic    TRAFFIC# daily counters from the beacon Lambda
    links      LINK# tracked links registered in the admin tool
    cats       CAT# items
    now        timezone-aware datetime; injected so tests can pin "today"
    """
    today = now.astimezone(LOCAL_TZ).date()
    contributors = _contributors(media, profiles)
    people = _people(contributors, profiles)

    return {
        "generatedAt": now.isoformat(),
        "timezone": str(LOCAL_TZ),
        "summary": _summary(
            media, duplicates, sessions, contributors, people, traffic, cats, today
        ),
        "daily": _daily(media, contributors, people, traffic, today),
        "referrals": _referrals(traffic, people, contributors, links),
        "channels": _channels(contributors),
        "contributors": _contributor_breakdown(contributors, len(media)),
        "cats": _cats(media, cats),
        "stalled": _stalled(pending, now),
        "evalMinSessions": EVAL_MIN_SESSIONS,
    }


def _stalled(pending, now):
    """Uploads whose record was written but whose file never arrived, oldest
    first. Younger ones are still in flight and are left out."""
    cutoff = now - STALLED_AFTER
    stalled = []
    for item in pending:
        try:
            created = datetime.fromisoformat(item.get("createdAt") or "")
        except ValueError:
            continue
        if created <= cutoff:
            stalled.append(item)
    stalled.sort(key=lambda item: item["createdAt"])
    return {
        "count": len(stalled),
        "items": [
            {
                "photoId": item.get("photoId"),
                "sessionId": item.get("sessionId"),
                "channel": item.get("channel") or DEFAULT_CHANNEL,
                "createdAt": item.get("createdAt"),
            }
            for item in stalled[:STALLED_SHOWN]
        ],
    }


# --------------------------------------------------------------------------
# Who: contributors (sent at least one photo) and people (any contact)
# --------------------------------------------------------------------------


def _contributors(media, profiles):
    by_hash = {}
    for item in media:
        submitter = item.get("submitterHash")
        if not submitter:
            continue
        c = by_hash.get(submitter)
        if c is None:
            c = by_hash[submitter] = {
                "hash": submitter,
                "photos": 0,
                "videos": 0,
                "sessions": set(),
                "cats": set(),
                "days": set(),
                "first": None,
                "last": None,
                "channel": item.get("channel") or DEFAULT_CHANNEL,
            }
        if item.get("mediaType") == "video":
            c["videos"] += 1
        else:
            c["photos"] += 1
        if item.get("sessionId"):
            c["sessions"].add(item["sessionId"])
        if item.get("catId"):
            c["cats"].add(item["catId"])
        created = item.get("createdAt")
        if created:
            c["first"] = min(c["first"] or created, created)
            c["last"] = max(c["last"] or created, created)
            day = local_day(created)
            if day:
                c["days"].add(day)

    profile_by_hash = {p.get("submitterHash"): p for p in profiles}
    for c in by_hash.values():
        profile = profile_by_hash.get(c["hash"]) or {}
        c["referral"] = profile.get("referral") or NO_REFERRAL
        # A profile can be younger than the photos it describes — everyone
        # who sent photos before profiles existed got one on their next
        # session — so the earliest photo is the better "first seen".
        if profile.get("firstSeenAt") and c["first"]:
            c["first"] = min(c["first"], profile["firstSeenAt"])
        c["media"] = c["photos"] + c["videos"]
    return list(by_hash.values())


def _people(contributors, profiles):
    """Everyone who has ever talked to a bot, photos or not."""
    people = {
        c["hash"]: {"referral": c["referral"], "first": c["first"]}
        for c in contributors
    }
    for profile in profiles:
        submitter = profile.get("submitterHash")
        if submitter and submitter not in people:
            people[submitter] = {
                "referral": profile.get("referral") or NO_REFERRAL,
                "first": profile.get("firstSeenAt"),
            }
    return people


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def _summary(media, duplicates, sessions, contributors, people, traffic, cats, today):
    this_week = {today - timedelta(days=i) for i in range(WEEK)}
    last_week = {today - timedelta(days=i) for i in range(WEEK, 2 * WEEK)}

    media_days = [local_day(item.get("createdAt")) for item in media]
    session_ids = {item["sessionId"] for item in media if item.get("sessionId")}
    located = {
        item["sessionId"]
        for item in media
        if item.get("sessionId") and item.get("coarseLat") is not None
    } | {
        sid
        for sid in session_ids
        if (sessions.get(sid) or {}).get("coarseLat") is not None
    }

    def traffic_total(counter, days):
        return sum(int(t.get(counter) or 0) for t in traffic if _traffic_day(t) in days)

    per_cat_sessions = defaultdict(set)
    for item in media:
        if item.get("catId") and item.get("sessionId"):
            per_cat_sessions[item["catId"]].add(item["sessionId"])

    return {
        "media": len(media),
        "videos": sum(1 for item in media if item.get("mediaType") == "video"),
        "labeled": sum(1 for item in media if item.get("status") == "labeled"),
        "unlabeled": sum(1 for item in media if item.get("status") == "unlabeled"),
        "duplicates": duplicates,
        "mediaThisWeek": sum(1 for d in media_days if d in this_week),
        "mediaLastWeek": sum(1 for d in media_days if d in last_week),
        "sessions": len(session_ids),
        "sessionsWithLocation": len(located),
        "contributors": len(contributors),
        "newContributorsThisWeek": sum(
            1 for c in contributors if local_day(c["first"]) in this_week
        ),
        "returningContributors": sum(1 for c in contributors if len(c["days"]) >= 2),
        "people": len(people),
        "cats": len(cats),
        "catsReady": sum(
            1 for s in per_cat_sessions.values() if len(s) >= EVAL_MIN_SESSIONS
        ),
        "visitsThisWeek": traffic_total("visits", this_week),
        "visitorsThisWeek": traffic_total("visitors", this_week),
        "visitorsLastWeek": traffic_total("visitors", last_week),
        "botClicksThisWeek": traffic_total("botClicks", this_week),
    }


def _daily(media, contributors, people, traffic, today):
    days = [today - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    rows = {
        d: {
            "media": 0,
            "newContributors": 0,
            "newPeople": 0,
            "visits": 0,
            "visitors": 0,
            "botClicks": 0,
        }
        for d in days
    }

    def bump(day, key, amount=1):
        if day in rows:
            rows[day][key] += amount

    for item in media:
        bump(local_day(item.get("createdAt")), "media")
    for c in contributors:
        bump(local_day(c["first"]), "newContributors")
    for person in people.values():
        bump(local_day(person["first"]), "newPeople")
    for t in traffic:
        for counter in ("visits", "visitors", "botClicks"):
            bump(_traffic_day(t), counter, int(t.get(counter) or 0))

    return [{"date": d.isoformat(), **rows[d]} for d in days]


def _referrals(traffic, people, contributors, links):
    """One row per source, all time — the funnel from landing to photos.

    All time rather than the last thirty days because the partner's numbers
    (ad views, plays, clicks) arrive as running totals: they only line up
    with ours over the same span.
    """
    rows = defaultdict(
        lambda: {
            "visits": 0,
            "visitors": 0,
            "botClicks": 0,
            "people": 0,
            "contributors": 0,
            "media": 0,
        }
    )
    for t in traffic:
        row = rows[t.get("referral") or "direct"]
        for counter in ("visits", "visitors", "botClicks"):
            row[counter] += int(t.get(counter) or 0)
    for person in people.values():
        rows[person["referral"]]["people"] += 1
    for c in contributors:
        rows[c["referral"]]["contributors"] += 1
        rows[c["referral"]]["media"] += c["media"]

    registered = {link["slug"]: link for link in links if link.get("slug")}
    for slug in registered:
        rows[slug]  # a fresh link shows up before anyone has used it

    result = []
    for slug, row in rows.items():
        link = registered.get(slug)
        entry = {"referral": slug, **row, "link": None}
        if link:
            entry["link"] = {
                "label": link.get("label") or slug,
                "createdAt": link.get("createdAt"),
                "partnerReportedAt": link.get("partnerReportedAt"),
                **{f: _int_or_none(link.get(f)) for f in PARTNER_FIELDS},
            }
        result.append(entry)
    result.sort(key=lambda r: (-(r["visitors"] + r["people"]), r["referral"]))
    return result


def _channels(contributors):
    rows = defaultdict(lambda: {"contributors": 0, "media": 0})
    for c in contributors:
        rows[c["channel"]]["contributors"] += 1
        rows[c["channel"]]["media"] += c["media"]
    return [
        {"channel": channel, **row}
        for channel, row in sorted(rows.items(), key=lambda kv: -kv[1]["media"])
    ]


def _contributor_breakdown(contributors, total_media):
    buckets = []
    for low, high, label in CONTRIBUTION_BUCKETS:
        buckets.append(
            {
                "label": label,
                "count": sum(
                    1
                    for c in contributors
                    if c["media"] >= low and (high is None or c["media"] <= high)
                ),
            }
        )

    ranked = sorted(contributors, key=lambda c: (-c["media"], c["first"] or ""))
    top = [
        {
            # Eight hex characters of a salted hash: enough to tell people
            # apart on this page, useless for finding them anywhere else.
            "id": c["hash"][:8],
            "media": c["media"],
            "videos": c["videos"],
            "sessions": len(c["sessions"]),
            "cats": len(c["cats"]),
            "activeDays": len(c["days"]),
            "firstSeen": c["first"],
            "lastSeen": c["last"],
            "channel": c["channel"],
            "referral": c["referral"],
        }
        for c in ranked[:TOP_CONTRIBUTORS]
    ]
    return {
        "buckets": buckets,
        "top": top,
        # How much of the dataset rests on one person's phone.
        "topShare": (ranked[0]["media"] / total_media) if ranked and total_media else 0,
    }


def _cats(media, cats):
    per_cat = defaultdict(
        lambda: {"media": 0, "sessions": set(), "contributors": set(), "last": None}
    )
    for item in media:
        cat_id = item.get("catId")
        if not cat_id:
            continue
        row = per_cat[cat_id]
        row["media"] += 1
        if item.get("sessionId"):
            row["sessions"].add(item["sessionId"])
        if item.get("submitterHash"):
            row["contributors"].add(item["submitterHash"])
        created = item.get("createdAt")
        if created:
            row["last"] = max(row["last"] or created, created)

    result = []
    for cat in cats:
        row = per_cat.get(cat["catId"]) or per_cat.default_factory()
        sessions = len(row["sessions"])
        result.append(
            {
                "catId": cat["catId"],
                "name": cat.get("name") or "?",
                "media": row["media"],
                "sessions": sessions,
                "contributors": len(row["contributors"]),
                "lastSeen": row["last"],
                "ready": sessions >= EVAL_MIN_SESSIONS,
            }
        )
    result.sort(key=lambda r: (-r["media"], r["name"].lower()))
    return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _traffic_day(item):
    """The beacon already stored an Israel calendar day; just parse it."""
    try:
        return date.fromisoformat(item.get("day") or "")
    except ValueError:
        return None


def _int_or_none(value):
    return None if value is None else int(value)
