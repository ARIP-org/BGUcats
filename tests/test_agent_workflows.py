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


def claude(workflow, job=None):
    """The step that runs Claude: the workflow's one, or that of a job."""
    (step,) = [
        s
        for name, j in workflow["jobs"].items()
        if job in (None, name)
        for s in j["steps"]
        if "claude-code-action" in s.get("uses", "")
    ]
    return step


def tools(workflow, job=None):
    args = claude(workflow, job)["with"]["claude_args"]
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
    # The builder's look at the queue after a deploy or by the clock does not
    # even start: a red run every two hours would tell nobody anything.
    assert "github.event_name != 'issues' && vars.AGENTS != 'off'" in builder()["jobs"]["pick"]["if"]


def test_the_token_lives_in_the_environment_only_main_can_read():
    for path in AGENTS:
        for name, job in load(path)["jobs"].items():
            if "secrets." in yaml.safe_dump(job):
                assert job["environment"] == "claude", f"{path.name}: {name}"
    # Every job that runs Claude is one of those.
    for path in AGENTS:
        running = [j for j in load(path)["jobs"].values() if "claude-code-action" in yaml.safe_dump(j)]
        assert running, path.name
        for job in running:
            assert job["environment"] == "claude", path.name


# ------------------------------------------------- on a public repository


def test_a_strangers_issue_is_never_read_by_an_agent():
    # Anyone can open an issue on a public repository, and every reading
    # is paid for from the owner's Claude plan.
    triage = steps(load(WORKFLOWS / "claude-triage.yml"))
    gate = next(s for s in triage if s.get("id") == "who")
    assert "collaborators/$AUTHOR/permission" in gate["run"]
    assert "admin | maintain | write" in gate["run"]
    after = triage[triage.index(gate) + 1 :]
    for step in after:
        if "uses" in step:
            assert step["if"] == "steps.who.outputs.ours", step["uses"]


def test_triage_leaves_the_planners_and_the_digests_issues_alone():
    condition = load(WORKFLOWS / "claude-triage.yml")["jobs"]["triage"]["if"]
    for label in ("ready", "digest"):
        assert f"!contains(github.event.issue.labels.*.name, '{label}')" in condition


# -------------------------------------------------------------- the builder


def builder():
    return load(WORKFLOWS / "claude-fix.yml")


def test_the_builder_looks_at_the_queue_on_a_label_a_deploy_and_the_clock():
    on = builder()["on"]
    assert on["issues"] == {"types": ["labeled"]}
    # After a deploy (a place may be free) and after a review (a pull
    # request may have been sent back).
    assert on["workflow_run"] == {"workflows": ["Deploy", "Claude review"], "types": ["completed"]}
    assert len(on["schedule"]) == 1


# What anthropics/claude-code-action runs on. It stops at anything else
# with "Unsupported event type", before Claude starts: the builder's first
# three builds were started by a push and all ended there (2026-11-23).
ACTION_TAKES = {
    "issues",
    "issue_comment",
    "pull_request",
    "pull_request_review",
    "pull_request_review_comment",
    "workflow_dispatch",
    "repository_dispatch",
    "schedule",
    "workflow_run",
}


def test_no_agent_starts_on_an_event_claudes_action_refuses():
    for path in AGENTS:
        assert set(load(path)["on"]) <= ACTION_TAKES, path.name
    on = builder()["on"]
    # Never on a pull request's own events: those run the pull request's
    # copy of this file.
    assert not any(event.startswith("pull_request") for event in on)


