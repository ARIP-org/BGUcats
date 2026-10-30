"""Paired experiments on one split: baseline, background-masked, reranked.

Every variant is scored on the *same* split and the *same* queries, so the
deltas between them are paired comparisons rather than differences between
runs that happened to sample different data.

The expensive step — local-feature matching — runs once. What it produces is
stored as raw evidence: for each query, its top-N templates by cosine, and for
each of those the match count both with and without the foreground guard.
Any fusion setting is then a few milliseconds of numpy over that evidence,
which is what makes it honest to sweep settings at all, and what the demo
page replays.

    PYTHONPATH=research python -m catreid.experiment
"""

import argparse
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from catreid.embed import cosine_similarity
from catreid.metrics import (
    QueryOutcome,
    choose_threshold,
    evaluate_at_threshold,
    rank_identities,
)
from catreid.rerank import RerankConfig, rerank_ranking

logger = logging.getLogger(__name__)


@dataclass
class Evidence:
    """Everything the scoring variants need, computed once per split.

    sims     (Q, G) cosine similarity of every query to every template
    top      (Q, N) indices of each query's N most similar templates
    total    (Q, N) LightGlue matches per shortlisted pair, unguarded
    animal   (Q, N) of those, matches with both endpoints on the animal
    """

    sims: np.ndarray
    top: np.ndarray
    total: np.ndarray
    animal: np.ndarray

    def save(self, path):
        np.savez_compressed(
            path, sims=self.sims, top=self.top, total=self.total, animal=self.animal
        )

    @classmethod
    def load(cls, path):
        data = np.load(path)
        return cls(data["sims"], data["top"], data["total"], data["animal"])


def outcomes_from_evidence(
    evidence, gallery_identities, query_records, known, config=None
):
    """QueryOutcomes for one variant. config=None means embedding only.

    Pure numpy over stored evidence — no model is touched here.
    """
    outcomes = []
    for q, record in enumerate(query_records):
        row = evidence.sims[q]
        if config is None:
            ranked, scores = rank_identities(gallery_identities, row)
        else:
            counts_source = (
                evidence.animal if config.foreground_only else evidence.total
            )
            limit = min(config.top_n, evidence.top.shape[1])
            counts = {
                int(evidence.top[q, j]): int(counts_source[q, j]) for j in range(limit)
            }
            ranked, scores, _ = rerank_ranking(row, gallery_identities, counts, config)
        outcomes.append(
            QueryOutcome(
                true_identity=record.identity,
                is_known=record.identity in known,
                ranked_identities=ranked,
                top_score=scores[0],
            )
        )
    return outcomes


def score_variant(name, outcomes, min_baus):
    threshold = choose_threshold(outcomes, min_baus=min_baus)
    scores = evaluate_at_threshold(outcomes, threshold)
    return {
        "variant": name,
        "threshold": scores.threshold,
        "baks": scores.baks,
        "baus": scores.baus,
        "auto_resolved_known": scores.auto_resolved_known,
        "top1_known": scores.top1_known,
        "top5_known": scores.top5_known,
        "per_identity": {
            k: v["rate"] for k, v in scores.per_identity.items() if v["known"]
        },
    }


