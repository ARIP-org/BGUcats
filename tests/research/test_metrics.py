"""Scoring tests.

The cases that matter are the ones where a plausible-looking implementation
reports a flattering number: a cat with many templates inflating top-k, one
heavily-photographed cat carrying a macro average, and a threshold chosen to
maximise a blended score instead of holding a rejection floor.
"""

import math

import pytest

from catreid.metrics import (
    NEW_CAT,
    QueryOutcome,
    candidate_thresholds,
    choose_threshold,
    evaluate_at_threshold,
    rank_identities,
    top_k_accuracy,
    worst_identities,
)


def outcome(true_identity, ranked, top_score, is_known=True):
    return QueryOutcome(
        true_identity=true_identity,
        is_known=is_known,
        ranked_identities=tuple(ranked),
        top_score=top_score,
    )


class TestRankIdentities:
    def test_max_pools_over_a_cats_templates(self):
        # "mitzi" has three templates; her score is the best of them, not the mean.
        ranked, scores = rank_identities(
            ["mitzi", "mitzi", "mitzi", "boris"], [0.1, 0.9, 0.2, 0.5]
        )
        assert ranked == ("mitzi", "boris")
        assert scores == (0.9, 0.5)

    def test_an_identity_appears_once_however_many_templates(self):
        ranked, _ = rank_identities(["a"] * 50 + ["b"], [0.3] * 50 + [0.4])
        assert ranked == ("b", "a")

    def test_sorted_descending(self):
        ranked, scores = rank_identities(["a", "b", "c"], [0.2, 0.9, 0.5])
        assert ranked == ("b", "c", "a")
        assert list(scores) == sorted(scores, reverse=True)

    def test_ties_break_on_name_not_gallery_order(self):
        forward, _ = rank_identities(["a", "b"], [0.5, 0.5])
        backward, _ = rank_identities(["b", "a"], [0.5, 0.5])
        assert forward == backward == ("a", "b")

    def test_length_mismatch_is_an_error(self):
        with pytest.raises(ValueError, match="2 identities and 3 scores"):
            rank_identities(["a", "b"], [0.1, 0.2, 0.3])


class TestTopK:
    def test_counts_only_known_queries(self):
        outcomes = [
            outcome("a", ["a", "b"], 0.9),
            outcome("zzz", ["a", "b"], 0.2, is_known=False),
        ]
        assert top_k_accuracy(outcomes, 1) == 1.0

    def test_top5_is_looser_than_top1(self):
        outcomes = [outcome("e", ["a", "b", "c", "d", "e"], 0.5)]
        assert top_k_accuracy(outcomes, 1) == 0.0
        assert top_k_accuracy(outcomes, 5) == 1.0

    def test_nan_when_nothing_is_known(self):
        outcomes = [outcome("x", ["a"], 0.1, is_known=False)]
        assert math.isnan(top_k_accuracy(outcomes, 1))


class TestPredict:
    def test_below_threshold_is_a_new_cat(self):
        assert outcome("a", ["a"], 0.4).predict(0.5) is NEW_CAT

    def test_at_threshold_is_accepted(self):
        assert outcome("a", ["a"], 0.5).predict(0.5) == "a"

    def test_empty_ranking_is_a_new_cat(self):
        assert outcome("a", [], 1.0).predict(0.0) is NEW_CAT


