# Agents: how Claude works on this repo without a codespace

Phases 2d and 2g of `docs/ROADMAP.md`. Work arrives as GitHub issues: the
owner's, or the planner's, cut from the owner's words, a failure or the
plan. An issue in the queue becomes a pull request; CI and a reviewer
read it; `main`'s rules decide whether it waits for the owner. Nothing
else changes: a merge deploys staging, and a `v*` tag promotes
(`docs/deploy.md`).

```
the owner's issue ──> triage: one comment ──> the owner adds "approved" ──┐
the planner's issue, labeled "ready" ─────────────────────────────────────┤
                                                                          │
              the queue (scripts/builder_queue.py): who labeled it, is there room
                                                                          │
                       the builder ──> branch claude/issue-N ──> pull request
                                                                          │
                     CI ──> the reviewer ──> main's rules ──> staging
```

## The agents

Each is a workflow, and what separates them is what their token can do,
not what their prompt says.

| Agent | Starts when | Acts as | Can | Cannot |
|---|---|---|---|---|
| **Triage** (`claude-triage.yml`) | an issue is opened | GitHub's job token | read the code, comment on and label issues | push, open or merge a pull request, start another workflow, reach AWS |
| **Fix**, the builder (`claude-fix.yml`) | an issue is in the queue and there is room (below) | Claude's own GitHub App | push a branch, open a pull request, comment | change `.github/workflows/` (the App has no `workflows` permission), approve or merge its own pull request, reach AWS |

**Which model** (the owner, 2026-11-22: the one that decides gets the
strongest, and nothing else pays for it):

| Role | Model | Where that is set |
|---|---|---|
| Planner | Fable | its cloud session, made with that model |
| Builder | Opus | `--model` in `claude-fix.yml` |
| Reviewer | Opus | `--model` in `claude-review.yml` |
| Triage | Sonnet | `--model` in `claude-triage.yml` |
| Digest | Sonnet | its cloud session, made with that model |

The token in the `claude` environment decides whose Claude plan pays, not
which model runs. A cloud session keeps the model it was made with:
changing one means a new session and pointing its schedule there (the
digest was moved off Fable that way on its first day).

**Decided 2026-11-22** (`docs/ROADMAP.md`, 2g, "The factory"): a chain
of five roles, and low-risk pull requests that merge to staging without
the owner. Built so far: the reviewer, the planner, the digest and the
builder's queue, all below, and the **iPhone verifier**: the `swift` job
of `ios.yml`, which builds the Swift app on a Mac and keeps a picture of
every screen (`native/swift/README.md`). The builder cannot see those
pictures while it works (it runs on Linux): it learns from the job's
result on its pull request, like anyone. The reviewer does not read them
yet either; it reads CI's. Planned: a **verifier** that runs a smoke
test against staging after each deploy and posts screenshots, and
**in-app feedback** that becomes issues.

## The builder's queue

The queue is the open issues labeled `approved` or `ready`. What starts
is decided by `scripts/builder_queue.py`, in a job with no Claude and no
secret, **from who put the label on, never from what an issue says:**

- `approved` counts only from a repository admin: the owner read the
  issue, whoever opened it.
- `ready` counts only from someone who can push, on an issue opened by
  someone who can push. That is the planner's lane: its issues are
  written by the bot from the owner's words.
- A label put on by a workflow's token or by an App counts for nothing,
  so the builder and the triage, which act as those, cannot hand
  themselves or each other work.
- **The bot account's `ready` does count,** and that is the design: it
  is a user who can push, the planner acts as it, and cutting `ready`
  issues is the planner's job. So does the `ready` of any cloud session,
  since every one acts as the bot. One agent can hand the builder work;
  what it cannot do is get that work past CI, the reviewer, the owner
  paths and the owner's tag.
- A label that does not count is taken off, with a comment saying why.
- An issue whose pull request is already open is never built a second
  time, whoever labels it again: its label becomes `building`.

**At most three pieces of agent work are open at once:** this
repository's open pull requests from `claude/` branches (a session's
too), plus issues being built that have no pull request yet. The rest
wait in the queue, the owner's `approved` first, then the oldest. The
queue is looked at when a label is added, after every deploy (so after
every merge), and every two hours. Not on the push itself: Claude's
action refuses a `push` event, which is how the queue's first three
builds ended before Claude started (2026-11-23).

**What an issue's labels say:** `ready` or `approved`, waiting; then
`building`, from the moment a run takes it until its pull request merges
(which closes the issue). A run that ends with no pull request, or a
`building` issue with no open pull request and nothing moving for three
hours, goes to `needs-owner` with a comment. To start it again: take
`needs-owner` off and put `ready` or `approved` on.

**The builder cannot change `.github/`, `.claude/`, `infra/bootstrap/` or
`infra/org/`.** Work that needs one of them is not `ready`: it is for a
session (below), and the planner labels it `needs-owner` and says so.

**A build that ends with no pull request says why.** The workflow prints
what Claude said last in the run's log, every time, and copies it into
the comment that hands the issue to the owner. On the queue's first day
two builds ended green with no pull request and not a word (2026-11-23),
and the action shows nothing of what Claude did.