def collect_evidence(
    gallery,
    queries,
    gallery_vectors,
    query_vectors,
    matcher,
    masks,
    top_n,
    progress_every=100,
):
    sims = cosine_similarity(query_vectors, gallery_vectors).astype(np.float32)
    n = min(top_n, len(gallery))
    top = np.argsort(-sims, axis=1, kind="stable")[:, :n].astype(np.int32)
    total = np.zeros_like(top)
    animal = np.zeros_like(top)

    started = time.time()
    for q, query in enumerate(queries):
        qf = matcher.features(query.path, masks.get(query.path))
        for j, g in enumerate(top[q]):
            template = gallery[int(g)]
            gf = matcher.features(template.path, masks.get(template.path))
            all_matches, on_animal, _ = matcher.count(qf, gf, foreground_only=True)
            total[q, j] = all_matches
            animal[q, j] = on_animal
        if progress_every and (q + 1) % progress_every == 0:
            rate = (time.time() - started) / (q + 1)
            logger.info(
                "matched %d/%d queries (%.1fs/query, ~%.0f min left)",
                q + 1,
                len(queries),
                rate,
                rate * (len(queries) - q - 1) / 60,
            )
    return Evidence(sims=sims, top=top, total=total, animal=animal)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="PolarBearVidID")
    parser.add_argument("--root", default="research/data/PolarBearVidID")
    parser.add_argument("--variant", default="T-224")
    parser.add_argument("--sessions-per-identity", type=int, default=10)
    parser.add_argument("--frames-per-session", type=int, default=10)
    parser.add_argument("--gallery-sessions", type=int, default=3)
    parser.add_argument("--unknown-fraction", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--min-baus", type=float, default=0.9)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--cache-dir", default="research/.cache")
    parser.add_argument("--out", default="research/runs")
    parser.add_argument(
        "--demo-out",
        default=None,
        help="also write an interactive demo page to this path",
    )
    parser.add_argument("--demo-samples", type=int, default=40)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    import torch

    from catreid.datasets import cap_sessions_per_identity, thin_frames_per_session
    from catreid.embed import embed_records, load_megadescriptor
    from catreid.evaluate import load_source
    from catreid.foreground import coverage, load_segmenter, masks_for_paths
    from catreid.rerank import LocalMatcher
    from catreid.splits import open_set_split

    torch.set_num_threads(6)
    cache = Path(args.cache_dir)

    source = load_source(args.dataset, args.root)
    source = cap_sessions_per_identity(
        source, args.sessions_per_identity, seed=args.seed
    )
    source = thin_frames_per_session(source, args.frames_per_session)
    split = open_set_split(
        source.for_evaluation(),
        unknown_fraction=args.unknown_fraction,
        gallery_sessions_per_identity=args.gallery_sessions,
        seed=args.seed,
    )
    gallery = list(split.gallery)
    queries = list(split.query_known) + list(split.query_unknown)
    identities = [r.identity for r in gallery]
    known = split.known_identities
    logger.info("split: %s", split.summary())

    all_paths = [r.path for r in gallery + queries]
    masks = masks_for_paths(load_segmenter(), all_paths, cache / "masks")
    found = [m for m in masks.values() if m is not None]
    mask_stats = {
        "images": len(all_paths),
        "animal_found": len(found),
        "mean_coverage": float(np.mean([coverage(m) for m in found])) if found else 0.0,
    }
    logger.info("masks: %s", mask_stats)

    embedder = load_megadescriptor(args.variant)
    emb_dir = cache / "embeddings"
    g_plain = embed_records(embedder, gallery, cache_dir=emb_dir)
    q_plain = embed_records(embedder, queries, cache_dir=emb_dir)
    g_masked = embed_records(embedder, gallery, cache_dir=emb_dir, masks=masks)
    q_masked = embed_records(embedder, queries, cache_dir=emb_dir, masks=masks)

    tag = (
        f"{args.dataset}-{args.variant}-s{args.sessions_per_identity}"
        f"-f{args.frames_per_session}-g{args.gallery_sessions}-seed{args.seed}"
        f"-top{args.top_n}"
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"evidence-{tag}.npz"

    matcher = LocalMatcher()
    if evidence_path.exists():
        logger.info("reusing evidence %s", evidence_path.name)
        evidence = Evidence.load(evidence_path)
    else:
        evidence = collect_evidence(
            gallery, queries, g_plain, q_plain, matcher, masks, args.top_n
        )
        evidence.save(evidence_path)

    masked_sims = cosine_similarity(q_masked, g_masked)
    masked_evidence = Evidence(
        masked_sims, evidence.top, evidence.total, evidence.animal
    )

    variants = [
        ("embedding only", evidence, None),
        ("embedding, background masked", masked_evidence, None),
        (
            "rerank, all matches (unguarded)",
            evidence,
            RerankConfig(top_n=args.top_n, foreground_only=False),
        ),
        (
            "rerank, animal-only matches",
            evidence,
            RerankConfig(top_n=args.top_n, foreground_only=True),
        ),
    ]
    results = [
        score_variant(
            name,
            outcomes_from_evidence(ev, identities, queries, known, config),
            args.min_baus,
        )
        for name, ev, config in variants
    ]

    # Where do the matches land? Same-identity vs different-identity pairs,
    # guarded vs unguarded — the direct measurement of the background trap.
    same = np.array(
        [
            [identities[int(g)] == q.identity for g in evidence.top[i]]
            for i, q in enumerate(queries)
        ]
    )
    match_stats = {
        "same_identity_mean_all": float(evidence.total[same].mean()),
        "diff_identity_mean_all": float(evidence.total[~same].mean()),
        "same_identity_mean_animal": float(evidence.animal[same].mean()),
        "diff_identity_mean_animal": float(evidence.animal[~same].mean()),
        "share_of_matches_on_animal": float(
            evidence.animal.sum() / max(evidence.total.sum(), 1)
        ),
    }

    summary = {
        "tag": tag,
        "split": split.summary(),
        "masks": mask_stats,
        "matches": match_stats,
        "results": results,
    }
    (out_dir / f"experiment-{tag}.json").write_text(json.dumps(summary, indent=2))

    print()
    print(f"{'variant':38} {'top-1':>7} {'top-5':>7} {'BAKS':>7} {'BAUS':>7}")
    for r in results:
        print(
            f"{r['variant']:38} {r['top1_known']:7.3f} {r['top5_known']:7.3f} "
            f"{r['baks']:7.3f} {r['baus']:7.3f}"
        )
    print()
    print("masks:", mask_stats)
    print("matches:", {k: round(v, 3) for k, v in match_stats.items()})

    if args.demo_out:
        from catreid.demo import export

        best = max(results, key=lambda r: r["auto_resolved_known"])
        counts = split.summary()
        split_line = (
            f"{args.dataset}: {counts['known_identities']} enrolled and "
            f"{counts['unknown_identities']} never-seen animals, {len(queries)} test "
            "photos, split by video so no clip appears on both sides."
        )
        models_line = (
            f"MegaDescriptor-{args.variant} for the overall look; ALIKED + LightGlue "
            "for matching details; Mask R-CNN to find the animal."
        )
        source_line = (
            "Photos: PolarBearVidID, Zuerl et al. 2023, CC BY 4.0. A public dataset "
            "used to test the machinery, not a measurement of how well this works on "
            "campus cats."
        )
        export(
            args.demo_out,
            gallery=gallery,
            queries=queries,
            known=known,
            evidence=evidence,
            masks=masks,
            matcher=matcher,
            config=RerankConfig(top_n=args.top_n, foreground_only=True),
            min_baus=args.min_baus,
            n_samples=args.demo_samples,
            seed=args.seed,
            meta={
                "dataset": args.dataset,
                "default_mode": (
                    "rerank" if best["variant"].startswith("rerank") else "embedding"
                ),
                "footer": [split_line, models_line, source_line],
            },
        )
    return summary


if __name__ == "__main__":
    main()
