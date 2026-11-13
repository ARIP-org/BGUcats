"""A cat's name poll: what both APIs agree on (docs/app-plan/04-api.md,
"Cats"; docs/data-model.md, "Cats, as the app sees them").

An option is `CAT#{catId}` / `NAME#{nameKey}`. The key is the name as people
would compare it, so "Mango", "mango " and "MANGO" are one option; the name
shown is the first spelling suggested.
"""

from common import text

NAME_MAX = 24

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
