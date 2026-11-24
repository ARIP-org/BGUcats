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
| 2026-11-11 | **The iPhone app carries `web/` inside it; it never loads it from the server.** Capacitor documents the remote mode for development only, Apple's review can refuse "a website in a wrapper", and Capture must open with no signal. The cost: a merged change reaches the iPhone app only with a new build. Live update (the app downloads a newer copy of `web/` from our own server) comes once the app works. |
| 2026-11-11 | **iPhone builds on GitHub Actions, not Xcode Cloud.** Xcode Cloud is free up to 25 hours a month and signs by itself, but its first workflow can only be created in Xcode on a Mac, it needs Apple's GitHub app on the private repo, and its settings live in App Store Connect where no pull request reviews them. A build on Actions costs about $1. |
| 2026-11-12 | **Build the app the prototype shows, for TestFlight** (Phase 4 of `CLAUDE.md`, no longer deferred): feed, posts, name polls, friends, profile, achievements, map, the capture flow, with moderation and re-ranking on Google's Decision 1. New AWS resources are allowed for it. The plan, the owner's open decisions and the owner's manual steps are `docs/app-plan/`. The row of 2026-11-07 about the fear of "we need a relational database" still stands: the plan recommends against one, and the owner decides (`DECISIONS.md`, A1). |
| 2026-11-22 | **Low-risk pull requests merge to staging without the owner** (2g). Pull request #98 passed CI in twenty minutes and waited six days for an approval. What is low-risk is decided by paths GitHub enforces, not by an agent; production still moves only on the owner's tag. |
| 2026-11-22 | **The iPhone app is rewritten in Swift, now; the web member app is frozen and will be retired** (2g). Supersedes "one codebase, never platform branches" (2026-10-31, below) and "the iPhone app carries `web/` inside it" (2026-11-11) for the member app. The owner wants native features and an app that feels native. The labeling desk stays a web app. |
| 2026-11-23 | **The Swift app ships to TestFlight now, unfinished, in the same app** (the owner). Not a second app beside the packed one, and not when it has every screen: the owner wants the system's glass, the flaws and the distance from the prototype on the phone early, and to watch them being fixed. TestFlight loses the packed app's screens until each is rebuilt; the home-screen app keeps them. Supersedes "the packed app stays what TestFlight gets until the Swift app has its screens" (2g, 2026-11-22). |
| 2026-11-22 | **A chain of agents, with no server of the owner's** (2g): planner, builder, reviewer, an iPhone verifier, a daily digest. How Mac time is paid for is open: 2g, "What Mac time costs". |
| 2026-11-22 | **Each role has a model of its own** (the owner): the planner on Fable, because it decides what is built; the builder and the reviewer on Opus; triage and the digest on Sonnet. A builder on Fable costs more than it returns. `docs/agents.md`, "Which model". |
| 2026-11-22 | **The repository goes public** (2g, "What Mac time costs", way B), when the owner changes its visibility. Paying by the minute for a factory was $80 to $390 a month and the owner will not spend $30; a public repository's standard runners are free, macOS too. Supersedes "private repos ... not public repos" (2026-10-31). What it takes first: `docs/agents.md`, "When the repository is public". |
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

## Next session starts here (2026-11-10, night)

