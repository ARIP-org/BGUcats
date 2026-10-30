"""Copy bgucats' data from the old AWS account to the new one, and prove it.

    python scripts/migrate_account.py media  [--apply]
    python scripts/migrate_account.py model  [--apply]
    python scripts/migrate_account.py table  [--apply] [--overwrite-prefix ADMIN#]
    python scripts/migrate_account.py ssm    [--apply]
    python scripts/migrate_account.py verify [--only table|media|model|ssm]

The old account is 851725214678 (now the organization's management
account), the new one 395591097129 (sasha-bgucats-prod). The runbook, with
the order these run in and why, is docs/MANUAL_STEPS.md.

What it copies:

    media   every current object in bgucats-media-{account}: raw/, derived/,
            exports/. Bytes, Content-Type, Cache-Control and user metadata.
    model   model/ in bgucats-admin-web-{account}, byte for byte, with
            model/manifest.json last: the same version hash, so every
            stored vector and guess stays valid.
    table   every item of bgucats-data, as raw attribute values, so
            `catId = null`, numbers and sets arrive exactly as they were.
            ULIDs are keys and are kept. GSIs fill themselves from the
            copied attributes. Skipped: RATE# and MGREPLY#, one-hour items
            the table's TTL deletes anyway.
    ssm     the three /bgucats/whatsapp/* values, into parameters the
            deploy created as "unset". The other /bgucats/* values come from
            the production environment's secrets through Terraform; `verify`
            proves they match (the submitter-hash salt above all: a
            different salt turns every contributor into a new person).
            Values are never printed, only "same" or "differ".
    verify  both sides, item by item and object by object: counts per key
            prefix and per GSI2PK (entity type), plus a content hash per
            item, size + MD5 per object, and SSM values compared by digest.
            Exit status 0 only on a match.

How it protects the dataset:

- Dry run unless --apply. A dry run makes the same comparisons and writes
  nothing anywhere.
- The old account is only ever read. Its clients are wrapped so that any
  call but a read raises before it is sent, and the default profile there
  is mgmt-ro (ReadOnlyAccess), so IAM refuses as well.
- The new account is only ever added to. Objects are written with
  If-None-Match: *, items with attribute_not_exists(PK). An existing
  object is never replaced. An existing item that differs is reported
  and left alone, unless its key starts with a prefix named in
  --overwrite-prefix (for the bootstrap admin row Terraform writes).
- Nothing deletes. There is no delete call in this file, and a test
  checks that.
- Each object's bytes are checked against the source ETag (its MD5) after
  download, and S3 checks them again on upload (Content-MD5).
- Both profiles are resolved to account IDs first, and the run stops
  unless they are exactly the expected two, and different.
- `media` refuses to run while the new table holds anything but ADMIN#
  rows: an object landing in raw/ triggers the process Lambda, which skips
  objects without a photo record but would re-process (and rewrite) one
  that has a record.

Imports nothing from src/ or research/.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError

SOURCE_ACCOUNT = "851725214678"
DEST_ACCOUNT = "395591097129"
REGION = "us-east-1"
TABLE = "bgucats-data"
MODEL_PREFIX = "model/"
MODEL_MANIFEST = "model/manifest.json"
SSM_PATH = "/bgucats/"
# Written outside Terraform (infra/scripts/set-whatsapp-secrets.sh), so the
# deploy leaves them "unset" and this copies them. Everything else under
# SSM_PATH is Terraform's, from the production environment's secrets.
SSM_COPIED = (
    "/bgucats/whatsapp/access-token",
    "/bgucats/whatsapp/app-secret",
    "/bgucats/whatsapp/verify-token",
)
SSM_UNSET = "unset"

# Partition-key prefixes not copied: short-lived items with expiresAt set,
# deleted by the table's TTL within the hour (src/ingest/core.py).
SKIP_PREFIXES = ("RATE#", "MGREPLY#")

# Object headers carried across. Everything else (ETag, LastModified,
# version IDs) is assigned by S3.
COPIED_HEADERS = (
    "ContentType",
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
)

WORKERS = 8


def media_bucket(account):
    return f"bgucats-media-{account}"


def web_bucket(account):
    return f"bgucats-admin-web-{account}"


class ReadOnly:
    """A boto3 client that can only read. Anything else raises unsent."""

    CALLS = frozenset(
        {
            "describe_table",
            "get_item",
            "get_parameter",
            "get_object",
            "head_object",
            "list_objects_v2",
            "scan",
        }
    )
    PAGINATORS = frozenset({"get_parameters_by_path", "list_objects_v2", "scan"})

    def __init__(self, client):
        self._client = client

    def get_paginator(self, operation):
        if operation not in self.PAGINATORS:
            raise PermissionError(f"{operation}: the source account is read-only")
        return self._client.get_paginator(operation)

    def __getattr__(self, name):
        if name not in self.CALLS:
            raise PermissionError(f"{name}: the source account is read-only")
        return getattr(self._client, name)


# --- items -----------------------------------------------------------------


def canonical(value):
    """A raw AttributeValue in a form that compares and hashes stably.

    Sets have no order in DynamoDB, and bytes do not serialise as JSON.
    """
    ((kind, v),) = value.items()
    if kind in ("SS", "NS"):
        return {kind: sorted(v)}
    if kind == "B":
        return {kind: base64.b64encode(v).decode()}
    if kind == "BS":
        return {kind: sorted(base64.b64encode(b).decode() for b in v)}
    if kind == "M":
        return {kind: {k: canonical(x) for k, x in v.items()}}
    if kind == "L":
        return {kind: [canonical(x) for x in v]}
    return {kind: v}


def item_digest(item):
    body = {name: canonical(value) for name, value in item.items()}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def key_of(item):
    return item["PK"]["S"], item["SK"]["S"]


def prefix_of(pk):
    head, sep, _ = pk.partition("#")
    return head + sep


def differing_names(a, b):
    """Attribute names whose values differ. Names only, never values."""
    names = set(a) | set(b)
    return sorted(
        n
        for n in names
        if n not in a or n not in b or canonical(a[n]) != canonical(b[n])
    )


def scan_items(client, table):
    for page in client.get_paginator("scan").paginate(
        TableName=table, ConsistentRead=True
    ):
        yield from page["Items"]


def get_dest_item(client, table, key):
    pk, sk = key
    response = client.get_item(
        TableName=table,
        Key={"PK": {"S": pk}, "SK": {"S": sk}},
        ConsistentRead=True,
    )
    return response.get("Item")


def table_has_data(client, table):
    """True if the table holds anything but allowlist (ADMIN#) rows."""
    paginator = client.get_paginator("scan")
    pages = paginator.paginate(
        TableName=table,
        Select="COUNT",
        FilterExpression="NOT begins_with(PK, :admin)",
        ExpressionAttributeValues={":admin": {"S": "ADMIN#"}},
    )
    return any(page["Count"] for page in pages)


def copy_item(dst, table, item, apply, overwrite_prefixes):
    """One item, create-only. Returns an outcome and, for conflicts, names."""
    key = key_of(item)
    if not apply:
        existing = get_dest_item(dst, table, key)
        if existing is None:
            return "would copy", None
        if item_digest(existing) == item_digest(item):
            return "same", None
        if key[0].startswith(overwrite_prefixes):
            return "would overwrite", differing_names(item, existing)
        return "conflict", differing_names(item, existing)
    try:
        dst.put_item(
            TableName=table,
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )
        return "copied", None
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    existing = get_dest_item(dst, table, key)
    if item_digest(existing) == item_digest(item):
        return "same", None
    names = differing_names(item, existing)
    if key[0].startswith(overwrite_prefixes):
        dst.put_item(TableName=table, Item=item)
        return "overwritten", names
    return "conflict", names


def copy_table(src, dst, src_table, dst_table, apply, overwrite_prefixes=()):
    """Copies every item. Returns {prefix: Counter(outcome)} and conflicts."""
    overwrite_prefixes = tuple(overwrite_prefixes)
    outcomes = defaultdict(Counter)
    conflicts = []
    items = []
    for item in scan_items(src, src_table):
        prefix = prefix_of(item["PK"]["S"])
        if item["PK"]["S"].startswith(SKIP_PREFIXES):
            outcomes[prefix]["skipped"] += 1
        else:
            items.append(item)

    def one(item):
        return item, copy_item(dst, dst_table, item, apply, overwrite_prefixes)

    with ThreadPoolExecutor(WORKERS) as pool:
        for done, (item, (outcome, names)) in enumerate(pool.map(one, items), 1):
            outcomes[prefix_of(item["PK"]["S"])][outcome] += 1
            if names is not None:
                conflicts.append((key_of(item), outcome, names))
            if done % 1000 == 0:
                print(f"  {done}/{len(items)} items", file=sys.stderr)
    return outcomes, conflicts


# --- objects ---------------------------------------------------------------


def list_objects(client, bucket, prefix=""):
    """{key: (size, etag)} for every current object under prefix."""
    found = {}
    pages = client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    )
    for page in pages:
        for obj in page.get("Contents", []):
            found[obj["Key"]] = (obj["Size"], obj["ETag"].strip('"'))
    return found


