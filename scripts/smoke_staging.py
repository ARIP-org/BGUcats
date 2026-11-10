"""After every deploy to staging: does the app still do what it is for?

One photo goes through the deployed pipeline and is cleaned up again:

1. the seed's admin is still an admin (`/api/me`), and the cats are there;
2. a collaborator opens an encounter and uploads a photo, the way a phone
   does: the record, the presigned upload to the bucket, the confirmation;
3. S3 starts the process Lambda, and the photo comes out measured;
4. the encounter is in the admin's queue, and its thumbnail can really be
   fetched with the URL the API signed;
5. the collaborator is refused the queue (roles are enforced by the API,
   not by what the app hides);
6. the admin deletes the encounter, and it is gone from the queue.

It talks to the API the way scripts/seed_campus.py does: the deployed
admin Lambda is invoked with the event API Gateway would hand it. That
skips API Gateway and sign-in, which the deploy job checks separately from
outside ("the front door answers"), and it is why this needs no password
and no Google account.

**Staging only.** Production never gets a made-up photo. The role the
deploy job runs this under exists in the staging account alone
(infra/bootstrap/smoke_role.tf), and staging_session() refuses any other
account.

    AWS_PROFILE=bgucats-staging-admin python scripts/smoke_staging.py

Run `make seed-staging` once before the first run: the smoke test acts as
the two members the seed made.
"""

import sys
import time

import urllib3

from seed_campus import (
    SEED_ADMIN,
    SEED_COLLABORATOR,
    Campus,
    staging_api,
    staging_session,
)


class SmokeFailure(Exception):
    pass


def check(condition, what):
    if not condition:
        raise SmokeFailure(what)


def run(api, admin=SEED_ADMIN, collaborator=SEED_COLLABORATOR, say=print):
    """The six steps above. Raises SmokeFailure with what went wrong."""
    campus = Campus(api, admin, collaborator)
    http = urllib3.PoolManager()

    status, me = api("GET", "/api/me", None, admin)
    check(
        status == 200 and me.get("role") == "admin",
        f"GET /api/me as {admin} answered {status} {me}. On staging: run `make seed-staging` once.",
    )
    status, cats = api("GET", "/api/cats", None, admin)
    check(
        status == 200 and cats["cats"],
        f"no cats: GET /api/cats answered {status} {cats}",
    )
    say(f"1. signed-in admin, {len(cats['cats'])} cats")

    # A different picture every run: an exact copy of a stored photo would,
    # rightly, be marked a duplicate.
    session_id = campus.add_encounter(photos=1, seed=int(time.time()))
    say(f"2. encounter {session_id}: record, upload, confirmation")

    try:
        campus.wait_until_processed(session_id)
        say("3. the process Lambda measured the photo")

        status, queue = api("GET", "/api/queue", None, admin)
        check(status == 200, f"GET /api/queue answered {status} {queue}")
        mine = [s for s in queue["sessions"] if s["session"]["sessionId"] == session_id]
        check(mine, "the new encounter is not in the queue")
        photo = mine[0]["photos"][0]
        check(
            photo["status"] == "unlabeled", f"the photo's status is {photo['status']}"
        )
        thumb = http.request("GET", photo["thumbUrl"])
        check(
            thumb.status == 200 and thumb.headers.get("content-type") == "image/webp",
            f"the thumbnail's signed URL answered {thumb.status} {thumb.headers.get('content-type')}",
        )
        say(f"4. in the queue, thumbnail fetched ({len(thumb.data)} bytes)")

        status, refused = api("GET", "/api/queue", None, collaborator)
        check(status == 403, f"a collaborator got the queue: {status} {refused}")
        say("5. a collaborator is refused the queue")
    finally:
        # Whatever failed, do not leave the made-up encounter behind.
        status, deleted = api("POST", f"/api/sessions/{session_id}/reject", None, admin)

    check(status == 200, f"deleting the encounter answered {status} {deleted}")
    status, queue = api("GET", "/api/queue", None, admin)
    left = [s for s in queue["sessions"] if s["session"]["sessionId"] == session_id]
    check(not left, "the deleted encounter is still in the queue")
    say("6. deleted again, queue as before")


def main():
    api = staging_api(staging_session())
    try:
        run(api)
    except (SmokeFailure, RuntimeError) as failure:
        sys.exit(f"SMOKE TEST FAILED: {failure}")
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
