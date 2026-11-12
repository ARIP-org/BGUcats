"""The made-up campus staging is filled with (scripts/seed_campus.py), run
here against the local app: the same calls, no AWS."""

from seed_campus import CATS, PEOPLE, Campus

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
        # Six cats with 2 + 3 photos each, and one encounter of 2 for each
        # person; four encounters of 2 in the queue.
        assert stats["photos"] == {
            "labeled": 30 + 2 * len(PEOPLE),
            "unlabeled": 8,
            "pending": 0,
            "duplicate": 0,
        }
        assert said[0] == f"  {CATS[0]}: 1 encounter(s) added"
        first_run = len(CATS) + 1 + len(PEOPLE)
        assert said[first_run:] == (
            [f"  {name}: complete already" for name in CATS]
            + ["  queue: 4 waiting already, 0 added"]
            + [f"  {email.split('@')[0]}: posted already" for email in PEOPLE]
        )

        # Each person's post is in the feed, liked by the others.
        _, feed = app.api("GET", "/api/v1/feed", email=ADMIN)
        assert len(feed["cards"]) == len(PEOPLE)
        assert {card["likes"] for card in feed["cards"]} == {len(PEOPLE) - 1}