**A build never waits for anything.** A run ends when Claude ends its
turn, and nothing wakes it afterwards. Three builds started the test
suite in the background, said "I'll wait for the notification that the
tests have finished", and were over (2026-11-23, known only once the
last message was printed). The builder now has no background commands
(`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`), may run one command for
twenty-five minutes, and is told to run the tests in pieces and to end
its turn only with a pull request or a reason.

**The App's own work is let in by name.** Claude's action refuses a run
that a bot started unless the bot is named (`allowed_bots`). The
builder's pull requests are opened by the App, so the reviewer names it,
and so does the builder (a merge the App asked for starts a deploy, and
the deploy reads the queue). Only `arip-claude`, never `*`: on a public
repository that would let any App start an agent.

**A pull request the reviewer sent back goes to the builder again**
(the job `rework`, since 2026-11-23). The queue script finds the
builder's open pull requests (`claude/issue-N`) whose newest `review`
status is the reviewer's "sent back", marks one `reworking`, and hands
it over. The builder is on the pull request's own branch, reads the
reviewer's comment (found by who wrote it, not by how it starts), fixes
what is right, says finding by finding what it did, and pushes; CI and
the reviewer read it again. **Twice at most:** a third "sent back", or
an answer that pushed nothing, puts `needs-owner` on the pull request
with a comment. A session's own pull request is not answered this way:
its session answers it.

**So does one that no longer merges with `main`** (since 2026-11-24).
The builder takes up to three issues at once, each from the same `main`;
that night three changed the same files, the first merged, and the other
two stood in conflict. GitHub runs no check on a pull request in
conflict, so no review would ever have sent them anywhere. The queue
asks each of the builder's pull requests whether it still merges, and
the rework job is told to merge `main` in and keep both changes whole.
The same two rounds count, whichever the reason. The planner's side of
it: issues that change the same files are not `ready` together, and for
the Swift app that is one at a time (`docs/agents/planner.md`).

It was first seen to work the same morning: the builder merged `main`
into #127 and #128 in four minutes each and pushed. Two things about it
that are not obvious:

- **The builder can push a merge of `main` that carries a workflow
  change**, though its App has no `workflows` permission. #130 had
  changed two workflows, both merges brought them in, and both pushes
  went through. GitHub refuses a push whose own commits change a
  workflow, not a merge of commits already on `main`. (The review of
  #130 doubted this, and a guard against it was written and taken back
  unmerged.)
- **GitHub says whether a pull request merges only once it has been
  asked,** and "not known" until then. The queue asks a few times, a
  few seconds apart, and on every look prints what it learned of each of
  the builder's pull requests. Its first look after #130 asked once,
  was told "not known", and printed "Nothing in the queue".

**The builder is shown what a failed check said.** When a check failed
on the commit, the rework job reads that check's log with its own token
and leaves the lines that say why in `failed/`, for Claude to read
before it changes anything. Swift cannot be compiled on Linux, so the
Mac's log is the only compiler the builder has: #127 failed on one
redeclared name that nothing had shown it.

**A commit per file** (the owner, 2026-11-24). Both of the builder's
prompts ask for it, and `CLAUDE.md` ("Workflow") has the rule for
everyone.

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

**What the reviewer sends to the owner is a short list** (the owner,
2026-11-23: "My approvals are asked too frequently"). Until then it was
told "when in doubt, owner", and every pull request of that day went up.
Now `owner` is only for a change that: deletes or rewrites what people
stored; changes who may sign in or what a role may do; adds a new kind
of AWS resource or a cost; changes what an agent may do, a rule in
`CLAUDE.md` or a recorded decision; or changes what is published outside
the app. Anything else it is not sure of goes back to its author
(`changes`), and a change that does what its description says passes,
even when it changes what users see: the owner sees it on staging and in
the digest, and production still moves only on the owner's tag.

**The two lanes** are those rules, not anything an agent decides:

- A pull request that touches no path in `.github/CODEOWNERS`, with CI
  and `review` green, merges by itself.
- One that touches an owner path waits for the owner, whatever the
  reviewer said. One the reviewer did not pass stays red.

**The owner's lane is held twice,** because on 2026-11-23 the first hold
was not there. #121 changed a workflow and the roadmap, the reviewer
passed it (rightly: it was a small fix), and it merged eight seconds
later with nobody's approval. GitHub had asked the owner for a review and
did not wait for it: the ruleset was not requiring one.

1. **The ruleset:** "Require review from Code Owners" on the `main`
   ruleset (below). Nobody but an admin can see or change it, and no
   agent can read it: whether it is on is known only by what it refuses.
2. **The reviewer's own script** (`scripts/review_verdict.py`, since
   2026-11-23): it reads the pull request's diff and `main`'s
   `CODEOWNERS`, and a "pass" on a change that touches an owner path
   becomes "for the owner". No model judges the paths, a file moved out
   of an owner path counts as well as one moved in, and a diff that
   cannot be read whole passes nothing. Auto-merge is asked for on a
   pass alone, so it is never asked for such a change: the owner merges
   it (the bypass list, below).