def head(client, bucket, key):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def headers_of(response):
    picked = {name: response[name] for name in COPIED_HEADERS if response.get(name)}
    if response.get("Metadata"):
        picked["Metadata"] = response["Metadata"]
    return picked


class IntegrityError(Exception):
    pass


def same_object(source, dest):
    """(size, etag) pairs. A multipart source ETag ("...-N") is not an MD5,
    and a single-part copy of it gets a different one: compare size only."""
    if source[0] != dest[0]:
        return False
    return "-" in source[1] or source[1] == dest[1]


def copy_object(src, dst, src_bucket, dst_bucket, key, size, etag, apply):
    existing = head(dst, dst_bucket, key)
    if existing is not None:
        theirs = (existing["ContentLength"], existing["ETag"].strip('"'))
        return "same" if same_object((size, etag), theirs) else "conflict"
    if not apply:
        return "would copy"
    response = src.get_object(Bucket=src_bucket, Key=key)
    body = response["Body"].read()
    md5 = hashlib.md5(body)
    if len(body) != size:
        raise IntegrityError(f"{key}: read {len(body)} bytes, listed {size}")
    # A multipart ETag ("...-N") is not an MD5 of the object; the size check
    # above and S3's own Content-MD5 check below still hold.
    if "-" not in etag and md5.hexdigest() != etag:
        raise IntegrityError(f"{key}: downloaded bytes do not match the source ETag")
    try:
        dst.put_object(
            Bucket=dst_bucket,
            Key=key,
            Body=body,
            ContentMD5=base64.b64encode(md5.digest()).decode(),
            IfNoneMatch="*",
            **headers_of(response),
        )
    except ClientError as error:
        if error.response["Error"]["Code"] in (
            "PreconditionFailed",
            "ConditionalRequestConflict",
        ):
            return "conflict"
        raise
    return "copied"