def test_a_script_decides_what_starts_before_any_claude_runs():
    jobs = builder()["jobs"]
    pick, fix = jobs["pick"], jobs["fix"]
    # The pick: a script from main with the job's own token, and nothing
    # of Claude's. It holds no secret and is in no environment.
    text = yaml.safe_dump(pick)
    assert "secrets." not in text and "claude-code-action" not in text and "environment" not in pick
    assert any(step.get("run") == "python3 scripts/builder_queue.py" for step in pick["steps"])
    # It may mark a pull request (a label, a comment) and read the
    # reviewer's status. It cannot push, merge or write a status.
    assert pick["permissions"] == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "write",
        "statuses": "read",
    }
    # One at a time, and never cancelled halfway through moving labels.
    assert pick["concurrency"] == {"group": "claude-fix-pick", "cancel-in-progress": False}
    # The build: only what the pick handed over, one job an issue.
    assert fix["needs"] == "pick"
    assert fix["strategy"]["matrix"]["issue"] == "${{ fromJSON(needs.pick.outputs.issues) }}"
    assert fix["env"]["ISSUE"] == "${{ matrix.issue }}"
    # Nothing in the build comes from the event: a label names no issue.
    assert "github.event." not in yaml.safe_dump(fix)


def test_the_builder_as_claude_cannot_push_workflows_or_reach_the_queue_script():
    fix = builder()["jobs"]["fix"]
    app = next(s for s in fix["steps"] if s.get("id") == "app")
    assert {k for k in app["with"] if k.startswith("permission-")} == {
        "permission-contents",
        "permission-pull-requests",
        "permission-issues",
    }
    prompt = claude(builder(), "fix")["with"]["prompt"]
    assert "Never touch .github/" in prompt
    assert "/scripts/builder_queue.py" in (REPO / ".github" / "CODEOWNERS").read_text()


def test_a_build_with_no_pull_request_goes_to_the_owner_with_claudes_last_words():
    fix = builder()["jobs"]["fix"]
    names = [s.get("name") for s in fix["steps"]]
    last = next(s for s in fix["steps"] if s.get("name") == "No pull request came of it")
    assert last["if"] == "always()"
    assert "labels[]=needs-owner" in last["run"] and "labels/building" in last["run"]
    # Two of the first builds ended green with no pull request and not a
    # word (2026-11-23). What Claude said last is printed every time, not
    # only on failure, and goes on the issue with the hand-over.
    said = next(s for s in fix["steps"] if s.get("name") == "What Claude said last")
    assert said["if"] == "always()" and "said.txt" in said["run"]
    assert names.index("What Claude said last") < names.index("No pull request came of it")
    # As a file, quoted and cut short: never put into a command.
    assert "--body-file" in last["run"] and "head -c 3000" in last["run"]
    assert "$(cat" not in last["run"]
    # Claude's step ends before the job does, so those steps run.
    assert claude(builder(), "fix")["timeout-minutes"] < fix["timeout-minutes"]


def test_the_builder_cannot_end_its_turn_waiting_for_a_command():
    # A run ends when Claude ends its turn. Three builds put the test suite
    # in the background, said they would wait for it, and were over with
    # nothing pushed (2026-11-23).
    step = claude(builder(), "fix")
    env = json.loads(step["with"]["settings"])["env"]
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    # One command may run as long as the whole suite does, and the step
    # outlasts two of them.
    ceiling_min = int(env["BASH_MAX_TIMEOUT_MS"]) / 60000
    assert env["BASH_DEFAULT_TIMEOUT_MS"] == env["BASH_MAX_TIMEOUT_MS"]
    assert 20 <= ceiling_min and 2 * ceiling_min <= step["timeout-minutes"]
    prompt = step["with"]["prompt"]
    assert "Never stop to wait for something" in prompt
    assert "pytest -q --ignore=tests/web" in prompt
    # Not the whole suite by reflex: that is what took eighteen minutes.
    assert "`make test`" not in prompt