Phases 0, 1, 2a, 2b, 2c and 2d are done, except the rows marked below.
The whole loop has run at least once: an issue became a pull request by
the Fix agent (#59), a cloud session opened one as the machine user
(#57), merges deploy staging, and the smoke test gates the mark a promote
needs.

| | State |
|---|---|
| Staging | deployed by every merge, seeded (`make seed-staging`), model published, alarms live and proven |
| Smoke test after every staging deploy (#58) | live; passed in the deploy job |
| Guardrails | the allowlist (with `sns`) is on the root; production runs under it |
| Triage and Fix agents | both have run. Fix's first pull request, #59, was merged |
| Hands-on cloud sessions as `arip-dev-bot` | work (#57) |
| Required approval on `main` | **on** (1 approval). "Require review from Code Owners" is still off |
| The owner's personal token in the codespace | deleted; the codespace has the bot's token instead (it loads when the codespace next starts) |
| Headless models | branch `claude/headless-models`: Fix on Opus, Triage on Sonnet by name. Needs a pull request opened as the bot |
| **First promote (a `v*` tag)** | **never exercised.** Production still lacks the alarms, Pillow 13, the consistent-read fix (#53) and the photo-count fix (#59) |
| The freeze policy's exemption for the Lambda roles | not proven yet (12g) |
| The owner signing in to the staging app on a phone | not done |
| Apple Developer Program | approved 2026-11-11. Bundle ID `org.arip.bgucats`, the app's record, an API key and the `testflight` environment (with `APPLE_TEAM_ID`) are made (`docs/MANUAL_STEPS.md`, step 15) |
| 2e, the iPhone app | **started 2026-11-11:** the Capacitor shell (`native/`) and the build workflow (`ios.yml`). The first build (3) was signed and uploaded to App Store Connect the same day and runs on the owner's phone. Sign-in through iOS's sign-in sheet is written; it works from the first build made after its Terraform is deployed |

**Next, in order:**

1. **The first promote** (the owner): tag a commit with a green
   `deployed/staging`. The production plan will show the alarms, the
   Lambda updates and nothing else. Then one confirmation email from AWS
   for production's alerts.
2. **2e, the iPhone app** (started 2026-11-11, the owner's go; bundle
   ID `org.arip.bgucats`). The shell, the simulator check and the upload
   job are written. In order from here (the list under 2e, below):
   1. the first build on the owner's phone: it is uploaded (build 3,
      2026-11-11); what is left is a TestFlight group with yourself in it
      (`docs/MANUAL_STEPS.md`, 15b);
   2. sign-in through the system browser: written (2026-11-11). Merge,
      let staging deploy, then make a new build and sign in on the phone.
      The Swift part has only ever been compiled, never run by a person;
   3. live update, then uploads with the app closed;
   4. Android, after TestFlight works (the owner's order, 2026-11-11).
3. **The reviewer agent:** comments on every pull request.
4. **12g, the rest:** the freeze policy attached to staging for a minute;
   the API must keep answering. An organization change, so the owner's
   command.
5. Tick "Require review from Code Owners" on the `main` ruleset.

**Where work happens from here:** cloud sessions for anything that ends
in a pull request; the codespace only for jobs that need AWS by hand
(`docs/agents.md`). A cloud session knows what is in this repo and
nothing else, which is why this section and `docs/notes.md` are kept
current.

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

**Superseded for the iPhone's member app on 2026-11-22** (2g): it is
being rewritten in Swift. What follows is how today's TestFlight app is
built, and stays true until the Swift app's first build replaces it.

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
- **Cost to plan for:** GitHub Team includes $18 of Actions usage a
  month. A macOS minute is $0.062 and a Linux one $0.006 (2026-11). The
  check of the shell took under three minutes on 2026-11-11, about $0.20;
  a TestFlight build is that job and a second one of under two minutes,
  about $0.30 together. iOS builds run for a release candidate or on
  request, never on every merge.
- **The slow loop, and what keeps it short.** With no Mac there is no
  simulator on a desk and no console to attach: a try of anything
  native-only is build → Apple's processing → TestFlight → the phone,
  20 to 30 minutes. So the native layer stays thin, screens stay web and
  are checked in the PWA and `tests/web`, and the workflow starts the app
  in a simulator and keeps its screenshot and log.

**State, 2026-11-11.** Apple approved the enrollment. Built, in one pull
request: `native/` (Capacitor 8, the generated Xcode project, the app's
icon), `scripts/native_bundle.py` (packs `web/` with staging's config and
the API's address), the few lines of `web/` that know they are packed
(`isNative` in `install.js`), and `.github/workflows/ios.yml`. How it is
built and run: `docs/deploy.md`, "The iPhone app".

**Proven the same day:** the `testflight` job. Build 3 was archived
unsigned, signed at export with a certificate Apple keeps, and uploaded,
with no change to the workflow. What stopped the first attempts was a
setting, not the code: the Team ID had been added as a secret, and the
workflow reads the variable `APPLE_TEAM_ID`.

**What is left, in order:**

1. **The first build on the owner's phone.** Uploaded; it needs a
   TestFlight group. It opens on the sign-in screen and says sign-in is
   not connected.
2. **Sign-in.** Written 2026-11-11, not yet tried on a phone. iOS's
   sign-in sheet (`ASWebAuthenticationSession`) through a small plugin of
   our own, `native/plugins/web-auth`; Cognito answers at
   `org.arip.bgucats://signin`; the API has a CORS configuration and the
   media bucket lists the app's origin (`docs/deploy.md`, "The iPhone
   app"). Terraform, so staging first, then the build.
3. **The recognition model in the app.** Written 2026-11-12 (N1 of
   `docs/app-plan/`): the app fetches `/model/` from the site, which
   answers with CORS, and keeps the files in IndexedDB. Merge, let
   staging deploy, then a new build; on the phone, a scan should offer
   three cats.
4. **Live update:** the app downloads a newer copy of `web/` from our own
   server, so a merge reaches it without a build.
5. **Uploads with the app closed** (`URLSession` background uploads): the
   reason to wrap at all (`docs/app-backlog.md`).
6. **Location without a second question.** A web view asks for the
   location once as the app and once as the page.
7. **Android,** after TestFlight works.

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

### 2g. The factory: shipping without the owner in every loop (decided 2026-11-22)

**Why.** The owner approves every pull request, and that is now the
slowest step by far: #98 was green twenty minutes after it opened and
merged six days later; #97 waited nine hours. More agents do not change
that. Who merges what does.

**What the owner decided** (2026-11-22): low-risk pull requests merge to
staging by themselves; the iPhone app is rewritten in Swift and the web
member app retires; the work is done by a chain of agents with no server
of the owner's. Open: how Mac time is paid for (below).

#### The chain

2d built the first two (`docs/agents.md`). Each role is separated by what
its token can do, not by what its prompt says.

| Role | Starts when | Does | Cannot | Runs as |
|---|---|---|---|---|
| **Planner** | once a day; when the owner leaves feedback | turns the plan, the owner's notes, failures and reports into small issues, each with a "done when" | write code, label an issue `approved` for work nobody asked for | a cloud session of its own, woken daily |
| **Builder** | an issue is in the queue (`approved` by the owner, or `ready`) and fewer than three pieces of agent work are open | one issue, one pull request, with tests and screenshots | merge, reach AWS, change the rules, start on a label an agent put on | the Fix workflow (2d), or a cloud session for what it cannot touch |
| **Reviewer** | a pull request opens or changes | reads the change and its screenshots with nothing of the builder's context; passes it, sends it back, or sends it to the owner | change code, approve as a person | a workflow on `main`'s copy of itself, whose result is a required check |
| **iPhone verifier** | a pull request touches the iPhone app | builds it, runs its UI tests in a simulator, keeps screenshots for the reviewer | upload to TestFlight | a macOS job |
| **Digest** | once a day | tells the owner what merged, what waits on them, what needs a decision | anything else | a cloud session of its own, woken daily |

#### Two lanes

- **Green lane: merges by itself.** CI passes, the reviewer's check
  passes, and the pull request touches no owner path. GitHub's own
  auto-merge does it; no agent decides to merge. (Claude's own safety
  check refuses to merge a pull request no person approved, and the
  design agrees with it.)
- **Owner lane: waits for the owner.** Anything that touches an owner
  path, and anything the reviewer sends up.

**Owner paths** (`.github/CODEOWNERS`, with "Require review from Code
Owners" on the `main` ruleset): what is there today (`.github/`,
`.claude/`, `CLAUDE.md`, `infra/bootstrap/`, `infra/org/`,
`infra/scripts/`, the resource allowlist, the plan check), widened to
all of `infra/`, every `requirements*.txt` and `web/vendor/` (a new
dependency is a decision), `src/common/admission.py` and the sign-up
trigger (who may sign in), the iPhone app's signing and entitlements, and
this file's decisions.

**What stays exactly as it is:** production moves only on the owner's
`v*` tag; no agent has AWS; the service allowlist, the budgets that act
and the plan check; staging holds no real contributor's photo.

**What is new and must hold:**

- The reviewer's result is a **check from a workflow**, not an approval
  and not a label. A builder can add a label; it cannot run `main`'s
  workflow with a different answer.
- The reviewer never runs the pull request's code. It reads the diff, the
  CI result and the screenshots.
- At most three agent pull requests are open at once, and one repository
  variable (`AGENTS`, set to `off`) stops every agent workflow at its
  first step.
- The digest is how the owner stays in the loop without being the loop.

**Said plainly:** the reviewer is the same kind of model as the builder
and shares its blind spots. What covers that is tests, screenshots,
staging before production, and the owner's tag.

#### Where the work comes from

1. `docs/app-plan/08-milestones.md`: what is not built.
2. The prototype against the built screens, screenshot by screenshot.
3. Failures: a red check, an alarm, an "App info" someone pasted.
4. The owner's feedback, whenever it comes: an issue, a comment, a note
   in a session. The planner picks it up; nothing waits for it.

Agents carry out a direction and find defects. An idea for a feature
nobody asked for goes into an issue labeled `proposal` for the owner, not
into code.

#### The iPhone app, in Swift

- **`native/` becomes a SwiftUI app.** It talks to the same member API
  (`/api/v1/`, `docs/app-plan/04-api.md`), signs in through the same
  sheet, and keeps the write order and the ULIDs made on the phone. The
  recognition model runs through Core ML or ONNX Runtime's iOS build: to
  be measured against the browser's numbers before it replaces them.
- **It is what TestFlight gets, from its first screens** (the owner,
  2026-11-23): the same app to Apple (`org.arip.bgucats`), so a build is
  an update of the packed one. A tab not built yet says so. The upload
  archives it with the script every pull request ran
  (`scripts/ios_archive.py`).
- **The web member app is frozen:** fixes only, no new screens. It
  retires when the Swift app has every screen the plan's L1 gate lists.
  Until then it is where a screen the Swift app lacks is found: the
  home-screen app.
- **The labeling desk and Capture stay a web app** for admins and
  collaborators; `web/` loses nothing of theirs.
- **No screen without a picture.** Swift cannot be compiled on Linux, so
  an agent writing it is blind until a Mac builds it. The verifier comes
  first: a UI test target that opens each screen in a simulator against a
  stand-in for the API and saves a screenshot, as `tests/web` does today.
  Screens follow in the plan's order (the frame, the feed, capture, cats,
  profile), each compared with the prototype.
- **What a simulator cannot show:** the camera (photos are injected), a
  real notification's delivery, and how the app behaves on a real phone
  under real memory. That stays the owner's on TestFlight, and "App
  info" moves into the Swift app with the first screen.

#### What Mac time costs

Prices as GitHub's pages gave them on 2026-11-22; times measured in this
repository in November 2026.

| Run | Time | Price |
|---|---|---|
| CI on a pull request, or on `main` (Linux, two jobs) | 18 to 20 minutes | $0.12 |
| A deploy (Linux) | 5 to 6 minutes | $0.03 |
| The simulator check of today's packed app (macOS) | under 3 minutes | $0.19 |
| A TestFlight build (macOS, two jobs) | about 5 minutes | $0.30 |

A Linux minute is $0.006 and a macOS minute $0.062. The organization's
plan (GitHub Team) includes **$18 a month**, charged to the organization:
the owner's personal Pro plan does not count here. That is 3,000 Linux
minutes or 290 macOS minutes. November 2026 had used about $15 of it by
the 22nd with no factory (an estimate from run counts: about 190 CI
runs, 50 deploys, 10 iPhone runs; the organization's billing page has
the real figure).

A merged pull request costs about $0.30 on Linux today (CI on the pull
request, CI again on `main`, the deploy). A pull request to the Swift app
adds a build and its UI tests, estimated at 8 to 12 minutes ($0.50 to
$0.75) and two to four times per pull request, because the Mac is the
compiler: **$1 to $3**. To be measured on the first build.

| Pace | Linux | Swift pull requests | A month |
|---|---|---|---|
| 2 a day, half of them Swift | $18 | 30 at $2 = $60 | about $80 |
| 10 a day, half of them Swift | $90 | 150 at $2 = $300 | about $390 |

**Three ways to pay,** and one to check:

| | A. By the minute, capped | B. A public repository | C. A rented Mac as the repository's own runner |
|---|---|---|---|
| Cost | as the table above, up to a budget set in GitHub | $0: standard runners are free on public repositories, macOS too | a flat rent: Scaleway listed an M1 at €75 and an M4 at €149 a month (to confirm on the day) |
| Good | nothing to set up | the whole problem goes away | every job is free, Linux ones too; the only way an agent could drive the simulator by hand |
| Bad | the factory's pace is the bill | the code and its history are public: needs a check of the history first, and a decision that this is a portfolio project in public | a machine to keep alive, patch and secure; the server the owner did not want |
| Break-even | | | about 1,300 macOS minutes a month, 45 a day |

To check: Xcode Cloud includes 25 hours a month, but its first workflow
can only be made in Xcode on a Mac (decided against on 2026-11-11 for
that reason).

**Chosen 2026-11-22: B.** The owner will not pay by the minute at any of
these paces and does not want a machine to keep. The repository goes
public when the owner changes its visibility; what the workflows needed
first is done (`docs/agents.md`, "When the repository is public"). Until
that day the Swift work does not start, because each of its builds
would be paid for. (The recommendation had been A for two weeks to
measure, then B or C.) Whichever is chosen, two savings are free: do
not run the whole suite a second time on `main` when the branch was up
to date, and skip the browser suite for a change that touches no code.

#### What only the owner can do, once

1. *Settings → General:* allow auto-merge.
2. *The `main` ruleset:* required approvals from one to none, "Require
   review from Code Owners" on, and the reviewer's check added to the
   required checks, **after** the reviewer's workflow is on `main` (a
   required check that never runs blocks every pull request).
3. *The organization's billing:* a payment method and a budget for
   Actions, or the decision to go public.
4. *Optional:* let a merge to `main` that touches the iPhone app start a
   TestFlight build by itself (today only the owner starts one).

Not asked for, on purpose: admin for the bot account (it could then
change the rules it works under), the `workflows` permission for the Fix
App, and any AWS access.

#### Order, and done when

1. The reviewer's workflow, the wider owner paths, the `AGENTS` switch;
   then the owner's settings. **Running since 2026-11-23**
   (`docs/agents.md`, "The reviewer, and the two lanes"); the owner
   changed the `main` ruleset the same day. **Done when** a pull request
   that touches no owner path merges with no person involved, and one
   that touches one waits. **Half seen 2026-11-23:** #120 (the Swift
   app's sign-in and feed) was sent back by the reviewer once, fixed,
   passed, and merged by auto-merge with nobody's approval. **The other
   half failed the same day:** #121 touched a workflow and this file,
   the reviewer passed it, and it merged with nobody's approval too. The
   ruleset was not requiring a code owner's review; #118 and #119 had
   waited only because the reviewer sent them up. Since then the
   reviewer's script holds every owner-path change for the owner
   (`docs/agents.md`, "The owner's lane is held twice"), and the
   ruleset's setting is the owner's to turn on. **Done when** a pull
   request that touches an owner path and that the reviewer would pass
   is seen to wait.
2. The planner and the digest, as scheduled cloud sessions. **Written
   2026-11-22** (`docs/agents/planner.md`, `docs/agents/digest.md`;
   `docs/agents.md`, "The planner and the digest"); scheduled the same
   day, each in a session of its own. The repository went public the
   same day, and the builder takes the planner's `ready` issues by
   itself (`docs/agents.md`, "The builder's queue"), and since
   2026-11-23 answers a review that was sent back, twice at most.
3. The Swift app's skeleton and its verifier, on a pull request, with
   the first screenshot from a simulator. **Written 2026-11-23**
   (`native/swift/`, the `swift` job of `ios.yml`): four tabs of system
   controls and "App info", each pictured in light and dark.
4. The upload to TestFlight is the Swift app. **Written 2026-11-23**
   (the `testflight` job of `ios.yml`). **Done when** the owner's phone
   has the frame from TestFlight; then the packed app's code
   (`native/ios`, `native/plugins`, `scripts/native_bundle.py`, its
   `simulator` job) is removed.
5. Screens, in the plan's order: signing in and the feed first, then
   capture, cats, profile. Each lands in the next build the owner starts.
   **Signing in, the feed and the profile's first rows: merged
   2026-11-23** (#120), pictured in a simulator from a made-up member.
   Not tried on a phone yet: the real sign-in sheet, the keychain, the
   feed against staging. **Scan a cat, first half** (#125, 2026-11-24):
   photos taken or chosen from the gallery, sent as one encounter by the
   web app's routes and write order, through a queue kept on the phone.
   Not tried on a phone yet: the real camera, a real fix from GPS, a
   large photo over a phone's connection. The second half (the cat, a
   new cat, the post) is its own issue.

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
- **Rewriting the backend in a faster language** (Rust, or C), the
  owner's idea of 2026-11-10: the Lambdas are Python today. Measured in
  production over the two weeks before that day, so the decision starts
  from numbers:

  | Lambda | Calls | Average | 95th percentile | Cold start adds |
  |---|---|---|---|---|
  | admin (the API) | 962 | 225 ms | 692 ms | about 540 ms, roughly one call in ten |
  | process (per photo) | 450 | 151 ms | 804 ms | about 860 ms |
  | ingest (the bot) | 30 | 743 ms | 1.8 s | |

  What a rewrite would buy: Rust on Lambda starts cold in tens of
  milliseconds instead of half a second, and uses a fraction of the
  memory. That is the part a person feels, on the first tap after a
  pause. What it would not buy: most of a warm call is spent waiting for
  DynamoDB and S3, which no language shortens, and the image work is
  already C (Pillow, libwebp). Cheaper things to try first, each one
  line of Terraform or a few of Python: `arm64`, more memory (which is
  also more CPU), fewer round trips per request. If it is done, it is
  done one Lambda at a time behind the same API, with the browser tests
  and the smoke test as the proof that nothing changed: `process` or
  `beacon` first, the API last. As a learning project it needs no other
  reason.

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
