"""Which issues the builder starts on now.

`.github/workflows/claude-fix.yml` runs this before any Claude does. The
queue is the open issues labeled `approved` (the owner's word) or `ready`
(cut by the planner, or by anyone who can push). This script decides which
of them start, and moves their labels: the one it takes loses its queue
label and gets `building`.

It decides from who put a label on and who opened the issue, never from
what an issue says. Nothing here reads an issue's text, and no model runs.

What holds:

- `approved` counts only from a repository admin. `ready` counts only from
  someone who can push, on an issue opened by someone who can push.
- A label put on by a workflow's own token or by an App counts for nothing,
  so the builder and the triage, which act as those, cannot hand
  themselves or each other work. The bot account can: it is a user who can
  push, the planner acts as it, and cutting `ready` issues is the
  planner's job. That is the design, not a gap in it.
- At most `LIMIT` pieces of agent work at once: this repository's open
  pull requests from `claude/` branches, plus issues being built that have
  no pull request yet. The rest wait in the queue; nothing is dropped.
- An issue marked `building` with no open pull request and nothing moving
  for `STALE_HOURS` goes to the owner (`needs-owner`) and frees its place.
- An issue whose pull request is already open is never built a second
  time, whatever label it carries: its queue label becomes `building`.
- A pull request of the builder's that the reviewer sent back goes to the
  builder again, `ROUNDS` times at most; after that it is the owner's.
  Only the reviewer's own status counts (written as GitHub Actions), and
  a pull request being reworked is marked so, so it is handed out once.
- So does one that no longer merges with main. GitHub runs no check on
  a pull request in conflict, so nothing would ever look at it again: on
  2026-11-24 three were built at once on the same files, the first
  merged, and the other two stood still. The same two rounds count for
  both reasons.

    REPO=owner/name GH_TOKEN=... python scripts/builder_queue.py

prints what it did and writes to `$GITHUB_OUTPUT`: `issues=[...]` (the
numbers taken) and `rework=[{issue, pull, round, sha, why}, ...]` (pull
requests that go back to the builder; `why` is `review` or `conflict`).
"""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta

LIMIT = 3
STALE_HOURS = 3
QUEUE = ("approved", "ready")  # in the order they are taken
BUILDING = "building"
HELD = ("needs-owner", "proposal")  # never taken, whatever else they carry
CAN_PUSH = frozenset({"admin", "maintain", "write"})

# A sent-back review. The words are scripts/review_verdict.py's for the
# verdict `changes` (a test holds the two together), and the status must be
# the reviewer workflow's own.
SENT_BACK = "Reviewed: sent back to its author"
REVIEWER = "github-actions[bot]"
REWORKING = "reworking"
ROUNDS = 2
ISSUE_BRANCH = re.compile(r"^claude/issue-(\d+)$")


def branch(number):
    return f"claude/issue-{number}"


def _person(who, permission):
    """Their permission here, if a person put the label on; else None."""
    if not who or who.get("type") != "User" or not who.get("by"):
        return None
    return permission(who["by"])