def test_a_sent_back_pull_request_is_answered_by_the_builder_on_its_own_branch():
    jobs = builder()["jobs"]
    rework, fix = jobs["rework"], jobs["fix"]
    # Only what the pick handed over, one job a pull request, and never
    # while the same issue is being built.
    assert rework["needs"] == "pick"
    assert rework["strategy"]["matrix"]["item"] == "${{ fromJSON(needs.pick.outputs.rework) }}"
    assert rework["concurrency"]["group"] == "claude-fix-${{ matrix.item.issue }}"
    assert fix["concurrency"]["group"] == "claude-fix-${{ matrix.issue }}"
    assert "github.event." not in yaml.safe_dump(rework)
    names = [s.get("name") for s in rework["steps"]]
    step = claude(builder(), "rework")
    at = rework["steps"].index(step)
    # The reviewer's comment is found by who wrote it: on a public
    # repository anyone can write one that starts like it. The reviewer
    # keeps its own comment current by the same test.
    found = rework["steps"][names.index("What the reviewer found")]
    assert names.index("What the reviewer found") < at
    assert '.user.login == "github-actions[bot]"' in found["run"]
    assert '.user.login == "github-actions[bot]"' in (WORKFLOWS / "claude-review.yml").read_text()
    # The pull request's own branch, with the App's token.
    checkout = next(s for s in rework["steps"] if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["ref"] == "claude/issue-${{ matrix.item.issue }}"
    assert checkout["with"]["token"] == "${{ steps.app.outputs.token }}"
    # The same Claude with the same walls as the build.
    build = claude(builder(), "fix")
    for same in ("claude_args", "settings", "allowed_bots", "github_token"):
        assert step["with"][same] == build["with"][same], same
    assert step["timeout-minutes"] < rework["timeout-minutes"]
    prompt = step["with"]["prompt"]
    for said in (
        "${{ runner.temp }}/review.md",
        "Open no new pull request",
        "never\n" + "force-push",
        "Never touch .github/",
        "Never stop to wait for something",
    ):
        assert said in prompt.replace("\n            ", "\n"), said
    # An answer that pushed nothing goes to the owner, with why; the mark
    # comes off either way.
    last = rework["steps"][names.index("Nothing was pushed")]
    assert last["if"] == "always()" and names.index("What Claude said last") < names.index("Nothing was pushed")
    assert "labels/reworking" in last["run"] and "labels[]=needs-owner" in last["run"]
    assert '"$now" != "$SHA"' in last["run"] and "--body-file" in last["run"]


def test_the_apps_own_work_is_reviewed_and_starts_the_queue():
    # Claude's action refuses a run started by a bot it was not told of.
    # The builder's pull requests are the App's, so unnamed, the reviewer
    # reviewed none of them (2026-11-23). Named, and only it: "*" would
    # let any App on a public repository start an agent.
    for name, job in (("claude-review.yml", None), ("claude-fix.yml", "fix"), ("claude-fix.yml", "rework")):
        assert claude(load(WORKFLOWS / name), job)["with"]["allowed_bots"] == "arip-claude", (name, job)
    assert "allowed_bots" not in claude(load(WORKFLOWS / "claude-triage.yml"))["with"]


def test_the_builder_reads_the_issue_without_strangers_comments():
    fix = load(WORKFLOWS / "claude-fix.yml")
    names = [s.get("name") for s in steps(fix)]
    # Made before Claude starts, by a step that is not Claude's.
    assert names.index("The issue, without strangers' comments") < steps(fix).index(claude(fix, "fix"))
    prompt = claude(fix, "fix")["with"]["prompt"]
    assert "${{ runner.temp }}/issue.md" in prompt
    assert "gh issue view" not in prompt
    assert "do not fetch the issue yourself" in prompt


def test_the_reviewer_reviews_only_branches_of_this_repository():
    # A fork's pull request is found by nobody: the lookup names the
    # organization's own branch, at the commit CI ran on.
    find = steps(reviewer())[0]["run"]
    assert "head=${REPO%%/*}:$BRANCH" in find and ".head.sha ==" in find


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


def test_the_reviewer_sends_the_owner_only_what_is_the_owners():
    # The owner, 2026-11-23: "My approvals are asked too frequently."
    # Until then the reviewer was told "when in doubt, owner", and every
    # pull request of the day went up. Now `owner` is a short list, doubt
    # goes back to the author, and a plainly described change passes.
    prompt = claude(reviewer())["with"]["prompt"]
    assert "When in doubt, `owner`" not in prompt
    assert "never `owner`" in prompt and "`owner`: rare." in prompt
    for kept in (
        "deletes or rewrites what people have stored",
        "who may sign in",
        "new kind of AWS resource",
        "what an agent may do",
        "published outside the app",
    ):
        assert kept in prompt, kept
    # Fails closed all the same: no verdict, or an unknown one, is `owner`.
    assert said("no verdict here")["verdict"] == "owner"


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
            if step.get("id") == "verdict":
                # The one other reader: main's own script is handed the
                # diff, and jq the pull request's facts, to be read as text.
                assert " ".join(line.split()) == (
                    'python3 scripts/review_verdict.py "${LOG:-$RUNNER_TEMP/claude-execution-output.json}" '
                    '"$RUNNER_TEMP/verdict" .review/pr.diff .github/CODEOWNERS '
                    '"$(jq -r .changedFiles .review/pr.json)"'
                ), line
                continue
            # Fetched, unpacked, removed: never executed, sourced or installed.
            assert re.match(r"\s*(mkdir|gh |tar |rm |echo )", line), line
        # The pull request's head is never checked out as the workspace.
        if "actions/checkout" in step.get("uses", ""):
            assert "ref" not in step.get("with", {})
    # The script that reads the diff runs nothing and imports nothing of it.
    script = (REPO / "scripts" / "review_verdict.py").read_text()
    for runs in ("subprocess", "os.system", "exec(", "eval(", "importlib", "__import__"):
        assert runs not in script, runs


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


def a_diff(*files, renames=()):
    lines = []
    for path in files:
        lines += [f"diff --git a/{path} b/{path}", "index 111..222 100644", f"--- a/{path}", f"+++ b/{path}", "@@ -1 +1 @@", "-a", "+b"]
    for old, new in renames:
        lines += [f"diff --git a/{old} b/{new}", "similarity index 100%", f"rename from {old}", f"rename to {new}"]
    return "\n".join(lines) + "\n"


OWNERS = (REPO / ".github" / "CODEOWNERS").read_text()
PASSED = {"verdict": "pass", "summary": "Fine.", "findings": []}


def test_a_change_to_an_owner_path_never_passes_whatever_the_reviewer_said():
    # 2026-11-23: #121 changed a workflow and the roadmap, the reviewer
    # passed it, and it merged eight seconds later with nobody's approval.
    # The ruleset was meant to hold it and did not.
    held = verdicts.hold_for_owner(PASSED, a_diff(".github/workflows/ios.yml", "docs/ROADMAP.md", "docs/notes.md"), OWNERS)
    assert held["verdict"] == "owner"
    assert "`.github/workflows/ios.yml`" in held["summary"] and "`docs/ROADMAP.md`" in held["summary"]
    assert "`docs/notes.md`" not in held["summary"] and "The review itself passed it: Fine." in held["summary"]
    for path in (
        "CLAUDE.md",
        "infra/main/web.tf",
        "src/app/requirements.txt",
        "src/common/admission.py",
        "scripts/review_verdict.py",
        "web/vendor/preact-htm.js",
        "native/swift/BGUCats.xcodeproj/project.pbxproj",
        ".github/CODEOWNERS",
    ):
        assert verdicts.hold_for_owner(PASSED, a_diff(path, "web/app.js"), OWNERS)["verdict"] == "owner", path
    # What #120 changed: none of it the owner's, and it still passes.
    free = a_diff("native/swift/BGUCats/Auth.swift", "tests/native/test_swift_app.py", "docs/deploy.md", "scripts/ios_screenshots.py")
    assert verdicts.hold_for_owner(PASSED, free, OWNERS) == PASSED
    # A file moved out of an owner path is the owner's too, and one moved in.
    assert verdicts.hold_for_owner(PASSED, a_diff(renames=[("infra/main/web.tf", "old/web.tf")]), OWNERS)["verdict"] == "owner"
    assert verdicts.hold_for_owner(PASSED, a_diff(renames=[("notes.txt", "CLAUDE.md")]), OWNERS)["verdict"] == "owner"


def test_what_cannot_be_read_waits_for_the_owner_and_nothing_is_made_better():
    # No diff, no CODEOWNERS, or fewer paths than GitHub counted: closed.
    assert verdicts.hold_for_owner(PASSED, "", OWNERS)["verdict"] == "owner"
    assert verdicts.hold_for_owner(PASSED, a_diff("web/app.js"), "")["verdict"] == "owner"
    assert verdicts.hold_for_owner(PASSED, a_diff("web/app.js"), OWNERS, changed_files=2)["verdict"] == "owner"
    assert verdicts.hold_for_owner(PASSED, a_diff("web/app.js"), OWNERS, changed_files=1) == PASSED
    # It only ever turns a pass into "owner": a sent-back review stays one.
    back = {"verdict": "changes", "summary": "Fix it.", "findings": []}
    assert verdicts.hold_for_owner(back, a_diff("CLAUDE.md"), OWNERS) == back


def test_the_workflow_hands_the_verdict_the_diff_and_mains_owner_paths(tmp_path):
    job = load(WORKFLOWS / "claude-review.yml")["jobs"]["review"]
    step = next(s for s in job["steps"] if s.get("id") == "verdict")
    assert '.review/pr.diff .github/CODEOWNERS "$(jq -r .changedFiles .review/pr.json)"' in step["run"]
    # And the whole script, as the workflow runs it.
    log = tmp_path / "log.json"
    log.write_text(json.dumps([{"type": "result", "result": json.dumps(PASSED)}]))
    diff = tmp_path / "pr.diff"
    owners = REPO / ".github" / "CODEOWNERS"
    diff.write_text(a_diff(".github/workflows/ios.yml"))
    verdicts.main(["", str(log), str(tmp_path / "out"), str(diff), str(owners), "1"])
    said = json.loads((tmp_path / "out" / "verdict.json").read_text())
    assert said == {"verdict": "owner", "state": "failure", "description": "Reviewed: the owner should look at this"}
    assert "touches an owner path" in (tmp_path / "out" / "comment.md").read_text()
    diff.write_text(a_diff("web/app.js"))
    verdicts.main(["", str(log), str(tmp_path / "out"), str(diff), str(owners), "1"])
    assert json.loads((tmp_path / "out" / "verdict.json").read_text())["verdict"] == "pass"
    # A diff that is not there: nothing passes.
    verdicts.main(["", str(log), str(tmp_path / "out"), str(tmp_path / "none.diff"), str(owners), "1"])
    assert json.loads((tmp_path / "out" / "verdict.json").read_text())["verdict"] == "owner"
    # Auto-merge is asked for on "pass" alone.
    merge = next(s for s in job["steps"] if s.get("name") == "Merge when the rules are met")
    assert merge["if"] == "steps.verdict.outputs.verdict == 'pass'"


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
        "/scripts/builder_queue.py",
        "/requirements.txt",
        "/src/*/requirements.txt",
        "/web/vendor/",
        "/src/common/admission.py",
        "/src/admin/presignup.py",
        "/docs/ROADMAP.md",
        "/docs/agents/",
    ):
        assert path in owned, path
    # Every owned path exists: a rule for a file that moved protects nothing.
    for path in owned:
        assert list(REPO.glob(path.strip("/"))), path


def test_each_scheduled_agent_has_its_job_in_a_file_and_may_only_write_issues():
    # A scheduled session is told to read its file on main and do what it
    # says, so the file is the agent. Each says what it may do, that
    # nothing else is allowed, and whose words count.
    for name in ("planner", "digest"):
        job = (REPO / "docs" / "agents" / f"{name}.md").read_text()
        assert "## What you may do" in job, name
        for never in ("no pull request", "no merge", "no AWS"):
            assert never in job, f"{name}: {never}"
        assert "arip-dev-bot" in job or "the bot wrote" in job, name
    planner = (REPO / "docs" / "agents" / "planner.md").read_text()
    assert "Do not\nlabel anything `approved`" in planner
    assert "never label it `ready`" in planner
