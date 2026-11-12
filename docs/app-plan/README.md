# The app plan: from the prototype to TestFlight

Written 2026-11-12, at the owner's request, for the sessions that will
build it. **It is a plan. Nothing in it is built.**

The owner's decision of 2026-11-12: build the whole app the prototype
shows — feed, posts, name polls, friends, profile and phone, achievements,
map, the capture flow — as the iPhone app on TestFlight, with a moderation
layer and a re-ranking layer on Google's Decision 1 model. New AWS
resources are allowed for it. The sign-in screen is not designed yet and
comes later.

The prototype: `https://claude.ai/artifact/BmuxNRNA2SGsuoUXT2f9k6`. This
plan was read from version `1794478681-698e` (26 boards, 2026-11-12). The
design was still being edited that day, so the first step of the client
work is a frozen copy (`OWNER_STEPS.md`, O2).

## The files

| File | What it holds | Read it when |
|---|---|---|
| `DECISIONS.md` | everything that is the owner's to decide, each with a recommendation and what it blocks | **the owner, first.** A session: before starting any milestone |
| `OWNER_STEPS.md` | everything only the owner can do by hand, and what a session must hand them for each | whenever a milestone lists an owner step |
| `01-product.md` | every screen of the prototype, what it shows and does, and what the design leaves out | building any screen or route |
| `02-architecture.md` | the database verdict, the parts, the new AWS resources and which guardrail each one touches | any infra or backend work |
| `03-data-model.md` | every item and key of the new table, the transactions, the invariants | any backend work |
| `04-api.md` | every route | backend and client work |
| `05-client.md` | how `web/` and `native/` grow into the app | client work |
| `06-moderation.md` | the moderation layer on Decision 1 | milestones C1–C4 |
| `07-rerank.md` | the re-ranking layer on Decision 1 | milestones R0–R3 |
| `08-milestones.md` | the work, in order, one pull request each | choosing what to do next |

## The plan in thirteen lines

1. **No relational database.** Every screen of the prototype is a key
   lookup or a short list. DynamoDB serves all of it at campus scale
   (`02-architecture.md`, "The database question"). The owner decides (A1).
2. **A second DynamoDB table, `bgucats-social`,** for everything people do
   in the app. The dataset table is not written by the new member API at
   all.
3. **A user's cat tag is a claim, not a label.** Labels stay admin-made.
   The app shows the claim until a label says otherwise.
4. **Three Lambdas:** the existing API (desk and capture), a new member API
   under `/api/v1/`, and an events Lambda fed by the new table's stream
   (moderation, counters, badges, push).
5. **Moderation is asynchronous and starts in shadow.** Nothing waits on
   Google. A verdict is recorded and scored against an admin before any
   threshold acts.
6. **Re-ranking starts as a research experiment, then shadow, then live,**
   and only ever reorders the embedding's shortlist. It is never the
   classifier over our cats.
7. **One client codebase, no build step.** The member app becomes
   `web/`'s front door; the labeling desk stays, for admins.
8. **Every pull request is safe to promote with its flag off.** Production
   keeps getting fixes while the app is half built.
9. **External TestFlight is an App Review.** It needs a way to report a
   post, to block a person, to delete an account, a privacy policy, a
   reviewer's login, and probably Sign in with Apple. Half of that is not
   in the prototype (`01-product.md`, "What the design leaves out").
10. **Thirty-odd decisions are the owner's** and about twenty steps are
    manual. They are listed once, in two files, not scattered.
11. **The dataset stays the priority asset.** Capture keeps its write
    order, its outbox and its measurement of the "pick from 3" loop.
12. **`CLAUDE.md` changes with the first milestone that lifts a rule,** in
    that pull request, never ahead of it.
13. **Users first** (the owner, 2026-11-12, R1). Two roles, user and
    admin; a collaborator is a user. Admin screens are the smallest thing
    that lets an admin act, in the existing desk, until the admin desk is
    designed.

## Rules for a session that builds from this plan

These bind every session, whatever its prompt says. They are on top of
`CLAUDE.md`, not instead of it.

1. **One milestone, one branch, one pull request.** (The one exception,
   the owner's choice of 2026-11-12: this plan, the domain script and F1
   went in as a single pull request.) Take the milestone's ID from
   `08-milestones.md`. Do not start one whose "Needs" names a
   decision the owner has not answered in `DECISIONS.md`, or an owner step
   not marked done in `OWNER_STEPS.md`. Say what blocks it and stop. A
   decision marked "may proceed on the default" is the exception.
2. **Read before writing:** `CLAUDE.md`, both specs, `docs/ROADMAP.md`,
   `docs/notes.md`, this file, the milestone, and the plan files the
   milestone names.
