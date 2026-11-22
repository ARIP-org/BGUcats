"""The agents' workflows keep to what docs/agents.md says holds them.

A workflow file is the wall between an agent and everything it must not
do, and nothing runs it before it is on `main`. So what each one promises
in its header is checked here: what can start it, what its token may do,
which tools Claude gets, and that the reviewer's verdict fails closed.
"""

import importlib.util
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
AGENTS = sorted(WORKFLOWS.glob("claude-*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

spec = importlib.util.spec_from_file_location(
    "review_verdict", REPO / "scripts" / "review_verdict.py"
)
verdicts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verdicts)


def load(path):
    data = yaml.safe_load(path.read_text())
    # YAML reads the key `on` as the boolean true.
    data["on"] = data.pop(True)
    return data


def steps(workflow):
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def claude(workflow):
    (step,) = [s for s in steps(workflow) if "claude-code-action" in s.get("uses", "")]
    return step


def tools(workflow):
    args = claude(workflow)["with"]["claude_args"]
    return re.search(r'--allowedTools "([^"]+)"', args).group(1).split(",")


def test_there_are_the_three_agents():
    assert [p.name for p in AGENTS] == ["claude-fix.yml", "claude-review.yml", "claude-triage.yml"]


def test_no_agent_can_reach_aws():
    for path in AGENTS:
        assert "id-token" not in path.read_text(), path.name


def test_every_action_is_pinned_to_a_commit():
    for path in AGENTS:
        for step in steps(load(path)):
            if "uses" in step:
                assert PINNED.match(step["uses"]), f"{path.name}: {step['uses']}"


def test_every_agent_stops_at_the_switch():
    for path in AGENTS:
        workflow = load(path)
        assert any("vars.AGENTS == 'off'" in str(s.get("if", "")) for s in steps(workflow)), path.name
    # The builder and the triage stop before anything else.
    for name in ("claude-fix.yml", "claude-triage.yml"):
        first = steps(load(WORKFLOWS / name))[0]
        assert first["if"] == "vars.AGENTS == 'off'" and "exit 1" in first["run"], name


def test_the_token_lives_in_the_environment_only_main_can_read():
    for path in AGENTS:
        for job in load(path)["jobs"].values():
            assert job["environment"] == "claude", path.name


# ------------------------------------------------------------ the reviewer


def reviewer():
    return load(WORKFLOWS / "claude-review.yml")


def test_the_reviewer_runs_mains_copy_of_itself_after_ci():
    # workflow_run takes the workflow from the default branch: a pull
    # request cannot change the reviewer that reviews it.
    assert reviewer()["on"] == {"workflow_run": {"workflows": ["CI"], "types": ["completed"]}}
    job = reviewer()["jobs"]["review"]
    assert "workflow_run.event == 'pull_request'" in job["if"]
    assert "workflow_run.conclusion == 'success'" in job["if"]


def test_the_reviewer_can_read_and_nothing_else():
    assert tools(reviewer()) == ["Read", "Grep", "Glob"]
    job = reviewer()["jobs"]["review"]
    assert job["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "write",
        "statuses": "write",
    }
    # Claude's own token is the job's, never the App's.
    assert claude(reviewer())["with"]["github_token"] == "${{ github.token }}"


def test_the_reviewer_never_runs_the_pull_requests_code():
    for step in steps(reviewer()):
        run = step.get("run", "").replace("\\\n", " ")  # a command over two lines is one
        for line in run.splitlines():
            if ".review/" not in line:
                continue
            # Fetched, unpacked, removed: never executed, sourced or installed.
            assert re.match(r"\s*(mkdir|gh |tar |rm |echo )", line), line
        # The pull request's head is never checked out as the workspace.
        if "actions/checkout" in step.get("uses", ""):
            assert "ref" not in step.get("with", {})


def test_the_app_token_is_made_after_claude_and_only_for_a_pass():
    order = [s.get("id") or s.get("name") or s.get("uses") for s in steps(reviewer())]
    after = order[order.index("verdict") :]
    assert "app" in after
    for step in steps(reviewer()):
        if step.get("id") == "app" or step.get("name") == "Merge when the rules are met":
            assert step["if"] == "steps.verdict.outputs.verdict == 'pass'"
    merge = next(s for s in steps(reviewer()) if s.get("name") == "Merge when the rules are met")
    # GitHub merges when main's rules are met; nothing here approves or
    # merges past them.
    assert "--auto" in merge["run"] and "--admin" not in merge["run"]
    assert "gh pr review" not in (WORKFLOWS / "claude-review.yml").read_text()


# -------------------------------------------------------------- the verdict


def said(text):
    return verdicts.read(text)


def test_a_verdict_is_the_last_object_in_the_message():
    review = said(
        'I looked at it. An earlier thought: {"verdict": "changes"}.\n\n'
        '{"verdict": "pass", "summary": "Fine.", "findings": []}'
    )
    assert (review["verdict"], review["summary"]) == ("pass", "Fine.")


def test_anything_that_is_not_a_verdict_waits_for_a_person():
    for text in ("", "Looks good to me!", '{"verdict": "approve"}', '{"summary": "pass"}', "{broken"):
        assert said(text)["verdict"] == "owner", text
    # Not a string that merely contains the word.
    assert said('{"verdict": "pass please"}')["verdict"] == "owner"


def test_findings_are_kept_small_and_plain():
    review = said(
        json.dumps(
            {
                "verdict": "changes",
                "summary": "x" * 5000,
                "findings": [{"file": "web/a.js", "line": 3, "what": "wrong\n\nvery wrong"}]
                + [{"what": f"finding {n}"} for n in range(40)]
                + ["not a finding", {"file": "b.py"}],
            }
        )
    )
    assert len(review["summary"]) == verdicts.MAX_TEXT
    assert len(review["findings"]) == verdicts.MAX_FINDINGS
    assert review["findings"][0] == {"file": "web/a.js", "line": 3, "what": "wrong very wrong"}


def test_the_status_and_the_comment_follow_the_verdict(tmp_path):
    log = tmp_path / "log.json"
    for verdict, state in (("pass", "success"), ("changes", "failure"), ("owner", "failure")):
        message = json.dumps({"verdict": verdict, "summary": "Because.", "findings": []})
        log.write_text(json.dumps([{"type": "assistant"}, {"type": "result", "result": message}]))
        verdicts.main(["", str(log), str(tmp_path / "out")])
        assert json.loads((tmp_path / "out" / "verdict.json").read_text())["state"] == state
        comment = (tmp_path / "out" / "comment.md").read_text()
        assert comment.startswith(verdicts.MARKER) and "Because." in comment
    # No log at all: Claude never ran, and nothing passes.
    verdicts.main(["", str(tmp_path / "missing.json"), str(tmp_path / "out")])
    assert json.loads((tmp_path / "out" / "verdict.json").read_text())["verdict"] == "owner"


# --------------------------------------------------------------- owner paths


def test_what_an_agent_may_not_change_by_itself_is_the_owners():
    owned = {
        line.split()[0]
        for line in (REPO / ".github" / "CODEOWNERS").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for path in (
        "/.github/",
        "/.claude/",
        "/CLAUDE.md",
        "/infra/",
        "/scripts/check_plan.py",
        "/scripts/ci_plan.sh",
        "/scripts/review_verdict.py",
        "/requirements.txt",
        "/src/*/requirements.txt",
        "/web/vendor/",
        "/src/common/admission.py",
        "/src/admin/presignup.py",
        "/docs/ROADMAP.md",
    ):
        assert path in owned, path
    # Every owned path exists: a rule for a file that moved protects nothing.
    for path in owned:
        assert list(REPO.glob(path.strip("/"))), path
