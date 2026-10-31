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
- **Claude is a contributor, not an operator.** It writes code and opens PRs
  in any repo. It never holds write credentials to AWS, and never merges.

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

## Where we are (updated 2026-10-31)

| Area | State |
|---|---|
| AWS Organization | Created. Management account `851725214678` (to end up running nothing). Identity Center with group `Admins` (AdministratorAccess, ReadOnlyAccess). |
| Production account | `sasha-bgucats-prod` `395591097129`. Bootstrapped (state bucket, lock table, OIDC provider, CI role, deploy role, permissions boundary). |
| CI/CD | PRs run `python` + `terraform` (plan). Push to `main` runs **Deploy** (OIDC, environment `production`). Ruleset on `main`: PR required, both checks required, no bypass. |
| Data | Copied and cut over on 2026-10-30 (`docs/MANUAL_STEPS.md` steps 7–8). The old account keeps its copy until step 9, not before 2026-11-13. |
| WhatsApp bot | Removed from code (PR #4). Old account copy runs until decommission. |
| Repo | Single repo `sasha720709/BGUcats`: `src/` (Lambdas), `web/` (PWA), `site/` (landing), `infra/`, `research/` (imports nothing from `src/`), `scripts/`. |
| Secrets | **Outside Terraform since 2026-10-31** (PR #12): SSM values and Cognito's Google provider are set by `infra/scripts/set-secret.sh`, owner-only. CI and deploy roles have no access to them (PR #14, bootstrap applied by the owner 2026-10-31; the CI plan with the restricted role shows no changes). Telegram bot token, webhook secret and Google client secret rotated by the owner 2026-10-31. Salt deliberately not rotated. |
| Telegram bot | A stopgap, not a product line: the app's Capture is the real upload channel. Kept working while the landing page points to it; no long-term plans around it (e.g. staging needs no test bot). |
| GitHub plan | Personal Pro, student (environments + branch policies on private repos; **no** required reviewers). The owner's merge is the only gate. |

---

## Next session starts here (2026-10-31)

**Phase 1, secrets gap: done** (PRs #12, #14, #15; bootstrap applied;
rotation done). Owner, before anything else:

- Confirm the rotation worked, if not already: the bot answers a photo;
  Google sign-in in the app works; the **old Google client secret is
  disabled and deleted** in Google Cloud → Credentials.
- Delete the five unused `production` environment secrets in GitHub, if
  not already: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `SUBMITTER_HASH_SALT`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
  (keep `BOOTSTRAP_ADMIN_EMAIL`).
- Delete merged branches; turn on Settings → General → *Automatically
  delete head branches* (a stacked PR, #13, merged into its base branch
  instead of `main` because the base was not deleted).

**Next: Phase 2a, the GitHub organization**, done together step by step.
Claude proposes its steps as text first. The rest of Phase 1 (SHA-pinned
actions, Dependabot, PR/issue templates, plan summary as a PR comment,
budgets) is not started and can be done between owner steps.

Small open item: `set-secret.sh` should delete its temp file on Ctrl-C too
(a `trap`), not only after the `aws` call.

## Phase 0 — Finish the move

Owner-driven; follows `docs/MANUAL_STEPS.md`.

- Pre-copy media + model; `verify --only ssm` = `same` ×3.
- Delete the WhatsApp Meta app before the cutover evening.
- Cutover (`scripts/cutover.sh`), reinstall the app on phones, smoke test.
- Next day: `verify --only table` → `missing` = 0.
- Two weeks later: decommission the old account (step 9), keys and the
  `sasha-bgucats-admin` IAM user deleted; 30 days after, old data deleted.
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

- Create the organization; choose its plan (Free if environments work for
  private repos there, else Team).
- Transfer `BGUcats` into it. **The transfer changes the OIDC subject**
  (`repo:sasha720709/BGUcats:…` → `repo:<org>/BGUcats:…`), so the bootstrap
  trust policies must accept the new name before the transfer and drop the
  old one after it — or CI and deploys are refused.
- Check that environments, environment secrets, variables and the ruleset
  came across; recreate what did not.

**Done when:** a PR in the organization's repo passes CI, and its merge
deploys.

### 2b. Staging account

- New member account `bgucats-staging`, created in Organizations; `Admins`
  assigned; covered by the same SCPs.
- Same Terraform, its own backend file (`infra/main/backend/staging.hcl`),
  its own bootstrap (OIDC, CI/deploy roles scoped to environment `staging`).
- Own secrets: **a separate Telegram test bot**, own Cognito domain prefix
  (e.g. `bgucats-staging`), its Google redirect URI added to the OAuth client
  (or a separate OAuth client), own salt.
- **Pipeline:** merge to `main` → deploy **staging** automatically.
  Production deploys only via a manual **Promote** workflow that deploys the
  *same commit SHA* that staging already runs (or a `v*` release tag).
  GitHub environment `staging` (branch `main`) and `production`
  (deployments only from the promote workflow).
- **Data:** staging never receives real contributor photos. A seed script
  creates sample cats/sessions from public-domain or own test images.
- The landing site and QR codes stay production-only.

**Done when:** a merge appears on staging within ~20 minutes without
touching production, and promoting deploys an identical build to
production.

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
| Claude | opens PRs in any repo | none (at most read-only on staging) | never merges, never holds AWS write |

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

## Never

- Long-lived environment branches.
- IAM users or access keys, for anyone, including CI.
- Claude merging, approving deploys, or holding AWS write credentials.
- Real contributor photos in staging or in the model repo.
- A softmax classifier over our cats (`CLAUDE.md`).
