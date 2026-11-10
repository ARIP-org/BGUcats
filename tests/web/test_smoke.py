"""The smoke test staging gets after every deploy (scripts/smoke_staging.py),
run here against the local app: the same six steps, no AWS."""

import pytest

from smoke_staging import SmokeFailure, run

from .localapp import ADMIN, COLLABORATOR, LocalApp


@pytest.fixture
def app():
    with LocalApp() as local:
        local.seed()
        yield local


def stored(app):
    return app.s3.list_objects_v2(Bucket=app.bucket)["KeyCount"]


def test_the_smoke_test_passes_and_leaves_nothing_behind(app):
    _, stats = app.api("GET", "/api/stats")
    objects = stored(app)
    said = []
    run(app.api, ADMIN, COLLABORATOR, say=said.append)
    assert len(said) == 6
    assert app.api("GET", "/api/stats")[1] == stats
    assert stored(app) == objects


def test_the_smoke_test_says_what_is_wrong(app):
    # Roles not enforced: the collaborator is made an admin behind its back.
    app.api("PATCH", f"/api/admins/{COLLABORATOR}", {"role": "admin"})
    with pytest.raises(SmokeFailure, match="a collaborator got the queue"):
        run(app.api, ADMIN, COLLABORATOR, say=lambda _: None)
    # And it still cleaned up after itself.
    _, queue = app.api("GET", "/api/queue")
    assert len(queue["sessions"]) == 2


def test_the_smoke_test_needs_the_seeded_members():
    with LocalApp() as empty, pytest.raises(SmokeFailure, match="make seed-staging"):
        run(empty.api, ADMIN, COLLABORATOR, say=lambda _: None)
