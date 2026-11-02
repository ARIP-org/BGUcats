"""Adapter tests.

The important behaviour is refusal: a source with no session information must
not quietly become a source where every photo is its own session, because that
is the exact substitution that turns a reported number into fiction.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from catreid.datasets import (
    SessionPolicy,
    SessionPolicyError,
    from_wildlife_dataset,
    policy_for_columns,
    records_from_dataframe,
)
from catreid.splits import SplitError, open_set_split

BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def frame(rows):
    return pd.DataFrame(rows)


def catalogue_without_sessions(n_identities=4, per_identity=5):
    """The CatIndividualImages shape: image_id, identity, path. Nothing else."""
    rows = []
    for i in range(n_identities):
        for j in range(per_identity):
            rows.append(
                {
                    "image_id": f"img{i}_{j}",
                    "identity": f"cat{i}",
                    "path": f"cat{i}/img{j}.jpg",
                }
            )
    return frame(rows)


class TestPolicySelection:
    def test_video_column_wins(self):
        assert policy_for_columns(["image_id", "date", "video"]) is SessionPolicy.VIDEO

    def test_date_is_the_fallback(self):
        assert policy_for_columns(["image_id", "date"]) is SessionPolicy.DATE_GAP

    def test_bare_catalogue_has_no_policy(self):
        assert (
            policy_for_columns(["image_id", "identity", "path"]) is SessionPolicy.NONE
        )


class TestNoSessionInformation:
    def test_marked_not_eval_grade(self):
        source = records_from_dataframe(
            catalogue_without_sessions(), name="bare", policy=SessionPolicy.NONE
        )
        assert source.eval_grade is False

    def test_training_still_works(self):
        source = records_from_dataframe(
            catalogue_without_sessions(), name="bare", policy=SessionPolicy.NONE
        )
        assert len(source.for_training()) == 20

    def test_evaluation_is_refused_with_a_reason(self):
        source = records_from_dataframe(
            catalogue_without_sessions(), name="bare", policy=SessionPolicy.NONE
        )
        with pytest.raises(SessionPolicyError, match="training only"):
            source.for_evaluation()

    def test_photos_do_not_become_their_own_sessions(self):
        # The failure this whole module exists to prevent: 20 images must not
        # turn into 20 sessions, which would look like a perfectly splittable
        # dataset to everything downstream.
        source = records_from_dataframe(
            catalogue_without_sessions(), name="bare", policy=SessionPolicy.NONE
        )
        assert len({r.session for r in source.records}) == 1

    def test_a_bare_source_cannot_be_split_even_if_the_gate_is_bypassed(self):
        source = records_from_dataframe(
            catalogue_without_sessions(), name="bare", policy=SessionPolicy.NONE
        )
        with pytest.raises(SplitError):
            open_set_split(source.records)


class TestVideoPolicy:
    def test_one_clip_is_one_session(self):
        df = frame(
            [
                {"image_id": "a1", "identity": "cat1", "path": "a1.jpg", "video": 1},
                {"image_id": "a2", "identity": "cat1", "path": "a2.jpg", "video": 1},
                {"image_id": "a3", "identity": "cat1", "path": "a3.jpg", "video": 2},
            ]
        )
        source = records_from_dataframe(df, name="vid", policy=SessionPolicy.VIDEO)
        sessions = {r.image_id: r.session for r in source.records}
        assert sessions["a1"] == sessions["a2"] != sessions["a3"]

    def test_same_clip_number_for_different_cats_is_not_one_session(self):
        df = frame(
            [
                {"image_id": "a", "identity": "cat1", "path": "a.jpg", "video": 1},
                {"image_id": "b", "identity": "cat2", "path": "b.jpg", "video": 1},
            ]
        )
        source = records_from_dataframe(df, name="vid", policy=SessionPolicy.VIDEO)
        assert len({r.session for r in source.records}) == 2

    def test_missing_video_values_are_refused(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "video": 1},
                {"image_id": "b", "identity": "c", "path": "b.jpg", "video": None},
            ]
        )
        with pytest.raises(SessionPolicyError, match="empty for 1 of 2"):
            records_from_dataframe(df, name="vid", policy=SessionPolicy.VIDEO)


class TestDateGapPolicy:
    def test_photos_close_in_time_share_a_session(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "date": BASE},
                {
                    "image_id": "b",
                    "identity": "c",
                    "path": "b.jpg",
                    "date": BASE + timedelta(minutes=2),
                },
            ]
        )
        source = records_from_dataframe(df, name="d", policy=SessionPolicy.DATE_GAP)
        assert len({r.session for r in source.records}) == 1

    def test_a_long_gap_starts_a_new_session(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "date": BASE},
                {
                    "image_id": "b",
                    "identity": "c",
                    "path": "b.jpg",
                    "date": BASE + timedelta(hours=3),
                },
            ]
        )
        source = records_from_dataframe(df, name="d", policy=SessionPolicy.DATE_GAP)
        assert len({r.session for r in source.records}) == 2

    def test_gap_is_measured_per_identity(self):
        # Two cats photographed in the same minute are two encounters.
        df = frame(
            [
                {"image_id": "a", "identity": "c1", "path": "a.jpg", "date": BASE},
                {"image_id": "b", "identity": "c2", "path": "b.jpg", "date": BASE},
            ]
        )
        source = records_from_dataframe(df, name="d", policy=SessionPolicy.DATE_GAP)
        assert len({r.session for r in source.records}) == 2

    def test_window_is_configurable(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "date": BASE},
                {
                    "image_id": "b",
                    "identity": "c",
                    "path": "b.jpg",
                    "date": BASE + timedelta(minutes=30),
                },
            ]
        )
        wide = records_from_dataframe(
            df, name="d", policy=SessionPolicy.DATE_GAP, gap_seconds=3600
        )
        narrow = records_from_dataframe(
            df, name="d", policy=SessionPolicy.DATE_GAP, gap_seconds=60
        )
        assert len({r.session for r in wide.records}) == 1
        assert len({r.session for r in narrow.records}) == 2

    def test_out_of_order_rows_still_cluster(self):
        df = frame(
            [
                {
                    "image_id": "late",
                    "identity": "c",
                    "path": "l.jpg",
                    "date": BASE + timedelta(hours=5),
                },
                {"image_id": "early", "identity": "c", "path": "e.jpg", "date": BASE},
                {
                    "image_id": "mid",
                    "identity": "c",
                    "path": "m.jpg",
                    "date": BASE + timedelta(minutes=1),
                },
            ]
        )
        source = records_from_dataframe(df, name="d", policy=SessionPolicy.DATE_GAP)
        sessions = {r.image_id: r.session for r in source.records}
        assert sessions["early"] == sessions["mid"] != sessions["late"]

    def test_missing_dates_are_refused(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "date": BASE},
                {"image_id": "b", "identity": "c", "path": "b.jpg", "date": None},
            ]
        )
        with pytest.raises(SessionPolicyError, match="empty for 1 of 2"):
            records_from_dataframe(df, name="d", policy=SessionPolicy.DATE_GAP)


class TestColumnPolicy:
    def test_listing_column_becomes_the_session(self):
        df = frame(
            [
                {"image_id": "a", "identity": "c", "path": "a.jpg", "listing": "L1"},
                {"image_id": "b", "identity": "c", "path": "b.jpg", "listing": "L1"},
                {"image_id": "d", "identity": "c", "path": "d.jpg", "listing": "L2"},
            ]
        )
        source = records_from_dataframe(
            df, name="s", policy=SessionPolicy.COLUMN, session_column="listing"
        )
        assert len({r.session for r in source.records}) == 2

    def test_column_policy_needs_a_column(self):
        with pytest.raises(SessionPolicyError, match="needs a session_column"):
            records_from_dataframe(
                catalogue_without_sessions(), name="s", policy=SessionPolicy.COLUMN
            )


class TestCatalogueValidation:
    @pytest.mark.parametrize("missing", ["image_id", "identity", "path"])
    def test_required_columns(self, missing):
        df = catalogue_without_sessions().drop(columns=[missing])
        with pytest.raises(SessionPolicyError, match=f"no '{missing}' column"):
            records_from_dataframe(df, name="x", policy=SessionPolicy.NONE)

    def test_empty_catalogue(self):
        df = pd.DataFrame(columns=["image_id", "identity", "path"])
        with pytest.raises(SessionPolicyError, match="empty catalogue"):
            records_from_dataframe(df, name="x", policy=SessionPolicy.NONE)


class TestFromWildlifeDataset:
    class FakeDataset:
        def __init__(self, df, root="/data/x"):
            self.df = df
            self.root = root

    def test_bare_catalogue_gets_none_policy_and_an_explanation(self):
        source = from_wildlife_dataset(
            self.FakeDataset(catalogue_without_sessions()), name="CatIndividualImages"
        )
        assert source.policy is SessionPolicy.NONE
        assert "folders are identities" in source.notes

    def test_root_prefixes_paths(self):
        source = from_wildlife_dataset(
            self.FakeDataset(catalogue_without_sessions()), name="x"
        )
        assert source.records[0].path.startswith("/data/x/")

    def test_video_catalogue_is_eval_grade(self):
        df = catalogue_without_sessions()
        df["video"] = [i // 5 for i in range(len(df))]
        source = from_wildlife_dataset(self.FakeDataset(df), name="x")
        assert source.policy is SessionPolicy.VIDEO
        assert source.eval_grade is True
        assert source.for_evaluation()

    def test_summary_reports_the_policy(self):
        source = from_wildlife_dataset(
            self.FakeDataset(catalogue_without_sessions()), name="bare"
        )
        summary = source.summary()
        assert summary["policy"] == "none"
        assert summary["eval_grade"] is False
        assert summary["identities"] == 4


class TestThinning:
    def build(self, identities=3, sessions=5, frames=10):
        from catreid.datasets import SessionPolicy, SourceDataset
        from catreid.records import PhotoRecord

        records = [
            PhotoRecord(
                image_id=f"c{i}_s{s}_f{f}",
                identity=f"cat{i}",
                session=f"c{i}_s{s}",
                path=f"/c{i}_s{s}_f{f}.jpg",
            )
            for i in range(identities)
            for s in range(sessions)
            for f in range(frames)
        ]
        return SourceDataset("x", records, SessionPolicy.VIDEO)

    def test_caps_sessions_per_identity(self):
        from catreid.datasets import cap_sessions_per_identity

        capped = cap_sessions_per_identity(self.build(), max_sessions=2)
        per_identity = {}
        for record in capped.records:
            per_identity.setdefault(record.identity, set()).add(record.session)
        assert all(len(s) == 2 for s in per_identity.values())

    def test_every_identity_survives_the_cap(self):
        from catreid.datasets import cap_sessions_per_identity

        capped = cap_sessions_per_identity(self.build(identities=6), max_sessions=1)
        assert len({r.identity for r in capped.records}) == 6

    def test_capping_keeps_sessions_whole(self):
        from catreid.datasets import cap_sessions_per_identity

        capped = cap_sessions_per_identity(self.build(), max_sessions=2)
        counts = {}
        for record in capped.records:
            counts[record.session] = counts.get(record.session, 0) + 1
        assert all(count == 10 for count in counts.values())

    def test_capping_is_deterministic(self):
        from catreid.datasets import cap_sessions_per_identity

        first = cap_sessions_per_identity(self.build(), max_sessions=2, seed=5)
        second = cap_sessions_per_identity(self.build(), max_sessions=2, seed=5)
        assert [r.image_id for r in first.records] == [
            r.image_id for r in second.records
        ]

    def test_thins_frames_within_a_session(self):
        from catreid.datasets import thin_frames_per_session

        thinned = thin_frames_per_session(self.build(frames=10), max_frames=3)
        counts = {}
        for record in thinned.records:
            counts[record.session] = counts.get(record.session, 0) + 1
        assert all(count == 3 for count in counts.values())

    def test_thinning_never_drops_a_session(self):
        from catreid.datasets import thin_frames_per_session

        source = self.build()
        thinned = thin_frames_per_session(source, max_frames=1)
        assert {r.session for r in thinned.records} == {
            r.session for r in source.records
        }

    def test_thinning_spreads_across_the_capture(self):
        # Even spacing, not the first N — a burst's first three frames are
        # the same instant and carry none of the pose variation.
        from catreid.datasets import thin_frames_per_session

        thinned = thin_frames_per_session(self.build(frames=10), max_frames=3)
        first_session = min(r.session for r in thinned.records)
        frames = [r.image_id for r in thinned.records if r.session == first_session]
        assert frames == ["c0_s0_f0", "c0_s0_f3", "c0_s0_f6"]

    def test_short_sessions_are_left_alone(self):
        from catreid.datasets import thin_frames_per_session

        thinned = thin_frames_per_session(self.build(frames=2), max_frames=5)
        assert len(thinned.records) == 3 * 5 * 2

    def test_thinned_source_keeps_its_policy(self):
        from catreid.datasets import SessionPolicy, thin_frames_per_session

        thinned = thin_frames_per_session(self.build(), max_frames=2)
        assert thinned.policy is SessionPolicy.VIDEO
        assert thinned.eval_grade is True

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_nonsense_limits(self, bad):
        from catreid.datasets import cap_sessions_per_identity, thin_frames_per_session

        with pytest.raises(SessionPolicyError):
            cap_sessions_per_identity(self.build(), max_sessions=bad)
        with pytest.raises(SessionPolicyError):
            thin_frames_per_session(self.build(), max_frames=bad)
