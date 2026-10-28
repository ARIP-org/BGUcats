"""Session-aware and held-out-identity splitting.

Two rules, both from CLAUDE.md, and both of them easy to break by accident:

1. **Split by session, never by photo.** Two frames from one burst are
   near-identical. One in the gallery and one in the query means the model is
   scored on matching the wall, not the cat.

2. **Open-set from the first run: hold out whole identities.** The product
   question is "is this a cat I know, or a new one?", and the only honest proxy
   for cat #51 is an identity the model has never enrolled. Holding out photos
   of enrolled cats measures something else entirely.

Both rules are enforced here and re-checked by `assert_no_session_leak` and
`assert_no_identity_leak`, which are cheap enough to run on every split rather
than only in tests.
"""

import random
from dataclasses import dataclass

from catreid.records import PhotoRecord, records_by_session, sessions_by_identity

# A known identity needs at least one session to enrol from and one distinct
# session to be queried with. One-session identities cannot be "known" without
# putting the same capture on both sides of the split.
MIN_SESSIONS_FOR_KNOWN = 2


class SplitError(ValueError):
    """A split was requested that cannot be built honestly."""


@dataclass(frozen=True)
class OpenSetSplit:
    """Gallery plus two query sets, scored separately and never pooled.

    `query_known` measures recognition; `query_unknown` measures rejection.
    An aggregate over both hides which half is failing (CLAUDE.md).
    """

    gallery: list[PhotoRecord]
    query_known: list[PhotoRecord]
    query_unknown: list[PhotoRecord]
    known_identities: frozenset[str]
    unknown_identities: frozenset[str]
    ineligible_identities: frozenset[str]

    def summary(self):
        return {
            "gallery_images": len(self.gallery),
            "query_known_images": len(self.query_known),
            "query_unknown_images": len(self.query_unknown),
            "known_identities": len(self.known_identities),
            "unknown_identities": len(self.unknown_identities),
            "ineligible_identities": len(self.ineligible_identities),
        }


def split_by_session(records, test_fraction=0.3, seed=0):
    """Closed-set split: whole sessions to one side or the other.

    Used for ordinary train/test work. For anything that reports a recognition
    number, prefer `open_set_split` — a closed-set score answers a question
    nobody asks of this product.
    """
    if not 0.0 < test_fraction < 1.0:
        raise SplitError(f"test_fraction must be in (0, 1), got {test_fraction}")

    grouped = records_by_session(records)
    # Sorted before shuffling so the result depends on the seed alone, never on
    # dict insertion order or the order the dataset happened to be read in.
    session_ids = sorted(grouped)
    random.Random(seed).shuffle(session_ids)

    cut = round(len(session_ids) * test_fraction)
    test_sessions = set(session_ids[:cut])

    train, test = [], []
    for session_id in sorted(grouped):
        (test if session_id in test_sessions else train).extend(grouped[session_id])

    assert_no_session_leak(train, test)
    return train, test


def open_set_split(
    records,
    unknown_fraction=0.3,
    gallery_sessions_per_identity=1,
    seed=0,
):
    """Split into an enrolled gallery and known/unknown query sets.

    Identities are partitioned first: a fraction become "unknown" and are never
    enrolled at all, so every one of their images should be rejected as a new
    cat. The rest are "known" — their sessions are then split so that enrolment
    and query never share a capture.

    Identities with fewer than `MIN_SESSIONS_FOR_KNOWN` sessions cannot be known
    without leaking a session across the split. They are reported as
    `ineligible_identities` rather than quietly dropped: on some public sources
    most cats appear in exactly one listing, which caps how much of the data can
    measure recognition at all, and that is a number worth seeing.
    """
    if not 0.0 < unknown_fraction < 1.0:
        raise SplitError(f"unknown_fraction must be in (0, 1), got {unknown_fraction}")
    if gallery_sessions_per_identity < 1:
        raise SplitError("gallery_sessions_per_identity must be at least 1")

    per_identity = sessions_by_identity(records)
    if not per_identity:
        raise SplitError("no records to split")

    eligible = sorted(
        identity
        for identity, session_ids in per_identity.items()
        if len(session_ids) > gallery_sessions_per_identity
    )
    ineligible = frozenset(per_identity) - frozenset(eligible)

    rng = random.Random(seed)

    # Unknowns are drawn from the full identity list, not just the eligible
    # ones: a cat seen in a single listing is a perfectly good unknown, and
    # excluding it would make the unknown set unrepresentatively rich.
    all_identities = sorted(per_identity)
    shuffled = list(all_identities)
    rng.shuffle(shuffled)

    unknown_target = round(len(all_identities) * unknown_fraction)
    unknown, known = set(), []
    for identity in shuffled:
        if len(unknown) < unknown_target:
            unknown.add(identity)
        elif identity in eligible:
            known.append(identity)

    if not known:
        raise SplitError(
            "no identity has enough distinct sessions to be enrolled and queried "
            f"(need more than {gallery_sessions_per_identity}); "
            f"{len(ineligible)} of {len(all_identities)} identities are single-session"
        )

    by_session = records_by_session(records)
    gallery, query_known, query_unknown = [], [], []

    for identity in sorted(known):
        session_ids = list(per_identity[identity])
        rng.shuffle(session_ids)
        enrolled = session_ids[:gallery_sessions_per_identity]
        queried = session_ids[gallery_sessions_per_identity:]
        for session_id in enrolled:
            gallery.extend(by_session[session_id])
        for session_id in queried:
            query_known.extend(by_session[session_id])

    for identity in sorted(unknown):
        for session_id in per_identity[identity]:
            query_unknown.extend(by_session[session_id])

    split = OpenSetSplit(
        gallery=gallery,
        query_known=query_known,
        query_unknown=query_unknown,
        known_identities=frozenset(known),
        unknown_identities=frozenset(unknown),
        ineligible_identities=ineligible,
    )

    assert_no_session_leak(split.gallery, split.query_known)
    assert_no_session_leak(split.gallery, split.query_unknown)
    assert_no_identity_leak(split.gallery, split.query_unknown)
    return split


def assert_no_session_leak(left, right):
    """Raise if any session has images on both sides.

    This is the check that keeps a reported number from being fiction, so it
    runs in production code rather than only in tests.
    """
    shared = {record.session for record in left} & {record.session for record in right}
    if shared:
        example = sorted(shared)[:3]
        raise SplitError(
            f"{len(shared)} session(s) appear on both sides of the split; "
            f"photos from one capture would be scored against each other: {example}"
        )


def assert_no_identity_leak(gallery, query_unknown):
    """Raise if an 'unknown' identity was in fact enrolled."""
    shared = {record.identity for record in gallery} & {
        record.identity for record in query_unknown
    }
    if shared:
        example = sorted(shared)[:3]
        raise SplitError(
            f"{len(shared)} identity/identities marked unknown are enrolled in the "
            f"gallery, so rejection accuracy would be meaningless: {example}"
        )
