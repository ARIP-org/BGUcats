"""The account migration (scripts/migrate_account.py): copies exactly, only
adds to the new account, only reads the old one, and never deletes."""

import ast
import hashlib
import io
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import migrate_account as m

SRC_TABLE, DST_TABLE = "src-data", "dst-data"
SRC_BUCKET, DST_BUCKET = "src-media", "dst-media"

SESSION = {
    "PK": {"S": "SESSION#01SESSION000000000000000"},
    "SK": {"S": "META"},
    "catId": {"NULL": True},
    "photoCount": {"N": "3"},
    "tags": {"SS": ["b", "a"]},
    "blob": {"B": b"\x00\x01"},
    "nested": {"M": {"x": {"L": [{"N": "1.5"}, {"NULL": True}]}}},
    "GSI2PK": {"S": "ENTITY#ENCOUNTER"},
    "GSI2SK": {"S": "someone@example.com#2026-10-30T00:00:00Z"},
}
PHOTO = {
    "PK": {"S": "PHOTO#01PHOTO0000000000000000000"},
    "SK": {"S": "META"},
    "status": {"S": "unlabeled"},
    "GSI1PK": {"S": "SESSION#01SESSION000000000000000"},
    "GSI1SK": {"S": "2026-10-30T00:00:00Z"},
    "GSI2PK": {"S": "STATUS#unlabeled"},
    "GSI2SK": {"S": "2026-10-30T00:00:00Z"},
}
ADMIN = {
    "PK": {"S": "ADMIN#someone@example.com"},
    "SK": {"S": "META"},
    "email": {"S": "someone@example.com"},
    "role": {"S": "collaborator"},
    "addedBy": {"S": "terraform"},
}
RATE = {"PK": {"S": "RATE#abc#2026"}, "SK": {"S": "META"}, "expiresAt": {"N": "1"}}
MGREPLY = {"PK": {"S": "MGREPLY#123"}, "SK": {"S": "META"}, "expiresAt": {"N": "1"}}


