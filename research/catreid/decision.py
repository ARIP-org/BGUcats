"""The decision policy — the third of the three dials in the addendum.

Two thresholds turn a ranked list into what the app actually does:

    top score >= accept      ACCEPT   "This is Mitzi."
    new <= top score < accept  PICK   "Is it one of these three?" + "none of these"
    top score < new           NEW     "Looks like a cat we haven't met."

Every query then lands in exactly one of eight outcomes, and they are not
equally bad. The policy is only honest if each one is counted separately:

    accepted_correct          the goal — answered alone, and right
    accepted_wrong_identity   silent corruption: a photo filed under the wrong cat
    accepted_stranger         silent corruption: a new cat filed under an old one
    pick_has_answer           a human confirms it in one tap — and labels a photo
    pick_missing_answer       a human sees the wrong three and has to search
    pick_stranger             a human taps "none of these" — fine
    new_correct               a new cat, correctly offered enrollment
    new_but_known             an enrolled cat called new — costs one merge later

The two "silent corruption" rows are the ones the threshold is biased against
(CLAUDE.md: a false accept surfaces months later; a false "new cat" costs one
merge). This module is mirrored line for line by the demo page's JavaScript.
"""

ACCEPT, PICK, NEW = "accept", "pick", "new"
PICK_K = 3

OUTCOMES = (
    "accepted_correct",
    "accepted_wrong_identity",
    "accepted_stranger",
    "pick_has_answer",
    "pick_missing_answer",
    "pick_stranger",
    "new_correct",
    "new_but_known",
)


def decide(top_score, accept_threshold, new_threshold):
    if new_threshold > accept_threshold:
        raise ValueError("the new-cat threshold cannot sit above the accept threshold")
    if top_score >= accept_threshold:
        return ACCEPT
    if top_score >= new_threshold:
        return PICK
    return NEW


def classify(outcome, accept_threshold, new_threshold, k=PICK_K):
    """Which of the eight outcomes one scored query lands in."""
    action = decide(outcome.top_score, accept_threshold, new_threshold)
    ranked = outcome.ranked_identities
    truth = outcome.true_identity

    if action == ACCEPT:
        if not outcome.is_known:
            return "accepted_stranger"
        return (
            "accepted_correct" if ranked[:1] == (truth,) else "accepted_wrong_identity"
        )
    if action == PICK:
        if not outcome.is_known:
            return "pick_stranger"
        return "pick_has_answer" if truth in ranked[:k] else "pick_missing_answer"
    return "new_correct" if not outcome.is_known else "new_but_known"


def tally(outcomes, accept_threshold, new_threshold, k=PICK_K):
    """Counts per outcome, plus the rates a person deciding the policy needs."""
    counts = dict.fromkeys(OUTCOMES, 0)
    for outcome in outcomes:
        counts[classify(outcome, accept_threshold, new_threshold, k)] += 1

    known = sum(1 for o in outcomes if o.is_known)
    unknown = len(outcomes) - known

    def rate(numerator, denominator):
        return numerator / denominator if denominator else float("nan")

    return {
        "counts": counts,
        # The headline: enrolled cats answered alone, and right.
        "auto_resolved": rate(counts["accepted_correct"], known),
        # Wrong answers given confidently. The number to keep near zero.
        "silent_errors": rate(
            counts["accepted_wrong_identity"] + counts["accepted_stranger"],
            len(outcomes),
        ),
        # Of the cats sent to a human, how often the right one was offered.
        "pick_useful": rate(
            counts["pick_has_answer"],
            counts["pick_has_answer"] + counts["pick_missing_answer"],
        ),
        "strangers_caught": rate(
            counts["pick_stranger"] + counts["new_correct"], unknown
        ),
        "known_called_new": rate(counts["new_but_known"], known),
    }