def decide(issues, branches, labeled, permission, now, limit=LIMIT):
    """What to do with the queue, as data.

    issues: open issues, each {number, author, author_type, labels, updated}.
    branches: this repository's branches that have an open pull request.
    labeled(number, label): who last put that label on, {by, type}, or None.
    permission(login): "admin", "write", "read", "none"...

    Returns {take: [numbers], refuse: [{number, label, why}],
    stale: [numbers], wait: [numbers], built: [numbers]}. `built`: in the
    queue although its pull request is open; to be marked, not built.
    """
    ours = [name for name in branches if name.startswith("claude/")]
    stale, busy = [], len(ours)
    for issue in issues:
        if BUILDING not in issue["labels"] or branch(issue["number"]) in ours:
            continue
        if now - issue["updated"] > timedelta(hours=STALE_HOURS):
            stale.append(issue["number"])
        else:
            busy += 1  # being built: its pull request is not open yet

    take, refuse, wait, built = [], [], [], []
    for label in QUEUE:
        for issue in sorted(issues, key=lambda i: i["number"]):
            number, labels = issue["number"], issue["labels"]
            if label not in labels or BUILDING in labels or number in take or number in built:
                continue
            if any(held in labels for held in HELD):
                continue
            if branch(number) in ours:
                # Its pull request is open already (the label was put on
                # again, or is left from before there was a queue). A
                # second build would push to the same branch.
                built.append(number)
                continue
            who = labeled(number, label)
            by = (who or {}).get("by") or "nobody we can name"
            theirs = _person(who, permission)
            if label == "approved" and theirs != "admin":
                refuse.append(
                    {
                        "number": number,
                        "label": label,
                        "why": f"it was added by {by}, and only a repository admin's approval starts work.",
                    }
                )
                continue
            if label == "ready":
                if theirs not in CAN_PUSH:
                    refuse.append(
                        {
                            "number": number,
                            "label": label,
                            "why": f"it was added by {by}, who cannot push to this repository.",
                        }
                    )
                    continue
                author = {"by": issue["author"], "type": issue["author_type"]}
                if _person(author, permission) not in CAN_PUSH:
                    refuse.append(
                        {
                            "number": number,
                            "label": label,
                            "why": (
                                f"this issue was opened by {issue['author']}, who cannot push to this "
                                "repository. A repository admin can start it with `approved`."
                            ),
                        }
                    )
                    continue
            if busy < limit:
                take.append(number)
                busy += 1
            else:
                wait.append(number)
    return {"take": take, "refuse": refuse, "stale": stale, "wait": wait, "built": built}


def sent_back(pulls, review, rounds=ROUNDS):
    """Which of the builder's pull requests go back to the builder.

    pulls: this repository's open pull requests, each {number, ref, sha,
    labels} and, for the builder's, `conflict`: True when it no longer
    merges with main, None when GitHub has not worked that out yet.
    review(sha): the newest `review` status on that commit, {state,
    description, by}, or None.

    Returns {rework: [{issue, pull, round, sha, why}], owner: [numbers]}:
    `why` is "conflict" or "review"; `owner` are those that need the
    builder once more than it may answer.
    """
    rework, owner = [], []
    for pull in sorted(pulls, key=lambda p: p["number"]):
        built = ISSUE_BRANCH.match(pull["ref"])
        labels = pull["labels"]
        if not built or REWORKING in labels or "needs-owner" in labels:
            continue
        if pull.get("conflict") is True:
            # First: no check runs on a pull request in conflict, so what
            # the reviewer last said of it is about a commit that cannot
            # merge anyway.
            why = "conflict"
        else:
            said = review(pull["sha"]) or {}
            if (said.get("state"), said.get("description"), said.get("by")) != ("failure", SENT_BACK, REVIEWER):
                continue
            why = "review"
        done = sum(f"rework-{n}" in labels for n in range(1, rounds + 1))
        if done >= rounds:
            owner.append(pull["number"])
        else:
            rework.append(
                {"issue": int(built[1]), "pull": pull["number"], "round": done + 1, "sha": pull["sha"], "why": why}
            )
    return {"rework": rework, "owner": owner}


# ------------------------------------------------------------- GitHub


def gh(path, *args):
    done = subprocess.run(["gh", "api", path, *args], check=True, capture_output=True, text=True)
    return done.stdout


def lines(path, jq):
    """One JSON value per item, over every page."""
    out = gh(path, "--paginate", "--jq", jq)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def read(repo):
    found = {}
    for label in (*QUEUE, BUILDING):
        for issue in lines(
            f"repos/{repo}/issues?state=open&labels={label}&per_page=100",
            ".[] | select(.pull_request | not) | {number, author: .user.login, "
            "author_type: .user.type, labels: [.labels[].name], updated: .updated_at}",
        ):
            issue["updated"] = datetime.fromisoformat(issue["updated"])
            found[issue["number"]] = issue
    # A fork's branch can be named anything: only our own count.
    pulls = lines(
        f"repos/{repo}/pulls?state=open&per_page=100",
        f'.[] | select(.head.repo.full_name == "{repo}") '
        "| {number, ref: .head.ref, sha: .head.sha, labels: [.labels[].name]}",
    )
    for pull in pulls:
        if ISSUE_BRANCH.match(pull["ref"]):
            # The list does not say whether a pull request still merges;
            # each one's own page does: true, false, or null while GitHub
            # is still working it out (then it is asked again next time).
            said = gh(f"repos/{repo}/pulls/{pull['number']}", "--jq", ".mergeable").strip()
            pull["conflict"] = {"true": False, "false": True}.get(said)
    return list(found.values()), pulls


