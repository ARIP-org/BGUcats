"""Who may come in, and as what (docs/app-plan/DECISIONS.md, D1 and R1).

Two roles, `user` and `admin`. An admin is on the allowlist
(`ADMIN#{email}` in bgucats-data) with no role, or with `role = admin`.
Everyone else who is admitted is a user; a collaborator is a user, and
`role = collaborator` on an allowlist item is read as `user`, so no item
has to be rewritten.

Who is admitted is the account's sign-up policy:

    allowlist   only people on the allowlist (staging; production until L3)
    domain      the allowlist, and any address at one of the listed domains
                (BGU's Google accounts, D1)
    open        any signed-in Google account

Used by the sign-up trigger (whether Cognito creates the account at all),
and by both APIs on every call (whether the account is still let in: the
policy or the allowlist may have changed since the account was made).
"""

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)
# Stored before 2026-11-12, and still accepted from the desk's people screen.
LEGACY_USER_ROLES = ("collaborator",)

POLICIES = ("allowlist", "domain", "open")


def role_of(allowlist_item):
    """The role an allowlist item gives. No role field means admin: the
    Terraform bootstrap item and `make admin-add` write none."""
    stored = allowlist_item.get("role")
    if stored == ROLE_USER or stored in LEGACY_USER_ROLES:
        return ROLE_USER
    return ROLE_ADMIN


def normalise_role(value):
    """A role as a request names it, or None if it names none."""
    if value in LEGACY_USER_ROLES:
        return ROLE_USER
    return value if value in ROLES else None


def domains_from(text):
    """ "post.bgu.ac.il, bgu.ac.il" -> ("post.bgu.ac.il", "bgu.ac.il")."""
    return tuple(d.strip().lower() for d in (text or "").split(",") if d.strip())


def admitted(email, allowlist_item, policy, domains):
    """Whether this address may use the app under the policy.

    allowlist_item is the `ADMIN#{email}` item, or None when there is none.
    """
    if allowlist_item is not None:
        return True
    if policy == "open":
        return True
    if policy == "domain":
        _, _, domain = email.rpartition("@")
        return domain.lower() in domains
    return False


def role_for(email, allowlist_item, policy, domains):
    """The caller's role, or None when they are not admitted."""
    if allowlist_item is not None:
        return role_of(allowlist_item)
    if admitted(email, None, policy, domains):
        return ROLE_USER
    return None
