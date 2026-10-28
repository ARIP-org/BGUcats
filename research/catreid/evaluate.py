"""The open-set evaluation harness.

Ties the pieces together in the order the addendum specifies: load a source,
decide what a session means for it, split by session and by identity, embed,
score every query against the enrolled templates, calibrate a threshold on the
held-out identities, and report knowns and unknowns separately with a per-cat
breakdown.

Run it:

    python -m catreid.evaluate --dataset PolarBearVidID \\
        --root research/data/PolarBearVidID --variant T-224
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from catreid.datasets import (
    cap_sessions_per_identity,
    from_wildlife_dataset,
    thin_frames_per_session,
)
from catreid.embed import DEFAULT_VARIANT, cosine_similarity
from catreid.metrics import QueryOutcome, evaluate_at_threshold, rank_identities
from catreid.splits import open_set_split

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    dataset: str
    backbone: str
    session_policy: str
    gallery_sessions_per_identity: int
    split_summary: dict
    source_summary: dict
    threshold: float
    baks: float
    baus: float
    auto_resolved_known: float
    top1_known: float
    top5_known: float
    n_known: int
    n_unknown: int
    comparable_geometric_mean: float
    per_identity: dict
    seconds: float

    def report(self):
        lines = [
            f"dataset              {self.dataset}",
            f"backbone             {self.backbone}",
            f"session policy       {self.session_policy}",
            f"enrolled sessions    {self.gallery_sessions_per_identity} per identity",
            "",
            f"enrolled identities  {self.split_summary['known_identities']}",
            f"unseen identities    {self.split_summary['unknown_identities']}",
            (
                f"ineligible           {self.split_summary['ineligible_identities']}"
                "  (too few sessions to enrol and query honestly)"
            ),
            f"gallery images       {self.split_summary['gallery_images']}",
            "",
            f"threshold            {self.threshold:.4f}",
            f"BAKS (knowns)        {self.baks:.4f}  over {self.n_known} queries",
            f"BAUS (unknowns)      {self.baus:.4f}  over {self.n_unknown} queries",
            f"auto-resolved @k=1   {self.auto_resolved_known:.4f}   <- headline",
            "",
            f"top-1 (ranking)      {self.top1_known:.4f}",
            f"top-5 (ranking)      {self.top5_known:.4f}",
            (
                f"geometric mean       {self.comparable_geometric_mean:.4f}"
                "  (for comparison with published baselines only)"
            ),
        ]
        known_rows = sorted(
            (
                (name, stats["rate"], stats["n"])
                for name, stats in self.per_identity.items()
                if stats["known"]
            ),
            key=lambda row: (row[1], row[0]),
        )
        if known_rows:
            lines += ["", "per-identity (worst first):"]
            lines += [
                f"    {name:<28} {rate:.3f}  n={count}"
                for name, rate, count in known_rows[:12]
            ]
        return "\n".join(lines)


def build_outcomes(
    gallery_records, gallery_vectors, query_records, query_vectors, known_identities
):
    """Score each query against every enrolled template.

    The ranking is collapsed to identities by `rank_identities`, which takes
    each cat's best-matching template rather than an average of them.
    """
    if len(gallery_records) != len(gallery_vectors):
        raise ValueError("gallery records and vectors disagree in length")
    if len(query_records) != len(query_vectors):
        raise ValueError("query records and vectors disagree in length")

    gallery_identities = [record.identity for record in gallery_records]
    similarities = cosine_similarity(query_vectors, gallery_vectors)

    outcomes = []
    for record, row in zip(query_records, similarities, strict=True):
        ranked, scores = rank_identities(gallery_identities, row)
        outcomes.append(
            QueryOutcome(
                true_identity=record.identity,
                is_known=record.identity in known_identities,
                ranked_identities=ranked,
                top_score=scores[0] if scores else float("-inf"),
            )
        )
    return outcomes


def run(
    source,
    embedder,
    unknown_fraction=0.3,
    seed=0,
    min_baus=0.9,
    cache_dir=None,
    gallery_sessions_per_identity=1,
):
    """Full open-set evaluation of one source with one backbone."""
    from catreid.embed import embed_records
    from catreid.metrics import choose_threshold

    started = time.time()

    # for_evaluation() refuses a source with no real session information,
    # rather than letting it produce a flattering number.
    records = source.for_evaluation()
    split = open_set_split(
        records,
        unknown_fraction=unknown_fraction,
        gallery_sessions_per_identity=gallery_sessions_per_identity,
        seed=seed,
    )
    logger.info("split: %s", split.summary())

    gallery_vectors = embed_records(embedder, split.gallery, cache_dir=cache_dir)
    queries = list(split.query_known) + list(split.query_unknown)
    query_vectors = embed_records(embedder, queries, cache_dir=cache_dir)

    outcomes = build_outcomes(
        split.gallery, gallery_vectors, queries, query_vectors, split.known_identities
    )

    threshold = choose_threshold(outcomes, min_baus=min_baus)
    scores = evaluate_at_threshold(outcomes, threshold)

    return RunResult(
        dataset=source.name,
        backbone=embedder.name,
        session_policy=source.policy.value,
        gallery_sessions_per_identity=gallery_sessions_per_identity,
        split_summary=split.summary(),
        source_summary=source.summary(),
        threshold=scores.threshold,
        baks=scores.baks,
        baus=scores.baus,
        auto_resolved_known=scores.auto_resolved_known,
        top1_known=scores.top1_known,
        top5_known=scores.top5_known,
        n_known=scores.n_known,
        n_unknown=scores.n_unknown,
        comparable_geometric_mean=scores.comparable_geometric_mean,
        per_identity=scores.per_identity,
        seconds=time.time() - started,
    )


def load_source(dataset_name, root):
    from wildlife_datasets import datasets as wd

    if not hasattr(wd, dataset_name):
        raise SystemExit(f"unknown dataset {dataset_name!r}")
    dataset = getattr(wd, dataset_name)(root)
    return from_wildlife_dataset(dataset, name=dataset_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--variant", default=DEFAULT_VARIANT)
    parser.add_argument("--unknown-fraction", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--min-baus", type=float, default=0.9)
    parser.add_argument(
        "--gallery-sessions",
        type=int,
        default=1,
        help="sessions enrolled per identity — the enrollment-richness axis",
    )
    parser.add_argument(
        "--sessions-per-identity",
        type=int,
        default=None,
        help="keep at most N whole sessions per identity",
    )
    parser.add_argument(
        "--frames-per-session",
        type=int,
        default=None,
        help="keep at most N evenly-spaced frames from each session",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="subsample for a quick smoke run; never for a quoted number",
    )
    parser.add_argument("--cache-dir", default="research/.cache/embeddings")
    parser.add_argument("--out", default="research/runs")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    from catreid.embed import load_megadescriptor

    source = load_source(args.dataset, args.root)
    logger.info("source: %s", source.summary())

    # Capping and thinning both respect session boundaries, so neither can
    # move a frame across a later split. --max-images is the blunt one.
    if args.sessions_per_identity:
        source = cap_sessions_per_identity(
            source, args.sessions_per_identity, seed=args.seed
        )
        logger.info("capped sessions: %s", source.summary())
    if args.frames_per_session:
        source = thin_frames_per_session(source, args.frames_per_session)
        logger.info("thinned frames: %s", source.summary())

    if args.max_images:
        source = _subsample(source, args.max_images, args.seed)
        logger.warning(
            "subsampled to %d images — a smoke-test number, not a result",
            len(source.records),
        )

    embedder = load_megadescriptor(args.variant)
    result = run(
        source,
        embedder,
        unknown_fraction=args.unknown_fraction,
        seed=args.seed,
        min_baus=args.min_baus,
        cache_dir=args.cache_dir,
        gallery_sessions_per_identity=args.gallery_sessions,
    )

    print()
    print(result.report())

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{args.dataset}-{args.variant}-{stamp}.json"
    out_path.write_text(json.dumps(asdict(result), indent=2, default=str))
    print(f"\nwritten to {out_path}")
    return 0


def _subsample(source, max_images, seed):
    """Keep whole sessions until the budget is spent.

    Sessions, never images: taking a random sample of images would split
    captures across the gallery/query boundary and quietly reintroduce the
    leak the splitter exists to prevent.
    """
    import random

    from catreid.datasets import SourceDataset
    from catreid.records import records_by_session

    grouped = records_by_session(source.records)
    session_ids = sorted(grouped)
    random.Random(seed).shuffle(session_ids)

    kept, total = [], 0
    for session_id in session_ids:
        if total >= max_images:
            break
        kept.extend(grouped[session_id])
        total += len(grouped[session_id])

    return SourceDataset(
        name=source.name, records=kept, policy=source.policy, notes=source.notes
    )


if __name__ == "__main__":
    sys.exit(main())
