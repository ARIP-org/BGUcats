"""Run the labelling tool locally against a fake AWS, seeded by the real pipeline.

    PYTHONPATH=src python -m admin.local                      # synthetic photos
    PYTHONPATH=src python -m admin.local --photos DIR         # DIR/<encounter>/*.jpg

Starts moto in server mode (so presigned image URLs resolve in a browser),
creates the table with its three GSIs, the bucket and the admin token, then
seeds photos through the *real* ingest write functions and the *real* process
Lambda — so the tool is exercised on records shaped by the actual pipeline,
not on records shaped by what this file assumes. Each subfolder of --photos is
one encounter (one session); folders sharing a name prefix before "__" are
re-encounters of the same animal on different days.

Development only. Not packaged into the Lambda (see the Makefile), and it
imports the ingest and process handlers, which the admin Lambda never does.
"""

import argparse
import io
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

FAKE_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_REGION": "us-east-1",
    "TABLE_NAME": "bgucats-data-local",
    "MEDIA_BUCKET": "bgucats-media-local",
    "ADMIN_TOKEN_PARAM": "/bgucats/admin/token",
    "TELEGRAM_BOT_TOKEN_PARAM": "/bgucats/telegram/bot-token",
    "TELEGRAM_WEBHOOK_SECRET_PARAM": "/bgucats/telegram/webhook-secret",
    "SUBMITTER_HASH_SALT_PARAM": "/bgucats/submitter-hash-salt",
}


