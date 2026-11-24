"""What the builder starts on (scripts/builder_queue.py).

The script is the wall between a label and a build: it runs before any
Claude does, and decides from who put the label on. `decide` is tested as
data. `main` is run against a stand-in for `gh` that answers with GitHub's
own shapes and runs the script's real filters through `jq`, and records
every change the script asks for.
"""

import importlib.util
import json
import os
import shutil
import stat
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("builder_queue", REPO / "scripts" / "builder_queue.py")
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
PEOPLE = {"owner": "admin", "bot": "write", "stranger": "read", "nobody": "none"}


def issue(number, *labels, author="bot", author_type="User", idle_hours=0):
    return {
        "number": number,
        "author": author,
        "author_type": author_type,
        "labels": list(labels),
        "updated": NOW - timedelta(hours=idle_hours),
    }


def decide(issues, branches=(), by=None, limit=3):
    """`by`: {(number, label): login or (login, type)}; the bot by default."""

    def labeled(number, label):
        who = (by or {}).get((number, label), "bot")
        if who is None:
            return None
        login, kind = who if isinstance(who, tuple) else (who, "User")
        return {"by": login, "type": kind}

    return queue.decide(issues, list(branches), labeled, lambda login: PEOPLE.get(login, "none"), NOW, limit)


# ----------------------------------------------------------------- who


def test_a_ready_issue_from_people_who_can_push_is_taken():
    assert decide([issue(104, "ready", "bug")])["take"] == [104]
    assert decide([issue(104, "ready", author="owner")], by={(104, "ready"): "owner"})["take"] == [104]


def test_approved_counts_only_from_an_admin():
    plan = decide([issue(7, "approved")], by={(7, "approved"): "bot"})
    assert plan["take"] == []
    assert plan["refuse"][0]["number"] == 7 and "only a repository admin" in plan["refuse"][0]["why"]
    # The owner's approval covers an issue anyone opened: they read it.
    plan = decide([issue(8, "approved", author="stranger")], by={(8, "approved"): "owner"})
    assert plan["take"] == [8]


def test_ready_on_a_strangers_issue_starts_nothing():
    # The planner is told to write its own issues. If it ever labels a
    # stranger's instead, the stranger's text must not reach the builder.
    plan = decide([issue(9, "ready", author="stranger")])
    assert plan["take"] == []
    assert "opened by stranger" in plan["refuse"][0]["why"]


def test_ready_from_someone_who_cannot_push_starts_nothing():
    plan = decide([issue(9, "ready")], by={(9, "ready"): "stranger"})
    assert plan["take"] == [] and "added by stranger" in plan["refuse"][0]["why"]


@pytest.mark.parametrize("label", ["approved", "ready"])
def test_a_label_from_a_workflow_or_an_app_counts_for_nothing(label):
    # The builder and the triage cannot hand themselves, or each other,
    # work: the job token and Claude's App are "Bot" to GitHub whatever
    # they may write. (The bot account is a user, and its `ready` counts:
    # that is the planner's job.)
    for who in (("github-actions[bot]", "Bot"), ("owner", "Bot"), None, (None, "User")):
        plan = decide([issue(5, label, author="owner")], by={(5, label): who})
        assert plan["take"] == [], who
        assert [item["number"] for item in plan["refuse"]] == [5], who


def test_an_issue_opened_by_an_app_is_not_ready_work():
    plan = decide([issue(5, "ready", author="owner", author_type="Bot")])
    assert plan["take"] == [] and plan["refuse"]


def test_what_waits_on_the_owner_is_never_taken():
    plan = decide([issue(1, "ready", "needs-owner"), issue(2, "approved", "proposal")], by={(2, "approved"): "owner"})
    assert plan == {"take": [], "refuse": [], "stale": [], "wait": [], "built": []}


# ------------------------------------------------------------- how many


def test_the_owners_word_goes_first_then_the_oldest():
    issues = [issue(30, "ready"), issue(10, "ready"), issue(20, "approved"), issue(40, "ready")]
    plan = decide(issues, by={(20, "approved"): "owner"})
    assert plan["take"] == [20, 10, 30] and plan["wait"] == [40]


