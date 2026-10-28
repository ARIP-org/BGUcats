"""Admin Lambda: auth, routing, and what leaves the building.

Two properties matter beyond "the routes work": every API route refuses a
request without the admin token, and responses never carry a raw original or
the full submitter hash.
"""

import json
import logging
import os

os.environ.setdefault("TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("ADMIN_TOKEN_PARAM", "/bgucats/admin/token")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from botocore.config import Config
from moto import mock_aws
from ulid import ULID

from admin import handler
from tests.admin.conftest import Seeder, create_table

TOKEN = "t" * 48


@pytest.fixture
def api(monkeypatch):
    with mock_aws():
        table = create_table()
        s3 = boto3.client(
            "s3", region_name="us-east-1", config=Config(signature_version="s3v4")
        )
        s3.create_bucket(Bucket=os.environ["MEDIA_BUCKET"])
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(
            Name=os.environ["ADMIN_TOKEN_PARAM"], Value=TOKEN, Type="SecureString"
        )
        monkeypatch.setattr(handler, "table", table)
        monkeypatch.setattr(handler, "s3", s3)
        monkeypatch.setattr(handler, "ssm", ssm)
        monkeypatch.setattr(handler, "_token_cache", None)
        yield Seeder(table)


def call(method, path, body=None, token=TOKEN, query=None):
    event = {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"Authorization": f"Bearer {token}"} if token else {},
        "queryStringParameters": query,
    }
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    response = handler.handler(event, None)
    content_type = response["headers"]["content-type"]
    data = json.loads(response["body"]) if "json" in content_type else response["body"]
    return response["statusCode"], data


def new_cat(**fields):
    fields = {"coatColor": "black", "coatPattern": "solid", **fields}
    status, body = call(
        "POST", "/admin/api/cats", {"catId": str(ULID()), "fields": fields}
    )
    assert status == 201, body
    return body


class TestAuth:
    def test_page_needs_no_token(self, api):
        status, body = call("GET", "/admin", token=None)
        assert status == 200
        assert isinstance(body, str)

    @pytest.mark.parametrize("token", [None, "wrong", ""])
    def test_api_refuses_a_missing_or_wrong_token(self, api, token):
        assert call("GET", "/admin/api/queue", token=token)[0] == 401

    def test_bearer_prefix_is_required(self, api):
        event = {
            "rawPath": "/admin/api/queue",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"authorization": TOKEN},
        }
        assert handler.handler(event, None)["statusCode"] == 401

    def test_the_token_is_never_logged(self, api, caplog):
        caplog.set_level(logging.INFO)
        call("GET", "/admin/api/queue")
        call("GET", "/admin/api/queue", token="wrong")
        assert TOKEN not in caplog.text


class TestPageSecurity:
    def headers(self, api):
        event = {"rawPath": "/admin", "requestContext": {"http": {"method": "GET"}}}
        return handler.handler(event, None)["headers"]

    def test_only_the_pages_own_script_may_run(self, api):
        import base64
        import hashlib
        import re

        csp = self.headers(api)["content-security-policy"]
        script = re.search(r"<script>(.*?)</script>", handler.PAGE, re.DOTALL).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"script-src 'sha256-{digest}'" in csp
        assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
        assert "default-src 'none'" in csp

    def test_images_only_from_where_presigned_urls_point(self, api):
        csp = self.headers(api)["content-security-policy"]
        img = csp.split("img-src ")[1].split(";")[0]
        assert img.startswith("https://") and "amazonaws.com" in img
        assert " " not in img.strip()

    def test_signed_urls_are_not_leaked_by_referrer(self, api):
        assert self.headers(api)["referrer-policy"] == "no-referrer"


class TestRouting:
    def test_unknown_route(self, api):
        assert call("GET", "/admin/api/nope")[0] == 404

    def test_wrong_method(self, api):
        assert call("DELETE", "/admin/api/queue")[0] == 405

    def test_outside_admin(self, api):
        assert call("GET", "/webhook/telegram")[0] == 404

    def test_bad_json(self, api):
        sid, _ = api.session()
        assert call("POST", f"/admin/api/sessions/{sid}/assign", body="{nope")[0] == 400

    def test_ids_in_the_path_must_be_ulids(self, api):
        status, body = call("GET", "/admin/api/sessions/X#Y")
        assert status == 400
        assert "ULID" in body["error"]

    def test_bad_cursor(self, api):
        assert call("GET", "/admin/api/queue", query={"cursor": "garbage"})[0] == 400

    def test_store_errors_map_to_status_codes(self, api):
        assert call("GET", f"/admin/api/cats/{ULID()}")[0] == 404
        a, b, c = new_cat(), new_cat(), new_cat()
        call("POST", f"/admin/api/cats/{b['catId']}/merge", {"intoCatId": a["catId"]})
        conflict = call(
            "POST", f"/admin/api/cats/{c['catId']}/merge", {"intoCatId": b["catId"]}
        )
        assert conflict[0] == 409