def copy_objects(src, dst, src_bucket, dst_bucket, prefix, apply, last=None):
    """Copies every current object under prefix, `last` after all others."""
    objects = list_objects(src, src_bucket, prefix)
    keys = sorted(k for k in objects if k != last)
    outcomes = defaultdict(Counter)
    conflicts = []

    def one(key):
        size, etag = objects[key]
        return key, copy_object(
            src, dst, src_bucket, dst_bucket, key, size, etag, apply
        )

    def record(key, outcome):
        outcomes[key.split("/", 1)[0] + "/"][outcome] += 1
        if outcome == "conflict":
            conflicts.append(key)

    with ThreadPoolExecutor(WORKERS) as pool:
        for done, (key, outcome) in enumerate(pool.map(one, keys), 1):
            record(key, outcome)
            if done % 500 == 0:
                print(f"  {done}/{len(keys)} objects", file=sys.stderr)
    if last is not None and last in objects:
        record(*one(last))
    return outcomes, conflicts


# --- parameters ------------------------------------------------------------


def parameter_values(client, path=SSM_PATH):
    """{name: value}, decrypted. Held in memory only, never printed."""
    values = {}
    pages = client.get_paginator("get_parameters_by_path").paginate(
        Path=path, Recursive=True, WithDecryption=True
    )
    for page in pages:
        for parameter in page["Parameters"]:
            values[parameter["Name"]] = parameter["Value"]
    return values


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def compare_parameters(source, dest):
    """{name: same | differ | missing | extra}, by digest."""
    result = {}
    for name in sorted(set(source) | set(dest)):
        if name not in dest:
            result[name] = "missing"
        elif name not in source:
            result[name] = "extra"
        else:
            result[name] = (
                "same" if digest(source[name]) == digest(dest[name]) else "differ"
            )
    return result