def test_open_agent_pull_requests_take_places():
    issues = [issue(1, "ready"), issue(2, "ready")]
    plan = decide(issues, branches=["claude/issue-90", "claude/some-session", "feature/x"])
    assert plan["take"] == [1] and plan["wait"] == [2]
    assert decide(issues, branches=["claude/a", "claude/b", "claude/c"])["take"] == []


def test_an_issue_being_built_takes_a_place_once():
    # Its pull request is not open yet: the run is working.
    building = issue(50, "building", idle_hours=1)
    assert decide([building, issue(1, "ready"), issue(2, "ready"), issue(3, "ready")])["take"] == [1, 2]
    # Its pull request is open: counted as the pull request, not twice.
    plan = decide([building, issue(1, "ready"), issue(2, "ready"), issue(3, "ready")], branches=["claude/issue-50"])
    assert plan["take"] == [1, 2]


def test_a_build_that_came_to_nothing_goes_to_the_owner_and_frees_its_place():
    dead = issue(50, "building", idle_hours=queue.STALE_HOURS + 1)
    plan = decide([dead, issue(1, "ready"), issue(2, "ready"), issue(3, "ready")])
    assert plan["stale"] == [50] and plan["take"] == [1, 2, 3]
    # Not while its pull request is open, however long that takes.
    plan = decide([dead], branches=["claude/issue-50"])
    assert plan["stale"] == []


def test_an_issue_being_built_is_not_taken_again():
    plan = decide([issue(1, "building", "ready")])
    assert plan["take"] == []


def test_an_issue_whose_pull_request_is_open_is_never_built_again():
    # The reviewer's finding on this change: before there was a queue,
    # `approved` stayed on an issue after its build started, and anyone
    # can put a label on again. A second build would push to the same
    # branch. It is marked as what it is, and takes one place, not two.
    issues = [issue(7, "approved"), issue(8, "ready"), issue(9, "ready"), issue(10, "ready")]
    plan = decide(issues, branches=["claude/issue-7", "claude/issue-8"], by={(7, "approved"): "owner"})
    assert plan["built"] == [7, 8]
    assert plan["take"] == [9] and plan["wait"] == [10]
    # Whoever put the label on: nothing starts, so nothing is refused.
    plan = decide([issue(7, "approved")], branches=["claude/issue-7"], by={(7, "approved"): "stranger"})
    assert (plan["built"], plan["take"], plan["refuse"]) == ([7], [], [])


def test_nothing_is_taken_twice():
    plan = decide([issue(1, "approved", "ready")], by={(1, "approved"): "owner"})
    assert plan["take"] == [1]


# ---------------------------------------------------- against GitHub's shapes

GH = textwrap.dedent(
    '''\
    #!/usr/bin/env python3
    """A stand-in for `gh api`: answers from world.json, records writes."""
    import json, os, subprocess, sys
    from urllib.parse import urlsplit, parse_qs

    here = os.path.dirname(os.path.abspath(__file__))
    world = json.load(open(os.path.join(here, "world.json")))
    args = sys.argv[2:]  # after "api"
    path, method, jq, fields = args[0], "GET", None, []
    rest = args[1:]
    while rest:
        flag = rest.pop(0)
        if flag == "-X": method = rest.pop(0)
        elif flag == "--jq": jq = rest.pop(0)
        elif flag == "-f": fields.append(rest.pop(0))
    url = urlsplit(path)
    query = parse_qs(url.query)
    if method != "GET":
        with open(os.path.join(here, "calls.jsonl"), "a") as log:
            log.write(json.dumps([method, url.path, fields]) + "\\n")
        sys.exit(0)
    parts = url.path.split("/")
    if parts[-1] == "issues":
        label = query["labels"][0]
        body = [i for i in world["issues"] if label in [l["name"] for l in i["labels"]]]
    elif parts[-1] == "pulls":
        body = world["pulls"]
    elif parts[-2] == "pulls" and parts[-1].isdigit():
        # One pull request's own page: the only place that says whether
        # it still merges.
        body = next(p for p in world["pulls"] if p["number"] == int(parts[-1]))
    elif parts[-1] == "statuses":
        body = world.get("statuses", {}).get(parts[-2], [])
    elif parts[-1] == "events":
        body = world["events"].get(parts[-2], [])
    elif parts[-1] == "permission":
        who = parts[-2]
        if who not in world["people"]:
            sys.exit(1)  # 404
        body = {"permission": world["people"][who]}
    else:
        sys.exit(f"unexpected: {path}")
    if jq:
        # gh prints strings bare and everything else as one line of JSON.
        sys.stdout.write(subprocess.run(["jq", "-r", "-c", jq], input=json.dumps(body),
                                        capture_output=True, text=True, check=True).stdout)
    else:
        print(json.dumps(body))
    '''
)