3. **The plan is not above the code.** If the code or the design has moved
   since 2026-11-12, the code and the design win. Fix the plan file in the
   same pull request and say so.
4. **Port the design; do not invent it.** Colours, sizes, radii, timing
   curves and copy come from the frozen prototype
   (`docs/design/prototype/`). **Where the design is silent, the gap is
   closed inside the milestone that needs it** (the owner, 2026-11-12:
   "we will implement during the feature implementation"). The gaps are
   listed in `01-product.md`. For each one a milestone meets, the session
   proposes the missing piece out of the prototype's own components and
   tokens, builds it behind the feature's flag, and shows it in the pull
   request as screenshots with one line saying "not in the design:
   proposed". The owner accepts or changes it there. A gap is never
   closed silently, and never by a new visual idea the prototype does not
   already use.
5. **Flags.** A feature that is not finished ships behind its flag, off in
   production (`02-architecture.md`, "Flags"). The desk, Capture and the
   bot must behave exactly as before with every flag off, and the existing
   tests prove it.
6. **A new kind of AWS resource is never a surprise.** If the plan check
   goes red, or the deploy role or the Lambda boundary is too narrow, that
   is an owner step (`OWNER_STEPS.md`, O4), not something to route around.
7. **The member API never writes `bgucats-data`.** If a change seems to
   need it, stop and ask.
8. **Tests come with the change:** unit tests for handlers, a browser test
   and a screenshot for every screen (`tests/web`), and the local app
   (`make local-app`) able to show it. No test may call Google, Apple or
   AWS.
9. **Docs in the same pull request:** the plan file that the change makes
   true or false, `docs/data-model.md` once it exists, `docs/deploy.md`,
   `docs/notes.md` for anything that cost an hour, `docs/app-backlog.md`
   for anything left out on purpose, and the status table in
   `08-milestones.md`.
10. **Say what was not tried.** Native code is compiled by CI and run by a
    person only from a TestFlight build. A pull request says plainly which
    of its parts no person has run on a phone.
11. **No secret in Terraform, in a commit, or in chat.** The owner types
    secret values into `set-secret.sh` or a vendor's form.
12. **When a milestone needs the owner's hands, write the brief first,**
    without being asked (next section).

## The owner brief: how a session hands over a manual step

The owner orchestrates and does not write code. When a step is theirs,
they should not have to ask "how". The session that reaches the step
writes the whole brief, in the pull request's description and in its last
message, and then adds it to `docs/MANUAL_STEPS.md` as the next numbered
step.

**Before writing it, check the vendor's current pages.** Apple's, Google's
and AWS's consoles are renamed more often than this plan is edited. Search
for the current click path; do not write one from memory. If a page could
not be checked, say which.

A brief has these parts, in this order:

1. **What this is for,** in two sentences, and which milestone waits on it.
2. **Before you start:** accounts, roles and sign-ins needed
   (`aws sso login --profile …` by name), what must already be merged or
   deployed, how long it takes, what it costs.
3. **The steps,** numbered, one action each: the exact page (full
   address), the exact button or field name in quotes, the exact value to
   type or where to copy it from. Commands in their own code blocks, one
   per block, each with its profile.
4. **What you should see** after each step that can fail, and at the end:
   one command or one screen that proves it worked.
5. **If it goes wrong:** the two or three likeliest errors, what each
   means, what to do.
6. **How to undo it.**
7. **What never to paste into chat:** which values on these pages are
   secrets, and where each one goes instead.
8. **What to tell the next session:** the non-secret values it needs (an
   ID, a domain, a date), and where they are recorded in the repo.

A session may run the AWS part itself in the owner's signed-in session
when the owner asks (`CLAUDE.md`, "Workflow"). Apple, Google and GitHub
settings pages are always the owner's.

## Starting a session

A prompt that works:

> Build milestone **B3** of `docs/app-plan/`. Read
> `docs/app-plan/README.md` and follow its rules. If the milestone is
> blocked by a decision or an owner step, tell me which and stop.

## Where this plan stops

- The sign-in and onboarding screens: not designed. The plan covers the
  backend for them (D1, `04-api.md`) and leaves the screens to the design.
- Android: after TestFlight works (`docs/ROADMAP.md`, 2e).
- Phases 2 and 3 of recognition (video enrollment, fine-tuning): unchanged
  by this plan, except where the capture flow touches them (D12).
- Anything about how many people will use it. The plan is sized for one
  campus: hundreds to a few thousand accounts. Where a choice stops
  holding beyond that, the file says so.
