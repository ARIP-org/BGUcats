"""The made-up campus staging is filled with (scripts/seed_campus.py), run
here against the local app: the same calls, no AWS."""

from seed_campus import CATS, Campus

from .localapp import ADMIN, COLLABORATOR, LocalApp


def test_the_staging_campus_finishes_a_half_done_run_and_then_adds_nothing():
    with LocalApp() as app:
        app.add_first_admin()
        campus = Campus(app.api, ADMIN, COLLABORATOR)
        # A run that stopped after one cat's first encounter.
        campus.add_member(COLLABORATOR)
        campus.label(campus.add_encounter(photos=2, cat=0), campus.add_cat(CATS[0]))

        said = []
        campus.full(say=said.append)
        campus.full(say=said.append)

        _, stats = app.api("GET", "/api/stats")
        assert stats["cats"] == len(CATS)
        # Six cats with 2 + 3 photos each; four encounters of 2 in the queue.
        assert stats["photos"] == {
            "labeled": 30,
            "unlabeled": 8,
            "pending": 0,
            "duplicate": 0,
        }
        assert said[0] == f"  {CATS[0]}: 1 encounter(s) added"
        assert said[len(CATS) + 1 :] == [
            f"  {name}: complete already" for name in CATS
        ] + ["  queue: 4 waiting already, 0 added"]
