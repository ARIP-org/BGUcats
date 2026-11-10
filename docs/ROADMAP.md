# BGU Cats — engineering roadmap

Written 2026-10-30 by the owner (Sasha). This is the long-term plan for **how the
project is built, deployed and worked on** — accounts, environments, repos,
people. *What* the product does next is still decided by `CLAUDE.md` (phases
1a–4); this file does not change product priorities.

**For Claude:** read this before any work that touches infra, CI/CD, repo
layout, access, or onboarding. Work one phase at a time, in order. Before
starting a phase, propose its issues (text only) and wait for the owner's go.
Never start a later phase because an earlier one is blocked — say what blocks
it instead.

## Decisions

| Date | Decision |
|---|---|
| 2026-10-31 | **Promote model, not a `dev` branch.** Merge to `main` deploys staging; a manual Promote deploys the same commit to production. (Considered: a long-lived `dev` branch merged into `main`. Rejected: production would run a merge commit staging never ran, and it is the branch stack again.) |
| 2026-10-31 | **GitHub organization, private repos.** If the organization needs a paid plan for environments, it is GitHub Team, not public repos. The owner's student Pro plan is personal and does not cover an organization. |
| 2026-10-31 | **Order: Phase 1's secrets gap → GitHub organization (2a) → staging (2b).** The organization comes before staging so the staging account's roles trust the new repo name from day one. The owner and Claude do 2a and 2b together, step by step. |
| 2026-11-02 | **The organization is on GitHub Team, from before the transfer.** On GitHub Free, a private repo has no deployment branch restrictions, environment secrets or environment variables, and transferring to a Free account loses protected branches. The deployment branch rule is what limits the deploy role to `main`, so a Free organization could let a workflow on any branch deploy. |
| 2026-11-02 | **Decommission the old account now, not on 2026-11-13.** The new account has run production since 2026-10-30, and the next-day check is done. |
| 2026-11-07 | **The organization is `ARIP-org`** (Animal Re-Identification Project), not a bgucats name: the architecture is not limited to one campus. `arip` was taken. Created by the owner 2026-11-07. |
| 2026-11-07 | **Claude may run AWS write commands** when the owner is signed in and asks for the job (step 9 was done this way). It still never deploys, never merges, and holds no credentials of its own: it works in the owner's SSO session. |
| 2026-11-07 | **Staging: no Telegram bot, a Google OAuth client of its own.** The bot is on its way out as the app gets closer to real. Staging's Google client lives in a Google Cloud project of its own (`bgucats-staging`), so its consent screen's *Test users* is a beta list kept apart from production's. Root email `sashajewishman+bgucats-staging@gmail.com`. |
| 2026-11-07 | **The owner orchestrates; Claude writes all the code and the infrastructure.** The owner directs through GitHub issues (features, bugs, tester feedback) and through interactive sessions (infrastructure, planning). CI deploys. Claude never deploys and never merges. |
| 2026-11-07 | **Guardrails that do not depend on Claude's judgment** (Phase 2c). The fear to design against: Claude deciding "we need a relational database" and a VPC, a NAT gateway and RDS reaching AWS. The walls are AWS-side (deploy role scope, an SCP that denies expensive services even to admins) and GitHub-side (Claude's own identity, a required approval, no `workflows` permission). `CLAUDE.md` and Claude Code's deny rules are seatbelts on top, not the wall. |
| 2026-11-10 | **The service SCP is an allowlist, not a list of expensive services.** Everything is denied except what the project uses (`infra/org/scp.tf`). A denylist is never complete: until this day an admin session in a member account could subscribe to Shield Advanced, register a domain or buy from the Marketplace. |
| 2026-11-10 | **A budget that acts, not only one that emails.** Per member account: $10 emails, $20 attaches an SCP that freezes every change, $40 one that stops the app's API. The owner accepted that production goes down at $40 until the policy is lifted. AWS has no hard cap and Budgets sees spending hours late, so the limit is "$40 plus what was spent before it noticed"; the allowlist and the accounts' quotas keep that remainder small. |
| 2026-11-10 | **Claude may apply `infra/bootstrap` and `infra/org`** in a session the owner has signed in to, when asked. `infra/main` stays CI-only. `infra/org` is a Terraform root from this day. |
| 2026-11-10 | **Promote is a protected `v*` tag, not a button.** Only the owner can create one (a tag ruleset) and `production` deploys only from those tags. A `workflow_dispatch` button can be pressed by anyone with write access, including a session that holds the owner's token. |
| 2026-11-10 | **Native apps early.** The owner will join the Apple Developer Program and ship the beta through TestFlight, with an Android build alongside (Phase 2e). Supersedes "decided then, not now" in the row below; one codebase still stands. |
| 2026-11-10 | **Interactive cloud sessions act on GitHub as a machine user,** not as the owner (2d, option B). The owner creates the account; one more seat on GitHub Team. |
| 2026-11-10 | **Alerts by email through SNS** (2f): `sns` goes onto the service allowlist. |
| 2026-11-10 | **The platform is the point.** The owner is more interested in the platform than in the product, so platform work is not held back until the product asks for it. |
| 2026-10-31 | iOS and Android: one codebase, never platform branches. Today that is the PWA; if the stores are needed (Phase 4 of `CLAUDE.md`), wrap `web/` with Capacitor. Decided then, not now. |

