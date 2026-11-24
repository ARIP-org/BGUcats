"""The reviewer's verdict, read out of what the reviewer said.

`.github/workflows/claude-review.yml` lets Claude read a pull request and
nothing else: it cannot write a file or run a command. So its verdict is
the last JSON object in its final message, and this script is what turns
that message into the three things the workflow does next: a status on
the pull request's head, a comment, and whether to ask GitHub to merge.

It fails closed. A message with no verdict, a verdict that is not one of
the three, or no message at all is "owner": the pull request waits for a
person, and the comment says why. Nothing here trusts the message beyond
its shape, and nothing in it is ever run.

**A pull request that touches an owner path never passes here**, whatever
the reviewer said: given the pull request's diff and the CODEOWNERS file,
a "pass" on such a change becomes "owner". The paths are read from the
diff by this script, not judged by a model. The `main` ruleset is meant to
hold the same line ("Require review from Code Owners"); on 2026-11-23 it
did not, and #121, which changed a workflow, merged eight seconds after
the reviewer passed it, with nobody's approval. A rule kept in a setting
nobody here can read is checked here as well.

**Nor does one with another check red, or not finished.** The reviewer
starts when CI ends, and the iPhone app's checks (`ios.yml`) run beside CI,
not in it. On 2026-11-24 #126 merged with its Mac check failed and left
`main` unable to build for TestFlight, and #127 was passed with a compile
error. Given the check runs on the pull request's head, a "pass" becomes
"sent back", naming the check, when one of them failed; and "owner" when
one had not finished or they could not be read.

    python scripts/review_verdict.py <execution-log.json> <out-dir> \
        [<pr.diff> <CODEOWNERS> [<changed-file-count> [<checks.json>]]]

writes `verdict.json` (`verdict`, `state`, `description`) and `comment.md`.
"""

import fnmatch
import json
import re
import sys
from pathlib import Path

# verdict -> (the status GitHub shows, its one line)
VERDICTS = {
    "pass": ("success", "Reviewed: nothing for the owner to look at"),
    "changes": ("failure", "Reviewed: sent back to its author"),
    "owner": ("failure", "Reviewed: the owner should look at this"),
}
HEADINGS = {
    "pass": "Review: passed",
    "changes": "Review: sent back",
    "owner": "Review: for the owner",
}
MARKER = "<!-- claude-review -->"
MAX_FINDINGS = 20
MAX_TEXT = 1200


