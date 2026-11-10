"""A made-up campus of cats, put in through the app's own API.

Two uses of one piece of code:

- the browser tests (tests/web) fill their local app with `Campus.small()`;
- **staging** is filled with `Campus.full()`:

      make seed-staging        # needs: aws sso login --profile bgucats-staging-admin

Nothing is written to the table or the bucket directly, except the one
member row every environment starts from. Each cat, encounter and photo
goes the way a phone sends it: the encounter's record, a presigned upload
to storage, the confirmation, and then the label an admin gives. On
staging that means the deployed admin Lambda is invoked with the event API
Gateway would hand it, the photo is posted to the real bucket, and the
real process Lambda is started by S3's own event. So a seed that finishes
is also proof that staging's whole pipeline works.

The photos are generated: flat coloured shapes, one colour per cat. Staging
never holds a contributor's photo (CLAUDE.md).

**Staging only.** The command line refuses any profile that is not a
staging one and any account other than the one in
infra/main/backend/staging.hcl.
"""

import argparse
import colorsys
import io
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import urllib3
from PIL import Image, ImageDraw
from ulid import ULID

REPO = Path(__file__).resolve().parents[1]

# Addresses nobody can sign in with: .invalid is reserved and Google will
# never vouch for one. They exist as callers of the API, not as accounts.
SEED_ADMIN = "seed-admin@bgucats.invalid"
SEED_COLLABORATOR = "seed-collaborator@bgucats.invalid"

CATS = ("Mitzi", "Shunra", "Pilpel", "Gingi", "Luna", "Kotik")


def sample_photo(seed, size=(1200, 900), cat=None):
    """A JPEG that is clearly not a cat: flat shapes, different per seed.

    With `cat` (a number) the colours belong to that cat, so its photos
    look alike and unlike another cat's, which is all a made-up identity
    needs. The process Lambda only needs something Pillow can decode.
    """
    if cat is None:
        palette = [(214, 122, 61), (63, 94, 135), (96, 140, 88), (150, 84, 140)]
        background = palette[seed % len(palette)]
    else:
        hue = (cat * 0.17) % 1.0
        palette = [
            tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, light, 0.55))
            for light in (0.35, 0.5, 0.65, 0.8)
        ]
        background = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, 0.2, 0.4))
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    for i in range(6):
        x = (seed * 97 + i * 173) % (size[0] - 300)
        y = (seed * 61 + i * 131) % (size[1] - 300)
        colour = palette[(seed + i + 1) % len(palette)]
        draw.ellipse([x, y, x + 180 + 20 * i, y + 180 + 20 * i], fill=colour)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def gateway_event(method, path, body=None, email=None, query=None):
    """The event API Gateway hands the admin Lambda, after its authorizer
    has verified the caller's token and read the email from it."""
    return {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"email": email}}},
        },
        "queryStringParameters": query or None,
        "body": json.dumps(body) if body is not None else None,
    }


class Campus:
    """Fills an environment through `api(method, path, body, email)`, which
    returns (status, json): the local app's, or staging's Lambda."""

    def __init__(self, api, admin, collaborator):
        self.api = api
        self.admin = admin
        self.collaborator = collaborator
        self._http = urllib3.PoolManager()
        self._salt = 0

    def _ok(self, method, path, body=None, email=None):
        status, out = self.api(method, path, body, email or self.admin)
        if status != 200:
            raise RuntimeError(f"{method} {path} answered {status}: {out}")
        return out

    def add_member(self, email, role="collaborator"):
        self._ok("POST", "/api/admins", {"email": email, "role": role})

    def add_cat(self, name):
        return self._ok("POST", "/api/cats", {"name": name})["catId"]

    def add_encounter(self, photos=2, seed=0, cat=None):
        """An encounter with photos, through the same three calls the phone
        makes for each: the record, the upload to storage, the confirmation."""
        who = self.collaborator
        session_id = str(ULID())
        self._ok("POST", "/api/encounters", {"sessionId": session_id}, who)
        for n in range(photos):
            photo_id = str(ULID())
            upload = self._ok(
                "POST",
                f"/api/encounters/{session_id}/media",
                {"photoId": photo_id, "contentType": "image/jpeg"},
                who,
            )["upload"]
            sent = self._http.request(
                "POST",
                upload["url"],
                fields={
                    **upload["fields"],
                    "file": (
                        "photo.jpg",
                        sample_photo(self._salt + seed * 10 + n, cat=cat),
                    ),
                },
            )
            if sent.status not in (200, 204):
                raise RuntimeError(f"upload refused ({sent.status}): {sent.data[:300]}")
            self._ok("POST", f"/api/photos/{photo_id}/complete", None, who)
        return session_id

    def label(self, session_id, cat_id):
        self._ok("POST", f"/api/sessions/{session_id}/assign", {"catId": cat_id})

    def wait_until_processed(self, session_id, timeout=90):
        """Until the process Lambda has measured every photo of the session.
        Where S3's event starts it, that takes a few seconds."""
        deadline = time.monotonic() + timeout
        while True:
            photos = self._ok("GET", f"/api/sessions/{session_id}")["photos"]
            if photos and all(p.get("width") for p in photos):
                return
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"session {session_id}: photos were stored but not processed "
                    f"within {timeout} s. Is the process Lambda being started?"
                )
            time.sleep(2)

    def small(self):
        """For the browser tests: three cats, two labeled encounters and two
        waiting in the queue."""
        self.add_member(self.collaborator)
        cats = {name: self.add_cat(name) for name in CATS[:3]}
        self.label(self.add_encounter(photos=3, seed=1), cats["Mitzi"])
        self.label(self.add_encounter(photos=2, seed=2), cats["Shunra"])
        queue = [
            self.add_encounter(photos=2, seed=3),
            self.add_encounter(photos=1, seed=4),
        ]
        return {"cats": cats, "queue": queue}

    def full(self, say=print):
        """For staging: six cats with two labeled encounters each, so every
        one of them counts as ready to evaluate, and four encounters left in
        the queue: three with known cats again and one with a stranger.

        It tops up rather than starts over: a cat that is there is kept, and
        only the encounters it lacks are added. So a run that stopped half
        way is finished by running it again, and a full campus is left alone.
        """
        # Not the same pictures as an earlier run's: an exact copy of a
        # stored photo is, rightly, marked a duplicate and kept out.
        self._salt = random.randrange(1, 10**6) * 100
        self.add_member(self.collaborator)
        known = {cat["name"]: cat for cat in self._ok("GET", "/api/cats")["cats"]}
        cats = {}
        for number, name in enumerate(CATS):
            cat = known.get(name)
            cats[name] = cat["catId"] if cat else self.add_cat(name)
            # Counted from the cat's photos, not from its stored photoCount:
            # that number is recounted through an index right after a label
            # and can be a moment behind (it was, on staging).
            photos = self._ok("GET", f"/api/cats/{cats[name]}")["photos"] if cat else []
            visits = len({photo["sessionId"] for photo in photos})
            # The first encounter has 2 photos, the second 3.
            missing = range(visits, 2)
            for visit in missing:
                session = self.add_encounter(
                    photos=2 + visit, seed=number * 10 + visit, cat=number
                )
                self.wait_until_processed(session)
                self.label(session, cats[name])
            added = (
                f"{len(missing)} encounter(s) added" if missing else "complete already"
            )
            say(f"  {name}: {added}")
        waiting = len(self._ok("GET", "/api/queue")["sessions"])
        strangers = (0, 2, 4, len(CATS))  # the last is a cat nobody has named
        queue = []
        for number in strangers[waiting:]:
            session = self.add_encounter(photos=2, seed=number * 10 + 7, cat=number)
            self.wait_until_processed(session)
            queue.append(session)
        say(f"  queue: {waiting} waiting already, {len(queue)} added")
        return {"cats": cats, "queue": queue}