def api_issue(number, labels, login="arip-dev-bot", kind="User", updated="2026-11-23T11:00:00Z", pull=False):
    found = {
        "number": number,
        "user": {"login": login, "type": kind},
        "labels": [{"name": name} for name in labels],
        "updated_at": updated,
    }
    if pull:
        found["pull_request"] = {"url": "..."}
    return found


def api_pull(number, ref, sha="aaa", labels=(), repo="ARIP-org/BGUcats", mergeable=True):
    return {
        "number": number,
        "labels": [{"name": name} for name in labels],
        "head": {"ref": ref, "sha": sha, "repo": {"full_name": repo} if repo else None},
        # true, false, or null while GitHub has not worked it out.
        "mergeable": mergeable,
    }


def api_status(state, description, login="github-actions[bot]", context="review"):
    return {"context": context, "state": state, "description": description, "creator": {"login": login}}


def labeled(label, login, kind="User"):
    return {"event": "labeled", "label": {"name": label}, "actor": {"login": login, "type": kind}}


@pytest.fixture
def github(tmp_path, monkeypatch):
    if not shutil.which("jq"):
        pytest.skip("needs jq, as the workflow's runner has")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(GH)
    (fake / "gh").chmod((fake / "gh").stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("REPO", "ARIP-org/BGUcats")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    def run(world):
        world.setdefault("people", {"sasha": "admin", "arip-dev-bot": "write"})
        (fake / "world.json").write_text(json.dumps(world))
        (fake / "calls.jsonl").write_text("")
        (tmp_path / "output").write_text("")
        queue.main()
        calls = [json.loads(line) for line in (fake / "calls.jsonl").read_text().splitlines()]
        return (tmp_path / "output").read_text().strip(), calls

    return run


def test_the_queue_is_read_from_github_and_the_labels_move(github, capsys):
    base = "repos/ARIP-org/BGUcats/issues"
    output, calls = github(
        {
            "issues": [
                api_issue(104, ["bug", "ready"]),
                api_issue(105, ["ready"], login="someone-else"),
                api_issue(106, ["approved", "enhancement"], login="someone-else"),
                # The issues API lists pull requests too: not an issue.
                api_issue(103, ["ready"], pull=True),
                api_issue(90, ["building"], updated="2026-11-01T00:00:00Z"),
                # Approved long ago, and its pull request is still open.
                api_issue(80, ["approved"]),
            ],
            "pulls": [
                api_pull(81, "claude/issue-80"),
                # A fork may name its branch anything; a deleted fork has no repo.
                api_pull(82, "claude/theirs", repo="stranger/BGUcats"),
                api_pull(83, "claude/gone", repo=None),
            ],
            "events": {
                "104": [labeled("ready", "arip-dev-bot")],
                "105": [labeled("ready", "arip-dev-bot")],
                # Put on by the bot, taken off, put on by the owner: the last one counts.
                "106": [labeled("approved", "arip-dev-bot"), labeled("enhancement", "x"), labeled("approved", "sasha")],
            },
        }
    )
    assert output == "issues=[106, 104]\nrework=[]"
    changed = [(method, path, fields) for method, path, fields in calls if "comments" not in path]
    assert changed == [
        ("DELETE", f"{base}/105/labels/ready", []),
        ("POST", f"{base}/90/labels", ["labels[]=needs-owner"]),
        ("DELETE", f"{base}/90/labels/building", []),
        ("POST", f"{base}/80/labels", ["labels[]=building"]),
        ("DELETE", f"{base}/80/labels/approved", []),
        ("POST", f"{base}/106/labels", ["labels[]=building"]),
        ("DELETE", f"{base}/106/labels/approved", []),
        ("POST", f"{base}/104/labels", ["labels[]=building"]),
        ("DELETE", f"{base}/104/labels/ready", []),
    ]
    said = {path.split("/")[-2]: fields[0] for method, path, fields in calls if path.endswith("/comments")}
    assert set(said) == {"105", "90"}
    assert "opened by someone-else" in said["105"] and "needs-owner" in said["90"]
    assert "#106: taken" in capsys.readouterr().out


def test_an_empty_queue_starts_nothing(github, capsys):
    output, calls = github({"issues": [], "pulls": [], "events": {}})
    assert (output, calls) == ("issues=[]\nrework=[]", [])
    assert "Nothing in the queue." in capsys.readouterr().out


def test_a_full_house_waits_and_changes_nothing(github, capsys):
    output, calls = github(
        {
            "issues": [api_issue(104, ["ready"])],
            "pulls": [api_pull(10 + n, f"claude/issue-{n}") for n in (1, 2, 3)],
            "events": {"104": [labeled("ready", "arip-dev-bot")]},
        }
    )
    assert (output, calls) == ("issues=[]\nrework=[]", [])
    assert "#104 waits" in capsys.readouterr().out


# ------------------------------------------------- sent back by the reviewer


def pull(number, ref, *labels, sha="aaa", conflict=False):
    return {"number": number, "ref": ref, "sha": sha, "labels": list(labels), "conflict": conflict}


def review(**by_sha):
    return lambda sha: by_sha.get(sha)


BACK = {"state": "failure", "description": queue.SENT_BACK, "by": queue.REVIEWER}


def test_the_words_for_sent_back_are_the_reviewers_own():
    # The queue knows a sent-back review by its description: the same
    # words the reviewer's script writes for the verdict `changes`.
    spec = importlib.util.spec_from_file_location("review_verdict", REPO / "scripts" / "review_verdict.py")
    verdicts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verdicts)
    assert verdicts.VERDICTS["changes"] == ("failure", queue.SENT_BACK)
    # The other two verdicts read differently, so neither is taken for it.
    assert queue.SENT_BACK not in (verdicts.VERDICTS["pass"][1], verdicts.VERDICTS["owner"][1])