def _table(ddb, name):
    keys = ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"]
    ddb.create_table(
        TableName=name,
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": f"GSI{n}",
                "KeySchema": [
                    {"AttributeName": f"GSI{n}PK", "KeyType": "HASH"},
                    {"AttributeName": f"GSI{n}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for n in (1, 2)
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        _table(ddb, SRC_TABLE)
        _table(ddb, DST_TABLE)
        s3.create_bucket(Bucket=SRC_BUCKET)
        s3.create_bucket(Bucket=DST_BUCKET)
        for item in (SESSION, PHOTO, ADMIN, RATE, MGREPLY):
            ddb.put_item(TableName=SRC_TABLE, Item=item)
        yield {"ddb": ddb, "s3": s3}


def _dest_items(ddb):
    return {m.key_of(i): i for i in m.scan_items(ddb, DST_TABLE)}


def _copy(aws, apply=True, overwrite=()):
    return m.copy_table(
        m.ReadOnly(aws["ddb"]), aws["ddb"], SRC_TABLE, DST_TABLE, apply, overwrite
    )


# --- table ---------------------------------------------------------------


def test_dry_run_writes_nothing(aws):
    outcomes, _ = _copy(aws, apply=False)
    assert _dest_items(aws["ddb"]) == {}
    assert outcomes["SESSION#"]["would copy"] == 1
    assert outcomes["RATE#"]["skipped"] == 1


def test_copies_raw_values_exactly_and_skips_ttl_items(aws):
    _copy(aws)
    dest = _dest_items(aws["ddb"])
    assert set(dest) == {m.key_of(SESSION), m.key_of(PHOTO), m.key_of(ADMIN)}
    copied = dest[m.key_of(SESSION)]
    # catId = null is what the guess transaction's condition depends on.
    assert copied["catId"] == {"NULL": True}
    assert m.item_digest(copied) == m.item_digest(SESSION)


def test_rerun_is_a_no_op(aws):
    _copy(aws)
    outcomes, conflicts = _copy(aws)
    assert sum(row["copied"] for row in outcomes.values()) == 0
    assert outcomes["PHOTO#"]["same"] == 1
    assert conflicts == []


def test_differing_dest_item_is_left_alone(aws):
    # Terraform's bootstrap row in the new account has no role (= admin).
    bootstrap = {k: v for k, v in ADMIN.items() if k != "role"}
    aws["ddb"].put_item(TableName=DST_TABLE, Item=bootstrap)
    changed = dict(PHOTO, status={"S": "labeled"})
    aws["ddb"].put_item(TableName=DST_TABLE, Item=changed)

    outcomes, conflicts = _copy(aws)

    dest = _dest_items(aws["ddb"])
    assert dest[m.key_of(ADMIN)] == bootstrap
    assert dest[m.key_of(PHOTO)]["status"] == {"S": "labeled"}
    assert outcomes["ADMIN#"]["conflict"] == 1
    assert ((m.key_of(ADMIN), "conflict", ["role"])) in conflicts


def test_overwrite_prefix_replaces_only_that_prefix(aws):
    bootstrap = {k: v for k, v in ADMIN.items() if k != "role"}
    aws["ddb"].put_item(TableName=DST_TABLE, Item=bootstrap)
    aws["ddb"].put_item(TableName=DST_TABLE, Item=dict(PHOTO, status={"S": "labeled"}))

    preview, _ = _copy(aws, apply=False, overwrite=["ADMIN#"])
    assert preview["ADMIN#"]["would overwrite"] == 1
    outcomes, _ = _copy(aws, overwrite=["ADMIN#"])

    dest = _dest_items(aws["ddb"])
    assert dest[m.key_of(ADMIN)]["role"] == {"S": "collaborator"}
    assert dest[m.key_of(PHOTO)]["status"] == {"S": "labeled"}
    assert outcomes["ADMIN#"]["overwritten"] == 1
    assert outcomes["PHOTO#"]["conflict"] == 1


def test_table_has_data_ignores_admin_rows(aws):
    assert not m.table_has_data(aws["ddb"], DST_TABLE)
    aws["ddb"].put_item(TableName=DST_TABLE, Item=ADMIN)
    assert not m.table_has_data(aws["ddb"], DST_TABLE)
    aws["ddb"].put_item(TableName=DST_TABLE, Item=PHOTO)
    assert m.table_has_data(aws["ddb"], DST_TABLE)


def test_verify_table_match_and_differences(aws):
    _copy(aws)
    rows, entities, problems, fill = m.compare_tables(
        m.ReadOnly(aws["ddb"]), aws["ddb"], SRC_TABLE, DST_TABLE
    )
    assert problems == []
    assert rows["SESSION#"]["source"] == rows["SESSION#"]["dest"] == 1
    assert entities["STATUS#unlabeled"] == {"source": 1, "dest": 1}
    assert fill["GSI1"] == (1, 1)
    assert fill["GSI2"] == (2, 2)

    aws["ddb"].put_item(TableName=DST_TABLE, Item=dict(SESSION, photoCount={"N": "4"}))
    aws["ddb"].delete_item(
        TableName=DST_TABLE, Key={"PK": PHOTO["PK"], "SK": PHOTO["SK"]}
    )
    extra = {"PK": {"S": "CAT#01NEW"}, "SK": {"S": "META"}}
    aws["ddb"].put_item(TableName=DST_TABLE, Item=extra)

    _, _, problems, _ = m.compare_tables(
        m.ReadOnly(aws["ddb"]), aws["ddb"], SRC_TABLE, DST_TABLE
    )
    assert ("differ", m.key_of(SESSION), ["photoCount"]) in problems
    assert ("missing", m.key_of(PHOTO), None) in problems
    assert ("extra", m.key_of(extra), None) in problems


def test_digest_ignores_set_order():
    a = {"PK": {"S": "X"}, "s": {"SS": ["a", "b"]}}
    b = {"PK": {"S": "X"}, "s": {"SS": ["b", "a"]}}
    assert m.item_digest(a) == m.item_digest(b)


# --- objects -------------------------------------------------------------


def _put(s3, key, body, **headers):
    s3.put_object(Bucket=SRC_BUCKET, Key=key, Body=body, **headers)


def _copy_objects(aws, prefix="", apply=True, last=None):
    return m.copy_objects(
        m.ReadOnly(aws["s3"]), aws["s3"], SRC_BUCKET, DST_BUCKET, prefix, apply, last
    )


def test_objects_copy_bytes_and_headers(aws):
    _put(
        aws["s3"],
        "raw/S1/P1.jpg",
        b"jpeg",
        ContentType="image/jpeg",
        Metadata={"a": "b"},
    )
    _put(aws["s3"], "derived/P1/thumb-256.webp", b"webp", ContentType="image/webp")

    preview, _ = _copy_objects(aws, apply=False)
    assert preview["raw/"]["would copy"] == 1
    assert "Contents" not in aws["s3"].list_objects_v2(Bucket=DST_BUCKET)

    outcomes, conflicts = _copy_objects(aws)
    assert outcomes["raw/"]["copied"] == outcomes["derived/"]["copied"] == 1
    assert conflicts == []
    got = aws["s3"].get_object(Bucket=DST_BUCKET, Key="raw/S1/P1.jpg")
    assert got["Body"].read() == b"jpeg"
    assert got["ContentType"] == "image/jpeg"
    assert got["Metadata"] == {"a": "b"}

    again, _ = _copy_objects(aws)
    assert again["raw/"]["same"] == 1


def test_existing_dest_object_is_never_replaced(aws):
    _put(aws["s3"], "raw/S1/P1.jpg", b"new")
    aws["s3"].put_object(Bucket=DST_BUCKET, Key="raw/S1/P1.jpg", Body=b"old")

    outcomes, conflicts = _copy_objects(aws)

    assert conflicts == ["raw/S1/P1.jpg"]
    assert outcomes["raw/"]["conflict"] == 1
    body = aws["s3"].get_object(Bucket=DST_BUCKET, Key="raw/S1/P1.jpg")["Body"].read()
    assert body == b"old"


def test_manifest_is_copied_last(aws):
    for key in (
        "model/v1/model.onnx",
        "model/manifest.json",
        "model/v1/ort.wasm.min.js",
    ):
        _put(aws["s3"], key, key.encode())
    order = []
    real = aws["s3"].put_object

    class Recording:
        def __getattr__(self, name):
            return getattr(aws["s3"], name)

        def put_object(self, **kwargs):
            order.append(kwargs["Key"])
            return real(**kwargs)

    m.copy_objects(
        m.ReadOnly(aws["s3"]),
        Recording(),
        SRC_BUCKET,
        DST_BUCKET,
        "model/",
        True,
        "model/manifest.json",
    )
    assert order[-1] == "model/manifest.json"
    assert len(order) == 3


def test_corrupted_download_is_refused():
    class Source:
        def get_object(self, **_):
            return {"Body": io.BytesIO(b"tampered"), "ContentType": "image/jpeg"}

    class Dest:
        def head_object(self, **_):
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

        def put_object(self, **_):
            raise AssertionError("must not upload")

    etag = hashlib.md5(b"original").hexdigest()
    with pytest.raises(m.IntegrityError):
        m.copy_object(Source(), Dest(), "a", "b", "raw/x.jpg", 8, etag, apply=True)


def test_verify_objects(aws):
    _put(aws["s3"], "raw/S1/P1.jpg", b"one", ContentType="image/jpeg")
    _put(aws["s3"], "raw/S1/P2.jpg", b"two", ContentType="image/jpeg")
    _copy_objects(aws)
    rows, problems = m.compare_objects(
        m.ReadOnly(aws["s3"]), aws["s3"], SRC_BUCKET, DST_BUCKET
    )
    assert problems == []
    assert rows["raw/"]["source"] == rows["raw/"]["dest"] == 2

    aws["s3"].put_object(
        Bucket=DST_BUCKET, Key="raw/S1/P2.jpg", Body=b"two", ContentType="text/plain"
    )
    aws["s3"].put_object(Bucket=DST_BUCKET, Key="raw/S1/P3.jpg", Body=b"three")
    _, problems = m.compare_objects(
        m.ReadOnly(aws["s3"]), aws["s3"], SRC_BUCKET, DST_BUCKET
    )
    assert ("headers differ", "raw/S1/P2.jpg") in problems
    assert ("extra", "raw/S1/P3.jpg") in problems


# --- guards --------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "put_item",
        "delete_item",
        "batch_write_item",
        "update_item",
        "put_object",
        "delete_object",
        "copy_object",
    ],
)
def test_source_refuses_anything_but_reads(call):
    with pytest.raises(PermissionError):
        getattr(m.ReadOnly(object()), call)


def test_source_refuses_write_paginators():
    with pytest.raises(PermissionError):
        m.ReadOnly(object()).get_paginator("list_object_versions")


@pytest.mark.parametrize(
    "src,dst",
    [
        ("111111111111", m.DEST_ACCOUNT),
        (m.SOURCE_ACCOUNT, "111111111111"),
        (m.DEST_ACCOUNT, m.DEST_ACCOUNT),
    ],
)
def test_wrong_accounts_stop_the_run(src, dst):
    with pytest.raises(SystemExit):
        m.check_accounts(src, dst, m.SOURCE_ACCOUNT, m.DEST_ACCOUNT)


def test_the_script_never_deletes():
    tree = ast.parse(Path(m.__file__).read_text())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {name for name in called if "delete" in name.lower()}


# --- parameters ----------------------------------------------------------


@pytest.fixture
def ssm():
    with mock_aws():
        yield boto3.client("ssm", region_name="us-east-1")


class Prefixed:
    """One moto account, two "accounts": the dest side lives under /dst."""

    def __init__(self, client, root):
        self._client, self._root = client, root

    def get_paginator(self, operation):
        paginator = self._client.get_paginator(operation)
        root = self._root

        class Paginator:
            def paginate(self, Path, **kwargs):
                for page in paginator.paginate(Path=root + Path, **kwargs):
                    for p in page["Parameters"]:
                        p["Name"] = p["Name"][len(root) :]
                    yield page

        return Paginator()


def _param(ssm, name, value):
    ssm.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True)


def test_verify_compares_parameters_by_digest_and_ignores_whatsapp(ssm):
    _param(ssm, "/bgucats/telegram/bot-token", "token")
    _param(ssm, "/bgucats/submitter-hash-salt", "salt")
    _param(ssm, "/bgucats/whatsapp/app-secret", "left-behind")
    _param(ssm, "/dst/bgucats/telegram/bot-token", "token")
    _param(ssm, "/dst/bgucats/submitter-hash-salt", "salt\n")
    src, dst = m.ReadOnly(Prefixed(ssm, "")), Prefixed(ssm, "/dst")

    result = m.compare_parameters(m.parameter_values(src), m.parameter_values(dst))

    # A trailing newline is a different salt.
    assert result == {
        "/bgucats/submitter-hash-salt": "differ",
        "/bgucats/telegram/bot-token": "same",
    }