# ------------------------------------------------------------------ staging


def _staging_account():
    text = (REPO / "infra/main/backend/staging.hcl").read_text()
    return re.search(r"bgucats-tfstate-(\d{12})", text).group(1)


def staging_session():
    """A boto3 session that is certainly staging, or the script stops.

    By hand it takes a bgucats-staging-* SSO profile. In GitHub Actions the
    job's role is the credentials and there is no profile. Either way the
    account must be the one infra/main/backend/staging.hcl names.
    """
    import boto3

    if os.environ.get("GITHUB_ACTIONS"):
        session = boto3.Session(region_name="us-east-1")
        who = "this job's role"
    else:
        profile = os.environ.get("AWS_PROFILE", "")
        if not profile.startswith("bgucats-staging-"):
            sys.exit(
                "Staging only. Run it with AWS_PROFILE=bgucats-staging-admin "
                f"(AWS_PROFILE is {profile or 'not set'})."
            )
        if os.environ.get("AWS_ACCESS_KEY_ID"):
            sys.exit("AWS_ACCESS_KEY_ID is set, and keys win over a profile. Unset it.")
        session = boto3.Session(profile_name=profile, region_name="us-east-1")
        who = f"profile {profile}"
    account = session.client("sts").get_caller_identity()["Account"]
    if account != _staging_account():
        sys.exit(
            f"{who} is account {account}, but staging is {_staging_account()} "
            "(infra/main/backend/staging.hcl). Nothing done."
        )
    return session


def staging_api(session):
    """api(method, path, body, email) against staging: the deployed admin
    Lambda, invoked with the event API Gateway would hand it."""
    functions = session.client("lambda")

    def api(method, path, body=None, email=SEED_ADMIN, query=None):
        event = gateway_event(method, path, body, email, query)
        answer = functions.invoke(
            FunctionName="bgucats-admin", Payload=json.dumps(event)
        )
        payload = json.loads(answer["Payload"].read())
        if "statusCode" not in payload:
            raise RuntimeError(f"bgucats-admin failed on {method} {path}: {payload}")
        return payload["statusCode"], json.loads(payload["body"])

    return api


def main():
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args()

    session = staging_session()
    api = staging_api(session)

    # The one direct write: the member the seed calls the API as. Every
    # environment starts from such a row (infra/main/cognito.tf).
    session.resource("dynamodb").Table("bgucats-data").put_item(
        Item={
            "PK": f"ADMIN#{SEED_ADMIN}",
            "SK": "META",
            "email": SEED_ADMIN,
            "addedAt": "seed",
            "addedBy": "scripts/seed_campus.py",
            "GSI2PK": "ENTITY#ADMIN",
            "GSI2SK": SEED_ADMIN,
        }
    )

    print("Seeding staging through its own API:")
    made = Campus(api, SEED_ADMIN, SEED_COLLABORATOR).full()
    print(f"Done: staging has {len(made['cats'])} cats.")


if __name__ == "__main__":
    main()
