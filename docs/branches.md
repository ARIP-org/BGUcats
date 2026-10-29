# Branches — what lives where

Updated 2026-10-29. The same file is on every branch; when a branch's role
changes, update it everywhere.

| Branch | What it is | Deployed? |
|---|---|---|
| `app-preprod` | **Production.** `admin-labeling-tool` + the installable app: roles (admin / collaborator), Capture, presigned uploads. Runbook: `docs/deploy-app-preprod.md`. | **yes, live since 2026-10-28** |
| `recognition-labeling` | `app-preprod` + the research track merged in + **phase 1c**: the recognition model runs in the admin's browser, guesses every queue session blind, and Stats measures it (live record + replay). Runbook: `docs/deploy-recognition-labeling.md`. | not yet — next to deploy |
| `admin-labeling-tool` | The previous production: bots (Telegram, WhatsApp), process Lambda, landing page, labeling tool, Stats. The rollback target for `app-preprod`. | was live until `app-preprod` |
| `claude/hopeful-feynman-l098o2` | **Research track (phase 1b)**: `research/catreid` (MegaDescriptor eval harness, splits, open-set metrics, rerank, browser export), `research/webapp` (Spotter demo), `research/FINDINGS.md`, `docs/recognition-design-addendum.pdf`. Fully merged into `recognition-labeling`; new research work can continue there. Its duplicate labeling tool was reverted — never apply infra from this branch. | never (research only) |
| `main` | The early foundation: CI, bootstrap, Telegram ingest, process Lambda. Far behind; no `site/`, `web/` or `research/`. Do not deploy from it. | no |

## Before you start

- **Check out the deployed branch before touching site, bots or the admin
  app**, and diff the deployed Lambda code against your tree before any
  apply. Deploying a stale branch silently removes features.
- Recognition work: `recognition-labeling` (it has both the app and
  `research/`).
- When a branch is deployed, change the "Deployed?" column here on every
  branch.

## Where the plan stands

| Phase | Status |
|---|---|
| 1a Collection + labeling | live (`app-preprod`) |
| 1b Recognition research on public data | done for round 1–2 (`research/FINDINGS.md`): enrollment diversity, not backbone size, is the lever |
| 1c Measure the model on BGU data | built on `recognition-labeling`; first numbers: right cat first on ~3–5 of 13 sessions, top 3 on ~9–10 of 13, 19 cats |
| 2 Enrollment + burst-query UX | next — re-encounters of known cats are what move the numbers |
| 3 Fine-tuning | conditional on 1c numbers |
| 4 Public read path | deferred |

`CLAUDE.md` on `main`, `admin-labeling-tool` and `app-preprod` still says
"no machine learning of any kind" — true of the code on those branches, and
superseded for the project by `docs/recognition-design-addendum.pdf` (on the
research and `recognition-labeling` branches).