def test_a_sent_back_pull_request_of_the_builders_goes_to_the_builder():
    back = queue.sent_back([pull(117, "claude/issue-104")], review(aaa=BACK))
    assert back == {
        "rework": [{"issue": 104, "pull": 117, "round": 1, "sha": "aaa", "why": "review"}],
        "owner": [],
    }
    # The second time is the second answer.
    back = queue.sent_back([pull(117, "claude/issue-104", "rework-1", sha="bbb")], review(bbb=BACK))
    assert back["rework"] == [{"issue": 104, "pull": 117, "round": 2, "sha": "bbb", "why": "review"}]


def test_a_pull_request_in_conflict_with_main_goes_to_the_builder_too():
    # 2026-11-24: three issues built at once on the same files. The first
    # merged; GitHub runs no check on the other two, so no review would
    # ever have sent them anywhere.
    nothing = review()
    back = queue.sent_back([pull(127, "claude/issue-123", conflict=True)], nothing)
    assert back == {
        "rework": [{"issue": 123, "pull": 127, "round": 1, "sha": "aaa", "why": "conflict"}],
        "owner": [],
    }
    # The conflict comes first: what the reviewer said is about a commit
    # that cannot merge anyway.
    both = queue.sent_back([pull(127, "claude/issue-123", conflict=True)], review(aaa=BACK))
    assert both["rework"][0]["why"] == "conflict"
    # Not known yet (GitHub is still working it out) is not a conflict.
    assert queue.sent_back([pull(127, "claude/issue-123", conflict=None)], nothing) == {"rework": [], "owner": []}
    # The same two rounds, whichever the reason; then it is the owner's.
    twice = pull(127, "claude/issue-123", "rework-1", "rework-2", conflict=True)
    assert queue.sent_back([twice], nothing) == {"rework": [], "owner": [127]}
    # A session's pull request in conflict is its session's to mend, and
    # one being answered now is not handed out again.
    others = [pull(1, "claude/busy-babbage", conflict=True), pull(3, "claude/issue-7", "reworking", conflict=True)]
    assert queue.sent_back(others, nothing) == {"rework": [], "owner": []}