def review_of(repo):
    def review(sha):
        # Newest first; the first with our context is the one that stands.
        found = lines(
            f"repos/{repo}/commits/{sha}/statuses?per_page=100",
            '.[] | select(.context == "review") | {state, description, by: .creator.login}',
        )
        return found[0] if found else None

    return review


def labeled_by(repo):
    def labeled(number, label):
        events = lines(
            f"repos/{repo}/issues/{number}/events?per_page=100",
            '.[] | select(.event == "labeled") | {label: .label.name, by: .actor.login, type: .actor.type}',
        )
        mine = [event for event in events if event["label"] == label]
        return mine[-1] if mine else None

    return labeled


def permission_in(repo):
    known = {}

    def permission(login):
        if login not in known:
            try:
                known[login] = gh(f"repos/{repo}/collaborators/{login}/permission", "--jq", ".permission").strip()
            except subprocess.CalledProcessError:
                known[login] = "none"
        return known[login]

    return permission


def add(repo, number, label):
    # Adding a label that does not exist yet makes it.
    gh(f"repos/{repo}/issues/{number}/labels", "-X", "POST", "-f", f"labels[]={label}", "--silent")


def remove(repo, number, label):
    try:
        gh(f"repos/{repo}/issues/{number}/labels/{label}", "-X", "DELETE", "--silent")
    except subprocess.CalledProcessError:
        pass  # already off


def say(repo, number, text):
    gh(f"repos/{repo}/issues/{number}/comments", "-X", "POST", "-f", f"body={text}", "--silent")


def main():
    repo = os.environ["REPO"]
    issues, pulls = read(repo)
    branches = [pull["ref"] for pull in pulls]
    plan = decide(issues, branches, labeled_by(repo), permission_in(repo), datetime.now(UTC))
    back = sent_back(pulls, review_of(repo))
    labels = {issue["number"]: issue["labels"] for issue in issues}

    for item in plan["refuse"]:
        remove(repo, item["number"], item["label"])
        say(repo, item["number"], f"`{item['label']}` taken off: {item['why']}")
        print(f"::warning::#{item['number']}: {item['label']} refused: {item['why']}")
    for number in plan["stale"]:
        add(repo, number, "needs-owner")
        remove(repo, number, BUILDING)
        say(
            repo,
            number,
            f"Nothing came of the build: no pull request is open for this issue and nothing has moved for "
            f"{STALE_HOURS} hours. It waits for the owner (`needs-owner`). Take that label off and put "
            "`ready` or `approved` on again to start it once more.",
        )
        print(f"::warning::#{number}: marked building, with no pull request and nothing moving. Sent to the owner.")
    for number in plan["built"]:
        add(repo, number, BUILDING)
        for label in QUEUE:
            if label in labels[number]:
                remove(repo, number, label)
        print(f"::notice::#{number}: its pull request is open already. Marked building, not built again.")
    for number in plan["take"]:
        add(repo, number, BUILDING)
        for label in QUEUE:
            if label in labels[number]:
                remove(repo, number, label)
        print(f"::notice::#{number}: taken.")
    for number in plan["wait"]:
        print(f"::notice::#{number} waits: {LIMIT} pieces of agent work are open already.")
    for item in back["rework"]:
        add(repo, item["pull"], REWORKING)
        add(repo, item["pull"], f"rework-{item['round']}")
        what = "in conflict with main" if item["why"] == "conflict" else "sent back"
        print(f"::notice::Pull request #{item['pull']}: {what}, round {item['round']} of {ROUNDS}. To the builder.")
    for number in back["owner"]:
        add(repo, number, "needs-owner")
        say(
            repo,
            number,
            f"This needs the builder again after its {ROUNDS} answers: the reviewer sent it back once more, "
            "or it is in conflict with main. It waits for the owner (`needs-owner`).",
        )
        print(f"::warning::Pull request #{number}: needs the builder a third time. To the owner.")
    if not any(plan.values()) and not any(back.values()):
        print("Nothing in the queue.")

    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as out:
        out.write(f"issues={json.dumps(plan['take'])}\n")
        out.write(f"rework={json.dumps(back['rework'])}\n")


if __name__ == "__main__":
    sys.exit(main())