def copy_parameters(src, dst, apply, names=SSM_COPIED):
    """Copies names whose dest value is missing or "unset". {name: outcome}."""
    source = parameter_values(src)
    dest = parameter_values(dst)
    outcomes = {}
    for name in names:
        if name not in source:
            outcomes[name] = "not in source"
        elif name in dest and digest(dest[name]) == digest(source[name]):
            outcomes[name] = "same"
        elif name in dest and dest[name] != SSM_UNSET:
            outcomes[name] = "conflict"
        elif not apply:
            outcomes[name] = "would copy"
        else:
            dst.put_parameter(
                Name=name,
                Value=source[name],
                Type="SecureString",
                Overwrite=name in dest,
            )
            outcomes[name] = "copied"
    return outcomes


# --- verify ----------------------------------------------------------------


def compare_tables(src, dst, src_table, dst_table):
    """Per-prefix counts and differences, per-GSI2PK counts, GSI fill."""
    source = {key_of(i): i for i in scan_items(src, src_table)}
    dest = {key_of(i): i for i in scan_items(dst, dst_table)}
    rows = defaultdict(Counter)
    problems = []
    for key, item in source.items():
        prefix = prefix_of(key[0])
        rows[prefix]["source"] += 1
        if key[0].startswith(SKIP_PREFIXES):
            continue
        other = dest.get(key)
        if other is None:
            rows[prefix]["missing"] += 1
            problems.append(("missing", key, None))
        elif item_digest(other) != item_digest(item):
            rows[prefix]["differ"] += 1
            problems.append(("differ", key, differing_names(item, other)))
    for key in dest:
        prefix = prefix_of(key[0])
        rows[prefix]["dest"] += 1
        if key not in source and not key[0].startswith(SKIP_PREFIXES):
            rows[prefix]["extra"] += 1
            problems.append(("extra", key, None))

    entities = defaultdict(Counter)
    for side, items in (("source", source), ("dest", dest)):
        for item in items.values():
            if "GSI2PK" in item and not item["PK"]["S"].startswith(SKIP_PREFIXES):
                entities[entity_of(item["GSI2PK"])][side] += 1
    return rows, entities, problems, index_fill(dst, dst_table, dest.values())


def entity_of(value):
    """A GSI2PK as a row label: ENTITY#CAT, STATUS#unlabeled, VECTOR#..."""
    ((kind, v),) = value.items()
    return v if kind == "S" else f"<{kind}>"


def index_fill(client, table, items):
    """{index: (expected, actual)}. GSIs are eventually consistent."""
    description = client.describe_table(TableName=table)["Table"]
    fill = {}
    for index in description.get("GlobalSecondaryIndexes", []):
        names = [k["AttributeName"] for k in index["KeySchema"]]
        expected = sum(1 for i in items if all(n in i for n in names))
        pages = client.get_paginator("scan").paginate(
            TableName=table, IndexName=index["IndexName"], Select="COUNT"
        )
        fill[index["IndexName"]] = (expected, sum(p["Count"] for p in pages))
    return fill