def final_message(log):
    """The reviewer's last words in the action's execution log, or ""."""
    found = ""

    def walk(node):
        nonlocal found
        if isinstance(node, dict):
            if node.get("type") == "result" and isinstance(node.get("result"), str):
                found = node["result"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(log)
    return found


def last_object(text):
    """The last JSON object in a text that has a `verdict`, or None."""
    decoder = json.JSONDecoder()
    best = None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and "verdict" in value:
            best = value
    return best


def _text(value, limit=MAX_TEXT):
    return " ".join(str(value or "").split())[:limit]


def read(message):
    """{verdict, summary, findings} from the reviewer's message, closed on
    anything that is not exactly a verdict."""
    said = last_object(message or "")
    if said is None:
        return {
            "verdict": "owner",
            "summary": "The reviewer gave no verdict, so this waits for a person.",
            "findings": [],
        }
    verdict = said.get("verdict")
    if verdict not in VERDICTS:
        return {
            "verdict": "owner",
            "summary": f"The reviewer's verdict was not one of {sorted(VERDICTS)}, so this waits for a person.",
            "findings": [],
        }
    findings = []
    for item in said.get("findings") or []:
        if not isinstance(item, dict) or not item.get("what"):
            continue
        findings.append(
            {
                "file": _text(item.get("file"), 200),
                "line": item.get("line") if isinstance(item.get("line"), int) else None,
                "what": _text(item.get("what")),
            }
        )
    return {
        "verdict": verdict,
        "summary": _text(said.get("summary")) or "(no summary)",
        "findings": findings[:MAX_FINDINGS],
    }


# ---------------------------------------------------------- owner paths


def owner_patterns(codeowners):
    """The paths a CODEOWNERS file names."""
    return [
        line.split()[0]
        for line in codeowners.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def owned(path, patterns):
    """The pattern that puts this path in the owner's lane, or None.

    CODEOWNERS' rules for the shapes this repository's file uses: a path
    from the root (`/CLAUDE.md`), a directory and all in it (`/infra/`),
    and `*` within one name (`/src/*/requirements.txt`). A pattern is
    taken as a prefix, so a mistake here sends more to the owner, never
    less.
    """
    names = path.strip("/").split("/")
    for pattern in patterns:
        parts = pattern.strip("/").split("/")
        starts = [0] if pattern.startswith("/") else range(len(names))
        for start in starts:
            window = names[start : start + len(parts)]
            if len(window) == len(parts) and all(
                fnmatch.fnmatchcase(name, part) for name, part in zip(window, parts, strict=True)
            ):
                return pattern
    return None


def changed_paths(diff):
    """Every path a diff names: the old and the new of each file, so a
    file moved out of an owner path is seen as well as one moved in."""
    paths = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git ") :]
            # "a/P b/P" for a file that kept its name; a rename says so
            # in the lines that follow.
            half = (len(rest) - 5) // 2
            name = rest[2 : 2 + half]
            if rest == f"a/{name} b/{name}":
                paths.add(name)
        else:
            moved = re.match(r"(?:rename|copy) (?:from|to) (.+)$", line)
            named = re.match(r"(?:---|\+\+\+) [ab]/(.+)$", line)
            if moved:
                paths.add(moved[1])
            elif named:
                paths.add(named[1].split("\t")[0])
    return {path.strip('"') for path in paths}


def hold_for_owner(review, diff, codeowners, changed_files=None):
    """The review, with a pass turned into "owner" when the change touches
    an owner path, or when its paths cannot all be seen."""
    if review["verdict"] != "pass":
        return review
    paths = changed_paths(diff)
    patterns = owner_patterns(codeowners)
    if not paths or not patterns or (changed_files is not None and len(paths) < changed_files):
        why = (
            "This pull request's changed files could not all be read, so it waits for the "
            "owner whatever the review found."
        )
    else:
        touched = sorted(path for path in paths if owned(path, patterns))
        if not touched:
            return review
        shown = ", ".join(f"`{path}`" for path in touched[:5]) + (" and more" if len(touched) > 5 else "")
        why = (
            f"This pull request touches an owner path ({shown}), so it waits for the owner "
            "whatever the review found."
        )
    return {
        "verdict": "owner",
        "summary": f"{why} The review itself passed it: {review['summary']}",
        "findings": review["findings"],
    }


# ----------------------------------------------- the other checks


# How a check ends when it did not do its job.
RED = frozenset({"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"})


def latest_checks(checks):
    """One check per name: a re-run of a job replaces the run before it."""
    newest = {}
    for check in checks:
        if not isinstance(check, dict) or not check.get("name"):
            continue
        before = newest.get(check["name"])
        if before is None or (check.get("id") or 0) >= (before.get("id") or 0):
            newest[check["name"]] = check
    return [newest[name] for name in sorted(newest)]


def hold_for_checks(review, checks):
    """The review, with a pass taken back when the commit's other checks
    do not all stand green.

    checks: the check runs on the pull request's head, each {name, status,
    conclusion, url, id}; None or empty when they could not be read. CI's
    own two are always among them, so an empty list is a failed read.
    """
    if review["verdict"] != "pass":
        return review

    def held(verdict, why, findings=()):
        return {
            "verdict": verdict,
            "summary": f"{why} The review itself passed it: {review['summary']}",
            "findings": ([*findings, *review["findings"]])[:MAX_FINDINGS],
        }

    def names(some):
        return ", ".join(f"`{check['name']}`" for check in some)

    if not checks:
        return held("owner", "The other checks on this commit could not be read, so this waits for a person.")
    checks = latest_checks(checks)
    red = [check for check in checks if check.get("conclusion") in RED]
    if red:
        findings = [
            {
                "file": "",
                "line": None,
                "what": _text(
                    f"The check `{check['name']}` ended `{check['conclusion']}`: {check.get('url') or 'no address'}"
                ),
            }
            for check in red
        ]
        return held(
            "changes",
            f"The check {names(red)} did not pass on this commit, so the change does not pass, whatever "
            "the review found: read what the check says, fix it and push.",
            findings,
        )
    running = [check for check in checks if check.get("status") != "completed"]
    if running:
        return held(
            "owner",
            f"The check {names(running)} had not finished when the review ended, so this waits for a person.",
        )
    return review


def comment(review):
    lines = [MARKER, f"**{HEADINGS[review['verdict']]}**", "", review["summary"]]
    if review["findings"]:
        lines.append("")
        for finding in review["findings"]:
            where = finding["file"]
            if where and finding["line"]:
                where += f":{finding['line']}"
            lines.append(f"- {f'`{where}`: ' if where else ''}{finding['what']}")
    lines += [
        "",
        "---",
        "_An agent's review of the diff, CI's result and the screenshots. It did not run the code._",
    ]
    return "\n".join(lines) + "\n"


def main(argv):
    log_path, out = Path(argv[1]), Path(argv[2])
    try:
        message = final_message(json.loads(log_path.read_text()))
    except (OSError, ValueError):
        message = ""
    review = read(message)
    if len(argv) > 6:
        # A red check sends it back to its author before anything is asked
        # of the owner.
        try:
            checks = json.loads(Path(argv[6]).read_text())
        except (OSError, ValueError):
            checks = None
        review = hold_for_checks(review, checks if isinstance(checks, list) else None)
    if len(argv) > 4:
        try:
            diff, codeowners = Path(argv[3]).read_text(), Path(argv[4]).read_text()
        except OSError:
            diff, codeowners = "", ""  # nothing to read: nothing passes
        count = int(argv[5]) if len(argv) > 5 and argv[5].isdigit() else None
        review = hold_for_owner(review, diff, codeowners, count)
    state, description = VERDICTS[review["verdict"]]
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(
        json.dumps({"verdict": review["verdict"], "state": state, "description": description})
    )
    (out / "comment.md").write_text(comment(review))
    print(review["verdict"])


if __name__ == "__main__":
    main(sys.argv)