---

## Vision

BGU Cats is run like a small real product team, even while it is one person
and Claude:

- **Production is boring.** Nothing reaches it except through a reviewed,
  merged PR and an automated pipeline. No one deploys by hand; no long-lived
  credentials exist anywhere.
- **Every change is seen before users see it.** A staging copy of the app
  gets every merge first; production gets the same, already-tested version on
  a deliberate promote.
- **Parts that are products in their own right live on their own.** The
  recognition model is developed, versioned and released separately, and the
  app consumes it as a dependency through a written contract.
- **Each person gets exactly the access their work needs.** A designer works
  in Figma and on staging, with no cloud access. An ML engineer works in the
  model repo with read access to dataset exports, never to production.
- **Claude is a contributor, not an operator.** It writes all the code and
  the infrastructure, and opens PRs in any repo; the owner orchestrates and
  does not write code. It never holds AWS credentials of its own, never
  deploys, and never merges; AWS writes happen only in the owner's session,
  for a job the owner asked for. Its only identity of its own will be a
  GitHub App (Phase 2d), which can open PRs and nothing more.

## Principles (apply to every phase)

1. **Environments are AWS accounts, not branches.** One trunk (`main`),
   short-lived feature branches, environments selected by the pipeline.
   No long-lived `dev`/`preprod` branches — they are what made the
   2026-10 branch stack.
2. **Everything is code.** Infra in Terraform, pipelines in GitHub Actions,
   access in Identity Center groups and permission sets (documented here
   until it is codified). A change nobody can review in a PR is a smell.
3. **Least privilege by role, not by person.** Access is granted to groups;
   people are added to groups.
4. **Boring, explainable choices.** Portfolio project: every decision should
   be defensible in an interview in two sentences.
5. **The dataset is the one irreplaceable asset.** Any step that touches the
   production table or media bucket is add-only, verified, and reversible.

---

## Where we are (updated 2026-11-10)

