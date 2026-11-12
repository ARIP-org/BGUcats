"""A new-cat proposal's fixed choices (docs/app-plan/01-product.md, "2b ·
New cat"), the one list both APIs check against. A proposal's id becomes
the cat's id when an admin approves it, so approving twice makes one cat.
"""

COATS = ("ginger", "black", "white", "gray", "tabby", "calico", "tuxedo")
TRAITS = ("friendly", "shy", "ear-tipped", "kitten", "collar")
# "Where does it hang out?": one of the campus places, or this.
ELSEWHERE = "elsewhere"

STATUSES = ("open", "approved", "merged", "rejected")
