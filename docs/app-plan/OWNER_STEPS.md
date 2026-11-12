# What only the owner can do

Every step in the plan that needs the owner's hands: a console Claude
cannot reach, a secret Claude must not see, a judgment that is the
owner's, or a phone.

**For the owner:** you do not need to know how to do any of these. When a
milestone reaches one, the session working on it writes you the full
instructions without being asked (`README.md`, "The owner brief"). If it
did not, tell it: "write the owner brief for O7".

**For a session:** the "The brief must cover" lines below are the minimum
for that step, on top of the eight parts every brief has. Look up the
vendor's current pages before writing; the click paths below are
deliberately not spelled out here, because they change. When the step is
done, record it in `docs/MANUAL_STEPS.md` as the next numbered step and
set its row here to done with the date.

## The list

| ID | Step | Needed before | Where | State |
|---|---|---|---|---|
| O1 | Answer the decisions | F1 (the bold ones) | `DECISIONS.md` | **done 2026-11-12:** all 34 |
| O2 | Freeze the design | E0 | the prototype | |
| O3 | The first production promote | L3 (was: F1) | GitHub, a `v*` tag | **postponed by the owner, 2026-11-12.** Blocks nothing until production is wanted |
| O4 | Apply the guardrail changes | F3 deploys | AWS: staging now, production with its first promote | **staging ready to run:** `docs/MANUAL_STEPS.md`, step 17 |
| O5 | Google: a Gemini API key per account | C1, R0 | Google AI Studio / Cloud | |
| O6 | Google: sign-in open to more than test users | F4 on production | Google Cloud console | |
| O7 | Apple: push | N2 | Apple Developer | |
| O8 | Apple: Sign in with Apple | N6 | Apple Developer, Cognito | |
| O9 | A domain, its DNS, its certificate | buying: now (A6). Wiring: N4 | AWS, the management account, from a codespace | **registered by the owner by hand, 2026-11-12.** No DNS yet, on purpose: N4. Its name and account are found at N4's start (`docs/MANUAL_STEPS.md`, step 16) |
| O10 | Privacy policy, terms, a support address | L1 (draft), L2 (final) | the landing site | |
| O11 | The blocklist and the gold set | C3 | files in the repo | |
| O12 | The campus regions and the feeding spots | nothing: made-up ones until the owner sends them | a file in the repo | later (the owner, 2026-11-12) |
| O13 | Each cat's public text | E4 looks right | the labeling desk | |
| O14 | Translations read by native speakers | E10 | files in the repo | |
| O15 | TestFlight builds and phone checks | every N milestone | GitHub Actions, a phone | |
| O16 | App Store Connect: test information and the reviewer | L2 | App Store Connect | |
| O17 | SMS for phone codes | B5b, only if D5 says so | AWS | |
| O18 | Approve, merge, tag, flip flags | always | GitHub | |
| O19 | The daily desk after launch | L2 onward | the labeling desk | |
| O20 | Photos for the re-rank experiment | R0 | a codespace | |

---

## O1. Answer the decisions

Fill the answer sheet in `DECISIONS.md`. A1–A3, D1, P2, P3 first: they
unblock the foundations. The rest can follow while F1–F4 are built.

Nothing to brief. A session may be asked to explain any decision further;
it should answer with the trade-off, not with a longer recommendation.

## O2. Freeze the design

The prototype was still changing on 2026-11-12 (a description field, a
new-cat form and a "post from +" flow appeared between two reads that
day). Client work copies exact values from it, so it needs a version that
stands still.

Tell a session "the design is frozen at today's version". It then saves
the prototype's source (text only, no cat photos) under
`docs/design/prototype/` with the version id in a `README.md` there, and
every client pull request cites that copy. A later design change is a new
freeze and a pull request that updates the copy, so the difference can be
read.

**The brief must cover:** nothing for you to click. The session reports
the version id it saved and lists every gap from `01-product.md` that the
frozen design still has, as questions.

## O3. The first production promote

`docs/ROADMAP.md` has had it as the next step since 2026-11-10: no `v*`
tag has ever been pushed, and production lacks the alarms and three
fixes. The plan asked for it before the app's work starts, so the first
promote ever is not also the one that carries a new table and two new
Lambdas.

