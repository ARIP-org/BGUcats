# Agents: how Claude works on this repo without a codespace

Phase 2d of `docs/ROADMAP.md`. The owner directs through GitHub issues;
Claude reads them, and, once the owner approves one, writes the change and
opens a pull request. The owner approves and merges. Nothing else changes:
CI runs on that pull request like on any other, a merge deploys staging,
and a `v*` tag promotes (`docs/deploy.md`).

```
issue opened ──> Claude triage ──> one comment + labels
                                        │
                     the owner reads it, adds the label "approved"
                                        │
                                   Claude fix ──> branch claude/issue-N ──> pull request
                                                                               │
                                              CI ──> the owner approves and merges ──> staging
```

## The agents

Each is a workflow, and what separates them is what their token can do,
not what their prompt says.

| Agent | Starts when | Acts as | Can | Cannot |
|---|---|---|---|---|
| **Triage** (`claude-triage.yml`) | an issue is opened | GitHub's job token | read the code, comment on and label issues | push, open or merge a pull request, start another workflow, reach AWS |
| **Fix** (`claude-fix.yml`) | a repository admin adds `approved` | Claude's own GitHub App | push a branch, open a pull request, comment | change `.github/workflows/` (the App has no `workflows` permission), approve or merge its own pull request, reach AWS |

**Which model:** each workflow names its own in `claude_args` (`--model`):
Fix runs on Opus, Triage on Sonnet. The token in the `claude` environment
decides whose Claude plan pays, not which model runs, and neither depends
on the model of the session the token was made in.

**Decided 2026-11-22** (`docs/ROADMAP.md`, 2g, "The factory"): a chain
of five roles, and low-risk pull requests that merge to staging without
the owner. Built so far: the reviewer, below. Planned: a **planner** and
a daily **digest** (scheduled cloud sessions), an **iPhone verifier**
(a macOS job), a **verifier** that runs a smoke test against staging
after each deploy and posts screenshots, and **in-app feedback** that
becomes issues.

## The reviewer, and the two lanes

| Agent | Starts when | Acts as | Can | Cannot |
|---|---|---|---|---|
| **Review** (`claude-review.yml`) | CI passes on a pull request | GitHub's job token for reading and for its one comment and status; Claude's App only to ask for auto-merge | read the change, the tree and CI's screenshots; write one comment and the `review` status | run the pull request's code, write a file, run a command, approve, merge past `main`'s rules, reach AWS |

It runs `main`'s copy of itself (`workflow_run`), so a pull request
cannot change the reviewer that reviews it. Claude gets `Read`, `Grep`
and `Glob` and nothing else. Its verdict is the last JSON object in its
final message, read by `scripts/review_verdict.py`: `pass`, `changes` or
`owner`, and anything that is not exactly one of them is `owner`. The
steps after it are fixed commands: one comment (kept current, not
repeated), a status named `review` on the pull request's head commit,
and for a `pass`, a request to GitHub to merge when `main`'s rules are
met.

**The two lanes** are those rules, not anything an agent decides:

- A pull request that touches no path in `.github/CODEOWNERS`, with CI
  and `review` green, merges by itself.
- One that touches an owner path waits for the owner's approval, whatever
  the reviewer said. One the reviewer did not pass stays red.

**They are not on yet.** Until the owner changes the `main` ruleset,
every pull request still needs one approval, and the reviewer only adds
its comment, its status, and auto-merge (so the owner's approval is also
the merge). What the owner sets, once, after this workflow is on `main`
and has reviewed one pull request:

1. *Settings → General → Pull Requests:* "Allow auto-merge".
2. *Settings → Rules → Rulesets → the `main` ruleset:* "Required
   approvals" to 0; "Require review from Code Owners" on; under "Require
   status checks to pass", add `review` beside `python` and `terraform`,
   **with GitHub Actions as its source**. The source matters: anyone who
   can push can post a status by that name, and only this workflow posts
   it as GitHub Actions.
3. *The same ruleset, "Bypass list":* repository admins, for pull
   requests. That is how the owner merges something the reviewer sent
   back or sent up and the owner has decided is right.

**Stopping all of it:** *Settings → Secrets and variables → Actions →
Variables*, a repository variable `AGENTS` with the value `off`. Triage
and Fix stop at their first step, and the reviewer marks every pull
request "the owner reviews", so nothing merges by itself. Delete the
variable to start them again.