def compare_objects(src, dst, src_bucket, dst_bucket, prefix="", headers=True):
    source = list_objects(src, src_bucket, prefix)
    dest = list_objects(dst, dst_bucket, prefix)
    rows = defaultdict(Counter)
    problems = []

    def check(key):
        if key not in dest:
            return key, "missing"
        if not same_object(source[key], dest[key]):
            return key, "differ"
        if headers:
            a = headers_of(head(src, src_bucket, key))
            b = headers_of(head(dst, dst_bucket, key))
            if a != b:
                return key, "headers differ"
        return key, "ok"

    with ThreadPoolExecutor(WORKERS) as pool:
        for key, outcome in pool.map(check, sorted(source)):
            group = key.split("/", 1)[0] + "/"
            rows[group]["source"] += 1
            if outcome != "ok":
                rows[group][outcome] += 1
                problems.append((outcome, key))
    for key in dest:
        group = key.split("/", 1)[0] + "/"
        rows[group]["dest"] += 1
        if key not in source:
            rows[group]["extra"] += 1
            problems.append(("extra", key))
    return rows, problems


# --- command line ------------------------------------------------------------


def print_rows(title, rows, columns):
    print(f"\n{title}")
    width = max([len(r) for r in rows] + [8])
    print("  " + "".ljust(width) + "".join(c.rjust(16) for c in columns))
    for name in sorted(rows):
        print(
            "  "
            + name.ljust(width)
            + "".join(str(rows[name][c]).rjust(16) for c in columns)
        )


def open_accounts(args):
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        sys.exit("AWS_ACCESS_KEY_ID is set: unset it, and name both profiles instead.")
    src = boto3.Session(profile_name=args.source_profile, region_name=REGION)
    dst = boto3.Session(profile_name=args.dest_profile, region_name=REGION)
    src_account = src.client("sts").get_caller_identity()["Account"]
    dst_account = dst.client("sts").get_caller_identity()["Account"]
    check_accounts(src_account, dst_account, args.source_account, args.dest_account)
    print(f"source {src_account} ({args.source_profile}), read only")
    print(
        f"dest   {dst_account} ({args.dest_profile}), {'WRITES' if getattr(args, 'apply', False) else 'dry run'}"
    )
    return src, dst


def check_accounts(src_account, dst_account, want_src, want_dst):
    if src_account != want_src:
        sys.exit(f"source profile is account {src_account}, expected {want_src}")
    if dst_account != want_dst:
        sys.exit(f"dest profile is account {dst_account}, expected {want_dst}")
    if src_account == dst_account:
        sys.exit("source and dest are the same account")


def run_media(args, src, dst):
    s3 = dst.client("s3")
    if table_has_data(dst.client("dynamodb"), TABLE) and not args.allow_nonempty_table:
        sys.exit(
            "The dest table already has data, so objects landing in raw/ would be "
            "re-processed. Copy media before the table (docs/MANUAL_STEPS.md)."
        )
    outcomes, conflicts = copy_objects(
        ReadOnly(src.client("s3")),
        s3,
        media_bucket(args.source_account),
        media_bucket(args.dest_account),
        "",
        args.apply,
    )
    for key in conflicts:
        print(f"  conflict: {key}")
    return report_copy("media objects", outcomes)


def run_model(args, src, dst):
    outcomes, conflicts = copy_objects(
        ReadOnly(src.client("s3")),
        dst.client("s3"),
        web_bucket(args.source_account),
        web_bucket(args.dest_account),
        MODEL_PREFIX,
        args.apply,
        last=MODEL_MANIFEST,
    )
    for key in conflicts:
        print(f"  conflict: {key}")
    return report_copy("model objects", outcomes)


def run_table(args, src, dst):
    outcomes, conflicts = copy_table(
        ReadOnly(src.client("dynamodb")),
        dst.client("dynamodb"),
        TABLE,
        TABLE,
        args.apply,
        args.overwrite_prefix,
    )
    for key, outcome, names in conflicts:
        print(f"  {outcome}: {key[0]} / {key[1]}  attributes: {', '.join(names)}")
    return report_copy("table items", outcomes)


def report_copy(title, outcomes):
    columns = sorted({c for row in outcomes.values() for c in row})
    print_rows(title, outcomes, columns)
    conflicts = sum(row["conflict"] for row in outcomes.values())
    if conflicts:
        print(
            f"\n{conflicts} conflict(s), listed above: left as they are in the dest account."
        )
        return 1
    return 0


