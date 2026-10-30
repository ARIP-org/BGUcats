"""The decision policy. Each of the eight outcomes is reachable, and the two
silent-corruption outcomes are counted apart from everything else."""

import math

import pytest

from catreid.decision import ACCEPT, NEW, OUTCOMES, PICK, classify, decide, tally
from catreid.metrics import QueryOutcome


def q(truth, ranked, score, known=True):
    return QueryOutcome(truth, known, tuple(ranked), score)


class TestDecide:
    @pytest.mark.parametrize(
        ("score", "expected"), [(0.9, ACCEPT), (0.7, ACCEPT), (0.5, PICK), (0.1, NEW)]
    )
    def test_bands(self, score, expected):
        assert decide(score, accept_threshold=0.7, new_threshold=0.3) == expected

    def test_new_threshold_is_inclusive(self):
        assert decide(0.3, 0.7, 0.3) == PICK

    def test_equal_thresholds_remove_the_pick_band(self):
        assert decide(0.5, 0.5, 0.5) == ACCEPT
        assert decide(0.49, 0.5, 0.5) == NEW

    def test_inverted_thresholds_are_an_error(self):
        with pytest.raises(ValueError):
            decide(0.5, 0.3, 0.7)


class TestClassify:
    A, N = 0.7, 0.3

    def test_accepted_correct(self):
        assert (
            classify(q("mitzi", ["mitzi"], 0.9), self.A, self.N) == "accepted_correct"
        )

    def test_accepted_wrong_identity(self):
        out = classify(q("mitzi", ["boris", "mitzi"], 0.9), self.A, self.N)
        assert out == "accepted_wrong_identity"

    def test_accepted_stranger(self):
        out = classify(q("ghost", ["boris"], 0.9, known=False), self.A, self.N)
        assert out == "accepted_stranger"

    def test_pick_has_answer_within_k(self):
        out = classify(q("mitzi", ["a", "b", "mitzi", "c"], 0.5), self.A, self.N)
        assert out == "pick_has_answer"

    def test_pick_missing_answer_beyond_k(self):
        out = classify(q("mitzi", ["a", "b", "c", "mitzi"], 0.5), self.A, self.N)
        assert out == "pick_missing_answer"

    def test_pick_stranger(self):
        out = classify(q("ghost", ["a"], 0.5, known=False), self.A, self.N)
        assert out == "pick_stranger"

    def test_new_correct(self):
        out = classify(q("ghost", ["a"], 0.1, known=False), self.A, self.N)
        assert out == "new_correct"

    def test_new_but_known(self):
        out = classify(q("mitzi", ["mitzi"], 0.1), self.A, self.N)
        assert out == "new_but_known"


class TestTally:
    def population(self):
        return [
            q("mitzi", ["mitzi"], 0.9),  # accepted_correct
            q("mitzi", ["boris"], 0.9),  # accepted_wrong_identity
            q("ghost", ["boris"], 0.9, known=False),  # accepted_stranger
            q("boris", ["a", "boris"], 0.5),  # pick_has_answer
            q("boris", ["a", "b", "c"], 0.5),  # pick_missing_answer
            q("ghost", ["a"], 0.5, known=False),  # pick_stranger
            q("ghost", ["a"], 0.1, known=False),  # new_correct
            q("mitzi", ["mitzi"], 0.1),  # new_but_known
        ]

    def test_every_outcome_counted_once(self):
        counts = tally(self.population(), 0.7, 0.3)["counts"]
        assert set(counts) == set(OUTCOMES)
        assert all(v == 1 for v in counts.values())

    def test_rates(self):
        t = tally(self.population(), 0.7, 0.3)
        assert t["auto_resolved"] == pytest.approx(1 / 5)
        assert t["silent_errors"] == pytest.approx(2 / 8)
        assert t["pick_useful"] == pytest.approx(1 / 2)
        assert t["strangers_caught"] == pytest.approx(2 / 3)
        assert t["known_called_new"] == pytest.approx(1 / 5)

    def test_raising_accept_trades_silent_errors_for_human_work(self):
        pop = self.population()
        loose, strict = tally(pop, 0.7, 0.3), tally(pop, 0.95, 0.3)
        assert strict["silent_errors"] < loose["silent_errors"]
        assert strict["auto_resolved"] <= loose["auto_resolved"]

    def test_empty_pick_band_has_no_pick_rate(self):
        t = tally([q("a", ["a"], 0.9)], 0.5, 0.5)
        assert math.isnan(t["pick_useful"])
