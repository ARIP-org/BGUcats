"""The splitters decide whether every number this project reports is real.

These tests are deliberately adversarial about the two ways to produce
fiction: putting one capture on both sides of a split, and measuring
"is this a new cat" against cats the model has already enrolled.
"""

import pytest

from catreid.records import PhotoRecord
from catreid.splits import (
    SplitError,
    assert_no_identity_leak,
    assert_no_session_leak,
    open_set_split,
    split_by_session,
)


def make_records(spec):
    """spec: {identity: {session: n_photos}} -> flat list of records."""
    records = []
    for identity, sessions in spec.items():
        for session, count in sessions.items():
            for index in range(count):
                image_id = f"{identity}-{session}-{index}"
                records.append(
                    PhotoRecord(
                        image_id=image_id,
                        identity=identity,
                        session=session,
                        path=f"/data/{image_id}.jpg",
                    )
                )
    return records


def population(n_identities=10, sessions_each=3, photos_each=4):
    return make_records(
        {
            f"cat{i}": {f"cat{i}_s{s}": photos_each for s in range(sessions_each)}
            for i in range(n_identities)
        }
    )


class TestSplitBySession:
    def test_no_session_spans_both_sides(self):
        train, test = split_by_session(population(), test_fraction=0.3, seed=0)
        assert {r.session for r in train} & {r.session for r in test} == set()

    def test_every_record_lands_somewhere_exactly_once(self):
        records = population()
        train, test = split_by_session(records, test_fraction=0.3, seed=0)
        assert sorted(r.image_id for r in train + test) == sorted(
            r.image_id for r in records
        )

    def test_a_session_is_never_torn_apart(self):
        records = population()
        train, test = split_by_session(records, test_fraction=0.5, seed=1)
        for side in (train, test):
            by_session = {}
            for record in side:
                by_session.setdefault(record.session, 0)
                by_session[record.session] += 1
            # every session present on this side must be present in full
            for session, count in by_session.items():
                expected = sum(1 for r in records if r.session == session)
                assert count == expected

    def test_deterministic_for_a_seed(self):
        records = population()
        first = split_by_session(records, seed=7)
        second = split_by_session(records, seed=7)
        assert [r.image_id for r in first[1]] == [r.image_id for r in second[1]]

    def test_insertion_order_does_not_change_the_split(self):
        records = population()
        shuffled = list(reversed(records))
        baseline = sorted(r.image_id for r in split_by_session(records, seed=3)[1])
        reordered = sorted(r.image_id for r in split_by_session(shuffled, seed=3)[1])
        assert baseline == reordered

    @pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
    def test_rejects_degenerate_fractions(self, fraction):
        with pytest.raises(SplitError):
            split_by_session(population(), test_fraction=fraction)


class TestOpenSetSplit:
    def test_gallery_and_known_query_share_no_session(self):
        split = open_set_split(population(), seed=0)
        assert_no_session_leak(split.gallery, split.query_known)

    def test_unknown_identities_are_never_enrolled(self):
        split = open_set_split(population(), seed=0)
        enrolled = {r.identity for r in split.gallery}
        assert enrolled & split.unknown_identities == set()

    def test_every_known_identity_appears_on_both_sides(self):
        split = open_set_split(population(), seed=0)
        in_gallery = {r.identity for r in split.gallery}
        in_query = {r.identity for r in split.query_known}
        assert in_gallery == split.known_identities
        assert in_query == split.known_identities

    def test_unknown_query_holds_only_unknown_identities(self):
        split = open_set_split(population(), seed=0)
        assert {r.identity for r in split.query_unknown} == split.unknown_identities

    def test_single_session_identities_cannot_be_known(self):
        records = make_records(
            {
                "multi1": {"multi1_a": 3, "multi1_b": 3},
                "multi2": {"multi2_a": 3, "multi2_b": 3},
                "multi3": {"multi3_a": 3, "multi3_b": 3},
                "lonely": {"lonely_a": 5},
            }
        )
        split = open_set_split(records, unknown_fraction=0.25, seed=0)
        assert "lonely" not in split.known_identities

    def test_ineligible_identities_are_reported_not_hidden(self):
        records = make_records(
            {
                "multi1": {"multi1_a": 2, "multi1_b": 2},
                "multi2": {"multi2_a": 2, "multi2_b": 2},
                "lonely1": {"lonely1_a": 2},
                "lonely2": {"lonely2_a": 2},
            }
        )
        split = open_set_split(records, unknown_fraction=0.25, seed=0)
        assert split.ineligible_identities == frozenset({"lonely1", "lonely2"})

    def test_raises_when_nothing_can_be_enrolled_honestly(self):
        # Every cat seen exactly once: a recognition number is not available
        # from this data, and that must be an error rather than a silent zero.
        records = make_records({f"cat{i}": {f"cat{i}_a": 3} for i in range(10)})
        with pytest.raises(SplitError, match="single-session"):
            open_set_split(records, seed=0)

    def test_more_gallery_sessions_raises_the_eligibility_bar(self):
        records = make_records(
            {
                "two": {"two_a": 2, "two_b": 2},
                "three": {"three_a": 2, "three_b": 2, "three_c": 2},
                "four": {"four_a": 2, "four_b": 2, "four_c": 2, "four_d": 2},
            }
        )
        split = open_set_split(
            records, unknown_fraction=0.34, gallery_sessions_per_identity=2, seed=0
        )
        # "two" has exactly 2 sessions; enrolling 2 would leave nothing to query.
        assert "two" in split.ineligible_identities

    def test_deterministic_for_a_seed(self):
        first = open_set_split(population(), seed=11)
        second = open_set_split(population(), seed=11)
        assert first.known_identities == second.known_identities
        assert [r.image_id for r in first.gallery] == [
            r.image_id for r in second.gallery
        ]

    def test_different_seeds_give_different_partitions(self):
        partitions = {
            frozenset(
                open_set_split(population(n_identities=30), seed=s).unknown_identities
            )
            for s in range(5)
        }
        assert len(partitions) > 1

    def test_summary_counts_add_up(self):
        split = open_set_split(population(), seed=0)
        summary = split.summary()
        assert summary["gallery_images"] == len(split.gallery)
        assert summary["known_identities"] + summary["unknown_identities"] <= 10

    @pytest.mark.parametrize("fraction", [0.0, 1.0, -0.2, 2.0])
    def test_rejects_degenerate_fractions(self, fraction):
        with pytest.raises(SplitError):
            open_set_split(population(), unknown_fraction=fraction)

    def test_rejects_empty_input(self):
        with pytest.raises(SplitError, match="no records"):
            open_set_split([])


class TestLeakGuards:
    def test_session_leak_is_detected(self):
        shared = make_records({"a": {"s1": 2}})
        with pytest.raises(SplitError, match="both sides"):
            assert_no_session_leak(shared, shared)

    def test_identity_leak_is_detected(self):
        gallery = make_records({"a": {"s1": 2}})
        query = make_records({"a": {"s2": 2}})
        with pytest.raises(SplitError, match="marked unknown"):
            assert_no_identity_leak(gallery, query)

    def test_clean_split_passes_both_guards(self):
        gallery = make_records({"a": {"s1": 2}})
        query = make_records({"b": {"s2": 2}})
        assert_no_session_leak(gallery, query)
        assert_no_identity_leak(gallery, query)