def run_verify(args, src, dst):
    status = 0
    if args.only in (None, "table"):
        rows, entities, problems, fill = compare_tables(
            ReadOnly(src.client("dynamodb")), dst.client("dynamodb"), TABLE, TABLE
        )
        print_rows(
            "table, by key prefix",
            rows,
            ["source", "dest", "missing", "differ", "extra"],
        )
        print_rows("table, by GSI2PK (entity type)", entities, ["source", "dest"])
        print("\nGSI fill in dest (expected / indexed):")
        for name, (expected, actual) in sorted(fill.items()):
            note = (
                ""
                if expected == actual
                else "  catching up? run verify again in a minute"
            )
            print(f"  {name}: {expected} / {actual}{note}")
        for kind, key, names in problems[:50]:
            print(
                f"  {kind}: {key[0]} / {key[1]}"
                + (f"  attributes: {', '.join(names)}" if names else "")
            )
        status |= bool(problems) or any(e != a for e, a in fill.values())
    if args.only in (None, "ssm"):
        result = compare_parameters(
            parameter_values(ReadOnly(src.client("ssm"))),
            parameter_values(dst.client("ssm")),
        )
        print("\nSSM parameters under /bgucats/ (values compared by digest):")
        for name, outcome in result.items():
            print(f"  {outcome:8} {name}")
        status |= any(outcome != "same" for outcome in result.values())
    buckets = []
    if args.only in (None, "media"):
        buckets.append(("media", media_bucket, ""))
    if args.only in (None, "model"):
        buckets.append(("model", web_bucket, MODEL_PREFIX))
    for title, bucket, prefix in buckets:
        rows, problems = compare_objects(
            ReadOnly(src.client("s3")),
            dst.client("s3"),
            bucket(args.source_account),
            bucket(args.dest_account),
            prefix,
            headers=not args.no_headers,
        )
        print_rows(
            f"{title} objects",
            rows,
            ["source", "dest", "missing", "differ", "headers differ", "extra"],
        )
        for problem in problems[:50]:
            print(f"  {problem}")
        status |= bool(problems)
    print("\nMATCH" if status == 0 else "\nDIFFERENCES, see above")
    return int(status)


def run_ssm(args, src, dst):
    outcomes = copy_parameters(
        ReadOnly(src.client("ssm")), dst.client("ssm"), args.apply
    )
    print("\nSSM parameters (values never printed):")
    for name, outcome in outcomes.items():
        print(f"  {outcome:14} {name}")
    if "conflict" in outcomes.values():
        print(
            "\nA conflict is a real value already in the dest account: left as it is."
        )
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-profile", default="mgmt-ro")
    parser.add_argument("--dest-profile", default="bgucats-prod-admin")
    parser.add_argument("--source-account", default=SOURCE_ACCOUNT)
    parser.add_argument("--dest-account", default=DEST_ACCOUNT)
    sub = parser.add_subparsers(dest="command", required=True)

    media = sub.add_parser("media", help="copy the media bucket")
    media.add_argument("--apply", action="store_true", help="write (default: dry run)")
    media.add_argument(
        "--allow-nonempty-table",
        action="store_true",
        help="copy even though the dest table has data (re-triggers processing)",
    )
    model = sub.add_parser("model", help="copy model/ from the admin web bucket")
    model.add_argument("--apply", action="store_true", help="write (default: dry run)")
    table = sub.add_parser("table", help="copy the table")
    table.add_argument("--apply", action="store_true", help="write (default: dry run)")
    table.add_argument(
        "--overwrite-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="replace dest items under this PK prefix that differ (repeatable)",
    )
    ssm = sub.add_parser("ssm", help="copy the WhatsApp secrets")
    ssm.add_argument("--apply", action="store_true", help="write (default: dry run)")
    verify = sub.add_parser("verify", help="compare both accounts")
    verify.add_argument("--only", choices=["table", "media", "model", "ssm"])
    verify.add_argument(
        "--no-headers", action="store_true", help="skip per-object HEADs"
    )

    args = parser.parse_args(argv)
    src, dst = open_accounts(args)
    run = {
        "media": run_media,
        "model": run_model,
        "table": run_table,
        "ssm": run_ssm,
        "verify": run_verify,
    }
    return run[args.command](args, src, dst)


if __name__ == "__main__":
    sys.exit(main())
