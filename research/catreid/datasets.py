"""Adapters from wildlife-datasets catalogues to `PhotoRecord`.

The whole job of this module is to answer one question per source: **what is a
session here?** Get it wrong and every number downstream is fiction, in exactly
the way CLAUDE.md warns about — every photo in a shelter listing was taken in
one sitting, against the same wall, in the same light, so splitting those by
photo scores the model on matching the wall.

wildlife-datasets standardises a small column vocabulary (`image_id`,
`identity`, `path`, `bbox`, `date`, `keypoints`, `orientation`, `species`,
`video`). Only some of it is session-shaped, so each source gets an explicit
policy rather than a guess:

    VIDEO     a `video` column — one clip is one encounter. Strongest signal.
    DATE_GAP  a `date` column — cluster an identity's photos by time gap, the
              same rule the Telegram ingest path uses to group a submitter's
              photos into one session.
    COLUMN    an explicit listing/folder/source column.
    NONE      no session information exists in this source.

NONE is not a fallback to "every photo is its own session". That substitution
is precisely the bug, so a NONE source is usable for *training* and refuses to
produce an *evaluation* split at all.
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from catreid.records import PhotoRecord

# Mirrors SESSION_IDLE_WINDOW_SECONDS in the ingest handler. One encounter with
# one cat, whether the photos arrive over Telegram or sit in a public archive.
DEFAULT_SESSION_GAP_SECONDS = 10 * 60


class SessionPolicy(Enum):
    VIDEO = "video"
    DATE_GAP = "date_gap"
    COLUMN = "column"
    NONE = "none"


class SessionPolicyError(ValueError):
    """A source cannot supply sessions honestly for the use requested."""


@dataclass(frozen=True)
class SourceDataset:
    """Records plus the provenance of their session ids.

    `for_evaluation()` is the gate: a source whose sessions were invented
    cannot be split for evaluation, so the refusal happens here rather than
    silently producing a flattering number three modules later.
    """

    name: str
    records: list[PhotoRecord]
    policy: SessionPolicy
    notes: str = ""

    @property
    def eval_grade(self):
        return self.policy is not SessionPolicy.NONE

    def for_training(self):
        return self.records

    def for_evaluation(self):
        if not self.eval_grade:
            raise SessionPolicyError(
                f"{self.name} carries no session information, so a split built "
                "from it would put photos from one sitting on both sides and "
                "report fiction. Usable for training only. "
                f"{self.notes}".strip()
            )
        return self.records

    def summary(self):
        return {
            "name": self.name,
            "images": len(self.records),
            "identities": len({r.identity for r in self.records}),
            "sessions": len({r.session for r in self.records}),
            "policy": self.policy.value,
            "eval_grade": self.eval_grade,
        }


def _column(row, name):
    """Read a catalogue cell, normalising pandas' several flavours of missing.

    A missing value arrives as None, float NaN, or — in a datetime column —
    NaT, which is none of the above and whose .timestamp() raises rather than
    returning anything. pandas.isna is the one check that covers all three.
    """
    value = row.get(name)
    if value is None or pd.isna(value):
        return None
    return value


def records_from_dataframe(
    dataframe,
    name,
    policy,
    session_column=None,
    gap_seconds=DEFAULT_SESSION_GAP_SECONDS,
    path_prefix="",
    notes="",
):
    """Build a `SourceDataset` from a wildlife-datasets catalogue."""
    rows = dataframe.to_dict("records")
    if not rows:
        raise SessionPolicyError(f"{name}: empty catalogue")

    for required in ("image_id", "identity", "path"):
        if required not in dataframe.columns:
            raise SessionPolicyError(f"{name}: catalogue has no '{required}' column")

    if policy is SessionPolicy.VIDEO:
        sessions = _sessions_from_column(rows, "video", name)
    elif policy is SessionPolicy.COLUMN:
        if not session_column:
            raise SessionPolicyError("COLUMN policy needs a session_column")
        sessions = _sessions_from_column(rows, session_column, name)
    elif policy is SessionPolicy.DATE_GAP:
        sessions = _sessions_from_date_gaps(rows, name, gap_seconds)
    else:
        # Every image becomes its own session id, which is deliberately
        # useless: SourceDataset.for_evaluation() refuses this policy, so the
        # ids only ever reach training code that ignores them.
        sessions = {str(row["image_id"]): f"{name}:no-session" for row in rows}

    records = [
        PhotoRecord(
            image_id=str(row["image_id"]),
            identity=str(row["identity"]),
            session=sessions[str(row["image_id"])],
            path=f"{path_prefix}{row['path']}",
        )
        for row in rows
    ]
    return SourceDataset(name=name, records=records, policy=policy, notes=notes)


def _sessions_from_column(rows, column, name):
    missing = sum(1 for row in rows if _column(row, column) is None)
    if missing:
        raise SessionPolicyError(
            f"{name}: '{column}' is empty for {missing} of {len(rows)} rows, so "
            "those images have no honest session. Fix the adapter or drop them "
            "explicitly rather than letting them default."
        )
    return {
        str(row["image_id"]): f"{name}:{row['identity']}:{_column(row, column)}"
        for row in rows
    }


def _sessions_from_date_gaps(rows, name, gap_seconds):
    """Cluster each identity's photos into encounters separated by a time gap.

    Same rule as the ingest handler's idle window: consecutive photos of one
    cat within the window belong to one encounter. Applied per identity, never
    globally — two different cats photographed in the same minute are two
    sessions, not one.
    """
    missing = sum(1 for row in rows if _column(row, "date") is None)
    if missing:
        raise SessionPolicyError(
            f"{name}: 'date' is empty for {missing} of {len(rows)} rows; a "
            "date-gap policy cannot place those images in an encounter."
        )

    by_identity = defaultdict(list)
    for row in rows:
        by_identity[str(row["identity"])].append(row)

    sessions = {}
    for identity, identity_rows in by_identity.items():
        ordered = sorted(identity_rows, key=lambda r: _to_epoch(_column(r, "date")))
        index, previous = 0, None
        for row in ordered:
            stamp = _to_epoch(_column(row, "date"))
            if previous is not None and stamp - previous > gap_seconds:
                index += 1
            sessions[str(row["image_id"])] = f"{name}:{identity}:{index}"
            previous = stamp
    return sessions


def _to_epoch(value):
    if hasattr(value, "timestamp"):
        return value.timestamp()
    raise SessionPolicyError(f"date value {value!r} is not a timestamp")


def policy_for_columns(columns):
    """Pick the strongest session policy a catalogue's columns can support."""
    if "video" in columns:
        return SessionPolicy.VIDEO
    if "date" in columns:
        return SessionPolicy.DATE_GAP
    return SessionPolicy.NONE


def from_wildlife_dataset(dataset, name=None, **kwargs):
    """Adapt a loaded wildlife-datasets object, choosing the policy for it.

    `dataset.df` is the standardised catalogue; `dataset.root` prefixes the
    relative paths in it.
    """
    name = name or type(dataset).__name__
    dataframe = dataset.df
    policy = kwargs.pop("policy", None) or policy_for_columns(dataframe.columns)
    prefix = kwargs.pop("path_prefix", None)
    if prefix is None:
        root = getattr(dataset, "root", "") or ""
        prefix = f"{root.rstrip('/')}/" if root else ""

    notes = kwargs.pop("notes", "")
    if policy is SessionPolicy.NONE:
        notes = notes or (
            f"{name}'s catalogue has neither a 'video' nor a 'date' column; its "
            "folders are identities, not listings, so no capture boundary "
            "survives in the data."
        )

    return records_from_dataframe(
        dataframe, name=name, policy=policy, path_prefix=prefix, notes=notes, **kwargs
    )
