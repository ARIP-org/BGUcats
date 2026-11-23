"""A made-up campus of cats, put in through the app's own API.

Two uses of one piece of code:

- the browser tests (tests/web) fill their local app with `Campus.small()`;
- **staging** is filled with `Campus.full()`:

      make seed-staging        # needs: aws sso login --profile bgucats-staging-admin

Nothing is written to the table or the bucket directly, except the one
member row every environment starts from. Each cat, encounter and photo
goes the way a phone sends it: the encounter's record, a presigned upload
to storage, the confirmation, and then the label an admin gives. Since
B3c, a few made-up people also open the member app (`/api/v1/`), answer
"Who did you meet?", post their encounter and like each other's posts. On
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

# Made-up people for the member app on staging: each meets one cat, says
# which, posts it, and likes the others' posts. (cat, words) per person.
PEOPLE = {
    "seed-maya@bgucats.invalid": ("Mitzi", "Asleep on the library steps again."),
    "seed-daniel@bgucats.invalid": ("Gingi", "Followed me all the way to the lab."),
    "seed-noa@bgucats.invalid": ("Luna", "Not sure, but I think this is Luna?"),
}
# What a pick says made the guess: seeded picks are never the model's.
SEED_MODEL = "seed-made-up"


# Enough for the largest seed there is: a salt below 10**8 plus ten times
# the clock, about 2**35 until the year 2500.
SEED_BITS = 48


def sample_photo(seed, size=(1200, 900), cat=None):
    """A JPEG that is clearly not a cat: flat shapes, different per seed.

    With `cat` (a number) the colours belong to that cat, so its photos
    look alike and unlike another cat's, which is all a made-up identity
    needs. The process Lambda only needs something Pillow can decode.

    Two seeds never give the same bytes. The shapes alone repeat every
    1,800 seeds, so the seed is also written along the bottom edge as a row
    of dark and light squares, one per bit. Without it the smoke test, which
    seeds its photo with the clock, now and then uploaded an exact copy of a
    seeded photo (in the tests, four seconds in every 180); a copy is a
    duplicate and leaves the queue.
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
    cell = 16
    for bit in range(SEED_BITS):
        x, y = bit * cell, size[1] - cell
        on = seed >> bit & 1
        draw.rectangle(
            [x, y, x + cell - 1, y + cell - 1],
            fill=(20, 20, 20) if on else (235, 235, 235),
        )
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

    def add_member(self, email, role="user"):
        self._ok("POST", "/api/admins", {"email": email, "role": role})

    def add_cat(self, name):
        return self._ok("POST", "/api/cats", {"name": name})["catId"]

    def add_encounter(self, photos=2, seed=0, cat=None, who=None):
        """An encounter with photos, through the same three calls the phone
        makes for each: the record, the upload to storage, the confirmation."""
        who = who or self.collaborator
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

    # ---------------------------------------------------- the member app

    def join(self, email):
        """A person opens the member app: the account is made by their
        first call, then they accept the terms."""
        me = self._ok("GET", "/api/v1/me", None, email)
        if me["terms"]["required"]:
            body = {"version": me["terms"]["current"]}
            me = self._ok("POST", "/api/v1/me/terms", body, email)
        return me

    def pick(self, session_id, cat_id, who):
        """The answer to "Who did you meet?", as Capture sends it."""
        self._ok(
            "POST",
            f"/api/encounters/{session_id}/pick",
            {
                "modelVersion": SEED_MODEL,
                "choice": "cat",
                "catId": cat_id,
                "shown": [cat_id],
                "ranked": [{"catId": cat_id, "score": 0.5}],
                "photoCount": 1,
            },
            who,
        )

    def post(self, session_id, cat_id, words, who):
        """The encounter, posted with its photos and a line of text."""
        photos = self._ok("GET", f"/api/sessions/{session_id}")["photos"]
        post_id = str(ULID())
        self._ok(
            "POST",
            "/api/v1/posts",
            {
                "postId": post_id,
                "sessionId": session_id,
                "photoIds": [p["photoId"] for p in photos],
                "claim": {"catId": cat_id},
                "text": words,
                "shareRegion": False,
            },
            who,
        )
        return post_id

    def like(self, post_id, who):
        self._ok("PUT", f"/api/v1/posts/{post_id}/like", None, who)

    def posts_of(self, email):
        return self._ok("GET", "/api/v1/me/posts", None, email)["cards"]

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
        waiting in the queue. The collaborator has opened the member app,
        said the first encounter was Mitzi and posted it; the admin liked it."""
        self.add_member(self.collaborator)
        self.join(self.collaborator)
        self.join(self.admin)
        cats = {name: self.add_cat(name) for name in CATS[:3]}
        first = self.add_encounter(photos=3, seed=1)
        self.pick(first, cats["Mitzi"], self.collaborator)
        post = self.post(
            first, cats["Mitzi"], "Asleep on the library steps.", self.collaborator
        )
        self.like(post, self.admin)
        self.label(first, cats["Mitzi"])
        self.label(self.add_encounter(photos=2, seed=2), cats["Shunra"])
        queue = [
            self.add_encounter(photos=2, seed=3),
            self.add_encounter(photos=1, seed=4),
        ]
        return {"cats": cats, "queue": queue, "posts": [post]}

    def people(self, cats, say=print):
        """For staging: PEOPLE open the app, each meets their cat, says so,
        posts it, and the others like it. A person who has a post already
        is left alone, so running it again adds nothing."""
        made = []
        for number, (email, (name, words)) in enumerate(PEOPLE.items()):
            self.add_member(email)
            self.join(email)
            if self.posts_of(email):
                say(f"  {email.split('@')[0]}: posted already")
                continue
            session = self.add_encounter(
                photos=2, seed=500 + number, cat=CATS.index(name), who=email
            )
            self.wait_until_processed(session)
            self.pick(session, cats[name], email)
            made.append((email, self.post(session, cats[name], words, email)))
            self.label(session, cats[name])
            say(f"  {email.split('@')[0]}: met {name} and posted it")
        for email, post in made:
            for other in PEOPLE:
                if other != email:
                    self.like(post, other)
        return made

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
        posts = self.people(cats, say=say)
        return {"cats": cats, "queue": queue, "posts": posts}


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


def function_for(path):
    """Which Lambda API Gateway hands a path to: `/api/v1/` is the member
    API's (infra/main/app_api.tf), the rest the desk's."""
    return "bgucats-app" if path.startswith("/api/v1/") else "bgucats-admin"


def staging_api(session):
    """api(method, path, body, email) against staging: the deployed Lambda
    for the path, invoked with the event API Gateway would hand it."""
    from botocore.exceptions import ClientError

    functions = session.client("lambda")

    def api(method, path, body=None, email=SEED_ADMIN, query=None):
        event = gateway_event(method, path, body, email, query)
        name = function_for(path)
        try:
            answer = functions.invoke(FunctionName=name, Payload=json.dumps(event))
        except ClientError as error:
            if error.response["Error"]["Code"] != "AccessDeniedException":
                raise
            raise RuntimeError(
                f"not allowed to invoke {name}. If it is bgucats-app: staging's "
                "bootstrap has not been applied since B3c (docs/MANUAL_STEPS.md, "
                "step 18)."
            ) from error
        payload = json.loads(answer["Payload"].read())
        if "statusCode" not in payload:
            raise RuntimeError(f"{name} failed on {method} {path}: {payload}")
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
