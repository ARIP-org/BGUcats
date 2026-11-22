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
    assert plan == {"take": [], "refuse": [], "stale": [], "wait": []}


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
            ],
            "pulls": [
                {"head": {"ref": "claude/busy", "repo": {"full_name": "ARIP-org/BGUcats"}}},
                # A fork may name its branch anything; a deleted fork has no repo.
                {"head": {"ref": "claude/theirs", "repo": {"full_name": "stranger/BGUcats"}}},
                {"head": {"ref": "claude/gone", "repo": None}},
            ],
            "events": {
                "104": [labeled("ready", "arip-dev-bot")],
                "105": [labeled("ready", "arip-dev-bot")],
                # Put on by the bot, taken off, put on by the owner: the last one counts.
                "106": [labeled("approved", "arip-dev-bot"), labeled("enhancement", "x"), labeled("approved", "sasha")],
            },
        }
    )
    assert output == "issues=[106, 104]"
    changed = [(method, path, fields) for method, path, fields in calls if "comments" not in path]
    assert changed == [
        ("DELETE", f"{base}/105/labels/ready", []),
        ("POST", f"{base}/90/labels", ["labels[]=needs-owner"]),
        ("DELETE", f"{base}/90/labels/building", []),
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
    assert (output, calls) == ("issues=[]", [])
    assert "Nothing in the queue." in capsys.readouterr().out


def test_a_full_house_waits_and_changes_nothing(github, capsys):
    ours = {"repo": {"full_name": "ARIP-org/BGUcats"}}
    output, calls = github(
        {
            "issues": [api_issue(104, ["ready"])],
            "pulls": [{"head": {"ref": f"claude/issue-{n}", **ours}} for n in (1, 2, 3)],
            "events": {"104": [labeled("ready", "arip-dev-bot")]},
        }
    )
    assert (output, calls) == ("issues=[]", [])
    assert "#104 waits" in capsys.readouterr().out
