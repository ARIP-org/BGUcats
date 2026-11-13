"""Reports: what both APIs agree on (docs/app-plan/06-moderation.md,
"Reports, blocks and bans"; docs/data-model.md, "Proposals, reports,
moderation"). Apple's rule 1.2 for content people make: report it, block
the person, and someone who acts within a day.
"""

# What can be reported, and what its id is: a post's id; a person's user id
# (their page, or their photo); a name in a cat's poll, "{catId}/{nameKey}".
TARGETS = ("post", "user", "avatar", "name")

# Why. A fixed list, so a report is something to count; the words a person
# reads are the app's strings (web/i18n/, "report.reason.*").
REASONS = ("spam", "offensive", "harassment", "privacy", "not_cat", "other")

# open: waits for an admin. actioned: an admin hid or removed the thing.
# dismissed: an admin looked and left it.
STATUSES = ("open", "actioned", "dismissed")

NOTE_MAX = 280
# This many different people reporting a post hide it until an admin looks.
HIDE_AT = 3


def report_key(report_id):
    return {"PK": f"REPORT#{report_id}", "SK": "META"}


def reported_pk(target_type, target_id):
    """The partition that holds one item per person who reported a thing:
    counting it is "how many different people"."""
    return f"REPORTED#{target_type}#{target_id}"
