"""What happens after a write to bgucats-social (docs/app-plan/02-architecture.md,
"What happens after a write: the events Lambda").

Fed by an event source mapping on the table's stream, through the filter in
filters.json, in batches. Since milestone F3 it only sorts each change by
kind, logs one line per batch, and counts. The milestones that bring each
kind (B1 onward) give it a real handler in HANDLERS; moderation, counters,
badges and push all arrive here.

The rules every handler keeps:

- Idempotent. A stream delivers at least once, so a handler checks the
  state it is about to make before making it, and writes with conditions.
- Never in a person's way: the request that wrote the item has answered.
- A failing record is reported by its sequence number, so the batch around
  it is not retried with it (ReportBatchItemFailures). The mapping retries
  it, splits the batch to find it, and after three tries sends it to the
  alerts topic.
- Never writes anything filters.json admits unless the handler that writes
  it checks the state first: that is how it would trigger itself.
"""

import json
import logging
from collections import Counter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# (partition key prefix, sort key equal or prefix) -> kind. The first match
# wins. Keys are the social table's (docs/data-model.md, "bgucats-social").
KINDS = (
    ("POST#", "META", "post"),
    ("CAT#", "NAME#", "name"),
    ("CAT#", "VOTE#", "vote"),
    ("CAT#", "FED#", "feeding"),
    ("USER#", "PROFILE", "profile"),
    ("USER#", "FRIEND#", "friend"),
    ("USER#", "FREQ#IN#", "friend_request"),
    ("USER#", "ENC#", "encounter"),
    ("PROPOSAL#", "META", "proposal"),
    ("REPORT#", "META", "report"),
)

# Items this Lambda writes, or will: none of them may pass the filter, or
# writing one would start the Lambda again (tests/events/test_filters.py).
SELF_WRITTEN = (
    ("CAT#", "PUBLIC"),
    ("USER#", "STATS#ALL"),
    ("USER#", "STATS#2026-11"),
    ("USER#", "MET#01J0000000000000000000000"),
    ("USER#", "METM#2026-11#01J0000000000000000000000"),
    ("USER#", "BADGE#first-meow"),
    ("USER#", "PUSHED#2026-11-12"),
    ("USER#", "DEVICE#phone"),
    ("MOD#POSTTEXT#01J0000000000000000000000", "RUN#2026-11-12T00:00:00Z"),
    ("SPEND#2026-11-12", "DECISIONS"),
    ("RATE#u#posts#1800000000", "META"),
    ("POST#01J0000000000000000000000", "LIKE#u"),
)


def kind_of(pk, sk):
    for pk_prefix, sk_match, kind in KINDS:
        if not pk.startswith(pk_prefix):
            continue
        exact = sk_match in ("META", "PROFILE")
        if (sk == sk_match) if exact else sk.startswith(sk_match):
            return kind
    return None


def _not_built_yet(record):
    """Every kind, until the milestone that brings it gives it a handler."""


HANDLERS = {kind: _not_built_yet for _, _, kind in KINDS}


def _keys(record):
    keys = record.get("dynamodb", {}).get("Keys", {})
    return keys.get("PK", {}).get("S", ""), keys.get("SK", {}).get("S", "")


def handler(event, context):
    records = event.get("Records") or []
    seen = Counter()
    failures = []
    for record in records:
        pk, sk = _keys(record)
        kind = kind_of(pk, sk)
        if kind is None:
            # Passed the filter but no kind matches: the two have drifted.
            # Skipped, not retried: retrying cannot make it match.
            seen["unexpected"] += 1
            logger.warning(
                "no kind for a change to %s / %s", pk.split("#")[0], sk.split("#")[0]
            )
            continue
        seen[f"{kind}:{record.get('eventName', '?')}"] += 1
        try:
            HANDLERS[kind](record)
        except Exception:
            logger.exception("handler for %s failed", kind)
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    logger.info(
        json.dumps(
            {
                "records": len(records),
                "kinds": dict(sorted(seen.items())),
                "failed": len(failures),
            }
        )
    )
    return {"batchItemFailures": failures}