**At most three agent pull requests are open at once.** Fix counts open
pull requests from `claude/` branches before it starts; at three it takes
the `approved` label back off the issue and says so there.

## The planner and the digest

Two more roles of the chain (`docs/ROADMAP.md`, 2g), and neither is a
workflow: each is a **scheduled cloud session** on the owner's Claude
account, started fresh every day, acting on GitHub as `arip-dev-bot` like
any cloud session. They use no Actions minutes. Each takes input only
from the two accounts that can push here, the owner and the bot, named
in its file; the workflows above check the same thing by permission.

| Agent | Runs | Does | Its whole job is in |
|---|---|---|---|
| **Planner** | once a day, early morning in Israel | turns the owner's feedback, failures and the plan's next milestone into at most three small issues labeled `ready` | `docs/agents/planner.md` |
| **Digest** | once a day, in the morning | one comment on the "Daily digest" issue: what needs the owner, what is broken, what merged, what is next | `docs/agents/digest.md` |

A scheduled session is told one thing: read its file on `main` and do
what it says. So changing what an agent does is a pull request to that
file, which is an owner path, and never an edit to a schedule.

**What holds them:** they are the bot, so they have what the bot has and
no more: no approval, no merge past `main`'s rules, no tag, no AWS. What
is new is that they are told to write only issues and comments; that is
an instruction, not a wall. The walls behind it are the ones every bot
session has, and the reviewer and the owner paths in front of anything
that would reach `main`.

**Labels:** `ready` (cut and ready to build), `needs-owner` (waits on a
decision or a step that is the owner's), `proposal` (an agent's own
idea; never built without the owner), `digest`. `approved` stays the
owner's: it is what starts the Fix workflow.

**Nothing builds a `ready` issue by itself yet.** The Fix workflow
starts only on the owner's `approved`. A builder that takes `ready`
issues is the next step, and waits for the repository to be public:
until then every CI run it caused would be paid for by the minute.

**Stopping them:** claude.ai → Claude Code → Scheduled tasks, pause or
delete "BGU Cats planner" and "BGU Cats digest". (`AGENTS=off` stops the
workflows; a cloud session cannot read that variable.)

## When the repository is public

Decided 2026-11-22 (`docs/ROADMAP.md`, 2g): the repository goes public,
because GitHub's standard runners, macOS too, are free there, and a
factory that pays by the minute costs more than the owner will spend. The
owner changes the visibility. What that changes for the agents, and is
already in the workflows:

- **Triage reads only issues from people who can push here.** Anyone can
  open an issue on a public repository, and each reading is paid for from
  the owner's Claude plan. A stranger's issue gets a notice in the run
  and waits for the owner.
- **Fix never sees a stranger's comment.** It reads the issue from a file
  made before it starts: the issue's text and the comments of people who
  can push, nothing else. Only an admin's `approved` starts it, as before.
- **Review looks only at branches of this repository.** A pull request
  from a fork is reviewed by nobody and merged by nobody but the owner.
- **Nothing private goes into the repository, an issue, a pull request
  or a run's log**: all of them are public, and stay public in copies
  after anything is deleted.

