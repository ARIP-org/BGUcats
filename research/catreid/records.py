"""The common shape every other module speaks.

One row per image. Three fields carry the whole evaluation contract:

    identity   which cat this is — the thing we are trying to predict
    session    the capture that produced it — the unit we must split on
    path       where the pixels are

`session` has no default on purpose. The single easiest way to report fiction
in this project is to let it fall back to the image id, which silently turns a
session split into a photo split and inflates every number (CLAUDE.md,
"Evaluation"). Every adapter has to state what a session means for its source —
for public data, one listing or one source folder.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PhotoRecord:
    image_id: str
    identity: str
    session: str
    path: str


def sessions_by_identity(records):
    """identity -> sorted list of its distinct session ids."""
    grouped = {}
    for record in records:
        grouped.setdefault(record.identity, set()).add(record.session)
    return {identity: sorted(sessions) for identity, sessions in grouped.items()}


def records_by_session(records):
    """session -> list of its records, input order preserved."""
    grouped = {}
    for record in records:
        grouped.setdefault(record.session, []).append(record)
    return grouped


def identities(records):
    return {record.identity for record in records}


def sessions(records):
    return {record.session for record in records}
