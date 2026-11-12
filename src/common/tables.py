"""Reading DynamoDB the way this project has learned it must
(docs/notes.md, "DynamoDB").
"""


def get_one(table, pk, sk="META"):
    """One record by its key, read strongly consistent.

    DynamoDB's default read may answer from a copy that has not received a
    write made milliseconds earlier. The app makes exactly such pairs of
    calls: an encounter and then its first photo, a photo's record and then
    its confirmation, a new cat and then its first label. A stale "not
    there" was answered as 404, and the phone's outbox treats a 404 as
    final, so the photo was dropped. Found on 2026-11-10 by seeding staging
    through the API: one encounter in twelve. A consistent read of one item
    costs one read unit instead of half of one.
    """
    return table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")


def query_all(table, **kwargs):
    """Every page of a query, not just the first 1 MB.

    An index can never be read consistently: nothing may be decided on an
    item's absence from what this returns.
    """
    items = []
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
