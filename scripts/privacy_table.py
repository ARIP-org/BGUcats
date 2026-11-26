"""What the app keeps about a person, as App Store Connect asks it (O16).

Apple's "App Privacy" form asks, for each of its kinds of data, whether the
app collects it, whether it is linked to the person, and what for. The
answers are easy to get wrong by memory and easy to let go stale, so they
are written here beside the reason for each, and held to the code:

- KEYS says, for every key prefix and sort key `src/` writes (the same
  ones `docs/data-model.md` is held to), which of Apple's kinds it holds,
  or that it holds nothing about a person. A new key with no entry fails
  `tests/test_privacy_table.py`: whoever adds it decides, in the same pull
  request, what it means for a person's privacy.
- ELSEWHERE is what is kept outside the two tables.
- `docs/privacy-data.md` is this file's output and nothing else:

      python scripts/privacy_table.py > docs/privacy-data.md

Apple's words (the kinds, "collect", "linked") are from
https://developer.apple.com/app-store/app-privacy-details/ as read on
2026-11-14. "Collect" is sending data off the phone and keeping it longer
than the request takes; what stays on the phone (the upload queue, "App
info") is not collected.

Written before the app has moderation (C1) or push on a phone (N2): each
of those changes an answer, and the pull request that builds it changes
this file. B10a (deleting what the app's table holds) and B10b (signing
out and deleting the Cognito user) changed "Deleting" below.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EMAIL = "Email Address"
NAME = "Name"
LOCATION = "Precise Location"
CONTACTS = "Contacts"
PHOTOS = "Photos or Videos"
CONTENT = "Other User Content"
USER_ID = "User ID"
DEVICE_ID = "Device ID"
USAGE = "Other Usage Data"
DIAGNOSTICS = "Other Diagnostic Data"

FUNCTION = "App Functionality"

# Apple's kind -> (its group on the form, why this app has it). Every kind
# here is linked to the person and used for App Functionality only: there
# is no advertising, no analytics service and no tracking in this app.
KINDS = {
    EMAIL: (
        "Contact Info",
        (
            "The Google account a person signs in with: who may sign in, and whose "
            "account it is. Never shown to another member."
        ),
    ),
    NAME: (
        "Contact Info",
        (
            "The Google account's name, which sign-in receives, and the display "
            "name a person chooses for others to see."
        ),
    ),
    LOCATION: (
        "Location",
        (
            "Where a cat was met: the phone's position when a photo is taken, "
            "rounded to three decimal places (about 100 m) before it is stored. "
            "Apple calls three decimal places or more precise. A photo that arrives "
            "as a file (the phone's own camera, or the library) is stored as it is, "
            "with whatever position it carries."
        ),
    ),
    CONTACTS: (
        "Contacts",
        (
            "Who a person's friends are in the app, and whom they blocked. Apple's "
            "kind includes a social graph. The phone's address book is not read."
        ),
    ),
    PHOTOS: (
        "User Content",
        (
            "The photos of cats a person takes, which are also the dataset the "
            "recognition model is measured on, and their profile photo."
        ),
    ),
    CONTENT: (
        "User Content",
        (
            "What a person writes or chooses: posts, name ideas and votes, likes, "
            "feedings, new-cat proposals, reports, and which cat they said they met."
        ),
    ),
    USER_ID: (
        "Identifiers",
        (
            "The account's id, the username, and the sign-in service's id for the "
            "Google account."
        ),
    ),
    DEVICE_ID: (
        "Identifiers",
        (
            "The phone's address for Apple's notifications and the id the app gives "
            "the phone. Only once notifications are turned on (N2)."
        ),
    ),
    USAGE: (
        "Usage Data",
        (
            "What the app counts from a person's activity: cats met, points, "
            "badges, and short-lived counters that limit how often an action can "
            "be repeated."
        ),
    ),
    DIAGNOSTICS: (
        "Diagnostics",
        (
            "The servers' logs, which name account ids, and for an admin's actions "
            "email addresses."
        ),
    ),
}

# Apple's kinds this app does not collect, with the reason where one could
# be doubted.
NOT_COLLECTED = {
    "Phone Number": "Finding friends by phone number (D5) is not built.",
    "Physical Address": "",
    "Other User Contact Info": "",
    "Health": "",
    "Fitness": "",
    "Payment Info": "",
    "Credit Info": "",
    "Other Financial Info": "",
    "Coarse Location": "What is stored is three decimal places: see Precise Location.",
    "Sensitive Info": "",
    "Emails or Text Messages": "",
    "Audio Data": "A video's sound is not kept apart from the video.",
    "Gameplay Content": "",
    "Customer Support": "",
    "Browsing History": "",
    "Search History": "The gallery's search runs on the phone.",
    "Purchase History": "",
    "Product Interaction": "No taps, screens or launches are sent anywhere.",
    "Advertising Data": "",
    "Crash Data": "No crash reporter. \"App info\" stays on the phone unless its owner copies it.",
    "Performance Data": "",
    "Environment Scanning": "",
    "Hands": "",
    "Head": "",
    "Other Data Types": "",
}

# Every key prefix (`XXX#`) and sort key the code writes -> the kinds it
# holds about a person, and what that is. An empty tuple: nothing about a
# person. The table is docs/data-model.md's, read with one question.
KEYS = {
    # ---- bgucats-data: the dataset
    "CAT#": ((), "a cat"),
    "SESSION#": ((EMAIL, LOCATION), "an encounter: who started it (app encounters) and where"),
    "PHOTO#": ((PHOTOS, LOCATION), "a photo's record: its place, taken from the phone or the file"),
    "SHA#": ((), "a photo's checksum"),
    "PREDICTION#": ((), "the model's guess for a session"),
    "PREDICTION": ((), "the model's guess for a session"),
    "PICK": ((CONTENT,), "which cat a person said they met"),
    "VECTOR#": ((), "a cat photo's vector"),
    "VECTOR": ((), "a cat photo's vector"),
    "ADMIN#": ((EMAIL,), "who may sign in, by email, and their role"),
    "SUBMITTER#": ((USER_ID,), "a contributor, by a hash of their chat id (salted) or of their email address (not salted)"),
    "ACTIVE_SESSION": ((), "the bot's open session"),
    "LAST_SESSION": ((), "the bot's last session"),
    "TGMSG#": ((), "a Telegram message, once (the bot, not the app)"),
    "MGREPLY#": ((), "an album's one reply (the bot)"),
    "RATE#": ((USAGE,), "how often a person did one thing lately; removed by itself"),
    "TRAFFIC#": ((), "the landing page's daily counts, with no visitor in them"),
    "LINK#": ((), "a tracked link's name"),
    "ENTITY#": ((EMAIL,), "an index: lists of one kind; an app encounter's holds its starter's email"),
    "STATUS#": ((), "an index: the labeling queue"),
    "META": ((), "the main item of whatever its partition is"),
    # ---- bgucats-social: people
    "USER#": ((USER_ID,), "everything of one account, under its id"),
    "PROFILE": ((EMAIL, NAME, USER_ID, PHOTOS), "the account: email, username, display name, profile photo, settings"),
    "IDENTITY#": ((EMAIL, USER_ID), "sign-in: from an email to its account"),
    "USERNAME#": ((USER_ID,), "from a username to its account"),
    "INVITE#": ((USER_ID,), "from an invite code to its account"),
    "FRIEND#": ((CONTACTS,), "a friendship"),
    "FRIEND": ((CONTACTS,), "a friendship"),
    "FREQ#": ((CONTACTS,), "a friend request (not written yet)"),
    "BLOCK#": ((CONTACTS,), "a block"),
    "BLOCK": ((CONTACTS,), "a block"),
    "BLOCKEDBY#": ((CONTACTS,), "a block, from the other side"),
    "BLOCKEDBY": ((CONTACTS,), "a block, from the other side"),
    "DEVICE#": ((DEVICE_ID,), "a phone's address for notifications"),
    "DEVICE": ((DEVICE_ID,), "a phone's address for notifications"),
    "PUSHED#": ((USAGE,), "how many notifications a person was sent today; removed by itself"),
    "PUSHED": ((USAGE,), "how many notifications a person was sent today; removed by itself"),
    "STATS#": ((USAGE,), "a person's counters"),
    "STATS": ((USAGE,), "a person's counters"),
    "MET#": ((USAGE,), "a cat a person met"),
    "MET": ((USAGE,), "a cat a person met"),
    "METM#": ((USAGE,), "what a person adds to a cat's popularity in a month"),
    "METM": ((USAGE,), "what a person adds to a cat's popularity in a month"),
    "BADGE#": ((USAGE,), "a badge a person earned"),
    "BADGE": ((USAGE,), "a badge a person earned"),
    "ENC#": ((CONTENT,), "an encounter as the app counts it: whose, which cat they said"),
    "ENC": ((CONTENT,), "an encounter as the app counts it: whose, which cat they said"),
    "FED#": ((CONTENT,), "a feeding: who, which cat, when"),
    "FED": ((CONTENT,), "a feeding: who, which cat, when"),
    "FEDCAT#": ((CONTENT,), "a person's last feeding of one cat"),
    "FEDCAT": ((CONTENT,), "a person's last feeding of one cat"),
    # ---- bgucats-social: posts, cats, the rest
    "POST#": ((CONTENT, PHOTOS), "a post: its author, text and photos"),
    "LIKE#": ((CONTENT,), "a like"),
    "LIKE": ((CONTENT,), "a like"),
    "AUTHOR#": ((USER_ID,), "an index: a person's own posts"),
    "FEED#": ((), "an index: a month of the feed"),
    "CATPOST#": ((), "an index: a cat's posts"),
    "PUBLIC": ((), "a cat's public counters"),
    "NAME#": ((CONTENT,), "a name idea, and who suggested it"),
    "NAME": ((CONTENT,), "a name idea, and who suggested it"),
    "VOTE#": ((CONTENT,), "a vote on a cat's name"),
    "VOTE": ((CONTENT,), "a vote on a cat's name"),
    "PROPOSAL#": ((CONTENT,), "a new-cat proposal, and who made it"),
    "PROPOSALS#": ((), "an index: proposals by state"),
    "PROPOSER#": ((USER_ID,), "an index: a person's own proposals"),
    "REPORT#": ((CONTENT,), "a report: who reported, whom or what, and their note"),
    "REPORTS#": ((), "an index: reports by state"),
    "REPORTED#": ((), "what was reported"),
    "BY#": ((CONTENT,), "who reported it"),
    "BY": ((CONTENT,), "who reported it"),
    "MOD#": ((), "a moderation run (not written yet)"),
    "RUN#": ((), "a moderation run (not written yet)"),
    "SPEND#": ((), "the day's use of the moderation service (not written yet)"),
}

# Kept somewhere other than the two tables.
ELSEWHERE = [
    ("The media bucket, `raw/` and `derived/`", (PHOTOS, LOCATION), "Every photo as it arrived, and smaller copies with their EXIF removed. An original that arrived as a file keeps its own EXIF, position included."),
    ("The media bucket, `avatars/`", (PHOTOS,), "Profile photos, made small on the phone, with no EXIF."),
    ("The sign-in service (Cognito)", (EMAIL, NAME, USER_ID), "The Google account's email, name, picture address and id, as Google gives them at sign-in."),
    ("The servers' logs (CloudWatch)", (DIAGNOSTICS, USER_ID, EMAIL), "Account ids on most writes; email addresses where an admin adds or removes a person. No retention is set: they are kept until someone deletes them."),
]

# What the form's answers do not say and a reviewer may ask.
NOTES = [
    "**Tracking: no.** Nothing is shared with a data broker or joined with anyone else's data for advertising. There is no advertising SDK and no analytics SDK in the app.",
    "**Who else holds it.** Amazon Web Services stores and runs everything, as a processor. Google is asked who a person is at sign-in and is sent nothing else. When moderation is built (C1) Google will also be sent what is about to become public; this file changes with it.",
    "**Deleting.** `DELETE /api/v1/me` (B10a) deletes everything the app's own table holds about the person: profile, username, invite code, friends, requests, blocks, likes, votes, feedings, counters, badges, devices and the profile photo; their posts are removed and no longer name them, names they suggested and reports they made stay with them cut out. Since B10b the person is signed out of every device and their sign-in (the Cognito user) is deleted first, before anything in the table; a token already handed out works for up to an hour after, and is answered as deleted while the job runs. In the dataset, the photos, encounters and answers to \"Who did you meet?\" they sent stay (D14), and since #135 their email address is taken off them, and off the list of who may sign in unless they are an admin. What still links them: a hash of the address, not salted, on those encounters and photos. There is no button for it in the app yet (the Swift app's profile). Apple requires one before the App Store.",
    "**Not from the iPhone app.** The Telegram bot's contributors are in the same tables (`SUBMITTER#`, `TGMSG#`) under a salted hash, and the landing page counts visits with no visitor in them. Neither is the app's collection.",
]

PREFIX = re.compile(r"""["']([A-Z][A-Z_]+#)""")
SORT_KEY = re.compile(r"""["']SK["']\s*:\s*f?["']([A-Z][A-Z_]*)["'#{]""")