def synthetic_jpeg(seed):
    """A stand-in photo: a soft blob on a background, varied per seed."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(seed)
    w, h = 640, 480
    bg = tuple(rng.randint(60, 170) for _ in range(3))
    image = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(image)
    coat = tuple(rng.randint(20, 240) for _ in range(3))
    cx, cy = rng.randint(200, 440), rng.randint(180, 300)
    draw.ellipse([cx - 120, cy - 70, cx + 120, cy + 70], fill=coat)
    draw.ellipse([cx + 70, cy - 120, cx + 170, cy - 20], fill=coat)
    image = image.filter(ImageFilter.GaussianBlur(2))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def seed_encounter(ingest, process, s3, bucket, images, submitter_hash, when):
    """One encounter through the real write path: ingest's record writes in its
    own order (pending -> S3 -> unlabeled), then the process Lambda.

    `images` is a list of JPEG bytes. Returns (session_id, photo_ids).
    """
    from PIL import Image
    from ulid import ULID

    session_id = ingest._open_session(
        submitter_hash, media_group_id=None, explicit=False
    )
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    ingest.table.update_item(
        Key={"PK": f"SESSION#{session_id}", "SK": "META"},
        UpdateExpression="SET startedAt = :t, lastPhotoAt = :t",
        ExpressionAttributeValues={":t": stamp},
    )

    photo_ids = []
    for index, data in enumerate(images):
        photo_id = str(ULID())
        created = (when + timedelta(seconds=index * 7)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        ingest._write_pending_photo(
            photo_id=photo_id,
            session_id=session_id,
            submitter_hash=submitter_hash,
            captured_at=created,
            created_at=created,
        )
        key = f"raw/{session_id}/{photo_id}.jpg"
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/jpeg")
        width, height = Image.open(io.BytesIO(data)).size
        ingest._mark_photo_unlabeled(
            photo_id=photo_id,
            session_id=session_id,
            created_at=created,
            s3_key=key,
            content_type="image/jpeg",
            width=width,
            height=height,
        )
        ingest._bump_session(session_id)
        process._process_object(key)
        photo_ids.append(photo_id)

    # Live ingest stamps lastPhotoAt with the wall clock as each photo
    # arrives; seeding replays the past, so stamp it with the last photo's.
    if photo_ids:
        ingest.table.update_item(
            Key={"PK": f"SESSION#{session_id}", "SK": "META"},
            UpdateExpression="SET lastPhotoAt = :t",
            ExpressionAttributeValues={":t": created},
        )
    return session_id, photo_ids


def create_resources(token):
    import boto3

    ddb = boto3.client("dynamodb")
    attributes = ["PK", "SK"] + [f"GSI{n}{k}" for n in (1, 2, 3) for k in ("PK", "SK")]
    ddb.create_table(
        TableName=os.environ["TABLE_NAME"],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in attributes
        ],
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
            for n in (1, 2, 3)
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    boto3.client("s3").create_bucket(Bucket=os.environ["MEDIA_BUCKET"])
    boto3.client("ssm").put_parameter(
        Name=os.environ["ADMIN_TOKEN_PARAM"], Value=token, Type="SecureString"
    )


def encounters_from(photos_dir, per_encounter):
    """[(animal, [jpeg bytes, ...]), ...] from DIR/<animal>__<n>/*.jpg."""
    out = []
    for folder in sorted(p for p in Path(photos_dir).iterdir() if p.is_dir()):
        files = sorted(folder.glob("*.jp*g"))[:per_encounter]
        if files:
            animal = folder.name.split("__")[0]
            out.append((animal, [f.read_bytes() for f in files]))
    return out


def synthetic_encounters(n_animals=6, encounters_each=3, per_encounter=6):
    out = []
    for a in range(n_animals):
        for e in range(encounters_each):
            out.append(
                (
                    f"animal{a}",
                    [
                        synthetic_jpeg(a * 1000 + e * 100 + i)
                        for i in range(per_encounter)
                    ],
                )
            )
    return out


def seed(encounters, prelabel=0.4, seed_value=0):
    """Push every encounter through the pipeline, then pre-label a share of
    them so the catalogue is not empty and the queue holds re-encounters of
    cats that already exist — the common case once collection is running."""
    import boto3

    from admin import store
    from ingest import handler as ingest
    from process import handler as process

    s3 = boto3.client("s3")
    bucket = os.environ["MEDIA_BUCKET"]
    rng = random.Random(seed_value)
    start = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    order = list(range(len(encounters)))
    rng.shuffle(order)
    created = []
    for rank, i in enumerate(order):
        animal, images = encounters[i]
        when = start + timedelta(days=rank * 2, hours=rng.randint(0, 9))
        submitter = f"{rng.randrange(16**64):064x}"
        sid, _ = seed_encounter(ingest, process, s3, bucket, images, submitter, when)
        created.append((animal, sid))
        print(
            f"  seeded encounter {rank + 1}/{len(encounters)} ({len(images)} photos)",
            flush=True,
        )

    cats = {}
    for animal, sid in created:
        if animal in cats:
            if rng.random() < prelabel:
                store.assign_session(ingest.table, sid, cats[animal])
            continue
        if rng.random() < prelabel + 0.2:
            cat = store.create_cat(
                ingest.table,
                {
                    "displayName": animal.replace("_", " ").title(),
                    "coatColor": rng.choice(store.COAT_COLORS),
                    "coatPattern": rng.choice(store.COAT_PATTERNS),
                },
            )
            cats[animal] = cat["catId"]
            store.assign_session(ingest.table, sid, cat["catId"])
    return created


def serve(port):
    from admin import handler as admin

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self):
            parts = urlsplit(self.path)
            if parts.path in ("/", ""):
                self.send_response(302)
                self.send_header("Location", "/admin")
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else None
            event = {
                "rawPath": parts.path,
                "rawQueryString": parts.query,
                "queryStringParameters": dict(parse_qsl(parts.query)) or None,
                "headers": dict(self.headers),
                "body": body,
                "isBase64Encoded": False,
                "requestContext": {
                    "http": {"method": self.command, "path": parts.path}
                },
            }
            result = admin.handler(event, None)
            payload = result.get("body", "").encode()
            self.send_response(result["statusCode"])
            for k, v in result.get("headers", {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_DELETE = _dispatch

        def log_message(self, fmt, *args):
            sys.stderr.write("  " + (fmt % args) + "\n")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"\n  open http://127.0.0.1:{port}/admin", flush=True)
    server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--moto-port", type=int, default=5099)
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--photos", help="DIR of encounter subfolders")
    parser.add_argument("--per-encounter", type=int, default=8)
    args = parser.parse_args(argv)

    from moto.server import ThreadedMotoServer

    moto = ThreadedMotoServer(ip_address="127.0.0.1", port=args.moto_port)
    moto.start()
    os.environ.update(FAKE_ENV)
    # Every boto3 client created from here on — including the ones the
    # handlers create at import — talks to the local moto server.
    os.environ["AWS_ENDPOINT_URL"] = f"http://127.0.0.1:{args.moto_port}"

    create_resources(args.token)
    encounters = (
        encounters_from(args.photos, args.per_encounter)
        if args.photos
        else synthetic_encounters()
    )
    print(
        f"seeding {len(encounters)} encounters through ingest + process...", flush=True
    )
    seed(encounters)
    print(json.dumps({"token": args.token}))
    serve(args.port)


if __name__ == "__main__":
    main()