| Area | State |
|---|---|
| AWS Organization | Created. Management account `851725214678`, running nothing since 2026-11-07 (step 9): only the organization, Identity Center, budgets and one backup of the old table. Identity Center: permission sets AdministratorAccess (1 h) and ReadOnlyAccess (4 h), assigned to the owner's user `Sasha` directly on each member account (group `Admins` exists, empty). |
| Staging account | `bgucats-staging` `586943192664`, created and bootstrapped 2026-11-07. Deployed by every merge since 2026-11-10: app `https://d2rysfyl47qmmz.cloudfront.net/`, landing `https://d2hdwn6h65nfue.cloudfront.net/`, its own user pool and Google client. The recognition model is published there (2026-11-10, the same files as production's). No cats or photos in it yet (12g). |
| Production account | `sasha-bgucats-prod` `395591097129`. Bootstrapped (state bucket, lock table, OIDC provider, CI role, deploy role, permissions boundary). |
| CI/CD | PRs run `python` + `terraform` (a plan of each account, then the plan check: no new kind of resource, no provisioned table, no oversized Lambda; both accounts since PR #48). A push to `main` runs **Deploy** for staging; a `v*` tag, which only the owner can create, runs the same job for production (#40). No tag exists yet, so the promote has never been exercised; production's plan today says `No changes`. Ruleset on `main`: PR required, both checks required, no bypass, no approval required yet. |
| Guardrails | `infra/org`, applied 2026-11-10 from the management account (`docs/MANUAL_STEPS.md`, step 13): the service allowlist SCP (on staging; onto the root with PR #47, which the owner applies, 13c), budget actions at $20 and $40 on both member accounts, anomaly emails from $5. Claude Code deny rules in `.claude/settings.json`. |
| Data | Copied and cut over on 2026-10-30 (`docs/MANUAL_STEPS.md` steps 7–8). The old copy was deleted on 2026-11-07 (step 9) after a final `verify`; production is the only copy in AWS, plus a media copy (`~/bgucats-media-backup`) the owner downloaded to a computer on 2026-11-07. |
| WhatsApp bot | Removed from code (PR #4) and from the old account (step 9). |
| Repo | Single repo `ARIP-org/BGUcats` (moved from `sasha720709/BGUcats` on 2026-11-07): `src/` (Lambdas), `web/` (PWA), `site/` (landing), `infra/`, `research/` (imports nothing from `src/`), `scripts/`. |
| Secrets | **Outside Terraform since 2026-10-31** (PR #12): SSM values and Cognito's Google provider are set by `infra/scripts/set-secret.sh`, owner-only. CI and deploy roles have no access to them (PR #14, bootstrap applied by the owner 2026-10-31; the CI plan with the restricted role shows no changes). Telegram bot token, webhook secret and Google client secret rotated by the owner 2026-10-31. Salt deliberately not rotated. |
| Telegram bot | A stopgap, not a product line: the app's Capture is the real upload channel. Kept working while the landing page points to it; no long-term plans around it (e.g. staging needs no test bot). |
| GitHub plan | Organization `ARIP-org` on GitHub Team; the repo moved into it on 2026-11-07. Team gives environments and deployment branch rules on private repos, and rulesets that can require a PR approval; required reviewers *on environments* need Enterprise. Today the owner's merge is the only gate, and every PR so far is authored with the owner's token. Claude's own GitHub App (`arip-claude`) and the environment `claude` exist since 2026-11-10: **Claude triage** has run on real issues; **Claude fix** has never run, because no issue has been labeled `approved` yet (`docs/agents.md`). |

---

## Next session starts here (2026-11-10, evening)

Phases 0, 1 and 2a are done. 2b, 2c and the first half of 2d are done
except for the rows marked below.

| | State |
|---|---|
| 12f deploy to staging, promote by tag (#40) | done; staging has been deployed by every merge since |
| 13c the allowlist onto the root (#47) | **applied 2026-11-10** by the owner, together with `sns` for the alerts. Production runs under the allowlist |
| Alerts (#51) | live on staging, proven (an email at ALARM and at OK). Production gets them with the first promote |
| Tests of the app's screens (#52), Pillow 13.0.0 (#50), CI plans both accounts (#48) | merged |
| Consistent reads (#53) | merged: a real bug the seed found, a photo could be dropped right after its encounter was made |
| Smoke test after every staging deploy | built: through the API, as the seed does (the owner's choice, 2026-11-10). A commit gets `deployed/staging` only if it passes |
| Machine user `arip-dev-bot` | works: PR #57 came from a cloud session and is authored by it. Next: the required approval on `main` |
| The model on staging | published 2026-11-10 |
| 12g seed data | done 2026-11-10: `make seed-staging`, six made-up cats, through staging's own API |
| 12g the freeze policy's exemption for the Lambda roles | not proven yet |
| First promote (a `v*` tag) | never exercised. Expected production plan: no changes |
| Claude triage | works |
| Claude fix | never run: label one small issue `approved` |
| Required approval on `main` | off until a pull request exists that the owner did not author |
| Apple Developer Program | paid 2026-11-10, enrollment pending |

**Claude's next jobs, in order:**

1. **12g, the rest:** the freeze policy attached to staging for a minute:
   the app's API must keep answering.
2. **The codespace without the owner's token:** the bot's token for
   `gh` there, so pull requests from infrastructure sessions have an
   author the owner can approve.
3. **Hands-on sessions in the cloud** (2d, below), once the machine user
   exists: the session setup hook, then one trial session.
4. **The reviewer** agent: comments on every pull request.
5. **2e,** when Apple approves the enrollment: the Capacitor wrap, signed
   in against staging, built and uploaded to TestFlight by a workflow.

**The owner's steps:**

- On branch `alerts`: `echo yes | infra/scripts/org-apply.sh`, then merge
  #51. Merge #48, #49, #50 and #52.
- Create the machine user (2d, below) and give it write access.
- Click the link in AWS's two confirmation emails, one per account, after
  #51 is deployed.
- Label a small issue `approved`, to see the first **Claude fix** run.
- Sign in to the staging app on a phone (the Google account must be in
  the staging Google project's *Test users*).
- Tag the first release, to exercise the promote (`docs/deploy.md`,
  "Promoting to production").
- After Apple's approval: an App Store Connect API key (Issuer ID, Key ID,
  the `.p8` file) into a GitHub environment, and the app's record in App
  Store Connect. Claude writes the steps when 2e starts.

**Photos backup:** the owner downloaded `~/bgucats-media-backup` to a
computer (2026-11-07), the one copy outside production.

**Incident during the rotation:** revoking the bot token also dropped the
webhook, and the first `set-secret.sh` did not notice, so the bot was
silent from the rotation until the owner set the webhook by hand the same
evening. Fixed in PR #17 (address from API Gateway, refused `setWebhook`
stops the script); `docs/deploy.md` has the details.

## Phase 0 — Finish the move

Owner-driven; follows `docs/MANUAL_STEPS.md`.

- Pre-copy media + model; `verify --only ssm` = `same` ×3.
- Delete the WhatsApp Meta app before the cutover evening.
- Cutover (`scripts/cutover.sh`), reinstall the app on phones, smoke test.
- Next day: `verify --only table` → `missing` = 0.
- Decommission the old account (step 9), keys and the
  `sasha-bgucats-admin` IAM user deleted, old data deleted. **Done 2026-11-07**,
  earlier than planned, all at once.
- SCPs on member accounts (step 10) and central root access management.

**Done when:** the management account runs nothing; no IAM users or access
keys exist in the organization; production has run two weeks on the new
account with `missing` = 0.

## Phase 1 — Harden what exists

- **Close the known secrets gap (first):** Terraform state holds the bot token,
  webhook secret, salt and Google client secret in clear text, readable
  through the CI role by any PR's workflow. The CI role can also read the
  three SSM parameters directly (`ssm:GetParameter`). Move them to write-only
  arguments (`value_wo`, Terraform ≥ 1.11) or set them outside Terraform.
  Then narrow the CI role's SSM read (bootstrap, owner-applied), and rotate
  whatever was readable before.
- **Pin and update Actions:** Node 20 actions are deprecated on runners
  (warning seen 2026-10-30). Pin every action to a full commit SHA and
  enable Dependabot for `github-actions` and `pip`.
- **PR hygiene:** a PR template with *what / why / how tested / terraform
  plan summary (add/change/destroy)*; CI posts the plan summary as a PR
  comment so review doesn't need the logs.
- **Issue templates:** bug, task, infra change.
- **Cost guard:** AWS Budgets alert per member account.

**Done when:** no secret value appears in any state file; every action is
SHA-pinned; every PR shows its plan summary inline.

## Phase 2 — GitHub organization and staging environment

### 2a. GitHub organization

- Create the organization **on GitHub Team, before the transfer** (Decisions,
  2026-11-02).
- Transfer `BGUcats` into it. **The transfer changes the OIDC claims**
  (`repo:sasha720709@…/BGUcats@…:…` → `repo:<org>@…/BGUcats@…:…`, and
  `repository`), so the bootstrap trust policies must accept the new name
  before the transfer and drop the old one after it — or CI and deploys are
  refused. GitHub says transfers after 2026-07-15 use the `@id` subject
  format; the first CI run after the transfer confirms it.
- Check that environments, environment secrets, variables and the ruleset
  came across; recreate what did not. GitHub's transfer docs promise secrets
  and webhooks but do not mention environments, variables or rulesets, so
  **check that the `production` deployment branch rule is there before the
  first merge**.

**Done when:** a PR in the organization's repo passes CI, and its merge
deploys. **Done 2026-11-07** (PR #34).

Codespaces in the organization: GitHub Team includes no Codespaces quota.
`ARIP-org` → *Settings* → *Codespaces* → *General* → "Codespace
ownership" decides who pays: **User ownership** bills the creator's
personal account (and its free or Pro quota); Organization ownership bills
the org and needs a spending limit above zero.

### 2b. Staging account

- New member account `bgucats-staging`, created in Organizations; `Admins`
  assigned; covered by the same SCPs.
- Same Terraform, its own backend file (`infra/main/backend/staging.hcl`),
  its own bootstrap (OIDC, CI/deploy roles scoped to environment `staging`).
- Own secrets: own Cognito domain prefix (`bgucats-staging`), **a separate
  Google OAuth client** (beta access is managed apart from production), own
  salt. **No Telegram bot** (decided 2026-11-07: the bot is on its way out).
- **Pipeline:** merge to `main` → deploy **staging** automatically.
  Production deploys only when the owner pushes a `v*` tag on a commit
  staging already runs. GitHub environment `staging` (branch `main`) and
  `production` (deployments only from `v*` tags, which a tag ruleset lets
  only the owner create).
- **Data:** staging never receives real contributor photos. A seed script
  creates sample cats/sessions from public-domain or own test images.
- The landing site is deployed to staging too (cheap, and a place to
  preview landing-page changes); QR codes and links point only to
  production.

**Done when:** a merge appears on staging within ~20 minutes without
touching production, and promoting deploys an identical build to
production.

### 2c. Guardrails that do not depend on Claude

Claude can only reach AWS through three doors. What holds each one shut:

| Door | Today | Wall (enforced by AWS or GitHub) | Seatbelt (enforced by the harness) |
|---|---|---|---|
| **1. A deploy:** Claude writes Terraform, the owner merges, CI applies | Open by design | The deploy role can create only the resource types `infra/main` uses today; widening it is a bootstrap change. The service allowlist SCP: every service the project does not use is denied in the member accounts, even to admins. A CI check that fails on any resource type not on an allowlist, so a red check means "something new that could cost money" | The plan summary on every PR |
| **2. The owner's admin login** in a session where Claude runs | Open whenever the owner signs in to an `-admin` profile there | The SCP above: even admin cannot create the expensive things. In Actions (2d) the runner has no SSO session and Claude's job requests no OIDC token | Claude Code deny rules in `.claude/settings.json` (`terraform apply` on `infra/main`, `gh pr merge` and `review`, `gh workflow run`, pushes to `main`, release tags). Habit: `-ro` while writing app code, `-admin` only for infra sessions, then `aws sso logout` |
| **3. Merging without the owner** | Partly open: in a codespace Claude holds the owner's token | 2d: Claude's own GitHub App, one required approval on `main`, no `workflows` permission, CODEOWNERS on `.github/`, `infra/bootstrap/`, `infra/org/` | Deny rule on `gh pr merge` |

**The SCP, `bgucats-service-allowlist`** (`infra/org/scp.tf`, applied
from the management account): deny everything except the services the
project uses, and inside those, the calls that buy a commitment or raise a
quota. Opening a service is a deliberate change in the management account,
never a side effect of a PR.

**A budget that acts** (`infra/org/budgets.tf`): $10 emails (the budget in
each account), $20 attaches `bgucats-budget-freeze` (no creates or
changes; the app keeps running), $40 attaches `bgucats-budget-stop` (the
app's API stops; data and static pages stay). **Cost Anomaly Detection**
emails from $5.

**What is still open,** said plainly:

- Budgets acts hours late, so the limit is not exact.
- DynamoDB has no condition key for a table's billing mode: a provisioned
  table is refused in CI (`scripts/check_plan.py`), not by AWS.
- SCPs never apply to the management account. An admin session there is
  held by nothing but habit. Next: a narrow permission set for
  organization and billing work, with full admin kept as break-glass that
  Claude's settings deny.
- Faster than Budgets: CloudWatch alarms on usage (Lambda duration,
  DynamoDB requests) that cut the app's concurrency within minutes. Not
  built; worth it once the app is public.
- CloudFront's flat-rate Free plan ($0, no overage charges) for the two
  distributions: to check when a custom domain is added.

**DDoS** (secondary): API Gateway throttling already caps the public
beacon, and CloudFront absorbs most floods. WAF costs money; not at this
scale. Revisit when the app is public.

**Done when:** the SCP is attached and proven (creating a NAT gateway in
staging is an explicit deny, even as admin); anomaly detection is on; the
allowlist check fails a plan that adds `aws_db_instance`; the deny rules
are in the repo. **Done 2026-11-10** for staging; the root follows
staging's first deploy (`docs/MANUAL_STEPS.md`, 13c). The plan check is
proven by its tests, not by a test PR.

### 2d. Claude in CI, and the feedback loop

What is built, how it is set up and how to stop it: `docs/agents.md`.

How the owner works from here: **orchestrating, not writing code.**

- **GitHub issues** for anything that should end in a PR: features, bugs,
  tester feedback. Claude triages, the owner adds `approved`, Claude opens a
  PR that carries screenshots from a headless run and a second agent's
  review. The owner approves and merges, staging gets it, a smoke test
  reports back, the owner tries it on a phone and tags a release to
  promote. (Staging only ever shows merged code, so "look at staging
  before merging" was never possible; the screenshots are the before.)
- **Interactive sessions** (codespace, claude.ai/code, Remote Control from
  a phone) for open-ended work: infrastructure, planning, "should we…?".
  The only place AWS admin is ever used, and only when the owner signs in
  for it.

What it takes:

- **Claude's own GitHub identity:** a GitHub App installed on `ARIP-org`,
  with contents and pull requests write, **no `workflows` permission** (it
  cannot change CI, deploys or its own workflow), no admin.
- **The `main` ruleset requires one approval.** A bot cannot approve its
  own PR, so nothing lands without the owner. "Allow GitHub Actions to
  create and approve pull requests" stays off.
- **Two workflows, split by trust.** *Triage* reads issues and feedback
  (untrusted text: anyone can write "ignore your instructions") with
  read-only GitHub permissions, no AWS, limited tools. *Fix* runs only when
  the owner adds `approved`; it may push a branch and open a PR. Neither
  requests `id-token`, so neither can assume an AWS role.
- **Subscription auth only** (`CLAUDE_CODE_OAUTH_TOKEN`, as an environment
  secret limited to `main`), never `ANTHROPIC_API_KEY`.
- **In-app feedback:** a "Send feedback" button and shake-to-report, sent to
  our own API (screenshots stay in S3, never in git). A read-only OIDC role
  lets GitHub pull new feedback into issues; no GitHub token in AWS. App
  Store Connect / TestFlight becomes a second source only once the app is
  wrapped for the stores.

#### Hands-on sessions in the cloud (decided 2026-11-10: option B; not built)

The feedback loop is for small changes nobody needs to watch. For larger
ones (a redesigned screen, a new feature, "try it this way") the owner
wants to work with Claude directly, from any device, without paying for a
machine and with no more access than the Fix agent has.

**Three ways of working, chosen by what the job needs:**

| | Feedback loop | Hands-on session | Infrastructure session |
|---|---|---|---|
| For | small fixes, tester feedback | features, design work, exploring | bootstrap, organization, secrets, incidents |
| Started from | an issue labeled `approved` | claude.ai/code or the Claude phone app, repo `ARIP-org/BGUcats` | a codespace, with Remote Control |
| Runs on | a GitHub Actions runner | a VM Anthropic runs: no charge beyond the Claude plan | Codespaces hours (personal quota) |
| GitHub | the App `arip-claude` | through a proxy; the credential never enters the VM. It can push branches; it cannot push tags or delete branches | the codespace's token (the owner's) |
| AWS | none | none: SSO sign-in is not possible there | the owner's SSO session, when asked |
| Ends in | a pull request | a pull request | a pull request, or an applied `infra/bootstrap` / `infra/org` |

A hands-on session, step by step:

1. The owner opens a cloud session on the repo and describes the change,
   with screenshots, sketches or a Figma link attached.
2. Claude works in the VM under the same `CLAUDE.md` and the same deny
   rules, runs `make lint` and `make test`, and shows the changed screens
   as screenshots from a headless browser (the verifier's harness, job 2
   above). That is the look before the merge.
3. Claude pushes `claude/<topic>` and a pull request is opened. CI plans
   both accounts. The owner approves and merges; staging gets it; the
   owner tries it on a phone and tags a release.

To build: a `SessionStart` hook that installs the dev dependencies and
Terraform when the session is a cloud one; the screenshot harness; and
the way a pull request gets an author who is not the owner (below).

**Whose GitHub identity a session uses.** A cloud
session acts on GitHub as whoever connected GitHub to the Claude account.
If that is the owner, the session's pull requests are the owner's own,
which the owner cannot approve, and the session could approve and merge
an App-authored pull request in the owner's name. Only the deny rules, a
seatbelt, would stop it. The codespace has the same gap today (door 3).

| | A. The owner's identity | B. A machine user |
|---|---|---|
| How | The session pushes `claude/*` and asks a workflow on `main` (`repository_dispatch`, to be tested through the proxy) to have the App open the pull request | A second GitHub account (`arip-dev-bot` or similar) with write access, not an admin and not a code owner, is what the Claude account connects to GitHub |
| Cost | nothing | one more seat on GitHub Team, about $4 a month |
| Required approval | works, but a session holding the owner's identity can give it | a wall: the bot cannot approve its own pull request, and nothing in a session can act as the owner |
| Extra code | one workflow | none |

**Decided: B** (2026-11-10). It is what companies do (a bot account,
never a person's), it closes door 3 for every kind of interactive session
at once, and it removes a workflow instead of adding one. The owner's
personal access token in the codespace can then be deleted. GitHub is
reached through a proxy that is part of Claude's cloud sessions: there
is nothing to set up or run.

**Doors after 2d:** door 2 closed for everyday work (no AWS in Claude's
jobs), door 3 closed (own identity + required approval), door 1 guarded by
the owner's approval, the allowlist check, staging before promote, and the
SCP. Open on purpose: interactive infra sessions with the owner's admin
login, covered by the SCP.

**Done when:** an issue labeled `approved` becomes a Claude PR that the
owner approves, which deploys to staging, without anyone opening a
codespace.

### 2e. Native apps: TestFlight and Android

Decided 2026-11-10: as early as possible, not Phase 4 of `CLAUDE.md`.

- **One codebase:** `web/` wrapped with Capacitor. The PWA stays (the
  labeling desk on a computer, and the fallback).
- **Built in CI, no Mac to own:** Android on the Linux runners; iOS on
  GitHub's macOS runners (ten times the minutes of Linux), signed and
  uploaded to TestFlight by script.
- **Known work:** Google blocks sign-in inside an embedded web view, so
  sign-in moves to the system browser sheet with a link back into the app;
  Cognito's callback and the media bucket's CORS must accept the app's
  origin; uploads with the app closed on an iPhone need a native plugin
  (the reason to wrap at all, `docs/app-backlog.md`).
- **The first builds talk to staging.** Which is why this follows 2b and 2d.
- **The owner's part, days of waiting, start any time:** the Apple
  Developer Program ($99 a year; an individual enrollment is quick, an
  organization needs a legal entity) and a Google Play Console account
  ($25 once, identity verification; check its closed-testing requirement
  for new personal accounts before planning a public release).
- **Feedback:** TestFlight's own feedback becomes a second source for the
  2d pipeline, as the owner's original spec had it.
- **State, 2026-11-10:** the owner has paid for the Apple Developer
  Program; the enrollment is pending. Nothing is built yet.
- **Cost to plan for:** GitHub Team includes 3,000 Actions minutes a
  month and a macOS minute counted as ten when this was written (check
  the current rate), so an iOS build of 15 minutes costs 150. iOS builds run for a release candidate or on request, never
  on every merge.

**Done when:** a merge produces a TestFlight build and an Android internal
test build of the same commit, both signed in against staging.

### 2f. Knowing when it breaks (built 2026-11-10, PR #51)

Nothing tells anyone when production fails. In October, 48 photos stalled
for an hour and it was found by looking. CloudWatch alarms on the
Lambdas' errors and the API's 5xx answers, sent by email
(`infra/main/alarms.tf`; what each alarm means: `docs/deploy.md`, "When
an alert email arrives"). It took `sns` on the service allowlist, and
the alarm and topic resource types on the plan check's list and in the
deploy role. Free at this size.

**Done when:** a Lambda made to fail on staging sends an email within
minutes.

## Review against industry practice (2026-11-10)

The owner's goal is experience as close to a company's as a student's
budget allows. An honest comparison, to be redone after each phase.

**As a company would do it:** one AWS account per environment under an
organization, SSO and OIDC with no long-lived keys, service control
policies, infrastructure as code with a plan on every pull request and
applies only by pipeline, trunk-based development, the same commit
promoted from staging to production, secrets outside the state, budgets
that act, a decision log and runbooks with incident notes. The split of
agents by what their tokens can do is ahead of common practice.

**Where it differs, most important first:**

1. **No automated test of the app's screens, and none end to end.** The
   Lambdas have unit tests; `web/` has none, and nothing checks a deploy
   beyond "it applied". A team would not let several authors, human or
   agent, change a UI without them. **Started in PR #52:** ten browser
   tests against the real handlers, with screenshots kept by CI. Still
   missing: the same tests against staging after a deploy.
2. **No alerting.** Built in PR #51 (2f).
3. **Review.** In a team a second engineer who understands the change
   approves it. Here the owner approves plans and outcomes, not code.
   That is the experience of a technical lead; interviews for
   infrastructure roles also test the hands: reading a diff, a plan, a
   policy, debugging a failed deploy. Worth doing by hand on purpose:
   read every infrastructure diff before approving it, and now and then
   break staging and find the cause without Claude.
4. **The platform is ahead of the product, on purpose** (Decisions,
   2026-11-10: the platform is what the owner is here for). Three weeks
   of accounts and pipelines for an app with 19 cats and a few users. The numbers that
   make the project real (re-encounters, auto-resolved queries) were last
   measured on 2026-10-29. The one thing the product must keep
   supplying is real use: a platform nobody uses is never tested by
   traffic, incidents or users' reports.
5. **A person's token in an agent's hands** (door 3, and the personal
   access token made on 2026-11-10). Option B above, decided; waits for
   the owner to create the account.
6. **Home-made where a standard tool exists.** `check_plan.py` is
   policy-as-code (the standard names: OPA with Conftest, Checkov,
   Trivy); `org-apply.sh` is what Atlantis or Terraform Cloud do; account
   setup by hand is what Control Tower does. At this size the small
   scripts are the better choice, and knowing the standard names is what
   an interview asks. A free scanner (Trivy or Checkov) in CI is cheap to
   add. Dependabot reported 164 alerts on `main`, 20 of them critical:
   all one package, Pillow below 13.0.0, counted once per requirements
   file. Dependabot never proposed the fix because major versions are
   ignored on purpose. Closed by PR #50.
7. **History inside the rules.** `CLAUDE.md` and this file carry dated
   history next to current rules. Teams keep one decision per file (an
   ADR) and a changelog, and keep the rules short.

**Already right, and easy to miss:** point-in-time recovery and deletion
protection on the data table, versioning on the media bucket.

## Phase 3 — Design system and the designer's workflow

- **Design tokens:** extract colors, type scale, spacing, radii, shadows from
  `web/` and `site/` into one CSS custom-properties file (e.g.
  `web/tokens.css`), used everywhere; no hard-coded values left in
  component CSS.
- **Figma:** a design-system file mirroring those tokens and the existing
  components (Capture, Queue card, picker, Stats panels, install page).
  Claude can read Figma through the Figma connector and turn a frame into a
  PR.
- **Flow:** design in Figma → PR (Claude or the designer) → review on
  staging from a phone → merge → promote.
- **Designer access:** GitHub collaborator with write (PRs only; ruleset
  protects `main`), Figma, the staging URL, a staging collaborator/admin
  account in the app. **No AWS access.**
- Short `docs/design.md`: where tokens live, how to preview, how to open a
  CSS-only PR.

**Done when:** a visual change can go from a Figma frame to staging as one
small PR that touches tokens or one component, without the owner editing
code.

## Phase 4 — The recognition model as its own product

- **Model contract** (`docs/model-contract.md`, in both repos): input
  preprocessing (resize, normalization, crop), output embedding size and
  normalization, ONNX opset, the `manifest.json` schema, version = content
  hash, and the browser runtime it must run on (ONNX Runtime Web version,
  WASM, memory budget).
- **New repo `bgucats-recognition`:** move `research/` there with its
  history. Own CI (eval on public data, export, contract tests), its own
  heavy dependencies; nothing from it enters the app's `requirements`.
- **Releases, not merges:** the model repo publishes a versioned artifact
  (ONNX + manifest + eval report) as a GitHub Release. The app repo pins a
  model version; upgrading is a PR that bumps the pin. The deploy pipeline
  publishes the pinned model to the web bucket (replacing hand-run
  `make model-publish`).
- **Evaluation stays honest:** a model bump PR includes its eval report;
  staging's Stats → Recognition replay compares against the current model
  before promote. Split by session, never by photo; open-set; public-data
  numbers never reported as the system's accuracy.
- **Dataset access:** a production job writes versioned exports to
  `exports/{datasetVersion}/` (EXIF stripped, locations rounded, split by
  session). Identity Center group `bgucats-ml` with a permission set that
  can only `s3:GetObject`/`ListBucket` on that prefix.

**Done when:** a new model can be trained, released and rolled out by
someone who has never had production access, and rolled back by reverting
one pin.

## Phase 5 — People

| Role | GitHub | AWS (Identity Center group) | Other |
|---|---|---|---|
| Owner (infra) | admin on all repos | `Admins` — everything | merges, promotes to production |
| ML engineer | write on `bgucats-recognition` | `bgucats-ml` — read dataset exports | own GPU / training environment |
| Designer | write on `BGUcats` (PRs) | none | Figma, staging URL |
| Claude | its own GitHub App (2d): opens PRs, no `workflows`, no admin | none in CI; in interactive sessions, only the owner's session, at the owner's request | never merges, never approves, never holds AWS credentials of its own |

- Onboarding doc per role: what to install, where to start, who reviews.
- Offboarding: remove from the group / repo; nothing personal to rotate,
  because no one holds long-lived keys.

## Later (not planned yet)

- **Custom domain** for the app and landing page, so QR codes survive any
  future infra change. Needed before printing new posters.
- Per-PR preview environments (only if staging becomes a bottleneck).
- Codifying Identity Center groups and permission sets in Terraform
  (an `infra/org` root, applied by the owner).
- Product phases 2–4 from `CLAUDE.md` run on top of this platform.
- **WAF** in front of API Gateway and CloudFront, once the app is public
  (Phase 2c, DDoS).

## Never

- Long-lived environment branches.
- IAM users or access keys, for anyone, including CI.
- Claude merging, approving deploys, or holding AWS credentials of its own.
- Claude's CI jobs requesting an OIDC token, or its GitHub App holding the
  `workflows` permission.
- Expensive services (RDS, NAT gateways, EC2, …) appearing as a side effect
  of a PR: they are denied by SCP until the owner lifts it (2c).
- Real contributor photos in staging or in the model repo.
- A softmax classifier over our cats (`CLAUDE.md`).