With both on, an owner-path pull request shows `review` red with "the
owner should look at this" and the reviewer's findings under it, as #118
and #119 did. The script's hold was first seen to work on #128
(2026-11-24): the reviewer would have passed it, and it waited because
it touches the Xcode project.

**A red check anywhere takes a pass back** (since 2026-11-24). The
reviewer starts when CI ends, and CI is `python` and `terraform`. The
iPhone app's checks (`ios.yml`: `swift`, `simulator`) run beside CI on a
pull request that touches `native/`, and nothing looked at them: #126
merged with `swift` failed, and `main` could not be built for TestFlight
until #129; #127 was passed with a compile error. They cannot simply be
made required checks, because they do not run on every pull request, and
a required check that never runs blocks the merge for ever. So the
reviewer's workflow lists every check run on the pull request's head,
waits while one is still running (twenty-five minutes at most), and the
verdict script reads the list:

- one **failed**: the pass becomes "sent back", naming the check and its
  address, so the builder's answer has it to read;
- one **not finished**, or a list that could not be read: "for the
  owner";
- a job run again replaces the run before it.

**They are on since 2026-11-23**, when the owner changed the `main`
ruleset. Before that every pull request needed one approval, and the
reviewer only added its comment, its status and auto-merge (so the
owner's approval was also the merge: #115, #116 and #117 merged within
seconds of it). What the owner set, for the record and for a second
repository:

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

**At most three pieces of agent work are open at once**, counted by the
builder's queue (above). At three, an issue waits in the queue with its
label; nothing is dropped and nothing has to be labeled again.

## The planner and the digest

Two more roles of the chain (`docs/ROADMAP.md`, 2g), and neither is a
workflow: each is a **cloud session of its own** on the owner's Claude
account, woken once a day by a schedule, acting on GitHub as
`arip-dev-bot` like any cloud session. (A schedule that starts a fresh
session each day was tried first, 2026-11-22: made from another session,
such a session gets no GitHub tools, so it could read the code and no
issue. One long-lived session per role has them. Each day it starts again
from its file, not from what it remembers.) They use no Actions minutes. Each takes input only
from the two accounts that can push here, the owner and the bot, named
in its file; the workflows above check the same thing by permission.

| Agent | Runs | Does | Its whole job is in |
|---|---|---|---|
| **Planner** | once a day, early morning in Israel | turns the owner's feedback, failures and the plan's next milestone into at most three small issues labeled `ready` | `docs/agents/planner.md` |
| **Digest** | once a day, in the morning | one comment on the "Daily digest" issue: what needs the owner, what is broken, what merged, what is next | `docs/agents/digest.md` |

Each is told one thing, every day: update to `main`, read its file
again, and do what it says. So changing what an agent does is a pull request to that
file, which is an owner path, and never an edit to a schedule.

**What holds them:** they are the bot, so they have what the bot has and
no more: no approval, no merge past `main`'s rules, no tag, no AWS. What
is new is that they are told to write only issues and comments; that is
an instruction, not a wall. The walls behind it are the ones every bot
session has, and the reviewer and the owner paths in front of anything
that would reach `main`.

**Labels:** `ready` (cut and ready to build: the builder takes it by
itself), `building` (a run is on it, or its pull request is open),
`needs-owner` (waits on a decision or a step that is the owner's),
`proposal` (an agent's own idea; never built without the owner),
`digest`. `approved` stays the owner's: it puts any issue in the queue,
ahead of the `ready` ones.

**A `ready` issue is built with no person involved** (since the
repository is public and its runners free; "The builder's queue",
above). What the owner still decides: every pull request, until the two
lanes are on; then every one that touches an owner path or that the
reviewer sends up.

**Stopping them:** claude.ai → Claude Code → Scheduled tasks, pause or
delete "BGU Cats planner" and "BGU Cats digest". Their two sessions,
with the same names, are in the session list and show each day's run. (`AGENTS=off` stops the
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
  can push, nothing else. A stranger's issue starts only on an admin's
  `approved`; `ready` on it is taken off (the builder's queue).
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

**What its first days showed:** a workflow that starts from
`workflow_run` runs only from `main`, so nothing here could be tried
before it merged, and four joins between the parts failed on the day
they were first needed (`docs/notes.md`, "Agents and sessions"). Each
failed closed: a status of `error`, an issue handed to the owner,
nothing merged by itself.

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
- **A script decides what starts a fix, from who added the label.**
  `approved` from an admin, or `ready` from someone who can push on an
  issue opened by someone who can push; never a label from a workflow or
  an App ("The builder's queue"). The script and the workflow are owner
  paths.
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
A `ready` issue has no such reading by a person: its text is the
planner's, and what stands behind it is that the planner takes its input
only from the owner and the bot, which is an instruction, and then CI,
the reviewer, the owner paths and the owner's tag, which are not.

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
- All of it: the `AGENTS` variable set to `off` ("The reviewer, and the
  two lanes"); or *Actions → Claude fix → ⋯ → Disable workflow* (and the
  same for triage), or delete the secret `CLAUDE_CODE_OAUTH_TOKEN`.
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
