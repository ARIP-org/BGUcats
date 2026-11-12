"""New IDs. A ULID everywhere (CLAUDE.md, "Data model essentials"): time
ordered, and the join key across the table, the bucket and the vectors.

Imports python-ulid, so a function that uses this lists it in its own
requirements.txt.
"""

from ulid import ULID


def new_ulid():
    return str(ULID())
