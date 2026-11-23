"""A stand-in for bgucats-social's stream, for tests and the local app.

`settle()` compares the table with what it saw last, hands every change the
stream's filter would pass to the events Lambda, the way the event source
mapping does, and repeats until the Lambda's own writes change nothing it
would see again. A Lambda that kept triggering itself fails here instead of
looping.
"""

from boto3.dynamodb.types import TypeSerializer

from events import handler as events

_SERIALIZE = TypeSerializer()
# Deleting an account (B10a) is a chain: each of its six steps is started
# by the change the step before wrote, and its deletions come back once more.
ROUNDS = 12


def _image(item):
    return {k: _SERIALIZE.serialize(v) for k, v in item.items()}


class Stream:
    def __init__(self, table):
        self.table = table
        self.seen = self._snapshot()
        self.sequence = 0

    def _snapshot(self):
        items, start = [], None
        while True:
            kwargs = {"ExclusiveStartKey": start} if start else {}
            page = self.table.scan(**kwargs)
            items.extend(page["Items"])
            start = page.get("LastEvaluatedKey")
            if not start:
                return {(i["PK"], i["SK"]): i for i in items}

    def _records(self, before, after):
        records = []
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            if old == new or events.kind_of(*key) is None:
                continue
            self.sequence += 1
            change = {
                "Keys": {"PK": {"S": key[0]}, "SK": {"S": key[1]}},
                "SequenceNumber": str(self.sequence),
            }
            if old is not None:
                change["OldImage"] = _image(old)
            if new is not None:
                change["NewImage"] = _image(new)
            name = "INSERT" if old is None else "REMOVE" if new is None else "MODIFY"
            records.append({"eventName": name, "dynamodb": change})
        return records

    def settle(self):
        """Deliver every change since the last call. Returns how many."""
        delivered = 0
        for _ in range(ROUNDS):
            now = self._snapshot()
            records = self._records(self.seen, now)
            self.seen = now
            if not records:
                return delivered
            answer = events.handler({"Records": records}, None)
            assert answer == {"batchItemFailures": []}, answer
            delivered += len(records)
        raise AssertionError("the events Lambda is still triggering itself")
