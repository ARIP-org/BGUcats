"""A failed screen test says what the app was doing.

The member-app fixture prints the app's own "App info" and the requests
that failed when its test fails (conftest.py). This runs a small failing
test in a pytest of its own and reads the report, because a diagnostic
that is only ever seen on the day it is needed has never been tried.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FAILING = '''
from tests.web.localapp import COLLABORATOR


def test_that_fails_on_purpose(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("[data-screen=frame]")
    page.evaluate("fetch('/api/v1/posts/not-a-post')")
    page.wait_for_timeout(300)
    assert False, "on purpose"
'''


def test_a_failed_member_test_reports_the_apps_own_account(tmp_path):
    inner = REPO / "tests" / "web" / "_inner_failure_test.py"
    inner.write_text(FAILING)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", str(inner), "-q", "-p", "no:cacheprovider"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        inner.unlink()
    out = done.stdout
    assert "1 failed" in out, out[-2000:]
    # The app's trail, with the steps of its start.
    assert "--- App info of http://127.0.0.1" in out
    assert "start: ready" in out
    # And the request the API refused.
    assert "--- Requests that failed or were refused" in out
    assert "GET http://127.0.0.1" in out and "/api/v1/posts/not-a-post" in out
