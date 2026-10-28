"""Open-set scoring: top-k, BAKS, BAUS, and the per-identity breakdown.

Three rules from CLAUDE.md are baked into the shapes here rather than left to
the caller to remember:

* **Knowns and unknowns are scored separately.** `OpenSetScores` has no field
  that blends them into one headline. `comparable_geometric_mean` exists only
  to line up against published AnimalCLEF numbers and is named to discourage
  quoting it as the result.

* **A cat's score is its best-matching template, not its average one.**
  `rank_identities` max-pools over each identity's templates. Averaging a
  frontal and a profile embedding produces a vector that matches neither.

* **Per-identity breakdown, always.** An aggregate hides that every error is a
  black cat.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

# Returned in place of an identity when nothing scored above threshold.
NEW_CAT = None


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    """One query image, already scored against the gallery.

    `ranked_identities` is identity-level and best-first — build it with
    `rank_identities` rather than passing raw template rankings, or a cat with
    many enrolled templates will appear repeatedly and inflate top-k.
    """

    true_identity: str
    is_known: bool
    ranked_identities: tuple[str, ...]
    top_score: float

    def predict(self, threshold):
        """The identity this query resolves to, or NEW_CAT if below threshold."""
        if not self.ranked_identities or self.top_score < threshold:
            return NEW_CAT
        return self.ranked_identities[0]


@dataclass(frozen=True)
class OpenSetScores:
    threshold: float
    baks: float
    baus: float
    auto_resolved_known: float
    top1_known: float
    top5_known: float
    n_known: int
    n_unknown: int
    per_identity: dict = field(default_factory=dict)

    @property
    def comparable_geometric_mean(self):
        """sqrt(BAKS * BAUS) — only for lining up against published baselines.

        AnimalCLEF reports this; we do not, because it hides which half is
        failing. Kept so our numbers can be compared to theirs at all.
        """
        if math.isnan(self.baks) or math.isnan(self.baus):
            return float("nan")
        return math.sqrt(max(self.baks, 0.0) * max(self.baus, 0.0))

    def report(self):
        """Multi-line human summary — the shape a run should print."""
        lines = [
            f"threshold            {self.threshold:.4f}",
            f"BAKS (knowns)        {self.baks:.4f}  over {self.n_known} queries",
            f"BAUS (unknowns)      {self.baus:.4f}  over {self.n_unknown} queries",
            f"auto-resolved @k=1   {self.auto_resolved_known:.4f}  <- headline",
            f"top-1 (ranking)      {self.top1_known:.4f}",
            f"top-5 (ranking)      {self.top5_known:.4f}",
        ]
        worst = worst_identities(self.per_identity, limit=5)
        if worst:
            lines.append("worst identities:")
            lines += [f"    {name:<24} {score:.3f}" for name, score in worst]
        return "\n".join(lines)


def rank_identities(template_identities, scores):
    """Collapse per-template scores into a best-first ranking of identities.

    Each enrolled cat contributes several template embeddings. Its score is the
    best match among them — the "templates, not centroids" rule — so this
    max-pools per identity and sorts descending.

    Ties break on identity name, so a ranking never depends on gallery order.
    """
    if len(template_identities) != len(scores):
        raise ValueError(
            f"got {len(template_identities)} identities and {len(scores)} scores"
        )

    best = {}
    for identity, score in zip(template_identities, scores, strict=True):
        score = float(score)
        if identity not in best or score > best[identity]:
            best[identity] = score

    ordered = sorted(best.items(), key=lambda pair: (-pair[1], pair[0]))
    return tuple(identity for identity, _ in ordered), tuple(
        score for _, score in ordered
    )


def top_k_accuracy(outcomes, k):
    """Fraction of *known* queries whose true identity is in the top k.

    Threshold-free: this measures ranking quality alone. A model can rank well
    and still be useless open-set if its scores are uncalibrated, which is why
    BAKS and BAUS are reported beside it rather than instead of it.
    """
    known = [outcome for outcome in outcomes if outcome.is_known]
    if not known:
        return float("nan")
    hits = sum(
        outcome.true_identity in outcome.ranked_identities[:k] for outcome in known
    )
    return hits / len(known)


def _macro_average(per_group_rates):
    if not per_group_rates:
        return float("nan")
    return sum(per_group_rates.values()) / len(per_group_rates)


def evaluate_at_threshold(outcomes, threshold):
    """Score every query at one acceptance threshold.

    BAKS is the macro-average over known identities of "predicted correctly and
    accepted". BAUS is the macro-average over unknown identities of "correctly
    rejected as a new cat". Both are macro rather than micro so that a single
    heavily-photographed cat cannot carry the score.
    """
    known_hits = defaultdict(list)
    unknown_hits = defaultdict(list)

    for outcome in outcomes:
        predicted = outcome.predict(threshold)
        if outcome.is_known:
            known_hits[outcome.true_identity].append(predicted == outcome.true_identity)
        else:
            unknown_hits[outcome.true_identity].append(predicted is NEW_CAT)

    known_rates = {
        identity: sum(hits) / len(hits) for identity, hits in known_hits.items()
    }
    unknown_rates = {
        identity: sum(hits) / len(hits) for identity, hits in unknown_hits.items()
    }

    n_known = sum(len(hits) for hits in known_hits.values())
    n_unknown = sum(len(hits) for hits in unknown_hits.values())

    # The headline: of the queries that *are* an enrolled cat, how many did the
    # system answer by itself and get right. Starts near zero, ends near one.
    auto_resolved = float("nan")
    if n_known:
        auto_resolved = sum(sum(hits) for hits in known_hits.values()) / n_known

    per_identity = {
        identity: {"rate": rate, "n": len(known_hits[identity]), "known": True}
        for identity, rate in known_rates.items()
    }
    per_identity.update(
        {
            identity: {"rate": rate, "n": len(unknown_hits[identity]), "known": False}
            for identity, rate in unknown_rates.items()
        }
    )

    return OpenSetScores(
        threshold=threshold,
        baks=_macro_average(known_rates),
        baus=_macro_average(unknown_rates),
        auto_resolved_known=auto_resolved,
        top1_known=top_k_accuracy(outcomes, 1),
        top5_known=top_k_accuracy(outcomes, 5),
        n_known=n_known,
        n_unknown=n_unknown,
        per_identity=per_identity,
    )


def candidate_thresholds(outcomes, steps=200):
    """A sweep range covering the observed score distribution."""
    scores = [outcome.top_score for outcome in outcomes if outcome.ranked_identities]
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if low == high:
        return [low]
    step = (high - low) / steps
    return [low + step * i for i in range(steps + 1)]


def threshold_sweep(outcomes, thresholds=None):
    thresholds = (
        candidate_thresholds(outcomes) if thresholds is None else list(thresholds)
    )
    return [evaluate_at_threshold(outcomes, threshold) for threshold in thresholds]


def choose_threshold(outcomes, min_baus=0.9):
    """Lowest threshold that still rejects new cats at `min_baus`.

    This is the "bias toward false 'new cat' verdicts" rule made mechanical: we
    fix a rejection floor first and take the best recognition available under
    it, rather than maximising a blended score. A wrongly-accepted cat silently
    corrupts the dataset and surfaces months later; a wrongly-rejected one costs
    an admin a single merge, and the labeling tool already has that action.

    Calibrate this on held-out *identities*. Calibrating on held-out photos of
    enrolled cats measures nothing about cat #51.
    """
    if not any(not outcome.is_known for outcome in outcomes):
        raise ValueError(
            "cannot calibrate a rejection threshold without unknown-identity "
            "queries — hold out whole identities, not photos"
        )

    acceptable = [
        scores
        for scores in threshold_sweep(outcomes)
        if not math.isnan(scores.baus) and scores.baus >= min_baus
    ]
    if not acceptable:
        raise ValueError(
            f"no threshold reaches BAUS >= {min_baus}; the embedding cannot "
            "separate new cats from enrolled ones at this quality"
        )
    return min(scores.threshold for scores in acceptable)


def worst_identities(per_identity, limit=5):
    """The identities carrying the failures — the per-cat breakdown's whole point."""
    rows = [
        (identity, stats["rate"])
        for identity, stats in per_identity.items()
        if stats["known"]
    ]
    rows.sort(key=lambda pair: (pair[1], pair[0]))
    return rows[:limit]