def keys_in_code():
    """Every key prefix and sort key `src/` writes, as tests/test_data_model_doc.py finds them."""
    found = set()
    for path in sorted((REPO / "src").rglob("*.py")):
        text = path.read_text()
        found |= set(PREFIX.findall(text)) | set(SORT_KEY.findall(text))
    return found


def where(kind):
    """The keys and the other places that hold one kind, for the answers' last column."""
    keys = sorted({key.rstrip("#") for key, (kinds, _) in KEYS.items() if kind in kinds})
    places = [place for place, kinds, _ in ELSEWHERE if kind in kinds]
    return ", ".join([f"`{key}`" for key in keys] + places)


def render():
    lines = [
        "# What the app keeps about a person",
        "",
        "For App Store Connect's \"App Privacy\" answers (owner step O16) and for",
        "the privacy policy (O10). **Do not edit this file:** it is the output of",
        "`scripts/privacy_table.py`, where every line has its reason, and",
        "`tests/test_privacy_table.py` fails if the two differ or if the code",
        "writes a key the script does not classify.",
        "",
        "Apple's words are from its App Privacy Details page as read on",
        "2026-11-14. \"Collected\" means sent off the phone and kept; \"linked\"",
        "means tied to the person's account.",
        "",
        "## The answers",
        "",
        "Every kind below is **linked to the person** and used for **App",
        "Functionality** only.",
        "",
        "| Apple's group | Kind | Why the app has it | Where it is kept |",
        "|---|---|---|---|",
    ]
    for kind, (group, why) in KINDS.items():
        lines.append(f"| {group} | **{kind}** | {why} | {where(kind)} |")
    lines += [
        "",
        "## Not collected",
        "",
        "| Kind | |",
        "|---|---|",
    ]
    for kind, why in NOT_COLLECTED.items():
        lines.append(f"| {kind} | {why} |")
    lines += ["", "## To know before answering", ""]
    lines += [f"- {note}" for note in NOTES]
    lines += [
        "",
        "## Outside the two tables",
        "",
        "| Where | Kinds | What |",
        "|---|---|---|",
    ]
    for place, kinds, what in ELSEWHERE:
        lines.append(f"| {place} | {', '.join(kinds)} | {what} |")
    lines += [
        "",
        "## Every key, read with one question",
        "",
        "The keys are `docs/data-model.md`'s. \"Nothing\" is nothing about a person.",
        "",
        "| Key | Holds | Kinds |",
        "|---|---|---|",
    ]
    for key, (kinds, what) in sorted(KEYS.items()):
        lines.append(f"| `{key}` | {what} | {', '.join(kinds) or 'Nothing'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render())