**Postponed by the owner on 2026-11-12:** staging works, production is
fixed later. Nothing in the plan waits for it now. What follows from
that is in `DECISIONS.md`, P2: guardrail changes go to staging only, and
when the promote does come, production's O4 comes first.

**The brief must cover:** which commit carries `deployed/staging` and how
to see that; the tag command; what production's plan should show and what
would be a reason to stop; the confirmation email from AWS for
production's alerts; the post-deploy checks from `docs/deploy.md`.

## O4. Apply the guardrail changes

The plan adds things the walls exist to stop: a second table, a table
stream, an event source mapping, two Lambdas and their roles, wider
Lambda permissions. Each wall is moved by the owner, before the pull
request that needs it can deploy (`infra/main/allowed-resource-types.txt`
says so at its top).

Milestone F1 is a pull request that changes only `infra/bootstrap`,
the allowlist file, and `infra/org` if a new service is needed. What it
holds is in `02-architecture.md`, "What the guardrails must learn". You
apply it to **staging first**, a later milestone proves it there, then to
production.

Claude may run the apply in your signed-in session when you ask
(`CLAUDE.md`, "Workflow").

**The brief must cover:** `aws sso login` with each profile by name
(`bgucats-staging-admin`, `bgucats-prod-admin`, `mgmt-admin` only if
`infra/org` changes); `infra/scripts/bootstrap-apply.sh` and, if needed,
`org-apply.sh`, with the plan shown before the apply; a plain-language
reading of each line of the plan ("the deploy role may now create a
second table named exactly `bgucats-social`"); the proof for each widened
permission and one proof that something *not* widened is still refused;
`aws sso logout` at the end; how to revert (a `git revert` and a second
apply).

## O5. Google: a Gemini API key per account

Moderation and re-ranking call Google's Decisions API. Three keys, kept
apart: staging, production, and one for the research experiment.

Two things matter more than the key itself:

- **Paid tier.** Free-tier requests are used to improve Google's
  products; paid-tier ones are not (pricing page, read 2026-11-12). The
  project must be on billing before a single real photo is sent (M1).
- **A ceiling.** Google's bill is outside the AWS budgets that protect
  this project. Set a budget alert and, if the console offers it, a daily
  request quota.

**The brief must cover:** which Google account owns the projects (the
staging one already exists for sign-in: `bgucats-staging`); turning
billing on and how to confirm the key is on the paid tier; creating the
key and restricting it to the Generative Language API; the budget alert
and the quota, with the numbers from K3; storing each key with
`infra/scripts/set-secret.sh` (the session adds the new secret name to
the script in the same milestone) and the exact command per account; a
one-line test that calls the API with the stored key without printing
it; how to rotate and how to revoke; today's price as the pricing page
shows it. The owner was told $0.75 per million input tokens; the page
read on 2026-11-12 said $0.10. Either is small, but the brief states the
one found that day.

**Never in chat:** the key.

## O6. Google: sign-in open to more than test users

Sign-in goes through a Google OAuth client whose consent screen is in
"Testing", which admits only listed test users (Google caps the list at
100). If D1 opens sign-up, production's client must be published.

**The brief must cover:** where the publishing status is; what Google
asks for at publishing (app name, support email, the privacy policy
address from O10, authorized domains) and whether the scopes this app
uses (`openid`, `email`, `profile`) need Google's verification; what
people see before and after; that staging's client stays in Testing on
purpose; the matching change to the sign-up rule in `infra/main`
(F4) and that it is deployed first.

## O7. Apple: push

**The brief must cover:** turning on the Push Notifications capability
for the App ID `org.arip.bgucats`; creating an APNs authentication key
(`.p8`), noting its Key ID and the Team ID, and that Apple lets it be
downloaded once; storing the key with `set-secret.sh` in each account and
the Key ID as a non-secret setting; which of Apple's two push
environments TestFlight builds use, and that the Lambda is set to match;
starting a new iOS build afterwards (O15), because the entitlement is
part of the signed app; a test notification to your own phone and what
to check if it does not arrive.

**Never in chat:** the `.p8` file's contents.

## O8. Apple: Sign in with Apple

Only if D1 says so, and before the first external build.

**The brief must cover:** the capability on the App ID; the Services ID,
its return address (Cognito's, from the Terraform output) and the key;
adding Apple as an identity provider to the user pool with
`set-secret.sh` (Terraform only names it, as with Google); what an
account with a hidden email looks like to the app and what D1 said about
it; trying it on a phone.

## O9. A domain, its DNS, its certificate

A6, answered 2026-11-12: the owner buys the domain now, **through AWS**,
with Claude doing the work in the owner's signed-in session.

**The buying half is written and ready:** `docs/MANUAL_STEPS.md`, step
16, and `infra/scripts/domain.sh`. In short:

- It is bought in the **management account**. No service control policy
  applies there, so nothing is unblocked, and `route53domains` stays
  denied in production and staging. A member account's budget would also
  count the purchase, and a domain costs about what the $20 freeze line
  is.
- It is run from a **codespace**. A cloud session has no AWS sign-in.
- You sign in (`mgmt-admin`), fill a contact file that stays outside the
  repo and out of chat, and ask Claude to check the name and then to buy
  it up to a price you name. You click one link in an email from AWS.
- Route 53 can point the bare domain at CloudFront, so the worry about a
  registrar's DNS does not arise.

The other half, the brief below, is written when N4 is reached: the
certificate, the DNS records, Apple's file, the allowed addresses. That
half needs `acm` on the organization's allowlist for the member accounts.

**The N4 brief must cover:** that `.app` addresses work over HTTPS only;
the `infra/org` change that adds `acm` to the allowlist and its apply
(O4's routine, management account); where the DNS records live (the
hosted zone Route 53 made in the management account, managed from
`infra/org`, or a zone in production that the domain is pointed at:
decided in N4, with the reasons) and what that needs opened; the
certificate request and the DNS records that validate it; the records
that point the name at the two CloudFront distributions, including the
bare domain; the file Apple reads for universal links
(`/.well-known/apple-app-site-association`) and how to check it is
served as JSON with no redirect; Cognito's and Google's lists of allowed
addresses; the new addresses for posters and QR codes.

## O10. Privacy policy, terms, a support address

Apple requires a privacy policy address for TestFlight's external
testing and for the store; Google asks for it when the sign-in client is
published; people are owed it regardless. A session drafts; you read,
change and own the text. It is not legal advice, and a lawyer or the
university's privacy officer reading it once is worth the hour.

The draft must say, truthfully, what the code does: what is collected
(Google account email and name, photos, their time and a location rounded
to about 100 m, a phone number if D5 ships it), who can see what
(friends, everyone, admins), that text and photos are sent to Google for
checking (M1) and, if K1 says so, at scan time; what deletion removes and
what it keeps (D14); the extra frames if D12 is on; how to reach a
person.

**The brief must cover:** the drafts as files under `site/` in a pull
request; a list of every sentence that is a promise about behaviour, each
with the file and line of the code that keeps it; the questions only you
can answer (legal name of the operator, contact address, minimum age,
which country's law); where the addresses go (App Store Connect, Google's
consent screen, the app's profile screen).

## O11. The blocklist and the gold set

Two files only people who speak the languages can write.

- **The blocklist:** words and names that are refused at once, in Hebrew,
  Arabic, Russian and English, including common ways of writing them in
  Latin letters. Small, readable, in the repo.
- **The gold set:** about 200 short names and 100 post texts, each marked
  acceptable or not and why, across the four languages, with the hard
  cases on purpose: an ordinary cat name that looks like a rude word, a
  real person's full name, a political slogan, a nickname a campus would
  understand and a model would not.

The gold set is what turns "the model says 0.3" into a threshold
(`06-moderation.md`). Without it, enforce mode is a guess.

**The brief must cover:** the two file formats with examples; that the
files hold offensive words on purpose and how the repo marks them; who
could help for each language; the command that scores the gold set and
how to read its table; that names of real private people must not be
used as examples.

## O12. The campus regions and the feeding spots

The map, "usually near…", the new-cat form's "where does it hang out"
and a post's area all use five named places: Building 96 · Engineering,
Aranne Library, Student Union, Dorms, Sports lawn, plus "somewhere else".

Since D10 (2026-11-12) the same file also holds the campus's **feeding
spots**, which only the owner knows: where each one is and what people
call it. They go on the map so people know where to feed.

**The brief must cover:** the regions file's format; for each region a
name in each language and a centre and radius (or outline) in
coordinates; for each feeding spot a name in each language and its
place, and the easiest way to collect those (standing at each spot with
the phone, or dropping pins on a map and sending the list); how to check
a region by standing in it with the app; what happens to a photo taken
outside all of them; whether five is the right list of regions.

## O13. Each cat's public text

A cat's page shows a short description and where it usually is. Those are
written by an admin in the desk (the fields arrive with B2). Until they
are filled, the page shows only the photos and the poll.

**The brief must cover:** where in the desk; the length limit; that this
text is public; that the description is not moderated by the model
because an admin wrote it.

## O14. Translations

A session drafts Hebrew, Russian and Arabic from the English strings. A
native speaker reads them on a phone, in the app, before that language is
offered.

**The brief must cover:** the strings file; a build or the local app
switched to each language; the screens most likely to break when text
runs right to left; how to send corrections (edit the file, or dictate
them to a session).

## O15. TestFlight builds and phone checks

Only you start an iOS build (*Actions* → *iOS* → *Run workflow*, from
`main`), and only a phone shows whether native code works: the camera,
push, contacts, the share sheet, links that open the app. This is the
slow loop (20–30 minutes a try), so each native milestone comes with a
checklist to run once.

**The brief must cover:** that the change is merged and staging has
deployed; starting the build and what it costs; when the build appears in
TestFlight; a numbered checklist of things to do on the phone and what
each should show; what to send back if one fails (a screenshot, the time,
the build number); which parts of the milestone no person has run until
this check.

## O16. App Store Connect: test information and the reviewer

For external testing.

**The brief must cover:** the beta description and "what to test"; the
feedback email; the privacy policy address; the age rating questionnaire
with the answers that follow from the app having user content (D16); the
App Privacy answers, as a table of each kind of data, whether it is
linked to the person, and why, taken from the code; export compliance;
**a login the reviewer can use**: an account that does not need a BGU
address or a second factor, what it can see, and how to disable it after;
the review notes that explain where Report, Block and Delete account
are; creating the external group and the public link; what a rejection
looks like and the usual reasons.

## O17. SMS for phone codes

Only if D5 chooses a code by SMS.

**The brief must cover:** the price of one message to an Israeli number
today; the account's SMS spending limit and that raising it is a quota
request the organization's policy denies until `infra/org` allows it;
whether Israel requires a registered sender name; the monthly cost at
100, 1,000 and 5,000 sign-ups; the alternative of Cognito's own phone
verification.

## O18. Approve, merge, tag, flip flags

As today: you approve and merge every pull request and push every `v*`
tag. New with this plan: flags.

Each feature's flag is a setting per account in `infra/main` (off in
production until L3). Turning one on is a one-line pull request you
merge and promote like any other. `moderation_mode` and `rerank_mode`
have three positions each; the files `06-moderation.md` and
`07-rerank.md` say what evidence each move needs, and the pull request
that proposes a move must show that evidence.

## O19. The daily desk after launch

Once strangers can post, the desk gains three queues beside labeling:
**moderation** (what the model flagged or could not check),
**reports** (what people reported: Apple expects action within 24
hours), **proposals** (new cats to approve or merge). An email arrives
for each new report through the existing alerts topic.

**The brief must cover** (at L2): how long each queue takes at the
expected volume; who else is an admin and can cover; what the app does
if nobody looks for two days (flagged content stays hidden; nothing
unchecked becomes public).

## O20. Photos for the re-rank experiment

The experiment (R0) needs labeled BGU sessions on a disk and a Gemini
key. A cloud session has neither AWS nor your key.

**The brief must cover:** in a codespace, signing in read-only
(`bgucats-prod-ro`) and exporting the labeled sessions to a local folder
that is in `.gitignore`; setting the research key in the shell without it
entering the history; the one command that runs the experiment and
roughly what it will cost; where the result lands and which numbers to
bring back; deleting the photos from the codespace afterwards.