class TestOpenSetScores:
    def test_perfect_system(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("b", ["b"], 0.9),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.baks == 1.0
        assert scores.baus == 1.0
        assert scores.auto_resolved_known == 1.0

    def test_accepting_everything_destroys_baus(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("ghost", ["a"], 0.8, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.0)
        assert scores.baks == 1.0
        assert scores.baus == 0.0

    def test_rejecting_everything_destroys_baks(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("ghost", ["a"], 0.8, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 1.0)
        assert scores.baks == 0.0
        assert scores.baus == 1.0

    def test_macro_average_stops_one_cat_carrying_the_score(self):
        # "popular" is photographed 10x and always right; "rare" once and wrong.
        # A micro-average would read 0.91; the macro-average must read 0.50.
        outcomes = [outcome("popular", ["popular"], 0.9) for _ in range(10)]
        outcomes.append(outcome("rare", ["wrong"], 0.9))
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.baks == pytest.approx(0.5)

    def test_auto_resolved_is_micro_over_known_queries(self):
        outcomes = [outcome("popular", ["popular"], 0.9) for _ in range(10)]
        outcomes.append(outcome("rare", ["wrong"], 0.9))
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.auto_resolved_known == pytest.approx(10 / 11)

    def test_a_correct_rank_below_threshold_is_not_a_hit(self):
        outcomes = [
            outcome("a", ["a"], 0.3),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.top1_known == 1.0  # ranking was right
        assert scores.baks == 0.0  # but it was rejected

    def test_counts_are_reported(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("b", ["b"], 0.9),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.n_known == 2
        assert scores.n_unknown == 1

    def test_geometric_mean_is_available_but_separate(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.comparable_geometric_mean == pytest.approx(1.0)
        # and it is not one of the dataclass fields
        assert "comparable_geometric_mean" not in scores.__dataclass_fields__

    def test_report_is_printable(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        text = evaluate_at_threshold(outcomes, 0.5).report()
        assert "BAKS" in text and "BAUS" in text and "headline" in text


class TestThresholdChoice:
    def test_holds_the_rejection_floor(self):
        outcomes = [
            outcome("a", ["a"], 0.80),
            outcome("b", ["b"], 0.75),
            outcome("ghost1", ["a"], 0.60, is_known=False),
            outcome("ghost2", ["b"], 0.55, is_known=False),
        ]
        threshold = choose_threshold(outcomes, min_baus=1.0)
        scores = evaluate_at_threshold(outcomes, threshold)
        assert scores.baus == 1.0

    def test_takes_the_lowest_threshold_meeting_the_floor(self):
        # Lower threshold = more recognition, so among thresholds that hold the
        # floor we want the most permissive one.
        outcomes = [
            outcome("a", ["a"], 0.90),
            outcome("ghost", ["a"], 0.30, is_known=False),
        ]
        threshold = choose_threshold(outcomes, min_baus=1.0)
        assert 0.30 < threshold <= 0.90

    def test_refuses_without_unknown_queries(self):
        outcomes = [outcome("a", ["a"], 0.9)]
        with pytest.raises(ValueError, match="whole identities"):
            choose_threshold(outcomes)

    def test_reports_when_the_embedding_cannot_separate(self):
        # Unknowns score higher than knowns: no threshold can reject them
        # without rejecting everything, and BAUS=1.0 is unreachable while any
        # known is accepted.
        outcomes = [
            outcome("a", ["a"], 0.10),
            outcome("ghost", ["a"], 0.99, is_known=False),
        ]
        with pytest.raises(ValueError, match="cannot separate"):
            choose_threshold(outcomes, min_baus=1.01)

    def test_sweep_covers_the_observed_range(self):
        outcomes = [
            outcome("a", ["a"], 0.2),
            outcome("b", ["b"], 0.8),
        ]
        thresholds = candidate_thresholds(outcomes, steps=10)
        assert thresholds[0] == pytest.approx(0.2)
        assert thresholds[-1] == pytest.approx(0.8)


class TestPerIdentityBreakdown:
    def test_surfaces_the_failing_cats(self):
        outcomes = [
            outcome("tabby", ["tabby"], 0.9),
            outcome("blackcat", ["tabby"], 0.9),
            outcome("calico", ["calico"], 0.9),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        worst = worst_identities(scores.per_identity, limit=1)
        assert worst == [("blackcat", 0.0)]

    def test_breakdown_marks_known_and_unknown_rows(self):
        outcomes = [
            outcome("a", ["a"], 0.9),
            outcome("ghost", ["a"], 0.1, is_known=False),
        ]
        scores = evaluate_at_threshold(outcomes, 0.5)
        assert scores.per_identity["a"]["known"] is True
        assert scores.per_identity["ghost"]["known"] is False
