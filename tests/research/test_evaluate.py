"""Harness tests.

`build_outcomes` is the join between embeddings and scoring, so it is tested
with hand-built vectors where the right answer is obvious. No torch needed:
the heavy imports in catreid.embed are inside the functions that use them,
precisely so this stays runnable in CI.
"""

import numpy as np
import pytest

from catreid.embed import cosine_similarity
from catreid.evaluate import build_outcomes
from catreid.records import PhotoRecord


def unit(*components):
    vector = np.array(components, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def record(identity, session="s", image_id=None):
    return PhotoRecord(
        image_id=image_id or f"{identity}-{session}",
        identity=identity,
        session=session,
        path=f"/{identity}.jpg",
    )


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        vectors = np.array([unit(1, 0, 0)])
        assert cosine_similarity(vectors, vectors)[0, 0] == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cosine_similarity(np.array([unit(1, 0)]), np.array([unit(0, 1)]))[
            0, 0
        ] == pytest.approx(0.0)

    def test_shape_is_queries_by_gallery(self):
        queries = np.array([unit(1, 0), unit(0, 1), unit(1, 1)])
        gallery = np.array([unit(1, 0), unit(0, 1)])
        assert cosine_similarity(queries, gallery).shape == (3, 2)

    def test_dimension_mismatch_is_an_error(self):
        with pytest.raises(ValueError, match="dimension mismatch"):
            cosine_similarity(np.zeros((1, 3)), np.zeros((1, 4)))


class TestBuildOutcomes:
    def test_nearest_template_wins(self):
        gallery_records = [record("alice"), record("bob")]
        gallery_vectors = np.array([unit(1, 0), unit(0, 1)])
        query_records = [record("alice", "q")]
        query_vectors = np.array([unit(0.97, 0.05)])

        outcomes = build_outcomes(
            gallery_records, gallery_vectors, query_records, query_vectors, {"alice"}
        )
        assert outcomes[0].ranked_identities[0] == "alice"
        assert outcomes[0].is_known is True

    def test_identity_appears_once_despite_many_templates(self):
        # alice enrolled with three templates, bob with one. The ranking is
        # over identities, so it must have exactly two entries.
        gallery_records = [
            record("alice", "s1"),
            record("alice", "s1", "a2"),
            record("alice", "s1", "a3"),
            record("bob", "s2"),
        ]
        gallery_vectors = np.array(
            [unit(1, 0), unit(0.9, 0.1), unit(0.8, 0.2), unit(0, 1)]
        )
        outcomes = build_outcomes(
            gallery_records,
            gallery_vectors,
            [record("alice", "q")],
            np.array([unit(1, 0)]),
            {"alice"},
        )
        assert outcomes[0].ranked_identities == ("alice", "bob")

    def test_a_cats_score_is_its_best_template_not_its_average(self):
        # alice has one perfect template and two poor ones. Averaging would
        # drop her below bob; max-pooling keeps her first.
        gallery_records = [
            record("alice", "s1"),
            record("alice", "s1", "a2"),
            record("alice", "s1", "a3"),
            record("bob", "s2"),
        ]
        gallery_vectors = np.array(
            [unit(1, 0), unit(0.1, 1), unit(0.1, 1), unit(0.6, 0.6)]
        )
        outcomes = build_outcomes(
            gallery_records,
            gallery_vectors,
            [record("alice", "q")],
            np.array([unit(1, 0)]),
            {"alice"},
        )
        assert outcomes[0].ranked_identities[0] == "alice"

    def test_unknown_identity_is_flagged(self):
        outcomes = build_outcomes(
            [record("alice")],
            np.array([unit(1, 0)]),
            [record("stranger", "q")],
            np.array([unit(0, 1)]),
            {"alice"},
        )
        assert outcomes[0].is_known is False
        assert outcomes[0].true_identity == "stranger"

    def test_top_score_matches_the_best_ranked_identity(self):
        outcomes = build_outcomes(
            [record("alice"), record("bob")],
            np.array([unit(1, 0), unit(0, 1)]),
            [record("alice", "q")],
            np.array([unit(1, 0)]),
            {"alice"},
        )
        assert outcomes[0].top_score == pytest.approx(1.0)

    def test_one_outcome_per_query(self):
        queries = [record("alice", "q1"), record("bob", "q2"), record("x", "q3")]
        outcomes = build_outcomes(
            [record("alice"), record("bob")],
            np.array([unit(1, 0), unit(0, 1)]),
            queries,
            np.array([unit(1, 0), unit(0, 1), unit(1, 1)]),
            {"alice", "bob"},
        )
        assert len(outcomes) == 3

    def test_length_disagreement_is_an_error(self):
        with pytest.raises(ValueError, match="gallery records and vectors"):
            build_outcomes(
                [record("a"), record("b")],
                np.array([unit(1, 0)]),
                [record("a", "q")],
                np.array([unit(1, 0)]),
                {"a"},
            )

    def test_query_length_disagreement_is_an_error(self):
        with pytest.raises(ValueError, match="query records and vectors"):
            build_outcomes(
                [record("a")],
                np.array([unit(1, 0)]),
                [record("a", "q"), record("b", "q")],
                np.array([unit(1, 0)]),
                {"a"},
            )


class TestSubsampling:
    def test_keeps_whole_sessions(self):
        from catreid.datasets import SessionPolicy, SourceDataset
        from catreid.evaluate import _subsample

        records = [
            PhotoRecord(f"i{s}_{n}", f"cat{s}", f"sess{s}", f"/{s}_{n}.jpg")
            for s in range(5)
            for n in range(4)
        ]
        source = SourceDataset("x", records, SessionPolicy.VIDEO)
        kept = _subsample(source, max_images=9, seed=0)

        # Every session present must be present in full — a random image
        # sample would reintroduce exactly the leak the splitter prevents.
        counts = {}
        for item in kept.records:
            counts[item.session] = counts.get(item.session, 0) + 1
        assert all(count == 4 for count in counts.values())

    def test_preserves_policy_and_name(self):
        from catreid.datasets import SessionPolicy, SourceDataset
        from catreid.evaluate import _subsample

        records = [PhotoRecord("i", "c", "s", "/i.jpg")]
        source = SourceDataset("x", records, SessionPolicy.VIDEO, notes="n")
        kept = _subsample(source, max_images=1, seed=0)
        assert kept.name == "x"
        assert kept.policy is SessionPolicy.VIDEO


class TestEmbedderContract:
    def test_variants_are_named_consistently(self):
        from catreid.embed import DEFAULT_VARIANT, VARIANTS

        assert DEFAULT_VARIANT in VARIANTS
        assert all(uri.startswith("hf-hub:BVRA/") for uri in VARIANTS.values())

    def test_unknown_variant_is_rejected_before_any_download(self):
        pytest.importorskip("timm")
        from catreid.embed import load_megadescriptor

        with pytest.raises(ValueError, match="unknown variant"):
            load_megadescriptor("XL-9999")

    def test_embedding_no_paths_is_an_error(self):
        pytest.importorskip("torch")
        from catreid.embed import embed_paths

        with pytest.raises(ValueError, match="no paths"):
            embed_paths(object(), [])
