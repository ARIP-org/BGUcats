"""Rerank and evidence-replay tests — all pure, no model weights.

The behaviour that matters: local evidence can promote a candidate the
embedding ranked second, but only countable (on-animal) matches can do it, and
fused scores stay on one scale so a single threshold remains meaningful.
"""

import numpy as np
import pytest

from catreid.experiment import Evidence, outcomes_from_evidence, score_variant
from catreid.records import PhotoRecord
from catreid.rerank import (
    RerankConfig,
    fuse,
    match_score,
    rerank_ranking,
    top_templates,
)


class TestMatchScore:
    def test_zero_matches_is_zero(self):
        assert match_score(0, 10) == 0.0

    def test_saturation_is_the_half_point(self):
        assert match_score(10, 10) == pytest.approx(0.5)

    def test_bounded_below_one(self):
        assert match_score(10_000, 10) < 1.0

    def test_diminishing_returns(self):
        low = match_score(10, 10) - match_score(0, 10)
        high = match_score(110, 10) - match_score(100, 10)
        assert low > high

    def test_negative_counts_clamp(self):
        assert match_score(-5, 10) == 0.0

    def test_rejects_nonpositive_saturation(self):
        with pytest.raises(ValueError):
            match_score(1, 0)


class TestFuse:
    def test_weight_zero_is_pure_cosine(self):
        assert fuse(0.7, 0.9, 0.0) == pytest.approx(0.7)

    def test_weight_one_is_pure_local(self):
        assert fuse(0.7, 0.9, 1.0) == pytest.approx(0.9)

    def test_blend(self):
        assert fuse(0.6, 0.2, 0.5) == pytest.approx(0.4)

    @pytest.mark.parametrize("weight", [-0.1, 1.5])
    def test_rejects_out_of_range_weight(self, weight):
        with pytest.raises(ValueError):
            fuse(0.5, 0.5, weight)


class TestTopTemplates:
    def test_best_first(self):
        assert top_templates([0.1, 0.9, 0.5], 2) == [1, 2]

    def test_ties_break_on_index(self):
        assert top_templates([0.5, 0.5, 0.5], 3) == [0, 1, 2]

    def test_n_larger_than_gallery(self):
        assert top_templates([0.2, 0.1], 50) == [0, 1]


class TestRerankRanking:
    config = RerankConfig(top_n=2, weight=0.5, saturation=10)

    def test_matches_promote_the_runner_up(self):
        # Embedding prefers "boris"; strong local evidence for "mitzi" wins.
        ranked, _, _ = rerank_ranking(
            [0.60, 0.55], ["boris", "mitzi"], {0: 0, 1: 40}, self.config
        )
        assert ranked[0] == "mitzi"

    def test_no_evidence_preserves_the_embedding_order(self):
        ranked, _, _ = rerank_ranking([0.60, 0.55], ["boris", "mitzi"], {}, self.config)
        assert ranked == ("boris", "mitzi")

    def test_unreranked_templates_stay_on_the_same_scale(self):
        # Template 2 was not shortlisted; it is fused with zero evidence rather
        # than left on raw cosine, which would put it on a different scale.
        _, _, fused = rerank_ranking(
            [0.6, 0.5, 0.4], ["a", "b", "c"], {0: 0, 1: 0}, self.config
        )
        assert fused[2] == pytest.approx(0.5 * 0.4)

    def test_identity_score_is_its_best_template(self):
        ranked, scores, _ = rerank_ranking(
            [0.5, 0.5, 0.5], ["a", "a", "b"], {0: 0, 1: 30, 2: 5}, self.config
        )
        assert ranked[0] == "a"
        assert scores[0] == pytest.approx(fuse(0.5, match_score(30, 10), 0.5))

    def test_length_mismatch_is_an_error(self):
        with pytest.raises(ValueError):
            rerank_ranking([0.1, 0.2], ["a"], {}, self.config)

    def test_describe_names_the_guard(self):
        assert "animal-only" in RerankConfig().describe()
        assert "all matches" in RerankConfig(foreground_only=False).describe()


def record(identity, session):
    return PhotoRecord(f"{identity}-{session}", identity, session, f"/{identity}.jpg")


class TestEvidenceReplay:
    """Background matches are the trap: same enclosure, different animal."""

    def build(self):
        gallery = [record("boris", "g1"), record("mitzi", "g2")]
        queries = [record("mitzi", "q1")]
        # Embedding slightly prefers the wrong animal. Unguarded, boris has
        # many matches — all of them on shared background. Guarded, only
        # mitzi's on-animal matches count.
        evidence = Evidence(
            sims=np.array([[0.60, 0.55]], dtype=np.float32),
            top=np.array([[0, 1]], dtype=np.int32),
            total=np.array([[60, 12]], dtype=np.int32),
            animal=np.array([[0, 12]], dtype=np.int32),
        )
        return gallery, queries, evidence

    def test_embedding_only_follows_cosine(self):
        gallery, queries, evidence = self.build()
        out = outcomes_from_evidence(
            evidence, [r.identity for r in gallery], queries, {"boris", "mitzi"}
        )
        assert out[0].ranked_identities[0] == "boris"

    def test_unguarded_rerank_is_fooled_by_background(self):
        gallery, queries, evidence = self.build()
        out = outcomes_from_evidence(
            evidence,
            [r.identity for r in gallery],
            queries,
            {"boris", "mitzi"},
            RerankConfig(top_n=2, foreground_only=False),
        )
        assert out[0].ranked_identities[0] == "boris"

    def test_guarded_rerank_recovers_the_right_animal(self):
        gallery, queries, evidence = self.build()
        out = outcomes_from_evidence(
            evidence,
            [r.identity for r in gallery],
            queries,
            {"boris", "mitzi"},
            RerankConfig(top_n=2, foreground_only=True),
        )
        assert out[0].ranked_identities[0] == "mitzi"

    def test_top_n_limits_which_templates_get_evidence(self):
        gallery, queries, evidence = self.build()
        out = outcomes_from_evidence(
            evidence,
            [r.identity for r in gallery],
            queries,
            {"boris", "mitzi"},
            RerankConfig(top_n=1, foreground_only=True),
        )
        # Only boris (rank 1) was shortlisted, and it has no animal matches.
        assert out[0].ranked_identities[0] == "boris"

    def test_evidence_round_trips(self, tmp_path):
        _, _, evidence = self.build()
        evidence.save(tmp_path / "e.npz")
        loaded = Evidence.load(tmp_path / "e.npz")
        assert (loaded.animal == evidence.animal).all()
        assert loaded.sims.dtype == np.float32

    def test_score_variant_reports_both_halves(self):
        gallery, queries, evidence = self.build()
        queries = queries + [record("ghost", "q2")]
        evidence = Evidence(
            sims=np.array([[0.6, 0.55], [0.1, 0.1]], dtype=np.float32),
            top=np.array([[0, 1], [0, 1]], dtype=np.int32),
            total=np.zeros((2, 2), dtype=np.int32),
            animal=np.zeros((2, 2), dtype=np.int32),
        )
        outcomes = outcomes_from_evidence(
            evidence, [r.identity for r in gallery], queries, {"boris", "mitzi"}
        )
        result = score_variant("x", outcomes, min_baus=1.0)
        assert result["baus"] == 1.0
        assert "baks" in result and "per_identity" in result
