"""The whole app on localhost, with no AWS: for the browser tests, and for
looking at a change before it is merged.

What runs is the real thing wherever it can be:

- `web/` is served as it is (the frontend has no build step);
- every `/api/` request is handed to the real `admin.handler`, and every
  `/api/v1/` request to the real member API, `app.handler`, in an event
  shaped like API Gateway's, with the email claim read from the token the
  page sent;
- after every request that writes, the changes to the app's table are
  handed to the real events Lambda, the way its stream does in AWS
  (tests/events/stream.py);
- DynamoDB and S3 are moto's server on a local port, so the presigned URLs
  the handler signs really work in the browser: photos load, and Capture's
  upload really lands in a bucket;
- each object that lands under `raw/` is given to the real `process.handler`,
  the way S3's event does in AWS.

What is faked: sign-in (the page gets a token nobody verified, as the API
Gateway authorizer would have) and the recognition model (not served, so
the app runs without it, as it must).

Run it by hand, seeded with a few cats and sessions:

    make local-app          # prints the address and how to sign in

Nothing here imports or reaches a real AWS account: the clients are given
moto's address and made-up keys explicitly.
"""

import base64
import contextlib
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("DATA_TABLE_NAME", os.environ["TABLE_NAME"])
os.environ.setdefault("SOCIAL_TABLE_NAME", "bgucats-social-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import logging

import boto3
import urllib3
from botocore.config import Config
from moto.server import ThreadedMotoServer

from admin import handler as admin_handler
from app import handler as app_handler
from events import handler as events_handler
from process import handler as process_handler
from seed_campus import Campus, gateway_event, sample_photo  # noqa: F401 (tests import it)
from tests.events.stream import Stream

WEB = Path(__file__).resolve().parents[2] / "web"

ADMIN = "admin@example.com"
COLLABORATOR = "collaborator@example.com"

CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def token_for(email):
    """What the page keeps after a sign-in: an ID token and when it expires.

    The token is shaped like a JWT and signed by nobody. In AWS the API
    Gateway authorizer verifies the signature before the handler runs; here
    the server below plays the authorizer and only reads the email.
    """

    def part(value):
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = ".".join([part({"alg": "none"}), part({"email": email}), "local"])
    return {"idToken": token, "expiresAt": int((time.time() + 86400) * 1000)}


def _email_from(authorization):
    try:
        payload = authorization.split(" ", 1)[1].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except (IndexError, ValueError, AttributeError):
        return None


class LocalApp:
    """Start with `with LocalApp() as app:`; `app.url` is the app's address."""

    def __init__(self):
        self._lock = threading.Lock()
        # config.json's frontDoor: "desk" as on staging today, or "app".
        self.front_door = "desk"
        self._processed = set()
        self._http = urllib3.PoolManager()

    # ------------------------------------------------------------------ AWS

    def _start_aws(self):
        # moto's server logs every request it answers.
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._moto = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
        self._moto.start()
        host, port = self._moto.get_host_and_port()
        self.aws_url = f"http://{host}:{port}"
        # moto keeps its tables and buckets for the whole process, whichever
        # server asks: start each app from nothing.
        self._http.request("POST", f"{self.aws_url}/moto-api/reset")
        self._processed.clear()
        made_up = {
            "endpoint_url": self.aws_url,
            "region_name": "us-east-1",
            "aws_access_key_id": "testing",
            "aws_secret_access_key": "testing",
        }
        self.s3 = boto3.client(
            "s3",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            **made_up,
        )
        dynamodb = boto3.resource("dynamodb", **made_up)

        self.bucket = admin_handler.MEDIA_BUCKET
        self.s3.create_bucket(Bucket=self.bucket)
        # The same rule as infra/main/s3.tf: the page may read a photo's
        # pixels (the model does) and post an upload.
        self.s3.put_bucket_cors(
            Bucket=self.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedMethods": ["GET", "POST"],
                        "AllowedOrigins": ["*"],
                        "AllowedHeaders": ["*"],
                    }
                ]
            },
        )
        # Both tables have the same keys and indexes (infra/main/dynamodb.tf,
        # social.tf); the stream is played by self.stream.
        keys = ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"]
        for name in (admin_handler.TABLE_NAME, app_handler.SOCIAL_TABLE_NAME):
            dynamodb.create_table(
                TableName=name,
                AttributeDefinitions=[
                    {"AttributeName": key, "AttributeType": "S"} for key in keys
                ],
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": index,
                        "KeySchema": [
                            {"AttributeName": f"{index}PK", "KeyType": "HASH"},
                            {"AttributeName": f"{index}SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                    for index in ("GSI1", "GSI2", "GSI3")
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        self.table = dynamodb.Table(admin_handler.TABLE_NAME)
        self.social = dynamodb.Table(app_handler.SOCIAL_TABLE_NAME)
        self.stream = Stream(self.social)

        # The handlers bind their clients and settings when they are
        # imported. Point them here for as long as this app runs, with the
        # app on as on staging, then put the originals back.
        self._patched = []
        for module, name, value in (
            (admin_handler, "table", self.table),
            (admin_handler, "s3", self.s3),
            (admin_handler, "social_table", self.social),
            (admin_handler, "SOCIAL", True),
            (process_handler, "table", self.table),
            (process_handler, "s3", self.s3),
            (app_handler, "data_table", self.table),
            (app_handler, "social_table", self.social),
            (app_handler, "s3", self.s3),
            (app_handler, "MEDIA_BUCKET", self.bucket),
            (app_handler, "SOCIAL", True),
            (app_handler, "FLAGS", {"social": True, "gpa": True, "achievements": True}),
            (events_handler, "social_table", self.social),
        ):
            self._patched.append((module, name, getattr(module, name)))
            setattr(module, name, value)

    def _stop_aws(self):
        for module, name, original in self._patched:
            setattr(module, name, original)
        self._moto.stop()

    # ------------------------------------------------------------- the API

    def api(self, method, path, body=None, email=ADMIN, query=None):
        """One API call, as API Gateway would deliver it. Returns (status, json).

        `/api/v1/` goes to the member API, the rest to the desk's, as the
        two routes in infra/main/app_api.tf and admin_api.tf divide them.
        The events Lambda has run by the time a write answers: in AWS it is
        a second or two behind, which the app never relies on.
        """
        event = gateway_event(method, path, body, email, query)
        target = app_handler if path.startswith("/api/v1/") else admin_handler
        with self._lock:
            if method == "GET":
                self._process_new_uploads()
            response = target.handler(event, None)
            if method != "GET":
                self._process_new_uploads()
                self.stream.settle()
        return response["statusCode"], json.loads(response["body"])

    def _process_new_uploads(self):
        """What S3's event does in AWS: each new raw/ object, once."""
        listing = self.s3.list_objects_v2(Bucket=self.bucket, Prefix="raw/")
        for entry in listing.get("Contents", []):
            key = entry["Key"]
            if key in self._processed:
                continue
            self._processed.add(key)
            process_handler.handler(
                {"Records": [{"s3": {"object": {"key": key}}}]}, None
            )

    # ----------------------------------------------------------- test data

    def add_first_admin(self, email=ADMIN):
        """The row infra/main/cognito.tf seeds, without which nobody could
        add anybody. No role field, which means admin."""
        self.table.put_item(
            Item={
                "PK": f"ADMIN#{email}",
                "SK": "META",
                "email": email,
                "GSI2PK": "ENTITY#ADMIN",
                "GSI2SK": email,
            }
        )

    def seed(self):
        """A small campus, put in through the API (scripts/seed_campus.py):
        two members, three cats, two labeled encounters, two in the queue."""
        self.add_first_admin()
        return Campus(self.api, ADMIN, COLLABORATOR).small()

    # ------------------------------------------------------ the web server

    def _start_web(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body, content_type, headers=()):
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(body)))
                self.send_header("cache-control", "no-store")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _send_api(self, status, payload):
                # API Gateway adds this to every answer, its own 401 too,
                # once the API has a CORS configuration (infra/main/api.tf).
                self._send(
                    status,
                    json.dumps(payload).encode(),
                    "application/json",
                    [("access-control-allow-origin", "*")],
                )

            def do_OPTIONS(self):
                """A web view's preflight, which the iPhone app's pages send
                because the API is not at their own address. It carries no
                token, and its route has no authorizer (admin_api.tf,
                app_api.tf; tests/native checks that), so API Gateway hands
                it to the route's Lambda and adds what api.tf allows to the
                answer. Until 2026-11-13 this stand-in answered 204 by
                itself, the real handlers answered 401, and every call from
                the iPhone app failed with "Load failed"."""
                path = urlsplit(self.path).path
                if not path.startswith("/api/"):
                    self._send(404, b"not found", "text/plain")
                    return
                member = path.startswith("/api/v1/")
                target = app_handler if member else admin_handler
                event = gateway_event("OPTIONS", path, None, None, None)
                answer = target.handler(event, None)
                self._send(
                    answer["statusCode"],
                    (answer.get("body") or "").encode(),
                    "application/json",
                    [
                        ("access-control-allow-origin", "*"),
                        ("access-control-allow-methods", "GET,POST,PUT,PATCH,DELETE"),
                        ("access-control-allow-headers", "authorization,content-type"),
                        ("access-control-max-age", "3600"),
                    ],
                )

            def _api(self):
                url = urlsplit(self.path)
                email = _email_from(self.headers.get("authorization"))
                if not email:
                    # What the JWT authorizer answers before any Lambda runs.
                    self._send_api(401, {"message": "Unauthorized"})
                    return
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length).decode() if length else None
                status, payload = app.api(
                    self.command,
                    url.path,
                    json.loads(raw) if raw else None,
                    email,
                    dict(parse_qsl(url.query)),
                )
                self._send_api(status, payload)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path.startswith("/api/"):
                    self._api()
                elif path == "/config.json":
                    # infra/main/web.tf writes this file in AWS.
                    config = {
                        "userPoolClientId": "local",
                        "cognitoDomain": "cognito.invalid",
                        "redirectUri": app.url + "/",
                        "siteUrl": "https://site.invalid/",
                        "botUrl": "https://t.me/example",
                        "frontDoor": app.front_door,
                    }
                    self._send(200, json.dumps(config).encode(), "application/json")
                else:
                    file = (WEB / (path.lstrip("/") or "index.html")).resolve()
                    if WEB not in file.parents or not file.is_file():
                        # Also the model's manifest: the app must work without it.
                        self._send(404, b"not found", "text/plain")
                        return
                    kind = (
                        CONTENT_TYPES.get(file.suffix)
                        or mimetypes.guess_type(file.name)[0]
                    )
                    self._send(
                        200, file.read_bytes(), kind or "application/octet-stream"
                    )

            do_POST = do_PUT = do_PATCH = do_DELETE = _api

        self._web = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._web.server_address[1]}"
        threading.Thread(target=self._web.serve_forever, daemon=True).start()

    def __enter__(self):
        self._start_aws()
        self._start_web()
        return self

    def __exit__(self, *exc):
        self._web.shutdown()
        self._web.server_close()
        self._stop_aws()


if __name__ == "__main__":
    with LocalApp() as local, contextlib.suppress(KeyboardInterrupt):
        local.seed()
        print(f"The app: {local.url}/?browser")
        print("Sign in by pasting this into the page's console, then reload:")
        for who in (ADMIN, COLLABORATOR):
            print(
                f"  localStorage['bgucats.tokens'] = '{json.dumps(token_for(who))}'  // {who}"
            )
        print("Ctrl+C stops it.")
        threading.Event().wait()
