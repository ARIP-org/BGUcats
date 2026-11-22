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
the owner. The reviewer there is more than the one planned below: its
result is a required check.

Planned, not built: a **reviewer** on every pull request (comments only), a
**verifier** that runs a smoke test against staging after each deploy and
posts screenshots, and **in-app feedback** that becomes issues.

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