class TestQueueAndSession:
    def test_queue_lists_sessions_with_thumbnails(self, api):
        sid, _ = api.session(photos=3)
        status, body = call("GET", "/admin/api/queue")
        assert status == 200
        assert body["queueSize"] == 3
        entry = body["sessions"][0]
        assert entry["session"]["sessionId"] == sid
        assert entry["unlabeledCount"] == 3
        assert "derived/" in entry["preview"][0]["thumb"]

    def test_urls_point_at_derivatives_never_raw_originals(self, api):
        sid, _ = api.session(photos=2)
        _, body = call("GET", f"/admin/api/sessions/{sid}")
        for photo in body["photos"]:
            for url in (photo["thumb"], photo["medium"]):
                assert "/derived/" in url and "/raw/" not in url

    def test_unprocessed_photos_get_no_url(self, api):
        sid, photos = api.session(photos=1)
        api.table.update_item(
            Key={"PK": f"PHOTO#{photos[0]}", "SK": "META"},
            UpdateExpression="REMOVE processedAt",
        )
        _, body = call("GET", f"/admin/api/sessions/{sid}")
        assert body["photos"][0]["processed"] is False
        assert body["photos"][0]["thumb"] is None

    def test_the_full_submitter_hash_is_never_sent(self, api):
        sid, _ = api.session()
        _, body = call("GET", f"/admin/api/sessions/{sid}")
        assert "submitterHash" not in body["session"]
        assert body["session"]["submitter"] == "a" * 6
        _, queue = call("GET", "/admin/api/queue")
        assert "a" * 64 not in json.dumps(queue)


class TestLabellingFlow:
    def test_assign_then_the_queue_empties_and_the_cat_counts(self, api):
        sid, _ = api.session(photos=3)
        cat = new_cat(displayName="Shadow")
        status, result = call(
            "POST", f"/admin/api/sessions/{sid}/assign", {"catId": cat["catId"]}
        )
        assert status == 200
        assert result["labeled"] == 3

        _, queue = call("GET", "/admin/api/queue")
        assert queue["sessions"] == [] and queue["queueSize"] == 0

        _, cats = call("GET", "/admin/api/cats")
        shown = cats["cats"][0]
        assert shown["photoCount"] == 3 and isinstance(shown["photoCount"], int)
        assert shown["coverage"]["usable"] is False
        assert shown["thumb"]

        _, session = call("GET", f"/admin/api/sessions/{sid}")
        assert session["cat"]["displayName"] == "Shadow"

    def test_cat_detail_groups_photos_by_session(self, api):
        cat = new_cat()
        for _ in range(2):
            sid, _ = api.session(photos=2)
            call("POST", f"/admin/api/sessions/{sid}/assign", {"catId": cat["catId"]})
        _, body = call("GET", f"/admin/api/cats/{cat['catId']}")
        assert [len(s["photos"]) for s in body["sessions"]] == [2, 2]

    def test_reject_and_restore_photos(self, api):
        _, photos = api.session(photos=2)
        path = "/admin/api/photos/reject"
        assert call("POST", path, {"photoIds": [photos[0]], "reason": "blurry"})[1] == {
            "rejected": 1
        }
        assert call("GET", "/admin/api/queue")[1]["queueSize"] == 1
        call("POST", "/admin/api/photos/restore", {"photoIds": [photos[0]]})
        assert call("GET", "/admin/api/queue")[1]["queueSize"] == 2

    def test_photo_id_list_is_bounded(self, api):
        status, _ = call("POST", "/admin/api/photos/reject", {"photoIds": []})
        assert status == 400

    def test_update_cat(self, api):
        cat = new_cat()
        status, body = call(
            "PATCH",
            f"/admin/api/cats/{cat['catId']}",
            {"fields": {"displayName": "Mitzi"}},
        )
        assert status == 200 and body["displayName"] == "Mitzi"

    def test_validation_errors_are_explained(self, api):
        status, body = call(
            "POST",
            "/admin/api/cats",
            {"fields": {"coatColor": "plaid", "coatPattern": "x"}},
        )
        assert status == 400
        assert "coatColor" in body["error"]

    def test_catalogue_publishes_the_spec_vocabulary(self, api):
        _, body = call("GET", "/admin/api/cats")
        assert "calico" in body["coatColors"]
        assert body["targets"]["sessions"]["floor"] == 3