def test_after_two_answers_it_is_the_owners():
    back = queue.sent_back([pull(117, "claude/issue-104", "rework-1", "rework-2")], review(aaa=BACK))
    assert back == {"rework": [], "owner": [117]}
    # And said once: with needs-owner on, it is left alone.
    back = queue.sent_back([pull(117, "claude/issue-104", "rework-1", "rework-2", "needs-owner")], review(aaa=BACK))
    assert back == {"rework": [], "owner": []}


def test_only_the_builders_own_pull_requests_and_only_once_at_a_time():
    pulls = [
        pull(1, "claude/busy-babbage"),  # a session's: its author answers
        pull(2, "feature/x"),
        pull(3, "claude/issue-7", "reworking"),  # being answered now
        pull(4, "claude/issue-8-extra"),
    ]
    assert queue.sent_back(pulls, lambda sha: BACK) == {"rework": [], "owner": []}


def test_only_the_reviewers_own_sent_back_counts():
    one = [pull(9, "claude/issue-5")]
    for said in (
        None,  # not reviewed yet
        {"state": "pending", "description": "Being reviewed", "by": queue.REVIEWER},
        {"state": "success", "description": "Reviewed: nothing for the owner to look at", "by": queue.REVIEWER},
        {"state": "failure", "description": "Reviewed: the owner should look at this", "by": queue.REVIEWER},
        {"state": "error", "description": "The review did not finish: see the run", "by": queue.REVIEWER},
        # The right words from anyone else: a status is a thing anyone who
        # can push may write.
        {**BACK, "by": "arip-dev-bot"},
    ):
        assert queue.sent_back(one, lambda sha, said=said: said) == {"rework": [], "owner": []}, said


def test_a_sent_back_pull_request_is_marked_and_handed_over(github, capsys):
    base = "repos/ARIP-org/BGUcats/issues"
    output, calls = github(
        {
            "issues": [api_issue(104, ["building"])],
            "pulls": [
                api_pull(117, "claude/issue-104", sha="abc"),
                api_pull(118, "claude/issue-105", sha="def", labels=["rework-1", "rework-2"]),
                api_pull(119, "claude/issue-106", sha="fff"),
            ],
            "events": {},
            "statuses": {
                # Newest first, as GitHub lists them: the last word stands.
                "abc": [
                    api_status("failure", queue.SENT_BACK),
                    api_status("pending", "Being reviewed"),
                    api_status("success", "x", context="something-else"),
                ],
                "def": [api_status("failure", queue.SENT_BACK)],
                "fff": [api_status("success", "Reviewed: nothing for the owner to look at")],
            },
        }
    )
    assert output == 'issues=[]\nrework=[{"issue": 104, "pull": 117, "round": 1, "sha": "abc", "why": "review"}]'
    changed = [(method, path, fields) for method, path, fields in calls if "comments" not in path]
    assert changed == [
        ("POST", f"{base}/117/labels", ["labels[]=reworking"]),
        ("POST", f"{base}/117/labels", ["labels[]=rework-1"]),
        ("POST", f"{base}/118/labels", ["labels[]=needs-owner"]),
    ]
    said = [fields[0] for method, path, fields in calls if path == f"{base}/118/comments"]
    assert len(said) == 1 and "waits for the owner" in said[0]
    assert "round 1 of 2" in capsys.readouterr().out


def test_a_conflicted_pull_request_is_found_on_its_own_page_and_handed_over(github, capsys):
    base = "repos/ARIP-org/BGUcats/issues"
    output, calls = github(
        {
            "issues": [],
            "pulls": [
                # No longer merges, and nobody reviewed it since: no check ran.
                api_pull(127, "claude/issue-123", sha="abc", mergeable=False),
                # GitHub has not worked it out yet: asked again next time.
                api_pull(128, "claude/issue-125", sha="def", mergeable=None),
                api_pull(130, "claude/issue-126", sha="fff"),
                # A session's: not the builder's to mend.
                api_pull(131, "claude/busy-babbage", sha="eee", mergeable=False),
            ],
            "events": {},
            "statuses": {},
        }
    )
    assert output == 'issues=[]\nrework=[{"issue": 123, "pull": 127, "round": 1, "sha": "abc", "why": "conflict"}]'
    assert calls == [
        ["POST", f"{base}/127/labels", ["labels[]=reworking"]],
        ["POST", f"{base}/127/labels", ["labels[]=rework-1"]],
    ]
    assert "#127: in conflict with main, round 1 of 2" in capsys.readouterr().out
