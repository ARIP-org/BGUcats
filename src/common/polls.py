"""A cat's name poll: what both APIs agree on (docs/app-plan/04-api.md,
"Cats"; docs/data-model.md, "Cats, as the app sees them").

An option is `CAT#{catId}` / `NAME#{nameKey}`. The key is the name as people
would compare it, so "Mango", "mango " and "MANGO" are one option; the name
shown is the first spelling suggested.
"""

from common import text

NAME_MAX = 24
# An admin's lock may be any name a cat can have in the dataset.
LOCK_MAX = 80

# pending: suggested, not yet checked; its author's alone.
# live: in the poll. rejected: refused by the check. removed: by an admin.
STATUSES = ("pending", "live", "rejected", "removed")


def clean_name(value):
    """The name as it will be shown, or ApiError(400)."""
    return text.clean(value, "name", NAME_MAX)


def name_key(name):
    """What makes two spellings one option: the cleaned name, case folded."""
    return clean_name(name).casefold()


def option_key(cat_id, key):
    return {"PK": f"CAT#{cat_id}", "SK": f"NAME#{key}"}


def vote_key(cat_id, user_id):
    return {"PK": f"CAT#{cat_id}", "SK": f"VOTE#{user_id}"}


def shown_name(cat, public):
    """(name, where it came from): an admin's lock, else the poll's leader,
    else the admin's name (docs/app-plan/03-data-model.md, D6). `cat` is the
    dataset's item, `public` the app's `CAT#{catId}` / `PUBLIC`."""
    if public.get("lockedName"):
        return public["lockedName"], "admin"
    if public.get("leaderName"):
        return public["leaderName"], "poll"
    if cat.get("name"):
        return cat["name"], "admin"
    return None, "none"


def leader(options):
    """The option that names the cat: live, with the most votes, the earlier
    suggestion on a tie; None while nobody has voted. Both APIs show it
    through this. The events Lambda, which writes it to the cat's public
    item, carries no shared code and has the same rule as `lead`."""
    voted = [
        o for o in options if o.get("status") == "live" and int(o.get("votes") or 0) > 0
    ]
    voted.sort(
        key=lambda o: (-int(o["votes"]), o.get("createdAt") or "", o["nameKey"])
    )
    return voted[0] if voted else None
