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

## Interactive sessions

A codespace session still works as before, for infrastructure and
planning. Its pull requests are opened with the owner's own token, so once
the ruleset requires an approval they need another author.

Planned: hands-on sessions in the cloud for features and design work, with
no AWS access at all, and a GitHub identity for them that is not the
owner's. The plan and the decision it waits for are in `docs/ROADMAP.md`,
2d, "Hands-on sessions in the cloud".