What stays private: every secret and variable (the App Store Connect key,
the Claude token, the App's key), the environments' rules, and AWS. A
fork's pull request gets no secret and no AWS role from GitHub, whatever
its workflow says. The App Store and TestFlight are not affected: the
build signs with a key that only the `testflight` environment holds, and
only a run started from `main` by someone who can push reaches it.

**What the owner sets on the day,** all in this repository's settings
(nothing changes for the organization). The names are GitHub's own, as
its pages gave them on 2026-11-22:

1. *Settings → Actions → General → "Approval for running fork pull
   request workflows from contributors":* choose "Require approval for
   all external contributors", then Save. A stranger's pull request then
   runs nothing until the owner says so. (The default asks only for
   first-time contributors.)
2. *Settings → Danger Zone → "Change repository visibility" → "Change
   visibility",* choose public, confirm the repository's name, "I have
   read and understand these effects", "Make this repository public".
3. *Settings → Advanced Security* (under "Security and quality"):
   "Enable" beside "Secret Protection" and beside "Push protection", if
   the switch did not turn them on: a key pushed by mistake is refused.
4. *Settings → Rules → Rulesets:* look that the `main` ruleset and the
   `v*` tag ruleset are still active. GitHub's page says the change
   disables "push rulesets"; these two are not that kind, and it costs a
   minute to see.
5. Afterwards, optional: the organization's paid plan was bought for
   environments and rulesets on a private repository, which a public one
   has for free. To check before changing it.

What GitHub's page says the change does, beyond showing the code: anyone
can fork it; "Actions history and logs will be visible to everyone",
old runs included; stars and watchers are erased.

Checked on 2026-11-22: no key, token or private key in any of the 314
commits. The owner's own email address is in the repository and stays
(the owner's choice). No photo and no dataset is.

**What nobody has seen yet:** this workflow has never run. A workflow
that starts from `workflow_run` runs only from `main`, so its first run
is on the first pull request after it merges. If it fails, the status is
`error` and nothing merges by itself: it fails closed.

## Seeing a change before it is merged

Staging only ever shows merged code. What shows a change before the merge
is `tests/web`: the app's screens in a headless browser at a phone's size,
against the real API and process handlers with AWS mocked on localhost.

- Every CI run keeps a screenshot of each screen: the run's page →
  *Artifacts* → `screenshots`.
- The Fix agent has the browser too, and is told to look at the screens it
  changes.
- In any session: `make screenshots`, or `make local-app` to click through
  the app by hand. Neither needs AWS.

They show a made-up campus (three cats, coloured shapes for photos), so
they are safe to attach anywhere.

## Why it is safe to let it run

An issue is text from outside, and text can say "ignore your instructions".
The design assumes it will, and relies on GitHub and AWS, not on the model:

- **Triage cannot escalate.** Its token cannot write code. A label it adds
  starts nothing, because GitHub does not trigger workflows from the job
  token, so it cannot approve its own work.
- **Only an admin's `approved` starts a fix.** The fix job's first step
  checks who added the label.
- **A fix cannot land itself.** The `main` ruleset requires one approval,
  and the author of a pull request cannot approve it. The App is the
  author; the owner is the approver.
- **A fix cannot rewrite the rules.** `.github/workflows/` is refused at
  push. The other files that decide what may reach AWS and what it may
  cost are in `.github/CODEOWNERS`.
- **Neither can reach AWS.** Neither job asks for an OIDC token, and each
  account's roles trust only the `staging` and `production` environments
  and the CI plan. What a merged change may create is then limited by the
  deploy role, the plan check and the organization's allowlist
  (`docs/MANUAL_STEPS.md`, step 13).
- **The secrets are out of reach of a branch.** They are in the GitHub
  environment `claude`, which only `main` may use, so a workflow edited in
  a pull request cannot read them.

What is not walled: the fix job runs any shell command on its runner, with
the App's token and the Claude token in its environment. An issue that got
past the owner's reading could make it misuse those within what they can
do: push branches, open pull requests, write comments, spend Claude usage.
It cannot merge. Read an issue's comments too before adding `approved`.

## Setup (once, by the owner)

1. **The App.** `https://github.com/organizations/ARIP-org/settings/apps/new`
   - Name `arip-claude` (any free name), homepage the repo's URL.
   - *Webhook*: untick **Active**.
   - *Repository permissions*: **Contents**, **Pull requests** and
     **Issues** → *Read and write*. Everything else *No access*; above all
     **Workflows**, **Administration** and **Actions**.
   - *Only on this account* → **Create GitHub App**.
   - Note the **App ID**. **Generate a private key** (a `.pem` downloads).
   - *Install App* → `ARIP-org` → *Only select repositories* → `BGUcats`.
2. **The Claude token.** In a terminal of your own (not a Claude session):
   `claude setup-token`, open the link, approve. It prints a token that
   starts with `sk-ant-oat01-`. Subscription auth only: never an
   `ANTHROPIC_API_KEY`.
3. **The environment.** *Settings → Environments → New environment* →
   `claude`. *Deployment branches and tags* → *Selected* → add branch
   `main`. Then:
   - *Environment secrets*: `CLAUDE_CODE_OAUTH_TOKEN` (the token),
     `CLAUDE_APP_PRIVATE_KEY` (the whole `.pem` file's text).
   - *Environment variables*: `CLAUDE_APP_ID` (the App ID).
4. **The label.** *Issues → Labels → New label* → `approved`.
5. **Try it.** Open an issue ("Fix a typo in docs/…"). Within a few
   minutes: a triage comment. Add `approved`: a pull request from
   `arip-claude[bot]` follows, with CI running on it.
6. **Then, and only then, require the approval.** *Settings → Rules →
   Rulesets → main → Require a pull request before merging*: **Required
   approvals** `1`, tick **Require review from Code Owners**. Before the
   App authors pull requests this would lock every merge, since the author
   of a pull request cannot approve it.

Delete the `.pem` from your computer afterwards: GitHub keeps only its
fingerprint, and a new one can be generated at any time.

## Stopping it

- One run: *Actions* → the run → *Cancel*.
- All of it: *Actions → Claude fix → ⋯ → Disable workflow* (and the same
  for triage), or delete the secret `CLAUDE_CODE_OAUTH_TOKEN`.
- For good: *Settings → GitHub Apps → arip-claude → Uninstall*.

## Hands-on sessions in the cloud

For work the owner wants to steer: a feature, a redesigned screen, "try it
this way". A session on claude.ai/code or in the Claude phone app, on this
repo, running on a machine Anthropic provides. No charge beyond the Claude
plan, and nothing to keep running.

| | |
|---|---|
| Acts on GitHub as | the machine user `arip-dev-bot`: write access, not an admin, not a code owner. Its credential stays outside the session's machine, behind a proxy that is part of the product; that proxy refuses tag pushes and branch deletions |
| AWS | none. SSO sign-in is not possible in a cloud session |
| Rules | the same `CLAUDE.md` and the same deny rules (`.claude/settings.json`) |
| Tools | `scripts/cloud_session_setup.sh` runs when the session starts: the dev dependencies in a virtual environment (`~/.venvs/bgucats`, first on PATH, because the system Python's Debian packages cannot be upgraded by pip) and Terraform. Its message names whatever did not install ("setup INCOMPLETE"), and the session starts anyway; the log is `/tmp/bgucats-cloud-setup.log`. A Chrome is already there, so `make screenshots` works |
| Ends in | a branch `claude/<topic>` and a pull request authored by the bot, which the owner approves and merges |

**How a session goes:** describe the change, attach screenshots, sketches
or a Figma link. Claude makes it, runs `make lint` and `make test`, and
shows the changed screens from `make screenshots`. The pull request gets
CI's two plans like any other. After the merge, staging has it.

**What it cannot do, and why that is the point:** approve or merge its own
pull request (the author cannot approve, and the `main` ruleset requires an
approval), change who may approve (no admin), create a `v*` tag (the tag
ruleset, and the proxy), or touch AWS. Anything that needs AWS is a
codespace session with the owner signed in.

### Setup (once, by the owner)

1. **The machine user.** A second GitHub account, `arip-dev-bot`, a member
   of `ARIP-org` with the role **Write** on `BGUcats`
   (`https://github.com/ARIP-org/BGUcats/settings/access`).
2. **The Claude GitHub App on the repo.** As the owner:
   `https://github.com/apps/claude` → *Install* (or *Configure*) →
   `ARIP-org` → *Only select repositories* → `BGUcats`.
3. **Connect the Claude account to GitHub as the bot.** In a browser where
   GitHub is signed in as `arip-dev-bot`, open `https://claude.ai/code` and
   connect GitHub. If the Claude account is already connected as the
   owner, disconnect that first in claude.ai's settings. From then on every
   cloud session on that Claude account acts as the bot, in any repo.
4. **Try it:** a cloud session, "fix a typo in docs/…, open a pull
   request". The pull request's author must be `arip-dev-bot`.
5. **Then require the approval** on `main` (step 6 of the setup above),
   which until now would have locked the owner's own pull requests.

## Infrastructure sessions

A codespace session, steered from a phone with Remote Control if wanted:
the only place AWS is used by hand, and only with the owner signed in to
SSO for a job the owner asked for (`CLAUDE.md`, "Workflow"). Its pull
requests are opened with the codespace's token, which is the owner's. Once
the ruleset requires an approval they need another author too: push the
branch and let a cloud session, or the bot's token, open the pull request.
