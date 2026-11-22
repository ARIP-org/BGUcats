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

    python scripts/review_verdict.py <execution-log.json> <out-dir>

writes `verdict.json` (`verdict`, `state`, `description`) and `comment.md`.
"""

import json
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
    state, description = VERDICTS[review["verdict"]]
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(
        json.dumps({"verdict": review["verdict"], "state": state, "description": description})
    )
    (out / "comment.md").write_text(comment(review))
    print(review["verdict"])


if __name__ == "__main__":
    main(sys.argv)
